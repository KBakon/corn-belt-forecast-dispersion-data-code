"""Check both frozen NLDAS collections without exposing Earthdata secrets."""

import json
from datetime import datetime, timezone
from pathlib import Path

import earthaccess


ROOT = Path(__file__).resolve().parents[1]
NAMES = ("NLDAS_FORA0125_H", "NLDAS_NOAH0125_H")


def main():
    result = {"checked_utc": datetime.now(timezone.utc).isoformat(), "collections": {}}
    auth = earthaccess.login(strategy="netrc", persist=False)
    result["netrc_login_authenticated"] = bool(auth.authenticated)
    if not auth.authenticated:
        raise RuntimeError("Earthdata netrc login was not authenticated")
    for name in NAMES:
        record = {}
        result["collections"][name] = record
        try:
            matches = earthaccess.search_data(
                short_name=name,
                version="2.0",
                temporal=("2000-01-01T00:00:00", "2000-01-01T00:00:01"),
                count=1,
            )
            if len(matches) != 1:
                raise RuntimeError("unexpected_granule_count")
            record["granule_ur"] = matches[0]["umm"]["GranuleUR"]
            paths = earthaccess.download(
                matches,
                local_path=ROOT / "raw" / "nldas_samples" / name,
                threads=1,
                show_progress=False,
            )
            record["status"] = "downloaded" if len(paths) == 1 else "unexpected_download_count"
        except Exception as error:
            record["status"] = "failed"
            record["error_type"] = type(error).__name__
    output = ROOT / "logs" / "nldas_access_diagnostic.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
