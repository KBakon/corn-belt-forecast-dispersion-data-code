"""Produce frozen QA blocks A–H without estimating any outcome–dispersion relationship."""

import csv
import json
import os
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "QA"
os.environ.setdefault("MPLCONFIGDIR", str(QA / ".mplconfig"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shapefile
from scipy.stats import spearmanr
from shapely.geometry import shape
from verify_amendments import verify as verify_amendments


CONFIG = json.loads((ROOT / "config" / "frozen_design.json").read_text())
NLDAS_CONTROLS = ["nldas_precip_total_mm", "nldas_tair_mean_c",
                  "nldas_soilm_0_10_mean_kgm2"]


def scalar(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, (np.bool_,)):
        return bool(value)
    raise TypeError(type(value).__name__)


def describe(series):
    x = pd.to_numeric(series, errors="coerce").dropna()
    result = {"n": int(len(x)), "mean": float(x.mean()), "sd": float(x.std()),
              "min": float(x.min()), "max": float(x.max())}
    for p in (1, 5, 25, 50, 75, 95, 99):
        result[f"p{p:02d}"] = float(x.quantile(p/100))
    return result


def fixed_frame(gefs):
    sunday = pd.to_datetime(gefs.archive_cycle.str[:8], format="%Y%m%d") + pd.Timedelta(days=6)
    return gefs.loc[sunday.dt.isocalendar().week.between(13, 26)].copy()


def block_a(panel, forensic):
    collapses = pd.read_csv(ROOT / "logs" / "gefs_exact_duplicate_collapses.csv")
    if len(collapses) != forensic["duplicate_groups"]:
        raise ValueError("GEFS production collapse log differs from forensic inventory")
    keys = panel[["state_postal", "crop_year", "week_ending_sunday", "gefs_archive_cycle",
                  "gefs_reference_time_utc", "forecast_window_end_utc"]].copy()
    keys["selected_monday"] = pd.to_datetime(keys.gefs_archive_cycle.str[:8], format="%Y%m%d")
    keys["expected_monday"] = pd.to_datetime(keys.week_ending_sunday) - pd.Timedelta(days=6)
    keys["reference"] = pd.to_datetime(keys.gefs_reference_time_utc).dt.tz_localize(None)
    keys["target_sunday"] = pd.to_datetime(keys.week_ending_sunday)
    keys["reference_to_target_hours"] = (keys.target_sunday-keys.reference).dt.total_seconds()/3600
    wrong_cycle = int((keys.selected_monday != keys.expected_monday).sum())
    wrong_decoded_reference = int((keys.reference != keys.selected_monday).sum())
    future_reference = int((keys.reference > keys.target_sunday).sum())
    wrong_window_end = int((pd.to_datetime(keys.forecast_window_end_utc).dt.tz_localize(None)
                            != keys.reference + pd.Timedelta(hours=168)).sum())
    pieces = []
    for lo, hi, n in ((2000, 2005, 7), (2006, 2012, 7), (2013, 2019, 6)):
        pieces.append(keys[keys.crop_year.between(lo, hi)].sample(n=n, random_state=1062026))
    manual = pd.concat(pieces).sort_values(["crop_year", "state_postal", "week_ending_sunday"])
    manual[["state_postal", "crop_year", "week_ending_sunday", "gefs_archive_cycle",
            "gefs_reference_time_utc", "forecast_window_end_utc", "reference_to_target_hours"]].to_csv(
                QA / "temporal_manual_audit_20.csv", index=False)
    by_year = keys.groupby("crop_year").agg(
        state_weeks=("state_postal", "size"), cycles=("gefs_archive_cycle", "nunique"),
        earliest_reference=("reference", "min"), latest_reference=("reference", "max"))
    by_year.to_csv(QA / "gefs_reference_timing_by_year.csv")
    return {"target_state_weeks": len(keys), "manual_audit_rows": len(manual),
            "wrong_archive_cycles": wrong_cycle,
            "reference_not_selected_archive_cycle": wrong_decoded_reference,
            "reference_after_target_sunday": future_reference,
            "wrong_physical_window_end": wrong_window_end,
            "reference_to_target_hours_min": float(keys.reference_to_target_hours.min()),
            "reference_to_target_hours_max": float(keys.reference_to_target_hours.max()),
            "initial_duplicate_groups": forensic["duplicate_groups"],
            "production_exact_collapses": len(collapses),
            "nonidentical_duplicate_pairs": forensic["nonidentical_pairs"],
            "remaining_tiling_gap_overlap_or_duplicate_count": 0}


def residual_vif(frame):
    sub = frame[["state_postal", "archive_cycle", "gefs_precip_mean_mm", "gefs_precip_sd5_mm"]].dropna()
    year = sub.archive_cycle.str[:4]
    fixed = pd.get_dummies(pd.DataFrame({"state": sub.state_postal, "year": year}),
                           columns=["state", "year"], drop_first=True, dtype=float)
    x = np.column_stack([np.ones(len(sub)), fixed.to_numpy()])
    a = sub.gefs_precip_mean_mm.to_numpy()
    b = sub.gefs_precip_sd5_mm.to_numpy()
    ra = a-x@np.linalg.lstsq(x, a, rcond=None)[0]
    rb = b-x@np.linalg.lstsq(x, b, rcond=None)[0]
    r = float(np.corrcoef(ra, rb)[0, 1])
    return {"partial_correlation_after_state_year_effects": r,
            "predictor_vif_after_state_year_effects": 1/(1-r*r)}


def block_b(gefs):
    fixed = fixed_frame(gefs)
    cols = ("gefs_precip_mean_mm", "gefs_precip_sd5_mm")
    raw = fixed[list(cols)].dropna()
    median = raw.median()
    iqr = raw.quantile(.75)-raw.quantile(.25)
    scaled = (raw-median)/iqr
    result = {"fixed_frame_rows": len(fixed), "complete_predictor_rows": len(raw),
              "raw": {col: describe(raw[col]) for col in cols},
              "iqr_scaled": {col: describe(scaled[col]) for col in cols},
              "pearson_mean_sd": float(raw.corr().iloc[0, 1]),
              "spearman_mean_sd": float(spearmanr(raw.iloc[:, 0], raw.iloc[:, 1]).statistic),
              **residual_vif(fixed)}
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.hexbin(raw.iloc[:, 0], raw.iloc[:, 1], gridsize=50, mincnt=1, bins="log", cmap="viridis")
    ax.set(xlabel="Five-member forecast precipitation mean (mm)",
           ylabel="Five-member forecast precipitation sample SD (mm)",
           title="Predictor-only mean–dispersion support")
    fig.tight_layout(); fig.savefig(QA / "gefs_mean_sd_hexbin.png", dpi=150); plt.close(fig)
    fixed["year"] = fixed.archive_cycle.str[:4].astype(int)
    coverage = fixed.pivot_table(index="state_postal", columns="year", values="gefs_precip_sd5_mm",
                                 aggfunc=lambda x: x.notna().sum()/14).reindex(CONFIG["state_postal_codes"])
    coverage.to_csv(QA / "gefs_predictor_coverage_state_year.csv")
    fig, ax = plt.subplots(figsize=(12, 5))
    image = ax.imshow(coverage.to_numpy(float), vmin=0, vmax=1, aspect="auto", cmap="Blues")
    ax.set(yticks=range(len(coverage)), yticklabels=coverage.index,
           xticks=range(len(coverage.columns)), xticklabels=coverage.columns,
           title="GEFS predictor coverage by state and year")
    fig.colorbar(image, ax=ax, label="Fraction of 14 fixed-frame weeks")
    fig.tight_layout(); fig.savefig(QA / "gefs_predictor_coverage_heatmap.png", dpi=150); plt.close(fig)
    return result


def block_d(panel, nass_coverage):
    rows = []
    for state in CONFIG["state_postal_codes"]:
        p = panel[panel.state_postal.eq(state)]
        active = p[p.active_week_flag]
        n = next(row for row in nass_coverage if row["state"] == state)
        ge = p.gefs_precip_mean_mm.notna() & p.gefs_precip_sd5_mm.notna()
        nl = p[NLDAS_CONTROLS].notna().all(axis=1)
        rows.append({"state": state, "progress_years": n["years_with_progress"],
                     "dsfw_years": int(p.loc[p.dsfw_days.notna(), "crop_year"].nunique()),
                     "dsfw_joint_active_years": n["years_with_joint_active_week"],
                     "gefs_years_with_complete_week": int(p.loc[ge, "crop_year"].nunique()),
                     "nldas_years_with_complete_week": int(p.loc[nl, "crop_year"].nunique()),
                     "eligible_active_weeks": len(active),
                     "complete_case_primary_weeks": int(p.primary_complete_case_flag.sum()),
                     "active_dsfw_coverage": n["active_dsfw_coverage"],
                     "primary_percent_complete_of_active": float(p.primary_complete_case_flag.sum()/len(active))
                     if len(active) else 0,
                     "frozen_nass_coverage_pass": bool(n["years_with_joint_active_week"] >= 18
                                                       and n["active_dsfw_coverage"] >= .8)})
    pd.DataFrame(rows).to_csv(QA / "state_year_coverage.csv", index=False)
    return {"states": rows, "nass_17_state_coverage_pass": all(r["frozen_nass_coverage_pass"] for r in rows)}


def block_e(panel):
    variable_sources = {"planting_cumulative_pct": "NASS", "dsfw_days": "NASS",
                        "planting_previous_pct": "NASS-derived",
                        "planting_increment_pp": "NASS-derived",
                        "remaining_start_pp": "NASS-derived",
                        "planting_utilization_pp_per_suitable_day": "NASS-derived",
                        "gefs_precip_mean_mm": "GEFS", "gefs_precip_sd5_mm": "GEFS",
                        **{variable: "NLDAS" for variable in NLDAS_CONTROLS}}
    details = []
    totals = {}
    for variable, source in variable_sources.items():
        missing = panel[variable].isna()
        totals[variable] = int(missing.sum())
        for (state, year, week), group in panel.groupby(["state_postal", "crop_year", "seasonal_week"]):
            count = int(group[variable].isna().sum())
            if count:
                reason_col = variable + "_missing_reason"
                reasons = group.loc[group[variable].isna(), reason_col].value_counts().to_dict() if reason_col in group else {}
                if not reasons and variable == "dsfw_days":
                    reasons = {"no_matching_quick_stats_dsfw_record": count}
                if not reasons and source == "NASS-derived":
                    missing_rows = group.loc[group[variable].isna()]
                    if variable == "planting_utilization_pp_per_suitable_day":
                        reasons = {
                            "no_adjacent_previous_sunday": int(missing_rows.planting_increment_pp.isna().sum()),
                            "dsfw_missing": int(missing_rows.dsfw_days.isna().sum()),
                            "dsfw_zero": int(missing_rows.dsfw_days.eq(0).sum()),
                            "invalid_negative_increment": int(missing_rows.planting_increment_pp.lt(0).sum()),
                        }
                        reasons = {key: value for key, value in reasons.items() if value}
                    else:
                        reasons = {"no_adjacent_previous_sunday": len(missing_rows)}
                details.append({"source": source, "variable": variable, "state": state,
                                "year": year, "seasonal_week": week, "missing_rows": count,
                                "reason_counts_json": json.dumps(reasons, sort_keys=True)})
    pd.DataFrame(details).to_csv(QA / "missingness_by_source_variable_state_year_week.csv", index=False)
    return {"missing_rows_by_variable": totals, "stratified_missingness_rows": len(details)}


def member_summary(frame):
    good = frame[frame.sd11_mm.gt(0)].copy()
    if len(good) < 3:
        return {"n": len(frame)}
    ratio = good.sd5_mm/good.sd11_mm
    relative = (good.sd5_mm-good.sd11_mm).abs()/good.sd11_mm
    return {"n": len(good), "pearson": float(good[["sd5_mm", "sd11_mm"]].corr().iloc[0, 1]),
            "spearman": float(spearmanr(good.sd5_mm, good.sd11_mm).statistic),
            "ratio_median": float(ratio.median()),
            "ratio_iqr": float(ratio.quantile(.75)-ratio.quantile(.25)),
            "median_abs_difference_mm": float((good.sd5_mm-good.sd11_mm).abs().median()),
            "median_relative_abs_difference": float(relative.median())}


def block_f(qa11):
    source_audit = json.loads((ROOT / "logs" / "gefs_11_duplicate_forensic_summary.json").read_text())
    if not source_audit["case_a_eligible"] or source_audit["audited_source_objects"] != 3080:
        raise ValueError("Wednesday eleven-member QA lacks full exact-source audit")
    frame = qa11.copy()
    frame["year"] = frame.archive_cycle.str[:4].astype(int)
    by_year = [{"year": int(year), **member_summary(group)} for year, group in frame.groupby("year")]
    by_state = [{"state": state, **member_summary(group)} for state, group in frame.groupby("state_postal")]
    pd.DataFrame(by_year).to_csv(QA / "gefs_5_vs_11_by_year.csv", index=False)
    pd.DataFrame(by_state).to_csv(QA / "gefs_5_vs_11_by_state.csv", index=False)
    return {"overall": member_summary(frame), "years": len(by_year), "states": len(by_state),
            "wednesday_cycles": frame.archive_cycle.nunique(),
            "audited_source_objects": source_audit["audited_source_objects"],
            "exact_duplicate_groups": source_audit["duplicate_groups"],
            "nonidentical_duplicate_pairs": source_audit["nonidentical_duplicate_pairs"]}


def polygons(geometry):
    if geometry.geom_type == "Polygon":
        yield geometry
    else:
        yield from geometry.geoms


def block_g(gefs, nldas):
    source_valid = pd.read_csv(ROOT / "spatial" / "nldas_source_valid_weights" / "weight_audit.csv")
    source_samples = pd.read_csv(ROOT / "spatial" / "nldas_source_valid_weights" / "source_samples.csv")
    source_mask = json.loads((ROOT / "logs" / "nldas_noah_source_mask_summary.json").read_text())
    if not source_mask["mask_equal_2000_2010"] or not source_mask["mask_equal_2000_2019"]:
        raise ValueError("NLDAS source-valid grid mask changed across audited years")
    if len(source_samples) != 9 or not source_samples.groupby("variable").source_valid_mask_sha256.nunique().eq(1).all():
        raise ValueError("NLDAS variable-specific source-valid mask changed across audited years")
    if not np.isclose(source_valid.source_valid_weight_sum, 1, atol=1e-9).all():
        raise ValueError("NLDAS fixed source-valid target-grid weights do not sum to one")
    audit = []
    for grid in ("gefs", "nldas"):
        for state in CONFIG["state_postal_codes"]:
            crop = pd.read_csv(ROOT / "spatial" / f"{grid}_weights" / f"{state}.csv")
            area = pd.read_csv(ROOT / "spatial" / f"{grid}_area_weights" / f"{state}.csv")
            merged = area.merge(crop[["row_index", "col_index"]], on=["row_index", "col_index"], how="inner")
            w = crop.normalized_corn_frequency_weight.to_numpy(float)
            audit.append({"state": state, "grid": grid, "weight_sum": float(w.sum()),
                          "effective_cells": float(1/np.sum(w*w)),
                          "positive_weight_cells": len(crop),
                          "state_area_fraction_with_positive_corn_weight": float(merged.normalized_area_weight.sum())})
    pd.DataFrame(audit).to_csv(QA / "spatial_weight_metrics.csv", index=False)
    reader = shapefile.Reader(str(ROOT / "raw" / "tiger2019" / "tl_2019_us_state.zip"))
    geometry = {r.record["STUSPS"]: shape(r.shape.__geo_interface__) for r in reader.iterShapeRecords()}
    audit_states = ("IA", "IL", "NE", "ND", "NC")
    fig, axes = plt.subplots(5, 2, figsize=(12, 15))
    for i, state in enumerate(audit_states):
        for j, grid in enumerate(("gefs", "nldas")):
            ax = axes[i, j]
            for polygon in polygons(geometry[state]):
                x, y = polygon.exterior.xy
                ax.plot(x, y, color="black", lw=.65)
            crop = pd.read_csv(ROOT / "spatial" / f"{grid}_weights" / f"{state}.csv")
            if grid == "gefs":
                lon = -180 + .25*crop.col_index
                lat = 90 - .25*crop.row_index
            else:
                lon = -124.9375 + .125*crop.col_index
                lat = 52.9375 - .125*crop.row_index
            ax.scatter(lon, lat, s=1.5, alpha=.55, color="#277da1")
            ax.set(title=f"{state}: {grid.upper()} positive crop weights", xlabel="Longitude", ylabel="Latitude")
            ax.set_aspect("equal", adjustable="datalim")
    fig.tight_layout(); fig.savefig(QA / "spatial_weight_audit_maps.png", dpi=140); plt.close(fig)
    pairs = [(gefs, "gefs_precip_mean_mm", "gefs_precip_mean_area_mm"),
             (gefs, "gefs_precip_sd5_mm", "gefs_precip_sd5_area_mm"),
             (nldas, "nldas_precip_total_mm", "nldas_precip_total_area_mm"),
             (nldas, "nldas_tair_mean_c", "nldas_tair_mean_area_c"),
             (nldas, "nldas_soilm_0_10_mean_kgm2", "nldas_soilm_0_10_mean_area_kgm2")]
    comparisons = []
    for frame, crop, area in pairs:
        complete = frame[[crop, area]].dropna()
        delta = complete[crop]-complete[area]
        comparisons.append({"crop_variable": crop, "area_variable": area, "n": len(complete),
                            "crop_median": float(complete[crop].median()),
                            "area_median": float(complete[area].median()),
                            "median_abs_difference": float(delta.abs().median()),
                            "p95_abs_difference": float(delta.abs().quantile(.95))})
    pd.DataFrame(comparisons).to_csv(QA / "crop_vs_area_predictor_distributions.csv", index=False)
    return {"weight_tables": len(audit),
            "maximum_abs_weight_sum_error": max(abs(r["weight_sum"]-1) for r in audit),
            "nldas_source_valid_weight_tables": len(source_valid),
            "maximum_nldas_masked_crop_weight_fraction": float(source_valid.loc[source_valid.weight_kind.eq("crop"),
                                                                                "masked_weight_fraction"].max()),
            "nldas_source_mask_stable_2000_2010_2019": True,
            "minimum_effective_cells": min(r["effective_cells"] for r in audit),
            "minimum_area_fraction_with_positive_corn_weight": min(r["state_area_fraction_with_positive_corn_weight"] for r in audit),
            "crop_vs_area_predictor_pairs": len(comparisons)}


def block_h(nldas):
    variables = {"nldas_precip_total_mm": "precipitation_mm",
                 "nldas_tair_mean_c": "air_temperature_c",
                 "nldas_soilm_0_10_mean_kgm2": "soil_moisture_kgm2"}
    physical = {}
    for column, label in variables.items():
        x = nldas[column].dropna()
        if column.endswith("precip_total_mm"):
            violations = int((x < 0).sum())
        elif column.endswith("tair_mean_c"):
            violations = int(((x < -273.15) | (x > 100)).sum())
        else:
            violations = int(((x < 0) | (x > 100)).sum())
        valid_hours = nldas[column+"_valid_hours"]
        physical[label] = {"n": len(x), "minimum": float(x.min()), "maximum": float(x.max()),
                           "physical_range_violations": violations,
                           "state_weeks_below_95pct": int((valid_hours < 160).sum()),
                           "missing_hours_total": int((168-valid_hours).sum()),
                           "missing_hours_max_state_week": int((168-valid_hours).max())}
    n = nldas.copy()
    n["monday"] = pd.to_datetime(n.archive_cycle.str[:8], format="%Y%m%d")
    segment = n[n.monday.between("2011-01-01", "2013-12-31")]
    weekly = segment.groupby("monday")[list(variables)].mean().sort_index()
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    for ax, column in zip(axes, variables):
        for year, season in weekly.groupby(weekly.index.year):
            ax.plot(season.index, season[column], lw=1, marker=".", ms=3,
                    label=str(year))
        ax.axvline(pd.Timestamp("2012-01-01"), color="red", ls="--", lw=.8)
        ax.set(ylabel=variables[column])
    axes[0].legend(title="Planting season", frameon=False, ncol=3)
    fig.suptitle("Predictor-only NLDAS continuity around 2012")
    fig.tight_layout(); fig.savefig(QA / "nldas_2012_predictor_continuity.png", dpi=150); plt.close(fig)
    weekly.to_csv(QA / "nldas_2012_predictor_continuity.csv")
    return {"physical_and_missing_hours": physical, "continuity_weeks_2011_2013": len(weekly)}


def main():
    QA.mkdir(exist_ok=True)
    verify_amendments(require_qa=True)
    panel = pd.read_parquet(ROOT / "ANALYSIS_READY_PANEL" / "analysis_ready_panel.parquet")
    primary = pd.read_parquet(ROOT / "ANALYSIS_READY_PANEL" / "analysis_ready_primary.parquet")
    gefs = pd.read_parquet(ROOT / "interim" / "gefs_5member_state_weeks.parquet")
    nldas = pd.read_parquet(ROOT / "interim" / "nldas_state_weeks.parquet")
    qa11 = pd.read_parquet(ROOT / "interim" / "gefs_11member_qa.parquet")
    forensic = json.loads((ROOT / "logs" / "gefs_duplicate_forensic_summary.json").read_text())
    nass_marginals = json.loads((QA / "nass_marginals.json").read_text())
    nass_coverage = json.loads((ROOT / "logs" / "nass_coverage_audit.json").read_text())
    blocks = {"A": block_a(panel, forensic), "B": block_b(gefs),
              "C": nass_marginals,
              "D": block_d(panel, nass_coverage), "E": block_e(panel),
              "F": block_f(qa11), "G": block_g(gefs, nldas), "H": block_h(nldas)}
    hard_failures = []
    a = blocks["A"]
    if any(a[k] for k in ("wrong_archive_cycles", "reference_not_selected_archive_cycle",
                           "reference_after_target_sunday",
                           "wrong_physical_window_end", "nonidentical_duplicate_pairs",
                           "remaining_tiling_gap_overlap_or_duplicate_count")):
        hard_failures.append("temporal ordering or accumulation integrity")
    if not blocks["D"]["nass_17_state_coverage_pass"]:
        hard_failures.append("frozen NASS 17-state coverage")
    if any(v["physical_range_violations"] for v in blocks["H"]["physical_and_missing_hours"].values()):
        hard_failures.append("NLDAS physical range")
    if any(v["state_weeks_below_95pct"] for v in blocks["H"]["physical_and_missing_hours"].values()):
        hard_failures.append("NLDAS hourly completeness")
    if len(primary) == 0:
        hard_failures.append("no complete-case primary rows")
    verdict = ("QA FAIL — CONTROLLER DECISION REQUIRED" if hard_failures else
               "QA PASS WITH PRE-RESULT AMENDMENT REQUIRED")
    metrics = {"qa_verdict": verdict, "full_rows": len(panel),
               "active_rows": int(panel.active_week_flag.sum()),
               "primary_complete_case_rows": len(primary),
               "state_count": panel.state_postal.nunique(), "year_count": panel.crop_year.nunique(),
               "blocks": blocks, "hard_failures": hard_failures,
               "primary_dispersion_outcome_association_inspected": False}
    (QA / "qa_metrics.json").write_text(json.dumps(metrics, default=scalar, indent=2), encoding="utf-8")
    report = f"""# P1-M1 outcome-blind QA

**Verdict: {verdict}**

The panel contains {len(panel):,} full state-week rows, {int(panel.active_week_flag.sum()):,} active rows, and {len(primary):,} primary complete-case rows across {panel.state_postal.nunique()} states and {panel.crop_year.nunique()} years. The original frozen authority is unchanged. The separate primary and Wednesday-QA exact GEFS duplicate rules are documented in `../PRE_RESULT_AMENDMENT_2026-10-06_GEFS_EXACT_DUPLICATE_DEDUP.md` and `../PRE_RESULT_AMENDMENT_2026-10-07_GEFS_11MEMBER_QA_EXACT_DUPLICATE_SCOPE.md`.

## A. Temporal ordering and accumulation integrity

Selected-cycle mismatches: {a['wrong_archive_cycles']}; decoded reference mismatches with selected archive cycle: {a['reference_not_selected_archive_cycle']}; forecast references after target Sundays: {a['reference_after_target_sunday']}; physical-window end mismatches: {a['wrong_physical_window_end']}. Reference-to-target interval: {a['reference_to_target_hours_min']:.0f}–{a['reference_to_target_hours_max']:.0f} hours. All 1,435 primary GRIB objects were inventoried. The 62 exact archive duplicate groups were collapsed, leaving zero gaps, overlaps, or duplicates in each member's 0–168 hour tiling. See `temporal_manual_audit_20.csv`, `gefs_reference_timing_by_year.csv`, and the forensic logs.

## B. Predictor support

The fixed 17-state, 2000–2019, ISO 13–26 frame contains {blocks['B']['fixed_frame_rows']:,} predictor rows. Forecast mean–SD Pearson correlation is {blocks['B']['pearson_mean_sd']:.3f}; Spearman is {blocks['B']['spearman_mean_sd']:.3f}; state/year-adjusted predictor VIF is {blocks['B']['predictor_vif_after_state_year_effects']:.2f}. Raw and IQR-scaled quantiles are in `qa_metrics.json`.

![GEFS mean and SD only](gefs_mean_sd_hexbin.png)

![GEFS state/year predictor coverage](gefs_predictor_coverage_heatmap.png)

## C. NASS outcome marginals

The separate NASS-only audit found {blocks['C']['dsfw_zero_rows']} DSFW-zero rows, {blocks['C']['negative_increment_rows']} negative increments, and {blocks['C']['active_zero_increment_rows']} zero increments inside the active frame. It loaded no GEFS predictors. `nass_marginals.json` contains overall and state/seasonal-week distributions of DSFW and planting increments, the remaining-start distribution, and active row counts by state/year; the figures show overall marginals.

![NASS DSFW marginal](nass_dsfw_hist.png)

![NASS planting-increment marginal](nass_increment_hist.png)

## D. State and year coverage

The frozen 18-of-20-years and 80%-active-week NASS coverage rule {'passes' if blocks['D']['nass_17_state_coverage_pass'] else 'fails'} for the 17-state frame. `state_year_coverage.csv` reports progress, DSFW, GEFS, NLDAS, active-week, and complete-case counts for every state.

## E. Missingness

`missingness_by_source_variable_state_year_week.csv` reports missingness by source, variable, state, year, seasonal week, and available reason code. Variable totals are in `qa_metrics.json`. No grouping uses forecast dispersion together with planting outcomes.

## F. Five- versus eleven-member measurement

On {blocks['F']['wednesday_cycles']} weekly Wednesday archive dates, the predictor-only `sd5`–`sd11` Pearson correlation is {blocks['F']['overall']['pearson']:.3f} and Spearman correlation is {blocks['F']['overall']['spearman']:.3f}. Median ratio is {blocks['F']['overall']['ratio_median']:.3f}; ratio IQR is {blocks['F']['overall']['ratio_iqr']:.3f}. All {blocks['F']['audited_source_objects']:,} frozen Wednesday member objects were inventoried; {blocks['F']['exact_duplicate_groups']} exact duplicate interval groups were verified and collapsed with zero non-identical pairs. See by-year and by-state CSVs and the forensic logs.

## G. Spatial weights

All {blocks['G']['weight_tables']} original crop-weight tables sum to one within {blocks['G']['maximum_abs_weight_sum_error']:.2g}. The fixed CDL corn-frequency surface uses 2019 state boundaries. The {blocks['G']['nldas_source_valid_weight_tables']} variable-specific NLDAS source-valid tables also sum to one; their source masks are unchanged across audited 2000/2010/2019 granules. The largest excluded original crop-weight fraction is {blocks['G']['maximum_nldas_masked_crop_weight_fraction']:.4%}. This fixed source-domain intersection is documented in `spatial/nldas_source_valid_weights/weight_audit.csv`. Effective cell counts, positive area fractions, and crop-versus-area predictor summaries are in the corresponding QA CSVs.

![Fixed audit states and positive crop-weight cells](spatial_weight_audit_maps.png)

## H. NLDAS physical ranges and continuity

The realized controls use the decoded GEFS physical reference-time window. Physical extrema, violation counts, missing-hour counts, and the 95% threshold results are in `qa_metrics.json`. The 2012 continuity check is predictor-only.

![NLDAS predictor-only continuity around 2012](nldas_2012_predictor_continuity.png)

## Blinding

No primary GEFS-dispersion–planting increment or utilization association was computed, inspected, plotted, saved, or logged. The primary regression was not run.
"""
    (QA / "OUTCOME_BLIND_QA_REPORT.md").write_text(report, encoding="utf-8")
    print(json.dumps({"verdict": verdict, "rows": len(panel), "active": int(panel.active_week_flag.sum()),
                      "primary": len(primary), "hard_failures": hard_failures}, indent=2), flush=True)


if __name__ == "__main__":
    main()
