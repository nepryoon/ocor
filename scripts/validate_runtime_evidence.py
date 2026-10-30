#!/usr/bin/env python3
"""Validate task evidence without converting absent or skipped work into PASS."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
from collections.abc import Sequence
from functools import cache
from pathlib import Path
from typing import Any

NON_QUALIFYING = {"SKIPPED", "UNAVAILABLE", "NOT_EXECUTED", "XFAIL"}
RESULT_COUNTERS = ("failed", "skipped", "not_executed", "xfailed")

ROOT = Path(__file__).resolve().parents[1]
REGISTER_V11 = "ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md"
BACKLOG = "docs/development_plan/OCOR_IMPLEMENTATION_BACKLOG.json"
# Evidence records sealed before OCOR-DEV-REM-0046, recognised by path and sha256
# (NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 3); every other record is new.
SEALED_REGISTRY = "reports/traceability/OCOR_SEALED_EVIDENCE_REGISTRY.json"
REVERSE_INDEX = "reports/traceability/OCOR_TEST_REVERSE_TRACEABILITY_INDEX.json"
# Per-case evidence-package fields: LLD v1.1 §7.3 (docs/OCOR_LLD_v1.1.md:411) and
# NFR-004 (Register v1.1 :26); raw_log carries the NFR-004 "evidence".
EVIDENCE_PACKAGE_FIELDS = (
    "requirement_id",
    "method",
    "metric",
    "threshold",
    "baseline",
    "dataset_or_scenario",
    "release_digest",
    "result",
    "raw_log",
    "owner",
    "signature",
)
SIGNATURE_FIELDS = ("scheme", "signer", "value")
LEGACY_TEST_DIRS = ("ocor-runtime/tests/acceptance_ev/", "ocor-runtime/tests/backend_assumptions/")
# LLD v1.1 transition, backend-assumption and Decision Register evidence identifiers
# (NCR-LEGACY-001, option A): a G6 case never binds a legacy test to them.
LLD_IDENTIFIER = re.compile(r"\b(?:ACT-T\d+[a-z]?|BA-0\d|EV-\d{3})\b")
OUT_OF_PROFILE = "fuori dal profilo PoC"
# REM-0046-REGRESSION-REQUALIFICATION-RECORDS (2026-10-30), option 1: a regression-only
# requalification is a declared non-qualifying class of record.
REGRESSION_KIND = "regression"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_zero_int(value: object, path: str) -> None:
    """Fail closed on a missing, non-integer or non-zero outcome field."""
    if type(value) is not int or value != 0:
        raise ValueError(f"{path} is not a valid zero: {value!r}")


def _validate_command(command: dict[str, object]) -> None:
    """Fail closed unless a command carries concrete numeric success evidence.

    The `status` label and the top-level `result` string are not trusted on their
    own: a command must back its PASS claim with either an integer exit_code of 0
    or a result/counters object carrying at least one failure counter, every one
    of which must be 0. An empty result object, or one holding only non-failure
    fields (e.g. just ``passed``), is not sufficient evidence.
    """
    exit_code = command.get("exit_code")
    result = command.get("result")
    if result is not None and not isinstance(result, dict):
        raise ValueError(f"command result is not an object: {result!r}")
    has_result_counters = isinstance(result, dict) and any(
        key in result for key in RESULT_COUNTERS
    )
    has_flat_counters = any(key in command for key in RESULT_COUNTERS)
    if exit_code is None and not has_result_counters and not has_flat_counters:
        raise ValueError(
            "command has no numeric outcome evidence "
            "(integer exit_code 0 or result/counters with a failure counter)"
        )
    if exit_code is not None:
        _require_zero_int(exit_code, "command exit_code")
    if isinstance(result, dict):
        for key in RESULT_COUNTERS:
            if key in result:
                _require_zero_int(result[key], f"command result.{key}")
    for key in RESULT_COUNTERS:
        if key in command:
            _require_zero_int(command[key], f"command {key}")


@cache
def requirement_register() -> dict[str, dict[str, Any]]:
    """Requirement Register v1.1 rows parsed by header name (header = row before a separator)."""
    lines = (ROOT / REGISTER_V11).read_text(encoding="utf-8").splitlines()
    out: dict[str, dict[str, Any]] = {}
    header: list[str] | None = None
    for index, line in enumerate(lines):
        if not line.startswith("|"):
            header = None
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if index + 1 < len(lines) and re.fullmatch(r"\|[\s\-:|]+\|?", lines[index + 1].strip()):
            header = cells
            continue
        rid = cells[0].strip("`")
        if header is None or not re.fullmatch(r"(BR|FR|NFR)-[0-9]{3}", rid):
            continue
        if len(cells) != len(header) or rid in out:
            raise ValueError(f"Requirement Register row cannot be parsed: {rid}")
        row = dict(zip(header, cells))
        values = {key: next(v for k, v in row.items() if k.startswith(key)) for key in ("Priorit", "Metodo", "Release")}
        out[rid] = {
            "line": index + 1,
            "priority": values["Priorit"],
            "method": values["Metodo"],
            "release": values["Release"],
        }
    if len(out) != 285:
        raise ValueError(f"Requirement Register has {len(out)} requirements, expected 285")
    return out


def in_poc_profile(requirement_id: str) -> bool:
    """NORMATIVE-CONFORMANCE-PLAN point 3: in the PoC profile when the Register release includes the PoC."""
    return "PoC" in requirement_register()[requirement_id]["release"]


def method_kind(method: str) -> str:
    """NCP-S08: inspection, demonstration, benchmark or audit is not proven by an automated test case."""
    lowered = method.lower()
    has_test = bool(re.search(r"test|replay|fault|injection", lowered))
    has_other = bool(
        re.search(
            r"ispezion|inspection|dimostraz|demonstrat|benchmark|audit|analisi|review|tabletop|drill|scan|game day",
            lowered,
        )
    )
    if has_test and has_other:
        return "MIXED"
    return "AUTOMATED_TEST" if has_test else "NON_TEST_METHOD"


@cache
def sealed_registry() -> dict[str, dict[str, Any]]:
    data = json.loads((ROOT / SEALED_REGISTRY).read_text(encoding="utf-8"))
    return {entry["path"]: entry for entry in data["records"]}


def is_sealed_legacy_record(path: Path) -> bool:
    """A record sealed before the evidence-package rules, recognised by path and sha256."""
    try:
        relative = path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return False
    entry = sealed_registry().get(relative)
    return entry is not None and entry.get("sha256") == digest(path)


def _empty(value: object) -> bool:
    return value is None or (isinstance(value, (str, list, dict)) and not value)


def _declared_requirements(root: Path, reference: str) -> set[str]:
    """Requirement identifiers a test declares: in its own source (decorators, docstring,
    body), in its module docstring, or for its file in the reverse traceability index with
    basis ``named_in_test``. Traceability links of the index (task_binding,
    remediation_record, subject_task) are never a declaration by the test."""
    path_text, _, function = reference.partition("::")
    function = function.split("[", 1)[0].split("::")[-1]
    path = root / path_text
    if not function or not path.is_file():
        raise ValueError(f"test reference does not resolve: {reference}")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function
    ]
    if not nodes:
        raise ValueError(f"test function does not exist: {reference}")
    text = " ".join(ast.get_source_segment(source, node, padded=False) or "" for node in nodes)
    for node in nodes:
        text += " " + " ".join(ast.unparse(decorator) for decorator in node.decorator_list)
    text += " " + (ast.get_docstring(tree) or "")
    declared = set(re.findall(r"\b(?:BR|FR|NFR)-\d{3}\b", text))
    index_path = root / REVERSE_INDEX
    if index_path.is_file():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        for entry in index.get("tests", []):
            if entry.get("path") == path_text:
                declared.update(
                    requirement
                    for requirement, links in (entry.get("basis") or {}).items()
                    if any(isinstance(link, dict) and link.get("kind") == "named_in_test" for link in links)
                )
    return declared


def _check_artifact(base: Path, item: object, label: str) -> None:
    if not isinstance(item, dict) or _empty(item.get("path")) or _empty(item.get("sha256")):
        raise ValueError(f"{label} is not a {{path, sha256}} reference: {item!r}")
    target = base / str(item["path"])
    if not target.is_file() or digest(target) != item["sha256"]:
        raise ValueError(f"{label} digest mismatch or missing file: {item['path']}")


def is_regression_record(record: dict[str, Any]) -> bool:
    return record.get("requalification_kind") == REGRESSION_KIND


def check_regression_record(record: dict[str, Any], manifest: dict[str, Any], evidence_name: str, root: Path) -> None:
    """REM-0046-REGRESSION-REQUALIFICATION-RECORDS point 1: a regression-only requalification
    record binds no case to a requirement and supersedes an earlier record of its own task;
    the checks that do not concern requirements are applied by the caller."""
    if record.get("qualifies_requirements") is not False:
        raise ValueError("regression requalification record: qualifies_requirements is not false")
    manifest_cases = [
        row
        for row in manifest.get("requirement_results", [])
        if isinstance(row, dict) and row.get("evidence_path") == evidence_name
    ]
    if not _empty(record.get("requirement_results")) or manifest_cases:
        raise ValueError("regression requalification record binds a case to a requirement")
    supersedes = record.get("supersedes")
    previous = record.get("previous_record")
    if _empty(supersedes) or not isinstance(previous, dict) or previous.get("record_id") != supersedes:
        raise ValueError("regression requalification record does not supersede a record")
    target = root / str(previous.get("record_path") or "")
    if not target.is_file() or digest(target) != previous.get("record_sha256"):
        raise ValueError("regression requalification record does not supersede a record: superseded record missing or digest mismatch")
    superseded = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(superseded, dict) or superseded.get("record_id") != supersedes:
        raise ValueError("regression requalification record does not supersede a record: record_id mismatch")
    if superseded.get("task_id") != record.get("task_id"):
        raise ValueError(f"regression requalification record supersedes a record of {superseded.get('task_id')}")


def check_new_record(record: dict[str, Any], gate: str | None, evidence_dir: Path, root: Path) -> None:
    """Evidence-package rules for a record that is not a sealed legacy record (NFR-003,
    NFR-004, LLD v1.1 §7.3 and §8, NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 3)."""
    cases = record.get("requirement_results")
    if not isinstance(cases, list) or not cases:
        raise ValueError("new evidence record has no requirement_results (NFR-003, NFR-004)")
    register = requirement_register()
    backlog = {task["id"]: task for task in json.loads((ROOT / BACKLOG).read_text(encoding="utf-8"))["tasks"]}
    task = backlog.get(str(record.get("task_id")))
    for number, case in enumerate(cases):
        label = f"requirement_results[{number}]"
        if not isinstance(case, dict):
            raise ValueError(f"{label} is not an object")
        for field in EVIDENCE_PACKAGE_FIELDS:
            if _empty(case.get(field)):
                raise ValueError(f"{label} lacks evidence-package field {field} (NFR-004, LLD v1.1 §7.3)")
        requirement = str(case["requirement_id"])
        if requirement not in register:
            raise ValueError(f"{label} requirement {requirement} is not in the Requirement Register v1.1")
        if gate == "G6" and not in_poc_profile(requirement):
            raise ValueError(f"{label} requirement {requirement} is {OUT_OF_PROFILE}: not qualified by a G6 campaign")
        if task is not None and requirement not in task["requirement_ids"]:
            raise ValueError(f"{label} requirement {requirement} is not a requirement of {task['id']}")
        method = register[requirement]["method"]
        if case["method"] != method:
            raise ValueError(f"{label} method {case['method']!r} is not the Register method {method!r} (NCP-S08)")
        signature = case["signature"]
        if not isinstance(signature, dict) or any(_empty(signature.get(key)) for key in SIGNATURE_FIELDS):
            raise ValueError(f"{label} signature lacks one of {', '.join(SIGNATURE_FIELDS)}")
        _check_artifact(evidence_dir, case["raw_log"], f"{label} raw_log")
        result = case["result"]
        if isinstance(result, dict):
            for key in RESULT_COUNTERS:
                if key in result:
                    _require_zero_int(result[key], f"{label} result.{key}")
        if str(case.get("status", "")).upper() != "PASS":
            raise ValueError(f"{label} status is not PASS")
        kind = method_kind(method)
        tests = case.get("tests") or []
        evidence = case.get("method_evidence") or []
        for reference in tests:
            if requirement not in _declared_requirements(root, str(reference)):
                raise ValueError(f"{label} requirement {requirement} is not declared by the test {reference}")
        if kind in ("AUTOMATED_TEST", "MIXED") and not tests:
            raise ValueError(f"{label} requirement {requirement} has a test method and no tests")
        if kind in ("NON_TEST_METHOD", "MIXED") and not evidence:
            raise ValueError(f"{label} requirement {requirement} needs the evidence of its Register method {method!r}")
        for item in evidence:
            _check_artifact(root, item, f"{label} method_evidence")
        if gate == "G6":
            legacy = [str(ref) for ref in tests if str(ref).startswith(LEGACY_TEST_DIRS)]
            bound = sorted(
                {
                    match
                    for key, value in case.items()
                    if key != "tests"
                    for match in LLD_IDENTIFIER.findall(json.dumps(value, ensure_ascii=False))
                }
            )
            if legacy and bound:
                raise ValueError(f"{label} binds the legacy test {legacy[0]} to the LLD identifier {bound[0]} (NCR-LEGACY-001)")


def requirement_evidence(requirement: str) -> dict[str, Any]:
    """Records that qualify a requirement: sealed legacy records never count (point 3, condition 2)."""
    if requirement not in requirement_register():
        raise ValueError(f"requirement {requirement} is not in the Requirement Register v1.1")
    qualifying: list[str] = []
    excluded: list[str] = []
    rejected: list[dict[str, str]] = []
    for manifest_path in sorted((ROOT / "reports/evidence").glob("G[0-7]/MANIFEST.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in manifest.get("artifacts", []):
            path = manifest_path.parent / item["path"]
            if path.suffix != ".json" or not path.is_file():
                continue
            record = json.loads(path.read_text(encoding="utf-8"))
            cases = record.get("requirement_results")
            if not isinstance(cases, list) or not any(
                isinstance(case, dict) and case.get("requirement_id") == requirement for case in cases
            ):
                continue
            relative = path.relative_to(ROOT).as_posix()
            if is_sealed_legacy_record(path):
                excluded.append(relative)
                continue
            if is_regression_record(record):
                rejected.append({"path": relative, "reason": "regression requalification record never qualifies a requirement"})
                continue
            try:
                check_new_record(record, manifest.get("gate"), manifest_path.parent, ROOT)
            except (OSError, ValueError, KeyError, SyntaxError) as exc:
                rejected.append({"path": relative, "reason": str(exc)})
                continue
            qualifying.append(relative)
    return {
        "excluded_non_conforming_sealed_records": excluded,
        "priority": requirement_register()[requirement]["priority"],
        "qualifying_records": qualifying,
        "rejected_records": rejected,
        "requirement_id": requirement,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--non-skipped", action="store_true")
    parser.add_argument("--root", type=Path, help="root for test references (default: OCOR_EVIDENCE_ROOT or the repository)")
    parser.add_argument("--requirement-evidence", metavar="REQUIREMENT_ID")
    args = parser.parse_args(argv)
    if args.requirement_evidence:
        try:
            print(json.dumps(requirement_evidence(args.requirement_evidence), indent=2, sort_keys=True))
            return 0
        except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1
    if not args.task or args.manifest is None:
        parser.error("--task and --manifest are required")
    root = (args.root or Path(os.environ.get("OCOR_EVIDENCE_ROOT") or ROOT)).resolve()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        entries = manifest.get("artifacts", [])
        evidence = next((item for item in entries if item.get("task_id") == args.task), None)
        if evidence is None:
            raise ValueError(f"manifest has no evidence entry for {args.task}")
        evidence_path = args.manifest.parent / evidence["path"]
        record = json.loads(evidence_path.read_text(encoding="utf-8"))
        if record.get("task_id") != args.task:
            raise ValueError("task identifier mismatch")
        if evidence.get("sha256") != digest(evidence_path):
            raise ValueError("evidence digest mismatch")
        raw_entry = next(
            (
                item
                for item in entries
                if item.get("task_id") == f"{args.task}-RAW"
            ),
            None,
        )
        if raw_entry is None:
            raise ValueError("manifest has no raw evidence entry")
        raw_path = args.manifest.parent / raw_entry["path"]
        raw_digest = digest(raw_path)
        if raw_entry.get("sha256") != raw_digest:
            raise ValueError("raw manifest digest mismatch")
        commands = record.get("commands", [])
        if not commands:
            raise ValueError("evidence has no executed command")
        for command in commands:
            if not isinstance(command, dict):
                raise ValueError(f"command entry is not an object: {command!r}")
            _validate_command(command)
        statuses = {str(item.get("status", "")).upper() for item in commands}
        if args.non_skipped and statuses & NON_QUALIFYING:
            raise ValueError(f"non-qualifying result present: {sorted(statuses & NON_QUALIFYING)}")
        if statuses != {"PASS"} or record.get("result") != "PASS":
            raise ValueError(f"mandatory evidence is not all PASS: {sorted(statuses)}")
        if record.get("raw_output_sha256") != raw_digest:
            raise ValueError("record raw-output digest mismatch")
        required = {"commit", "environment", "raw_output_sha256", "created_at"}
        missing = sorted(required - record.keys())
        if missing:
            raise ValueError(f"evidence fields missing: {', '.join(missing)}")
        if not is_sealed_legacy_record(evidence_path):
            if is_regression_record(record):
                check_regression_record(record, manifest, evidence["path"], root)
            else:
                check_new_record(record, manifest.get("gate"), evidence_path.parent, root)
        print(f"PASS: qualifying task evidence for {args.task}")
        return 0
    except (OSError, json.JSONDecodeError, KeyError, ValueError, SyntaxError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
