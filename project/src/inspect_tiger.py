"""Inspect frozen state identities and geometry metadata from 2019 TIGER/Line."""

import io
import json
import zipfile
from pathlib import Path

import shapefile


ROOT = Path(__file__).resolve().parents[1]
ZIP = ROOT / "raw" / "tiger2019" / "tl_2019_us_state.zip"


def main():
    config = json.loads((ROOT / "config" / "frozen_design.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(ZIP) as archive:
        reader = shapefile.Reader(
            shp=io.BytesIO(archive.read("tl_2019_us_state.shp")),
            shx=io.BytesIO(archive.read("tl_2019_us_state.shx")),
            dbf=io.BytesIO(archive.read("tl_2019_us_state.dbf")),
        )
        selected = []
        for shape_record in reader.iterShapeRecords():
            record = shape_record.record.as_dict()
            if record["STUSPS"] in config["state_postal_codes"]:
                selected.append({
                    "postal_code": record["STUSPS"],
                    "state_fips": record["STATEFP"],
                    "name": record["NAME"],
                    "bbox_lon_lat": shape_record.shape.bbox,
                    "part_count": len(shape_record.shape.parts),
                })
    selected.sort(key=lambda x: x["postal_code"])
    expected = config["state_fips"]
    if len(selected) != 17 or any(item["state_fips"] != expected[item["postal_code"]] for item in selected):
        raise ValueError("2019 TIGER state identities do not match frozen 17-state frame")
    output = {"source": str(ZIP), "selected_states": selected, "selected_count": len(selected)}
    target = ROOT / "spatial" / "state_boundary_audit.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print("verified 2019 TIGER state identities:", len(selected))


if __name__ == "__main__":
    main()
