"""Outcome-blind inventory and full-grid comparison of cached GEFS messages.

This module reads only raw GEFS GRIB files and their object inventories. It does
not import NASS or any panel outcome.
"""

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import eccodes
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
MEMBERS = ("c00", "p01", "p02", "p03", "p04")
EXPECTED_6H = {(s, s + 6) for s in range(0, 168, 6)}
EXPECTED_3H = {(s, s + 3) for s in range(0, 168, 3)}
SEMANTIC_KEYS = (
    "shortName", "paramId", "typeOfLevel", "level", "dataDate", "dataTime",
    "validityDate", "validityTime", "startStep", "endStep", "stepRange",
    "stepType", "productDefinitionTemplateNumber", "typeOfStatisticalProcessing",
    "forecastTime", "lengthOfTimeRange", "numberOfTimeRanges", "gridType",
    "Ni", "Nj", "numberOfPoints", "bitmapPresent", "numberOfMissing",
    "edition", "number", "centre", "subCentre", "generatingProcessIdentifier",
    "typeOfGeneratingProcess", "latitudeOfFirstGridPointInDegrees",
    "longitudeOfFirstGridPointInDegrees", "latitudeOfLastGridPointInDegrees",
    "longitudeOfLastGridPointInDegrees", "iDirectionIncrementInDegrees",
    "jDirectionIncrementInDegrees", "iScansNegatively", "jScansPositively",
    "units",
)


def get_or_none(handle, key):
    try:
        return eccodes.codes_get(handle, key)
    except eccodes.CodesInternalError:
        return None


def message_info(handle, index, offset):
    info = {key: get_or_none(handle, key) for key in SEMANTIC_KEYS}
    info["message_index"] = index
    info["byte_offset"] = offset
    info["message_size"] = eccodes.codes_get_message_size(handle)
    return info


def scan_object(path):
    selected = defaultdict(list)
    unexpected = []
    total_messages = 0
    with path.open("rb") as stream:
        while True:
            offset = stream.tell()
            handle = eccodes.codes_grib_new_from_file(stream)
            if handle is None:
                break
            total_messages += 1
            try:
                info = message_info(handle, total_messages, offset)
                pair = (int(info["startStep"]), int(info["endStep"]))
                if pair in EXPECTED_6H:
                    selected[pair].append(info)
                elif pair not in EXPECTED_3H and pair[0] < 168 and pair[1] > 0:
                    unexpected.append(info)
            finally:
                eccodes.codes_release(handle)
    return selected, unexpected, total_messages


def inventory_rows(cycle, member, selected, unexpected, total):
    base = {"archive_cycle": cycle, "member": member, "total_grib_messages": total}
    rows = []
    for s, e in sorted(EXPECTED_6H):
        group = selected[(s, e)]
        if len(group) != 1:
            rows.append({**base, "anomaly": "missing_6h_window" if not group else "duplicated_6h_window",
                         "start_step_hour": s, "end_step_hour": e,
                         "message_count": len(group),
                         "message_indices": ";".join(str(m["message_index"]) for m in group),
                         "byte_offsets": ";".join(str(m["byte_offset"]) for m in group)})
    for info in unexpected:
        rows.append({**base, "anomaly": "unexpected_intersecting_interval",
                     "start_step_hour": info["startStep"], "end_step_hour": info["endStep"],
                     "message_count": 1, "message_indices": info["message_index"],
                     "byte_offsets": info["byte_offset"]})
    # Overlap across distinct selected 6h windows is forbidden independently
    # of exact duplicate groups. Nested 3h records are expected alternatives.
    present = sorted(k for k in selected if selected[k])
    for left, right in zip(present, present[1:]):
        if left != right and right[0] < left[1]:
            rows.append({**base, "anomaly": "overlapping_distinct_6h_windows",
                         "start_step_hour": right[0], "end_step_hour": left[1],
                         "message_count": 2,
                         "message_indices": f"{selected[left][0]['message_index']};{selected[right][0]['message_index']}",
                         "byte_offsets": f"{selected[left][0]['byte_offset']};{selected[right][0]['byte_offset']}"})
    return rows


def decoded_fields(handle):
    values = np.asarray(eccodes.codes_get_array(handle, "values"), dtype="<f8")
    missing = ~np.isfinite(values)
    missing_value = get_or_none(handle, "missingValue")
    if missing_value is not None:
        missing |= values == float(missing_value)
    bitmap_present = int(get_or_none(handle, "bitmapPresent") or 0)
    bitmap_hash = None
    if bitmap_present:
        bitmap = np.asarray(eccodes.codes_get_array(handle, "bitmap"), dtype=np.uint8)
        bitmap_hash = hashlib.sha256(bitmap.tobytes()).hexdigest()
        missing |= bitmap == 0
    return {
        "values": values,
        "missing": missing,
        "data_hash": hashlib.sha256(values.tobytes()).hexdigest(),
        "missing_hash": hashlib.sha256(np.packbits(missing).tobytes()).hexdigest(),
        "bitmap_hash": bitmap_hash,
    }


def compare_group(path, cycle, member, pair, group, source):
    wanted = {info["message_index"] for info in group}
    captured = {}
    with path.open("rb") as stream:
        index = 0
        while wanted:
            handle = eccodes.codes_grib_new_from_file(stream)
            if handle is None:
                raise ValueError(f"Missing GRIB message during second pass: {path}: {wanted}")
            index += 1
            try:
                if index in wanted:
                    captured[index] = decoded_fields(handle)
                    wanted.remove(index)
            finally:
                eccodes.codes_release(handle)
    first = min(group, key=lambda info: (info["byte_offset"], info["message_index"]))
    rows = []
    for other in sorted((m for m in group if m is not first), key=lambda m: (m["byte_offset"], m["message_index"])):
        a, b = captured[first["message_index"]], captured[other["message_index"]]
        semantic_differences = {key: [first[key], other[key]] for key in SEMANTIC_KEYS
                                if first[key] != other[key]}
        same_shape = a["values"].shape == b["values"].shape
        same_mask = same_shape and np.array_equal(a["missing"], b["missing"])
        if same_shape:
            valid = ~(a["missing"] | b["missing"])
            unequal = int(np.count_nonzero(a["values"][valid] != b["values"][valid]))
            max_diff = float(np.max(np.abs(a["values"][valid] - b["values"][valid]))) if valid.any() else 0.0
        else:
            unequal = None
            max_diff = None
        same_data = same_shape and same_mask and unequal == 0
        exact = not semantic_differences and same_data and a["bitmap_hash"] == b["bitmap_hash"]
        rows.append({
            "archive_cycle": cycle, "member": member, "start_step_hour": pair[0],
            "end_step_hour": pair[1], "retained_message_index": first["message_index"],
            "retained_byte_offset": first["byte_offset"],
            "duplicate_message_index": other["message_index"],
            "duplicate_byte_offset": other["byte_offset"],
            "retained_message_size": first["message_size"],
            "duplicate_message_size": other["message_size"],
            "retained_metadata_json": json.dumps({k: first[k] for k in SEMANTIC_KEYS}, sort_keys=True),
            "duplicate_metadata_json": json.dumps({k: other[k] for k in SEMANTIC_KEYS}, sort_keys=True),
            "semantic_differences_json": json.dumps(semantic_differences, sort_keys=True),
            "retained_decoded_sha256": a["data_hash"],
            "duplicate_decoded_sha256": b["data_hash"],
            "retained_missing_mask_sha256": a["missing_hash"],
            "duplicate_missing_mask_sha256": b["missing_hash"],
            "retained_bitmap_sha256": a["bitmap_hash"],
            "duplicate_bitmap_sha256": b["bitmap_hash"],
            "max_abs_decoded_difference": max_diff,
            "unequal_decoded_cells": unequal,
            "same_grid_mask_and_semantics": not semantic_differences and same_mask and a["bitmap_hash"] == b["bitmap_hash"],
            "exact_semantic_duplicate": exact,
            "source_etag": source.get("etag"), "source_url": source.get("source_url"),
            "source_sha256": source.get("sha256"),
        })
    return rows


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def add_verified_source_hashes(path):
    """Bind every forensic row to the exact cached object and SHA sidecar."""
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    checks = {}
    for row in rows:
        key = (row["archive_cycle"], row["member"])
        if key not in checks:
            obj = ROOT / "raw" / "gefs_bulk" / key[0] / f"{key[1]}.grib2"
            sidecar = obj.with_suffix(".sha256")
            observed = hashlib.sha256(obj.read_bytes()).hexdigest()
            recorded = sidecar.read_text(encoding="utf-8").strip().split()[0]
            if observed != recorded:
                raise ValueError(f"GEFS cached-object SHA sidecar mismatch: {obj}")
            checks[key] = observed
        row["source_sha256"] = checks[key]
    if rows:
        write_csv(path, rows, list(rows[0]))
    return checks


def main():
    source = {}
    for name in ("gefs_object_manifest_iso13_26.csv", "gefs_panel_extra_inventory.csv"):
        with (ROOT / "raw" / name).open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                source[(row["archive_cycle"], row["member"])] = row
    inventory = []
    duplicate_groups = []
    file_count = 0
    for cycle, member in sorted(source):
        path = ROOT / "raw" / "gefs_bulk" / cycle / f"{member}.grib2"
        if not path.is_file():
            inventory.append({"archive_cycle": cycle, "member": member,
                              "anomaly": "missing_cached_object", "start_step_hour": "",
                              "end_step_hour": "", "total_grib_messages": 0,
                              "message_count": 0, "message_indices": "", "byte_offsets": ""})
            continue
        selected, unexpected, total = scan_object(path)
        inventory.extend(inventory_rows(cycle, member, selected, unexpected, total))
        for pair, group in selected.items():
            if len(group) > 1:
                duplicate_groups.append((cycle, member, pair, group))
        file_count += 1
        if file_count % 100 == 0:
            print(f"scanned {file_count}/{len(source)} GEFS objects", flush=True)
    log = ROOT / "logs"
    write_csv(log / "gefs_accumulation_anomaly_inventory.csv", inventory,
              ("archive_cycle", "member", "total_grib_messages", "anomaly",
               "start_step_hour", "end_step_hour", "message_count", "message_indices", "byte_offsets"))
    print(f"inventory complete: {file_count} objects, {len(inventory)} anomalies, "
          f"{len(duplicate_groups)} duplicate groups", flush=True)
    comparisons = []
    for i, (cycle, member, pair, group) in enumerate(duplicate_groups, 1):
        path = ROOT / "raw" / "gefs_bulk" / cycle / f"{member}.grib2"
        comparisons.extend(compare_group(path, cycle, member, pair, group, source[(cycle, member)]))
        if i % 10 == 0:
            print(f"compared {i}/{len(duplicate_groups)} full-grid groups", flush=True)
    fields = list(comparisons[0]) if comparisons else [
        "archive_cycle", "member", "start_step_hour", "end_step_hour",
        "exact_semantic_duplicate"]
    write_csv(log / "gefs_duplicate_forensic_comparison.csv", comparisons, fields)
    object_hashes = add_verified_source_hashes(log / "gefs_duplicate_forensic_comparison.csv")
    counts = Counter(row["anomaly"] for row in inventory)
    result = {
        "observed_utc": datetime.now(timezone.utc).isoformat(),
        "cached_objects_expected": len(source), "cached_objects_scanned": file_count,
        "anomaly_counts": dict(counts), "duplicate_groups": len(duplicate_groups),
        "duplicate_pairs_compared_full_grid": len(comparisons),
        "exact_pairs": sum(bool(row["exact_semantic_duplicate"]) for row in comparisons),
        "nonidentical_pairs": sum(not row["exact_semantic_duplicate"] for row in comparisons),
        "affected_cached_object_sha256": {f"{cycle}/{member}": sha
                                          for (cycle, member), sha in object_hashes.items()},
        "case_a_eligible": file_count == len(source) and
            set(counts) <= {"duplicated_6h_window"} and
            all(row["exact_semantic_duplicate"] for row in comparisons),
    }
    (log / "gefs_duplicate_forensic_summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
