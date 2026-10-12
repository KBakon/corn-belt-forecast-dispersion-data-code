"""Build fixed CDL 2008–2019 corn-frequency masks and conservative grid weights.

The annual national TIFF is extracted temporarily from its immutable ZIP.
Count rasters have a scale of 1/12: count 12 means corn in every CDL year.
No planting or forecast values are read by this module.
"""

import io
import json
import shutil
import zipfile
from pathlib import Path

import numpy as np
import pyproj
import rasterio
import rasterio.features
import rasterio.warp
import rasterio.windows
import shapefile
from rasterio.enums import Resampling
from shapely.geometry import shape
from shapely.ops import transform as transform_geometry


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "frozen_design.json").read_text())
SOURCE_TRANSFORM = rasterio.Affine(30, 0, -2356095, 0, -30, 3172605)
SOURCE_SHAPE = (96523, 153811)
TARGETS = {
    "gefs": {"shape": (721, 1440), "transform": rasterio.Affine(.25, 0, -180.125, 0, -.25, 90.125)},
    "nldas": {"shape": (224, 464), "transform": rasterio.Affine(.125, 0, -125, 0, -.125, 53)},
}


def state_geometries():
    path = ROOT / "raw" / "tiger2019" / "tl_2019_us_state.zip"
    with zipfile.ZipFile(path) as archive:
        def member(extension):
            return io.BytesIO(archive.read(f"tl_2019_us_state.{extension}"))
        reader = shapefile.Reader(shp=member("shp"), shx=member("shx"), dbf=member("dbf"))
        convert = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True).transform
        output = {}
        for item in reader.iterShapeRecords():
            postal = item.record.as_dict()["STUSPS"]
            if postal not in CONFIG["state_postal_codes"]:
                continue
            geographic = shape(item.shape.__geo_interface__)
            projected = transform_geometry(convert, geographic)
            window = rasterio.windows.from_bounds(*projected.bounds, transform=SOURCE_TRANSFORM)
            col_start = max(0, int(np.floor(window.col_off)))
            row_start = max(0, int(np.floor(window.row_off)))
            col_stop = min(SOURCE_SHAPE[1], int(np.ceil(window.col_off + window.width)))
            row_stop = min(SOURCE_SHAPE[0], int(np.ceil(window.row_off + window.height)))
            window = rasterio.windows.Window(col_start, row_start, col_stop-col_start, row_stop-row_start)
            output[postal] = {"geographic": geographic, "projected": projected, "window": window}
    if set(output) != set(CONFIG["state_postal_codes"]):
        raise ValueError("TIGER state geometry frame mismatch")
    return output


def annual_tiff(year):
    archive_path = ROOT / "raw" / "cdl" / f"{year}_30m_cdls.zip"
    temporary = ROOT / "tmp" / f"{year}_30m_cdls.tif"
    temporary.parent.mkdir(exist_ok=True)
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(archive_path) as archive:
        info = archive.getinfo(temporary.name)
        with archive.open(info) as source, temporary.open("wb") as destination:
            shutil.copyfileobj(source, destination, length=8 * 1024 * 1024)
    if temporary.stat().st_size != info.file_size:
        raise ValueError(f"CDL TIFF extraction size mismatch in {year}")
    return temporary


def write_frequency_geotiff(postal, count, local_transform):
    path = ROOT / "spatial" / "corn_frequency_count" / f"{postal}_cdl_2008_2019_count.tif"
    path.parent.mkdir(parents=True, exist_ok=True)
    height, width = count.shape
    with rasterio.open(path, "w", driver="GTiff", width=width, height=height, count=1,
                       dtype="uint8", crs="EPSG:5070", transform=local_transform,
                       tiled=True, blockxsize=512, blockysize=512, compress="deflate") as target:
        target.update_tags(frequency_scale="1/12", corn_cdl_value="1",
                           source_years="2008-2019", state=postal)
        for _, window in target.block_windows(1):
            rows, cols = window.toslices()
            target.write(np.asarray(count[rows, cols]), 1, window=window)
    return path


def target_window(geometry, target):
    transform = target["transform"]
    y_size, x_size = target["shape"]
    bounds = geometry.bounds
    window = rasterio.windows.from_bounds(*bounds, transform=transform)
    col_start = max(0, int(np.floor(window.col_off)) - 1)
    row_start = max(0, int(np.floor(window.row_off)) - 1)
    col_stop = min(x_size, int(np.ceil(window.col_off + window.width)) + 1)
    row_stop = min(y_size, int(np.ceil(window.row_off + window.height)) + 1)
    return rasterio.windows.Window(col_start, row_start, col_stop-col_start, row_stop-row_start)


def build_weights(postal, count, local_transform, geometry, grid_name, grid, weight_kind="corn"):
    window = target_window(geometry, grid)
    dest = np.zeros((int(window.height), int(window.width)), dtype=np.float64)
    rasterio.warp.reproject(
        source=np.asarray(count), destination=dest,
        src_transform=local_transform, src_crs="EPSG:5070", src_nodata=0,
        dst_transform=rasterio.windows.transform(window, grid["transform"]),
        dst_crs="EPSG:4326", dst_nodata=0,
        resampling=Resampling.sum, num_threads=2,
    )
    raw_sum = float(dest.sum())
    if raw_sum <= 0:
        raise ValueError(f"No corn weight in {postal} for {grid_name}")
    rows, cols = np.nonzero(dest > 0)
    weights = dest[rows, cols] / raw_sum
    if not np.isclose(weights.sum(), 1, atol=1e-10):
        raise ValueError(f"Unnormalized {grid_name} weights for {postal}")
    folder = f"{grid_name}_weights" if weight_kind == "corn" else f"{grid_name}_{weight_kind}_weights"
    table = ROOT / "spatial" / folder / f"{postal}.csv"
    table.parent.mkdir(parents=True, exist_ok=True)
    data = np.column_stack((rows + int(window.row_off), cols + int(window.col_off), weights))
    np.savetxt(table, data, fmt=["%d", "%d", "%.15g"], delimiter=",",
               header="row_index,col_index,normalized_corn_frequency_weight", comments="")
    return {"grid": grid_name, "state": postal, "positive_cells": int(len(weights)),
            "weight_sum": float(weights.sum()), "raw_frequency_count_grid_sum": raw_sum,
            "source_count_pixel_sum": int(np.asarray(count).sum()), "table": str(table)}


def main():
    states = state_geometries()
    scratch = ROOT / "spatial" / "scratch_counts"
    scratch.mkdir(parents=True, exist_ok=True)
    counts = {}
    for postal, item in states.items():
        shape = (int(item["window"].height), int(item["window"].width))
        path = scratch / f"{postal}.dat"
        count = np.memmap(path, mode="w+", dtype="uint8", shape=shape)
        count[:] = 0
        count.flush()
        counts[postal] = count
    progress_path = ROOT / "logs" / "cdl_processing_progress.json"
    for year in CONFIG["spatial_cdl_years"]:
        tiff = annual_tiff(year)
        with rasterio.open(tiff) as raster:
            if raster.shape != SOURCE_SHAPE or raster.transform != SOURCE_TRANSFORM or str(raster.crs) != "EPSG:5070":
                raise ValueError(f"CDL {year} grid differs from frozen frequency grid")
            for postal, item in states.items():
                state_window = item["window"]
                local_transform = rasterio.windows.transform(state_window, SOURCE_TRANSFORM)
                count = counts[postal]
                for row in range(0, count.shape[0], 1024):
                    height = min(1024, count.shape[0]-row)
                    block = rasterio.windows.Window(state_window.col_off, state_window.row_off+row,
                                                    state_window.width, height)
                    values = raster.read(1, window=block)
                    block_transform = rasterio.windows.transform(block, SOURCE_TRANSFORM)
                    inside = rasterio.features.rasterize(
                        [(item["projected"], 1)], out_shape=values.shape,
                        transform=block_transform, fill=0, dtype="uint8")
                    count[row:row+height] += ((values == 1) & (inside == 1)).astype("uint8")
                count.flush()
        tiff.unlink()
        progress_path.write_text(json.dumps({"last_completed_year": year,
                                             "completed_years": year-2007}) + "\n")
        print("completed CDL year", year, flush=True)
    audit = []
    for postal, item in sorted(states.items()):
        count = counts[postal]
        transform = rasterio.windows.transform(item["window"], SOURCE_TRANSFORM)
        frequency_tiff = write_frequency_geotiff(postal, count, transform)
        for name, grid in TARGETS.items():
            record = build_weights(postal, count, transform, item["geographic"], name, grid)
            record["frequency_tiff"] = str(frequency_tiff)
            audit.append(record)
    output = ROOT / "spatial" / "weight_audit.json"
    output.write_text(json.dumps(audit, indent=2) + "\n")
    print("verified", len(audit), "state-grid weight tables", flush=True)


if __name__ == "__main__":
    main()
