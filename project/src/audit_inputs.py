"""Record mounted authority files without inferring missing freeze inputs."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT.parent / "artifacts"
NAMES = [
    "PROJECT_ADMISSION_PACKAGE.md",
    "CODEX_ES_IZOLALT_CHATGPT_CONTROLLER_SZABALYZAT_v3_5.md",
    "1_KUTATASI_PROJEKT_FO_MUKODESI_UTASITAS_v3_1.md",
    "PROJECT_CONTROL_STATE.md",
    "SCIENTIFIC_CONTRIBUTION_CONTRACT.md",
    "DATA_PROVENANCE.md",
    "PANEL_CONSTRUCTION_SPEC.md",
    "PRIMARY_ANALYSIS_SPEC.md",
    "OUTCOME_BLIND_QA_SPEC.md",
    "FREEZE_MANIFEST.sha256",
]
RECOVERY_HASHES = {
    "CODEX_ES_IZOLALT_CHATGPT_CONTROLLER_SZABALYZAT_v3_5.md": "6c06fcfe3e82aeb1ff35a09a14f8912ac73547b282625f44589b1f66a6080b19",
    "1_KUTATASI_PROJEKT_FO_MUKODESI_UTASITAS_v3_1.md": "860fe3031a01ce1d01c16d29d3e962766bf112ccbe1bd19d205e6ae2ac939d60",
    "FREEZE_MANIFEST.sha256": "2caad1805e7b6e1cfe9ce9c7953e0c1d46e2ac91dd2c7f630fe1ee4064673ced",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    records = []
    for name in NAMES:
        candidates = ([ROOT.parent / name, ARTIFACTS / name]
                      if name == "FREEZE_MANIFEST.sha256" else [ARTIFACTS / name])
        mounted = next((path for path in candidates if path.is_file()), candidates[0])
        observed = sha256(mounted) if mounted.is_file() else None
        records.append(
            {
                "requested_path": (
                    "/mnt/data/" + name
                    if name in NAMES[:3]
                    else "/mnt/data/corn_belt_f1_protocol1_milestone1/" + name
                ),
                "resolved_path": str(mounted) if mounted.is_file() else None,
                "checked_paths": [str(path) for path in candidates],
                "status": "present" if mounted.is_file() else "missing",
                "sha256": observed,
                "expected_sha256": RECOVERY_HASHES.get(name),
                "expected_hash_match": observed == RECOVERY_HASHES[name] if name in RECOVERY_HASHES and observed else None,
                "byte_size": mounted.stat().st_size if mounted.is_file() else None,
            }
        )
    output = {
        "audit_time_utc": datetime.now(timezone.utc).isoformat(),
        "requested_execution_root": "/mnt/data/corn_belt_f1_execution",
        "resolved_execution_root": str(ROOT),
        "requested_root_accessible": Path("/mnt/data").is_dir(),
        "inputs": records,
    }
    manifest = next(x for x in records if x["requested_path"].endswith("FREEZE_MANIFEST.sha256"))
    entry_checks = []
    if manifest["expected_hash_match"]:
        lines = Path(manifest["resolved_path"]).read_text(encoding="ascii").splitlines()
        for line in lines:
            expected, logical_path = line.split("  ", 1)
            resolved = ARTIFACTS / Path(logical_path).name
            observed = sha256(resolved) if resolved.is_file() else None
            entry_checks.append({
                "logical_path": logical_path,
                "resolved_path": str(resolved) if resolved.is_file() else None,
                "expected_sha256": expected,
                "observed_sha256": observed,
                "match": observed == expected,
            })
    output["freeze_manifest_entries"] = entry_checks
    output["freeze_manifest_entries_verified"] = len(entry_checks) == 8 and all(x["match"] for x in entry_checks)
    output["recovery_verdict"] = (
        "AUTHORITY SET VERIFIED — RESUME P1-M1"
        if all(x["status"] == "present" and x["expected_hash_match"] is not False for x in records)
        and output["freeze_manifest_entries_verified"]
        else "STOP — CONTROLLER DECISION REQUIRED"
    )
    target = ROOT / "logs" / "input_mounts.json"
    target.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"present": sum(x["status"] == "present" for x in records),
                      "missing": [x["requested_path"] for x in records if x["status"] == "missing"],
                      "output": str(target)}, indent=2))


if __name__ == "__main__":
    main()
