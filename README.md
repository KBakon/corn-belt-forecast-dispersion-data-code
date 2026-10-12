# Corn Belt forecast-distribution study | Derived panel and code v1.0.0

Version 1.0.0 contains the scoped derived research panel and original code. Cite the source institutions and observe the file-level license boundaries below.

## What's included

- Analysis-ready full panel (`project/ANALYSIS_READY_PANEL/analysis_ready_panel.parquet`): 3,000 state-weeks, of which 1,782 are active planting weeks.
- Frozen complete-case primary panel (`project/ANALYSIS_READY_PANEL/analysis_ready_primary.parquet`): 1,777 state-weeks, 17 states, 2000-2019; SHA-256 `bc20339686b6ccc819e022d8b3b827bf02bc8ce27e38a1099e515c64ae2b0896`.
- Data dictionaries, one GEFS five-member state-week predictor aggregate used for the fixed scaling audit, original analysis/build scripts, frozen model outputs, methods, tests, manuscript-owned tables/figures, and a source-object **manifest** (not the source objects themselves). No other interim state-week table or spatial weight table is included.
- Explicit provenance and rights scope. Science-bearing files retain their hashes from the accepted P3-M9C source candidate. The content was locally verified before release; no independent-host reproduction is claimed.

## What's NOT included

No direct raw USDA NASS CSV copies, U.S. Census shapefile ZIP, NOAA GRIB files, NASA NLDAS hourly granules, raw CDL rasters, manuscript/preprint, or login credentials. Government source data remain from their own custodians. The full source-to-panel pipeline has NOT been demonstrated on a clean independent machine.

## Run the frozen primary model from the bundled panel

Requires Python 3.11 and the pinned requirements listed in `requirements.txt` (heavy native dependencies may be platform-specific):

```
python -m pip install -r requirements.txt
python verify_derivative_candidate.py
python reproduce_primary.py --write-report
python -m unittest discover -s project/tests -p test_primary_inference.py -v
python verify_derivative_candidate.py
```

`verify_derivative_candidate.py` verifies this distribution's checksums and frozen primary panel SHA; it does not itself rerun the model. `reproduce_primary.py` is copied byte-for-byte from the prior M9C validated candidate, including its dependencies. The supported verification is panel-to-primary-results on an isolated environment on the same host; it is not independent-host or source-to-panel validation.

The study is retrospective, observational, and associational. It does not establish prospective GEFS use by farmers, behavioral causality or forecast value. Frozen focal beta is +0.1353486466 percentage points/day/IQR; primary two-way-clustered p = 0.0696425429; TOST equivalence is within the investigator-selected +/-0.5 pp/day/IQR bound.

## Authorship, source credit, scope of licenses

- Author-controlled original source code: MIT in `LICENSE` only for original code over which the creator holds rights.
- Original selection, arrangement, explanations, tables and figures: CC BY 4.0 to the extent protectable and owned by the creator. See `LICENSE_DATA_CC_BY_4.0.txt` and `LICENSE_SCOPE.md`.
- Factual information, U.S. government source datasets, and underlying NASA/NOAA/NASS/Census products: **not relicensed by this release**. See `THIRD_PARTY_NOTICES.md` and `SOURCE_DATA_ACQUISITION.md`. NOAA and NASA do not endorse this analysis.

To cite data sources, use the exact identifiers in THIRD_PARTY_NOTICES.md. Use the Zenodo record's DOI after publication; do not substitute an unverified identifier.

## Release identity and boundary

Version: **1.0.0**.

GitHub repository: **https://github.com/KBakon/corn-belt-forecast-dispersion-data-code** (private until author confirmation for public release).

Zenodo DOI: **10.5281/zenodo.23319228** (reserved for the unpublished Dataset draft; registration and resolution follow publication).

Only author-controlled original code is offered under MIT; only eligible author-controlled protectable derived contributions are offered under CC BY 4.0. Underlying USDA, NOAA, NASA and Census source facts/products remain with their custodians. See `LICENSE_SCOPE.md`, `THIRD_PARTY_NOTICES.md`, and `SOURCE_DATA_ACQUISITION.md`.
