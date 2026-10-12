"""Outcome-blind public-source access preflight with reproducible response metadata."""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
S = requests.Session()
S.headers.update({"User-Agent": "corn-belt-f1-provenance-audit/1.0"})


def probe(url: str, method: str = "GET", headers=None) -> dict:
    try:
        r = S.request(method, url, timeout=45, allow_redirects=True, headers=headers)
        result = {
            "url": url,
            "method": method,
            "status_code": r.status_code,
            "final_url": r.url,
            "content_type": r.headers.get("Content-Type"),
            "content_length_header": r.headers.get("Content-Length"),
            "response_bytes": len(r.content),
            "response_sha256": hashlib.sha256(r.content).hexdigest() if method == "GET" else None,
            "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        }
        return result, r
    except requests.RequestException as e:
        return {"url": url, "method": method, "error": str(e)}, None


def main() -> None:
    probes = {}
    nass_url = "https://www.nass.usda.gov/datasets/"
    probes["nass_catalog"], nass = probe(nass_url)
    if nass is not None and nass.ok:
        links = re.findall(r'''href=["']([^"']*qs\.crops_[^"']*\.gz)["']''', nass.text, re.I)
        probes["nass_crop_bulk_links"] = sorted(set(links))
    s3_url = "https://noaa-gefs-retrospective.s3.amazonaws.com/?list-type=2&prefix=GEFSv12/reforecast/2000/2000030600/&max-keys=10"
    probes["gefs_s3_listing"], listing = probe(s3_url)
    if listing is not None and listing.ok:
        probes["gefs_s3_keys"] = re.findall(r"<Key>(.*?)</Key>", listing.text)
    nldas_url = "https://hydro1.gesdisc.eosdis.nasa.gov/data/NLDAS/NLDAS_FORA0125_H.2.0/2000/001/NLDAS_FORA0125_H.A20000101.0000.020.nc"
    probes["nldas_forcing_head"], _ = probe(nldas_url, "HEAD")
    probes["nldas_forcing_get_range"], _ = probe(nldas_url, "GET", {"Range": "bytes=0-15"})
    nldas_noah_url = "https://hydro1.gesdisc.eosdis.nasa.gov/data/NLDAS/NLDAS_NOAH0125_H.2.0/2000/001/NLDAS_NOAH0125_H.A20000101.0000.020.nc"
    probes["nldas_noah_get_range"], _ = probe(nldas_noah_url, "GET", {"Range": "bytes=0-15"})
    target = ROOT / "logs" / "source_access_preflight.json"
    target.write_text(json.dumps(probes, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(probes, indent=2))


if __name__ == "__main__":
    main()
