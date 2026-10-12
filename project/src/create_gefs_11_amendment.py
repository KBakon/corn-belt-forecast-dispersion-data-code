"""Create the Controller-authorized P2 QA scope extension only after 3,080-object Case A."""

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from verify_amendments import ROOT, PRIMARY, QA, PRIMARY_EXPECTED_SHA256, verify_file


def rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def main():
    primary_sha = verify_file(PRIMARY, PRIMARY_EXPECTED_SHA256)
    freeze_path = ROOT.parent / "FREEZE_MANIFEST.sha256"
    freeze_sha = hashlib.sha256(freeze_path.read_bytes()).hexdigest()
    if freeze_sha != "2caad1805e7b6e1cfe9ce9c7953e0c1d46e2ac91dd2c7f630fe1ee4064673ced":
        raise ValueError("Original frozen manifest hash has changed")
    summary = json.loads((ROOT / "logs" / "gefs_11_duplicate_forensic_summary.json").read_text())
    if (not summary["case_a_eligible"] or summary["audited_source_objects"] != 3080
            or summary["cycles"] != 280 or summary["nonidentical_duplicate_pairs"]
            or summary["maximum_abs_decoded_difference"] != 0
            or summary["unequal_decoded_cells"] != 0):
        raise ValueError("Controller's full-universe exact-only condition has not been met")
    forbidden_anomalies = ("missing_6h_window", "overlapping_distinct_6h_windows",
                           "unexpected_intersecting_interval",
                           "malformed_or_inconsistent_temporal_metadata")
    if any(summary["anomaly_counts"].get(key, 0) for key in forbidden_anomalies):
        raise ValueError("Wednesday source inventory contains a non-duplicate accumulation anomaly")
    evidence = ROOT / "logs" / "gefs_11_duplicate_forensic_comparison.csv"
    inventory = ROOT / "logs" / "gefs_11_accumulation_anomaly_inventory.csv"
    if hashlib.sha256(evidence.read_bytes()).hexdigest() != summary["forensic_sha256"]:
        raise ValueError("Wednesday full-grid forensic evidence hash changed")
    if hashlib.sha256(inventory.read_bytes()).hexdigest() != summary["inventory_sha256"]:
        raise ValueError("Wednesday full-source inventory hash changed")
    comparisons = rows(evidence)
    if len(comparisons) != summary["duplicate_comparison_pairs"]:
        raise ValueError("Wednesday forensic comparison count changed")
    by_cycle = defaultdict(lambda: {"groups": set(), "members": set()})
    for row in comparisons:
        if row["exact_semantic_duplicate"] != "True":
            raise ValueError("Wednesday source contains a non-identical forensic pair")
        cycle = row["archive_cycle"]
        by_cycle[cycle]["groups"].add((row["member"], row["start_step_hour"], row["end_step_hour"]))
        by_cycle[cycle]["members"].add(row["member"])
    cycle_lines = ["| Wednesday archive cycle | Members with exact duplicates | Duplicate interval groups |",
                   "|---|---|---:|"]
    for cycle, item in sorted(by_cycle.items()):
        cycle_lines.append(f"| `{cycle}` | {', '.join(sorted(item['members']))} | {len(item['groups'])} |")
    cycle_table = "\n".join(cycle_lines)
    content = f"""# Pre-result amendment: Wednesday GEFS eleven-member QA exact-duplicate scope

**Project and milestone:** Corn Belt F1, Protocol 1, P1-M1  
**Date:** 2026-10-07  
**Authority:** Controller's conditional outcome-blind GEFS 11-member QA exact-duplicate scope extension, satisfied by the full frozen-source inventory.  
**Status:** Authorized Case A after complete source forensic verification; before QA Block F or any primary dispersion–planting association was inspected.

## Relation to existing authority

The original freeze manifest and frozen scientific specifications remain unchanged. The separate primary-cache amendment `{PRIMARY}` remains unchanged with SHA-256 `{primary_sha}`. This amendment extends its exact-semantic source-encoding normalization principle **only** to the frozen Wednesday eleven-member GEFS QA source construction. It does not alter the GEFSv12 source, Wednesday timing rule, 0–168 hour precipitation quantity, five-member primary or eleven-member QA ensemble, state weights, forecast mean or sample-SD formulas, QA Block F purpose, primary estimand, regression, or scientific claim.

## Full-universe outcome-blind evidence

The complete frozen Wednesday source universe contains **{summary['cycles']} cycles and {summary['audited_source_objects']:,} member objects**. Every object was retrieved, checked against its NOAA inventory identity, decoded, and inventoried for expected six-hour windows, overlaps, unexpected intervals, and temporal metadata. The inventory found **{summary['duplicate_groups']} duplicate interval groups**, represented by **{summary['duplicate_comparison_pairs']} full-grid pair comparisons**. All **{summary['exact_semantic_duplicate_pairs']} comparisons** are exact semantic duplicates. Non-identical pairs: **0**; maximum absolute decoded precipitation difference: **0**; unequal decoded grid cells: **0**. Missing expected windows, distinct overlaps, unexpected intersecting intervals, and malformed temporal metadata: **0**. No NASS outcomes entered these checks.

{cycle_table}

The exact affected cycle/member/window/message identities, original byte offsets, source URLs, SHA-256 values and ETags, GRIB semantics, grid/mask/data hashes, and decoded-difference evidence are in `logs/gefs_11_accumulation_anomaly_inventory.csv` and `logs/gefs_11_duplicate_forensic_comparison.csv`. Their SHA-256 values are `{summary['inventory_sha256']}` and `{summary['forensic_sha256']}`, respectively. Each cycle's retained/discarded counterpart log is under `logs/gefs_11_cycle_audits/`.

## Narrow amended implementation rule

Before exact-once 0–168 hour tiling of each Wednesday QA member, collapse **only** records with identical meteorological identity and processing metadata, accumulation interval, grid, bitmap and missing mask, and decoded precipitation at every grid cell. The source object SHA-256 and each duplicate message pair must match the full-universe verified forensic catalogue. Retain the lowest original GRIB byte offset; if unavailable, retain the lowest message/submessage index. Log every retained and discarded counterpart. Any non-identical or unapproved duplicate remains a hard failure, as does any gap, distinct overlap, unexpected interval, changed source object, or malformed timing.

The resulting 28 six-hour accumulation intervals per member must tile 0–168 hours exactly once. The collapse leaves member precipitation totals equal to the totals from one retained exact copy. This is source encoding normalization only and changes no scientific estimand.

This amendment was made outcome-blind, before QA Block F results or any primary GEFS-dispersion–planting increment/utilization association were inspected. The primary model was not run.
"""
    path = ROOT / QA
    sidecar = path.with_suffix(path.suffix + ".sha256")
    if path.exists() or sidecar.exists():
        observed = verify_file(QA)
        if path.read_text(encoding="utf-8") != content:
            raise ValueError("Existing QA amendment differs from current full-source audit; no overwrite permitted")
        qa_sha = observed
    else:
        path.write_text(content, encoding="utf-8")
        qa_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        sidecar.write_text(f"{qa_sha}  {QA}\n", encoding="ascii")
    authority_path = ROOT / "provenance" / "project_authority_decisions.json"
    authority = {"project": "Corn Belt F1 P1-M1", "original_freeze_manifest_unchanged": True,
                 "original_freeze_manifest_sha256": freeze_sha,
                 "post_freeze_amendments": [
                     {"filename": PRIMARY, "sha256": primary_sha,
                      "controller_authorization": "2026-10-06 primary-cache exact-semantic duplicate Case A"},
                     {"filename": QA, "sha256": qa_sha,
                      "controller_authorization": "2026-10-07 conditional Wednesday 11-member QA exact-duplicate scope extension",
                      "condition": "Full 280-cycle/3,080-object outcome-blind Case A forensic audit passed",
                      "inventory_sha256": summary["inventory_sha256"],
                      "forensic_sha256": summary["forensic_sha256"]}]}
    if authority_path.exists():
        if json.loads(authority_path.read_text(encoding="utf-8")) != authority:
            raise ValueError("Existing durable authority decision log differs; no overwrite permitted")
    else:
        authority_path.write_text(json.dumps(authority, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"amendment": str(path), "sha256": qa_sha,
                      "duplicate_groups": summary["duplicate_groups"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
