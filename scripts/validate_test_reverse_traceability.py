#!/usr/bin/env python3
"""Fail-closed validator of the reverse traceability of tests (LLD v1.1 §8).

LLD v1.1 §8 (docs/OCOR_LLD_v1.1.md:434): every test declares at least one requirement,
otherwise ``ORPHAN_DESIGN`` (register entry NCR-PLAN-006). The non-normative index
``reports/traceability/OCOR_TEST_REVERSE_TRACEABILITY_INDEX.json`` gives, for every
``test_*.py`` under ``ocor-runtime/tests`` and ``reports/tests``, the requirements of the
Requirement Register v1.1 it traces to and the basis of each link:

- ``named_in_test``: the identifier appears in the test file source;
- ``task_binding``: a requirement of the backlog task that owns the file;
- ``remediation_record``: a ``requirement_results`` requirement of the remediation record;
- ``subject_task``: a requirement of the backlog task whose deliverable the test exercises,
  with a rationale.

No link is a declaration by a test function: ``named_in_test`` is per file, and
scripts/validate_runtime_evidence.py reads declarations from the selected function only;
the links are traceability, never evidence. The validator never modifies the index
and never converts a missing link into PASS.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INDEX = "reports/traceability/OCOR_TEST_REVERSE_TRACEABILITY_INDEX.json"
REGISTER_V11 = "ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md"
BACKLOG = "docs/development_plan/OCOR_IMPLEMENTATION_BACKLOG.json"
TEST_TREES = ("ocor-runtime/tests", "reports/tests")
REQUIREMENT_ID = re.compile(r"\b(?:BR|FR|NFR)-\d{3}\b")
TASK_KINDS = ("task_binding", "subject_task")
KINDS = ("named_in_test", "remediation_record", *TASK_KINDS)


def register_ids(root: Path) -> set[str]:
    text = (root / REGISTER_V11).read_text(encoding="utf-8")
    ids = set(re.findall(r"^\| `?((?:BR|FR|NFR)-\d{3})`? \|", text, re.MULTILINE))
    if len(ids) != 285:
        raise ValueError(f"Requirement Register v1.1 parsed {len(ids)} requirements, expected 285")
    return ids


def collect_test_files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for tree in TEST_TREES for p in (root / tree).rglob("test_*.py"))


def _record_requirements(path: Path) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("requirement_results") if isinstance(data, dict) else None
    if not isinstance(cases, list):
        return set()
    return {str(case.get("requirement_id")) for case in cases if isinstance(case, dict)}


def _check_link(root: Path, path: str, requirement: str, link: Any, tasks: dict[str, set[str]]) -> list[str]:
    label = f"{path} {requirement}"
    if not isinstance(link, dict) or link.get("kind") not in KINDS:
        return [f"UNKNOWN_BASIS: {label}: {link!r}"]
    kind = link["kind"]
    if kind == "named_in_test":
        source = (root / path).read_text(encoding="utf-8")
        return [] if requirement in REQUIREMENT_ID.findall(source) else [f"BASIS_MISMATCH: {label} is not named in the test"]
    if kind in TASK_KINDS:
        task = str(link.get("task_id"))
        if task not in tasks:
            return [f"UNKNOWN_TASK: {label}: {task}"]
        if kind == "subject_task" and not str(link.get("rationale", "")).strip():
            return [f"MISSING_RATIONALE: {label}"]
        return [] if requirement in tasks[task] else [f"BASIS_MISMATCH: {label} is not a requirement of {task}"]
    record = link.get("source")
    source_path = root / record if isinstance(record, str) and record else None
    if source_path is None or not source_path.is_file():
        return [f"MISSING_FILE: {label}: remediation record {link.get('source')!r}"]
    if requirement not in _record_requirements(source_path):
        return [f"BASIS_MISMATCH: {label} is not in the requirement_results of {link['source']}"]
    return []


def validate(root: Path, index_path: Path) -> list[str]:
    index = json.loads(index_path.read_text(encoding="utf-8"))
    entries = index.get("tests") if isinstance(index, dict) else None
    if not isinstance(entries, list):
        return ["INVALID_INDEX: no tests list"]
    known = register_ids(root)
    backlog = json.loads((root / BACKLOG).read_text(encoding="utf-8"))["tasks"]
    tasks = {task["id"]: set(task["requirement_ids"]) for task in backlog}
    findings: list[str] = []
    declared: dict[str, dict[str, Any]] = {}
    for entry in entries:
        path = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(path, str) or not path or path in declared:
            findings.append(f"INVALID_ENTRY: duplicate, unnamed or malformed entry {entry!r}")
            continue
        declared[path] = entry
        if not (root / path).is_file():
            findings.append(f"MISSING_FILE: {path}")
            continue
        requirements = entry.get("requirement_ids")
        basis = entry.get("basis")
        if not isinstance(requirements, list) or not requirements:
            findings.append(f"ORPHAN_DESIGN: {path} declares no requirement")
            continue
        if not all(isinstance(requirement, str) for requirement in requirements):
            findings.append(f"INVALID_ENTRY: {path}: requirement_ids is not a list of identifiers")
            continue
        unknown = sorted(set(requirements) - known)
        if unknown:
            findings.append(f"UNKNOWN_REQUIREMENT: {path}: {', '.join(unknown)}")
        if not isinstance(basis, dict) or set(basis) != set(requirements):
            findings.append(f"BASIS_MISMATCH: {path}: basis keys differ from requirement_ids")
            continue
        for requirement, links in sorted(basis.items()):
            if not isinstance(links, list) or not links:
                findings.append(f"BASIS_MISMATCH: {path} {requirement} has no basis")
                continue
            for link in links:
                findings.extend(_check_link(root, path, requirement, link, tasks))
    for path in collect_test_files(root):
        if path not in declared:
            findings.append(f"ORPHAN_DESIGN: {path} is not in the reverse traceability index")
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (default: repo root)")
    parser.add_argument("--index", type=Path, default=None, help=f"index path (default: <root>/{INDEX})")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    index_path = args.index or root / INDEX
    try:
        findings = validate(root, index_path)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        findings = [f"INVALID_INDEX: {exc}"]
    status = "FAIL" if findings else "PASS"
    print(json.dumps({"findings": findings, "index": str(index_path), "status": status}, indent=2, sort_keys=True))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
