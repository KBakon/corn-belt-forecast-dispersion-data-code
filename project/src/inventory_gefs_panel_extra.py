"""Inventory NASS panel cycles outside fixed ISO 13–26 GEFS scaling frame."""

import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta

import pandas as pd

from inventory_gefs import CONFIG, ROOT, one


def main():
    panel = pd.read_parquet(ROOT / "interim" / "nass_state_weeks.parquet")
    sundays = sorted(set(panel["week_ending_sunday"].dt.date))
    outside = [sunday for sunday in sundays if not 13 <= sunday.isocalendar().week <= 26]
    items = [(sunday, (sunday-timedelta(days=6)).strftime("%Y%m%d00"), member)
             for sunday in outside for member in CONFIG["gefs_primary_members"]]
    rows = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        for future in as_completed([pool.submit(one, item) for item in items]):
            rows.append(future.result())
    rows.sort(key=lambda row: (row["target_sunday"], row["member"]))
    path = ROOT / "raw" / "gefs_panel_extra_inventory.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print("Panel-only extra GEFS objects available:", sum(row["status_code"] == 200 for row in rows),
          "of", len(rows))


if __name__ == "__main__":
    main()
