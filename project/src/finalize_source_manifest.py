"""Consolidate immutable object-level source evidence after all source builds."""

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "provenance" / "source_manifest.csv"
FIELDS = ("source", "version", "source_url", "object_key", "local_path",
          "retrieved_utc", "byte_size", "sha256", "access_note", "first_consumer")


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def main():
    rows = read_csv(MANIFEST)
    nass = ROOT / "interim" / "nass_state_weeks.parquet"
    if not nass.exists():
        raise ValueError("NASS construction incomplete")
    spotchecks = read_csv(ROOT / "logs" / "nass_historical_publication_spotcheck.csv")
    for entry in spotchecks:
        path = Path(entry["publication_path"])
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
        if observed != entry["publication_sha256"]:
            raise ValueError(f"NASS publication snapshot SHA mismatch: {path}")
        rows.append({"source": "USDA NASS Crop Progress publication",
                     "version": f"released {entry['release_date']}",
                     "source_url": entry["publication_url"], "object_key": path.name,
                     "local_path": str(path), "retrieved_utc": "", "byte_size": path.stat().st_size,
                     "sha256": observed, "access_note": "Fixed-seed Quick Stats publication cross-check",
                     "first_consumer": "src/verify_nass_publications.py"})
    for label in ("asb", "quick_stats"):
        path = ROOT / "raw" / "nass" / f"corrections_{label}_2026-10-06.html"
        rows.append({"source": "USDA NASS corrections log", "version": "snapshot 2026-10-06",
                     "source_url": "https://www.nass.usda.gov/Corrections/index.php"+
                                   ("?log=QS" if label == "quick_stats" else ""),
                     "object_key": path.name, "local_path": str(path), "retrieved_utc": "",
                     "byte_size": path.stat().st_size,
                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "access_note": "Correction log search for Crop Progress and DSFW hits",
                     "first_consumer": "src/audit_nass_corrections.py"})
    nldas_inventory = {entry["granule_ur"]: entry
                       for entry in read_csv(ROOT / "raw" / "nldas_object_manifest.csv")}
    for path in sorted((ROOT / "raw" / "nldas_samples").glob("*/*.nc")):
        if "A20000101.0000.020" in path.name:
            continue  # Initial samples are already in the source manifest.
        product = path.parent.name
        granule_ur = product + ".2.0:" + path.name
        granule = nldas_inventory.get(granule_ur)
        if granule is None or not granule.get("get_data_url"):
            raise ValueError(f"NLDAS source-mask sample has no exact CMR URL: {granule_ur}")
        rows.append({"source": "NASA NLDAS-2", "version": product+".2.0",
                     "source_url": granule["get_data_url"], "object_key": granule_ur,
                     "local_path": str(path), "retrieved_utc": "", "byte_size": path.stat().st_size,
                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "access_note": "Authenticated source-mask audit sample; checksum covers full granule",
                     "first_consumer": "src/build_nldas_source_weights.py"})
    nldas_files = sorted((ROOT / "provenance" / "nldas_week_objects").glob("*.csv"))
    gefs11_files = sorted((ROOT / "provenance" / "gefs_11member_objects").glob("*.csv"))
    if len(nldas_files) != 202 or len(gefs11_files) != 280:
        raise ValueError(f"Incomplete object provenance: NLDAS {len(nldas_files)}/202, GEFS11 {len(gefs11_files)}/280")
    nldas_count = 0
    for path in nldas_files:
        for entry in read_csv(path):
            nldas_count += 1
            subset_url = entry.get("retrieved_subset_url", "")
            access_note = ("CMR granule; authenticated OPeNDAP NetCDF4 subset " +
                           entry.get("subset_variables", "") + "; SHA-256 covers retrieved subset") if subset_url else (
                           "CMR/Earthdata authenticated full-object retrieval; SHA-256 covers full object")
            payload_key = entry["granule_ur"] + ("#opendap_subset=" + entry["subset_variables"] if subset_url else "")
            rows.append({"source": "NASA NLDAS-2", "version": entry["collection_short_name"]+".2.0",
                         "source_url": subset_url or entry["get_data_url"], "object_key": payload_key,
                         "local_path": "", "retrieved_utc": entry["retrieved_utc"],
                         "byte_size": entry["byte_size"], "sha256": entry["sha256"],
                         "access_note": access_note,
                         "first_consumer": "src/build_nldas_hourly.py"})
    if nldas_count != 202*168*2:
        raise ValueError(f"NLDAS source object count {nldas_count} != {202*168*2}")
    gefs11_count = 0
    for path in gefs11_files:
        for entry in read_csv(path):
            gefs11_count += 1
            rows.append({name: entry[name] for name in FIELDS})
    if gefs11_count != 280*11:
        raise ValueError(f"GEFS eleven-member object count {gefs11_count} != {280*11}")
    keyed = {}
    for row in rows:
        key = (row["source"], row["version"], row["object_key"])
        if key in keyed and keyed[key]["sha256"] != row["sha256"]:
            raise ValueError(f"Source identity has conflicting retrieved bytes: {key}")
        keyed[key] = row
    ordered = [keyed[key] for key in sorted(keyed)]
    temporary = MANIFEST.with_suffix(".part")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(ordered)
    temporary.replace(MANIFEST)
    digest = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    (ROOT / "provenance" / "source_manifest.sha256").write_text(
        f"{digest}  source_manifest.csv\n", encoding="ascii")
    print(f"source objects {len(ordered)}; NLDAS {nldas_count}; Wednesday GEFS {gefs11_count}; SHA-256 {digest}", flush=True)


if __name__ == "__main__":
    main()
