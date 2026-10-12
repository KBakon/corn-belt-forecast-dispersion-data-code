"""Decode representative GEFS GRIB metadata before any bulk feature construction."""

import csv
import os
from collections import Counter
from pathlib import Path

import eccodes


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw" / "gefs_metadata_audit"


def get(handle, key):
    try:
        return eccodes.codes_get(handle, key)
    except eccodes.CodesInternalError:
        return None


def decode(path: Path):
    rows = []
    with path.open("rb") as stream:
        while (handle := eccodes.codes_grib_new_from_file(stream)) is not None:
            try:
                start, end = int(get(handle, "startStep")), int(get(handle, "endStep"))
                rows.append({
                    "archive_key": f"GEFSv12/reforecast/{path.name[9:13]}/{path.name[9:19]}/c00/Days:1-10/{path.name}",
                    "member": "c00",
                    "dataDate": get(handle, "dataDate"),
                    "dataTime": get(handle, "dataTime"),
                    "reference_time_utc": f"{get(handle, 'dataDate')}T{int(get(handle, 'dataTime')):04d}Z",
                    "startStep": start,
                    "endStep": end,
                    "stepRange": get(handle, "stepRange"),
                    "validityDate": get(handle, "validityDate"),
                    "validityTime": get(handle, "validityTime"),
                    "gridType": get(handle, "gridType"),
                    "Ni": get(handle, "Ni"),
                    "Nj": get(handle, "Nj"),
                    "iDirectionIncrementInDegrees": get(handle, "iDirectionIncrementInDegrees"),
                    "jDirectionIncrementInDegrees": get(handle, "jDirectionIncrementInDegrees"),
                    "units": get(handle, "units"),
                    "shortName": get(handle, "shortName"),
                    "member_number": get(handle, "number"),
                })
            finally:
                eccodes.codes_release(handle)
    return rows


def tile(rows):
    # Metadata-only audit: choose the widest available interval from each
    # current forecast hour. This implements the frozen 6-h preference.
    selected = []
    cursor = 0
    while cursor < 168:
        candidates = [r for r in rows if r["startStep"] == cursor and cursor < r["endStep"] <= 168]
        if not candidates:
            raise ValueError(f"accumulation gap at hour {cursor}")
        candidate = max(candidates, key=lambda r: r["endStep"])
        if sum(r["endStep"] == candidate["endStep"] for r in candidates) > 1:
            raise ValueError(f"duplicated accumulation window {cursor}-{candidate['endStep']}")
        selected.append(candidate)
        cursor = candidate["endStep"]
    assert selected[0]["startStep"] == 0 and selected[-1]["endStep"] == 168
    return selected


def main():
    all_rows = []
    for path in sorted(RAW.glob("*.grib2")):
        rows = decode(path)
        selected = tile(rows)
        print(path.name, "messages", len(rows), "selected", len(selected),
              "reference_times", sorted(set(r["reference_time_utc"] for r in rows)),
              "durations", dict(Counter(r["endStep"] - r["startStep"] for r in selected)))
        selected_keys = {(r["startStep"], r["endStep"]) for r in selected}
        for row in rows:
            row["selected_for_0_168_tile"] = (row["startStep"], row["endStep"]) in selected_keys
        all_rows.extend(rows)
    target = ROOT / "logs" / "gefs_grib_metadata_audit.csv"
    with target.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(all_rows[0]))
        writer.writeheader()
        writer.writerows(all_rows)


if __name__ == "__main__":
    main()
