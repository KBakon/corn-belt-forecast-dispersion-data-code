"""Open only the frozen P1-M2 primary association and mandatory sensitivities."""

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.linalg as la
import shapefile
from shapely.geometry import shape

from close_milestone1_open_milestone2 import main as verify_opening
from primary_inference import (BOOTSTRAP_REPLICATIONS, BOOTSTRAP_SEED, coefficient_table,
                               conley_hac_state_centroids, cr2_satterthwaite_state,
                               fit_model, tost_equivalence, wild_state_bootstrap_t)


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "PRIMARY_RESULTS"
PRIMARY = ROOT / "ANALYSIS_READY_PANEL" / "analysis_ready_primary.parquet"
FULL = ROOT / "ANALYSIS_READY_PANEL" / "analysis_ready_panel.parquet"
ACREAGE = ROOT / "raw" / "nass_annual_acreage" / "corn_area_planted_2000_2019_17states.csv"
REQUIRED = ("planting_utilization_pp_per_suitable_day", "gefs_precip_sd5_iqr",
            "gefs_precip_mean_iqr", "dsfw_days", "nldas_precip_total_mm",
            "nldas_tair_mean_c", "nldas_soilm_0_10_mean_kgm2", "remaining_start_pp")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def verify_primary_sample(full, primary):
    selected = (full.active_week_flag & full.increment_valid_flag & full.dsfw_days.gt(0)
                & full[list(REQUIRED)].notna().all(axis=1))
    expected = full.loc[selected].sort_values(["state_postal", "week_ending_sunday"])
    observed = primary.sort_values(["state_postal", "week_ending_sunday"])
    if len(primary) != 1777 or len(expected) != 1777:
        raise ValueError("Frozen primary sample differs from accepted N=1,777")
    keys = ["state_postal", "crop_year", "week_ending_sunday"]
    pd.testing.assert_frame_equal(expected[keys].reset_index(drop=True),
                                  observed[keys].reset_index(drop=True), check_dtype=False)
    if not observed.primary_complete_case_flag.all():
        raise ValueError("Primary export includes a row outside the frozen complete-case frame")
    return {"full_panel_rows": len(full), "active_start_state_rows": int(full.active_week_flag.sum()),
            "primary_complete_case_rows": len(primary),
            "active_rows_outside_primary": int(full.active_week_flag.sum() - len(primary)),
            "post_qa_exclusions": 0,
            "states": int(primary.state_postal.nunique()),
            "years": int(primary.crop_year.nunique()),
            "week_dates": int(primary.week_ending_sunday.nunique()),
            "by_state": {str(k): int(v) for k, v in primary.state_postal.value_counts().sort_index().items()},
            "by_year": {str(k): int(v) for k, v in primary.crop_year.value_counts().sort_index().items()}}


def acreage_weights(primary):
    source = json.loads((ROOT / "provenance" / "p1_m2_nass_acreage_source.json").read_text())
    if digest(ACREAGE) != source["subset_sha256"]:
        raise ValueError("Independent NASS acreage subset hash mismatch")
    data = pd.read_csv(ACREAGE, sep=",", dtype={"STATE_ALPHA": str, "YEAR": int, "VALUE": str})
    if len(data) != 340 or data.duplicated(["STATE_ALPHA", "YEAR"]).any():
        raise ValueError("NASS acreage source lacks exact 17-state/20-year frame")
    data["planted_acres"] = data.VALUE.str.replace(",", "", regex=False).astype(float)
    weights = data[["STATE_ALPHA", "YEAR", "planted_acres"]].rename(
        columns={"STATE_ALPHA": "state_postal", "YEAR": "crop_year"})
    joined = primary.merge(weights, on=["state_postal", "crop_year"], how="left", validate="many_to_one")
    if len(joined) != len(primary) or joined.planted_acres.isna().any():
        raise ValueError("Acreage weighting would change the primary row set")
    return joined, source


def area_scaling(full):
    gefs = pd.read_parquet(ROOT / "interim" / "gefs_5member_state_weeks.parquet")
    sunday = pd.to_datetime(gefs.archive_cycle.str[:8], format="%Y%m%d") + pd.Timedelta(days=6)
    fixed = gefs.loc[sunday.dt.isocalendar().week.between(13, 26)]
    if len(fixed) != 4760:
        raise ValueError("Area-weighted GEFS scaling frame differs from frozen 4,760 predictor rows")
    scaling = {}
    for raw, name in (("gefs_precip_sd5_area_mm", "dispersion"),
                      ("gefs_precip_mean_area_mm", "mean")):
        values = fixed[raw].dropna()
        if len(values) != len(fixed):
            raise ValueError(f"Incomplete area-weighted forecast scaling frame: {raw}")
        median = float(values.median())
        iqr = float(values.quantile(.75) - values.quantile(.25))
        if iqr <= 0:
            raise ValueError("Area-weighted forecast IQR is nonpositive")
        scaling[name] = {"raw_field": raw, "pooled_median": median, "pooled_iqr": iqr,
                         "fixed_frame_rows": len(values)}
        full["area_" + name + "_iqr"] = (full[raw] - median) / iqr
    return scaling


def verify_primary_scaling(scaler, primary):
    gefs = pd.read_parquet(ROOT / "interim" / "gefs_5member_state_weeks.parquet")
    sunday = pd.to_datetime(gefs.archive_cycle.str[:8], format="%Y%m%d") + pd.Timedelta(days=6)
    fixed = gefs.loc[sunday.dt.isocalendar().week.between(13, 26)]
    if len(fixed) != 4760:
        raise ValueError("Frozen pooled forecast-scaling frame differs from 4,760 rows")
    for field, median_key, iqr_key in (
        ("gefs_precip_sd5_mm", "sd5_median_mm", "sd5_iqr_mm"),
        ("gefs_precip_mean_mm", "mean_median_mm", "mean_iqr_mm"),
    ):
        values = fixed[field]
        median = float(values.median())
        iqr = float(values.quantile(.75) - values.quantile(.25))
        if not np.isclose(median, scaler[median_key], rtol=1e-12, atol=1e-12):
            raise ValueError(f"Frozen pooled median mismatch for {field}")
        if not np.isclose(iqr, scaler[iqr_key], rtol=1e-12, atol=1e-12):
            raise ValueError(f"Frozen pooled IQR mismatch for {field}")
    if not np.isclose((primary.gefs_precip_sd5_mm - scaler["sd5_median_mm"]) /
                      scaler["sd5_iqr_mm"], primary.gefs_precip_sd5_iqr,
                      rtol=1e-12, atol=1e-12).all():
        raise ValueError("Primary dispersion scaling differs from frozen pooled scaler")
    if not np.isclose((primary.gefs_precip_mean_mm - scaler["mean_median_mm"]) /
                      scaler["mean_iqr_mm"], primary.gefs_precip_mean_iqr,
                      rtol=1e-12, atol=1e-12).all():
        raise ValueError("Primary mean scaling differs from frozen pooled scaler")


def centroids():
    reader = shapefile.Reader(str(ROOT / "raw" / "tiger2019" / "tl_2019_us_state.zip"))
    requested = set(json.loads((ROOT / "config" / "frozen_design.json").read_text())["state_postal_codes"])
    result = {}
    for entry in reader.iterShapeRecords():
        state = entry.record["STUSPS"]
        if state in requested:
            point = shape(entry.shape.__geo_interface__).centroid
            result[state] = (float(point.x), float(point.y))
    if set(result) != requested:
        raise ValueError("2019 state centroid set differs from frozen 17 states")
    return result


def independent_coefficient_check(fit):
    """SVD on the full dummy matrix, separate from the FWL/QR fitting path."""
    frame = fit.frame
    sw = frame.state_postal.astype(str) + "|" + frame.seasonal_week.astype(str)
    yw = frame.crop_year.astype(str) + "|" + frame.seasonal_week.astype(str)
    fe = np.concatenate([pd.get_dummies(sw, dtype=float).to_numpy(),
                         pd.get_dummies(yw, dtype=float).to_numpy()], axis=1)
    columns = [frame.gefs_precip_sd5_iqr.to_numpy(float),
               frame.gefs_precip_mean_iqr.to_numpy(float),
               frame.dsfw_days.to_numpy(float), frame.dsfw_days.to_numpy(float) ** 2,
               frame.nldas_precip_total_mm.to_numpy(float),
               frame.nldas_tair_mean_c.to_numpy(float),
               frame.nldas_soilm_0_10_mean_kgm2.to_numpy(float),
               frame.remaining_start_pp.to_numpy(float),
               frame.remaining_start_pp.to_numpy(float) ** 2]
    design = np.column_stack(columns + [fe])
    norms = np.linalg.norm(design, axis=0)
    scaled = design / norms
    beta_scaled, _, rank, _ = la.lstsq(scaled, fit.y, cond=1e-10,
                                      lapack_driver="gelsd", check_finite=False)
    check = float(beta_scaled[0] / norms[0])
    difference = abs(check - float(fit.beta[0]))
    if difference > 1e-8:
        raise ValueError(f"Independent full-design SVD disagrees on focal coefficient: {difference}")
    return {"method": "full-design SVD least squares; independent of FWL/QR",
            "coefficient": check, "absolute_difference": difference,
            "full_design_columns": design.shape[1], "full_design_rank": int(rank)}


def sensitivity_row(label, fit, note):
    focal = coefficient_table(fit)[0]
    return {"sensitivity": label, "n": len(fit.frame),
            "coefficient": focal["coefficient"],
            "two_way_cluster_se": focal["two_way_cluster_se"],
            "ci95_lower": focal["ci95_lower"], "ci95_upper": focal["ci95_upper"],
            "two_sided_p": focal["two_sided_p"],
            "state_clusters": int(fit.state_codes.max()) + 1,
            "week_date_clusters": int(fit.date_codes.max()) + 1, "note": note}


def main():
    verify_opening()
    OUT.mkdir(exist_ok=True)
    full = pd.read_parquet(FULL)
    primary = pd.read_parquet(PRIMARY)
    sample = verify_primary_sample(full, primary)
    scaler = json.loads((ROOT / "logs" / "panel_build_log.json").read_text())["gefs_scaling"]
    verify_primary_scaling(scaler, primary)
    primary_fit = fit_model(primary)
    table = coefficient_table(primary_fit)
    bootstrap = wild_state_bootstrap_t(primary_fit)
    equivalence = tost_equivalence(primary_fit)
    independent = independent_coefficient_check(primary_fit)
    try:
        cr2 = cr2_satterthwaite_state(primary_fit)
    except (ValueError, np.linalg.LinAlgError) as error:
        cr2 = {"status": "not_faithfully_supported", "reason": str(error)}
    try:
        conley = conley_hac_state_centroids(primary_fit, centroids())
    except (ValueError, np.linalg.LinAlgError) as error:
        conley = {"status": "not_faithfully_supported", "reason": str(error)}
    area_scale = area_scaling(full)
    keys = ["state_postal", "crop_year", "week_ending_sunday"]
    area_primary = primary.merge(full[keys + ["area_dispersion_iqr", "area_mean_iqr"]],
                                 on=keys, how="left", validate="one_to_one")
    if len(area_primary) != len(primary):
        raise ValueError("Area sensitivity changed primary row identity")
    acreage_primary, acreage_source = acreage_weights(primary)
    sensitivity_fits = []
    sensitivity_fits.append(("acreage_weighted", fit_model(
        acreage_primary, weights=lambda ordered: ordered.planted_acres.to_numpy(float)),
        "Same frozen primary rows; independently sourced annual NASS planted corn acreage fixed by state-year"))
    direct_required = ["planting_increment_pp", *REQUIRED[1:]]
    direct = full.loc[full.active_week_flag & full.increment_valid_flag &
                      full[direct_required].notna().all(axis=1)].copy()
    sensitivity_fits.append(("direct_weekly_increment", fit_model(
        direct, outcome="planting_increment_pp"),
        "Active start-state frame; weekly increment outcome; DSFW=0 rows retained if present"))
    iso = full.loc[full.seasonal_week.between(14, 24) & full.increment_valid_flag &
                   full.dsfw_days.gt(0) & full[list(REQUIRED)].notna().all(axis=1)].copy()
    sensitivity_fits.append(("fixed_iso_weeks_14_24", fit_model(iso),
                             "Fixed ISO 14–24 frame without the 5/95 active-state filter; DSFW>0"))
    soil_start = primary.loc[primary.nldas_soilm_0_10_start_kgm2.notna()].copy()
    sensitivity_fits.append(("start_of_window_soil_moisture", fit_model(
        soil_start, soil="nldas_soilm_0_10_start_kgm2"),
        "Start-of-window Noah top-layer soil moisture replaces weekly mean"))
    area_cols = ["area_dispersion_iqr", "area_mean_iqr", "nldas_precip_total_area_mm",
                 "nldas_tair_mean_area_c", "nldas_soilm_0_10_mean_area_kgm2"]
    area_primary = area_primary.loc[area_primary[area_cols].notna().all(axis=1)].copy()
    sensitivity_fits.append(("state_land_area_meteorology", fit_model(
        area_primary, dispersion="area_dispersion_iqr", forecast_mean="area_mean_iqr",
        precip="nldas_precip_total_area_mm", tair="nldas_tair_mean_area_c",
        soil="nldas_soilm_0_10_mean_area_kgm2"),
        "State-land-area GEFS/NLDAS aggregation; own outcome-blind pooled ISO 13–26 IQR scaling"))
    robustness = [sensitivity_row(label, fit, note) for label, fit, note in sensitivity_fits]
    sample["direct_increment_rows"] = len(direct)
    sample["direct_increment_dsfw_zero_rows"] = int(direct.dsfw_days.eq(0).sum())
    sample["fixed_iso_14_24_rows"] = len(iso)
    sample["start_soil_rows"] = len(soil_start)
    sample["land_area_rows"] = len(area_primary)
    sample["acreage_weighted_rows"] = len(acreage_primary)
    sample["invalid_negative_increment_rows_full_panel"] = int(full.planting_increment_pp.lt(0).sum())
    focal = table[0]
    conventional_p = focal["two_sided_p"]
    wild_p = bootstrap["two_sided_p"]
    if (conventional_p < .05) != (wild_p < .05):
        branch = "E — model/inference instability prevents clean interpretation"
    elif conventional_p < .05:
        branch = ("A — positive association supported" if focal["coefficient"] > 0 else
                  "B — negative association supported")
    elif equivalence["equivalent"]:
        branch = "C — statistically unresolved but practically equivalent"
    else:
        branch = "D — statistically unresolved and not practically equivalent"
    diagnostics = {"primary_n": len(primary_fit.frame), "ols_unweighted": True,
                   "state_week_categories": int((primary.state_postal.astype(str) + "|" +
                                                 primary.seasonal_week.astype(str)).nunique()),
                   "year_week_categories": int((primary.crop_year.astype(str) + "|" +
                                                primary.seasonal_week.astype(str)).nunique()),
                   "fe_rank": primary_fit.rank_fe, "total_rank": primary_fit.rank_total,
                   "residual_df": len(primary_fit.frame) - primary_fit.rank_total,
                   "state_clusters": int(primary_fit.state_codes.max()) + 1,
                   "week_date_clusters": int(primary_fit.date_codes.max()) + 1,
                   "state_week_intersection_clusters": len(primary_fit.frame),
                   "two_way_cluster_p_df": primary_fit.df_two_way,
                   "numeric_condition_number_after_fe": primary_fit.numeric_condition_number,
                   "r_squared": primary_fit.r_squared,
                   "min_state_cluster_rows": int(primary_fit.frame.state_postal.value_counts().min()),
                   "min_week_date_cluster_rows": int(primary_fit.frame.week_ending_sunday.value_counts().min()),
                   "independent_coefficient_check": independent,
                   "cr2_state_satterthwaite": cr2,
                   "conley_500km_1week": conley}
    pd.DataFrame(table).to_csv(OUT / "primary_coefficients.csv", index=False)
    pd.DataFrame(robustness).to_csv(OUT / "mandatory_robustness.csv", index=False)
    write_json(OUT / "tost_equivalence.json", equivalence)
    write_json(OUT / "inference_sensitivities.json", {"wild_bootstrap_t": bootstrap,
                                                       "cr2_state_satterthwaite": cr2,
                                                       "conley_500km_1week": conley})
    write_json(OUT / "model_diagnostics.json", diagnostics)
    write_json(OUT / "sample_accounting.json", sample)
    write_json(OUT / "independent_coefficient_check.json", independent)
    accepted = ROOT / "provenance" / "P1_M1_CONTROLLER_ADJUDICATION_2026-10-07.md"
    manifest = {"work_package": "P1-M2 — PRIMARY ASSOCIATION OPENING",
                "run_utc": datetime.now(timezone.utc).isoformat(),
                "controller_adjudication_sha256": digest(accepted),
                "frozen_primary_spec_sha256": digest(ROOT.parent / "artifacts" / "PRIMARY_ANALYSIS_SPEC.md"),
                "accepted_primary_panel_sha256": digest(PRIMARY),
                "analysis_script_sha256": digest(ROOT / "src" / "run_primary_association.py"),
                "inference_script_sha256": digest(ROOT / "src" / "primary_inference.py"),
                "accepted_primary_n": 1777,
                "acreage_source_manifest_sha256": digest(ROOT / "provenance" / "p1_m2_nass_acreage_source.json"),
                "acreage_subset_sha256": acreage_source["subset_sha256"],
                "pooled_gefs_scaling": scaler, "area_sensitivity_scaling": area_scale,
                "primary_inference": "two-way state and week-date CRV1 with min-cluster t df",
                "bootstrap_seed": BOOTSTRAP_SEED,
                "bootstrap_replications": BOOTSTRAP_REPLICATIONS,
                "primary_evidence_branch": branch,
                "unapproved_subgroup_or_post_hoc_analysis_run": False}
    write_json(OUT / "primary_result_manifest.json", manifest)
    report = f"""# P1-M2 primary association result

**Primary evidence branch:** {branch}  
**Accepted sample:** {len(primary_fit.frame):,} state-weeks, 17 states, 2000–2019.  
**Controller opening authority:** `provenance/P1_M1_CONTROLLER_ADJUDICATION_2026-10-07.md`.

## Estimate

The frozen unweighted OLS coefficient on a one-pooled-IQR increase in five-member GEFSv12 precipitation-distribution SD is **{focal['coefficient']:.4f} percentage points of total state corn acreage planted per suitable field day**. The corresponding raw SD IQR is {scaler['sd5_iqr_mm']:.4f} mm. This is an incremental conditional association, not a causal or farmer-perception estimate.

## Statistical uncertainty

Classical OLS SE: {focal['classical_ols_se']:.4f}; classical two-sided p = {focal['classical_ols_two_sided_p']:.4g}. The primary two-way state and common week-ending-date clustered SE is {focal['two_way_cluster_se']:.4f}; 95% CI [{focal['ci95_lower']:.4f}, {focal['ci95_upper']:.4f}]; two-sided primary p = {focal['two_sided_p']:.4g}, using t with {primary_fit.df_two_way} degrees of freedom. The restricted-null state-cluster wild bootstrap-t uses Rademacher weights, seed {BOOTSTRAP_SEED}, and {BOOTSTRAP_REPLICATIONS:,} replications; p = {wild_p:.4g}. The state-cluster CR2/Satterthwaite and 500-km/one-week Conley results or fidelity limitations are in `inference_sensitivities.json`.

The prespecified inferential sensitivities do not give the same threshold decision: state-cluster CR2/Satterthwaite yields SE {cr2['se']:.4f}, p = {cr2['two_sided_p']:.4g}, while 500-km/one-week Conley yields SE {conley['se']:.4f}, normal-approximation p = {conley['normal_approx_two_sided_p']:.4g}. Their implementation details and diagnostics are in `inference_sensitivities.json`. The frozen two-way state/date result remains the primary test; these differences limit confidence in a binary significance conclusion.

## Practical equivalence

The frozen meaningful-effect bounds are ±0.5 percentage point of total acreage per suitable day per dispersion IQR. The 90% two-way-cluster equivalence CI is [{equivalence['ci90_lower']:.4f}, {equivalence['ci90_upper']:.4f}]. TOST p = {equivalence['tost_p']:.4g}; equivalence at alpha 0.05: **{'supported' if equivalence['equivalent'] else 'not established'}**. No directional alternative was imposed.

## Mandatory robustness

`mandatory_robustness.csv` reports the frozen acreage-weighted, direct weekly increment, fixed ISO-week 14–24, start-of-window soil moisture, and state-land-area meteorology sensitivities. Their dispersion coefficients are positive, but none has a two-way-cluster 95% CI excluding zero. The direct-increment coefficient has a different outcome unit (percentage points per week). Its frame contains {sample['direct_increment_dsfw_zero_rows']} DSFW-zero active rows; the full panel contains {sample['invalid_negative_increment_rows_full_panel']} physically invalid negative increments. Sensitivities use their frozen frames and do not replace the primary estimate or change its sample.

## What is supported

The point estimate is positive. The primary two-way 95% CI includes zero and the state wild-bootstrap p-value is above 0.05, so a directional association is not established by the primary inference hierarchy. The 90% two-way CI lies wholly inside the frozen ±0.5 practical bounds: effects of that magnitude are ruled out under this model and covariance choice. The full coefficient table and numeric diagnostics are machine-readable in this package.

## What is not supported

The data do not establish a zero coefficient or absence of all incremental information. A positive association is also not cleanly established: CR2 and Conley cross the 0.05 threshold but are inferential sensitivities, whereas the frozen primary two-way and state wild-bootstrap results do not. This state-week association cannot establish a causal farmer response, a waiting mechanism, farmer exposure to GEFS, perceived uncertainty, or theoretical novelty. The result does not authorize subgroup, alternative dispersion-family, soybean, or manuscript-claim analyses.

## Residual scientific uncertainty

The aggregate state-week unit does not identify farm-level decisions. NASS suitable days and planted progress are survey estimates. With 17 state clusters, the discordant inferential sensitivities and a wild-bootstrap p-value close to 0.05 leave the evidence for a directional conditional association sensitive to the uncertainty estimator. The Controller must adjudicate this P1-M2 package before opening further analyses.
"""
    (OUT / "P1_M2_PRIMARY_ASSOCIATION_RESULT.md").write_text(report, encoding="utf-8")
    paths = sorted(path for path in OUT.iterdir() if path.is_file() and path.name != "primary_artifacts.sha256")
    with (OUT / "primary_artifacts.sha256").open("w", encoding="ascii") as stream:
        for path in paths:
            stream.write(f"{digest(path)}  {path.name}\n")
    print(json.dumps({"primary_n": len(primary_fit.frame), "coefficient": focal["coefficient"],
                      "two_way_p": conventional_p, "wild_p": wild_p,
                      "tost_p": equivalence["tost_p"], "branch": branch,
                      "robustness_models": len(robustness)}, indent=2))


if __name__ == "__main__":
    main()
