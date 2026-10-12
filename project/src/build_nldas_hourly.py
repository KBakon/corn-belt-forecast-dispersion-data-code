"""Stream frozen NLDAS-2 hourly objects into crop-weighted state subsets.

The per-object manifest retains URL, CMR identity, byte count and SHA-256.
The state-hour subset is cached; full upstream objects are streamed in memory.
"""

import csv
import argparse
import hashlib
import json
import threading
import time
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import earthaccess
import netCDF4
import numpy as np
import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "frozen_design.json").read_text())
NAMES = {"NLDAS_FORA0125_H": ("Rainf", "Tair"), "NLDAS_NOAH0125_H": ("SoilM_0_10cm",)}
LOCAL = threading.local()
AUTH = None


def weighted_indices():
    output = {}
    for variables in NAMES.values():
        for variable in variables:
            output[variable] = {}
            for state in CONFIG["state_postal_codes"]:
                for kind in ("crop", "area"):
                    frame = pd.read_csv(ROOT / "spatial" / "nldas_source_valid_weights" /
                                        variable / f"{state}_{kind}.csv")
                    weight_column = "normalized_source_valid_weight"
                    if not np.isclose(frame[weight_column].sum(), 1, atol=1e-9):
                        raise ValueError(f"NLDAS source-valid weight sum != 1 for {variable}:{state}:{kind}")
                    # Weight GeoTIFF is north-to-south; NLDAS NetCDF latitude is ascending.
                    rows = 223 - frame["row_index"].to_numpy(np.int64)
                    cols = frame["col_index"].to_numpy(np.int64)
                    if (rows < 0).any() or (rows >= 224).any() or (cols < 0).any() or (cols >= 464).any():
                        raise ValueError(f"NLDAS weight index out of bounds for {variable}:{state}:{kind}")
                    output[variable][(state, kind)] = (rows*464 + cols,
                                                       frame[weight_column].to_numpy(float))
    return output


def download_one(row):
    if not hasattr(LOCAL, "session"):
        LOCAL.session = AUTH.get_session()
    last_error = None
    product = row["collection_short_name"]
    variables = ",".join((*NAMES[product], "time"))
    url = ("https://opendap.earthdata.nasa.gov/collections/" +
           row["collection_concept_id"] + "/granules/" +
           quote(row["granule_ur"], safe="") + ".nc4?" + variables)
    for attempt in range(3):
        try:
            response = LOCAL.session.get(url, timeout=120)
            response.raise_for_status()
            payload = response.content
            if len(payload) < 1000:
                raise RuntimeError("NLDAS response shorter than NetCDF header")
            return payload, len(payload), hashlib.sha256(payload).hexdigest(), url, variables
        except (requests.RequestException, RuntimeError) as error:
            last_error = error
            if attempt < 2:
                time.sleep(2**attempt)
    raise RuntimeError(f"NLDAS retrieval failed after retries for {row['granule_ur']}: {type(last_error).__name__}")


def spatial_values(payload, product, expected_hour, weights):
    with netCDF4.Dataset("inmemory.nc", memory=payload) as dataset:
        time_variable = dataset.variables["time"]
        time_value = netCDF4.num2date(time_variable[0], time_variable.units,
                                      calendar=getattr(time_variable, "calendar", "standard"))
        encoded_hour = datetime(time_value.year, time_value.month, time_value.day,
                                time_value.hour, time_value.minute, tzinfo=timezone.utc)
        if encoded_hour != expected_hour:
            raise ValueError(f"NLDAS time coordinate differs from CMR granule hour: {product}")
        output = {}
        for variable in NAMES[product]:
            field = dataset.variables[variable]
            if field.shape != (1, 224, 464):
                raise ValueError(f"NLDAS variable shape differs from sample: {product}:{variable}")
            expected_unit = "K" if variable == "Tair" else "kg m-2"
            if getattr(field, "units", None) != expected_unit:
                raise ValueError(f"NLDAS variable unit differs from sample: {product}:{variable}")
            values = np.ma.filled(field[0], np.nan).astype(np.float64).ravel()
            output[variable] = {}
            for state_kind, (indices, weighted) in weights[variable].items():
                subset = values[indices]
                output[variable][state_kind] = float(np.dot(subset, weighted)) if np.isfinite(subset).all() else float("nan")
    return output


def process_week(cycle, start, entries, weights, pool):
    subset_path = ROOT / "raw" / "nldas_hourly_state_subsets" / f"{cycle}.parquet"
    manifest_path = ROOT / "provenance" / "nldas_week_objects" / f"{cycle}.csv"
    subset_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if subset_path.exists() and manifest_path.exists():
        return {"cycle": cycle, "status": "cached"}
    if subset_path.exists() != manifest_path.exists():
        raise ValueError(f"Incomplete NLDAS weekly cache for {cycle}")
    hours = [start + timedelta(hours=offset) for offset in range(168)]
    all_rows = []
    for name in NAMES:
        lookup = entries[name]
        for hour in hours:
            if hour not in lookup:
                for variable in NAMES[name]:
                    for state, kind in weights[variable]:
                        all_rows.append({"archive_cycle": cycle, "hour_utc": hour,
                                         "state_postal": state, "variable": variable if kind == "crop" else variable+"_area",
                                         "value": float("nan"), "reason": "cmr_granule_missing"})
    requested = [entries[name][hour] for name in NAMES for hour in hours if hour in entries[name]]
    sources = []
    for offset in range(0, len(requested), 12):
        batch = requested[offset:offset+12]
        futures = {pool.submit(download_one, row): row for row in batch}
        for future in as_completed(futures):
            row = futures[future]
            payload, byte_size, sha, url, variables = future.result()
            hour = datetime.fromisoformat(row["hour_utc"])
            values = spatial_values(payload, row["collection_short_name"], hour, weights)
            for variable, states in values.items():
                for (state, kind), value in states.items():
                    all_rows.append({"archive_cycle": cycle, "hour_utc": hour,
                                     "state_postal": state, "variable": variable if kind == "crop" else variable+"_area",
                                     "value": value, "reason": "" if np.isfinite(value) else "spatial_cell_missing"})
            sources.append({**row, "retrieved_utc": datetime.now(timezone.utc).isoformat(),
                            "byte_size": byte_size, "sha256": sha,
                            "access_route": "Earthdata authenticated OPeNDAP NetCDF4 variable subset",
                            "retrieved_subset_url": url, "subset_variables": variables,
                            "checksum_scope": "retrieved NetCDF4 variable subset; source granule identity from CMR"})
    expected = 168 * sum(len(weights[variable]) for names in NAMES.values() for variable in names)
    if len(all_rows) != expected:
        raise ValueError(f"NLDAS state-hour row count mismatch for {cycle}: {len(all_rows)} vs {expected}")
    temporary_subset = subset_path.with_suffix(".part")
    pd.DataFrame(all_rows).to_parquet(temporary_subset, index=False)
    temporary_subset.replace(subset_path)
    temporary_manifest = manifest_path.with_suffix(".part")
    with temporary_manifest.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(sources[0]))
        writer.writeheader()
        writer.writerows(sources)
    temporary_manifest.replace(manifest_path)
    return {"cycle": cycle, "status": "built", "downloaded_objects": len(sources),
            "missing_cmr_objects": 336-len(sources)}


def main():
    global AUTH
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--cycle", help="Build one archived GEFS reference cycle for verification")
    args = parser.parse_args()
    if not 0 <= args.shard_index < args.shard_count:
        raise ValueError("Invalid NLDAS shard")
    AUTH = earthaccess.login(strategy="netrc", persist=False)
    if not AUTH.authenticated:
        raise RuntimeError("Earthdata netrc authentication failed")
    weights = weighted_indices()
    feature_path = ROOT / "interim" / "gefs_5member_state_weeks.parquet"
    gefs = pd.read_parquet(feature_path)
    references = gefs.groupby("archive_cycle")["gefs_reference_time_utc"].nunique()
    if not references.eq(1).all():
        raise ValueError("GEFS member reference-time mismatch")
    by_cycle = gefs.drop_duplicates("archive_cycle").set_index("archive_cycle")["gefs_reference_time_utc"]
    panel = pd.read_parquet(ROOT / "interim" / "nass_state_weeks.parquet")
    cycles = sorted(set((panel["week_ending_sunday"]-pd.Timedelta(days=6)).dt.strftime("%Y%m%d00")))
    if not set(cycles).issubset(by_cycle.index):
        raise ValueError("GEFS features missing panel cycles before NLDAS construction")
    entries = {name: {} for name in NAMES}
    with (ROOT / "raw" / "nldas_object_manifest.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            hour = datetime.fromisoformat(row["hour_utc"])
            entries[row["collection_short_name"]][hour] = row
    shard = [cycle for index, cycle in enumerate(cycles) if index % args.shard_count == args.shard_index]
    if args.cycle:
        if args.cycle not in cycles:
            raise ValueError(f"Requested cycle is not in the frozen panel: {args.cycle}")
        shard = [args.cycle]
    progress_path = ROOT / "logs" / f"nldas_build_progress_shard{args.shard_index}_of_{args.shard_count}.jsonl"
    with ThreadPoolExecutor(max_workers=12) as pool, progress_path.open("a", encoding="utf-8") as progress:
        for index, cycle in enumerate(shard, 1):
            start = pd.Timestamp(by_cycle.loc[cycle]).to_pydatetime()
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            record = process_week(cycle, start, entries, weights, pool)
            progress.write(json.dumps(record) + "\n")
            progress.flush()
            if index % 5 == 0:
                print(index, "of", len(shard), "NLDAS weeks in shard", args.shard_index, "built", flush=True)


if __name__ == "__main__":
    main()
