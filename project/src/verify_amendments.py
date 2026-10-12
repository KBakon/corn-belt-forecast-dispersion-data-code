"""Verify separate post-freeze authorities without touching the original freeze."""

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIMARY = "PRE_RESULT_AMENDMENT_2026-10-06_GEFS_EXACT_DUPLICATE_DEDUP.md"
QA = "PRE_RESULT_AMENDMENT_2026-10-07_GEFS_11MEMBER_QA_EXACT_DUPLICATE_SCOPE.md"
PRIMARY_EXPECTED_SHA256 = "9ce4ceb935114c5edb5cb0d2ead67a823a9f34f47e35db02ae43c40d4847e1c8"


def verify_file(name, expected=None):
    path = ROOT / name
    sidecar = path.with_suffix(path.suffix + ".sha256")
    if not path.is_file() or not sidecar.is_file():
        raise ValueError(f"Authorized amendment or SHA sidecar missing: {name}")
    declared = sidecar.read_text(encoding="ascii").split()[0]
    observed = hashlib.sha256(path.read_bytes()).hexdigest()
    if declared != observed or (expected is not None and observed != expected):
        raise ValueError(f"Authorized amendment hash mismatch: {name}")
    return observed


def verify(require_qa=False):
    primary_sha = verify_file(PRIMARY, PRIMARY_EXPECTED_SHA256)
    output = {"primary_amendment_sha256": primary_sha}
    if require_qa:
        qa_sha = verify_file(QA)
        summary = json.loads((ROOT / "logs" / "gefs_11_duplicate_forensic_summary.json").read_text())
        if not summary["case_a_eligible"] or summary["audited_source_objects"] != 3080:
            raise ValueError("Wednesday QA amendment lacks complete Case A source audit")
        if summary["nonidentical_duplicate_pairs"] or summary["maximum_abs_decoded_difference"] or summary["unequal_decoded_cells"]:
            raise ValueError("Wednesday QA source audit contains non-identical duplicate evidence")
        for filename, field in (("gefs_11_accumulation_anomaly_inventory.csv", "inventory_sha256"),
                                ("gefs_11_duplicate_forensic_comparison.csv", "forensic_sha256")):
            observed = hashlib.sha256((ROOT / "logs" / filename).read_bytes()).hexdigest()
            if observed != summary[field]:
                raise ValueError(f"Wednesday QA forensic evidence hash mismatch: {filename}")
        authority = json.loads((ROOT / "provenance" / "project_authority_decisions.json").read_text())
        freeze_sha = hashlib.sha256((ROOT.parent / "FREEZE_MANIFEST.sha256").read_bytes()).hexdigest()
        if freeze_sha != authority["original_freeze_manifest_sha256"] or not authority["original_freeze_manifest_unchanged"]:
            raise ValueError("Original freeze manifest differs from durable authority decision log")
        registered = {row["filename"]: row["sha256"] for row in authority["post_freeze_amendments"]}
        if registered.get(PRIMARY) != primary_sha or registered.get(QA) != qa_sha:
            raise ValueError("Post-freeze authority decision log does not match amendments")
        output["qa_amendment_sha256"] = qa_sha
        output["wednesday_source_objects_audited"] = summary["audited_source_objects"]
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-qa", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(require_qa=args.require_qa), indent=2), flush=True)


if __name__ == "__main__":
    main()
