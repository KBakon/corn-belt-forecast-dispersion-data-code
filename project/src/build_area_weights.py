"""Build exact state-polygon overlap weights on GEFS and NLDAS grids."""

import csv
import json

import numpy as np
import pyproj
from shapely.geometry import box
from shapely.ops import transform as transform_geometry

from build_spatial_weights import ROOT, TARGETS, state_geometries, target_window


def grid_cell_polygon(row, col, affine, convert):
    west, north = affine * (col, row)
    east, south = affine * (col+1, row+1)
    return transform_geometry(convert, box(west, south, east, north))


def main():
    audit = []
    convert = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True).transform
    for postal, item in sorted(state_geometries().items()):
        for grid_name, grid in TARGETS.items():
            window = target_window(item["geographic"], grid)
            table = ROOT / "spatial" / f"{grid_name}_area_weights" / f"{postal}.csv"
            table.parent.mkdir(parents=True, exist_ok=True)
            rows = []
            for row in range(int(window.row_off), int(window.row_off+window.height)):
                for col in range(int(window.col_off), int(window.col_off+window.width)):
                    cell = grid_cell_polygon(row, col, grid["transform"], convert)
                    overlap = item["projected"].intersection(cell).area
                    if overlap > 0:
                        rows.append((row, col, overlap))
            if not rows:
                raise ValueError(f"No {grid_name} area overlap for {postal}")
            total = sum(value for _, _, value in rows)
            with table.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(("row_index", "col_index", "normalized_area_weight"))
                writer.writerows((row, col, format(value/total, ".15g")) for row, col, value in rows)
            weights = np.array([value/total for _, _, value in rows])
            if not np.isclose(weights.sum(), 1, atol=1e-10):
                raise ValueError(f"Area weights do not normalize for {postal}:{grid_name}")
            audit.append({"state": postal, "grid": grid_name, "positive_cells": len(rows),
                          "weight_sum": float(weights.sum()), "state_projected_area_m2": float(item["projected"].area),
                          "grid_overlap_area_m2": float(total), "table": str(table)})
        print("area weights", postal, flush=True)
    (ROOT / "spatial" / "area_weight_audit.json").write_text(json.dumps(audit, indent=2) + "\n")


if __name__ == "__main__":
    main()
