#!/usr/bin/env python3
"""Regression tests for scripts/validate_runtime_evidence.py.

Hermetic: builds a temporary manifest + evidence record + raw log and asserts the
validator's fail-closed behaviour on the numeric outcome fields (exit_code and the
failed/skipped/not_executed counters), so that a bare `status: PASS` label is never
accepted on its own.

OCOR-DEV-REM-0046 (NCP-U13, NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 3): the
fixture record is a new record, so it carries a requirement case with the
evidence-package fields of LLD v1.1 §7.3 (docs/OCOR_LLD_v1.1.md:411) and NFR-004
(Requirement Register v1.1 :26), bound to a requirement its test declares; the
negative cases of the new rules follow the original ones. REM-0046-REGRESSION-REQUALIFICATION-RECORDS
(2026-10-30, option 1): a regression-only requalification record is a declared
non-qualifying class; it gets every check that does not concern requirements and is
rejected if it binds a case to a requirement or does not supersede a record of its task.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "scripts" / "validate_runtime_evidence.py"

_TASK = "OCOR-DEV-9999"
_RAW = b"raw log output\n"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _full_command(
    *,
    exit_code: int = 0,
    failed: int = 0,
    skipped: int = 0,
    not_executed: int = 0,
    passed: int = 4,
) -> dict[str, Any]:
    return {
        "command": "pytest -q ocor-runtime/tests/tasks/test_ocor_dev_9999.py",
        "exit_code": exit_code,
        "result": {
            "failed": failed,
            "not_executed": not_executed,
            "passed": passed,
            "skipped": skipped,
        },
        "status": "PASS",
    }


_TEST_FILE = "tests/test_ocor_dev_9999.py"
_TEST_SOURCE = '''"""Fixture test module."""


def test_fixture_case():
    """Qualifies FR-062."""
    assert True
'''


def _case(**overrides: Any) -> dict[str, Any]:
    case: dict[str, Any] = {
        "requirement_id": "FR-062",
        "method": "test",
        "metric": "failed, skipped and not executed test cases",
        "threshold": "0 failed, 0 skipped, 0 not executed",
        "baseline": "fixture baseline",
        "dataset_or_scenario": "fixture scenario",
        "release_digest": "sha256:" + "0" * 64,
        "result": {"failed": 0, "not_executed": 0, "passed": 1, "skipped": 0},
        "raw_log": {"path": f"{_TASK}.log", "sha256": _sha256(_RAW)},
        "owner": "fixture owner",
        "signature": {"scheme": "fixture", "signer": "fixture signer", "value": "fixture"},
        "status": "PASS",
        "tests": [f"{_TEST_FILE}::test_fixture_case"],
    }
    case.update(overrides)
    return case


def _write_fixture(
    base: Path,
    commands: list[dict[str, Any]],
    cases: list[dict[str, Any]] | None = None,
    gate: str = "G9",
) -> None:
    (base / "tests").mkdir(exist_ok=True)
    (base / _TEST_FILE).write_text(_TEST_SOURCE, encoding="utf-8")
    record = {
        "task_id": _TASK,
        "result": "PASS",
        "commands": commands,
        "raw_output_sha256": _sha256(_RAW),
        "commit": "0" * 40,
        "environment": {"host": "test"},
        "created_at": "2026-10-02T00:00:00Z",
        "requirement_results": [_case()] if cases is None else cases,
    }
    record_bytes = json.dumps(record, indent=2, sort_keys=True).encode("utf-8")
    (base / f"{_TASK}.json").write_bytes(record_bytes)
    (base / f"{_TASK}.log").write_bytes(_RAW)
    manifest = {
        "artifacts": [
            {"path": f"{_TASK}.json", "sha256": _sha256(record_bytes), "task_id": _TASK},
            {"path": f"{_TASK}.log", "sha256": _sha256(_RAW), "task_id": f"{_TASK}-RAW"},
        ],
        "gate": gate,
        "schema_version": "1.0",
    }
    (base / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


_PREVIOUS = "evidence/OCOR-DEV-9999.previous.json"


def _write_regression_fixture(
    base: Path,
    *,
    commands: list[dict[str, Any]] | None = None,
    previous_task: str = _TASK,
    manifest_cases: list[dict[str, Any]] | None = None,
    drop: tuple[str, ...] = (),
    **overrides: Any,
) -> None:
    """A regression-only requalification record superseding an earlier record of the task."""
    previous = {"record_id": "OCOR-DEV-9999-previous", "task_id": previous_task}
    previous_bytes = json.dumps(previous, indent=2, sort_keys=True).encode("utf-8")
    (base / _PREVIOUS).parent.mkdir(parents=True, exist_ok=True)
    (base / _PREVIOUS).write_bytes(previous_bytes)
    record: dict[str, Any] = {
        "task_id": _TASK,
        "result": "PASS",
        "commands": [_full_command()] if commands is None else commands,
        "raw_output_sha256": _sha256(_RAW),
        "commit": "0" * 40,
        "environment": {"host": "test"},
        "created_at": "2026-10-30T00:00:00Z",
        "requalification_kind": "regression",
        "qualifies_requirements": False,
        "supersedes": "OCOR-DEV-9999-previous",
        "previous_record": {
            "record_id": "OCOR-DEV-9999-previous",
            "record_path": _PREVIOUS,
            "record_sha256": _sha256(previous_bytes),
        },
    }
    record.update(overrides)
    for key in drop:
        del record[key]
    record_bytes = json.dumps(record, indent=2, sort_keys=True).encode("utf-8")
    (base / f"{_TASK}.json").write_bytes(record_bytes)
    (base / f"{_TASK}.log").write_bytes(_RAW)
    manifest: dict[str, Any] = {
        "artifacts": [
            {"path": f"{_TASK}.json", "sha256": _sha256(record_bytes), "task_id": _TASK},
            {"path": f"{_TASK}.log", "sha256": _sha256(_RAW), "task_id": f"{_TASK}-RAW"},
        ],
        "gate": "G9",
        "schema_version": "1.0",
    }
    if manifest_cases is not None:
        manifest["requirement_results"] = manifest_cases
    (base / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _run_validator(base: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--task",
            _TASK,
            "--non-skipped",
            "--manifest",
            str(base / "MANIFEST.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "OCOR_EVIDENCE_ROOT": str(base)},
    )


def _assert_pass(self: unittest.TestCase, base: Path) -> None:
    result = _run_validator(base)
    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
    self.assertIn("PASS", result.stdout)


def _assert_fail(self: unittest.TestCase, base: Path, *, expected: str) -> None:
    result = _run_validator(base)
    self.assertNotEqual(0, result.returncode)
    self.assertIn("FAIL", result.stderr)
    self.assertIn(expected, result.stderr)


class RuntimeEvidenceValidatorTests(unittest.TestCase):
    def test_accepts_full_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_fixture(base, [_full_command()])
            _assert_pass(self, base)

    def test_accepts_exit_code_only_legacy_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            command = {
                "command": "sha256sum -c inputs/normative/SHA256SUMS",
                "exit_code": 0,
                "status": "PASS",
            }
            _write_fixture(base, [command])
            _assert_pass(self, base)

    def test_accepts_result_dict_only_requalified_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            command = {
                "command": "uv run pytest -q ...",
                "result": {"failed": 0, "not_executed": 0, "passed": 7, "skipped": 0},
                "status": "PASS",
            }
            _write_fixture(base, [command])
            _assert_pass(self, base)

    def test_rejects_nonzero_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_fixture(base, [_full_command(exit_code=1)])
            _assert_fail(self, base, expected="command exit_code is not a valid zero: 1")

    def test_rejects_nonzero_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_fixture(base, [_full_command(failed=1)])
            _assert_fail(self, base, expected="command result.failed is not a valid zero: 1")

    def test_rejects_nonzero_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_fixture(base, [_full_command(skipped=1)])
            _assert_fail(self, base, expected="command result.skipped is not a valid zero: 1")

    def test_rejects_nonzero_not_executed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_fixture(base, [_full_command(not_executed=1)])
            _assert_fail(self, base, expected="command result.not_executed is not a valid zero: 1")

    def test_rejects_invalid_exit_code_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            command = {
                "command": "pytest -q ...",
                "exit_code": "0",
                "result": {"failed": 0, "not_executed": 0, "passed": 4, "skipped": 0},
                "status": "PASS",
            }
            _write_fixture(base, [command])
            _assert_fail(self, base, expected="command exit_code is not a valid zero: '0'")

    def test_rejects_flat_nonzero_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            command = {
                "command": "pytest -q ...",
                "exit_code": 0,
                "failed": 1,
                "status": "PASS",
            }
            _write_fixture(base, [command])
            _assert_fail(self, base, expected="command failed is not a valid zero: 1")

    def test_rejects_bare_status_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            command = {"command": "pytest -q ...", "status": "PASS"}
            _write_fixture(base, [command])
            _assert_fail(self, base, expected="command has no numeric outcome evidence")

    def test_rejects_empty_result_dict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            command = {"command": "pytest test.py", "result": {}, "status": "PASS"}
            _write_fixture(base, [command])
            _assert_fail(self, base, expected="command has no numeric outcome evidence")

    def test_rejects_result_with_only_passed_counter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            command = {
                "command": "pytest -q ...",
                "result": {"passed": 7},
                "status": "PASS",
            }
            _write_fixture(base, [command])
            _assert_fail(self, base, expected="command has no numeric outcome evidence")

    def test_rejects_result_xfailed_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            command = {
                "command": "pytest -q ...",
                "exit_code": 0,
                "failed": 0,
                "not_executed": 0,
                "skipped": 0,
                "result": {"xfailed": 1},
                "status": "PASS",
            }
            _write_fixture(base, [command])
            _assert_fail(self, base, expected="command result.xfailed is not a valid zero: 1")

    def test_accepts_result_xfailed_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            command = {
                "command": "pytest -q ...",
                "result": {
                    "failed": 0,
                    "not_executed": 0,
                    "passed": 7,
                    "skipped": 0,
                    "xfailed": 0,
                },
                "status": "PASS",
            }
            _write_fixture(base, [command])
            _assert_pass(self, base)

    # OCOR-DEV-REM-0046: negative cases of the evidence-package rules for new records.
    def test_rejects_new_record_without_requirement_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_fixture(base, [_full_command()], cases=[])
            _assert_fail(self, base, expected="new evidence record has no requirement_results")

    def test_rejects_case_without_evidence_package_field(self) -> None:
        for field in ("method", "metric", "threshold", "baseline", "dataset_or_scenario", "release_digest", "owner", "signature", "raw_log", "result"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                case = _case()
                del case[field]
                _write_fixture(base, [_full_command()], cases=[case])
                _assert_fail(self, base, expected=f"lacks evidence-package field {field}")

    def test_rejects_requirement_outside_the_register(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_fixture(base, [_full_command()], cases=[_case(requirement_id="FR-999")])
            _assert_fail(self, base, expected="FR-999 is not in the Requirement Register v1.1")

    def test_rejects_method_other_than_the_register_method(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_fixture(base, [_full_command()], cases=[_case(method="ispezione")])
            _assert_fail(self, base, expected="is not the Register method")

    def test_rejects_incomplete_signature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_fixture(base, [_full_command()], cases=[_case(signature={"scheme": "fixture", "signer": "fixture"})])
            _assert_fail(self, base, expected="signature lacks one of scheme, signer, value")

    def test_rejects_raw_log_digest_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_fixture(base, [_full_command()], cases=[_case(raw_log={"path": f"{_TASK}.log", "sha256": "0" * 64})])
            _assert_fail(self, base, expected="raw_log digest mismatch")

    def test_rejects_failed_case_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_fixture(base, [_full_command()], cases=[_case(result={"failed": 1, "passed": 0, "skipped": 0})])
            _assert_fail(self, base, expected="result.failed is not a valid zero: 1")

    def test_rejects_requirement_not_declared_by_the_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_fixture(base, [_full_command()], cases=[_case(requirement_id="FR-064", method="fault-injection test")])
            _assert_fail(self, base, expected="FR-064 is not declared by the test")

    def test_rejects_requirement_only_traced_by_the_reverse_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            index = base / "reports/traceability/OCOR_TEST_REVERSE_TRACEABILITY_INDEX.json"
            index.parent.mkdir(parents=True)
            links = {
                "FR-064": [
                    {"kind": "task_binding", "task_id": "OCOR-DEV-0041"},
                    {"kind": "subject_task", "task_id": "OCOR-DEV-0041", "rationale": "fixture"},
                    {"kind": "remediation_record", "task_id": "OCOR-DEV-REM-0026", "source": "fixture.json"},
                ]
            }
            entry = {"basis": links, "path": _TEST_FILE, "requirement_ids": ["FR-064"]}
            index.write_text(json.dumps({"tests": [entry]}), encoding="utf-8")
            _write_fixture(base, [_full_command()], cases=[_case(requirement_id="FR-064", method="fault-injection test")])
            _assert_fail(self, base, expected="FR-064 is not declared by the test")

    def test_rejects_unresolvable_test_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_fixture(base, [_full_command()], cases=[_case(tests=[f"{_TEST_FILE}::test_missing"])])
            _assert_fail(self, base, expected="test function does not exist")

    def test_rejects_non_test_method_without_method_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "tests").mkdir()
            case = _case(requirement_id="BR-002", method="dimostrazione", tests=[])
            _write_fixture(base, [_full_command()], cases=[case])
            _assert_fail(self, base, expected="needs the evidence of its Register method")

    def test_rejects_g6_case_outside_the_poc_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            case = _case(requirement_id="NFR-001", method="test")
            _write_fixture(base, [_full_command()], cases=[case], gate="G6")
            _assert_fail(self, base, expected="NFR-001 is fuori dal profilo PoC")

    def test_rejects_g6_case_binding_a_legacy_test_to_an_lld_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            legacy = "ocor-runtime/tests/backend_assumptions/test_ba01_atomic_outbox.py"
            (base / legacy).parent.mkdir(parents=True)
            (base / legacy).write_text(_TEST_SOURCE, encoding="utf-8")
            case = _case(tests=[f"{legacy}::test_fixture_case"], ba_id="BA-01")
            _write_fixture(base, [_full_command()], cases=[case], gate="G6")
            _assert_fail(self, base, expected="binds the legacy test")

    # REM-0046-REGRESSION-REQUALIFICATION-RECORDS (2026-10-30), option 1: the regression class.
    def test_accepts_regression_requalification_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_regression_fixture(base)
            _assert_pass(self, base)

    def test_rejects_regression_record_with_a_requirement_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_regression_fixture(base, requirement_results=[_case()])
            _assert_fail(self, base, expected="regression requalification record binds a case to a requirement")

    def test_rejects_regression_record_with_a_manifest_requirement_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            row = {"case_id": "OCOR-DEV-9999-REGRESSION", "evidence_path": f"{_TASK}.json", "requirement_id": "FR-062", "status": "PASS"}
            _write_regression_fixture(base, manifest_cases=[row])
            _assert_fail(self, base, expected="regression requalification record binds a case to a requirement")

    def test_rejects_regression_record_that_qualifies_requirements(self) -> None:
        for value in (True, None, "false"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                _write_regression_fixture(base, qualifies_requirements=value)
                _assert_fail(self, base, expected="qualifies_requirements is not false")

    def test_rejects_regression_record_without_supersedes(self) -> None:
        for drop in (("supersedes",), ("previous_record",)):
            with self.subTest(drop=drop), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                _write_regression_fixture(base, drop=drop)
                _assert_fail(self, base, expected="does not supersede a record")

    def test_rejects_regression_record_superseding_another_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_regression_fixture(base, previous_task="OCOR-DEV-9998")
            _assert_fail(self, base, expected="supersedes a record of OCOR-DEV-9998")

    def test_rejects_regression_record_with_a_mismatched_superseded_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_regression_fixture(base, supersedes="OCOR-DEV-9999-other")
            _assert_fail(self, base, expected="does not supersede a record")

    def test_rejects_regression_record_failing_the_non_requirement_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_regression_fixture(base, commands=[_full_command(skipped=1)])
            _assert_fail(self, base, expected="command result.skipped is not a valid zero: 1")
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_regression_fixture(base, drop=("commit",))
            _assert_fail(self, base, expected="evidence fields missing: commit")

    def test_regression_record_never_counts_as_requirement_evidence(self) -> None:
        spec = importlib.util.spec_from_file_location("validate_runtime_evidence_fixture", VALIDATOR)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.requirement_register()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            gate = base / "reports/evidence/G5"
            gate.mkdir(parents=True)
            registry = base / "reports/traceability/OCOR_SEALED_EVIDENCE_REGISTRY.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(json.dumps({"records": []}), encoding="utf-8")
            (base / _TEST_FILE).parent.mkdir(parents=True, exist_ok=True)
            (base / _TEST_FILE).write_text(_TEST_SOURCE, encoding="utf-8")
            _write_regression_fixture(gate, requirement_results=[_case()])
            module.ROOT = base
            report = module.requirement_evidence("FR-062")
        self.assertEqual([], report["qualifying_records"])
        self.assertEqual(["reports/evidence/G5/OCOR-DEV-9999.json"], [item["path"] for item in report["rejected_records"]])
        self.assertIn("regression requalification record", report["rejected_records"][0]["reason"])


# Preventive review OCOR-DEV-REM-0046-2dae278d970d-pre: shape of the evidence-package fields,
# provenance of declarations, legacy-path normalisation and the --requirement-evidence query.
_TWO_FUNCTION_SOURCE = '''"""Fixture test module."""


def test_fixture_case():
    """Qualifies FR-062."""
    assert True


def test_other_case():
    """Qualifies FR-064."""
    assert True
'''


def _assert_typed_fail(self: unittest.TestCase, base: Path, *, expected: str) -> None:
    """Fail through the validator's FAIL outcome, never through an unhandled exception."""
    result = _run_validator(base)
    self.assertEqual(1, result.returncode, result.stdout + result.stderr)
    self.assertNotIn("Traceback", result.stderr)
    self.assertIn("FAIL", result.stderr)
    self.assertIn(expected, result.stderr)


def _rewrite_record(base: Path, mutate: Any) -> None:
    """Replace the fixture record with ``mutate(record)`` and refresh its manifest digest."""
    record = json.loads((base / f"{_TASK}.json").read_text(encoding="utf-8"))
    record_bytes = json.dumps(mutate(record), indent=2, sort_keys=True).encode("utf-8")
    (base / f"{_TASK}.json").write_bytes(record_bytes)
    manifest = json.loads((base / "MANIFEST.json").read_text(encoding="utf-8"))
    manifest["artifacts"][0]["sha256"] = _sha256(record_bytes)
    (base / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")


def _load_validator(base: Path) -> Any:
    """The validator module rooted at ``base``; the Register is read from the repository first."""
    spec = importlib.util.spec_from_file_location("validate_runtime_evidence_query", VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.requirement_register()
    registry = base / "reports/traceability/OCOR_SEALED_EVIDENCE_REGISTRY.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps({"records": []}), encoding="utf-8")
    backlog = base / "docs/development_plan/OCOR_IMPLEMENTATION_BACKLOG.json"
    backlog.parent.mkdir(parents=True, exist_ok=True)
    backlog.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    (base / _TEST_FILE).parent.mkdir(parents=True, exist_ok=True)
    (base / _TEST_FILE).write_text(_TEST_SOURCE, encoding="utf-8")
    (base / "reports/evidence/G5").mkdir(parents=True, exist_ok=True)
    module.ROOT = base
    return module


def _query_record(
    base: Path,
    name: str,
    *,
    record_id: str,
    cases: list[dict[str, Any]] | None = None,
    **overrides: Any,
) -> list[dict[str, Any]]:
    """A record of the fixture task under reports/evidence/G5 and its manifest entries."""
    gate = base / "reports/evidence/G5"
    record: dict[str, Any] = {
        "task_id": _TASK,
        "record_id": record_id,
        "result": "PASS",
        "commands": [_full_command()],
        "raw_output_sha256": _sha256(_RAW),
        "commit": "0" * 40,
        "environment": {"host": "test"},
        "created_at": "2026-10-30T00:00:00Z",
        "requirement_results": [_case(raw_log={"path": f"{name}.log", "sha256": _sha256(_RAW)})] if cases is None else cases,
    }
    record.update(overrides)
    record_bytes = json.dumps(record, indent=2, sort_keys=True).encode("utf-8")
    (gate / f"{name}.json").write_bytes(record_bytes)
    (gate / f"{name}.log").write_bytes(_RAW)
    return [
        {"path": f"{name}.json", "sha256": _sha256(record_bytes), "task_id": _TASK},
        {"path": f"{name}.log", "sha256": _sha256(_RAW), "task_id": f"{_TASK}-RAW"},
    ]


def _query_manifest(base: Path, entries: list[dict[str, Any]]) -> None:
    manifest = {"artifacts": entries, "gate": "G5", "schema_version": "1.0"}
    (base / "reports/evidence/G5/MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")


class PreventiveReviewRemediationTests(unittest.TestCase):
    # P3: a present but malformed evidence-package field is not evidence.
    def test_rejects_malformed_evidence_package_fields(self) -> None:
        malformed = {
            "requirement_id": ["FR-062"],
            "metric": False,
            "threshold": True,
            "baseline": 42,
            "dataset_or_scenario": [None],
            "release_digest": False,
            "result": True,
            "owner": ["fixture owner"],
            "raw_log": "FR-062.log",
            "signature": {"scheme": False, "signer": 17, "value": [None]},
            "status": True,
        }
        for field, value in malformed.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                _write_fixture(base, [_full_command()], cases=[_case(**{field: value})])
                _assert_typed_fail(self, base, expected="requirement_results[0]")

    def test_rejects_case_result_without_the_outcome_counters(self) -> None:
        for result in ({"passed": 1}, {"failed": 0, "passed": 1}, {"failed": 0, "skipped": 0, "not_executed": False}):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                _write_fixture(base, [_full_command()], cases=[_case(result=result)])
                _assert_typed_fail(self, base, expected="requirement_results[0] result")

    def test_rejects_release_digest_outside_the_sha256_form(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_fixture(base, [_full_command()], cases=[_case(release_digest="release 1.0")])
            _assert_typed_fail(self, base, expected="release_digest")

    def test_accepts_scenario_list_of_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_fixture(base, [_full_command()], cases=[_case(dataset_or_scenario=["scenario a", "scenario b"])])
            _assert_pass(self, base)

    # P4: every parsing path fails through the typed FAIL outcome.
    def test_rejects_malformed_case_collections(self) -> None:
        for field, value in (
            ("tests", True),
            ("tests", [None]),
            ("tests", [""]),
            ("method_evidence", True),
            ("method_evidence", [None]),
        ):
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                _write_fixture(base, [_full_command()], cases=[_case(**{field: value})])
                _assert_typed_fail(self, base, expected=f"requirement_results[0] {field}")

    def test_rejects_malformed_manifest_and_record_structures(self) -> None:
        mutations = {
            "manifest null": ("MANIFEST.json", None),
            "artifacts false": ("MANIFEST.json", {"artifacts": False, "gate": "G9"}),
            "artifacts [null]": ("MANIFEST.json", {"artifacts": [None], "gate": "G9"}),
        }
        for label, (name, content) in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                _write_fixture(base, [_full_command()])
                (base / name).write_text(json.dumps(content), encoding="utf-8")
                _assert_typed_fail(self, base, expected="manifest")
        for label, mutate, expected in (
            ("record list", lambda record: [record], "evidence record is not an object"),
            ("commands object", lambda record: {**record, "commands": {"exit_code": 0}}, "commands is not a list"),
            ("requirement_results true", lambda record: {**record, "requirement_results": True}, "requirement_results"),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                _write_fixture(base, [_full_command()])
                _rewrite_record(base, mutate)
                _assert_typed_fail(self, base, expected=expected)

    # P2: a declaration belongs to the selected test function, never to its file.
    def test_rejects_requirement_named_by_another_function_of_the_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            index = base / "reports/traceability/OCOR_TEST_REVERSE_TRACEABILITY_INDEX.json"
            index.parent.mkdir(parents=True)
            entry = {"basis": {"FR-064": [{"kind": "named_in_test"}]}, "path": _TEST_FILE, "requirement_ids": ["FR-064"]}
            index.write_text(json.dumps({"tests": [entry]}), encoding="utf-8")
            _write_fixture(base, [_full_command()], cases=[_case(requirement_id="FR-064", method="fault-injection test")])
            (base / _TEST_FILE).write_text(_TWO_FUNCTION_SOURCE, encoding="utf-8")
            _assert_typed_fail(self, base, expected="FR-064 is not declared by the test")

    def test_accepts_requirement_declared_by_the_selected_function(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            case = _case(requirement_id="FR-064", method="fault-injection test", tests=[f"{_TEST_FILE}::test_other_case"])
            _write_fixture(base, [_full_command()], cases=[case])
            (base / _TEST_FILE).write_text(_TWO_FUNCTION_SOURCE, encoding="utf-8")
            _assert_pass(self, base)

    # P6: the legacy slice is recognised on the resolved test path.
    def test_rejects_g6_legacy_binding_through_an_equivalent_path(self) -> None:
        legacy = "ocor-runtime/tests/backend_assumptions/test_ba01_atomic_outbox.py"
        for form in ("./" + legacy, "ocor-runtime/tests/../tests/backend_assumptions/test_ba01_atomic_outbox.py", "{base}/" + legacy):
            with self.subTest(form=form), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp).resolve()
                (base / legacy).parent.mkdir(parents=True)
                (base / legacy).write_text(_TEST_SOURCE, encoding="utf-8")
                reference = form.format(base=base) + "::test_fixture_case"
                _write_fixture(base, [_full_command()], cases=[_case(tests=[reference], ba_id="BA-01")], gate="G6")
                _assert_typed_fail(self, base, expected="binds the legacy test")

    def test_rejects_test_reference_outside_the_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            base = Path(tmp)
            (Path(outside) / "test_outside.py").write_text(_TEST_SOURCE, encoding="utf-8")
            for reference in (f"{outside}/test_outside.py::test_fixture_case", f"../{Path(outside).name}/test_outside.py::test_fixture_case"):
                with self.subTest(reference=reference):
                    _write_fixture(base, [_full_command()], cases=[_case(tests=[reference])])
                    _assert_typed_fail(self, base, expected="test reference does not resolve")

    # P1: the query applies the integrity and outcome checks of the task validation.
    def test_requirement_evidence_accepts_a_conforming_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            module = _load_validator(base)
            _query_manifest(base, _query_record(base, "record", record_id="R1"))
            report = module.requirement_evidence("FR-062")
        self.assertEqual(["reports/evidence/G5/record.json"], report["qualifying_records"])
        self.assertEqual([], report["rejected_records"])

    def test_requirement_evidence_applies_the_task_record_checks(self) -> None:
        variants: dict[str, Any] = {
            "record result FAIL": {"result": "FAIL"},
            "failed command": {"commands": [_full_command(exit_code=1)]},
            "skipped command": {"commands": [{**_full_command(), "status": "SKIPPED"}]},
            "no command": {"commands": []},
            "raw digest": {"raw_output_sha256": "0" * 64},
            "missing commit": {"commit": None},
        }
        for label, overrides in [*variants.items(), ("manifest digest", None), ("no raw entry", None)]:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                module = _load_validator(base)
                entries = _query_record(base, "record", record_id="R1", **(overrides or {}))
                if label == "missing commit":
                    path = base / "reports/evidence/G5/record.json"
                    record = json.loads(path.read_text(encoding="utf-8"))
                    del record["commit"]
                    data = json.dumps(record).encode("utf-8")
                    path.write_bytes(data)
                    entries[0]["sha256"] = _sha256(data)
                if label == "manifest digest":
                    entries[0]["sha256"] = "incorrect"
                if label == "no raw entry":
                    entries = entries[:1]
                _query_manifest(base, entries)
                report = module.requirement_evidence("FR-062")
                self.assertEqual([], report["qualifying_records"])
                self.assertEqual(["reports/evidence/G5/record.json"], [item["path"] for item in report["rejected_records"]])

    # P5: only the latest qualifying record of the task chain is evidence.
    def test_requirement_evidence_counts_only_the_latest_qualifying_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            module = _load_validator(base)
            entries = _query_record(base, "new", record_id="R2", supersedes="R1") + _query_record(base, "old", record_id="R1")
            _query_manifest(base, entries)
            report = module.requirement_evidence("FR-062")
        self.assertEqual(["reports/evidence/G5/new.json"], report["qualifying_records"])
        self.assertEqual(["reports/evidence/G5/old.json"], [item["path"] for item in report["rejected_records"]])
        self.assertIn("superseded", report["rejected_records"][0]["reason"])

    def test_requirement_evidence_drops_a_requirement_the_successor_leaves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            module = _load_validator(base)
            successor = [_case(requirement_id="FR-064", method="fault-injection test", raw_log={"path": "new.log", "sha256": _sha256(_RAW)})]
            entries = _query_record(base, "new", record_id="R2", supersedes="R1", cases=successor) + _query_record(base, "old", record_id="R1")
            _query_manifest(base, entries)
            report = module.requirement_evidence("FR-062")
        self.assertEqual([], report["qualifying_records"])
        self.assertEqual(["reports/evidence/G5/old.json"], [item["path"] for item in report["rejected_records"]])

    def test_requirement_evidence_keeps_the_record_through_a_regression_successor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            module = _load_validator(base)
            regression = _query_record(
                base,
                "regression",
                record_id="R2",
                cases=[],
                requalification_kind="regression",
                qualifies_requirements=False,
                supersedes="R1",
            )
            _query_manifest(base, regression + _query_record(base, "old", record_id="R1"))
            report = module.requirement_evidence("FR-062")
        self.assertEqual(["reports/evidence/G5/old.json"], report["qualifying_records"])

    def test_requirement_evidence_rejects_an_ambiguous_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            module = _load_validator(base)
            entries = _query_record(base, "first", record_id="R1") + _query_record(base, "second", record_id="R2")
            _query_manifest(base, entries)
            report = module.requirement_evidence("FR-062")
        self.assertEqual([], report["qualifying_records"])
        self.assertEqual(2, len(report["rejected_records"]))
        self.assertTrue(all("supersedes chain" in item["reason"] for item in report["rejected_records"]))


if __name__ == "__main__":
    unittest.main()
