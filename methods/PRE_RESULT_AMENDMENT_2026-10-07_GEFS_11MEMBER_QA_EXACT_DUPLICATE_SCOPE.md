# Pre-result amendment: Wednesday GEFS eleven-member QA exact-duplicate scope

**Project and milestone:** Corn Belt F1, Protocol 1, P1-M1  
**Date:** 2026-10-07  
**Authority:** Controller's conditional outcome-blind GEFS 11-member QA exact-duplicate scope extension, satisfied by the full frozen-source inventory.  
**Status:** Authorized Case A after complete source forensic verification; before QA Block F or any primary dispersion–planting association was inspected.

## Relation to existing authority

The original freeze manifest and frozen scientific specifications remain unchanged. The separate primary-cache amendment `PRE_RESULT_AMENDMENT_2026-10-06_GEFS_EXACT_DUPLICATE_DEDUP.md` remains unchanged with SHA-256 `9ce4ceb935114c5edb5cb0d2ead67a823a9f34f47e35db02ae43c40d4847e1c8`. This amendment extends its exact-semantic source-encoding normalization principle **only** to the frozen Wednesday eleven-member GEFS QA source construction. It does not alter the GEFSv12 source, Wednesday timing rule, 0–168 hour precipitation quantity, five-member primary or eleven-member QA ensemble, state weights, forecast mean or sample-SD formulas, QA Block F purpose, primary estimand, regression, or scientific claim.

## Full-universe outcome-blind evidence

The complete frozen Wednesday source universe contains **280 cycles and 3,080 member objects**. Every object was retrieved, checked against its NOAA inventory identity, decoded, and inventoried for expected six-hour windows, overlaps, unexpected intervals, and temporal metadata. The inventory found **25 duplicate interval groups**, represented by **25 full-grid pair comparisons**. All **25 comparisons** are exact semantic duplicates. Non-identical pairs: **0**; maximum absolute decoded precipitation difference: **0**; unequal decoded grid cells: **0**. Missing expected windows, distinct overlaps, unexpected intersecting intervals, and malformed temporal metadata: **0**. No NASS outcomes entered these checks.

| Wednesday archive cycle | Members with exact duplicates | Duplicate interval groups |
|---|---|---:|
| `2004042100` | p07, p08, p09, p10 | 25 |

The exact affected cycle/member/window/message identities, original byte offsets, source URLs, SHA-256 values and ETags, GRIB semantics, grid/mask/data hashes, and decoded-difference evidence are in `logs/gefs_11_accumulation_anomaly_inventory.csv` and `logs/gefs_11_duplicate_forensic_comparison.csv`. Their SHA-256 values are `4e57eae20ca9a20e825d1ace4c88fc35a064fa7ed81a8747d130bf9e8ec98a68` and `f8aee05ea2835495989a98cd53448473e4983123571ef95614cabcf65355b358`, respectively. Each cycle's retained/discarded counterpart log is under `logs/gefs_11_cycle_audits/`.

## Narrow amended implementation rule

Before exact-once 0–168 hour tiling of each Wednesday QA member, collapse **only** records with identical meteorological identity and processing metadata, accumulation interval, grid, bitmap and missing mask, and decoded precipitation at every grid cell. The source object SHA-256 and each duplicate message pair must match the full-universe verified forensic catalogue. Retain the lowest original GRIB byte offset; if unavailable, retain the lowest message/submessage index. Log every retained and discarded counterpart. Any non-identical or unapproved duplicate remains a hard failure, as does any gap, distinct overlap, unexpected interval, changed source object, or malformed timing.

The resulting 28 six-hour accumulation intervals per member must tile 0–168 hours exactly once. The collapse leaves member precipitation totals equal to the totals from one retained exact copy. This is source encoding normalization only and changes no scientific estimand.

This amendment was made outcome-blind, before QA Block F results or any primary GEFS-dispersion–planting increment/utilization association were inspected. The primary model was not run.
