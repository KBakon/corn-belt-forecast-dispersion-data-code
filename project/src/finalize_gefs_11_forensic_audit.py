"""Consolidate all 280 Wednesday source audits before any QA extension amendment."""

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from audit_build_gefs_11_full import (ROOT, AUDIT_DIR, COMPARISON_FIELDS,
                                      INVENTORY_FIELDS, INVENTORY)
from forensic_gefs_duplicates import write_csv


def rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def main():
    frozen = rows(INVENTORY)
    expected = {(row["archive_cycle"], row["member"], row["object_key"])
                for row in frozen}
    if len(frozen) != 3080 or len(expected) != 3080:
        raise ValueError("Frozen Wednesday 11-member source inventory is not 3,080 unique objects")
    cycles = sorted({row["archive_cycle"] for row in frozen})
    if len(cycles) != 280:
        raise ValueError("Frozen Wednesday QA source cycle count differs from 280")
    full_inventory = []
    comparisons = []
    source_keys = set()
    source_shas = {}
    for cycle in cycles:
        audit_path = AUDIT_DIR / f"{cycle}.json"
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        if audit["status"] != "cycle_exact_audit_passed" or audit["object_count"] != 11:
            raise ValueError(f"Incomplete exact source audit: {cycle}")
        for obj in audit["source_objects"]:
            key = (cycle, obj["member"], obj["object_key"])
            if key in source_keys or key not in expected:
                raise ValueError(f"Duplicate or extraneous Wednesday source identity: {key}")
            source_keys.add(key)
            source_shas[(cycle, obj["member"])] = obj["sha256"]
        cycle_inventory = rows(AUDIT_DIR / f"{cycle}_inventory.csv")
        cycle_comparisons = rows(AUDIT_DIR / f"{cycle}_forensic.csv")
        if len([item for item in cycle_inventory if item["anomaly"] == "none"]) != 11:
            raise ValueError(f"Wednesday cycle lacks eleven per-object inventory rows: {cycle}")
        if len(cycle_comparisons) != audit["duplicate_groups"]:
            raise ValueError(f"Wednesday forensic pair count mismatch: {cycle}")
        if any(item["exact_semantic_duplicate"] != "True" for item in cycle_comparisons):
            raise ValueError(f"CASE B — non-identical Wednesday duplicate: {cycle}")
        if any(item["anomaly"] in ("missing_6h_window", "overlapping_distinct_6h_windows",
                                    "unexpected_intersecting_interval",
                                    "malformed_or_inconsistent_temporal_metadata")
               for item in cycle_inventory):
            raise ValueError(f"Wednesday accumulation or timing anomaly: {cycle}")
        for item in cycle_comparisons:
            if item["source_sha256"] != source_shas[(cycle, item["member"])]:
                raise ValueError(f"Wednesday forensic pair source hash mismatch: {cycle}")
            if float(item["max_abs_decoded_difference"]) != 0 or int(item["unequal_decoded_cells"]) != 0:
                raise ValueError(f"CASE B — nonzero Wednesday duplicate data difference: {cycle}")
        provenance = rows(ROOT / "provenance" / "gefs_11member_objects" / f"{cycle}.csv")
        if len(provenance) != 11 or any(item["sha256"] != source_shas[(cycle, item["object_key"].split("/")[-3])]
                                     for item in provenance):
            raise ValueError(f"Wednesday object provenance does not match audited source: {cycle}")
        if not (ROOT / "interim" / "gefs_11member_qa_cycles" / f"{cycle}.parquet").exists():
            raise ValueError(f"Wednesday outcome-blind state totals missing: {cycle}")
        full_inventory.extend(cycle_inventory)
        comparisons.extend(cycle_comparisons)
    if source_keys != expected:
        raise ValueError("Wednesday source audit does not cover the complete frozen universe")
    groups = {(row["archive_cycle"], row["member"], row["start_step_hour"], row["end_step_hour"])
              for row in comparisons}
    anomalies = Counter(item["anomaly"] for item in full_inventory if item["anomaly"] != "none")
    write_csv(ROOT / "logs" / "gefs_11_accumulation_anomaly_inventory.csv",
              full_inventory, INVENTORY_FIELDS)
    write_csv(ROOT / "logs" / "gefs_11_duplicate_forensic_comparison.csv",
              comparisons, COMPARISON_FIELDS)
    summary = {"frozen_source_objects": len(expected), "audited_source_objects": len(source_keys),
               "cycles": len(cycles), "duplicate_groups": len(groups),
               "duplicate_comparison_pairs": len(comparisons),
               "exact_semantic_duplicate_pairs": sum(item["exact_semantic_duplicate"] == "True"
                                                     for item in comparisons),
               "nonidentical_duplicate_pairs": sum(item["exact_semantic_duplicate"] != "True"
                                                   for item in comparisons),
               "anomaly_counts": dict(anomalies),
               "maximum_abs_decoded_difference": max((float(item["max_abs_decoded_difference"])
                                                      for item in comparisons), default=0),
               "unequal_decoded_cells": sum(int(item["unequal_decoded_cells"]) for item in comparisons),
               "inventory_sha256": hashlib.sha256((ROOT / "logs" / "gefs_11_accumulation_anomaly_inventory.csv").read_bytes()).hexdigest(),
               "forensic_sha256": hashlib.sha256((ROOT / "logs" / "gefs_11_duplicate_forensic_comparison.csv").read_bytes()).hexdigest(),
               "case_a_eligible": True,
               "primary_dispersion_outcome_association_inspected": False}
    (ROOT / "logs" / "gefs_11_duplicate_forensic_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
