"""CMR and Earthdata access preflight for the two frozen NLDAS collections.

Credential values are never read into logs or printed. Authentication uses
earthaccess's environment strategy only when the standard variables exist.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import earthaccess


ROOT = Path(__file__).resolve().parents[1]
COLLECTIONS = ("NLDAS_FORA0125_H", "NLDAS_NOAH0125_H")


def safe_collection(collection):
    meta = collection.get("meta", {})
    umm = collection.get("umm", {})
    return {
        "concept_id": meta.get("concept-id"),
        "provider_id": meta.get("provider-id"),
        "short_name": umm.get("ShortName"),
        "version": umm.get("Version"),
        "entry_title": umm.get("EntryTitle"),
        "doi": (umm.get("DOI") or {}).get("DOI"),
    }


def safe_granule(granule):
    meta = granule.get("meta", {})
    umm = granule.get("umm", {})
    urls = []
    for item in umm.get("RelatedUrls", []):
        url = item.get("URL", "")
        if "urs.earthdata.nasa.gov" not in url:
            urls.append({"url": url, "type": item.get("Type"), "subtype": item.get("Subtype")})
    distributions = umm.get("DataGranule", {}).get("ArchiveAndDistributionInformation", [])
    checksums = []
    for item in distributions:
        checksums.extend(item.get("Checksum", []) if isinstance(item.get("Checksum"), list) else ([item["Checksum"]] if item.get("Checksum") else []))
    return {
        "concept_id": meta.get("concept-id"),
        "provider_id": meta.get("provider-id"),
        "granule_ur": umm.get("GranuleUR"),
        "beginning_datetime": (umm.get("TemporalExtent") or {}).get("RangeDateTime", {}).get("BeginningDateTime"),
        "ending_datetime": (umm.get("TemporalExtent") or {}).get("RangeDateTime", {}).get("EndingDateTime"),
        "distribution_sizes": [{"size": item.get("Size"), "unit": item.get("SizeUnit")}
                               for item in distributions],
        "urls": urls,
        "checksums": checksums,
    }


def main():
    output = {"checked_utc": datetime.now(timezone.utc).isoformat(), "collections": {}}
    for short_name in COLLECTIONS:
        datasets = earthaccess.search_datasets(short_name=short_name, version="2.0")
        granules = earthaccess.search_data(
            short_name=short_name,
            version="2.0",
            temporal=("2000-01-01T00:00:00", "2000-01-01T02:00:00"),
            count=2,
        )
        output["collections"][short_name] = {
            "collection_hits": [safe_collection(d) for d in datasets],
            "granule_hits": [safe_granule(g) for g in granules],
        }
    credential_vars_present = all(os.getenv(k) for k in ("EARTHDATA_USERNAME", "EARTHDATA_PASSWORD"))
    netrc_present = any((Path.home() / name).is_file() for name in (".netrc", "_netrc"))
    output["environment_credentials_present"] = credential_vars_present
    output["netrc_present"] = netrc_present
    if credential_vars_present:
        try:
            auth = earthaccess.login(strategy="environment", persist=False)
            output["authenticated"] = bool(auth.authenticated)
        except Exception as error:
            output["authenticated"] = False
            output["authentication_error_type"] = type(error).__name__
    elif netrc_present:
        try:
            auth = earthaccess.login(strategy="netrc", persist=False)
            output["authenticated"] = bool(auth.authenticated)
        except Exception as error:
            output["authenticated"] = False
            output["authentication_error_type"] = type(error).__name__
    else:
        output["authenticated"] = False
        output["authentication_error_type"] = "NoEarthdataCredentialSource"
    target = ROOT / "logs" / "earthdata_preflight.json"
    target.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"collection_hits": {k: len(v["collection_hits"]) for k, v in output["collections"].items()},
                      "granule_hits": {k: len(v["granule_hits"]) for k, v in output["collections"].items()},
                      "authenticated": output["authenticated"],
                      "authentication_error_type": output.get("authentication_error_type")}, indent=2))


if __name__ == "__main__":
    main()
