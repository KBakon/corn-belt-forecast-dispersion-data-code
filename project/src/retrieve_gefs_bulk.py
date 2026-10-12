"""Cache immutable GEFS five-member objects in the frozen ISO-week scaling frame."""

import argparse
import csv
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "raw" / "gefs_object_manifest_iso13_26.csv"
PROGRESS = ROOT / "logs" / "gefs_bulk_retrieval.jsonl"
MANIFEST = ROOT / "provenance" / "source_manifest.csv"


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def retrieve(row):
    if row["status_code"] != "200":
        raise ValueError("GEFS inventory object was not HTTP 200")
    key = row["object_key"]
    cycle = row["archive_cycle"]
    member = row["member"]
    path = ROOT / "raw" / "gefs_bulk" / cycle / f"{member}.grib2"
    sidecar = path.with_suffix(".sha256")
    path.parent.mkdir(parents=True, exist_ok=True)
    expected_size = int(row["content_length"])
    if path.exists() and sidecar.exists():
        prior = sidecar.read_text().strip()
        if path.stat().st_size != expected_size or digest(path) != prior:
            raise ValueError(f"Cached GEFS object differs from its immutable sidecar: {key}")
        sha = prior
    else:
        if path.exists() and not sidecar.exists():
            # Recover only a complete, source-ETag-verified object after a
            # process interruption between the atomic rename and sidecar.
            etag = row["etag"].strip('"')
            md5 = hashlib.md5()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    md5.update(chunk)
            if path.stat().st_size == expected_size and md5.hexdigest() == etag:
                sha = digest(path)
                sidecar.write_text(sha + "\n")
                return {
                    "source": "NOAA GEFSv12 reforecast", "version": "GEFSv12 retrospective 2000-2019",
                    "source_url": row["source_url"], "object_key": key, "local_path": str(path),
                    "retrieved_utc": datetime.now(timezone.utc).isoformat(), "byte_size": expected_size,
                    "sha256": sha, "access_note": "NOAA public S3; recovered after ETag verification",
                    "first_consumer": "src/build_gefs_features.py",
                }
            raise ValueError(f"Unverified cached GEFS object after interruption: {key}")
        if sidecar.exists() and not path.exists():
            raise ValueError(f"GEFS sidecar without object: {key}")
        temporary = path.with_suffix(".part")
        if temporary.exists():
            temporary.unlink()
        sha_obj = hashlib.sha256()
        size = 0
        with requests.get(row["source_url"], stream=True, timeout=180) as response:
            response.raise_for_status()
            with temporary.open("wb") as stream:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        sha_obj.update(chunk)
                        size += len(chunk)
                        stream.write(chunk)
        if size != expected_size:
            temporary.unlink()
            raise ValueError(f"GEFS object byte count differs from inventory: {key}")
        os.replace(temporary, path)
        sha = sha_obj.hexdigest()
        sidecar.write_text(sha + "\n")
    return {
        "source": "NOAA GEFSv12 reforecast",
        "version": "GEFSv12 retrospective 2000-2019",
        "source_url": row["source_url"],
        "object_key": key,
        "local_path": str(path),
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "byte_size": expected_size,
        "sha256": sha,
        "access_note": "NOAA public S3; frozen Monday archive cycle; five-member ISO-week 13-26 design frame",
        "first_consumer": "src/build_gefs_features.py",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, default=INVENTORY)
    inventory_path = parser.parse_args().inventory
    with inventory_path.open(newline="", encoding="utf-8") as stream:
        inventory = list(csv.DictReader(stream))
    with MANIFEST.open(newline="", encoding="utf-8") as stream:
        prior = {row["source_url"]: row for row in csv.DictReader(stream)}
    finished = {}
    if PROGRESS.exists():
        for line in PROGRESS.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            finished[row["source_url"]] = row
    remaining = [row for row in inventory if row["source_url"] not in finished]
    with PROGRESS.open("a", encoding="utf-8") as progress, ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(retrieve, row): row for row in remaining}
        for number, future in enumerate(as_completed(futures), 1):
            row = future.result()
            progress.write(json.dumps(row) + "\n")
            progress.flush()
            finished[row["source_url"]] = row
            if number % 100 == 0:
                print(number, "of", len(remaining), "new GEFS objects cached", flush=True)
    prior.update(finished)
    with MANIFEST.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(next(iter(prior.values()))))
        writer.writeheader()
        writer.writerows(prior[url] for url in sorted(prior))
    print("GEFS objects verified:", len(finished), flush=True)


if __name__ == "__main__":
    main()
