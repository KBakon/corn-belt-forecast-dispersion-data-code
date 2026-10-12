"""Outcome-blind Noah source-domain mask audit at beginning/middle/end sample."""

import csv
import hashlib
import json
from pathlib import Path

import earthaccess
import netCDF4
import numpy as np
import pandas as pd

from build_nldas_hourly import ROOT, download_one
import build_nldas_hourly as hourly


def main():
    hourly.AUTH = earthaccess.login(strategy="netrc", persist=False)
    if not hourly.AUTH.authenticated:
        raise RuntimeError("Earthdata netrc authentication failed")
    rows = []
    with (ROOT / "raw" / "nldas_object_manifest.csv").open(newline="", encoding="utf-8") as stream:
        source = list(csv.DictReader(stream))
    paths = []
    for year in ("2000", "2010", "2019"):
        if year == "2000":
            path = ROOT / "raw" / "nldas_samples" / "NLDAS_NOAH0125_H" / "NLDAS_NOAH0125_H.A20000101.0000.020.nc"
            granule = "NLDAS_NOAH0125_H.2.0:NLDAS_NOAH0125_H.A20000101.0000.020.nc"
        else:
            row = next(row for row in source if row["collection_short_name"] == "NLDAS_NOAH0125_H"
                       and row["hour_utc"].startswith(year))
            path = ROOT / "raw" / "nldas_samples" / "NLDAS_NOAH0125_H" / row["granule_ur"].split(":", 1)[1]
            granule = row["granule_ur"]
            if not path.exists():
                payload, _, _ = download_one(row)
                path.write_bytes(payload)
        paths.append((year, path, granule))
    masks = {}
    for year, path, granule in paths:
        with netCDF4.Dataset(path) as dataset:
            field = np.ma.filled(dataset.variables["SoilM_0_10cm"][0], np.nan).ravel()
            masks[year] = np.isfinite(field)
            if field.size != 224 * 464:
                raise ValueError("Noah sample grid differs from frozen NLDAS grid")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        for state in hourly.CONFIG["state_postal_codes"]:
            for kind, folder, col in (
                    ("crop", "nldas_weights", "normalized_corn_frequency_weight"),
                    ("area", "nldas_area_weights", "normalized_area_weight")):
                table = pd.read_csv(ROOT / "spatial" / folder / f"{state}.csv")
                indices = (223-table["row_index"].to_numpy(int))*464+table["col_index"].to_numpy(int)
                invalid = ~masks[year][indices]
                rows.append({"year": year, "granule_ur": granule, "source_sha256": sha,
                             "state_postal": state, "weight_kind": kind,
                             "positive_weight_cells": len(table),
                             "source_masked_cells": int(invalid.sum()),
                             "source_masked_weight_fraction": float(table.loc[invalid, col].sum())})
    output = ROOT / "logs" / "nldas_noah_source_mask_audit.csv"
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {"years": list(masks),
               "mask_equal_2000_2010": bool(np.array_equal(masks["2000"], masks["2010"])),
               "mask_equal_2000_2019": bool(np.array_equal(masks["2000"], masks["2019"])),
               "states_with_masked_crop_weight": sorted({r["state_postal"] for r in rows
                                                         if r["weight_kind"] == "crop" and
                                                         r["source_masked_weight_fraction"] > 0}),
               "maximum_masked_crop_weight_fraction": max(r["source_masked_weight_fraction"]
                                                           for r in rows if r["weight_kind"] == "crop")}
    (ROOT / "logs" / "nldas_noah_source_mask_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
