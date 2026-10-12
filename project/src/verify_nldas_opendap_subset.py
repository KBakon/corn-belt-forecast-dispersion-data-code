"""Verify variable-only OPeNDAP bytes decode identically to saved full granules."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import earthaccess
import netCDF4
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = (
    ("NLDAS_FORA0125_H", "C2033151148-GES_DISC", ("Rainf", "Tair")),
    ("NLDAS_NOAH0125_H", "C2069246977-GES_DISC", ("SoilM_0_10cm",)),
)


def main():
    auth = earthaccess.login(strategy="netrc", persist=False)
    if not auth.authenticated:
        raise RuntimeError("Earthdata netrc authentication failed")
    session = auth.get_session()
    records = []
    for product, concept, variables in SAMPLES:
        name = f"{product}.A20000101.0000.020.nc"
        granule_ur = product + ".2.0:" + name
        url = (f"https://opendap.earthdata.nasa.gov/collections/{concept}/granules/" +
               granule_ur.replace(":", "%3A") + ".nc4?" + ",".join((*variables, "time")))
        response = session.get(url, timeout=120)
        response.raise_for_status()
        full_path = ROOT / "raw" / "nldas_samples" / product / name
        comparisons = []
        with netCDF4.Dataset("subset.nc", memory=response.content) as subset, netCDF4.Dataset(full_path) as full:
            for variable in (*variables, "time", "lat", "lon"):
                left = np.ma.filled(subset.variables[variable][:], np.nan)
                right = np.ma.filled(full.variables[variable][:], np.nan)
                equal = bool(np.array_equal(left, right, equal_nan=True))
                unit_equal = (getattr(subset.variables[variable], "units", None) ==
                              getattr(full.variables[variable], "units", None))
                comparisons.append({"variable": variable, "shape": list(left.shape),
                                    "decoded_values_equal": equal, "units_equal": unit_equal})
                if not (equal and unit_equal):
                    raise ValueError(f"OPeNDAP subset differs from full granule: {product}:{variable}")
        records.append({"collection_short_name": product, "version": "2.0",
                        "collection_concept_id": concept, "granule_ur": granule_ur,
                        "opendap_subset_url": url, "subset_byte_size": len(response.content),
                        "subset_sha256": hashlib.sha256(response.content).hexdigest(),
                        "full_path": str(full_path),
                        "full_sha256": hashlib.sha256(full_path.read_bytes()).hexdigest(),
                        "comparisons": comparisons})
    output = {"verified_utc": datetime.now(timezone.utc).isoformat(),
              "exact_frozen_products_verified": len(records), "records": records}
    (ROOT / "logs" / "nldas_opendap_subset_equivalence.json").write_text(
        json.dumps(output, indent=2), encoding="utf-8")
    print("Verified exact decoded OPeNDAP subset equality for both frozen NLDAS products", flush=True)


if __name__ == "__main__":
    main()
