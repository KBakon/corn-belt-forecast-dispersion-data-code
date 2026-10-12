"""Inventory hourly CMR granules for frozen NASS state-weeks, no data download."""

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import earthaccess
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
COLLECTIONS = {
    "NLDAS_FORA0125_H": "C2033151148-GES_DISC",
    "NLDAS_NOAH0125_H": "C2069246977-GES_DISC",
}
FIELDS = ("collection_short_name", "collection_version", "collection_concept_id", "granule_ur",
          "hour_utc", "get_data_url", "reported_size_mb", "checksum_algorithm", "checksum_value")


def inventory_one(name, concept, start, end):
    granules = earthaccess.search_data(
        short_name=name, version="2.0",
        temporal=(start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")),
        count=200,
    )
    output = {}
    for granule in granules:
        umm = granule["umm"]
        beginning = umm["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"]
        hour = datetime.fromisoformat(beginning.replace("Z", "+00:00"))
        if not (start <= hour < end):
            continue
        urls = [entry["URL"] for entry in umm.get("RelatedUrls", [])
                if entry.get("Type") == "GET DATA" and entry.get("URL", "").startswith("https://")]
        if len(urls) != 1:
            raise ValueError(f"Ambiguous GET DATA URL for {name} {hour}")
        checksums = umm.get("DataGranule", {}).get("ArchiveAndDistributionInformation", [])
        checksums = [entry.get("Checksum", {}) for entry in checksums if entry.get("Checksum")]
        if hour in output:
            raise ValueError(f"Duplicate CMR hour for {name} {hour}")
        output[hour] = {
            "collection_short_name": name,
            "collection_version": "2.0",
            "collection_concept_id": concept,
            "granule_ur": umm["GranuleUR"],
            "hour_utc": hour.isoformat(),
            "get_data_url": urls[0],
            "reported_size_mb": next((entry.get("Size") for entry in umm.get("DataGranule", {}).get("ArchiveAndDistributionInformation", [])), ""),
            "checksum_algorithm": checksums[0].get("Algorithm", "") if checksums else "",
            "checksum_value": checksums[0].get("Value", "") if checksums else "",
        }
    return output


def main():
    auth = earthaccess.login(strategy="netrc", persist=False)
    if not auth.authenticated:
        raise RuntimeError("Earthdata netrc authentication failed")
    panel = pd.read_parquet(ROOT / "interim" / "nass_state_weeks.parquet")
    starts = sorted(set((panel["week_ending_sunday"] - pd.Timedelta(days=6)).dt.to_pydatetime()))
    target = ROOT / "raw" / "nldas_object_manifest.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    summary = {"created_utc": datetime.now(timezone.utc).isoformat(), "weeks": len(starts),
               "expected_hours_per_collection": len(starts)*168, "collections": {}}
    with target.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for name, concept in COLLECTIONS.items():
            hours = {}
            for index, naive_start in enumerate(starts, 1):
                start = naive_start.replace(tzinfo=timezone.utc)
                end = start + timedelta(hours=168)
                found = inventory_one(name, concept, start, end)
                hours.update(found)
                if index % 20 == 0:
                    print(name, index, "of", len(starts), "weeks inventoried", flush=True)
            for hour in sorted(hours):
                row = hours[hour]
                if row["get_data_url"] in seen:
                    raise ValueError("Duplicate NLDAS object URL")
                seen.add(row["get_data_url"])
                writer.writerow(row)
            summary["collections"][name] = {"hours_found": len(hours),
                                               "hours_expected": len(starts)*168}
            stream.flush()
    log = ROOT / "logs" / "nldas_inventory.json"
    log.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
