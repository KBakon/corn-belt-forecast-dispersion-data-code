# Pre-result amendment: exact GEFS archive duplicate collapse

**Project and milestone:** Corn Belt F1, Protocol 1, P1-M1  
**Date:** 2026-10-06  
**Authority:** Controller instruction authorizing Case A only after outcome-blind full-cache inventory and full-grid forensic equality.  
**Status:** Implemented before any primary dispersion–planting association was opened.

## Frozen rule and source anomaly

`DATA_PROVENANCE.md` originally required each member's `apcp_sfc` start/end steps to tile forecast hours 0–168 exactly once, preferring non-overlapping six-hour records, and to hard-fail on any duplicated window. The NOAA GEFSv12 reforecast archive object for Monday cycle `2007060400` repeats six-hour precipitation messages in all five primary members. The duplicate groups are:

| Member | Duplicate six-hour windows | NOAA ETag | Cached object SHA-256 |
|---|---:|---|---|
| c00 | 13, 90–96 through 162–168 | `384fa87d505e5e4d9c050f3d4fa56e94` | `a8b9afe676db6ff535a1886d822e71618804ceee26b77208f0c1e7704b3c354d` |
| p01 | 13, 90–96 through 162–168 | `e8d256a3efa126e3ff176fc7efb960d1` | `6d243fdfeb9fe2f62b45e9a65ee81fa8c9218e9fd9e4749bde09ef93bbc433a9` |
| p02 | 12, 96–102 through 162–168 | `11666f16cf39203d6277f76117fcf79b` | `8a5df2c9d8a8200ce8980e3da3014d7be075487c02a5a0d2bf3b99b912bf4359` |
| p03 | 12, 96–102 through 162–168 | `1ced232df31491a2ef66d5eef6e41d7d` | `d7779a81d188592d3b3f18308603edbd7730f29e08899e1ec889867d4ea44e93` |
| p04 | 12, 96–102 through 162–168 | `dff6108a79c84a03e649b392bb1a832e` | `5beea047e1b8736c0f7ced2de484d1934a6bf369e785941841ca9a170f070424` |

Each object key is `GEFSv12/reforecast/2007/2007060400/{member}/Days:1-10/apcp_sfc_2007060400_{member}.grib2` in `noaa-gefs-retrospective.s3.amazonaws.com`. The `c00` source bytes were independently retrieved again over HTTPS and matched the cache SHA-256 and ETag. All affected cached objects match their retrieval SHA-256 sidecars.

## Outcome-blind forensic evidence

The inventory scanned all **1,435** cached primary GEFS objects, representing 287 selected cycles and five members. It found **62 duplicated six-hour groups**, all in the above cycle, and **zero** missing expected six-hour windows, overlapping distinct six-hour windows, unexpected intervals intersecting the frozen 0–168 hour tiling, or missing cached objects.

For every one of the 62 duplicate pairs, the forensic comparison recorded original message index and byte offset; variable, level, reference and valid times; interval and step metadata; product template and statistical processing; grid definition and dimensions; bitmap and missing-mask hashes; deterministic decoded-grid hashes; maximum absolute difference; and unequal decoded-cell count. All 62 pairs have identical meteorological semantics, interval, grid, missing mask, bitmap, and decoded precipitation on the **entire 1,038,240-cell grid**. Every maximum absolute difference and unequal-cell count is zero. No planting outcomes were loaded or consulted.

The durable P1 evidence is `logs/gefs_accumulation_anomaly_inventory.csv`, `logs/gefs_duplicate_forensic_comparison.csv`, and `logs/gefs_duplicate_forensic_summary.json` under the execution root. The production collapse log is `logs/gefs_exact_duplicate_collapses.csv`.

## Narrow amended implementation rule

Before the exact-once 0–168 hour tiling check, collapse **only** records that have the same meteorological metadata, interval, grid, missing mask, and exactly equal decoded precipitation at every grid cell. A source object must match the forensic SHA-256 and the duplicate pair must be in the verified catalogue. Retain the record with the lowest original GRIB byte offset; where offset is unavailable, retain the lowest message/submessage index. Log each retained and discarded counterpart.

Any non-identical duplicate, missing interval, overlapping interval, unapproved duplicate, changed source object, or mismatch with the forensic catalogue still hard-fails. The remaining 28 six-hour intervals per member must tile 0–168 hours exactly once. The GEFSv12 source/version, Monday cycle, 1–7 day precipitation quantity, five-member definition, mean and sample SD, state-week design, and all other protected scientific dimensions are unchanged.

`src/forensic_gefs_duplicates.py`, `src/gefs_tiling.py`, and `src/build_gefs_features.py` implement the forensic and production rules. `tests/test_gefs_exact_dedup.py` verifies exact collapse, non-identical hard failures, gap and overlap failures, and final exact tiling. This amendment is separate from the original frozen authorities and freeze manifest; none was overwritten.
