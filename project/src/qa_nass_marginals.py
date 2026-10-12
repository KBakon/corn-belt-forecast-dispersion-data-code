"""Outcome-only QA block C, isolated from all GEFS predictor data."""

import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parents[1] / "tmp" / "matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "QA"


def describe(series):
    values = series.dropna()
    if values.empty:
        return {"n": 0, **{key: None for key in ("mean", "sd", "min", "p01", "p05", "p25",
                                                   "median", "p75", "p95", "p99", "max")}}
    return {"n": len(values), "mean": float(values.mean()),
            "sd": float(values.std()) if len(values) > 1 else None,
            "min": float(values.min()), "p01": float(values.quantile(.01)),
            "p05": float(values.quantile(.05)), "p25": float(values.quantile(.25)),
            "median": float(values.median()), "p75": float(values.quantile(.75)),
            "p95": float(values.quantile(.95)), "p99": float(values.quantile(.99)),
            "max": float(values.max())}


def main():
    QA.mkdir(exist_ok=True)
    frame = pd.read_parquet(ROOT / "interim" / "nass_state_weeks.parquet")
    metrics = {
        "block": "C", "source": "NASS-only interim panel; no GEFS fields loaded",
        "dsfw_distribution": describe(frame["dsfw_days"]),
        "increment_distribution": describe(frame["planting_increment_pp"]),
        "remaining_start_distribution": describe(frame["remaining_start_pp"]),
        "dsfw_zero_rows": int(frame["dsfw_zero_flag"].sum()),
        "negative_increment_rows": int(frame["planting_increment_pp"].lt(0).sum()),
        "active_zero_increment_rows": int((frame["active_week_flag"] & frame["planting_increment_pp"].eq(0)).sum()),
        "dsfw_zero_nonzero_increment_rows": int((frame["dsfw_zero_flag"] & frame["planting_increment_pp"].notna() & frame["planting_increment_pp"].ne(0)).sum()),
    }
    grouped = frame.groupby(["state_postal", "seasonal_week"])
    metrics["by_state_seasonal_week"] = [
        {"state": state, "seasonal_week": int(week),
         "dsfw_distribution": describe(group["dsfw_days"]),
         "increment_distribution": describe(group["planting_increment_pp"])}
        for (state, week), group in grouped]
    metrics["active_counts_state_year"] = [
        {"state": state, "year": int(year), "active_weeks": int(group["active_week_flag"].sum())}
        for (state, year), group in frame.groupby(["state_postal", "crop_year"])]
    (QA / "nass_marginals.json").write_text(json.dumps(metrics, indent=2) + "\n")
    for column, title, filename in (
        ("dsfw_days", "NASS Days Suitable for Fieldwork", "nass_dsfw_hist.png"),
        ("planting_increment_pp", "Weekly corn planting increment (pp)", "nass_increment_hist.png"),
        ("remaining_start_pp", "Unplanted share at interval start (pp)", "nass_remaining_hist.png"),
    ):
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.hist(frame[column].dropna(), bins=30, color="#2b6b85", edgecolor="white")
        ax.set_title(title)
        ax.set_ylabel("State-weeks")
        ax.set_xlabel(column)
        fig.tight_layout()
        fig.savefig(QA / filename, dpi=140)
        plt.close(fig)
    print("NASS-only QA block C built")


if __name__ == "__main__":
    main()
