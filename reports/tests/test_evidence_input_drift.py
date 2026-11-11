#!/usr/bin/env python3
"""Regression tests for scripts/validate_evidence_input_drift.py.

These tests are hermetic: they build a temporary repository fixture and assert the
validator's fail-closed behaviour (PASS on matching inputs, FAIL on drift or missing
files) without depending on the drift state of the real repository.
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
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "scripts" / "validate_evidence_input_drift.py"

_TASK = "OCOR-DEV-9999"
_CONTENT = b"governed evidence input\n"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_fixture(base: Path, inputs: dict[str, str], tasks: list[str]) -> None:
    (base / "reports" / "development").mkdir(parents=True)
    (base / "reports" / "evidence" / "G9").mkdir(parents=True)
    state = {"completed_evidence_tasks": tasks}
    (base / "reports" / "development" / "EXECUTION_STATE.json").write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    record = {
        "task_id": _TASK,
        "commit": "0" * 40,
        "created_at": "2026-10-01T00:00:00Z",
        "inputs": {"inputs_tree": "0" * 40, **inputs},
    }
    (base / "reports" / "evidence" / "G9" / f"{_TASK}.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _run_validator(base: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--root", str(base)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class EvidenceInputDriftValidatorTests(unittest.TestCase):
    def test_accepts_matching_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "ocor-runtime" / "src").mkdir(parents=True)
            target = base / "ocor-runtime" / "src" / "kernel.py"
            target.write_bytes(_CONTENT)
            _build_fixture(base, {"ocor-runtime/src/kernel.py": _sha256(_CONTENT)}, [_TASK])
            result = _run_validator(base)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual("PASS", json.loads(result.stdout)["status"])

    def test_rejects_drifted_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = base / "module.py"
            target.write_bytes(b"current content")
            _build_fixture(base, {"module.py": _sha256(b"original content")}, [_TASK])
            result = _run_validator(base)
            self.assertNotEqual(0, result.returncode)
            payload = json.loads(result.stdout)
            self.assertEqual("FAIL", payload["status"])
            self.assertIn("module.py", {f["path"] for f in payload["findings"]})

    def test_rejects_missing_input_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _build_fixture(base, {"deleted.py": _sha256(_CONTENT)}, [_TASK])
            result = _run_validator(base)
            self.assertNotEqual(0, result.returncode)
            payload = json.loads(result.stdout)
            findings = payload["findings"]
            self.assertTrue(any(f["path"] == "deleted.py" and f["reason"] == "file missing at HEAD" for f in findings))

    def test_rejects_task_without_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _build_fixture(base, {}, [_TASK, "OCOR-DEV-8888"])
            result = _run_validator(base)
            self.assertNotEqual(0, result.returncode)
            payload = json.loads(result.stdout)
            self.assertTrue(any(f["task_id"] == "OCOR-DEV-8888" for f in payload["findings"]))

    def test_ignores_inputs_tree_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = base / "module.py"
            target.write_bytes(_CONTENT)
            _build_fixture(base, {"module.py": _sha256(_CONTENT)}, [_TASK])
            # Corrupt only the tree-level digest; per-file hash still matches.
            record_path = base / "reports" / "evidence" / "G9" / f"{_TASK}.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["inputs"]["inputs_tree"] = "f" * 40
            record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            result = _run_validator(base)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual("PASS", json.loads(result.stdout)["status"])

    def test_head_scan_rejects_a_non_string_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = base / "module.py"
            target.write_bytes(_CONTENT)
            _build_fixture(base, {"module.py": _sha256(_CONTENT)}, [_TASK])
            record_path = base / "reports" / "evidence" / "G9" / f"{_TASK}.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["inputs"]["module.py"] = True
            record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            result = _run_validator(base)
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual("FAIL", payload["status"])
            self.assertTrue(
                any(
                    item["path"] == "module.py" and item["reason"] == "recorded digest is not a string"
                    for item in payload["findings"]
                )
            )

    def test_head_scan_rejects_a_non_utf8_record_without_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = base / "module.py"
            target.write_bytes(_CONTENT)
            _build_fixture(base, {"module.py": _sha256(_CONTENT)}, [_TASK])
            record_path = base / "reports" / "evidence" / "G9" / f"{_TASK}.json"
            record_path.write_bytes(b"\xff\xfe")
            result = _run_validator(base)
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual("FAIL", payload["status"])
            self.assertTrue(any(item["task_id"] == _TASK for item in payload["findings"]))


def _git(base: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Drift Test",
        "GIT_AUTHOR_EMAIL": "drift@example.com",
        "GIT_COMMITTER_NAME": "Drift Test",
        "GIT_COMMITTER_EMAIL": "drift@example.com",
    }
    return subprocess.run(
        ["git", "-C", str(base), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def _commit_blob(base: Path, relative: str, content: bytes) -> str:
    _git(base, "init", "-q", "-b", "main")
    path = base / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    _git(base, "add", "--", relative)
    _git(base, "commit", "-q", "-m", "fixture", "--", relative)
    return _git(base, "rev-parse", "HEAD").stdout.strip()


def _write_execution_record(
    base: Path,
    commit: str,
    inputs: dict[str, str],
    *,
    raw: str | None = None,
    raw_bytes: bytes | None = None,
) -> Path:
    evidence = base / "reports" / "evidence" / "G9"
    evidence.mkdir(parents=True, exist_ok=True)
    record: dict[str, object] = {
        "commit": commit,
        "created_at": "2026-11-11T00:00:00Z",
        "inputs": {"inputs_tree": "a" * 40, **inputs},
        "task_id": _TASK,
    }
    if raw is not None:
        record["raw_output_sha256"] = raw
    path = evidence / f"{_TASK}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if raw_bytes is not None:
        path.with_suffix(".log").write_bytes(raw_bytes)
    return path


def _run_execution_commit(base: Path, record: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--root",
            str(base),
            "--execution-commit",
            "--record",
            str(record),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class ExecutionCommitDigestTests(unittest.TestCase):
    def test_accepts_git_show_bytes_when_the_working_tree_differs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            revision = _commit_blob(base, "module.py", _CONTENT)
            (base / "module.py").write_bytes(b"working tree differs\n")
            record = _write_execution_record(base, revision, {"module.py": _sha256(_CONTENT)})
            result = _run_execution_commit(base, record)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual("PASS", json.loads(result.stdout)["status"])

    def test_rejects_a_hash_that_does_not_match_git_show(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            revision = _commit_blob(base, "module.py", _CONTENT)
            record = _write_execution_record(base, revision, {"module.py": _sha256(b"other\n")})
            result = _run_execution_commit(base, record)
            self.assertNotEqual(0, result.returncode)
            payload = json.loads(result.stdout)
            self.assertEqual("FAIL", payload["status"])
            self.assertTrue(
                any(item["path"] == "module.py" and item["reason"] == "input hash mismatch" for item in payload["findings"])
            )

    def test_rejects_a_path_absent_from_the_execution_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            revision = _commit_blob(base, "module.py", _CONTENT)
            record = _write_execution_record(base, revision, {"missing.py": _sha256(_CONTENT)})
            result = _run_execution_commit(base, record)
            self.assertNotEqual(0, result.returncode)
            payload = json.loads(result.stdout)
            self.assertTrue(
                any(item["path"] == "missing.py" and item["reason"] == "file missing at execution commit" for item in payload["findings"])
            )

    def test_rejects_a_raw_log_that_does_not_match_the_preserved_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            revision = _commit_blob(base, "module.py", _CONTENT)
            record = _write_execution_record(
                base,
                revision,
                {"module.py": _sha256(_CONTENT)},
                raw=_sha256(b"expected log\n"),
                raw_bytes=b"different log\n",
            )
            result = _run_execution_commit(base, record)
            self.assertNotEqual(0, result.returncode)
            payload = json.loads(result.stdout)
            self.assertTrue(any(item["reason"] == "raw log hash mismatch" for item in payload["findings"]))

    def test_rejects_a_commit_that_is_not_a_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            record = _write_execution_record(base, "not-a-revision", {"module.py": _sha256(_CONTENT)})
            result = _run_execution_commit(base, record)
            self.assertNotEqual(0, result.returncode)
            payload = json.loads(result.stdout)
            self.assertTrue(
                any(item["reason"] == "execution commit is not a 40-character revision" for item in payload["findings"])
            )

    def test_fails_closed_when_no_record_is_listed(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), "--root", str(ROOT), "--execution-commit"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("FAIL", json.loads(result.stdout)["status"])

    def test_rejects_non_string_input_digests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            record = {
                "commit": "0" * 40,
                "created_at": "2026-11-12T00:00:00Z",
                "inputs": {
                    "bool.py": True,
                    "float.py": 1.0,
                    "inputs_tree": None,
                    "int.py": 123,
                    "list.py": ["abc"],
                    "none.py": None,
                    "object.py": {"sha256": "x"},
                },
                "task_id": _TASK,
            }
            path = _write_object_record(base, record)
            result = _run_execution_commit(base, path)
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual("FAIL", payload["status"])
            reasons = {(item["path"], item["reason"]) for item in payload["findings"]}
            for name in ("inputs_tree", "none.py", "int.py", "float.py", "bool.py", "object.py", "list.py"):
                self.assertIn((name, "recorded digest is not a string"), reasons)
            self.assertFalse(any(item["reason"] == "input hash mismatch" for item in payload["findings"]))

    def test_rejects_a_record_that_is_not_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            evidence = base / "reports" / "evidence" / "G9"
            evidence.mkdir(parents=True)
            path = evidence / f"{_TASK}.json"
            path.write_bytes(b"\xff\xfe")
            result = _run_execution_commit(base, path)
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual("FAIL", payload["status"])
            self.assertTrue(
                any(
                    "record unreadable" in item["reason"] and "UnicodeDecodeError" in item["reason"]
                    for item in payload["findings"]
                )
            )

    def test_rejects_nan_and_infinities_before_use(self) -> None:
        for literal in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(literal=literal):
                with tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    evidence = base / "reports" / "evidence" / "G9"
                    evidence.mkdir(parents=True)
                    path = evidence / f"{_TASK}.json"
                    path.write_text(
                        '{"commit": "' + ("0" * 40) + '", "inputs": {"nan.py": ' + literal + '}, "task_id": "' + _TASK + '"}',
                        encoding="utf-8",
                    )
                    result = _run_execution_commit(base, path)
                    self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    payload = json.loads(result.stdout)
                    self.assertEqual("FAIL", payload["status"])
                    self.assertTrue(
                        any("record unreadable" in item["reason"] and "JSONDecodeError" in item["reason"] for item in payload["findings"])
                    )

    def test_rejects_a_lone_surrogate_in_a_key_and_in_a_nested_value(self) -> None:
        lone = json.loads('"\\uD800"')
        cases = (
            {"commit": "0" * 40, "inputs": {"module.py": "a" * 64}, "note": {"inner": lone}, "task_id": _TASK},
            {"commit": "0" * 40, "inputs": {lone: "a" * 64}, "task_id": _TASK},
        )
        for record in cases:
            with self.subTest(record=sorted(record)):
                with tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    path = _write_object_record(base, record)
                    result = _run_execution_commit(base, path)
                    self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                    payload = json.loads(result.stdout)
                    self.assertEqual("FAIL", payload["status"])
                    self.assertTrue(any("lone surrogate" in item["reason"] for item in payload["findings"]))
                    self.assertFalse(any(item["reason"] == "input hash mismatch" for item in payload["findings"]))

    def test_accepts_a_valid_surrogate_pair_in_an_unused_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            revision = _commit_blob(base, "module.py", _CONTENT)
            path = _write_execution_record(base, revision, {"module.py": _sha256(_CONTENT)})
            record = json.loads(path.read_text(encoding="utf-8"))
            record["note"] = json.loads('"\\uD83D\\uDE00"')
            path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            result = _run_execution_commit(base, path)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual("PASS", json.loads(result.stdout)["status"])

    def test_rejects_digest_text_that_is_empty_non_ascii_or_the_wrong_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            record = {
                "commit": "0" * 40,
                "created_at": "2026-11-12T00:00:00Z",
                "inputs": {
                    "empty.py": "",
                    "inputs_tree": "a" * 40,
                    "nonascii.py": "é" + ("a" * 63),
                    "short.py": "abc",
                    "upper.py": "A" * 64,
                },
                "task_id": _TASK,
            }
            path = _write_object_record(base, record)
            result = _run_execution_commit(base, path)
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual("FAIL", payload["status"])
            reasons = {(item["path"], item["reason"]) for item in payload["findings"]}
            expected = "recorded digest is not a lowercase sha256 hex digest"
            for name in ("empty.py", "nonascii.py", "short.py", "upper.py"):
                self.assertIn((name, expected), reasons)
            self.assertNotIn(("inputs_tree", expected), reasons)
            self.assertFalse(any(item["reason"] == "input hash mismatch" for item in payload["findings"]))

    def test_rejects_raw_output_digests_that_are_not_sha256_text(self) -> None:
        non_strings = (None, True, 1, 1.0, {"sha256": "x"}, ["x"])
        for raw in (*non_strings, "", "not-a-digest", "É" + ("a" * 63)):
            with self.subTest(raw=raw):
                with tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    revision = _commit_blob(base, "module.py", _CONTENT)
                    path = _write_execution_record(base, revision, {"module.py": _sha256(_CONTENT)})
                    record = json.loads(path.read_text(encoding="utf-8"))
                    record["raw_output_sha256"] = raw
                    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                    result = _run_execution_commit(base, path)
                    self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                    payload = json.loads(result.stdout)
                    self.assertEqual("FAIL", payload["status"])
                    if isinstance(raw, str):
                        reason = "raw output digest is not a lowercase sha256 hex digest"
                    else:
                        reason = "raw output digest is not a string"
                    self.assertTrue(any(item["reason"] == reason for item in payload["findings"]))

    def test_git_invocation_errors_are_findings(self) -> None:
        module = _validator_module()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            path = _write_execution_record(base, "0" * 40, {"module.py": _sha256(_CONTENT)})
            with mock.patch.object(module.subprocess, "run", side_effect=OSError("git missing")):
                findings = module.execution_commit_findings(base, path)
            self.assertTrue(
                any(item["reason"].startswith("execution commit unreadable: OSError:") for item in findings)
            )


def _write_object_record(base: Path, record: dict[str, object]) -> Path:
    evidence = base / "reports" / "evidence" / "G9"
    evidence.mkdir(parents=True, exist_ok=True)
    path = evidence / f"{_TASK}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _validator_module() -> object:
    spec = importlib.util.spec_from_file_location("rem0061_evidence_input_drift", VALIDATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("validator module is not loadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
