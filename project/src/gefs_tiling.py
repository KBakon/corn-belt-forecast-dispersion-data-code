"""Exact-only duplicate collapse and exact precipitation-window validation."""

import numpy as np


def retain_exact_pair(first, other, semantic_keys):
    """Return (retained, discarded); fail if metadata, mask, or cells differ."""
    a, b = first["full"], other["full"]
    if a is None or b is None:
        raise ValueError("Full-grid evidence is required for duplicate collapse")
    if any(first["info"].get(k) != other["info"].get(k) for k in semantic_keys):
        raise ValueError("Non-identical GEFS duplicate meteorological metadata")
    if a["values"].shape != b["values"].shape:
        raise ValueError("Non-identical GEFS duplicate grid dimensions")
    if a["bitmap_hash"] != b["bitmap_hash"] or not np.array_equal(a["missing"], b["missing"]):
        raise ValueError("Non-identical GEFS duplicate bitmap or missing mask")
    valid = ~a["missing"]
    if not np.array_equal(a["values"][valid], b["values"][valid]):
        raise ValueError("Non-identical GEFS duplicate decoded precipitation")
    return sorted((first, other), key=lambda r: (
        r["info"]["byte_offset"] if r["info"]["byte_offset"] is not None else float("inf"),
        r["info"]["message_index"]))


def assert_exact_tiling(windows, horizon=168):
    ordered = sorted(windows)
    cursor = 0
    for start, end in ordered:
        if start < cursor:
            raise ValueError(f"GEFS accumulation overlap at {start}-{end}")
        if start > cursor:
            raise ValueError(f"GEFS accumulation gap at {cursor}-{start}")
        if end <= start:
            raise ValueError(f"GEFS accumulation invalid interval at {start}-{end}")
        cursor = end
    if cursor != horizon:
        raise ValueError(f"GEFS accumulation gap at {cursor}-{horizon}")
