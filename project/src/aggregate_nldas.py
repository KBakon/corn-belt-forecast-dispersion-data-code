"""Aggregate physical seven-day NLDAS windows using frozen 95% completeness."""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "frozen_design.json").read_text())
EXPECTED_HOURS = 168
MIN_HOURS = math.ceil(EXPECTED_HOURS * CONFIG["nldas_hourly_completeness_minimum"])
VARIABLES = {
    "Rainf": "nldas_precip_total_mm",
    "Rainf_area": "nldas_precip_total_area_mm",
    "Tair": "nldas_tair_mean_c",
    "Tair_area": "nldas_tair_mean_area_c",
    "SoilM_0_10cm": "nldas_soilm_0_10_mean_kgm2",
    "SoilM_0_10cm_area": "nldas_soilm_0_10_mean_area_kgm2",
}


def aggregate_one(cycle, group):
    records = {"archive_cycle": cycle}
    if group.duplicated(["hour_utc", "variable"]).any():
        raise ValueError(f"Duplicate NLDAS state-hour variable in {cycle}")
    for variable, output_name in VARIABLES.items():
        selected = group[group["variable"] == variable].sort_values("hour_utc")
        if len(selected) != EXPECTED_HOURS:
            raise ValueError(f"NLDAS expected-hour row count differs in {cycle}:{variable}")
        values = selected["value"].to_numpy(dtype=float)
        valid = np.isfinite(values)
        n_valid = int(valid.sum())
        records[output_name + "_valid_hours"] = n_valid
        records[output_name + "_missing_reason"] = "" if n_valid >= MIN_HOURS else "below_95pct_hourly_completeness"
        if n_valid < MIN_HOURS:
            records[output_name] = float("nan")
        elif variable.startswith("Rainf"):
            records[output_name] = float(np.sum(values[valid]))
        elif variable.startswith("Tair"):
            records[output_name] = float(np.mean(values[valid]) - 273.15)
        else:
            records[output_name] = float(np.mean(values[valid]))
        if variable.startswith("SoilM_0_10cm"):
            start_name = "nldas_soilm_0_10_start_kgm2" if variable == "SoilM_0_10cm" else "nldas_soilm_0_10_start_area_kgm2"
            records[start_name] = float(values[valid][0]) if n_valid else float("nan")
    return records


def main():
    source = ROOT / "raw" / "nldas_hourly_state_subsets"
    files = sorted(source.glob("*.parquet"))
    panel = pd.read_parquet(ROOT / "interim" / "nass_state_weeks.parquet")
    expected_cycles = set((panel["week_ending_sunday"] - pd.Timedelta(days=6)).dt.strftime("%Y%m%d00"))
    if {path.stem for path in files} != expected_cycles:
        raise ValueError("NLDAS subset windows do not match all NASS panel cycles")
    output = []
    for path in files:
        frame = pd.read_parquet(path)
        if set(frame["variable"]) != set(VARIABLES):
            raise ValueError(f"NLDAS variable schema mismatch in {path.name}")
        for state, subset in frame.groupby("state_postal"):
            record = aggregate_one(path.stem, subset)
            record["state_postal"] = state
            output.append(record)
    results = pd.DataFrame(output)
    if len(results) != len(expected_cycles) * len(CONFIG["state_postal_codes"]):
        raise ValueError("NLDAS state-week output row count mismatch")
    target = ROOT / "interim" / "nldas_state_weeks.parquet"
    results.to_parquet(target, index=False)
    print("NLDAS state-week rows:", len(results))


if __name__ == "__main__":
    main()
