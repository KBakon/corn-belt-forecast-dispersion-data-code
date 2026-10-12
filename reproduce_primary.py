"""Bounded rerun of the accepted primary model from the bundled frozen panel.

This imports the unchanged primary_inference.py. It does not rerun source
retrieval, the five mandatory specification sensitivities, CR2 or Conley.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
PROJECT = HERE / "project"
sys.path.insert(0, str(PROJECT / "src"))
from primary_inference import coefficient_table, fit_model, tost_equivalence, wild_state_bootstrap_t  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def close(actual: float, expected: float, label: str) -> None:
    if not math.isclose(float(actual), float(expected), rel_tol=1e-9, abs_tol=1e-10):
        raise AssertionError(f"Frozen {label} differs: {actual} versus {expected}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-report", action="store_true", help="Write verification/primary_reproduction.json")
    args = parser.parse_args()
    accepted = json.loads((PROJECT / "PRIMARY_RESULTS/primary_result_manifest.json").read_text(encoding="utf-8"))
    assert sha(PROJECT / "src/run_primary_association.py") == accepted["analysis_script_sha256"]
    assert sha(PROJECT / "src/primary_inference.py") == accepted["inference_script_sha256"]
    panel_path = PROJECT / "ANALYSIS_READY_PANEL/analysis_ready_primary.parquet"
    assert sha(panel_path) == accepted["accepted_primary_panel_sha256"]
    full = pd.read_parquet(PROJECT / "ANALYSIS_READY_PANEL/analysis_ready_panel.parquet")
    primary = pd.read_parquet(panel_path)
    assert len(full) == 3000 and int(full.active_week_flag.sum()) == 1782
    assert len(primary) == accepted["accepted_primary_n"] == 1777
    assert primary.state_postal.nunique() == 17 and primary.crop_year.nunique() == 20
    assert primary.primary_complete_case_flag.all()

    # Recheck the fixed outcome-blind scaling frame using the accepted source.
    predictors = pd.read_parquet(PROJECT / "interim/gefs_5member_state_weeks.parquet")
    sunday = pd.to_datetime(predictors.archive_cycle.str[:8], format="%Y%m%d") + pd.Timedelta(days=6)
    frame = predictors.loc[sunday.dt.isocalendar().week.between(13, 26)]
    assert len(frame) == 4760
    for field, prefix in (("gefs_precip_sd5_mm", "sd5"), ("gefs_precip_mean_mm", "mean")):
        values = frame[field]
        close(values.median(), accepted["pooled_gefs_scaling"][prefix + "_median_mm"], field + " median")
        close(values.quantile(.75) - values.quantile(.25),
              accepted["pooled_gefs_scaling"][prefix + "_iqr_mm"], field + " IQR")

    fit = fit_model(primary)
    focal = coefficient_table(fit)[0]
    with (PROJECT / "PRIMARY_RESULTS/primary_coefficients.csv").open(newline="", encoding="utf-8") as stream:
        expected_focal = next(row for row in csv.DictReader(stream) if row["term"] == "dispersion_iqr")
    for key in ("coefficient", "two_way_cluster_se", "two_sided_p", "ci95_lower", "ci95_upper"):
        close(focal[key], float(expected_focal[key]), key)
    assert fit.df_two_way == int(expected_focal["two_way_cluster_df"]) == 16

    wild = wild_state_bootstrap_t(fit)
    accepted_inference = json.loads((PROJECT / "PRIMARY_RESULTS/inference_sensitivities.json").read_text(encoding="utf-8"))
    for key in ("two_sided_p", "observed_t", "observed_state_cluster_se"):
        close(wild[key], accepted_inference["wild_bootstrap_t"][key], "wild " + key)
    assert wild["draws_sha256"] == accepted_inference["wild_bootstrap_t"]["draws_sha256"]
    assert wild["replications"] == accepted["bootstrap_replications"] == 9999

    tost = tost_equivalence(fit)
    accepted_tost = json.loads((PROJECT / "PRIMARY_RESULTS/tost_equivalence.json").read_text(encoding="utf-8"))
    for key in ("ci90_lower", "ci90_upper", "tost_p", "bound_lower", "bound_upper"):
        close(tost[key], accepted_tost[key], "TOST " + key)
    assert tost["equivalent"] is accepted_tost["equivalent"] is True

    report = {
        "status": "accepted primary result reproduced from bundled panel with unchanged inference code",
        "sample": {"full": len(full), "active": int(full.active_week_flag.sum()), "primary": len(primary)},
        "predictor_scaling_frame_rows": len(frame),
        "coefficient": focal["coefficient"],
        "two_way_cluster_se": focal["two_way_cluster_se"],
        "ci95": [focal["ci95_lower"], focal["ci95_upper"]],
        "two_way_p": focal["two_sided_p"],
        "wild_bootstrap_p": wild["two_sided_p"],
        "wild_draws_sha256": wild["draws_sha256"],
        "equivalence_ci90": [tost["ci90_lower"], tost["ci90_upper"]],
        "tost_p": tost["tost_p"],
        "equivalent": tost["equivalent"],
        "not_rerun": ["source-to-panel pipeline", "five mandatory specification sensitivities", "CR2", "Conley"],
    }
    if args.write_report:
        output = HERE / "verification/primary_reproduction.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
