"""Compute outcome-blind Wednesday five-vs-eleven GEFS dispersion QA."""

import csv
import hashlib
import json
import os
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from build_gefs_features import ROOT, CONFIG, load_weights, member_totals
from verify_amendments import verify as verify_amendments


INVENTORY = ROOT / "raw" / "gefs_11member_wednesday_inventory.csv"


def retrieve(row):
    cycle, member = row["archive_cycle"], row["member"]
    path = ROOT / "raw" / "gefs_11member_temp" / f"{cycle}_{member}.grib2"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".part")
    sha = hashlib.sha256()
    size = 0
    with requests.get(row["source_url"], timeout=180, stream=True) as response:
        response.raise_for_status()
        with temp.open("wb") as stream:
            for chunk in response.iter_content(1024*1024):
                if chunk:
                    stream.write(chunk)
                    sha.update(chunk)
                    size += len(chunk)
    if size != int(row["content_length"]):
        temp.unlink()
        raise ValueError(f"Wednesday GEFS object size mismatch: {cycle} {member}")
    os.replace(temp, path)
    return path, sha.hexdigest(), size


def build_cycle(cycle, rows, unique, mapped, pool):
    output = ROOT / "interim" / "gefs_11member_qa_cycles" / f"{cycle}.parquet"
    provenance = ROOT / "provenance" / "gefs_11member_objects" / f"{cycle}.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    provenance.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and provenance.exists():
        return "cached"
    if output.exists() != provenance.exists():
        raise ValueError(f"Incomplete Wednesday GEFS QA cycle {cycle}")
    if len(rows) != 11 or any(row["status_code"] != "200" for row in rows):
        raise ValueError(f"Incomplete Wednesday 11-member archive cycle {cycle}")
    futures = {pool.submit(retrieve, row): row for row in rows}
    values = defaultdict(dict)
    source_rows = []
    references = set()
    for future in as_completed(futures):
        row = futures[future]
        path, sha, size = future.result()
        try:
            reference, totals = member_totals(path, cycle, row["member"], unique, mapped)
            references.add(reference)
            for state in CONFIG["state_postal_codes"]:
                values[state][row["member"]] = totals[state]
            source_rows.append({"source": "NOAA GEFSv12 reforecast", "version": "GEFSv12 retrospective 2000-2019",
                                "source_url": row["source_url"], "object_key": row["object_key"],
                                "local_path": "", "retrieved_utc": datetime.now(timezone.utc).isoformat(),
                                "byte_size": size, "sha256": sha,
                                "access_note": "Wednesday 11-member outcome-blind QA; streamed object; cached state totals",
                                "first_consumer": "src/build_gefs_11_qa.py"})
        finally:
            path.unlink()
    if len(references) != 1:
        raise ValueError(f"Wednesday GEFS reference-time mismatch {cycle}")
    records = []
    for state in CONFIG["state_postal_codes"]:
        members = values[state]
        first_five = np.array([members[m] for m in ("c00", "p01", "p02", "p03", "p04")])
        all_eleven = np.array([members["c00"]] + [members[f"p{number:02d}"] for number in range(1, 11)])
        records.append({"archive_cycle": cycle, "state_postal": state,
                        "gefs_reference_time_utc": next(iter(references)),
                        "sd5_mm": float(first_five.std(ddof=1)),
                        "sd11_mm": float(all_eleven.std(ddof=1))})
    temporary = output.with_suffix(".part")
    pd.DataFrame(records).to_parquet(temporary, index=False)
    temporary.replace(output)
    manifest_temp = provenance.with_suffix(".part")
    with manifest_temp.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(source_rows[0]))
        writer.writeheader()
        writer.writerows(source_rows)
    manifest_temp.replace(provenance)
    return "built"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--finalize-only", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.shard_index < args.shard_count:
        raise ValueError("Invalid GEFS eleven-member shard")
    if not args.finalize_only:
        raise ValueError("Wednesday source construction requires the full forensic audit: src/audit_build_gefs_11_full.py")
    verify_amendments(require_qa=True)
    unique, mapped = load_weights()
    with INVENTORY.open(newline="", encoding="utf-8") as stream:
        inventory = list(csv.DictReader(stream))
    groups = defaultdict(list)
    for row in inventory:
        groups[row["archive_cycle"]].append(row)
    files = sorted((ROOT / "interim" / "gefs_11member_qa_cycles").glob("*.parquet"))
    if len(files) != len(groups):
        raise ValueError(f"GEFS eleven-member QA cycle count {len(files)} differs from {len(groups)}")
    result = pd.concat([pd.read_parquet(path) for path in files], ignore_index=True)
    result.to_parquet(ROOT / "interim" / "gefs_11member_qa.parquet", index=False)
    print("Wednesday state-week QA rows:", len(result))


if __name__ == "__main__":
    main()
