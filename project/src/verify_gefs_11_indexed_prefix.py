"""Verify source-indexed 0–168 h GRIB prefix against one full Wednesday object."""

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

from build_gefs_features import ROOT, load_weights, member_totals


def prefix_end(index_text, expected_size):
    lines = index_text.splitlines()
    entries = []
    for line in lines:
        match = re.match(r"^(\d+):(\d+):.*:APCP:surface:([0-9]+)-([0-9]+) hour acc fcst:", line)
        if not match:
            raise ValueError(f"Unexpected GEFS precipitation index syntax: {line[:100]}")
        entries.append(tuple(map(int, match.groups())))
    positions = [i for i, (_, _, start, end) in enumerate(entries) if start == 162 and end == 168]
    if len(positions) != 1 or positions[0]+1 >= len(entries):
        raise ValueError("GEFS index lacks a unique 162–168 h message with a successor")
    first_after = entries[positions[0]+1]
    if first_after[2] != 168 or first_after[3] != 171:
        raise ValueError("GEFS index message following 162–168 h is unexpected")
    end = first_after[1]
    if not 0 < end < expected_size:
        raise ValueError("GEFS indexed prefix byte count is outside source object")
    return end


def main():
    with (ROOT / "raw" / "gefs_11member_wednesday_inventory.csv").open(newline="", encoding="utf-8") as stream:
        row = next(csv.DictReader(stream))
    url = row["source_url"]
    index_response = requests.get(url + ".idx", timeout=30)
    index_response.raise_for_status()
    end = prefix_end(index_response.text, int(row["content_length"]))
    range_response = requests.get(url, headers={"Range": f"bytes=0-{end-1}"}, timeout=120)
    range_response.raise_for_status()
    if range_response.status_code != 206 or len(range_response.content) != end:
        raise ValueError("NOAA source did not honor indexed byte range")
    full_response = requests.get(url, timeout=180)
    full_response.raise_for_status()
    if len(full_response.content) != int(row["content_length"]):
        raise ValueError("Full NOAA object byte count differs from inventory")
    if not full_response.content.startswith(range_response.content):
        raise ValueError("Indexed prefix differs from full NOAA source object")
    scratch = ROOT / "tmp"
    scratch.mkdir(exist_ok=True)
    full_path = scratch / "gefs_11_index_audit_full.grib2"
    prefix_path = scratch / "gefs_11_index_audit_prefix.grib2"
    full_path.write_bytes(full_response.content)
    prefix_path.write_bytes(range_response.content)
    try:
        unique, mapped = load_weights()
        full_time, full_totals = member_totals(full_path, row["archive_cycle"], row["member"], unique, mapped)
        prefix_time, prefix_totals = member_totals(prefix_path, row["archive_cycle"], row["member"], unique, mapped)
        if full_time != prefix_time or any(full_totals[state] != prefix_totals[state] for state in full_totals):
            raise ValueError("Indexed GRIB prefix changed a decoded state precipitation total")
    finally:
        full_path.unlink(missing_ok=True)
        prefix_path.unlink(missing_ok=True)
    record = {"verified_utc": datetime.now(timezone.utc).isoformat(),
              "source_url": url, "source_object_key": row["object_key"],
              "source_object_bytes": len(full_response.content),
              "source_object_sha256": hashlib.sha256(full_response.content).hexdigest(),
              "index_url": url + ".idx", "index_sha256": hashlib.sha256(index_response.content).hexdigest(),
              "prefix_range": f"bytes=0-{end-1}", "prefix_bytes": end,
              "prefix_sha256": hashlib.sha256(range_response.content).hexdigest(),
              "full_prefix_byte_identity": True, "all_state_totals_exactly_equal": True,
              "reference_time_equal": True, "state_count": len(full_totals)}
    (ROOT / "logs" / "gefs_11_indexed_prefix_equivalence.json").write_text(
        json.dumps(record, indent=2), encoding="utf-8")
    print("NOAA indexed prefix exactly matches full-object bytes and state totals", flush=True)


if __name__ == "__main__":
    main()
