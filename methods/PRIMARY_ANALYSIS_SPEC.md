# PRIMARY_ANALYSIS_SPEC

**Project:** Corn Belt Forecast-State Planting Utilization (F1)  
**Version:** 1.0  
**Date:** 2026-10-05  
**Status:** `FROZEN — DO NOT INSPECT PRIMARY DISPERSION–OUTCOME ASSOCIATION BEFORE QA PASS`  

## 1. Primary estimand

The coefficient on a **one-pooled-IQR increase in the five-member GEFSv12 1–7 day precipitation-distribution SD**, conditional on the corresponding forecast mean, realized workability/weather/soil state, remaining acreage, state-specific seasonal structure, and common year-week shocks.

Outcome unit: percentage points of total state corn acreage planted **per NASS suitable field day**.

The estimand is associational / incremental-information, not causal and not cognitive.

## 2. Primary estimation frame

- crop: corn;
- years: 2000–2019;
- 17 prespecified states;
- active start state: `5 <= P_prev < 95`;
- `DSFW > 0`;
- complete cases on all primary variables;
- no post-association sample changes except correction of proven implementation errors, which require a deviation log.

## 3. Primary model

Estimate by OLS:

`U_syt = beta_D * D_syt + beta_M * M_syt + b1*DSFW_syt + b2*DSFW_syt^2 + c1*RP_syt + c2*RT_syt + c3*SM_syt + r1*R_syt + r2*R_syt^2 + alpha_(state x seasonal_week) + lambda_(year x seasonal_week) + error_syt`

where:

- `U`: `planting_utilization_pp_per_suitable_day`;
- `D`: `gefs_precip_sd5_iqr`;
- `M`: `gefs_precip_mean_iqr`;
- `DSFW`: realized NASS Days Suitable for Fieldwork;
- `RP`: `nldas_precip_total_mm`;
- `RT`: `nldas_tair_mean_c`;
- `SM`: `nldas_soilm_0_10_mean_kgm2`;
- `R`: `remaining_start_pp`;
- `alpha_(state x seasonal_week)`: state-by-ISO-week fixed effects;
- `lambda_(year x seasonal_week)`: year-by-ISO-week fixed effects, equivalent to common week-year shocks.

No interaction with dispersion is in the primary model.

## 4. Weighting

Primary OLS is **unweighted across state-weeks**. The estimand is the average conditional state-week relationship in the prespecified major-corn-state panel, not a national acreage-weighted effect.

Prespecified sensitivity: state-year planted-corn-acreage-weighted OLS, using an independently sourced NASS planted-acreage weight fixed within a crop year. It cannot replace the primary estimate.

## 5. Forecast mean and dispersion

Forecast mean and dispersion enter separately and simultaneously. Both are median-centered and scaled by their pooled fixed-frame IQR as specified in `PANEL_CONSTRUCTION_SPEC.md`.

The primary dispersion metric is **only** sample SD across `c00,p01,p02,p03,p04` of the crop-area-weighted 168-hour precipitation total.

## 6. Realized-state controls

Primary realized-state vector is frozen as:

1. NASS DSFW and `DSFW^2`;
2. NLDAS-2 realized precipitation total;
3. NLDAS-2 weekly mean 2-m air temperature;
4. NLDAS-2 weekly mean 0–10 cm Noah soil moisture;
5. remaining unplanted acreage at interval start and its square.

Additional physical variables are not added to the confirmatory model after inspecting `beta_D`.

## 7. Dependence-robust inference

### Primary uncertainty estimate

Two-way cluster-robust covariance clustered by:

1. state; and
2. NASS week-ending date (`year x seasonal_week`).

Report point estimate, 95% confidence interval, and two-sided p-value for `beta_D`.

### Small-state-cluster sensitivity

Because the primary state dimension has only 17 clusters, report:

- wild cluster bootstrap-t by state, restricted null, Rademacher weights, 9,999 replications; and
- CR2 state-clustered standard errors with Satterthwaite degrees of freedom where supported by the chosen software.

These are inferential sensitivities, not alternate estimands.

### Spatial/serial dependence sensitivity

Report a Conley-type HAC sensitivity using state centroids / crop-weighted centroids with a prespecified 500-km spatial cutoff and 1-week temporal lag. If the software cannot reproduce this estimator faithfully, record the limitation rather than silently substituting an arbitrary HAC.

## 8. Practical significance and equivalence

Admission-stage meaningful-effect scale is frozen after unit harmonization as:

**0.5 percentage point of total state corn acreage per suitable day for a one-IQR increase in forecast dispersion.**

Report `beta_D` against ±0.5 pp/day/IQR.

- A statistically detectable effect materially below this scale is labeled scientifically small.
- Report the ordinary 95% confidence interval for estimation uncertainty.
- For equivalence, use two one-sided tests (TOST) with bounds ±0.5 and alpha=0.05; equivalently, assess whether the 90% equivalence confidence interval lies wholly inside `[-0.5, +0.5]`.

No directional alternative is preregistered.

## 9. Multiplicity

The single primary test is `beta_D` for `gefs_precip_sd5_iqr`; it is not multiplicity-adjusted.

Any alternative dispersion metrics (for example member IQR, MAD, or other spread summaries) form one **secondary dispersion family** and use Holm adjustment across that family. They cannot replace the primary SD result.

Heterogeneity tests belong to a separate preregistered family and are not opened until the primary average result is adjudicated.

## 10. Prespecified sensitivity set

1. fixed ISO weeks 14–24 instead of the 5/95 active-state filter;
2. direct weekly planting-increment model retaining `DSFW=0` weeks;
3. reported count/provenance of physically invalid negative weekly increments; no alternate confirmatory estimand is opened for these rows;
4. start-of-window NLDAS top-layer soil moisture instead of weekly mean;
5. simple state-area weather/forecast aggregation instead of fixed corn-frequency weighting;
6. acreage-weighted regression;
7. inferential alternatives in Section 7.

Sensitivity results do not alter the identity of the primary estimand.

## 11. Outcome-blind QA permitted before unblinding

Permitted:

- temporal ordering and GRIB validity/reference-time checks;
- marginal distributions of planting increment and DSFW;
- state/year/seasonal-week coverage;
- marginal missingness;
- forecast mean/dispersion support and overlap with one another;
- collinearity diagnostics among **predictors only**;
- five-vs-eleven-member spread measurement sensitivity;
- NLDAS/GEFS physical-range and spatial-weight checks.

Forbidden before freeze/QA pass:

- correlation between dispersion and planting increment/utilization;
- regression with any planting outcome on the left-hand side and dispersion on the right;
- scatterplots, bins, subgroup tables, or residual plots revealing the dispersion–outcome relationship;
- choosing transformations, states, weeks, or dispersion metrics because they improve the main association.

## 12. Pre-result amendment rule

If an unforeseen source-semantic, implementation, or estimability problem is found during outcome-blind QA, create `PRE_RESULT_AMENDMENT_<date>.md` that states:

- problem;
- evidence;
- exact change;
- why the change is outcome-blind;
- affected artifacts;
- new hashes.

The primary association remains locked until the amended spec is re-frozen. Once any primary dispersion–outcome association is inspected, design changes are deviations, not amendments, and must be reported as such.
