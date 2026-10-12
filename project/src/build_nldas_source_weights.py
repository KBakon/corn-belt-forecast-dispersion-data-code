"""Intersect fixed CDL weights with each frozen NLDAS variable's fixed source grid mask."""

import csv
import hashlib
import json
from pathlib import Path

import earthaccess
import netCDF4
import numpy as np
import pandas as pd

import build_nldas_hourly as hourly


ROOT = Path(__file__).resolve().parents[1]
PRODUCTS = {"NLDAS_FORA0125_H": ("Rainf", "Tair"),
            "NLDAS_NOAH0125_H": ("SoilM_0_10cm",)}


def main():
    hourly.AUTH = earthaccess.login(strategy="netrc", persist=False)
    if not hourly.AUTH.authenticated:
        raise RuntimeError("Earthdata netrc authentication failed")
    with (ROOT / "raw" / "nldas_object_manifest.csv").open(newline="", encoding="utf-8") as stream:
        source = list(csv.DictReader(stream))
    masks = {}
    samples = []
    for product, variables in PRODUCTS.items():
        for year in ("2000", "2010", "2019"):
            if year == "2000":
                path = ROOT / "raw" / "nldas_samples" / product / f"{product}.A20000101.0000.020.nc"
                granule = f"{product}.2.0:{path.name}"
            else:
                row = next(r for r in source if r["collection_short_name"] == product
                           and r["hour_utc"].startswith(year))
                path = ROOT / "raw" / "nldas_samples" / product / row["granule_ur"].split(":", 1)[1]
                granule = row["granule_ur"]
                if not path.exists():
                    payload, _, _ = hourly.download_one(row)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(payload)
            with netCDF4.Dataset(path) as dataset:
                for variable in variables:
                    values = np.ma.filled(dataset.variables[variable][0], np.nan).astype(float)
                    if values.shape != (224, 464):
                        raise ValueError(f"NLDAS source grid mismatch: {granule}:{variable}")
                    mask = np.isfinite(values.ravel())
                    masks[(variable, year)] = mask
                    samples.append({"year": year, "product": product, "variable": variable,
                                    "granule_ur": granule,
                                    "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                    "source_valid_mask_sha256": hashlib.sha256(np.packbits(mask).tobytes()).hexdigest(),
                                    "valid_cells": int(mask.sum())})
    for variable in {v for vs in PRODUCTS.values() for v in vs}:
        if not all(np.array_equal(masks[(variable, "2000")], masks[(variable, year)])
                   for year in ("2010", "2019")):
            raise ValueError(f"NLDAS {variable} source-valid mask differs across sample years")
    out = ROOT / "spatial" / "nldas_source_valid_weights"
    audit = []
    for variable in {v for vs in PRODUCTS.values() for v in vs}:
        valid = masks[(variable, "2000")]
        (out / variable).mkdir(parents=True, exist_ok=True)
        for state in hourly.CONFIG["state_postal_codes"]:
            for kind, folder, col in (
                    ("crop", "nldas_weights", "normalized_corn_frequency_weight"),
                    ("area", "nldas_area_weights", "normalized_area_weight")):
                table = pd.read_csv(ROOT / "spatial" / folder / f"{state}.csv")
                indices = (223-table["row_index"].to_numpy(int))*464+table["col_index"].to_numpy(int)
                kept = valid[indices]
                original_sum = float(table[col].sum())
                retained_sum = float(table.loc[kept, col].sum())
                if retained_sum <= 0:
                    raise ValueError(f"No NLDAS source-valid spatial support: {variable}:{state}:{kind}")
                selected = table.loc[kept, ["row_index", "col_index", col]].copy()
                selected["normalized_source_valid_weight"] = selected[col] / retained_sum
                if not np.isclose(selected["normalized_source_valid_weight"].sum(), 1, atol=1e-9):
                    raise ValueError("NLDAS source-valid weights do not sum to one")
                selected.to_csv(out / variable / f"{state}_{kind}.csv", index=False)
                audit.append({"variable": variable, "state_postal": state, "weight_kind": kind,
                              "original_cells": len(table), "source_valid_cells": len(selected),
                              "masked_weight_fraction": 1-retained_sum/original_sum,
                              "source_valid_weight_sum": float(selected["normalized_source_valid_weight"].sum()),
                              "source_valid_mask_sha256": hashlib.sha256(np.packbits(valid).tobytes()).hexdigest()})
    pd.DataFrame(samples).to_csv(out / "source_samples.csv", index=False)
    pd.DataFrame(audit).to_csv(out / "weight_audit.csv", index=False)
    print(json.dumps({"source_samples": len(samples), "weight_tables": len(audit),
                      "maximum_masked_crop_weight_fraction": max(r["masked_weight_fraction"]
                                                                  for r in audit if r["weight_kind"] == "crop")},
                     indent=2), flush=True)


if __name__ == "__main__":
    main()
