#!/usr/bin/env python3
"""Fail-closed tests for the execution-commit input digest check.

The tests build a temporary Git repository. They do not read sealed records
and they do not start a service.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts" / "check_execution_commit_inputs.py"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "OCOR Test",
            "GIT_AUTHOR_EMAIL": "ocor-test@example.com",
            "GIT_COMMITTER_NAME": "OCOR Test",
            "GIT_COMMITTER_EMAIL": "ocor-test@example.com",
        }
    )
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
        env=env,
    )


def _init_repo(repo: Path) -> str:
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    (repo / "inputs").mkdir()
    (repo / "inputs" / "pin.txt").write_bytes(b"pin\n")
    (repo / "module.py").write_bytes(b"alpha\n")
    _git(repo, "add", "inputs/pin.txt", "module.py")
    _git(repo, "commit", "-m", "base")
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _record(repo: Path, commit: str, inputs: dict[str, str]) -> Path:
    path = repo / "record.json"
    path.write_text(
        json.dumps(
            {"commit": commit, "inputs": inputs, "task_id": "OCOR-DEV-0005"},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _run(repo: Path, commit: str, record: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "python3",
            str(CHECKER),
            "--root",
            str(repo),
            "--execution-commit",
            commit,
            "--record",
            str(record),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


class ExecutionCommitInputTests(unittest.TestCase):
    def test_matching_blob_and_inputs_tree_pass(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            commit = _init_repo(repo)
            tree = _git(repo, "rev-parse", f"{commit}:inputs").stdout.strip()
            record = _record(
                repo,
                commit,
                {
                    "inputs_tree": tree,
                    "module.py": _sha256(b"alpha\n"),
                },
            )
            result = _run(repo, commit, record)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual("PASS", payload["status"])
            self.assertEqual(1, payload["checked_inputs"])
            self.assertEqual([], payload["findings"])

    def test_wrong_hash_fails(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            commit = _init_repo(repo)
            record = _record(repo, commit, {"module.py": _sha256(b"other\n")})
            result = _run(repo, commit, record)
            self.assertNotEqual(0, result.returncode)
            payload = json.loads(result.stdout)
            self.assertEqual("FAIL", payload["status"])
            self.assertTrue(
                any(item["reason"] == "input hash mismatch" for item in payload["findings"])
            )

    def test_change_between_commit_and_head_fails(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            commit = _init_repo(repo)
            record = _record(repo, commit, {"module.py": _sha256(b"alpha\n")})
            (repo / "module.py").write_bytes(b"beta\n")
            _git(repo, "add", "module.py")
            _git(repo, "commit", "-m", "edit")
            result = _run(repo, commit, record)
            self.assertNotEqual(0, result.returncode)
            payload = json.loads(result.stdout)
            reasons = {item["reason"] for item in payload["findings"]}
            self.assertIn("changed between the execution commit and HEAD", reasons)

    def test_working_tree_edit_fails(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            commit = _init_repo(repo)
            record = _record(repo, commit, {"module.py": _sha256(b"alpha\n")})
            (repo / "module.py").write_bytes(b"dirty\n")
            result = _run(repo, commit, record)
            self.assertNotEqual(0, result.returncode)
            payload = json.loads(result.stdout)
            reasons = {item["reason"] for item in payload["findings"]}
            self.assertIn("working tree differs from the execution commit", reasons)

    def test_declared_commit_mismatch_fails(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            commit = _init_repo(repo)
            record = _record(repo, "a" * 40, {"module.py": _sha256(b"alpha\n")})
            result = _run(repo, commit, record)
            self.assertNotEqual(0, result.returncode)
            payload = json.loads(result.stdout)
            self.assertTrue(
                any(
                    item["reason"] == "declared commit differs from the execution commit"
                    for item in payload["findings"]
                )
            )

    def test_record_without_file_inputs_checks_declared_commit(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            commit = _init_repo(repo)
            path = repo / "unit.json"
            path.write_text(
                json.dumps(
                    {
                        "execution_commit": commit,
                        "task_id": "OCOR-DEV-REM-0062",
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            result = _run(repo, commit, path)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual("PASS", payload["status"])
            self.assertEqual(0, payload["checked_inputs"])
            self.assertEqual(1, payload["checked_records"])
