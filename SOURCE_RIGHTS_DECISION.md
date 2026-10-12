# Data origin and release scope

## Scope

The analysis-ready panels and computation/analysis code were assembled from documented public products: USDA NASS Quick Stats, NOAA GEFSv12 reforecasts, NASA GES DISC NLDAS-2, USDA Cropland Data Layer, and U.S. Census TIGER/Line. The panels are aggregate research products; they are not farmer-level observations or independently measured meteorological data. Earthdata account access does not convey ownership of NASA source data.

**License scope:** eligible author-controlled original code is offered under MIT; eligible original derived contributions and documentation are offered under CC BY 4.0. Neither license conveys rights to third-party source data. NASA, NOAA, USDA and Census original observations and products remain attributed to their originating institutions.

**Release boundary:** this repository contains the accepted full and primary analysis-ready Parquet panels (3,000 and 1,777 rows, respectively), their dictionary, original analysis/processing code, the GEFS state-week aggregate needed to reproduce scaling, fixed design and results, tests, figures/tables, and provenance/attribution. It excludes `project/raw/` in its entirety, including direct NASS exports and the Census TIGER ZIP, as well as raw NOAA GRIB, NASA hourly NLDAS files, full CDL rasters and the manuscript PDF. Original sources remain available from their custodians subject to their access conditions.

Accepted primary Parquet SHA-256: `bc20339686b6ccc819e022d8b3b827bf02bc8ce27e38a1099e515c64ae2b0896`. `FILES.sha256` records the complete repository file inventory and checksums.

## Source-specific rights rationale

- USDA NASS Quick Stats: NASS says most information is public domain and may be reproduced with requested acknowledgement: https://www.nass.usda.gov/Data_and_Statistics/Citation_Request/ .
- USDA NASS Cropland Data Layer: its published metadata say public domain/free to redistribute: https://data.nass.usda.gov/Research_and_Science/Cropland/sarsfaqs2.php .
- NOAA GEFSv12: NOAA NODD explicitly permits open use; do not claim modified data are original unaltered NOAA output or imply endorsement: https://registry.opendata.aws/noaa-gefs-reforecast/ .
- NASA NLDAS-2: NASA's ESDIS policy generally permits factual reuse and distribution of NASA uncopyrighted data, subject to restrictions on separately licensed non-NASA content: https://www.earthdata.nasa.gov/engage/open-data-services-software/data-use-policy . NASA Open Data Portal lists both exact collection DOIs, public access and a government-works license link: https://doi.org/10.5067/THUF4J1RLSYG and https://doi.org/10.5067/T4OW83T8EXDO . Do not interpret this as permission to relicense source data under the author's CC BY 4.0; source-specific exceptions are possible. No original hourly NLDAS files are included in the narrower candidate.
- U.S. Census TIGER/Line boundaries: omitted from narrow candidate; provenance and attribution retained.

## Reproducibility boundary

The included scripts and panel support reproduction of the accepted primary association and equivalence inference. This has been tested in an isolated Python 3.11 environment on one Windows host. Independent-host execution and source-to-panel reconstruction have not been demonstrated. Raw source objects and some historical intermediates are excluded; see `SOURCE_DATA_ACQUISITION.md`. `verify_derivative_candidate.py` checks the file inventory and accepted primary-panel hash.

The licensing scope does not transfer ownership of third-party original data or imply that underlying values were collected by the author. See `LICENSE_SCOPE.md` and `THIRD_PARTY_NOTICES.md`.
