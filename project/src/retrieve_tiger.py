"""Write-once retrieval of the frozen 2019 TIGER/Line state boundary object."""

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
URL = "https://www2.census.gov/geo/tiger/TIGER2019/STATE/tl_2019_us_state.zip"
TARGET = ROOT / "raw" / "tiger2019" / "tl_2019_us_state.zip"
MANIFEST = ROOT / "provenance" / "source_manifest.csv"


def main():
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    prior = {}
    if MANIFEST.exists():
        with MANIFEST.open(newline="", encoding="utf-8") as stream:
            prior = {row["source_url"]: row for row in csv.DictReader(stream)}
    if not TARGET.exists():
        response = requests.get(URL, timeout=120, stream=True)
        response.raise_for_status()
        temporary = TARGET.with_suffix(".download")
        with temporary.open("wb") as stream:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    stream.write(chunk)
        temporary.rename(TARGET)
        retrieved = datetime.now(timezone.utc).isoformat()
    else:
        old = prior.get(URL)
        if old is None:
            raise RuntimeError("cached boundary object lacks provenance entry")
        retrieved = old["retrieved_utc"]
    observed = hashlib.sha256(TARGET.read_bytes()).hexdigest()
    old = prior.get(URL)
    if old is not None and old["sha256"] != observed:
        raise RuntimeError("immutable boundary object hash changed")
    row = {
        "source": "US Census TIGER/Line state boundaries",
        "version": "2019",
        "source_url": URL,
        "object_key": "geo/tiger/TIGER2019/STATE/tl_2019_us_state.zip",
        "local_path": str(TARGET),
        "retrieved_utc": retrieved,
        "byte_size": TARGET.stat().st_size,
        "sha256": observed,
        "access_note": "Public Census ZIP; legal state boundaries as of 2019-01-01",
        "first_consumer": "src/inspect_tiger.py",
    }
    prior[URL] = row
    with MANIFEST.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerows(prior[url] for url in sorted(prior))
    print(TARGET, TARGET.stat().st_size, observed)


if __name__ == "__main__":
    main()
