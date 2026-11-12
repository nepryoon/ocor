#!/usr/bin/env python3
"""Fail-closed check of evidence inputs at a declared execution commit.

For each record, every file digest under ``inputs`` must equal the SHA-256 of
``git show <execution-commit>:<path>``. ``inputs_tree`` is the Git tree id from
``git rev-parse <execution-commit>:inputs``, not a file digest. Each of those
paths must be unchanged between that commit and HEAD, and the working tree
bytes must still match the execution commit. A record without file inputs is
checked through ``commit`` or ``execution_commit`` only.

The checker never rewrites a record and never turns a mismatch into PASS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def _git(root: Path, args: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
    )


def _rev_parse(root: Path, spec: str) -> str | None:
    proc = _git(root, ["rev-parse", "--verify", spec])
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8").strip()


def _blob(root: Path, commit: str, path: str) -> bytes | None:
    proc = _git(root, ["show", f"{commit}:{path}"])
    if proc.returncode != 0:
        return None
    return proc.stdout


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _finding(record: Path, reason: str, **extra: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"path": str(record), "reason": reason}
    item.update(extra)
    return item


def check_records(
    root: Path,
    execution_commit: str,
    record_paths: Sequence[Path],
) -> dict[str, Any]:
    """Return the canonical check payload. Callers print it and map status to an exit code."""
    resolved = _rev_parse(root, f"{execution_commit}^{{commit}}")
    head = _rev_parse(root, "HEAD")
    findings: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    checked_inputs = 0
    if resolved is None or head is None:
        findings.append(
            {
                "path": None,
                "reason": "execution commit or HEAD does not resolve",
                "execution_commit": execution_commit,
                "head": head,
            }
        )
        return _payload(execution_commit, head, findings, records, checked_inputs)

    for record_path in record_paths:
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            findings.append(_finding(record_path, "record unreadable", detail=str(exc)))
            continue
        if not isinstance(record, dict):
            findings.append(_finding(record_path, "record is not a JSON object"))
            continue
        declared = record.get("commit") or record.get("execution_commit")
        if declared != resolved:
            findings.append(
                _finding(
                    record_path,
                    "declared commit differs from the execution commit",
                    declared_commit=declared,
                )
            )
        inputs = record.get("inputs")
        file_inputs = 0
        if inputs is None:
            records.append(
                {
                    "declared_commit": declared,
                    "inputs_checked": 0,
                    "path": str(record_path),
                }
            )
            continue
        if not isinstance(inputs, dict):
            findings.append(_finding(record_path, "inputs is not an object"))
            records.append(
                {
                    "declared_commit": declared,
                    "inputs_checked": 0,
                    "path": str(record_path),
                }
            )
            continue
        for path in sorted(inputs):
            recorded = inputs[path]
            if not isinstance(recorded, str):
                findings.append(
                    _finding(record_path, "recorded input is not a string", input_path=path)
                )
                continue
            if path == "inputs_tree":
                commit_tree = _rev_parse(root, f"{resolved}:inputs")
                head_tree = _rev_parse(root, "HEAD:inputs")
                if commit_tree != recorded:
                    findings.append(
                        _finding(
                            record_path,
                            "inputs_tree mismatch",
                            input_path=path,
                            recorded=recorded,
                            execution_tree=commit_tree,
                        )
                    )
                if head_tree != commit_tree:
                    findings.append(
                        _finding(
                            record_path,
                            "inputs_tree changed between the execution commit and HEAD",
                            input_path=path,
                        )
                    )
                continue
            blob = _blob(root, resolved, path)
            if blob is None:
                findings.append(
                    _finding(record_path, "blob missing at the execution commit", input_path=path)
                )
                continue
            file_inputs += 1
            checked_inputs += 1
            digest = _sha256(blob)
            if digest != recorded:
                findings.append(
                    _finding(
                        record_path,
                        "input hash mismatch",
                        input_path=path,
                        recorded_sha256=recorded,
                        execution_sha256=digest,
                    )
                )
            head_blob = _blob(root, "HEAD", path)
            if head_blob != blob:
                findings.append(
                    _finding(
                        record_path,
                        "changed between the execution commit and HEAD",
                        input_path=path,
                    )
                )
            worktree = root / path
            if not worktree.is_file() or worktree.read_bytes() != blob:
                findings.append(
                    _finding(
                        record_path,
                        "working tree differs from the execution commit",
                        input_path=path,
                    )
                )
        records.append(
            {
                "declared_commit": declared,
                "inputs_checked": file_inputs,
                "path": str(record_path),
            }
        )
    return _payload(resolved, head, findings, records, checked_inputs)


def _payload(
    execution_commit: str | None,
    head: str | None,
    findings: list[dict[str, Any]],
    records: list[dict[str, Any]],
    checked_inputs: int,
) -> dict[str, Any]:
    return {
        "checked_inputs": checked_inputs,
        "checked_records": len(records),
        "execution_commit": execution_commit,
        "findings": findings,
        "head": head,
        "records": records,
        "status": "PASS" if not findings else "FAIL",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--execution-commit", required=True)
    parser.add_argument("--record", type=Path, action="append", required=True)
    args = parser.parse_args(argv)
    payload = check_records(args.root.resolve(), args.execution_commit, args.record)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
