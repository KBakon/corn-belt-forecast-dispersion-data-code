"""Compute frozen five-member GEFS state precipitation features, outcome-blind."""

import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import eccodes
import numpy as np
import pandas as pd

from forensic_gefs_duplicates import SEMANTIC_KEYS, decoded_fields, message_info
from gefs_tiling import assert_exact_tiling, retain_exact_pair


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "frozen_design.json").read_text())
MEMBERS = CONFIG["gefs_primary_members"]
EXPECTED_STEPS = {(start, start+6) for start in range(0, 168, 6)}
EXPECTED_3H = {(start, start+3) for start in range(0, 168, 3)}


def load_approved_duplicates():
    summary = json.loads((ROOT / "logs" / "gefs_duplicate_forensic_summary.json").read_text(encoding="utf-8"))
    if not summary["case_a_eligible"] or summary["nonidentical_pairs"]:
        raise ValueError("GEFS exact-duplicate forensic verdict does not authorize collapse")
    approved = defaultdict(dict)
    with (ROOT / "logs" / "gefs_duplicate_forensic_comparison.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row["exact_semantic_duplicate"] != "True" or not row["source_sha256"]:
                raise ValueError("GEFS forensic pair is not verified as exact")
            key = (row["archive_cycle"], row["member"])
            pair = (int(row["start_step_hour"]), int(row["end_step_hour"]))
            approved[key][pair] = row
    return approved


def load_weights():
    by_state = {}
    all_indices = set()
    for postal in CONFIG["state_postal_codes"]:
        for suffix, folder in (("", "gefs_weights"), ("_area", "gefs_area_weights")):
            table = pd.read_csv(ROOT / "spatial" / folder / f"{postal}.csv")
            weight_column = "normalized_area_weight" if suffix else "normalized_corn_frequency_weight"
            if not math.isclose(table[weight_column].sum(), 1.0, abs_tol=1e-9):
                raise ValueError(f"GEFS weight sum != 1 for {postal}{suffix}")
            row = table["row_index"].to_numpy(dtype=np.int64)
            col = table["col_index"].to_numpy(dtype=np.int64)
            # Weight grid uses longitudes -180..180, archive GRIB uses 0..360.
            archive_col = (col - 720) % 1440
            indices = row * 1440 + archive_col
            by_state[postal+suffix] = (indices, table[weight_column].to_numpy(float))
            all_indices.update(indices.tolist())
    unique = np.array(sorted(all_indices), dtype=np.int64)
    position = {int(index): i for i, index in enumerate(unique)}
    mapped = {state: (np.array([position[int(index)] for index in indices]), weights)
              for state, (indices, weights) in by_state.items()}
    return unique, mapped


def member_totals(path, archive_cycle, expected_member, unique, mapped,
                  approved_duplicates=None, discarded_log=None):
    found = {}
    reference = None
    approved = (approved_duplicates or {}).get((archive_cycle, expected_member), {})
    if approved:
        observed_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        audited_rows = [row for value in approved.values()
                        for row in (value if isinstance(value, list) else [value])]
        if {row["source_sha256"] for row in audited_rows} != {observed_sha}:
            raise ValueError(f"GEFS object differs from verified forensic source: {path}")
    collapsed = set()
    collapse_count = defaultdict(int)
    with path.open("rb") as stream:
        message_index = 0
        while True:
            offset = stream.tell()
            message = eccodes.codes_grib_new_from_file(stream)
            if message is None:
                break
            message_index += 1
            try:
                start = int(eccodes.codes_get(message, "startStep"))
                end = int(eccodes.codes_get(message, "endStep"))
                if (start, end) not in EXPECTED_STEPS:
                    if (start, end) not in EXPECTED_3H and start < 168 and end > 0:
                        raise ValueError(f"Unexpected GEFS interval intersecting 0-168 h in {path}: {start}-{end}")
                    continue
                info = message_info(message, message_index, offset)
                full = decoded_fields(message) if (start, end) in approved else None
                record = {"info": info, "full": full}
                if (start, end) in found:
                    if (start, end) not in approved:
                        raise ValueError(f"Unapproved GEFS accumulation duplicate in {path}: {start}-{end}")
                    retained, discarded = retain_exact_pair(found[(start, end)], record, SEMANTIC_KEYS)
                    candidates = approved[(start, end)]
                    if not isinstance(candidates, list):
                        candidates = [candidates]
                    matches = [row for row in candidates
                               if int(row["duplicate_message_index"]) == discarded["info"]["message_index"]]
                    if len(matches) != 1:
                        raise ValueError(f"GEFS duplicate is absent from forensic catalogue: {path}: {start}-{end}")
                    audit = matches[0]
                    if (retained["info"]["message_index"] != int(audit["retained_message_index"])
                            or discarded["info"]["message_index"] != int(audit["duplicate_message_index"])):
                        raise ValueError(f"GEFS duplicate order differs from forensic audit: {path}: {start}-{end}")
                    found[(start, end)] = retained
                    collapsed.add((start, end))
                    collapse_count[(start, end)] += 1
                    if discarded_log is not None:
                        discarded_log.append({"archive_cycle": archive_cycle, "member": expected_member,
                                              "start_step_hour": start, "end_step_hour": end,
                                              "retained_message_index": retained["info"]["message_index"],
                                              "retained_byte_offset": retained["info"]["byte_offset"],
                                              "discarded_message_index": discarded["info"]["message_index"],
                                              "discarded_byte_offset": discarded["info"]["byte_offset"],
                                              "source_sha256": audit["source_sha256"]})
                    continue
                date = int(eccodes.codes_get(message, "dataDate"))
                time = int(eccodes.codes_get(message, "dataTime"))
                instant = datetime.strptime(f"{date:08d}{time:04d}", "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
                if instant.strftime("%Y%m%d%H") != archive_cycle:
                    raise ValueError(f"GEFS reference time differs from selected archive cycle: {path}")
                if reference is None:
                    reference = instant
                elif instant != reference:
                    raise ValueError(f"Inconsistent GEFS reference time in {path}")
                if eccodes.codes_get(message, "gridType") != "regular_ll":
                    raise ValueError(f"Unexpected GEFS grid in {path}")
                if (int(eccodes.codes_get(message, "Ni")), int(eccodes.codes_get(message, "Nj"))) != (1440, 721):
                    raise ValueError(f"Unexpected GEFS grid shape in {path}")
                if eccodes.codes_get(message, "units") != "kg m**-2":
                    raise ValueError(f"Unexpected GEFS apcp units in {path}")
                valid_date = int(eccodes.codes_get(message, "validityDate"))
                valid_time = int(eccodes.codes_get(message, "validityTime"))
                valid = datetime.strptime(f"{valid_date:08d}{valid_time:04d}", "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
                if valid != instant + timedelta(hours=end):
                    raise ValueError(f"GEFS accumulation valid time mismatch in {path}")
                values = np.asarray(eccodes.codes_get_double_elements(message, "values", unique.tolist()), dtype=np.float64)
                if not np.isfinite(values).all() or (values < -1e-8).any():
                    raise ValueError(f"Nonphysical GEFS precipitation in {path}")
                record["subset"] = values
                found[(start, end)] = record
            finally:
                eccodes.codes_release(message)
    if collapsed != set(approved):
        raise ValueError(f"GEFS approved duplicate catalogue differs from actual messages: {path}")
    for pair, candidate in approved.items():
        expected_collapses = len(candidate) if isinstance(candidate, list) else 1
        if collapse_count[pair] != expected_collapses:
            raise ValueError(f"GEFS duplicate collapse count differs from forensic catalogue: {path}: {pair}")
    if set(found) != EXPECTED_STEPS:
        missing = sorted(EXPECTED_STEPS - set(found))
        raise ValueError(f"GEFS 0-168 h tiling gap in {path}: {missing}")
    assert_exact_tiling(found)
    if reference is None:
        raise ValueError(f"No selected GEFS accumulation in {path}")
    total_cells = np.sum(np.stack([found[step]["subset"] for step in sorted(found)]), axis=0)
    totals = {state: float(np.dot(total_cells[positions], weights))
              for state, (positions, weights) in mapped.items()}
    return reference, totals


def build_cycle(cycle, group, unique, mapped, approved_duplicates=None, discarded_log=None):
    state_values = defaultdict(dict)
    references = set()
    member_records = []
    for member in MEMBERS:
        path = ROOT / "raw" / "gefs_bulk" / cycle / f"{member}.grib2"
        reference, totals = member_totals(path, cycle, member, unique, mapped,
                                          approved_duplicates, discarded_log)
        references.add(reference)
        for state, total in totals.items():
            state_values[state][member] = total
            if not state.endswith("_area"):
                member_records.append({"archive_cycle": cycle, "state_postal": state,
                                       "member": member, "precip_total_mm": total})
    if len(references) != 1:
        raise ValueError(f"GEFS members have different reference times for {cycle}")
    reference = next(iter(references))
    results = []
    for state in CONFIG["state_postal_codes"]:
        values = state_values[state]
        ordered = np.array([values[member] for member in MEMBERS])
        ordered_area = np.array([state_values[state+"_area"][member] for member in MEMBERS])
        results.append({"archive_cycle": cycle, "state_postal": state,
                        "gefs_reference_time_utc": reference,
                        "gefs_precip_mean_mm": float(ordered.mean()),
                        "gefs_precip_sd5_mm": float(ordered.std(ddof=1)),
                        "gefs_precip_mean_area_mm": float(ordered_area.mean()),
                        "gefs_precip_sd5_area_mm": float(ordered_area.std(ddof=1))})
    return results, member_records


def main():
    unique, mapped = load_weights()
    approved_duplicates = load_approved_duplicates()
    rows = []
    for inventory in ("gefs_object_manifest_iso13_26.csv", "gefs_panel_extra_inventory.csv"):
        with (ROOT / "raw" / inventory).open(newline="", encoding="utf-8") as stream:
            rows.extend(csv.DictReader(stream))
    groups = defaultdict(dict)
    for row in rows:
        groups[row["archive_cycle"]][row["member"]] = row
    if any(set(group) != set(MEMBERS) for group in groups.values()):
        raise ValueError("Missing five-member GEFS cycle")
    result, per_member, discarded = [], [], []
    # ecCodes shares parser state and is unsafe in Python threads. Windows
    # policy blocks process-pool IPC, so decode deterministically in one process.
    for index, (cycle, group) in enumerate(sorted(groups.items()), 1):
        cycle_result, cycle_members = build_cycle(cycle, group, unique, mapped,
                                                  approved_duplicates, discarded)
        result.extend(cycle_result)
        per_member.extend(cycle_members)
        if index % 20 == 0:
            print(index, "of", len(groups), "GEFS cycles built", flush=True)
    if len(discarded) != sum(len(v) for v in approved_duplicates.values()):
        raise ValueError("GEFS discarded duplicate count differs from forensic catalogue")
    output = ROOT / "interim"
    pd.DataFrame(result).to_parquet(output / "gefs_5member_state_weeks.parquet", index=False)
    pd.DataFrame(per_member).to_parquet(output / "gefs_member_totals.parquet", index=False)
    with (ROOT / "logs" / "gefs_exact_duplicate_collapses.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(discarded[0]))
        writer.writeheader()
        writer.writerows(discarded)
    print("state-cycle features", len(result), flush=True)


if __name__ == "__main__":
    main()
