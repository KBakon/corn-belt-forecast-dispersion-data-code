# PANEL_CONSTRUCTION_SPEC

**Project:** Corn Belt Forecast-State Planting Utilization (F1)  
**Version:** 1.0  
**Date:** 2026-10-05  
**Status:** FROZEN BEFORE PRIMARY ASSOCIATION

## 1. Unit of analysis

One row per **state × NASS week-ending Sunday × crop-year** for corn, 2000–2019, within the 17-state primary frame.

Key fields:

- `state_fips`, `state_name`
- `crop = CORN`
- `crop_year`
- `week_ending_sunday`
- `seasonal_week` (ISO week number of `week_ending_sunday`; retained as integer and categorical factor)
- `gefs_archive_cycle`
- `gefs_reference_time_utc`
- `forecast_window_start_utc`, `forecast_window_end_utc`

## 2. Outcome interval

For target NASS week ending Sunday `S_t`:

- previous cumulative planting progress: `P_prev = P(S_t - 7 days)`
- current cumulative planting progress: `P_curr = P(S_t)`
- weekly increment: `planting_increment_pp = P_curr - P_prev`
- remaining unplanted acreage at interval start: `remaining_start_pp = 100 - P_prev`

The conceptual planting interval is the week between the two Sunday NASS reference dates. Meteorological/forecast variables use the matched seven-day forecast window defined below.

Do not interpolate missing weekly cumulative progress. No isotonic smoothing or monotonic repair is allowed in the primary construction.

## 3. Primary active-planting-week rule

A row is in the confirmatory active-week analysis frame iff, at the **start** of the interval:

`5 <= P_prev < 95`

This rule uses only the lagged cumulative state at the start of the interval and avoids selecting rows based on the current-week planting increment. Zero weekly increments inside this active frame are retained.

Prespecified sensitivity: fixed calendar planting frame of ISO weeks 14–24, without the 5/95 filter.

## 4. DSFW and utilization outcome

Let `DSFW_t` be NASS Days Suitable for Fieldwork for the target week ending `S_t`.

Primary utilization for rows with `DSFW_t > 0`:

`planting_utilization_pp_per_suitable_day = planting_increment_pp / DSFW_t`

### DSFW = 0

- retain the row in the full analysis-ready panel;
- set the ratio outcome to missing / undefined, never to zero or infinity;
- add `dsfw_zero_flag = 1`;
- flag any `DSFW=0` row with nonzero planting increment for semantic/revision QA;
- exclude `DSFW=0` only from the primary ratio regression;
- prespecified sensitivity: model weekly planting increment directly with DSFW and the same physical/opportunity controls so zero-DSFW weeks remain estimable.

## 5. NASS validity rules

- Require `0 <= P_prev <= 100`, `0 <= P_curr <= 100`, and `0 <= DSFW <= 7`.
- A negative weekly increment is **not** silently clipped or smoothed. It is physically invalid as a planting-utilization observation, so retain the row/value in the full panel, set `increment_valid_flag = 0`, set the primary utilization outcome to missing, and exclude it from the confirmatory ratio regression. The count and provenance of such rows are reported in QA.
- Duplicate state-week observations after source filtering are a hard error until source dimensions are reconciled.

## 6. Forecast initialization cutoff and temporal ordering

For target week ending Sunday `S_t`:

`archive_cycle_date = S_t - 6 days` (the Monday immediately after the prior NASS Sunday).

Use the GEFSv12 reforecast archive cycle stored under `YYYYMMDD00` for that Monday. The actual GRIB reference time is read from metadata and stored in `gefs_reference_time_utc`; if Phase-2 files encode 03 UTC, that timestamp is used as the physical start without changing the selected archive cycle.

The seven-day forecast horizon is:

`[gefs_reference_time_utc, gefs_reference_time_utc + 168 hours]`

No data initialized after that reference time may enter the forecast-state features.

## 7. Primary GEFS precipitation state

### 7.1 Member-level quantity

For each of the standard five members `c00, p01, p02, p03, p04`:

1. extract `apcp_sfc`;
2. tile forecast hours 0–168 exactly once using GRIB accumulation start/end metadata;
3. sum to a 7-day precipitation total at each grid cell (mm);
4. apply fixed corn-frequency state weights;
5. obtain one state-level 7-day total per member, `Q_m` (mm).

### 7.2 Forecast mean

`gefs_precip_mean_mm = mean(Q_m)` across the five standard members.

### 7.3 Primary forecast dispersion

`gefs_precip_sd5_mm = sample_sd(Q_m)` across the same five members, denominator `n-1`.

This is an objective forecast-distribution / predictability state. It is not labeled farmer-perceived uncertainty.

### 7.4 Scaling

Compute the pooled IQR and median of the raw five-member mean and SD over the fixed design frame:

- all 17 primary states;
- 2000–2019;
- ISO weeks 13–26;
- no conditioning on current planting increment or utilization.

Create:

`gefs_precip_mean_iqr = (mean_mm - pooled_median_mean) / pooled_IQR_mean`

`gefs_precip_sd5_iqr = (sd5_mm - pooled_median_sd) / pooled_IQR_sd`

The primary dispersion coefficient is therefore the utilization difference associated with a one-IQR shift in forecast dispersion, holding the mean and other controls fixed.

## 8. Ensemble-member-count measurement QA

Where an 11-member reforecast exists, construct a separate outcome-blind QA comparison:

- `sd5` using `c00,p01,p02,p03,p04`;
- `sd11` using `c00,p01,...,p10`.

Report correlation, Spearman rank correlation, median `sd5/sd11`, IQR of the ratio, and state/year variation. Do not relate either measure to planting outcomes during this QA.

## 9. Realized NLDAS-2 controls

Use the same physical seven-day window as the GEFS horizon and the same fixed crop-area weights.

Primary controls:

- `nldas_precip_total_mm`: sum of hourly `NLDAS_FORA0125_H.2.0:Rainf` over the matched window;
- `nldas_tair_mean_c`: mean hourly `Tair` over the matched window, converted K -> C;
- `nldas_soilm_0_10_mean_kgm2`: mean hourly `NLDAS_NOAH0125_H.2.0:SoilM_0_10cm` over the matched window.

Prespecified soil-state sensitivity:

- `nldas_soilm_0_10_start_kgm2`: first available hourly top-layer soil-moisture observation at/after the forecast reference time, used in place of weekly mean soil moisture.

## 10. State/crop inclusion rule

Primary crop: corn only.

Primary states: CO, IL, IN, IA, KS, KY, MI, MN, MO, NE, NC, ND, OH, PA, SD, TN, WI.

Texas is excluded from the primary frame because DSFW is structurally missing before 2014 and no cross-state proxy will be introduced.

A primary state remains eligible if NASS planting progress and DSFW jointly cover at least 18 of the 20 study years and at least 80% of its otherwise eligible start-state active weeks. If this rule fails, exclusion is made and logged **before any dispersion–outcome association is viewed**. No replacement state is added post hoc.

## 11. Missing-data policy

- no primary-outcome, GEFS, NLDAS, or DSFW imputation;
- complete-case estimation on the frozen primary variables after active-week and `DSFW>0` rules;
- source-specific missingness flags retained in the full panel;
- missingness summarized by state, year, source, and seasonal week before association analysis;
- a missingness pattern that threatens support or temporal validity triggers Controller adjudication before unblinding.

## 12. Bounded outcome / remaining acreage

`remaining_start_pp` remains an explicit opportunity control; it is not folded into the utilization denominator.

Primary model includes both:

- `remaining_start_pp`
- `remaining_start_pp^2`

This predeclared curvature accommodates the bounded opportunity set without converting the scientific outcome into a different estimand.

## 13. Spatial aggregation sensitivity

Primary: fixed 2008–2019 CDL corn-frequency weights within 2019 state boundaries.

Prespecified sensitivity: simple state-land-area mean for GEFS and NLDAS variables. Any further weighting scheme is exploratory unless added by a pre-result amendment.

## 14. Analysis-ready panel outputs

Required machine-readable outputs:

- `analysis_ready_panel.parquet` — full panel, including ineligible/zero-DSFW rows and flags;
- `analysis_ready_primary.parquet` — frozen primary complete-case estimation frame;
- `data_dictionary.csv` — one row per field with type, units, source, construction, role, allowed missingness;
- `data_dictionary.json` — same dictionary in machine-readable JSON;
- `source_manifest.csv` — raw objects/queries/checksums;
- `panel_build_log.json` — counts and hard/soft QA events.
