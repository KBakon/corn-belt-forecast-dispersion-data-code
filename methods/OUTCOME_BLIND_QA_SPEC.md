# OUTCOME_BLIND_QA_SPEC

**Project:** Corn Belt Forecast-State Planting Utilization (F1)  
**Milestone:** 1  
**Rule:** This QA may inspect outcome marginals but must not expose any dispersion–outcome relationship.

## Required QA blocks

### A. Temporal ordering / leakage

Report:

- count of target state-weeks;
- selected GEFS archive cycle and decoded GRIB reference time by year;
- minimum/maximum difference between GEFS reference time and target NASS week-ending Sunday;
- count of forecast records with initialization/reference time after the frozen cutoff (must be zero);
- count of precipitation accumulation gaps/overlaps/duplicates (must be zero);
- random manual audit of at least 20 state-weeks across beginning/middle/end of sample.

**Hard fail:** any feature contains forecast information initialized after the selected cycle/reference time or any member total double-counts overlapping accumulation windows.

### B. Predictor support / mean–dispersion overlap

Outcome-blind summaries for raw and IQR-scaled GEFS mean and SD:

- N, mean, SD, min, p01, p05, p25, median, p75, p95, p99, max;
- Pearson and Spearman correlation between forecast mean and forecast SD;
- predictor-only VIF or equivalent collinearity diagnostic for mean and SD after fixed effects where feasible;
- state/year heatmap of predictor coverage;
- scatter/hexbin of forecast mean vs SD only.

Do not color/facet by planting outcome or utilization.

### C. NASS outcome marginals

Permitted marginal-only diagnostics:

- DSFW distribution overall and by state/seasonal week;
- weekly planting-increment distribution overall and by state/seasonal week;
- counts of `DSFW=0`;
- counts of negative increments / physically invalid differences;
- counts of increments equal to zero inside the active frame;
- distribution of `remaining_start_pp`;
- active-frame row counts by state/year.

No statistic in this block may be grouped, binned, sorted, or plotted by GEFS dispersion.

### D. State/year coverage

For each state:

- study years with planting progress;
- study years with DSFW;
- years with complete GEFS;
- years with complete NLDAS;
- eligible active weeks;
- complete-case primary weeks;
- percent complete.

Apply the frozen 18-of-20-years and 80%-active-week NASS coverage rule before association unblinding.

### E. Missingness

Report missingness by:

- source;
- variable;
- state;
- year;
- seasonal week;
- reason code where identifiable.

Allowed: predictor-vs-predictor missingness patterns.  
Forbidden: missingness comparisons conditional on high/low dispersion *and* planting outcome.

### F. Five-vs-eleven-member measurement sensitivity

On weekly 11-member dates:

- `sd5` from c00,p01–p04;
- `sd11` from c00,p01–p10;
- Pearson correlation;
- Spearman correlation;
- median and IQR of `sd5/sd11` where `sd11>0`;
- median absolute difference and relative absolute difference;
- summaries by year and state.

No planting outcome may enter this block.

### G. Spatial-weight QA

For each state and target grid:

- weight sum (must equal 1 within numerical tolerance);
- effective number of weighted grid cells;
- fraction of state area with positive corn-frequency weight;
- maps for a small fixed audit set (IA, IL, NE, ND, NC) showing state boundary and positive-weight grid cells;
- compare primary crop-weighted vs state-area mean distributions for predictor variables, without outcomes.

### H. NLDAS physical and continuity QA

- physical-range checks for precipitation, air temperature, top-layer soil moisture;
- missing-hour counts per state-week;
- no aggregation if a week falls below a prespecified 95% hourly-completeness threshold; such rows become missing and are logged;
- predictor-only time-series checks around 2012 to identify known forcing-method discontinuity behavior;
- no outcome-driven exclusion of anomalous physical values.

## QA pass verdict

Return exactly one:

- `QA PASS — PRIMARY ASSOCIATION MAY BE OPENED`
- `QA PASS WITH PRE-RESULT AMENDMENT REQUIRED`
- `QA FAIL — CONTROLLER DECISION REQUIRED`

The executor must not run the primary model after issuing the QA verdict. Opening the primary association is a separate Controller-authorized work package.
