#!/usr/bin/env python3
"""Create and validate content-addressed OCOR task evidence manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

NON_QUALIFYING = {"SKIPPED", "UNAVAILABLE", "NOT_EXECUTED", "XFAIL"}
TASK_ID = re.compile(r"OCOR-DEV-[0-9]{4}")
SHA256 = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")


class ManifestError(ValueError):
    """Raised when evidence cannot qualify for acceptance."""


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ManifestError(f"JSON root must be an object: {path}")
    return value


def _normalise_cases(cases: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not cases:
        raise ManifestError("at least one requirement-result case is required")
    normalised: list[dict[str, Any]] = []
    seen: set[str] = set()
    for case in cases:
        required = {"requirement_id", "case_id", "command", "status", "result"}
        missing = sorted(required - case.keys())
        if missing:
            raise ManifestError(f"case fields missing: {', '.join(missing)}")
        command = case["command"]
        if not isinstance(command, str) or not command.strip():
            raise ManifestError("case command must be non-empty")
        case_id = case["case_id"]
        if not isinstance(case_id, str) or not case_id.strip() or case_id in seen:
            raise ManifestError("case_id must be non-empty and unique")
        status = str(case["status"]).upper()
        if status in NON_QUALIFYING:
            raise ManifestError(f"non-qualifying result present: {status}")
        if status != "PASS":
            raise ManifestError(f"mandatory case is not PASS: {case_id}={status}")
        result = case["result"]
        if not isinstance(result, Mapping):
            raise ManifestError(f"case result must be an object: {case_id}")
        if any(int(result.get(field, 0)) for field in ("failed", "skipped", "not_executed")):
            raise ManifestError(f"mandatory case contains non-passing counts: {case_id}")
        seen.add(case_id)
        normalised.append(
            {
                "case_id": case_id,
                "command": command,
                "requirement_id": str(case["requirement_id"]),
                "result": dict(result),
                "status": status,
            }
        )
    return sorted(normalised, key=lambda item: str(item["case_id"]))


def record_task_evidence(
    *,
    manifest_path: Path,
    gate: str,
    task_id: str,
    commit: str,
    environment: Mapping[str, Any],
    inputs: Mapping[str, str],
    cases: Sequence[Mapping[str, Any]],
    raw_output: str,
    created_at: str | None = None,
) -> Path:
    """Write raw output, evidence record, requirement ledger and manifest atomically."""
    if TASK_ID.fullmatch(task_id) is None:
        raise ManifestError("task_id must match OCOR-DEV-NNNN")
    if COMMIT.fullmatch(commit) is None:
        raise ManifestError("commit must be a full lowercase Git SHA-1")
    if not raw_output:
        raise ManifestError("raw evidence output must be non-empty")
    if not environment:
        raise ManifestError("environment must be non-empty")
    if not inputs or any(SHA256.fullmatch(value) is None for value in inputs.values()):
        raise ManifestError("inputs must contain SHA-256 digests")

    normalised_cases = _normalise_cases(cases)
    timestamp = created_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    evidence_path = manifest_path.parent / f"{task_id}.json"
    raw_path = manifest_path.parent / f"{task_id}.log"
    _atomic_text(raw_path, raw_output)
    raw_digest = _digest(raw_path)
    evidence = {
        "commands": [
            {
                "command": case["command"],
                "result": case["result"],
                "status": case["status"],
            }
            for case in normalised_cases
        ],
        "commit": commit,
        "created_at": timestamp,
        "environment": dict(environment),
        "inputs": dict(inputs),
        "raw_output_sha256": raw_digest,
        "requirement_results": normalised_cases,
        "result": "PASS",
        "schema_version": "1.0",
        "task_id": task_id,
    }
    _atomic_json(evidence_path, evidence)

    manifest = _load_json(manifest_path) if manifest_path.exists() else {
        "artifacts": [],
        "created_at": timestamp,
        "gate": gate,
        "requirement_results": [],
        "schema_version": "1.0",
    }
    if manifest.get("gate") != gate:
        raise ManifestError(f"gate mismatch: {manifest.get('gate')} != {gate}")
    artifacts = [
        item
        for item in manifest.get("artifacts", [])
        if item.get("task_id") not in {task_id, f"{task_id}-RAW"}
    ]
    artifacts.extend(
        [
            {"path": evidence_path.name, "sha256": _digest(evidence_path), "task_id": task_id},
            {"path": raw_path.name, "sha256": raw_digest, "task_id": f"{task_id}-RAW"},
        ]
    )
    ledger = [
        item
        for item in manifest.get("requirement_results", [])
        if item.get("task_id") != task_id
    ]
    ledger.extend(
        {
            "case_id": case["case_id"],
            "command": case["command"],
            "evidence_path": evidence_path.name,
            "raw_output_path": raw_path.name,
            "requirement_id": case["requirement_id"],
            "status": case["status"],
            "task_id": task_id,
        }
        for case in normalised_cases
    )
    manifest["artifacts"] = sorted(artifacts, key=lambda item: str(item["task_id"]))
    manifest["requirement_results"] = sorted(
        ledger, key=lambda item: (str(item["task_id"]), str(item["case_id"]))
    )
    _atomic_json(manifest_path, manifest)
    validate_manifest(manifest_path, task_id=task_id, non_skipped=True)
    return evidence_path


REGRESSION_KIND = "regression"
QUALIFYING_FIELDS = frozenset(
    {
        "task_id", "commit", "environment", "inputs", "commands",
        "requirement_results", "raw_output_sha256", "result", "created_at",
    }
)
# REM-0046-REGRESSION-REQUALIFICATION-RECORDS (2026-10-30) point 1: a regression-only
# requalification record binds no case to a requirement.
REGRESSION_FIELDS = QUALIFYING_FIELDS - {"requirement_results"}


def _resolve_pair(
    manifest_path: Path, evidence_entry: Mapping[str, Any], raw_entry: Mapping[str, Any]
) -> tuple[Path, Path, str]:
    evidence_path = manifest_path.parent / str(evidence_entry.get("path", ""))
    raw_path = manifest_path.parent / str(raw_entry.get("path", ""))
    if not raw_path.is_file():
        raise ManifestError("raw evidence file is missing")
    if not evidence_path.is_file():
        raise ManifestError("evidence record is missing")
    if evidence_entry.get("sha256") != _digest(evidence_path):
        raise ManifestError("evidence digest mismatch")
    raw_digest = _digest(raw_path)
    if raw_entry.get("sha256") != raw_digest:
        raise ManifestError("raw evidence digest mismatch")
    return evidence_path, raw_path, raw_digest


def _validate_regression(
    manifest: Mapping[str, Any],
    record: Mapping[str, Any],
    *,
    task_id: str,
    evidence_name: str,
    raw_name: str,
    raw_digest: str,
    non_skipped: bool,
) -> None:
    """Checks of a regression-only requalification record that do not concern requirements
    (NCP-U06-0004-REGRESSION-MANIFEST-VALIDATION (2026-11-04), option 1)."""
    missing = sorted(REGRESSION_FIELDS - record.keys())
    if missing:
        raise ManifestError(f"evidence fields missing: {', '.join(missing)}")
    if record["task_id"] != task_id or COMMIT.fullmatch(str(record["commit"])) is None:
        raise ManifestError("task or commit identifier mismatch")
    if record["raw_output_sha256"] != raw_digest:
        raise ManifestError("record raw-output digest mismatch")
    if record.get("qualifies_requirements") is not False:
        raise ManifestError("regression requalification record: qualifies_requirements is not false")
    ledger = manifest.get("requirement_results", [])
    if not isinstance(ledger, list):
        raise ManifestError("manifest requirement_results must be an array")
    naming = [
        row
        for row in ledger
        if isinstance(row, Mapping)
        and (row.get("evidence_path") == evidence_name or row.get("raw_output_path") == raw_name)
    ]
    if "requirement_results" in record or naming:
        raise ManifestError("regression requalification record binds a case to a requirement")
    commands = record["commands"]
    if (
        not isinstance(commands, list)
        or not commands
        or not all(isinstance(item, Mapping) for item in commands)
    ):
        raise ManifestError("regression requalification record has no well-formed executed command")
    statuses = {str(item.get("status", "")).upper() for item in commands}
    if non_skipped and statuses & NON_QUALIFYING:
        raise ManifestError(f"non-qualifying result present: {sorted(statuses & NON_QUALIFYING)}")
    if statuses != {"PASS"} or record["result"] != "PASS":
        raise ManifestError("mandatory evidence is not all PASS")


def _superseded(
    manifest_path: Path,
    artifacts: Sequence[Any],
    record: Mapping[str, Any],
    *,
    task_id: str,
    seen: set[str],
) -> tuple[Path, Path, str, dict[str, Any]]:
    """Resolve the record a regression record supersedes: an evidence record of the same task
    in the manifest directory, listed with its raw log, with the declared digest and identifier."""
    supersedes = record.get("supersedes")
    previous = record.get("previous_record")
    if (
        not isinstance(supersedes, str)
        or not supersedes
        or not isinstance(previous, Mapping)
        or previous.get("record_id") != supersedes
    ):
        raise ManifestError("regression requalification record does not supersede a record")
    record_path = previous.get("record_path")
    location = PurePosixPath(record_path) if isinstance(record_path, str) else None
    if (
        location is None
        or location.is_absolute()
        or ".." in location.parts
        or not location.name.endswith(".json")
        or not location.parent.parts
        or manifest_path.parent.resolve().parts[-len(location.parent.parts):] != location.parent.parts
    ):
        raise ManifestError("superseded record is not an evidence record of this manifest directory")
    name = location.name
    if name in seen:
        raise ManifestError("supersedes chain is cyclic")
    seen.add(name)
    entries = [item for item in artifacts if isinstance(item, Mapping)]
    evidence_entry = next(
        (item for item in entries if item.get("task_id") == task_id and item.get("path") == name), None
    )
    if evidence_entry is None:
        raise ManifestError(f"manifest has no evidence entry for superseded record {name}")
    raw_entry = next(
        (
            item
            for item in entries
            if item.get("task_id") == f"{task_id}-RAW" and item.get("path") == name.removesuffix(".json") + ".log"
        ),
        None,
    )
    if raw_entry is None:
        raise ManifestError(f"manifest has no raw evidence entry for superseded record {name}")
    evidence_path, raw_path, raw_digest = _resolve_pair(manifest_path, evidence_entry, raw_entry)
    if previous.get("record_sha256") != _digest(evidence_path):
        raise ManifestError("superseded record digest mismatch")
    superseded = _load_json(evidence_path)
    if superseded.get("record_id") != supersedes:
        raise ManifestError("superseded record identifier mismatch")
    if superseded.get("task_id") != task_id:
        raise ManifestError("superseded record belongs to another task")
    return evidence_path, raw_path, raw_digest, superseded


def validate_manifest(manifest_path: Path, *, task_id: str, non_skipped: bool) -> bool:
    """Fail closed unless task evidence and every requirement result are reproducible.

    A first artifact with ``requalification_kind: "regression"`` receives the checks that do not
    concern requirements; the ``supersedes`` chain is then followed to the latest non-regression
    record, which receives every qualifying check, ledger included
    (NCP-U06-0004-REGRESSION-MANIFEST-VALIDATION (2026-11-04), option 1)."""
    manifest = _load_json(manifest_path)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ManifestError("manifest artifacts must be an array")
    evidence_entry = next((item for item in artifacts if item.get("task_id") == task_id), None)
    raw_entry = next((item for item in artifacts if item.get("task_id") == f"{task_id}-RAW"), None)
    if evidence_entry is None:
        raise ManifestError(f"manifest has no evidence entry for {task_id}")
    if raw_entry is None:
        raise ManifestError(f"manifest has no raw evidence entry for {task_id}")
    evidence_path, raw_path, raw_digest = _resolve_pair(manifest_path, evidence_entry, raw_entry)

    record = _load_json(evidence_path)
    seen = {evidence_path.name}
    while record.get("requalification_kind") == REGRESSION_KIND:
        _validate_regression(
            manifest,
            record,
            task_id=task_id,
            evidence_name=evidence_path.name,
            raw_name=raw_path.name,
            raw_digest=raw_digest,
            non_skipped=non_skipped,
        )
        evidence_path, raw_path, raw_digest, record = _superseded(
            manifest_path, artifacts, record, task_id=task_id, seen=seen
        )

    missing = sorted(QUALIFYING_FIELDS - record.keys())
    if missing:
        raise ManifestError(f"evidence fields missing: {', '.join(missing)}")
    if record["task_id"] != task_id or COMMIT.fullmatch(str(record["commit"])) is None:
        raise ManifestError("task or commit identifier mismatch")
    if record["raw_output_sha256"] != raw_digest:
        raise ManifestError("record raw-output digest mismatch")
    cases = _normalise_cases(record["requirement_results"])
    if not record["commands"] or len(record["commands"]) != len(cases):
        raise ManifestError("executed command/result cardinality mismatch")
    statuses = {str(item.get("status", "")).upper() for item in record["commands"]}
    if non_skipped and statuses & NON_QUALIFYING:
        raise ManifestError(f"non-qualifying result present: {sorted(statuses & NON_QUALIFYING)}")
    if statuses != {"PASS"} or record["result"] != "PASS":
        raise ManifestError("mandatory evidence is not all PASS")
    ledger_rows = [
        item for item in manifest.get("requirement_results", []) if item.get("task_id") == task_id
    ]
    if len(ledger_rows) != len(cases):
        raise ManifestError("requirement-result ledger cardinality mismatch")
    for row in ledger_rows:
        if not row.get("command") or row.get("status") != "PASS":
            raise ManifestError("requirement-result ledger contains a non-qualifying row")
        if row.get("evidence_path") != evidence_path.name or row.get("raw_output_path") != raw_path.name:
            raise ManifestError("requirement-result ledger path mismatch")
    return True


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--task", required=True)
    validate.add_argument("--non-skipped", action="store_true")
    args = parser.parse_args(argv)
    try:
        validate_manifest(args.manifest, task_id=args.task, non_skipped=args.non_skipped)
        print(f"PASS: qualifying manifest and requirement ledger for {args.task}")
        return 0
    except ManifestError as exc:
        print(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
