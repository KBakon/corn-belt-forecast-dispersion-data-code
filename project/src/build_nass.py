"""Build the frozen outcome-side state-week extract without forecast joins."""

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "frozen_design.json").read_text())
PLANTED_ITEM = "CORN - PROGRESS, MEASURED IN PCT PLANTED"
DSFW_ITEM = "FIELDWORK - DAYS SUITABLE, MEASURED IN DAYS / WEEK"
EXPORTS = {
    "planted_2000_2019_17states.csv": "AC5449A8-F34C-3468-B44C-DE625A980396",
    "planted_2000_2004.csv": "63E1842B-C9D7-3477-88B4-A21DC781A489",
    "planted_2005_2009.csv": "C39EA166-C4D7-3565-8525-791531F4E4B9",
    "planted_2010_2014.csv": "652EC217-BB79-36F2-8534-D8AED9AECC02",
    "planted_2015_2019.csv": "89F14B7B-FD6D-3F03-8DE2-D09842B4D39D",
    "dsfw_2000_2019_17states.csv": "DA9D916A-DC67-32FF-BA94-85749833E019",
}


def load_export(filename, item):
    path = ROOT / "raw" / "nass" / filename
    frame = pd.read_csv(path, dtype={"State ANSI": str, "Year": int, "Value": str})
    if set(frame["Data Item"]) != {item}:
        raise ValueError(f"Unexpected NASS Data Item in {filename}")
    if set(frame["Program"]) != {"SURVEY"} or set(frame["Geo Level"]) != {"STATE"}:
        raise ValueError(f"Unexpected NASS program/geography in {filename}")
    if set(frame["Domain"]) != {"TOTAL"}:
        raise ValueError(f"Unexpected NASS domain in {filename}")
    frame["week_ending_sunday"] = pd.to_datetime(frame["Week Ending"], errors="raise")
    if not frame["week_ending_sunday"].dt.dayofweek.eq(6).all():
        raise ValueError(f"Non-Sunday NASS date in {filename}")
    # Quick Stats labels the reporting crop year; a week-ending Sunday can
    # fall in early January of the next calendar year (week 52/53).
    if not frame["State ANSI"].str.zfill(2).isin(CONFIG["state_fips"].values()).all():
        raise ValueError(f"State outside frozen frame in {filename}")
    frame["value"] = pd.to_numeric(frame["Value"], errors="raise")
    if frame.duplicated(["State ANSI", "week_ending_sunday"]).any():
        raise ValueError(f"Duplicate NASS state-week in {filename}")
    return frame


def append_provenance():
    target = ROOT / "provenance" / "source_manifest.csv"
    with target.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    seen = {row["source_url"] for row in rows}
    for filename, export_id in EXPORTS.items():
        url = f"https://quickstats.nass.usda.gov/data/spreadsheet/{export_id}.csv"
        if url in seen:
            continue
        path = ROOT / "raw" / "nass" / filename
        rows.append({
            "source": "USDA NASS Quick Stats",
            "version": "SURVEY current historical extract 2026-10-06",
            "source_url": url,
            "object_key": export_id,
            "local_path": str(path),
            "retrieved_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            "byte_size": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "access_note": "Quick Stats interactive query, state-level, exact data item, fixed 17 states and years; raw CSV snapshot",
            "first_consumer": "src/build_nass.py",
        })
    with target.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    planted = pd.concat([load_export(name, PLANTED_ITEM) for name in EXPORTS
                         if name.startswith("planted_") and name != "planted_2000_2019_17states.csv"], ignore_index=True)
    dsfw = load_export("dsfw_2000_2019_17states.csv", DSFW_ITEM)
    key = ["State ANSI", "week_ending_sunday"]
    if planted.duplicated(key).any():
        raise ValueError("Duplicate planted state-week across export chunks")
    states = {fips: postal for postal, fips in CONFIG["state_fips"].items()}
    frame = planted[["State ANSI", "State", "Year", "week_ending_sunday", "value"]].rename(columns={
        "State ANSI": "state_fips", "State": "state_name", "Year": "crop_year", "value": "planting_cumulative_pct"})
    frame["state_fips"] = frame["state_fips"].str.zfill(2)
    frame["state_postal"] = frame["state_fips"].map(states)
    work = dsfw[["State ANSI", "week_ending_sunday", "value"]].rename(columns={
        "State ANSI": "state_fips", "value": "dsfw_days"})
    work["state_fips"] = work["state_fips"].str.zfill(2)
    frame = frame.merge(work, on=["state_fips", "week_ending_sunday"], how="left", validate="one_to_one")
    previous = frame[["state_fips", "week_ending_sunday", "planting_cumulative_pct"]].copy()
    previous["week_ending_sunday"] += pd.Timedelta(days=7)
    previous = previous.rename(columns={"planting_cumulative_pct": "planting_previous_pct"})
    frame = frame.merge(previous, on=["state_fips", "week_ending_sunday"], how="left", validate="one_to_one")
    frame["planting_increment_pp"] = frame["planting_cumulative_pct"] - frame["planting_previous_pct"]
    frame["remaining_start_pp"] = 100 - frame["planting_previous_pct"]
    frame["seasonal_week"] = frame["week_ending_sunday"].dt.isocalendar().week.astype(int)
    frame["active_week_flag"] = frame["planting_previous_pct"].ge(5) & frame["planting_previous_pct"].lt(95)
    frame["increment_valid_flag"] = frame["planting_increment_pp"].ge(0)
    frame["dsfw_zero_flag"] = frame["dsfw_days"].eq(0)
    valid = frame["increment_valid_flag"] & frame["dsfw_days"].gt(0)
    frame["planting_utilization_pp_per_suitable_day"] = (frame["planting_increment_pp"] / frame["dsfw_days"]).where(valid)
    if not frame["planting_cumulative_pct"].between(0, 100).all():
        raise ValueError("NASS planted progress out of range")
    if not work["dsfw_days"].between(0, 7).all():
        raise ValueError("NASS DSFW out of range")
    frame = frame.sort_values(["state_fips", "week_ending_sunday"])
    output = ROOT / "interim" / "nass_state_weeks.parquet"
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(output, index=False)
    metrics = {
        "planted_rows": len(planted), "dsfw_rows": len(dsfw),
        "nass_panel_rows": len(frame), "states": frame["state_fips"].nunique(),
        "years": frame["crop_year"].nunique(),
        "active_rows": int(frame["active_week_flag"].sum()),
        "active_with_dsfw_rows": int((frame["active_week_flag"] & frame["dsfw_days"].notna()).sum()),
        "negative_increment_rows": int(frame["planting_increment_pp"].lt(0).sum()),
        "zero_dsfw_with_nonzero_increment_rows": int((frame["dsfw_zero_flag"] & frame["planting_increment_pp"].notna() & frame["planting_increment_pp"].ne(0)).sum()),
        "missing_previous_rows": int(frame["planting_previous_pct"].isna().sum()),
        "missing_dsfw_rows": int(frame["dsfw_days"].isna().sum()),
    }
    (ROOT / "logs" / "nass_build_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    append_provenance()
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
