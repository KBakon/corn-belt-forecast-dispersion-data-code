"""Inventory frozen Monday GEFS objects for the fixed ISO 13–26 scaling frame.

This is an outcome-blind object inventory, not a substitute for GRIB decoding.
"""

import csv
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "frozen_design.json").read_text(encoding="utf-8"))
BASE = "https://noaa-gefs-retrospective.s3.amazonaws.com/GEFSv12/reforecast"


def one(item):
    target_sunday, cycle, member = item
    filename = f"apcp_sfc_{cycle}_{member}.grib2"
    key = f"GEFSv12/reforecast/{cycle[:4]}/{cycle}/{member}/Days:1-10/{filename}"
    url = f"{BASE}/{cycle[:4]}/{cycle}/{member}/Days%3A1-10/{filename}"
    result = {
        "target_sunday": target_sunday.isoformat(),
        "archive_cycle": cycle,
        "member": member,
        "object_key": key,
        "source_url": url,
        "status_code": None,
        "content_length": None,
        "etag": None,
        "last_modified": None,
        "checked_utc": None,
        "error": None,
    }
    for attempt in range(3):
        try:
            response = requests.head(url, timeout=30, allow_redirects=True)
            result.update({
                "status_code": response.status_code,
                "content_length": response.headers.get("Content-Length"),
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
                "checked_utc": datetime.now(timezone.utc).isoformat(),
            })
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                continue
            break
        except requests.RequestException as error:
            result["error"] = type(error).__name__
            if attempt == 2:
                result["checked_utc"] = datetime.now(timezone.utc).isoformat()
    return result


def main():
    items = []
    for year in range(CONFIG["study_year_start"], CONFIG["study_year_end"] + 1):
        for week in range(13, 27):
            sunday = date.fromisocalendar(year, week, 7)
            cycle = (sunday - timedelta(days=6)).strftime("%Y%m%d00")
            for member in CONFIG["gefs_primary_members"]:
                items.append((sunday, cycle, member))
    rows = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(one, item) for item in items]
        for future in as_completed(futures):
            rows.append(future.result())
    rows.sort(key=lambda row: (row["target_sunday"], row["member"]))
    target = ROOT / "raw" / "gefs_object_manifest_iso13_26.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    success = sum(row["status_code"] == 200 for row in rows)
    print(f"GEFS object inventory: {success}/{len(rows)} HTTP 200; output={target}")


if __name__ == "__main__":
    main()
