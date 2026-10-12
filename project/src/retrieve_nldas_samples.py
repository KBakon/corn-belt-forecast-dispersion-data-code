"""Retrieve one authenticated granule from each frozen NLDAS-2 collection.

No credentials, tokens, cookies, or authentication responses are serialized.
"""

import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import earthaccess
import netCDF4


ROOT = Path(__file__).resolve().parents[1]
PRODUCTS = {
    "NLDAS_FORA0125_H": ("Rainf", "Tair"),
    "NLDAS_NOAH0125_H": ("SoilM_0_10cm",),
}


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    log = {"attempted_utc": datetime.now(timezone.utc).isoformat(), "products": {}}
    has_environment = all(os.getenv(key) for key in ("EARTHDATA_USERNAME", "EARTHDATA_PASSWORD"))
    has_netrc = any((Path.home() / name).is_file() for name in (".netrc", "_netrc"))
    if not (has_environment or has_netrc):
        log["status"] = "credential_source_unavailable"
    else:
        strategy = "environment" if has_environment else "netrc"
        try:
            auth = earthaccess.login(strategy=strategy, persist=False)
            if not auth.authenticated:
                raise RuntimeError("authentication_not_confirmed")
            log["status"] = "authenticated"
            manifest = ROOT / "provenance" / "source_manifest.csv"
            prior = {}
            if manifest.exists():
                with manifest.open(newline="", encoding="utf-8") as stream:
                    prior = {row["source_url"]: row for row in csv.DictReader(stream)}
            for short_name, variables in PRODUCTS.items():
                matches = earthaccess.search_data(
                    short_name=short_name,
                    version="2.0",
                    temporal=("2000-01-01T00:00:00", "2000-01-01T00:00:01"),
                    count=2,
                )
                exact = [granule for granule in matches if granule["umm"]["GranuleUR"].endswith("A20000101.0000.020.nc")]
                if len(exact) != 1:
                    raise RuntimeError(f"expected_one_exact_granule_{short_name}")
                granule = exact[0]
                directory = ROOT / "raw" / "nldas_samples" / short_name
                directory.mkdir(parents=True, exist_ok=True)
                files = earthaccess.download([granule], local_path=directory, threads=1, show_progress=False)
                if len(files) != 1:
                    raise RuntimeError(f"expected_one_downloaded_file_{short_name}")
                path = Path(files[0])
                if not path.is_file() or path.stat().st_size == 0:
                    raise RuntimeError(f"download_missing_or_empty_{short_name}")
                with netCDF4.Dataset(path) as dataset:
                    metadata = {}
                    grid_shape = [len(dataset.dimensions["lat"]), len(dataset.dimensions["lon"])]
                    time_variable = dataset.variables["time"]
                    time_value = netCDF4.num2date(time_variable[0], time_variable.units,
                                                  calendar=getattr(time_variable, "calendar", "standard"))
                    encoded_time = (time_value.year, time_value.month, time_value.day,
                                    time_value.hour, time_value.minute)
                    if encoded_time != (2000, 1, 1, 0, 0):
                        raise RuntimeError(f"sample_time_mismatch_{short_name}")
                    for name in variables:
                        if name not in dataset.variables:
                            raise RuntimeError(f"required_variable_missing_{short_name}_{name}")
                        variable = dataset.variables[name]
                        metadata[name] = {
                            "units": getattr(variable, "units", None),
                            "dimensions": list(variable.dimensions),
                            "shape": list(variable.shape),
                        }
                urls = [entry["URL"] for entry in granule["umm"].get("RelatedUrls", [])
                        if entry.get("Type") == "GET DATA" and entry.get("URL", "").startswith("https://")]
                if len(urls) != 1:
                    raise RuntimeError(f"ambiguous_data_url_{short_name}")
                url = urls[0]
                row = {
                    "source": "NASA NLDAS-2",
                    "version": short_name + ".2.0",
                    "source_url": url,
                    "object_key": granule["umm"]["GranuleUR"],
                    "local_path": str(path),
                    "retrieved_utc": datetime.now(timezone.utc).isoformat(),
                    "byte_size": path.stat().st_size,
                    "sha256": digest(path),
                    "access_note": "Earthdata CMR + earthaccess authenticated download; GES_DISC",
                    "first_consumer": "src/retrieve_nldas_samples.py",
                }
                prior[url] = row
                log["products"][short_name] = {
                    "status": "verified",
                    "granule_ur": row["object_key"],
                    "local_path": str(path),
                    "byte_size": row["byte_size"],
                    "sha256": row["sha256"],
                    "required_variables": metadata,
                    "encoded_time_utc": "2000-01-01T00:00:00Z",
                    "grid_shape_lat_lon": grid_shape,
                }
            with manifest.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(next(iter(prior.values()))))
                writer.writeheader()
                writer.writerows(prior[url] for url in sorted(prior))
            log["status"] = "two_granules_verified"
        except Exception as error:
            log["status"] = "authentication_or_retrieval_failed"
            log["error_type"] = type(error).__name__
            # Error text is deliberately omitted because auth libraries can
            # include request details in exceptions.
    target = ROOT / "logs" / "nldas_sample_retrieval.json"
    target.write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": log["status"], "products_verified": len(log["products"]),
                      "error_type": log.get("error_type")}, indent=2))


if __name__ == "__main__":
    main()
