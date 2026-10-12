"""Inventory every Wednesday GEFS QA source object and build provisional predictor-only totals.

Full NOAA objects are streamed one cycle at a time. No planting outcomes are read.
Cycle totals remain provisional until the entire 280-cycle forensic audit passes.
"""

import argparse
import csv
import hashlib
import json
import os
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import eccodes
import numpy as np
import pandas as pd
import requests

from build_gefs_features import ROOT, CONFIG, load_weights, member_totals
from forensic_gefs_duplicates import (EXPECTED_3H, EXPECTED_6H, SEMANTIC_KEYS,
                                      compare_group, inventory_rows, message_info, write_csv)


INVENTORY = ROOT / "raw" / "gefs_11member_wednesday_inventory.csv"
AUDIT_DIR = ROOT / "logs" / "gefs_11_cycle_audits"
COMPARISON_FIELDS = (
    "archive_cycle", "member", "start_step_hour", "end_step_hour",
    "retained_message_index", "retained_byte_offset", "duplicate_message_index",
    "duplicate_byte_offset", "retained_message_size", "duplicate_message_size",
    "retained_metadata_json", "duplicate_metadata_json", "semantic_differences_json",
    "retained_decoded_sha256", "duplicate_decoded_sha256",
    "retained_missing_mask_sha256", "duplicate_missing_mask_sha256",
    "retained_bitmap_sha256", "duplicate_bitmap_sha256", "max_abs_decoded_difference",
    "unequal_decoded_cells", "same_grid_mask_and_semantics", "exact_semantic_duplicate",
    "source_etag", "source_url", "source_sha256",
)
INVENTORY_FIELDS = (
    "archive_cycle", "member", "object_key", "source_sha256", "source_etag",
    "total_grib_messages", "anomaly", "start_step_hour", "end_step_hour",
    "message_count", "message_indices", "byte_offsets", "detail",
)


def source_retrieve(row):
    cycle, member = row["archive_cycle"], row["member"]
    if row["status_code"] != "200":
        raise ValueError(f"NOAA Wednesday source inventory is not HTTP 200: {cycle}:{member}")
    path = ROOT / "raw" / "gefs_11member_temp" / f"{cycle}_{member}.grib2"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".part")
    last_error = None
    for attempt in range(3):
        sha = hashlib.sha256()
        md5 = hashlib.md5()
        size = 0
        try:
            with requests.get(row["source_url"], timeout=180, stream=True) as response:
                response.raise_for_status()
                with temporary.open("wb") as stream:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            stream.write(chunk)
                            sha.update(chunk)
                            md5.update(chunk)
                            size += len(chunk)
            if size != int(row["content_length"]):
                raise ValueError(f"NOAA object byte count differs from CMR-style inventory: {cycle}:{member}")
            etag = row["etag"].strip('"')
            if re.fullmatch(r"[0-9a-fA-F]{32}", etag) and md5.hexdigest().lower() != etag.lower():
                raise ValueError(f"NOAA object MD5 differs from ETag: {cycle}:{member}")
            os.replace(temporary, path)
            return path, sha.hexdigest(), size
        except (requests.RequestException, ValueError, OSError) as error:
            last_error = error
            temporary.unlink(missing_ok=True)
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Wednesday GEFS retrieval failed after retries for {cycle}:{member}: {type(last_error).__name__}: {last_error}")


def scan_temporal_object(path, cycle, member):
    selected = defaultdict(list)
    unexpected = []
    malformed = []
    total = 0
    reference = datetime.strptime(cycle, "%Y%m%d%H").replace(tzinfo=timezone.utc)
    expected_number = 0 if member == "c00" else int(member[1:])
    with path.open("rb") as stream:
        while True:
            offset = stream.tell()
            handle = eccodes.codes_grib_new_from_file(stream)
            if handle is None:
                break
            total += 1
            try:
                info = message_info(handle, total, offset)
                start, end = int(info["startStep"]), int(info["endStep"])
                pair = (start, end)
                if pair in EXPECTED_6H:
                    selected[pair].append(info)
                elif pair not in EXPECTED_3H and start < 168 and end > 0:
                    unexpected.append(info)
                if start < 168 and end > 0:
                    valid = reference + timedelta(hours=end)
                    expected = {"shortName": "tp", "paramId": 228228,
                                "typeOfLevel": "surface", "stepType": "accum",
                                "gridType": "regular_ll", "Ni": 1440, "Nj": 721,
                                "units": "kg m**-2", "number": expected_number,
                                "dataDate": int(reference.strftime("%Y%m%d")),
                                "dataTime": int(reference.strftime("%H%M")),
                                "validityDate": int(valid.strftime("%Y%m%d")),
                                "validityTime": int(valid.strftime("%H%M"))}
                    differences = {key: {"expected": value, "observed": info[key]}
                                   for key, value in expected.items() if info[key] != value}
                    if differences or not (0 <= start < end):
                        malformed.append({"info": info, "differences": differences})
            finally:
                eccodes.codes_release(handle)
    return selected, unexpected, malformed, total


def object_audit_rows(row, sha, selected, unexpected, malformed, total):
    cycle, member = row["archive_cycle"], row["member"]
    base = {"archive_cycle": cycle, "member": member, "object_key": row["object_key"],
            "source_sha256": sha, "source_etag": row["etag"], "total_grib_messages": total}
    entries = [{**base, "anomaly": "none", "start_step_hour": "", "end_step_hour": "",
                "message_count": "", "message_indices": "", "byte_offsets": "", "detail": ""}]
    for issue in inventory_rows(cycle, member, selected, unexpected, total):
        entries.append({**base, **{key: issue.get(key, "") for key in INVENTORY_FIELDS},
                        "object_key": row["object_key"], "source_sha256": sha,
                        "source_etag": row["etag"], "detail": ""})
    for issue in malformed:
        info = issue["info"]
        entries.append({**base, "anomaly": "malformed_or_inconsistent_temporal_metadata",
                        "start_step_hour": info["startStep"], "end_step_hour": info["endStep"],
                        "message_count": 1, "message_indices": info["message_index"],
                        "byte_offsets": info["byte_offset"],
                        "detail": json.dumps(issue["differences"], sort_keys=True)})
    return entries


def save_cycle_evidence(cycle, inventory, comparisons, objects, status):
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(AUDIT_DIR / f"{cycle}_inventory.csv", inventory, INVENTORY_FIELDS)
    write_csv(AUDIT_DIR / f"{cycle}_forensic.csv", comparisons, COMPARISON_FIELDS)
    record = {"archive_cycle": cycle, "status": status, "source_objects": objects,
              "object_count": len(objects), "duplicate_groups": len(comparisons),
              "exact_duplicate_groups": sum(bool(row["exact_semantic_duplicate"]) for row in comparisons),
              "nonidentical_duplicate_groups": sum(not row["exact_semantic_duplicate"] for row in comparisons),
              "missing_windows": sum(row["anomaly"] == "missing_6h_window" for row in inventory),
              "distinct_overlaps": sum(row["anomaly"] == "overlapping_distinct_6h_windows" for row in inventory),
              "unexpected_intervals": sum(row["anomaly"] == "unexpected_intersecting_interval" for row in inventory),
              "malformed_temporal_messages": sum(row["anomaly"] == "malformed_or_inconsistent_temporal_metadata" for row in inventory)}
    (AUDIT_DIR / f"{cycle}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def assert_cycle_case_a(record):
    cycle = record["archive_cycle"]
    if record["nonidentical_duplicate_groups"]:
        raise ValueError(f"CASE B — non-identical Wednesday GEFS duplicate: {cycle}")
    if any(record[key] for key in ("missing_windows", "distinct_overlaps",
                                 "unexpected_intervals", "malformed_temporal_messages")):
        raise ValueError(f"Wednesday GEFS source tiling or temporal anomaly: {cycle}")


def build_cycle(cycle, rows, unique, mapped, pool):
    output = ROOT / "interim" / "gefs_11member_qa_cycles" / f"{cycle}.parquet"
    provenance = ROOT / "provenance" / "gefs_11member_objects" / f"{cycle}.csv"
    audit = AUDIT_DIR / f"{cycle}.json"
    if output.exists() and provenance.exists() and audit.exists():
        previous = json.loads(audit.read_text(encoding="utf-8"))
        if previous["status"] == "cycle_exact_audit_passed" and previous["object_count"] == 11:
            return "cached"
    if len(rows) != 11 or {row["member"] for row in rows} != {"c00", *(f"p{x:02d}" for x in range(1, 11))}:
        raise ValueError(f"Incomplete frozen Wednesday ensemble for {cycle}")
    future_rows = {pool.submit(source_retrieve, row): row for row in rows}
    downloads = {}
    try:
        for future in as_completed(future_rows):
            row = future_rows[future]
            downloads[row["member"]] = future.result()
        inventory = []
        comparisons = []
        source_objects = []
        approved = defaultdict(dict)
        for row in sorted(rows, key=lambda item: item["member"]):
            member = row["member"]
            path, sha, size = downloads[member]
            selected, unexpected, malformed, total = scan_temporal_object(path, cycle, member)
            inventory.extend(object_audit_rows(row, sha, selected, unexpected, malformed, total))
            source = dict(row)
            source["sha256"] = sha
            for pair, group in sorted(selected.items()):
                if len(group) > 1:
                    evidence = compare_group(path, cycle, member, pair, group, source)
                    comparisons.extend(evidence)
                    if len(evidence) != len(group)-1:
                        raise ValueError(f"Incomplete duplicate comparison: {cycle}:{member}:{pair}")
                    if all(item["exact_semantic_duplicate"] for item in evidence):
                        approved[(cycle, member)][pair] = evidence
            source_objects.append({"member": member, "source_url": row["source_url"],
                                   "object_key": row["object_key"], "etag": row["etag"],
                                   "sha256": sha, "byte_size": size, "message_count": total})
        record = save_cycle_evidence(cycle, inventory, comparisons, source_objects,
                                     "forensic_complete_pending_cycle_validation")
        assert_cycle_case_a(record)
        values = defaultdict(dict)
        references = set()
        source_rows = []
        collapse_log = []
        for row in sorted(rows, key=lambda item: item["member"]):
            member = row["member"]
            path, sha, size = downloads[member]
            reference, totals = member_totals(path, cycle, member, unique, mapped,
                                              approved_duplicates=approved,
                                              discarded_log=collapse_log)
            references.add(reference)
            for state in CONFIG["state_postal_codes"]:
                values[state][member] = totals[state]
            source_rows.append({"source": "NOAA GEFSv12 reforecast",
                                "version": "GEFSv12 retrospective 2000-2019",
                                "source_url": row["source_url"], "object_key": row["object_key"],
                                "local_path": "", "retrieved_utc": datetime.now(timezone.utc).isoformat(),
                                "byte_size": size, "sha256": sha,
                                "access_note": "Wednesday 11-member outcome-blind QA; complete source object streamed; full-grid anomaly forensic audit before state totals",
                                "first_consumer": "src/audit_build_gefs_11_full.py"})
        if len(references) != 1 or len(collapse_log) != len(comparisons):
            raise ValueError(f"Wednesday GEFS reference or collapse count mismatch: {cycle}")
        records = []
        for state in CONFIG["state_postal_codes"]:
            member_values = values[state]
            first_five = np.array([member_values[x] for x in ("c00", "p01", "p02", "p03", "p04")])
            all_eleven = np.array([member_values["c00"]] + [member_values[f"p{x:02d}"] for x in range(1, 11)])
            records.append({"archive_cycle": cycle, "state_postal": state,
                            "gefs_reference_time_utc": next(iter(references)),
                            "sd5_mm": float(first_five.std(ddof=1)),
                            "sd11_mm": float(all_eleven.std(ddof=1))})
        output.parent.mkdir(parents=True, exist_ok=True)
        provenance.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".part")
        pd.DataFrame(records).to_parquet(temporary, index=False)
        temporary.replace(output)
        temporary = provenance.with_suffix(".part")
        with temporary.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(source_rows[0]))
            writer.writeheader(); writer.writerows(source_rows)
        temporary.replace(provenance)
        write_csv(AUDIT_DIR / f"{cycle}_collapses.csv", collapse_log,
                  ("archive_cycle", "member", "start_step_hour", "end_step_hour",
                   "retained_message_index", "retained_byte_offset", "discarded_message_index",
                   "discarded_byte_offset", "source_sha256"))
        save_cycle_evidence(cycle, inventory, comparisons, source_objects, "cycle_exact_audit_passed")
        return "built"
    finally:
        for path, _, _ in downloads.values():
            path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--cycle", help="Audit one frozen Wednesday cycle for implementation verification")
    args = parser.parse_args()
    if not 0 <= args.shard_index < args.shard_count:
        raise ValueError("Invalid Wednesday source audit shard")
    unique, mapped = load_weights()
    with INVENTORY.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    groups = defaultdict(list)
    for row in rows:
        groups[row["archive_cycle"]].append(row)
    if len(groups) != 280 or len(rows) != 280 * 11:
        raise ValueError("Frozen Wednesday source inventory is incomplete")
    shard = [(cycle, group) for index, (cycle, group) in enumerate(sorted(groups.items()))
             if index % args.shard_count == args.shard_index]
    if args.cycle:
        if args.cycle not in groups:
            raise ValueError("Requested cycle is outside frozen Wednesday inventory")
        shard = [(args.cycle, groups[args.cycle])]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for index, (cycle, group) in enumerate(shard, 1):
            status = build_cycle(cycle, group, unique, mapped, pool)
            if index % 5 == 0:
                print(index, "of", len(shard), "Wednesday forensic QA cycles in shard",
                      args.shard_index, status, flush=True)


if __name__ == "__main__":
    main()
