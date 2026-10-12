"""Snapshot the independent NASS state-year corn planted-acreage source."""

import csv
import gzip
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
URL = "https://www.nass.usda.gov/datasets/qs.crops_20261007.txt.gz"
RAW = ROOT / "raw" / "nass_annual_acreage" / "qs.crops_20261007.txt.gz"
SUBSET = ROOT / "raw" / "nass_annual_acreage" / "corn_area_planted_2000_2019_17states.csv"
MANIFEST = ROOT / "provenance" / "p1_m2_nass_acreage_source.json"
STATES = set(json.loads((ROOT / "config" / "frozen_design.json").read_text())["state_postal_codes"])
SHORT_DESC = "CORN - ACRES PLANTED"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    RAW.parent.mkdir(parents=True, exist_ok=True)
    sidecar = RAW.with_suffix(RAW.suffix + ".sha256")
    if RAW.exists():
        if not sidecar.exists() or digest(RAW) != sidecar.read_text(encoding="ascii").split()[0]:
            raise ValueError("Immutable NASS acreage snapshot hash mismatch")
        if MANIFEST.exists():
            source_meta = json.loads(MANIFEST.read_text(encoding="utf-8"))
            if source_meta.get("sha256") != digest(RAW):
                raise ValueError("NASS acreage source manifest differs from immutable snapshot")
        else:
            head = requests.head(URL, timeout=30, allow_redirects=True)
            head.raise_for_status()
            headers = {key: head.headers.get(key) for key in
                       ("Content-Length", "ETag", "Last-Modified", "Content-Type")}
            if headers["Content-Length"] and RAW.stat().st_size != int(headers["Content-Length"]):
                raise ValueError("NASS acreage snapshot differs from current object length")
            source_meta = {"source": "USDA NASS Quick Stats daily crops bulk dataset",
                           "source_url": URL,
                           "retrieved_utc": datetime.fromtimestamp(RAW.stat().st_mtime, timezone.utc).isoformat(),
                           "http_headers": headers, "byte_size": RAW.stat().st_size,
                           "sha256": digest(RAW), "local_path": str(RAW)}
    else:
        if sidecar.exists():
            raise ValueError("NASS acreage hash sidecar exists without source snapshot")
        temp = RAW.with_suffix(RAW.suffix + ".part")
        h = hashlib.sha256()
        size = 0
        with requests.get(URL, stream=True, timeout=180) as response:
            response.raise_for_status()
            headers = {key: response.headers.get(key) for key in
                       ("Content-Length", "ETag", "Last-Modified", "Content-Type")}
            with temp.open("wb") as stream:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        stream.write(chunk)
                        h.update(chunk)
                        size += len(chunk)
                        if size // (100 * 1024 * 1024) != (size-len(chunk)) // (100 * 1024 * 1024):
                            print(f"NASS acreage snapshot downloaded {size // (1024 * 1024)} MiB", flush=True)
        if headers["Content-Length"] and size != int(headers["Content-Length"]):
            temp.unlink(missing_ok=True)
            raise ValueError("NASS acreage source byte count differs from HTTP header")
        os.replace(temp, RAW)
        sidecar.write_text(f"{h.hexdigest()}  {RAW.name}\n", encoding="ascii")
        source_meta = {"source": "USDA NASS Quick Stats daily crops bulk dataset",
                       "source_url": URL, "retrieved_utc": datetime.now(timezone.utc).isoformat(),
                       "http_headers": headers, "byte_size": size, "sha256": h.hexdigest(),
                       "local_path": str(RAW)}
    with gzip.open(RAW, "rb") as stream:
        fieldnames = stream.readline().rstrip(b"\r\n").decode("utf-8").split("\t")
        required = {"SOURCE_DESC", "COMMODITY_DESC", "SHORT_DESC", "AGG_LEVEL_DESC",
                    "FREQ_DESC", "DOMAIN_DESC", "YEAR", "STATE_ALPHA", "VALUE",
                    "UNIT_DESC", "CLASS_DESC", "REFERENCE_PERIOD_DESC"}
        if not required.issubset(fieldnames):
            raise ValueError("NASS acreage bulk schema lacks required descriptors")
        candidates = []
        for line in stream:
            if b"\tCORN - ACRES PLANTED\t" not in line:
                continue
            parts = line.rstrip(b"\r\n").split(b"\t")
            if len(parts) != len(fieldnames):
                raise ValueError("NASS acreage record does not match source header width")
            row = dict(zip(fieldnames, (part.decode("utf-8", errors="replace") for part in parts)))
            if (row["SHORT_DESC"] == SHORT_DESC and row["SOURCE_DESC"] == "SURVEY"
                    and row["AGG_LEVEL_DESC"] == "STATE" and row["STATE_ALPHA"] in STATES
                    and row["YEAR"].isdigit() and 2000 <= int(row["YEAR"]) <= 2019):
                candidates.append(row)
    found = [row for row in candidates if
             row["FREQ_DESC"] == "ANNUAL" and row["DOMAIN_DESC"] == "TOTAL" and
             row["UNIT_DESC"] == "ACRES" and row["REFERENCE_PERIOD_DESC"] == "YEAR" and
             row["CLASS_DESC"] == "ALL CLASSES" and
             row["PRODN_PRACTICE_DESC"] == "ALL PRODUCTION PRACTICES" and
             row["UTIL_PRACTICE_DESC"] == "ALL UTILIZATION PRACTICES" and
             row["STATISTICCAT_DESC"] == "AREA PLANTED"]
    if len(found) != 17 * 20:
        patterns = Counter((row["FREQ_DESC"], row["DOMAIN_DESC"], row["CLASS_DESC"],
                            row["PRODN_PRACTICE_DESC"], row["UTIL_PRACTICE_DESC"],
                            row["STATISTICCAT_DESC"]) for row in candidates)
        raise ValueError(f"NASS planted acreage rows {len(found)} != 340; "
                         f"candidate descriptor patterns: {patterns.most_common(10)}")
    for column, expected in {"COMMODITY_DESC": "CORN", "FREQ_DESC": "ANNUAL",
                             "DOMAIN_DESC": "TOTAL", "UNIT_DESC": "ACRES",
                             "REFERENCE_PERIOD_DESC": "YEAR"}.items():
        observed = {row[column] for row in found}
        if observed != {expected}:
            raise ValueError(f"NASS acreage {column} semantics differ: {observed}")
    if len({(row["STATE_ALPHA"], row["YEAR"]) for row in found}) != 340:
        raise ValueError("NASS acreage state-year records are not unique")
    if any(float(row["VALUE"].replace(",", "")) <= 0 for row in found):
        raise ValueError("NASS acreage contains missing or nonpositive values")
    if SUBSET.exists():
        if source_meta.get("subset_sha256") != digest(SUBSET):
            raise ValueError("Existing immutable acreage subset hash mismatch")
    else:
        with SUBSET.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(sorted(found, key=lambda row: (row["STATE_ALPHA"], int(row["YEAR"]))))
        source_meta["subset_path"] = str(SUBSET)
        source_meta["subset_sha256"] = digest(SUBSET)
        source_meta["subset_rows"] = len(found)
        source_meta["broad_candidate_rows"] = len(candidates)
        source_meta["selection"] = {"short_desc": SHORT_DESC, "source": "SURVEY",
                                    "geo": "STATE", "domain": "TOTAL", "frequency": "ANNUAL",
                                    "states": sorted(STATES), "years": "2000-2019"}
        if MANIFEST.exists():
            raise ValueError("Acreage source manifest exists before first subset; refusing overwrite")
        MANIFEST.write_text(json.dumps(source_meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(found), "states": 17, "years": 20,
                      "raw_sha256": digest(RAW), "subset_sha256": digest(SUBSET)}, indent=2))


if __name__ == "__main__":
    main()
