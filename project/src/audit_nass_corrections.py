"""Snapshot USDA correction logs and flag Crop Progress/DSFW hits in sample years."""

import csv
import hashlib
import html
import re
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
PAGES = {"ASB": "https://www.nass.usda.gov/Corrections/index.php",
         "Quick Stats": "https://www.nass.usda.gov/Corrections/index.php?log=QS"}


def clean(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def main():
    rows = []
    for log_type, url in PAGES.items():
        path = ROOT / "raw" / "nass" / f"corrections_{log_type.lower().replace(' ', '_')}_2026-10-06.html"
        if not path.exists():
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            path.write_bytes(response.content)
        source_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        source = path.read_text(encoding="utf-8", errors="replace")
        for table_row in re.findall(r"<tr\b[^>]*>[\s\S]*?</tr>", source, re.I):
            cells = re.findall(r"<(?:th|td)\b[^>]*>([\s\S]*?)</(?:th|td)>", table_row, re.I)
            values = [clean(cell) for cell in cells]
            if not values or "Crop Progress" not in values[0]:
                continue
            joined = " | ".join(values)
            if not re.search(r"\b(?:200\d|201\d)\b", joined):
                continue
            relevant = bool(re.search(r"corn|days suitable|fieldwork|plant", joined, re.I))
            rows.append({"log_type": log_type, "source_url": url, "snapshot_path": str(path),
                         "snapshot_sha256": source_sha, "report": values[0],
                         "report_date_or_series": values[1] if len(values) > 1 else "",
                         "correction_text": values[2] if len(values) > 2 else "",
                         "correction_date": values[3] if len(values) > 3 else "",
                         "mentions_corn_planting_or_dsfw": relevant})
    target = ROOT / "logs" / "nass_correction_log_hits.csv"
    with target.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    print(f"Crop Progress correction-log hits, 2000-2019: {len(rows)}; corn/DSFW mentions: "
          f"{sum(r['mentions_corn_planting_or_dsfw'] for r in rows)}", flush=True)


if __name__ == "__main__":
    main()
