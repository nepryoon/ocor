#!/usr/bin/env python3
"""Fail-closed validator: evidence input hashes must match the current HEAD.

For each task in ``completed_evidence_tasks`` (``reports/development/EXECUTION_STATE.json``)
the per-file ``inputs`` hashes of its most recent evidence record must equal the
SHA-256 of the referenced files at the checked-out HEAD. Any drift — a recorded
hash that no longer matches the file, or a referenced file that no longer exists —
is a blocking finding: a sealed evidence record whose inputs no longer describe the
code it was produced from is no longer a faithful witness.

This validator never modifies a record and never converts a mismatch into PASS.

``--execution-commit`` checks named records against ``git show <commit>:<path>``
of the commit the record declares, and checks a preserved raw log against
``raw_output_sha256``. A digest that is not a lowercase SHA-256 hex string, a
non-finite JSON number, a lone surrogate, or a record that is not strict UTF-8
is a finding before any comparison. It does not replace the HEAD scan above.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")

# Directories under reports/evidence that hold non-qualifying or historical records;
# they are not the canonical evidence for a completed task.
_EXCLUDED_PARTS = {"blockers", "local-gates"}


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reject_non_finite(token: str) -> float:
    raise json.JSONDecodeError(f"non-finite number {token}", token, 0)


def _lone_surrogate(value: object) -> bool:
    if isinstance(value, str):
        return any(0xD800 <= ord(character) <= 0xDFFF for character in value)
    if isinstance(value, dict):
        return any(_lone_surrogate(key) or _lone_surrogate(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_lone_surrogate(item) for item in value)
    return False


def _read_json_object(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Return a JSON object, or an error that names the decode failure."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    try:
        data = json.loads(text, parse_constant=_reject_non_finite)
    except json.JSONDecodeError as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if not isinstance(data, dict):
        return None, f"{type(data).__name__} is not an object"
    if _lone_surrogate(data):
        return None, "lone surrogate in record JSON"
    return data, None


def _task_id(record: dict[str, Any]) -> str:
    task_id = record.get("task_id", "")
    return task_id if isinstance(task_id, str) else ""


def _shape_findings(task_id: str, path_str: object, recorded: object) -> list[dict[str, Any]]:
    """Refuse one inputs entry before it is compared. Empty means it may be compared."""
    if not isinstance(path_str, str) or (path_str != "inputs_tree" and not _relative_input_path(path_str)):
        shown = path_str if isinstance(path_str, str) else None
        return [{
            "path": shown,
            "reason": "input path is not a relative repository path",
            "task_id": task_id,
        }]
    if not isinstance(recorded, str):
        return [{
            "path": path_str,
            "reason": "recorded digest is not a string",
            "task_id": task_id,
        }]
    if path_str == "inputs_tree":
        return []
    if not _SHA256_HEX.fullmatch(recorded):
        return [{
            "path": path_str,
            "reason": "recorded digest is not a lowercase sha256 hex digest",
            "recorded_sha256": recorded,
            "task_id": task_id,
        }]
    return []


def _raw_findings(task_id: str, record: dict[str, Any], record_path: Path) -> list[dict[str, Any]]:
    if "raw_output_sha256" not in record:
        return []
    raw = record.get("raw_output_sha256")
    log_name = record_path.with_suffix(".log").name
    if not isinstance(raw, str):
        return [{"path": log_name, "reason": "raw output digest is not a string", "task_id": task_id}]
    if not _SHA256_HEX.fullmatch(raw):
        return [{
            "path": log_name,
            "reason": "raw output digest is not a lowercase sha256 hex digest",
            "recorded_sha256": raw,
            "task_id": task_id,
        }]
    log_path = record_path.with_suffix(".log")
    if not log_path.is_file():
        return [{"path": log_name, "reason": "raw log missing", "task_id": task_id}]
    actual = sha256_of(log_path)
    if actual != raw:
        return [{
            "file_sha256": actual,
            "path": log_name,
            "reason": "raw log hash mismatch",
            "recorded_sha256": raw,
            "task_id": task_id,
        }]
    return []


def discover_records(evidence_dir: Path) -> dict[str, list[Path]]:
    """Index every canonical evidence record by ``task_id``."""
    records: dict[str, list[Path]] = {}
    for path in sorted(evidence_dir.rglob("*.json")):
        if path.name == "MANIFEST.json":
            continue
        if _EXCLUDED_PARTS & set(path.parts):
            continue
        data, error = _read_json_object(path)
        if error is not None or data is None:
            continue
        task_id = data.get("task_id")
        if isinstance(task_id, str) and task_id:
            records.setdefault(task_id, []).append(path)
    return records


def select_most_recent(paths: Sequence[Path]) -> Path:
    """Return the most recent (non-superseded) record for a task.

    With a single record it is returned as-is. When R3(b) introduces
    re-qualification records, a record whose ``supersedes`` field references the
    identifier of another record supersedes it; the most recent record is the one
    that is not referenced by any ``supersedes`` value. Records lacking an explicit
    identifier fall back to their path so the selection stays deterministic.
    """
    if len(paths) == 1:
        return paths[0]
    entries: list[tuple[str, dict[str, Any], Path]] = []
    for path in paths:
        data, error = _read_json_object(path)
        if error is not None or data is None:
            data = {}
        ident = data.get("record_id") or data.get("commit") or str(path)
        entries.append((str(ident), data, path))
    superseded = {
        str(data.get("supersedes"))
        for _, data, _ in entries
        if isinstance(data.get("supersedes"), str)
    }
    current = [entry for entry in entries if entry[0] not in superseded]
    if not current:
        raise ValueError("no non-superseded evidence record remains")
    current.sort(key=lambda entry: str(entry[1].get("created_at", "")))
    return current[-1][2]


def drift_for_record(root: Path, record_path: Path) -> list[dict[str, Any]]:
    """Return drift findings for the ``inputs`` hashes of one evidence record."""
    record, error = _read_json_object(record_path)
    if error is not None or record is None:
        return [{"path": record_path.name, "reason": f"record unreadable: {error}", "task_id": ""}]
    task_id = _task_id(record)
    findings: list[dict[str, Any]] = []
    inputs = record.get("inputs", {})
    if not isinstance(inputs, dict):
        return [{"path": "inputs", "reason": "inputs is not an object", "task_id": task_id}]
    for path_str, recorded in inputs.items():
        shape = _shape_findings(task_id, path_str, recorded)
        if shape:
            findings.extend(shape)
            continue
        if path_str == "inputs_tree":
            # Tree-level digest, not a per-file hash; per-file hashes are checked below.
            continue
        file_path = root / str(path_str)
        if not file_path.is_file():
            findings.append(
                {
                    "task_id": task_id,
                    "path": path_str,
                    "recorded_sha256": recorded,
                    "head_sha256": None,
                    "reason": "file missing at HEAD",
                }
            )
            continue
        head_hash = sha256_of(file_path)
        if head_hash != recorded:
            findings.append(
                {
                    "task_id": task_id,
                    "path": path_str,
                    "recorded_sha256": recorded,
                    "head_sha256": head_hash,
                    "reason": "input hash mismatch",
                }
            )
    return findings


def _relative_input_path(path_str: str) -> bool:
    if not path_str or not path_str.isascii() or path_str.startswith(("/", "-")) or "\\" in path_str or "\n" in path_str:
        return False
    return all(part not in ("", ".", "..") for part in path_str.split("/"))


def execution_commit_findings(root: Path, record_path: Path) -> list[dict[str, Any]]:
    """Compare declared input digests with ``git show`` of the record's commit."""
    record, error = _read_json_object(record_path)
    if error is not None or record is None:
        return [{"path": record_path.name, "reason": f"record unreadable: {error}", "task_id": ""}]
    task_id = _task_id(record)
    commit = record.get("commit")
    if not isinstance(commit, str) or not _REVISION.fullmatch(commit):
        return [{
            "path": None,
            "reason": "execution commit is not a 40-character revision",
            "task_id": task_id,
        }]
    inputs = record.get("inputs", {})
    findings: list[dict[str, Any]] = []
    if not isinstance(inputs, dict):
        findings.append({"path": "inputs", "reason": "inputs is not an object", "task_id": task_id})
    else:
        for path_str, recorded in inputs.items():
            shape = _shape_findings(task_id, path_str, recorded)
            if shape:
                findings.extend(shape)
                continue
            if path_str == "inputs_tree":
                continue
            try:
                shown = subprocess.run(
                    ["git", "-C", str(root), "show", f"{commit}:{path_str}"],
                    capture_output=True,
                    check=False,
                )
            except OSError as exc:
                findings.append({
                    "path": path_str,
                    "reason": f"execution commit unreadable: {type(exc).__name__}: {exc}",
                    "recorded_sha256": recorded,
                    "task_id": task_id,
                })
                continue
            if shown.returncode != 0:
                findings.append({
                    "execution_commit": commit,
                    "path": path_str,
                    "reason": "file missing at execution commit",
                    "recorded_sha256": recorded,
                    "task_id": task_id,
                })
                continue
            digest = hashlib.sha256(shown.stdout).hexdigest()
            if digest != recorded:
                findings.append({
                    "execution_commit": commit,
                    "execution_sha256": digest,
                    "path": path_str,
                    "reason": "input hash mismatch",
                    "recorded_sha256": recorded,
                    "task_id": task_id,
                })
    findings.extend(_raw_findings(task_id, record, record_path))
    return findings


def _execution_commit_report(root: Path, records: Sequence[Path]) -> int:
    if not records:
        print(json.dumps({"error": "no records", "findings": [], "status": "FAIL"}, indent=2, sort_keys=True))
        return 1
    findings: list[dict[str, Any]] = []
    for record in records:
        path = record if record.is_absolute() else root / record
        findings.extend(execution_commit_findings(root, path))
    payload = {
        "checked_records": len(records),
        "findings": findings,
        "status": "PASS" if not findings else "FAIL",
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not findings else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root used to resolve input paths (default: repo root)",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=None,
        help="EXECUTION_STATE.json path (default: <root>/reports/development/EXECUTION_STATE.json)",
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=None,
        help="evidence directory (default: <root>/reports/evidence)",
    )
    parser.add_argument(
        "--execution-commit",
        action="store_true",
        help="check --record inputs against git show of each record's declared commit",
    )
    parser.add_argument(
        "--record",
        action="append",
        default=[],
        type=Path,
        help="evidence or requalification record to check with --execution-commit",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.execution_commit:
        return _execution_commit_report(root, args.record)
    state_path = args.state or root / "reports/development/EXECUTION_STATE.json"
    evidence_dir = args.evidence_dir or root / "reports/evidence"

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": f"cannot read state: {exc}"}, indent=2, sort_keys=True))
        return 1

    completed = state.get("completed_evidence_tasks", [])
    records = discover_records(evidence_dir)

    findings: list[dict[str, Any]] = []
    checked_tasks = 0
    checked_inputs = 0
    missing_record_tasks: list[str] = []
    for task_id in sorted(set(completed)):
        if task_id not in records:
            missing_record_tasks.append(task_id)
            continue
        record_path = select_most_recent(records[task_id])
        record, error = _read_json_object(record_path)
        if error is not None or record is None:
            findings.append({
                "path": record_path.name,
                "reason": f"record unreadable: {error}",
                "task_id": task_id,
            })
            continue
        inputs = record.get("inputs", {})
        if isinstance(inputs, dict):
            checked_inputs += sum(
                1 for key, value in inputs.items() if key != "inputs_tree" and isinstance(value, str)
            )
        findings.extend(drift_for_record(root, record_path))
        checked_tasks += 1

    for task_id in missing_record_tasks:
        findings.append({"task_id": task_id, "path": None, "reason": "no evidence record found"})

    drifted_tasks = sorted({str(f["task_id"]) for f in findings})
    payload = {
        "status": "PASS" if not findings else "FAIL",
        "checked_tasks": checked_tasks,
        "checked_inputs": checked_inputs,
        "drifted_inputs": len(findings),
        "drifted_tasks": drifted_tasks,
        "findings": findings,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
