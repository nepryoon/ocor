#!/usr/bin/env python3
"""Regression tests for scripts/validate_evidence_input_drift.py.

These tests are hermetic: they build a temporary repository fixture and assert the
validator's fail-closed behaviour (PASS on matching inputs, FAIL on drift or missing
files) without depending on the drift state of the real repository.
"""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
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


def _supersession_successor(previous: dict[str, object], inputs: dict[str, str]) -> dict[str, object]:
    return {
        **previous,
        "created_at": "2026-02-01T00:00:00Z",
        "inputs": inputs,
        "record_id": "latest",
        "supersedes": "previous",
    }


def _write_supersession_chain(base: Path, successor: bytes) -> None:
    evidence = base / "reports" / "evidence" / "G0"
    evidence.mkdir(parents=True)
    (base / "reports" / "development").mkdir(parents=True)
    (base / "reports" / "development" / "EXECUTION_STATE.json").write_text(
        json.dumps({"completed_evidence_tasks": ["OCOR-DEV-0005"]}) + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(b"current input\n").hexdigest()
    (base / "module.py").write_bytes(b"current input\n")
    previous = {
        "created_at": "2026-01-01T00:00:00Z",
        "inputs": {"module.py": digest},
        "record_id": "previous",
        "task_id": "OCOR-DEV-0005",
    }
    previous_bytes = json.dumps(previous).encode()
    (evidence / "previous.json").write_bytes(previous_bytes)
    (evidence / "latest.json").write_bytes(successor)
    manifest = {
        "artifacts": [
            {
                "path": "latest.json",
                "sha256": hashlib.sha256(successor).hexdigest(),
                "task_id": "OCOR-DEV-0005",
            },
            {
                "path": "previous.json",
                "sha256": hashlib.sha256(previous_bytes).hexdigest(),
                "task_id": "OCOR-DEV-0005",
            },
        ],
        "gate": "G0",
    }
    (evidence / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")


class CanonicalSupersessionDecodeTests(unittest.TestCase):
    def _previous(self) -> dict[str, object]:
        return {
            "created_at": "2026-01-01T00:00:00Z",
            "inputs": {"module.py": hashlib.sha256(b"current input\n").hexdigest()},
            "record_id": "previous",
            "task_id": "OCOR-DEV-0005",
        }

    def test_a_readable_successor_with_a_bad_hash_stays_a_mismatch(self) -> None:
        current = _supersession_successor(self._previous(), {"module.py": "0" * 64})
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_supersession_chain(base, json.dumps(current).encode())
            result = _run_validator(base)
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual("FAIL", payload["status"])
            self.assertTrue(
                any(item["reason"] == "input hash mismatch" and item["path"] == "module.py" for item in payload["findings"])
            )

    def test_a_readable_matching_successor_passes(self) -> None:
        digest = hashlib.sha256(b"current input\n").hexdigest()
        current = _supersession_successor(self._previous(), {"module.py": digest})
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_supersession_chain(base, json.dumps(current).encode())
            result = _run_validator(base)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual("PASS", json.loads(result.stdout)["status"])

    def _assert_unreadable_successor(self, successor: bytes, marker: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_supersession_chain(base, successor)
            result = _run_validator(base)
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual("FAIL", payload["status"])
            self.assertTrue(
                any(
                    item.get("task_id") == "OCOR-DEV-0005"
                    and item.get("path") == "latest.json"
                    and marker in item["reason"]
                    for item in payload["findings"]
                ),
                payload,
            )
            self.assertFalse(any(item.get("reason") == "input hash mismatch" for item in payload["findings"]))

    def test_a_non_utf8_successor_is_not_replaced_by_its_predecessor(self) -> None:
        current = _supersession_successor(self._previous(), {"module.py": "0" * 64})
        self._assert_unreadable_successor(json.dumps(current).encode() + b"\xff", "UnicodeDecodeError")

    def test_a_non_finite_successor_is_not_replaced_by_its_predecessor(self) -> None:
        current = _supersession_successor(self._previous(), {"module.py": "0" * 64})
        current["unused"] = float("nan")
        self._assert_unreadable_successor(json.dumps(current).encode(), "JSONDecodeError")

    def test_a_lone_surrogate_successor_is_not_replaced_by_its_predecessor(self) -> None:
        current = _supersession_successor(self._previous(), {"module.py": "0" * 64})
        current["unused"] = "\ud800"
        self._assert_unreadable_successor(json.dumps(current).encode(), "lone surrogate")

    def _assert_listed_successor_fails(self, successor: bytes | None, reason: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            payload = b"{}" if successor is None else successor
            _write_supersession_chain(base, payload)
            if successor is None:
                (base / "reports" / "evidence" / "G0" / "latest.json").unlink()
            result = _run_validator(base)
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            decoded = json.loads(result.stdout)
            self.assertEqual("FAIL", decoded["status"])
            self.assertTrue(
                any(
                    item.get("task_id") == "OCOR-DEV-0005" and reason in str(item.get("reason"))
                    for item in decoded["findings"]
                ),
                decoded,
            )
            self.assertFalse(any(item.get("reason") == "input hash mismatch" for item in decoded["findings"]))

    def test_a_missing_listed_successor_is_not_replaced_by_its_predecessor(self) -> None:
        self._assert_listed_successor_fails(None, "record missing")

    def test_an_empty_object_successor_is_not_replaced_by_its_predecessor(self) -> None:
        self._assert_listed_successor_fails(b"{}", "record task_id is not a non-empty string")

    def test_a_null_or_non_string_task_id_is_not_replaced_by_its_predecessor(self) -> None:
        for task_id in (None, 5, True):
            with self.subTest(task_id=task_id):
                current = _supersession_successor(self._previous(), {"module.py": "0" * 64})
                current["task_id"] = task_id
                self._assert_listed_successor_fails(
                    json.dumps(current).encode(),
                    "record task_id is not a non-empty string",
                )

    def test_a_manifest_whose_artifacts_are_not_a_list_fails_closed(self) -> None:
        current = _supersession_successor(self._previous(), {"module.py": "0" * 64})
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_supersession_chain(base, json.dumps(current).encode() + b"\xff")
            manifest_path = base / "reports" / "evidence" / "G0" / "MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"] = None
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = _run_validator(base)
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            decoded = json.loads(result.stdout)
            self.assertEqual("FAIL", decoded["status"])
            self.assertTrue(
                any(item.get("reason") == "manifest artifacts is not a list" for item in decoded["findings"]),
                decoded,
            )

    def test_an_empty_or_missing_inputs_successor_does_not_pass(self) -> None:
        cases = (
            ("inputs is empty", {"inputs": {}}),
            ("inputs is missing", {}),
        )
        for reason, override in cases:
            with self.subTest(reason=reason):
                current = _supersession_successor(self._previous(), {"module.py": "0" * 64})
                current.pop("inputs")
                current.update(override)
                self._assert_listed_successor_fails(json.dumps(current).encode(), reason)

    def test_a_sole_record_without_inputs_stays_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "reports" / "development").mkdir(parents=True)
            evidence = base / "reports" / "evidence" / "G0"
            evidence.mkdir(parents=True)
            (base / "reports" / "development" / "EXECUTION_STATE.json").write_text(
                json.dumps({"completed_evidence_tasks": ["OCOR-DEV-0001"]}) + "\n",
                encoding="utf-8",
            )
            record = {
                "created_at": "2026-01-01T00:00:00Z",
                "record_id": "only",
                "task_id": "OCOR-DEV-0001",
            }
            body = json.dumps(record).encode()
            (evidence / "OCOR-DEV-0001.json").write_bytes(body)
            manifest = {
                "artifacts": [
                    {
                        "path": "OCOR-DEV-0001.json",
                        "sha256": hashlib.sha256(body).hexdigest(),
                        "task_id": "OCOR-DEV-0001",
                    }
                ],
                "gate": "G0",
            }
            (evidence / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
            result = _run_validator(base)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual("PASS", json.loads(result.stdout)["status"])


def _apply_successor_perturbation(name: str, successor: dict[str, object], context: dict[str, object]) -> None:
    """Mutate one listed successor. Broken supersession also drops created_at.

    A later created_at would still select the successor. The class that passes
    on the predecessor is the one where ordering cannot rescue a broken link.
    """
    task_id = str(successor["task_id"])
    if name == "task_id_one_character":
        successor["task_id"] = task_id[:-1] + ("6" if task_id[-1] != "6" else "7")
    elif name == "supersedes_absent":
        successor.pop("supersedes", None)
        successor.pop("created_at", None)
    elif name == "supersedes_empty":
        successor["supersedes"] = ""
        successor.pop("created_at", None)
    elif name == "supersedes_not_listed":
        successor["supersedes"] = "not-a-listed-record"
        successor.pop("created_at", None)
    elif name == "inputs_not_per_file":
        successor["inputs"] = {"inputs_tree": "0" * 40}
    elif name == "inputs_absent":
        successor.pop("inputs", None)
    elif name == "manifest_not_canonical":
        context["manifest_path"] = "./latest.json"
    elif name == "manifest_not_object":
        context["manifest_entry"] = "latest.json"
    elif name == "record_absent":
        context["drop"] = True
    elif name == "record_unreadable":
        context["corrupt"] = True
    else:
        raise AssertionError(name)


_SUCCESSOR_PERTURBATIONS = (
    "task_id_one_character",
    "supersedes_absent",
    "supersedes_empty",
    "supersedes_not_listed",
    "inputs_not_per_file",
    "inputs_absent",
    "manifest_not_canonical",
    "manifest_not_object",
    "record_absent",
    "record_unreadable",
)


class ListedSuccessorClassTests(unittest.TestCase):
    """A listed successor is validated in full, or the manifest task fails.

    The predecessor must not be a PASS stand-in. Perturbations and their
    pairwise combinations are generated here, not listed by hand.
    """

    def _assert_not_predecessor_pass(self, names: tuple[str, ...], *, good_hash: bool = False) -> None:
        digest = hashlib.sha256(b"current input\n").hexdigest()
        bad = "0" * 64
        successor = _supersession_successor(
            {
                "created_at": "2026-01-01T00:00:00Z",
                "inputs": {"module.py": digest},
                "record_id": "previous",
                "task_id": "OCOR-DEV-0005",
            },
            {"module.py": digest if good_hash else bad},
        )
        context: dict[str, object] = {}
        for name in names:
            _apply_successor_perturbation(name, successor, context)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            body = json.dumps(successor).encode()
            if context.get("corrupt") is True:
                body += b"\xff"
            _write_supersession_chain(base, body)
            evidence = base / "reports" / "evidence" / "G0"
            if context.get("drop") is True:
                (evidence / "latest.json").unlink()
            manifest_path = evidence / "MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if "manifest_entry" in context:
                manifest["artifacts"][0] = context["manifest_entry"]
            elif "manifest_path" in context:
                manifest["artifacts"][0]["path"] = context["manifest_path"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = _run_validator(base)
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("FAIL", payload["status"], payload)
        self.assertTrue(payload["findings"], payload)
        self.assertTrue(
            any(item.get("task_id") in {"", "OCOR-DEV-0005"} for item in payload["findings"]),
            payload,
        )

    def test_a_matching_listed_successor_still_passes(self) -> None:
        digest = hashlib.sha256(b"current input\n").hexdigest()
        current = _supersession_successor(
            {
                "created_at": "2026-01-01T00:00:00Z",
                "inputs": {"module.py": digest},
                "record_id": "previous",
                "task_id": "OCOR-DEV-0005",
            },
            {"module.py": digest},
        )
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_supersession_chain(base, json.dumps(current).encode())
            result = _run_validator(base)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("PASS", json.loads(result.stdout)["status"])

    def test_each_listed_successor_perturbation_and_each_pair_refuses_the_predecessor(self) -> None:
        names = _SUCCESSOR_PERTURBATIONS
        cases = [(name,) for name in names]
        cases.extend(itertools.combinations(names, 2))
        for case in cases:
            with self.subTest(case=case):
                self._assert_not_predecessor_pass(case)

    def test_task_id_space_case_and_a_matching_hash_do_not_pass_on_the_predecessor(self) -> None:
        digest = hashlib.sha256(b"current input\n").hexdigest()
        for label, task_id, good_hash in (
            ("trailing-space", "OCOR-DEV-0005 ", False),
            ("lowercase", "ocor-dev-0005", False),
            ("other-task-matching-hash", "OCOR-DEV-0099", True),
        ):
            with self.subTest(label=label):
                successor = _supersession_successor(
                    {
                        "created_at": "2026-01-01T00:00:00Z",
                        "inputs": {"module.py": digest},
                        "record_id": "previous",
                        "task_id": "OCOR-DEV-0005",
                    },
                    {"module.py": digest if good_hash else "0" * 64},
                )
                successor["task_id"] = task_id
                with tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    _write_supersession_chain(base, json.dumps(successor).encode())
                    result = _run_validator(base)
                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual("FAIL", payload["status"], payload)
                self.assertTrue(
                    any(
                        item.get("task_id") == "OCOR-DEV-0005"
                        and "task_id" in str(item.get("reason"))
                        for item in payload["findings"]
                    ),
                    payload,
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
