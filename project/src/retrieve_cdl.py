"""Resumable write-once retrieval of official annual 30-m national CDL ZIPs."""

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
BASE = "https://www.nass.usda.gov/Research_and_Science/Cropland/Release/datasets"
MANIFEST = ROOT / "provenance" / "source_manifest.csv"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(year):
    if year not in range(2008, 2020):
        raise ValueError("year outside frozen CDL mask period")
    filename = f"{year}_30m_cdls.zip"
    url = f"{BASE}/{filename}"
    path = ROOT / "raw" / "cdl" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    prior = {}
    if MANIFEST.exists():
        with MANIFEST.open(newline="", encoding="utf-8") as stream:
            prior = {row["source_url"]: row for row in csv.DictReader(stream)}
    if not path.exists():
        head = requests.head(url, timeout=60)
        head.raise_for_status()
        expected_size = int(head.headers["Content-Length"])
        etag = head.headers.get("ETag")
        partial = path.with_suffix(".part")
        sidecar = path.with_suffix(".part.json")
        if partial.exists():
            if not sidecar.exists() or json.loads(sidecar.read_text())["etag"] != etag:
                raise RuntimeError("partial object lacks matching source ETag")
            offset = partial.stat().st_size
        else:
            offset = 0
            sidecar.write_text(json.dumps({"url": url, "etag": etag,
                                           "expected_size": expected_size}) + "\n", encoding="utf-8")
        if offset > expected_size:
            raise RuntimeError("partial object exceeds expected size")
        if offset < expected_size:
            headers = {"Range": f"bytes={offset}-"} if offset else {}
            response = requests.get(url, headers=headers, timeout=120, stream=True)
            response.raise_for_status()
            if offset and response.status_code != 206:
                raise RuntimeError("server did not honor resume range")
            with partial.open("ab") as stream:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        stream.write(chunk)
        if partial.stat().st_size != expected_size:
            raise RuntimeError("CDL ZIP incomplete after transfer")
        partial.rename(path)
        sidecar.unlink()
        retrieved = datetime.now(timezone.utc).isoformat()
    else:
        old = prior.get(url)
        if old is None or old["sha256"] != sha256(path):
            raise RuntimeError("cached CDL object lacks matching immutable manifest entry")
        retrieved = old["retrieved_utc"]
    row = {
        "source": "USDA NASS Cropland Data Layer",
        "version": f"{year} national 30-m CDL",
        "source_url": url,
        "object_key": filename,
        "local_path": str(path),
        "retrieved_utc": retrieved,
        "byte_size": path.stat().st_size,
        "sha256": sha256(path),
        "access_note": "Official NASS public annual 30-m CDL ZIP; fixed-mask input",
        "first_consumer": "src/build_corn_frequency.py",
    }
    prior[url] = row
    with MANIFEST.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerows(prior[u] for u in sorted(prior))
    print(filename, row["byte_size"], row["sha256"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("year", type=int)
    download(parser.parse_args().year)
