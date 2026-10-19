"""PO 2026-10-15: exercise the actual inline scanner, without secret output."""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/ocor-supply-chain.yml"
REGISTRY = Path("reports/assurance/OCOR-DEV-REM-0034-RCCAD/synthetic-secret-occurrences.json")
RECORD = Path("reports/evidence/G5/OCOR-DEV-0050.requalified-rem0019-marker.json")
SEALED_COMMIT = "0addbaa99c3f13d39cb64c1e9aee73ca45eed3cd"
SOURCE_COMMIT = "6e1c4b050ac610a22673d6f559e424a01705189c"
RECORD_SHA = "0e37bcb00cd57560cb74342d00b08a04c8fda7abaac0e762a8bab688dfefdee7"


def scanner_source(workflow: str | None = None) -> str:
    doc = yaml.load(workflow or WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    step = next(x for x in doc["jobs"]["supply-chain"]["steps"] if x.get("name") == "Run pinned in-repository scanners")
    return step["run"].rstrip().removeprefix("python - <<'PY'\n").removesuffix("\nPY")


def sealed_bytes() -> bytes:
    value = subprocess.check_output(["git", "show", f"{SEALED_COMMIT}:{RECORD}"], cwd=ROOT, timeout=20)
    assert hashlib.sha256(value).hexdigest() == RECORD_SHA
    return value


def sandbox(tmp_path: Path) -> Path:
    (tmp_path / RECORD).parent.mkdir(parents=True)
    (tmp_path / RECORD).write_bytes(sealed_bytes())
    (tmp_path / REGISTRY).parent.mkdir(parents=True)
    if (ROOT / REGISTRY).exists():
        (tmp_path / REGISTRY).write_bytes((ROOT / REGISTRY).read_bytes())
    (tmp_path / "ocor-runtime").mkdir()
    (tmp_path / "ocor-runtime/uv.lock").write_text("version = 1\npackage = []\n")
    return tmp_path


def scan(root: Path, *, source: str | None = None) -> tuple[int, dict]:
    result = subprocess.run(
        [sys.executable, "-c", source or scanner_source()], cwd=root,
        env=os.environ | {"OCOR_SCAN_ROOT": str(root), "OCOR_SCAN_OUTPUT": str(root / "out"), "OCOR_SCANNER_VERSION": "1.1.0"},
        capture_output=True, timeout=30,
    )
    # No raw stdout/stderr or parametrised credential-bearing node IDs in evidence.
    report = json.loads((root / "out/secrets.json").read_text())
    return result.returncode, report


def test_authorized_sealed_occurrences_are_suspended_and_reported(tmp_path: Path) -> None:
    code, report = scan(sandbox(tmp_path))
    assert code == 0
    assert report["blocking_findings"] == 0
    assert len(report["suspended_findings"]) == 3
    assert {r["registry_entry_id"] for r in report["suspended_findings"]} == {"REM0034-140", "REM0034-141", "REM0034-175"}
    summary = json.loads((tmp_path / "out/summary.json").read_text())
    assert summary["suspended_findings"] == report["suspended_findings"]
    assert hashlib.sha256((tmp_path / RECORD).read_bytes()).hexdigest() == RECORD_SHA


@pytest.mark.parametrize("mutation", [
    "record-byte", "fourth-occurrence", "other-file", "other-field", "new-credential",
    "wrong-rule", "wrong-digest", "wrong-index", "wrong-path", "wrong-file-digest",
    "wrong-provenance", "extra-entry", "missing-entry", "extra-field", "malformed", "missing",
])
def test_every_unapproved_variation_fails_closed(tmp_path: Path, mutation: str) -> None:
    sandbox(tmp_path)
    registry = tmp_path / REGISTRY
    record = tmp_path / RECORD
    if mutation == "record-byte":
        record.write_bytes(record.read_bytes() + b" ")
    elif mutation in {"fourth-occurrence", "other-field"}:
        d = json.loads(record.read_text())
        v = d["regression_case_identity"][140]
        if mutation == "fourth-occurrence":
            d["regression_case_identity"].append(v)
        else:
            d["another_field"] = v
        record.write_text(json.dumps(d))
    elif mutation == "other-file":
        (tmp_path / "elsewhere.json").write_bytes(record.read_bytes())
    elif mutation == "new-credential":
        (tmp_path / "elsewhere.txt").write_text("ghp" + "_" + "x" * 36)
    elif mutation == "missing":
        registry.unlink(missing_ok=True)
    elif mutation == "malformed":
        registry.write_text("{invalid")
    else:
        d = json.loads(registry.read_text())
        e = d["entries"][0]
        if mutation == "wrong-rule":
            e["rule_id"] = "AWS_ACCESS_KEY"
        elif mutation == "wrong-digest":
            e["string_sha256"] = "0" * 64
        elif mutation == "wrong-index":
            e["index"] = 139
        elif mutation == "wrong-path":
            e["path"] = "another.json"
        elif mutation == "wrong-file-digest":
            e["file_sha256"] = "0" * 64
        elif mutation == "wrong-provenance":
            e["provenance"]["commit"] = "0" * 40
        elif mutation == "extra-entry":
            d["entries"].append(e.copy())
        elif mutation == "missing-entry":
            d["entries"].pop()
        elif mutation == "extra-field":
            e["extra"] = True
        registry.write_text(json.dumps(d))
    code, report = scan(tmp_path)
    assert code != 0
    assert report["result"] == "FAIL"
    assert report["blocking_findings"] > 0


def test_registry_is_required_even_when_no_secret_is_present(tmp_path: Path) -> None:
    sandbox(tmp_path)
    (tmp_path / RECORD).unlink()
    (tmp_path / REGISTRY).unlink(missing_ok=True)
    code, report = scan(tmp_path)
    assert code != 0
    assert any(f["rule_id"] == "SYNTHETIC_REGISTRY_INVALID" for f in report["findings"])


def test_valid_registry_allows_checkout_before_historical_record_is_merged(tmp_path: Path) -> None:
    sandbox(tmp_path)
    (tmp_path / RECORD).unlink()
    code, report = scan(tmp_path)
    assert code == 0
    assert report["suspended_findings"] == []


def test_original_scanner_rejects_exact_sealed_record(tmp_path: Path) -> None:
    baseline = subprocess.check_output(["git", "show", "80a97ba:.github/workflows/ocor-supply-chain.yml"], cwd=ROOT, text=True, timeout=20)
    code, report = scan(sandbox(tmp_path), source=scanner_source(baseline))
    assert code != 0
    assert report["blocking_findings"] == 3


def test_non_secret_scanners_patterns_selection_and_size_limit_are_unchanged() -> None:
    baseline = subprocess.check_output(["git", "show", "80a97ba:.github/workflows/ocor-supply-chain.yml"], cwd=ROOT, text=True, timeout=20)
    before = scanner_source(baseline)
    after = scanner_source()
    assert before[:before.index("secret_findings: list")] == after[:after.index("# This append-only authority")]
    assert before[before.index("lock_path ="):before.index('(output / "summary.json")')] == after[after.index("lock_path ="):after.index("if suspended_findings:")]
    old_doc = yaml.load(baseline, Loader=yaml.BaseLoader)
    new_doc = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
    old_job = old_doc["jobs"]["supply-chain"]
    new_job = new_doc["jobs"]["supply-chain"]
    old_job["env"]["OCOR_SCANNER_VERSION"] = new_job["env"]["OCOR_SCANNER_VERSION"]
    old_job["steps"][2]["run"] = new_job["steps"][2]["run"]
    assert old_doc == new_doc


def test_fixture_provenance_is_literal_non_operational_test_data() -> None:
    source = subprocess.check_output(["git", "show", f"{SOURCE_COMMIT}:ocor-runtime/tests/tasks/test_ocor_dev_0050.py"], cwd=ROOT, text=True, timeout=20)
    tree = ast.parse(source)
    ids = json.loads(sealed_bytes())["regression_case_identity"]
    expected = {
        140: b"".join((b"-----BEGIN RSA ", b"PRIVATE KEY-----\nMIIB")),
        141: b"".join((b"aws key AKIA", b"ABCDEFGHIJKLMNOP leaked")),
        175: b"".join((b"-----BEGIN RSA ", b"PRIVATE KEY-----\nMIIB")),
    }
    # Evaluate only literal fixture expressions and bytes.join, never test code.
    for index, value in expected.items():
        function = ids[index][1].split("[")[0]
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function)
        values = node.decorator_list[0].args[1]
        fixtures = []
        for entry in values.elts:
            expr = entry.elts[0]
            if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute) and expr.func.attr == "join":
                fixtures.append(ast.literal_eval(expr.func.value).join(ast.literal_eval(expr.args[0])))
        assert value in fixtures
        # Pytest escapes control characters in the collected parameter id.
        assert value.decode().replace("\n", "\\n") in ids[index][1]
