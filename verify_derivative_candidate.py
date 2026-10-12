"""Verify immutable release files, exact runtime exceptions, and frozen panel identity."""
from hashlib import sha256
from pathlib import Path, PurePosixPath
import importlib.util
import json
import marshal
import re
import types

ROOT = Path(__file__).resolve().parent
RUNTIME = {
    "project/src/__pycache__/primary_inference.cpython-311.pyc": "project/src/primary_inference.py",
    "project/tests/__pycache__/test_primary_inference.cpython-311.pyc": "project/tests/test_primary_inference.py",
}
REPORT = "verification/primary_reproduction.json"

def digest(path):
    h = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def main():
    manifest = ROOT / "FILES.sha256"
    assert manifest.is_file(), "Missing release manifest"
    expected = {}
    for line in manifest.read_text(encoding="ascii").splitlines():
        h, rel = line.split("  ", 1)
        p = PurePosixPath(rel)
        assert re.fullmatch(r"[0-9a-f]{64}", h) and p.as_posix() == rel and not p.is_absolute() and ".." not in p.parts and "\\" not in rel, f"Unsafe entry: {rel}"
        assert rel not in expected and rel not in RUNTIME and rel != REPORT, f"Duplicate/runtime entry: {rel}"
        expected[rel] = h
    assert expected, "Empty manifest"
    actual = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file() and p != manifest}
    extras = actual - set(expected)
    assert extras <= set(RUNTIME) | {REPORT}, f"Unexpected files: {sorted(extras)}"
    assert set(expected) - actual == set(), f"Missing files: {sorted(set(expected)-actual)}"
    for rel, h in expected.items():
        assert digest(ROOT / rel) == h, f"Hash mismatch: {rel}"
    for rel in extras & set(RUNTIME):
        src = ROOT / RUNTIME[rel]
        payload = (ROOT / rel).read_bytes()
        assert len(payload) >= 17 and payload[:4] == importlib.util.MAGIC_NUMBER, f"Invalid bytecode: {rel}"
        assert int.from_bytes(payload[4:8], "little") == 0, f"Unexpected bytecode mode: {rel}"
        assert int.from_bytes(payload[8:12], "little") == int(src.stat().st_mtime), f"Stale bytecode: {rel}"
        assert int.from_bytes(payload[12:16], "little") == src.stat().st_size, f"Bytecode size mismatch: {rel}"
        compiled = compile(src.read_bytes(), str(src), "exec", dont_inherit=True)
        assert isinstance(marshal.loads(payload[16:]), types.CodeType) and payload[16:] == marshal.dumps(compiled), f"Bytecode differs from source: {rel}"
    if REPORT in extras:
        report = json.loads((ROOT / REPORT).read_text(encoding="utf-8"))
        assert report.get("status") == "accepted primary result reproduced from bundled panel with unchanged inference code", "Generated reproduction report is not a PASS"
    primary = "project/ANALYSIS_READY_PANEL/analysis_ready_primary.parquet"
    frozen = "bc20339686b6ccc819e022d8b3b827bf02bc8ce27e38a1099e515c64ae2b0896"
    assert expected[primary] == frozen and digest(ROOT / primary) == frozen, "Frozen primary panel differs"
    print(f"PASS {len(expected)} immutable files; frozen primary panel SHA matched; runtime files: {sorted(extras)}")

if __name__ == "__main__":
    main()
