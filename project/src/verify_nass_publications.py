"""Fixed-seed NASS Quick Stats spot check against historical USDA Crop Progress text."""

import csv
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from build_nass import ROOT, EXPORTS, PLANTED_ITEM, DSFW_ITEM


REPORTS = {
    2000: ("2000-05-08", "https://esmis.nal.usda.gov/sites/default/release-files/8336h188j/vd66w130j/pv63g1800/CropProg-05-08-2000.txt"),
    2005: ("2005-05-02", "https://esmis.nal.usda.gov/sites/default/release-files/8336h188j/k643b259n/rn301298b/CropProg-05-02-2005.txt"),
    2010: ("2010-05-17", "https://esmis.nal.usda.gov/sites/default/release-files/8336h188j/d791sh59q/w3763844w/CropProg-05-17-2010.txt"),
    2015: ("2015-05-04", "https://esmis.nal.usda.gov/sites/default/release-files/8336h188j/8c97kr860/5425kc529/CropProg-05-04-2015.txt"),
    2019: ("2019-05-13", "https://esmis.nal.usda.gov/sites/default/release-files/8336h188j/qn59qd37j/w0892k986/prog2019.txt"),
}
SAMPLE_SEED = 1062026
STATES = {"IL": "Illinois", "PA": "Pennsylvania", "IN": "Indiana",
          "KY": "Kentucky", "MN": "Minnesota"}


def report_value(text, year, state, kind):
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if year < 2015:
        if kind != "planted":
            return None
        marker = "Corn:  Percent Planted,"
        state_label = state
        current_column = 0
    else:
        marker = ("Corn Planted - Selected States" if kind == "planted"
                  else "Days Suitable for Fieldwork - Selected States")
        state_label = STATES[state]
        current_column = 2
    start = normalized.find(marker)
    if start < 0:
        raise ValueError(f"Historical publication table missing: {year}:{kind}")
    block = normalized[start:start+5000]
    line = next((line for line in block.splitlines() if
                 re.match(r"^"+re.escape(state_label)+r"\s*(?:\.*):", line)), None)
    if line is None:
        raise ValueError(f"Historical publication state row missing: {year}:{state}:{kind}")
    numbers = re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?", line.split(":", 1)[1])
    if len(numbers) <= current_column:
        raise ValueError(f"Historical publication state row has insufficient values: {year}:{state}:{kind}")
    return float(numbers[current_column]), line.strip()


def audit_raw_exports():
    rows = []
    for filename, export_id in EXPORTS.items():
        path = ROOT / "raw" / "nass" / filename
        frame = pd.read_csv(path, dtype=str)
        rows.append({"filename": filename, "export_id": export_id,
                     "source_url": f"https://quickstats.nass.usda.gov/data/spreadsheet/{export_id}.csv",
                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "byte_size": path.stat().st_size, "columns_in_order": list(frame.columns),
                     "row_count": len(frame),
                     "data_items": sorted(frame["Data Item"].dropna().unique().tolist()),
                     "programs": sorted(frame["Program"].dropna().unique().tolist()),
                     "geo_levels": sorted(frame["Geo Level"].dropna().unique().tolist()),
                     "domains": sorted(frame["Domain"].dropna().unique().tolist()),
                     "years": [int(frame.Year.astype(int).min()), int(frame.Year.astype(int).max())],
                     "state_fips": sorted(frame["State ANSI"].str.zfill(2).dropna().unique().tolist())})
    descriptor = {"retrieval_route": "USDA NASS Quick Stats interactive state-level CSV export",
                  "query_series": [PLANTED_ITEM, DSFW_ITEM],
                  "filters": {"program": "SURVEY", "geo_level": "STATE", "domain": "TOTAL",
                              "years": "2000-2019", "week_ending": "Sunday",
                              "state_fips": sorted(rows[0]["state_fips"])},
                  "raw_exports": rows, "selection_rule": "fixed 17-state corn panel; preserve retrieved revisions"}
    (ROOT / "logs" / "nass_query_schema_descriptors.json").write_text(json.dumps(descriptor, indent=2), encoding="utf-8")
    return descriptor


def main():
    audit_raw_exports()
    frame = pd.read_parquet(ROOT / "interim" / "nass_state_weeks.parquet")
    rng = np.random.default_rng(SAMPLE_SEED)
    selected = []
    for year in REPORTS:
        eligible = frame[(frame.crop_year.eq(year)) & frame.seasonal_week.between(15, 22)
                         & frame.planting_cumulative_pct.notna()]
        selected.append(eligible.iloc[int(rng.integers(len(eligible)))])
    if [(int(row.crop_year), row.state_postal) for row in selected] != [
            (2000, "IL"), (2005, "PA"), (2010, "IN"), (2015, "KY"), (2019, "MN")]:
        raise ValueError("Fixed NASS random sample changed")
    results = []
    for row in selected:
        year = int(row.crop_year)
        release_date, url = REPORTS[year]
        path = ROOT / "raw" / "nass_publication_samples" / f"crop_progress_{release_date}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            path.write_bytes(response.content)
        text = path.read_text(encoding="utf-8", errors="replace")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        planted, planted_line = report_value(text, year, row.state_postal, "planted")
        if year >= 2015:
            dsfw, dsfw_line = report_value(text, year, row.state_postal, "dsfw")
        else:
            dsfw, dsfw_line = None, "not listed in this national edition"
        results.append({"seed": SAMPLE_SEED, "crop_year": year, "state_postal": row.state_postal,
                        "week_ending_sunday": row.week_ending_sunday.date().isoformat(),
                        "release_date": release_date, "publication_url": url,
                        "publication_path": str(path), "publication_sha256": sha,
                        "quick_stats_planted_pct": float(row.planting_cumulative_pct),
                        "publication_planted_pct": planted,
                        "planted_equal": bool(planted == row.planting_cumulative_pct),
                        "publication_planted_line": planted_line,
                        "quick_stats_dsfw_days": float(row.dsfw_days),
                        "publication_dsfw_days": dsfw,
                        "dsfw_equal_if_published": None if dsfw is None else bool(dsfw == row.dsfw_days),
                        "publication_dsfw_line": dsfw_line})
    target = ROOT / "logs" / "nass_historical_publication_spotcheck.csv"
    with target.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(results[0]))
        writer.writeheader(); writer.writerows(results)
    if not all(r["planted_equal"] and r["dsfw_equal_if_published"] is not False for r in results):
        raise ValueError("NASS Quick Stats random spot check differs from historical publication")
    print(f"NASS historical publication checks: {len(results)} planted and "
          f"{sum(r['publication_dsfw_days'] is not None for r in results)} DSFW exact matches", flush=True)


if __name__ == "__main__":
    main()
