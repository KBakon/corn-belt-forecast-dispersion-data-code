# DATA_PROVENANCE

**Project:** Corn Belt Forecast-State Planting Utilization (F1)  
**Milestone:** 1  
**Version:** 1.0  
**Retrieval / verification date:** 2026-10-05  
**Status:** provenance specification frozen before primary association

## 1. Source register

| Role | Source / exact product | Version / identifier | Primary access route | Core semantics |
|---|---|---|---|---|
| Weekly planting outcome + workability | USDA NASS Crop Progress and Condition / Quick Stats | Survey program; weekly Crop Progress estimates | NASS Quick Stats downloadable bulk files or API/interactive export; historical Crop Progress reports for spot validation | State-level cumulative crop progress for week ending Sunday; DSFW is number of days in the week where weather/field conditions allowed field work for a major portion of the day |
| Prospective forecast distribution | NOAA GEFSv12 reforecast archive | Phase covering 2000–2019; GRIB2; NOAA/NODD AWS bucket `noaa-gefs-retrospective` | NOAA Open Data / AWS public bucket | Daily retrospective ensemble; standard five members (`c00`,`p01`–`p04`), weekly 11-member expansion; primary variable `apcp_sfc` total precipitation |
| Realized meteorology | NASA NLDAS-2 primary forcing | `NLDAS_FORA0125_H.2.0`; DOI `10.5067/THUF4J1RLSYG` | NASA GES DISC / Earthdata | Hourly 1/8-degree primary forcing; `Rainf` total precipitation (hourly sum, kg m-2), `Tair` 2-m air temperature (K) |
| Realized soil state | NASA NLDAS-2 Noah LSM | `NLDAS_NOAH0125_H.2.0`; DOI `10.5067/T4OW83T8EXDO` | NASA GES DISC / Earthdata | Hourly 1/8-degree Noah land-surface fields; `SoilM_0_10cm` top-layer soil moisture content (kg m-2) |
| Fixed crop-area spatial support | USDA NASS Cropland Data Layer | Annual national 30-m CDL, 2008–2019 | NASS Cropland Data Layer releases / CropScape | Annual crop-specific raster. Primary project mask is a fixed corn-frequency surface computed from 2008–2019 annual CDL, not a time-varying treatment/control |
| State boundaries | U.S. Census Bureau TIGER/Line | 2019 state boundaries | Census TIGER/Line 2019 | Legal state boundaries as of 2019-01-01 |

## 2. USDA NASS semantics and extraction

### 2.1 Planting progress

Preferred Quick Stats item:

`CORN — PROGRESS, MEASURED IN PCT PLANTED`

Use weekly state observations with the explicit `WEEK ENDING` reference date. Values are cumulative percentage planted. Reporters are instructed to report for the week ending Sunday. The panel uses the Sunday reference date, never the publication timestamp, as the temporal key.

### 2.2 Days Suitable for Fieldwork (DSFW)

NASS definition: a suitable day is one in which weather and field conditions allowed producers to work in fields a major portion of that day. Extract the state-week numeric estimate corresponding to Days Suitable for Fieldwork and verify exact Quick Stats descriptor/schema programmatically before bulk processing.

### 2.3 Estimation and revision semantics

Crop Progress is a non-probability reporting system. State offices summarize reporter indications and weight counties with NASS county acreage estimates. Published estimates are preliminary and can be corrected/updated; Quick Stats and online reports can be revised. Therefore:

- the canonical research extract is the latest Quick Stats value retrieved on 2026-10-05;
- the raw extract and retrieval timestamp are immutable and checksummed;
- a sample of state-weeks is cross-checked against historical Crop Progress reports;
- correction-log hits affecting Crop Progress/DSFW are recorded, not silently repaired.

## 3. NOAA GEFSv12 provenance and a required metadata audit

The public archive documentation describes 2000–2019 reforecasts stored once daily under `YYYYMMDD00`, usually with five members (`c00`,`p01`–`p04`) and a weekly 11-member expansion. The same documentation states 0.25-degree output and 3-hourly storage during the first 10 forecast days. For total precipitation, `apcp_sfc` is in kg m-2 (= mm) and accumulation records represent recent 3- or 6-hour periods.

A publication describing the dataset states Phase-2 reforecasts were initialized at 0300 UTC, whereas the public archive documentation and directory labels use 00 UTC. This discrepancy is **not** resolved by assumption. Before bulk extraction, inspect GRIB metadata for representative 2000, 2010, and 2019 files and record:

- archive cycle directory;
- `dataDate` / `dataTime` or equivalent reference timestamp;
- `startStep` / `endStep` or `stepRange` for `apcp_sfc`;
- valid time;
- grid definition and units.

**Frozen cycle-selection rule:** select the archive cycle stored under the Monday `YYYYMMDD00` directory immediately following the prior NASS week-ending Sunday. If GRIB metadata reports 03 UTC as the actual reference time for Phase 2, retain that archive cycle and use the metadata reference time as the physical forecast start; do not substitute another daily cycle.

**Frozen precipitation-integration rule:** for each member, use `apcp_sfc` accumulation messages whose GRIB start/end steps tile forecast hour 0 through 168 exactly once. Prefer the coarser non-overlapping 6-hour accumulation records when multiple nested 3/6-hour records are available. Hard-fail on gaps, duplicated windows, or overlaps rather than summing blindly.

## 4. NASA NLDAS-2 realized-state provenance

### 4.1 Primary forcing

`NLDAS_FORA0125_H.2.0` is hourly at 0.125 degrees. Primary controls:

- `Rainf`: total precipitation, kg m-2, hourly accumulated/summed quantity; sum across the matched seven-day realized interval to mm.
- `Tair`: 2-m air temperature, K, point field; average across the matched seven-day realized interval, then convert to degrees C for reporting if desired.

The NLDAS primary precipitation is based on a temporally disaggregated CPC gauge-only daily analysis over CONUS with PRISM orographic adjustment; its subdaily timing uses ancillary radar/CMORPH/NARR information as available.

### 4.2 Noah land-surface output

`NLDAS_NOAH0125_H.2.0` is hourly at 0.125 degrees with four Noah soil layers. Primary soil-state control:

- `SoilM_0_10cm`: soil moisture content in the 0–10 cm layer, kg m-2, point field; weekly mean over the matched realized interval.

Prespecified sensitivity: start-of-interval `SoilM_0_10cm` in place of the weekly mean.

### 4.3 Known NLDAS quality issues

The NLDAS README documents localized precipitation artifacts (including near the Canada border), isolated dry spots, a forcing-method change around 2012, and some historical localized anomalies. The pipeline must retain an issue log and run time-series discontinuity/coverage QA. No state-week may be excluded because its outcome or forecast-dispersion relationship looks inconvenient.

## 5. Fixed spatial aggregation support

Primary meteorological and forecast variables are crop-area-weighted within each state using a **fixed** corn-frequency mask:

1. For each 30-m CDL pixel, compute `corn_frequency = mean(1[pixel classified as corn])` across 2008–2019.
2. Intersect with 2019 TIGER/Line state boundaries.
3. Aggregate/regrid this fixed weight surface to the GEFS and NLDAS grids using area-conservative overlap weights where feasible.
4. Normalize weights to sum to one within state for each target grid.

The mask is fixed across all 2000–2019 observations. It is a retrospective geographic measurement support, not a forecast-time state variable. Primary sensitivity uses unweighted state-land-area spatial means.

## 6. Study period and geographic frame

**Primary period:** 2000–2019.

**Primary states (17):** Colorado, Illinois, Indiana, Iowa, Kansas, Kentucky, Michigan, Minnesota, Missouri, Nebraska, North Carolina, North Dakota, Ohio, Pennsylvania, South Dakota, Tennessee, Wisconsin.

These are the NASS 18 major corn states used in the direct benchmark, excluding Texas because pre-2014 DSFW is structurally unavailable and the project will not impute Texas DSFW from another state in the confirmatory panel.

## 7. Raw-data immutability and source manifest

Each retrieved object must have:

- source URL or source query definition;
- retrieval UTC timestamp;
- original filename/object key;
- byte size;
- SHA-256 checksum;
- source/product version where available;
- license/access note;
- transformation script version that first consumes it.

Raw files are write-once. Any upstream correction or refresh is stored as a new snapshot and never overwrites the original research snapshot.
