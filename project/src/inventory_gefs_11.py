"""Inventory Wednesday 11-member GEFS cycles for outcome-blind sensitivity QA."""

import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

from inventory_gefs import CONFIG, ROOT, one


def main():
    items = []
    for year in range(CONFIG["study_year_start"], CONFIG["study_year_end"]+1):
        for week in range(13, 27):
            wednesday = date.fromisocalendar(year, week, 3)
            cycle = wednesday.strftime("%Y%m%d00")
            for member in ("c00", *(f"p{number:02d}" for number in range(1, 11))):
                items.append((wednesday, cycle, member))
    rows = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(one, item) for item in items]
        for future in as_completed(futures):
            rows.append(future.result())
    rows.sort(key=lambda item: (item["target_sunday"], item["member"]))
    path = ROOT / "raw" / "gefs_11member_wednesday_inventory.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print("Wednesday 11-member GEFS objects available:", sum(row["status_code"] == 200 for row in rows),
          "of", len(rows))


if __name__ == "__main__":
    main()
