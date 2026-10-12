"""Freeze final P2 provenance and outcome-blind QA artifact checksums."""

import hashlib
import json
from pathlib import Path

from verify_amendments import ROOT, PRIMARY, QA, verify


FILES = (
    PRIMARY,
    PRIMARY + ".sha256",
    QA,
    QA + ".sha256",
    "provenance/project_authority_decisions.json",
    "provenance/source_manifest.csv",
    "provenance/source_manifest.sha256",
    "ANALYSIS_READY_PANEL/analysis_ready_panel.parquet",
    "ANALYSIS_READY_PANEL/analysis_ready_primary.parquet",
    "ANALYSIS_READY_PANEL/data_dictionary.csv",
    "ANALYSIS_READY_PANEL/data_dictionary.json",
    "QA/qa_metrics.json",
    "QA/OUTCOME_BLIND_QA_REPORT.md",
    "logs/panel_build_log.json",
    "logs/gefs_grib_metadata_audit.csv",
    "logs/gefs_accumulation_anomaly_inventory.csv",
    "logs/gefs_duplicate_forensic_comparison.csv",
    "logs/gefs_11_accumulation_anomaly_inventory.csv",
    "logs/gefs_11_duplicate_forensic_comparison.csv",
    "logs/gefs_11_duplicate_forensic_summary.json",
    "logs/primary_blinding_code_audit.json",
)
ALLOWED_VERDICTS = {"QA PASS — PRIMARY ASSOCIATION MAY BE OPENED",
                    "QA PASS WITH PRE-RESULT AMENDMENT REQUIRED",
                    "QA FAIL — CONTROLLER DECISION REQUIRED"}


def main():
    verify(require_qa=True)
    metrics = json.loads((ROOT / "QA" / "qa_metrics.json").read_text(encoding="utf-8"))
    if metrics["qa_verdict"] not in ALLOWED_VERDICTS:
        raise ValueError("Final outcome-blind QA verdict is not one of the frozen exact strings")
    if metrics["primary_dispersion_outcome_association_inspected"]:
        raise ValueError("Primary dispersion-outcome blinding assertion is false")
    lines = []
    for filename in FILES:
        path = ROOT / filename
        if not path.is_file():
            raise ValueError(f"Final deliverable is missing: {filename}")
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {filename}")
    target = ROOT / "provenance" / "final_deliverables.sha256"
    content = "\n".join(lines) + "\n"
    if target.exists() and target.read_text(encoding="ascii") != content:
        raise ValueError("Final deliverable hash manifest already exists with different contents")
    target.write_text(content, encoding="ascii")
    print(json.dumps({"qa_verdict": metrics["qa_verdict"],
                      "p2_hashed_artifacts": len(lines), "manifest": str(target)}, indent=2), flush=True)


if __name__ == "__main__":
    main()
