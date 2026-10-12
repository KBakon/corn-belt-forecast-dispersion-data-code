# F1 data origin and publication-scope decision | 2026-10-12

## Decision

The F1 analysis-ready panels and computation/analysis code are original research products assembled from documented, predominantly U.S. government public datasets. The panel is **NOT original farmer-level observation or independently measured meteorological data**. Its source values were obtained from USDA NASS Quick Stats, NOAA GEFSv12 reforecasts, NASA GES DISC NLDAS-2, USDA Cropland Data Layer, and U.S. Census TIGER/Line. No evidence in the inspected provenance identifies stolen, private, confidential, or restricted-access respondent records. Access through a NASA Earthdata account must not be confused with ownership.

**Scope of conditional author consent:** original code and original selection/processing/aggregation/arrangement in the analysis-ready panel may be shared with accurate attribution and precisely scoped licenses. The license cannot convey rights to third-party source data. Do not describe NASA/NOAA/USDA/Census original observations and products as authored by the paper's author.

**Release boundary:** prepare a narrow public deposit containing the frozen full and primary analysis-ready Parquet panels (3,000 and 1,777 rows, respectively), their dictionary, the unchanged author-controlled analysis/processing code, the GEFS state-week aggregate needed to reproduce scaling, fixed design and results, tests, figures/tables, and provenance/attribution. Exclude `project/raw/` in its entirety, including direct NASS exports and the Census TIGER ZIP; exclude raw NOAA GRIB, NASA hourly NLDAS files, and full CDL rasters. Those sources remain accessible from originating institutions. Do not include the manuscript PDF or create a preprint.

Accepted primary Parquet SHA-256: `bc20339686b6ccc819e022d8b3b827bf02bc8ce27e38a1099e515c64ae2b0896`. The source release candidate SHA-256 is `c9854d670781fbcace947f98539f87da5234e78eb161a0708c1f5e353debcedc`. Primary panel and analysis code in this narrower derivative candidate remain byte-identical to that validated source candidate; no analysis is rerun or changed.

## Source-specific rights rationale

- USDA NASS Quick Stats: NASS says most information is public domain and may be reproduced with requested acknowledgement: https://www.nass.usda.gov/Data_and_Statistics/Citation_Request/ .
- USDA NASS Cropland Data Layer: its published metadata say public domain/free to redistribute: https://data.nass.usda.gov/Research_and_Science/Cropland/sarsfaqs2.php .
- NOAA GEFSv12: NOAA NODD explicitly permits open use; do not claim modified data are original unaltered NOAA output or imply endorsement: https://registry.opendata.aws/noaa-gefs-reforecast/ .
- NASA NLDAS-2: NASA's ESDIS policy generally permits factual reuse and distribution of NASA uncopyrighted data, subject to restrictions on separately licensed non-NASA content: https://www.earthdata.nasa.gov/engage/open-data-services-software/data-use-policy . NASA Open Data Portal lists both exact collection DOIs, public access and a government-works license link: https://doi.org/10.5067/THUF4J1RLSYG and https://doi.org/10.5067/T4OW83T8EXDO . Do not interpret this as permission to relicense source data under the author's CC BY 4.0; source-specific exceptions are possible. No original hourly NLDAS files are included in the narrower candidate.
- U.S. Census TIGER/Line boundaries: omitted from narrow candidate; provenance and attribution retained.

## Evidence and remaining action

Inspect `F1_DERIVED_PANEL_AND_CODE_PUBLIC_RELEASE_CANDIDATE_2026-10-12.zip` and its manifest. It is a **local staging artifact, not a GitHub/Zenodo release**. Original local M9C release tests demonstrated panel-to-primary-result reproduction on a clean Python 3.11 environment on one Windows host; they did not demonstrate independent source-to-panel reconstruction. The narrower packaging has **not independently rerun** the numerical model and cannot claim an independent-host execution. The package preserves the unchanged required files, and provides a checksum/integrity verifier. Before an irreversible public upload, confirm the exact published file list, avoid committing credentials, accept only rights you actually control, and use the DOI only after Zenodo reports a real one. The MAUSAM manuscript must be updated to the real repository link, not a placeholder.

No separate institutional or publisher letter is required by this decision; the author has stated no institutional restriction. Any legally operative, inconsistent terms actually presented during deposit must still be reviewed rather than auto-accepted. The scope decision does not transfer ownership of third-party original data and does not mean that all underlying values were collected by the author.
