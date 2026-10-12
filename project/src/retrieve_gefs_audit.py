"""Fetch fixed representative GEFS GRIB objects for the frozen metadata audit."""

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
CYCLES = ["2000030600", "2010030800", "2019030400"]
BASE = "https://noaa-gefs-retrospective.s3.amazonaws.com/GEFSv12/reforecast"


def main() -> None:
    raw = ROOT / "raw" / "gefs_metadata_audit"
    raw.mkdir(parents=True, exist_ok=True)
    manifest = ROOT / "provenance" / "source_manifest.csv"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    prior = {}
    if manifest.exists():
        with manifest.open(newline="", encoding="utf-8") as stream:
            prior = {row["source_url"]: row for row in csv.DictReader(stream)}
    rows = []
    for cycle in CYCLES:
        filename = f"apcp_sfc_{cycle}_c00.grib2"
        url = f"{BASE}/{cycle[:4]}/{cycle}/c00/Days%3A1-10/{filename}"
        path = raw / filename
        if not path.exists():
            response = requests.get(url, timeout=120, stream=True)
            response.raise_for_status()
            temporary = path.with_suffix(".download")
            digest = hashlib.sha256()
            count = 0
            with temporary.open("wb") as stream:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        stream.write(chunk)
                        digest.update(chunk)
                        count += len(chunk)
            temporary.rename(path)
            retrieved = datetime.now(timezone.utc).isoformat()
        else:
            digest = hashlib.sha256(path.read_bytes())
            count = path.stat().st_size
            old = prior.get(url)
            if old is None or old["sha256"] != digest.hexdigest():
                raise RuntimeError(f"immutable raw object lacks matching prior manifest: {path}")
            retrieved = old["retrieved_utc"]
        rows.append({
            "source": "NOAA GEFSv12 reforecast",
            "version": "GEFSv12 retrospective 2000-2019",
            "source_url": url,
            "object_key": url.split(".com/", 1)[1],
            "local_path": str(path),
            "retrieved_utc": retrieved,
            "byte_size": count,
            "sha256": digest.hexdigest(),
            "access_note": "NOAA public AWS S3; metadata-audit sample",
            "first_consumer": "src/decode_gefs_audit.py",
        })
        print(cycle, count, digest.hexdigest())
    prior.update({row["source_url"]: row for row in rows})
    with manifest.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(prior[url] for url in sorted(prior))


if __name__ == "__main__":
    main()
