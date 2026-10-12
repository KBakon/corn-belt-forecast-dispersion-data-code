"""Assemble frozen corn state-week exports; never estimates associations."""

import csv
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "frozen_design.json").read_text())
OUTPUT = ROOT / "ANALYSIS_READY_PANEL"
REQUIRED_PRIMARY = [
    "planting_utilization_pp_per_suitable_day", "gefs_precip_mean_iqr", "gefs_precip_sd5_iqr",
    "nldas_precip_total_mm", "nldas_tair_mean_c", "nldas_soilm_0_10_mean_kgm2",
    "remaining_start_pp", "seasonal_week", "state_fips", "crop_year",
]


def dictionary(panel_columns):
    entries = [
        ("state_fips", "string", "2019 TIGER state FIPS; frozen 17-state frame", "TIGER/Line 2019"),
        ("state_postal", "string", "State postal code", "TIGER/Line 2019"),
        ("state_name", "string", "NASS state name", "USDA NASS Quick Stats"),
        ("crop", "string", "CORN, frozen primary crop", "frozen design"),
        ("crop_year", "integer", "NASS reporting crop year", "USDA NASS Quick Stats"),
        ("week_ending_sunday", "date", "NASS week-ending Sunday", "USDA NASS Quick Stats"),
        ("seasonal_week", "integer", "ISO week of NASS Sunday", "derived"),
        ("planting_previous_pct", "percent", "Previous Sunday cumulative corn planted", "USDA NASS Quick Stats"),
        ("planting_cumulative_pct", "percent", "Current Sunday cumulative corn planted", "USDA NASS Quick Stats"),
        ("planting_increment_pp", "percentage points", "Unsmoothed current minus previous cumulative progress", "derived from NASS"),
        ("remaining_start_pp", "percentage points", "100 minus prior cumulative progress", "derived from NASS"),
        ("dsfw_days", "days per week", "Days Suitable for Fieldwork", "USDA NASS Quick Stats"),
        ("dsfw_zero_flag", "boolean", "DSFW equals zero", "derived from NASS"),
        ("active_week_flag", "boolean", "5 <= prior cumulative planting < 95", "frozen design"),
        ("increment_valid_flag", "boolean", "Weekly planting increment is nonnegative", "frozen design"),
        ("planting_utilization_pp_per_suitable_day", "percentage points per suitable day", "Increment divided by positive DSFW for valid active rows", "derived from NASS"),
        ("gefs_archive_cycle", "YYYYMMDDHH", "Selected Monday 00 archive directory", "NOAA GEFSv12"),
        ("gefs_reference_time_utc", "UTC timestamp", "Decoded GRIB reference time", "NOAA GEFSv12"),
        ("forecast_window_start_utc", "UTC timestamp", "Physical seven-day window start", "decoded GEFS metadata"),
        ("forecast_window_end_utc", "UTC timestamp", "Physical seven-day window end, exclusive for NLDAS hours", "decoded GEFS metadata"),
        ("gefs_precip_mean_mm", "mm", "Five-member mean of corn-weighted 0-168 h precipitation totals", "NOAA GEFSv12"),
        ("gefs_precip_sd5_mm", "mm", "Sample SD of five member totals, ddof=1", "NOAA GEFSv12"),
        ("gefs_precip_mean_iqr", "pooled IQR units", "Raw GEFS mean centered and scaled on fixed ISO 13-26 frame", "derived from GEFS"),
        ("gefs_precip_sd5_iqr", "pooled IQR units", "Raw GEFS SD centered and scaled on fixed ISO 13-26 frame", "derived from GEFS"),
        ("gefs_precip_mean_area_mm", "mm", "Five-member state-land-area mean for outcome-blind spatial QA", "NOAA GEFSv12"),
        ("gefs_precip_sd5_area_mm", "mm", "Five-member state-land-area SD for outcome-blind spatial QA", "NOAA GEFSv12"),
        ("nldas_precip_total_mm", "mm", "Sum of hourly crop-weighted Rainf over physical forecast window", "NLDAS_FORA0125_H.2.0"),
        ("nldas_tair_mean_c", "degrees C", "Mean hourly crop-weighted Tair, K-273.15", "NLDAS_FORA0125_H.2.0"),
        ("nldas_soilm_0_10_mean_kgm2", "kg m-2", "Mean hourly crop-weighted top-layer Noah soil moisture", "NLDAS_NOAH0125_H.2.0"),
        ("nldas_soilm_0_10_start_kgm2", "kg m-2", "First available hourly top-layer Noah soil moisture at/after reference", "NLDAS_NOAH0125_H.2.0"),
        ("nldas_precip_total_area_mm", "mm", "State-land-area counterpart for spatial QA", "NLDAS_FORA0125_H.2.0"),
        ("nldas_tair_mean_area_c", "degrees C", "State-land-area counterpart for spatial QA", "NLDAS_FORA0125_H.2.0"),
        ("nldas_soilm_0_10_mean_area_kgm2", "kg m-2", "State-land-area counterpart for spatial QA", "NLDAS_NOAH0125_H.2.0"),
        ("nldas_soilm_0_10_start_area_kgm2", "kg m-2", "First available hourly state-land-area Noah soil moisture for spatial QA", "NLDAS_NOAH0125_H.2.0"),
        ("primary_complete_case_flag", "boolean", "All frozen primary variables present after active, valid and DSFW>0 rules", "derived"),
    ]
    for name in ("nldas_precip_total_mm", "nldas_precip_total_area_mm",
                 "nldas_tair_mean_c", "nldas_tair_mean_area_c",
                 "nldas_soilm_0_10_mean_kgm2", "nldas_soilm_0_10_mean_area_kgm2"):
        entries.append((name+"_valid_hours", "hours", "Observed hourly values out of 168", "NLDAS-2"))
        entries.append((name+"_missing_reason", "string", "Reason control is missing after 95% threshold", "NLDAS-2"))
    documented = [entry[0] for entry in entries]
    if len(documented) != len(set(documented)) or set(documented) != set(panel_columns):
        raise ValueError(f"Data dictionary does not match panel schema: missing {set(panel_columns)-set(documented)}, extra {set(documented)-set(panel_columns)}")
    with (OUTPUT / "data_dictionary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("variable", "unit_or_type", "definition", "source"))
        writer.writerows(entries)
    (OUTPUT / "data_dictionary.json").write_text(json.dumps([
        {"variable": name, "unit_or_type": unit, "definition": description, "source": source}
        for name, unit, description, source in entries], indent=2) + "\n")


def main():
    OUTPUT.mkdir(exist_ok=True)
    panel = pd.read_parquet(ROOT / "interim" / "nass_state_weeks.parquet")
    gefs = pd.read_parquet(ROOT / "interim" / "gefs_5member_state_weeks.parquet")
    nldas = pd.read_parquet(ROOT / "interim" / "nldas_state_weeks.parquet")
    target_sunday = pd.to_datetime(gefs["archive_cycle"].str[:8], format="%Y%m%d") + pd.Timedelta(days=6)
    fixed = gefs.loc[target_sunday.dt.isocalendar().week.between(13, 26)]
    scaling = fixed["gefs_precip_mean_mm"].median()
    mean_iqr = fixed["gefs_precip_mean_mm"].quantile(.75) - fixed["gefs_precip_mean_mm"].quantile(.25)
    sd_median = fixed["gefs_precip_sd5_mm"].median()
    sd_iqr = fixed["gefs_precip_sd5_mm"].quantile(.75) - fixed["gefs_precip_sd5_mm"].quantile(.25)
    if mean_iqr <= 0 or sd_iqr <= 0 or len(fixed) != 17*20*14:
        raise ValueError("GEFS fixed-frame scaling support invalid")
    gefs["gefs_precip_mean_iqr"] = (gefs["gefs_precip_mean_mm"] - scaling)/mean_iqr
    gefs["gefs_precip_sd5_iqr"] = (gefs["gefs_precip_sd5_mm"] - sd_median)/sd_iqr
    panel["gefs_archive_cycle"] = (panel["week_ending_sunday"]-pd.Timedelta(days=6)).dt.strftime("%Y%m%d00")
    panel = panel.merge(gefs, left_on=["gefs_archive_cycle", "state_postal"],
                        right_on=["archive_cycle", "state_postal"], how="left", validate="many_to_one")
    panel = panel.drop(columns=["archive_cycle"])
    panel = panel.merge(nldas, left_on=["gefs_archive_cycle", "state_postal"],
                        right_on=["archive_cycle", "state_postal"], how="left", validate="many_to_one")
    panel = panel.drop(columns=["archive_cycle"])
    panel["crop"] = "CORN"
    panel["forecast_window_start_utc"] = panel["gefs_reference_time_utc"]
    panel["forecast_window_end_utc"] = panel["gefs_reference_time_utc"] + pd.Timedelta(hours=168)
    selected = panel["active_week_flag"] & panel["increment_valid_flag"] & panel["dsfw_days"].gt(0)
    panel["primary_complete_case_flag"] = selected & panel[REQUIRED_PRIMARY].notna().all(axis=1)
    if len(panel) != 3000 or panel.duplicated(["state_fips", "week_ending_sunday"]).any():
        raise ValueError("Full panel key/row count mismatch")
    primary = panel.loc[panel["primary_complete_case_flag"]].copy()
    panel.to_parquet(OUTPUT / "analysis_ready_panel.parquet", index=False)
    primary.to_parquet(OUTPUT / "analysis_ready_primary.parquet", index=False)
    dictionary(panel.columns)
    metrics = {"full_rows": len(panel), "active_rows": int(panel.active_week_flag.sum()),
               "primary_complete_case_rows": len(primary), "states": int(panel.state_fips.nunique()),
               "years": int(panel.crop_year.nunique()),
               "gefs_scaling": {"mean_median_mm": float(scaling), "mean_iqr_mm": float(mean_iqr),
                                "sd5_median_mm": float(sd_median), "sd5_iqr_mm": float(sd_iqr)}}
    (ROOT / "logs" / "panel_build_log.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
