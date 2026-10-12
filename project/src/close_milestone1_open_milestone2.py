"""Record the Controller's P1-M1 adjudication before opening the primary result."""

import hashlib
import json
from pathlib import Path

import pandas as pd

from verify_amendments import ROOT, verify


VERDICT = "QA PASS — PRIMARY ASSOCIATION MAY BE OPENED"
ADJUDICATION = ROOT / "provenance" / "P1_M1_CONTROLLER_ADJUDICATION_2026-10-07.md"
CONTROL_STATE = ROOT / "PROJECT_CONTROL_STATE.md"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_once(path, content):
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise ValueError(f"Durable P1-M2 authority differs; refusing overwrite: {path}")
    else:
        path.write_text(content, encoding="utf-8")
    sidecar = path.with_suffix(path.suffix + ".sha256")
    digest = sha256(path)
    expected = f"{digest}  {path.name}\n"
    if sidecar.exists():
        if sidecar.read_text(encoding="ascii") != expected:
            raise ValueError(f"Durable authority hash sidecar mismatch: {sidecar}")
    else:
        sidecar.write_text(expected, encoding="ascii")
    return digest


def main():
    mounts = json.loads((ROOT / "logs" / "input_mounts.json").read_text(encoding="utf-8"))
    if mounts["recovery_verdict"] != "AUTHORITY SET VERIFIED — RESUME P1-M1":
        raise ValueError("Original freeze authority is not verified")
    if len(mounts["freeze_manifest_entries"]) != 8 or not all(
        row["match"] for row in mounts["freeze_manifest_entries"]
    ):
        raise ValueError("All eight original frozen artifacts must match")
    amendments = verify(require_qa=True)
    qa = json.loads((ROOT / "QA" / "qa_metrics.json").read_text(encoding="utf-8"))
    if set(qa["blocks"]) != set("ABCDEFGH") or qa["hard_failures"]:
        raise ValueError("Outcome-blind QA A–H is incomplete or failed")
    if qa["primary_dispersion_outcome_association_inspected"]:
        raise ValueError("Primary-result blinding was broken before QA closure")
    panel = ROOT / "ANALYSIS_READY_PANEL" / "analysis_ready_primary.parquet"
    if qa["primary_complete_case_rows"] != 1777 or len(pd.read_parquet(panel)) != 1777:
        raise ValueError("Accepted frozen primary sample N differs from 1,777")
    final_manifest = ROOT / "provenance" / "final_deliverables.sha256"
    for line in final_manifest.read_text(encoding="ascii").splitlines():
        expected, filename = line.split("  ", 1)
        if sha256(ROOT / filename) != expected:
            raise ValueError(f"Milestone 1 final artifact hash mismatch: {filename}")
    freeze_manifest = ROOT.parent / "FREEZE_MANIFEST.sha256"
    content = f"""# P1-M1 Controller adjudication — 2026-10-07

**Controller verdict:** {VERDICT}

Milestone 1 outcome-blind QA blocks A–H completed with no remaining hard QA failure. The Controller accepts both previously authorized GEFS exact-semantic-duplicate pre-result amendments as valid P2 methodology authority:

- `PRE_RESULT_AMENDMENT_2026-10-06_GEFS_EXACT_DUPLICATE_DEDUP.md` — SHA-256 `{amendments['primary_amendment_sha256']}`.
- `PRE_RESULT_AMENDMENT_2026-10-07_GEFS_11MEMBER_QA_EXACT_DUPLICATE_SCOPE.md` — SHA-256 `{amendments['qa_amendment_sha256']}`.

The frozen primary complete-case sample contains **1,777 state-weeks**. Primary-result blinding remained intact through QA closure; no GEFS-dispersion–planting-outcome association was inspected before this adjudication. The original freeze manifest (SHA-256 `{sha256(freeze_manifest)}`) and all eight frozen artifacts remain unchanged and verified. The accepted primary panel SHA-256 is `{sha256(panel)}`; the accepted P1-M1 final deliverables manifest SHA-256 is `{sha256(final_manifest)}`.

**Milestone 1 status:** COMPLETE. **Primary association opening:** AUTHORIZED. **Active work package:** P1-M2 — PRIMARY ASSOCIATION OPENING. The frozen original authority files are not rewritten. P1-M2 analysis must follow the frozen primary specification and stop after the primary result package.
"""
    adjudication_sha = write_once(ADJUDICATION, content)
    state = f"""# Project control state — P1-M2

**Lifecycle:** Protocol 1 research development  
**Milestone 1:** COMPLETE  
**Primary association opening:** AUTHORIZED  
**Active work package:** P1-M2 — PRIMARY ASSOCIATION OPENING  
**Controller verdict:** {VERDICT}

The authoritative frozen project files remain in `C:\\Research\\corn_belt\\artifacts`. This execution-state update records the Controller's 2026-10-07 adjudication at `provenance/P1_M1_CONTROLLER_ADJUDICATION_2026-10-07.md` (SHA-256 `{adjudication_sha}`). Both accepted post-freeze GEFS amendments are verified before analysis. The accepted primary complete-case sample is N = 1,777.
"""
    state_sha = write_once(CONTROL_STATE, state)
    print(json.dumps({"controller_verdict": VERDICT, "primary_n": 1777,
                      "adjudication_sha256": adjudication_sha,
                      "control_state_sha256": state_sha}, indent=2))


if __name__ == "__main__":
    main()
