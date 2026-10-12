"""Retrieve the exact frozen Quick Stats export IDs without replacing snapshots."""

import csv
import hashlib
import os
from pathlib import Path

import requests

from build_nass import EXPORTS, ROOT


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def main():
    folder = ROOT / "raw" / "nass"
    folder.mkdir(parents=True, exist_ok=True)
    manifest = ROOT / "provenance" / "source_manifest.csv"
    known = {}
    if manifest.exists():
        with manifest.open(newline="", encoding="utf-8") as stream:
            known = {row["source_url"]: row for row in csv.DictReader(stream)}
    for filename, export_id in EXPORTS.items():
        url = f"https://quickstats.nass.usda.gov/data/spreadsheet/{export_id}.csv"
        path = folder / filename
        sidecar = path.with_suffix(path.suffix + ".sha256")
        if path.exists():
            observed = digest(path)
            if sidecar.exists():
                if observed != sidecar.read_text(encoding="ascii").strip():
                    raise ValueError(f"NASS immutable snapshot sidecar mismatch: {filename}")
            elif url in known:
                if observed != known[url]["sha256"]:
                    raise ValueError(f"NASS source manifest hash mismatch: {filename}")
                sidecar.write_text(observed + "\n", encoding="ascii")
            else:
                response = requests.get(url, timeout=180)
                response.raise_for_status()
                if hashlib.sha256(response.content).hexdigest() != observed:
                    raise ValueError(f"Existing NASS snapshot differs from current source and has no prior hash evidence: {filename}")
                sidecar.write_text(observed + "\n", encoding="ascii")
            continue
        if sidecar.exists():
            raise ValueError(f"NASS sidecar exists without snapshot: {filename}")
        temporary = path.with_suffix(path.suffix + ".part")
        with requests.get(url, stream=True, timeout=180) as response:
            response.raise_for_status()
            with temporary.open("wb") as stream:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        stream.write(chunk)
        if temporary.stat().st_size < 100:
            temporary.unlink()
            raise ValueError(f"NASS export unexpectedly short: {filename}")
        os.replace(temporary, path)
        sidecar.write_text(digest(path) + "\n", encoding="ascii")
    print(f"Verified {len(EXPORTS)} immutable NASS Quick Stats export snapshots", flush=True)


if __name__ == "__main__":
    main()
