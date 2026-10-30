"""OCOR-DEV-REM-0046 (NCP-U13): plan, evidence and governance tooling of the normative
conformance plan (NORMATIVE-CONFORMANCE-PLAN (2026-10-30), plan unit NCP-U13, plus the
extra scope of decision point 3).

One test per register entry resolved by the unit (``plan_units.NCP-U13.red_tests`` of
reports/development/NORMATIVE_CONFORMANCE_REGISTER.json). Each test asserts the
prescribed behaviour of the entry on its normative anchors; the values are read from the
Requirement Register v1.1 (never from the normative traceability matrix, whose priority
and release columns are shifted: NCR-GOVERNANCE-002, decision point 3) and from the
approved plan (``g6_g7_proposals`` of the register at the decision commit).

Normative anchors (file:line):
- ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md:25
  NFR-003, every P0 has criterion, evidence and individual outcome;
- same file :26, NFR-004, the verification matrix declares metric, threshold, baseline,
  scenario/dataset, result and evidence for every P0;
- same file :14, column ``Metodo``: the verification method is normative (SUPPLEMENT
  point 4, NCP-S08);
- same file :267-268, FR-118 and FR-119 acceptance criteria name the FGM cases;
- docs/OCOR_LLD_v1.1.md:411, LLD v1.1 §7.3 evidence-package fields;
- docs/OCOR_LLD_v1.1.md:425-434, LLD v1.1 §8 traceability matrix, gate and reverse
  traceability (``ORPHAN_DESIGN``);
- docs/development_methodology/OCOR_ARCHITECTURE_FITNESS_FUNCTIONS.md:20-21, AFF-009
  and AFF-010.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable
REGISTER_V11 = "ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md"
LLD = "docs/OCOR_LLD_v1.1.md"
BACKLOG = "docs/development_plan/OCOR_IMPLEMENTATION_BACKLOG.json"
TRACE_PLAN = "docs/development_plan/OCOR_TRACEABILITY_PLAN.csv"
NCR = "reports/development/NORMATIVE_CONFORMANCE_REGISTER.json"
RUNTIME_EVIDENCE_VALIDATOR = "scripts/validate_runtime_evidence.py"
RCCAD_VALIDATOR = "scripts/validate_rccad.py"
REVERSE_INDEX = "reports/traceability/OCOR_TEST_REVERSE_TRACEABILITY_INDEX.json"
REVERSE_VALIDATOR = "scripts/validate_test_reverse_traceability.py"
SEALED_REGISTRY = "reports/traceability/OCOR_SEALED_EVIDENCE_REGISTRY.json"

G6_G7_TASKS = (
    "OCOR-DEV-0060",
    "OCOR-DEV-0062",
    "OCOR-DEV-0063",
    "OCOR-DEV-0064",
    "OCOR-DEV-0065",
    "OCOR-DEV-0066",
    "OCOR-DEV-0067",
)
LEDGER_OR_PACKAGE = ("OCOR-DEV-0067", "OCOR-DEV-0068", "OCOR-DEV-0069")
OUT_OF_PROFILE = "fuori dal profilo PoC"
# LLD v1.1 §7.3 (docs/OCOR_LLD_v1.1.md:411) and NFR-004 (Register v1.1 :26), as the
# per-case fields of the evidence package; raw_log carries the NFR-004 "evidence".
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
LEGACY_TEST_DIRS = ("ocor-runtime/tests/acceptance_ev/", "ocor-runtime/tests/backend_assumptions/")


# --------------------------------------------------------------------------- readers
def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def parse_requirement_register() -> dict[str, dict[str, Any]]:
    """Register v1.1 rows parsed by header name (a header is the row before a separator)."""
    lines = _read(REGISTER_V11).splitlines()
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
        assert len(cells) == len(header) and rid not in out, rid
        row = dict(zip(header, cells))

        def pick(prefix: str, row: dict[str, str] = row) -> str:
            return next(value for key, value in row.items() if key.startswith(prefix))

        out[rid] = {
            "line": index + 1,
            "priority": pick("Priorit"),
            "acceptance": pick("Criteri"),
            "method": pick("Metodo"),
            "release": pick("Release"),
        }
    assert len(out) == 285, len(out)
    return out


REG = parse_requirement_register()


def in_poc_profile(requirement_id: str) -> bool:
    """Decision point 3: a requirement is in the PoC profile when its Register release includes the PoC."""
    return "PoC" in REG[requirement_id]["release"]


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


def backlog_tasks() -> dict[str, dict[str, Any]]:
    return {task["id"]: task for task in json.loads(_read(BACKLOG))["tasks"]}


def plan_rows() -> dict[str, dict[str, str]]:
    with (ROOT / TRACE_PLAN).open(encoding="utf-8", newline="") as handle:
        return {row["requirement_id"]: row for row in csv.DictReader(handle)}


def approved_proposals() -> dict[str, dict[str, Any]]:
    return json.loads(_read(NCR))["g6_g7_proposals"]["tasks"]


def expand_fgm(text: str) -> set[str]:
    """FGM identifiers named by a Register acceptance cell, ranges (FGM-01..FGM-04, FGM-01–04) expanded."""
    text = text.replace("`", "")
    found: set[str] = set()
    for first, last in re.findall(r"FGM-(\d{2})\s*(?:\.\.|–|-|to)\s*(?:FGM-)?(\d{2})", text):
        found.update(f"FGM-{n:02d}" for n in range(int(first), int(last) + 1))
    found.update(re.findall(r"FGM-\d{2}", text))
    return found


def recount(criterion: str, kept: set[str], split: dict[str, list[str]]) -> str:
    """Decision point 3: the "(N here)" counts of the proposed criteria are recomputed after the exclusions."""
    other = len([r for r in split["non_test_method"] if r in kept])
    mixed = len([r for r in split["mixed_test_and_method"] if r in kept])
    criterion = re.sub(r"is not an automated test \(\d+ here\)", f"is not an automated test ({other} here)", criterion)
    return re.sub(r"mixed method \(\d+ here\)", f"mixed method ({mixed} here)", criterion)


# --------------------------------------------------------------------------- NCR-PLAN-001
def test_ncr_plan_001_conforms() -> None:
    """NFR-003 (Register :25), NFR-004 (:26), LLD v1.1 §7.3 (:411): every G6/G7 task binds
    its own requirements, criteria and per-requirement cases, never BR-003 alone."""
    tasks = backlog_tasks()
    proposals = approved_proposals()
    for task_id in G6_G7_TASKS:
        task, proposal = tasks[task_id], proposals[task_id]
        expected = [r for r in proposal["proposed_requirement_ids"] if in_poc_profile(r)]
        assert expected and expected != ["BR-003"], task_id
        assert task["requirement_ids"] == expected, (task_id, task["requirement_ids"][:5])
        kept = set(expected)
        for criterion in proposal["proposed_acceptance_criteria"]:
            assert recount(criterion, kept, proposal["method_split"]) in task["acceptance_criteria"], (task_id, criterion[:60])
        cases = task.get("requirement_cases")
        assert isinstance(cases, list) and [c["requirement_id"] for c in cases] == expected, task_id
        for case in cases:
            rid = case["requirement_id"]
            assert case["acceptance_criterion"] == {"path": REGISTER_V11, "lines": str(REG[rid]["line"])}, rid
            assert case["register_method"] == REG[rid]["method"], rid
            assert case["release"] == REG[rid]["release"] and in_poc_profile(rid), rid
            assert case["priority"] == REG[rid]["priority"], rid
            assert case["method_kind"] == method_kind(REG[rid]["method"]), rid
            assert case["expected_evidence"] == f"reports/evidence/G6/{rid}.json + raw-log hash", rid
    ledger = " ".join(tasks["OCOR-DEV-0067"]["acceptance_criteria"])
    assert "285" in ledger and OUT_OF_PROFILE in ledger
    for field in EVIDENCE_PACKAGE_FIELDS:
        assert field in ledger, field
    assert SEALED_REGISTRY in ledger, "0067 must exclude the non-conforming sealed records (condition 2)"


# --------------------------------------------------------------------------- NCR-PLAN-002 / 003
def test_ncr_plan_002_conforms() -> None:
    """NFR-003 (Register :25), LLD v1.1 §8 (:425-432): no requirement has the ledger or the
    decision package as implementation task; the implementation task declares it."""
    rows, tasks = plan_rows(), backlog_tasks()
    ledger_allocated = sorted(r for r, row in rows.items() if row["implementation_task"] in LEDGER_OR_PACKAGE)
    assert not ledger_allocated, ledger_allocated
    for rid, row in rows.items():
        implementation = tasks[row["implementation_task"]]
        assert rid in implementation["requirement_ids"], (rid, row["implementation_task"])
        assert implementation["delivery_gate"] in {f"G{i}" for i in range(6)}, (rid, row["implementation_task"])


def test_ncr_plan_003_conforms() -> None:
    """FR-164 (Register :409), FR-045 (:141), NFR-088 (:423), LLD v1.1 §8 (:425-432): the
    three misallocated requirements move to a task that delivers them."""
    rows = plan_rows()
    assert rows["FR-164"]["implementation_task"] != "OCOR-DEV-0047"
    assert rows["FR-045"]["implementation_task"] != "OCOR-DEV-0045"
    assert rows["NFR-088"]["implementation_task"] != "OCOR-DEV-0045"
    tasks = backlog_tasks()
    for rid in ("FR-164", "FR-045", "NFR-088"):
        task = tasks[rows[rid]["implementation_task"]]
        assert rid in task["requirement_ids"], rid
        assert rid not in tasks["OCOR-DEV-0047" if rid == "FR-164" else "OCOR-DEV-0045"]["requirement_ids"], rid


# --------------------------------------------------------------------------- NCR-PLAN-004
def test_ncr_plan_004_conforms() -> None:
    """FR-118 and FR-119 acceptance (Register :267-268), LLD v1.1 §7 (:378): OCOR-DEV-0061
    binds its FGM cases to FR-118 and FR-119 as the Register assigns them; 0062 likewise."""
    fr118 = expand_fgm(REG["FR-118"]["acceptance"])
    fr119 = expand_fgm(REG["FR-119"]["acceptance"])
    assert fr118 and fr119
    tasks = backlog_tasks()
    for task_id, numbers in (("OCOR-DEV-0061", range(1, 11)), ("OCOR-DEV-0062", range(11, 21))):
        task = tasks[task_id]
        assert {"FR-118", "FR-119"} <= set(task["requirement_ids"]), task_id
        cases = {case["fgm"]: case for case in task.get("fgm_cases", [])}
        assert sorted(cases) == [f"FGM-{n:02d}" for n in numbers], task_id
        for fgm, case in cases.items():
            expected = sorted(r for r, named in (("FR-118", fr118), ("FR-119", fr119)) if fgm in named)
            assert sorted(case["requirement_ids"]) == expected, (task_id, fgm)
            line = int(case["norm_ref"]["lines"])
            assert case["norm_ref"]["path"] == LLD and fgm in _read(LLD).splitlines()[line - 1], (task_id, fgm)
    criteria = " ".join(tasks["OCOR-DEV-0061"]["acceptance_criteria"])
    assert "FR-118" in criteria and "FR-119" in criteria


# --------------------------------------------------------------------------- NCR-PLAN-005
def test_ncr_plan_005_conforms() -> None:
    """Register :14 (column Metodo), LLD v1.1 §7.3 (:411) and §8 (:425-432): the plan
    carries the Register release and method of every requirement; a requirement outside
    the PoC profile is a ledger row of 0067, and a non-test method gets the evidence of
    its method, not an automated test case."""
    rows = plan_rows()
    assert len(rows) == 285
    for rid, row in rows.items():
        method = REG[rid]["method"]
        kind = method_kind(method)
        assert row.get("register_release") == REG[rid]["release"], rid
        assert row.get("register_method") == method, rid
        assert row.get("method_kind") == kind, rid
        frozen = row["verification_task"] == "OCOR-DEV-0061" or rid == "FR-118"
        if frozen:
            # changed only by the supersession requalification of OCOR-DEV-0061 (decision point 3)
            continue
        if not in_poc_profile(rid):
            assert row["campaign_profile"] == OUT_OF_PROFILE, rid
            assert (row["verification_task"], row["target_gate"]) == ("OCOR-DEV-0067", "G7"), rid
            assert row["qualifying_test"] == f"{OUT_OF_PROFILE}: ledger row without qualifying evidence", rid
            continue
        assert row["campaign_profile"] == "PoC", rid
        assert row["target_gate"] == "G6" and row["verification_task"] in G6_G7_TASKS[1:-1], rid
        if kind == "NON_TEST_METHOD":
            assert row["qualifying_test"] == f"Register method evidence: {method}", rid
        elif kind == "MIXED":
            assert row["qualifying_test"].endswith(f"; plus Register method evidence: {method}"), rid
        assert rid in backlog_tasks()[row["verification_task"]]["requirement_ids"], rid


# --------------------------------------------------------------------------- NCR-PLAN-006
def _test_files() -> list[str]:
    files = [p for base in ("ocor-runtime/tests", "reports/tests") for p in (ROOT / base).rglob("test_*.py")]
    return sorted(p.relative_to(ROOT).as_posix() for p in files)


def test_ncr_plan_006_conforms() -> None:
    """LLD v1.1 §8 (:434): every test declares at least one requirement, otherwise
    ORPHAN_DESIGN; the reverse index and its validator enforce it."""
    index_path = ROOT / REVERSE_INDEX
    assert index_path.is_file(), f"ORPHAN_DESIGN: {len(_test_files())} test files and no reverse traceability index"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    declared = {entry["path"]: entry for entry in index["tests"]}
    orphans = [path for path in _test_files() if not declared.get(path, {}).get("requirement_ids")]
    assert not orphans, f"ORPHAN_DESIGN: {orphans[:5]}"
    for path, entry in declared.items():
        assert (ROOT / path).is_file(), path
        assert set(entry["requirement_ids"]) <= set(REG), path
    result = subprocess.run([PY, str(ROOT / REVERSE_VALIDATOR)], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    with tempfile.TemporaryDirectory() as tmp:
        mutated = Path(tmp) / "index.json"
        index["tests"] = [entry for entry in index["tests"] if entry["path"] != _test_files()[0]]
        mutated.write_text(json.dumps(index), encoding="utf-8")
        result = subprocess.run(
            [PY, str(ROOT / REVERSE_VALIDATOR), "--index", str(mutated)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert result.returncode == 1 and "ORPHAN_DESIGN" in result.stdout + result.stderr


# --------------------------------------------------------------------------- evidence fixtures
_RAW = b"collected 2 items\n2 passed\n"
_TEST_SOURCE = '''"""Fixture campaign test."""


def test_fixture_positive():
    """Qualifies FR-062 (fixture declaration)."""
    assert True


def test_fixture_legacy_named():
    """Qualifies FR-062 (fixture declaration)."""
    assert True
'''


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _case(**overrides: Any) -> dict[str, Any]:
    case: dict[str, Any] = {
        "requirement_id": "FR-062",
        "method": REG["FR-062"]["method"],
        "metric": "failed, skipped and not executed test cases",
        "threshold": "0 failed, 0 skipped, 0 not executed",
        "baseline": "OCOR-DEV-0036 sealed behaviour",
        "dataset_or_scenario": "fixture scenario",
        "release_digest": "sha256:" + "0" * 64,
        "result": {"failed": 0, "not_executed": 0, "passed": 2, "skipped": 0},
        "raw_log": {"path": "OCOR-DEV-9999.log", "sha256": _sha(_RAW)},
        "owner": "fixture owner",
        "signature": {"scheme": "fixture", "signer": "fixture signer", "value": "fixture"},
        "status": "PASS",
        "tests": ["tests/test_fixture_campaign.py::test_fixture_positive"],
    }
    case.update(overrides)
    return case


def _write_evidence(base: Path, cases: list[dict[str, Any]], gate: str = "G6", task: str = "OCOR-DEV-9999") -> Path:
    (base / "tests").mkdir(parents=True, exist_ok=True)
    (base / "tests/test_fixture_campaign.py").write_text(_TEST_SOURCE, encoding="utf-8")
    evidence = base / "evidence"
    evidence.mkdir(exist_ok=True)
    record = {
        "task_id": task,
        "result": "PASS",
        "commands": [{"command": "pytest -q tests/test_fixture_campaign.py", "exit_code": 0, "status": "PASS"}],
        "raw_output_sha256": _sha(_RAW),
        "commit": "0" * 40,
        "environment": {"host": "fixture"},
        "created_at": "2026-10-30T00:00:00Z",
        "requirement_results": cases,
    }
    data = json.dumps(record, indent=2, sort_keys=True).encode("utf-8")
    (evidence / f"{task}.json").write_bytes(data)
    (evidence / f"{task}.log").write_bytes(_RAW)
    manifest = {
        "artifacts": [
            {"path": f"{task}.json", "sha256": _sha(data), "task_id": task},
            {"path": f"{task}.log", "sha256": _sha(_RAW), "task_id": f"{task}-RAW"},
        ],
        "gate": gate,
        "schema_version": "1.0",
    }
    (evidence / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence / "MANIFEST.json"


def _validate(manifest: Path, root: Path, task: str = "OCOR-DEV-9999") -> subprocess.CompletedProcess[str]:
    """Run the validator; test references of the cases resolve against OCOR_EVIDENCE_ROOT (the fixture root)."""
    return subprocess.run(
        [PY, str(ROOT / RUNTIME_EVIDENCE_VALIDATOR), "--task", task, "--non-skipped", "--manifest", str(manifest)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "OCOR_EVIDENCE_ROOT": str(root)},
    )


# --------------------------------------------------------------------------- NCR-EVIDENCE-001
def test_ncr_evidence_001_conforms() -> None:
    """NFR-003 (Register :25), LLD v1.1 §7.3 (:411) and §8 (:434): a new record binding a
    case to a requirement the test does not declare is rejected; a G6 case may not bind a
    legacy test to an LLD identifier nor qualify a requirement outside the PoC profile; the
    sealed records are recognised by path and sha256 and excluded as P0 evidence."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        accepted = _validate(_write_evidence(base, [_case()]), base)
        assert accepted.returncode == 0, accepted.stdout + accepted.stderr
        undeclared = _validate(_write_evidence(base, [_case(requirement_id="FR-053", method=REG["FR-053"]["method"])]), base)
        assert undeclared.returncode == 1 and "not declared by the test" in undeclared.stderr, undeclared.stderr
        legacy_path = base / "ocor-runtime/tests/backend_assumptions"
        legacy_path.mkdir(parents=True)
        (legacy_path / "test_ba03_single_writer.py").write_text(_TEST_SOURCE.replace("FR-062", "FR-062 BA-03"), encoding="utf-8")
        legacy = _case(
            tests=["ocor-runtime/tests/backend_assumptions/test_ba03_single_writer.py::test_fixture_positive"],
            ba_id="BA-03",
        )
        rejected = _validate(_write_evidence(base, [legacy]), base)
        assert rejected.returncode == 1 and "legacy test" in rejected.stderr, rejected.stderr
        out_of_profile = [r for r in REG if not in_poc_profile(r)][0]
        source = _TEST_SOURCE.replace("FR-062", out_of_profile)
        (base / "tests").mkdir(exist_ok=True)
        manifest = _write_evidence(base, [_case(requirement_id=out_of_profile, method=REG[out_of_profile]["method"])])
        (base / "tests/test_fixture_campaign.py").write_text(source, encoding="utf-8")
        rejected = _validate(manifest, base)
        assert rejected.returncode == 1 and OUT_OF_PROFILE in rejected.stderr, rejected.stderr
    registry = json.loads(_read(SEALED_REGISTRY))
    listed = {entry["path"]: entry for entry in registry["records"]}
    for path in sorted((ROOT / "reports/evidence").rglob("*.json")):
        relative = path.relative_to(ROOT).as_posix()
        data = json.loads(path.read_text(encoding="utf-8")) if path.name != "MANIFEST.json" else {}
        if data.get("requirement_results") and relative in listed:
            assert listed[relative]["sha256"] == _sha(path.read_bytes()), relative
    assert listed and all(entry["conforming"] is False and entry["reasons"] for entry in listed.values())
    result = subprocess.run(
        [PY, str(ROOT / RUNTIME_EVIDENCE_VALIDATOR), "--requirement-evidence", "FR-053"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["requirement_id"] == "FR-053" and report["qualifying_records"] == []
    assert report["excluded_non_conforming_sealed_records"], report


# --------------------------------------------------------------------------- NCR-EVIDENCE-002
@pytest.mark.parametrize("field", EVIDENCE_PACKAGE_FIELDS)
def test_ncr_evidence_002_conforms(field: str) -> None:
    """NFR-004 (Register :26), LLD v1.1 §7.3 (:411): a new record whose case lacks any
    evidence-package field is rejected; the complete case is accepted."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        complete = _validate(_write_evidence(base, [_case()]), base)
        assert complete.returncode == 0, complete.stdout + complete.stderr
        case = _case()
        del case[field]
        missing = _validate(_write_evidence(base, [case]), base)
        assert missing.returncode == 1 and field in missing.stderr, (field, missing.stderr)
        empty = _validate(_write_evidence(base, [_case(**{field: ""})]), base)
        assert empty.returncode == 1 and field in empty.stderr, (field, empty.stderr)
        no_cases = _validate(_write_evidence(base, []), base)
        assert no_cases.returncode == 1 and "requirement_results" in no_cases.stderr


# --------------------------------------------------------------------------- NCR-GOVERNANCE-001
@pytest.fixture(scope="module")
def repository_copy() -> Iterator[Path]:
    """A clone of the head sharing the object store, with the working-tree changes copied over."""
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain", "-z", "--untracked-files=all", "--no-renames"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    with tempfile.TemporaryDirectory(prefix="rem0046-rccad-") as tmp:
        target = Path(tmp) / "repo"
        subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(ROOT), str(target)], check=True)
        subprocess.run(["git", "-C", str(target), "checkout", "-q", "--detach", head], check=True)
        for item in status.split(b"\0"):
            if not item:
                continue
            relative = item[3:].decode("utf-8")
            source, destination = ROOT / relative, target / relative
            if source.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            elif destination.exists():
                destination.unlink()
        yield target


def _rccad(root: Path) -> dict[str, Any]:
    result = subprocess.run([PY, str(ROOT / RCCAD_VALIDATOR), "--root", str(root)], cwd=ROOT, capture_output=True, text=True, timeout=300)
    return json.loads(result.stdout)


def _rules(payload: dict[str, Any]) -> set[str]:
    return {finding["rule_id"] for finding in payload["findings"]}


def test_ncr_governance_001_conforms(repository_copy: Path) -> None:
    """AFF-009 and AFF-010 (OCOR_ARCHITECTURE_FITNESS_FUNCTIONS.md:20-21): the fitness
    functions fail without the property they state, on the current components and on
    requirement-specific bindings, and pass on the head."""
    head = _rccad(repository_copy)
    assert not ({"AFF-009", "AFF-010", "RCCAD-VALIDATOR-ERROR"} & _rules(head)), head["findings"]

    target = repository_copy / "ocor-runtime/src/ocor_runtime/c8/tool_runtime.py"
    original = target.read_text(encoding="utf-8")
    target.write_text(original + "\n\ndef _authorise_fixture(call: object, allow: bool = True) -> bool:\n    return allow\n", encoding="utf-8")
    try:
        assert "AFF-009" in _rules(_rccad(repository_copy)), "permissive authorization default accepted in a current component"
    finally:
        target.write_text(original, encoding="utf-8")

    target = repository_copy / "ocor-runtime/src/ocor_runtime/c6/engine.py"
    original = target.read_text(encoding="utf-8")
    target.write_text(
        original + "\n\ndef _fixture_fallback() -> str:\n    try:\n        raise RuntimeError\n    except RuntimeError:\n        return \"PERMIT\"\n",
        encoding="utf-8",
    )
    try:
        assert "AFF-009" in _rules(_rccad(repository_copy)), "fail-open exception fallback accepted in a current component"
    finally:
        target.write_text(original, encoding="utf-8")

    backlog_path = repository_copy / BACKLOG
    original = backlog_path.read_text(encoding="utf-8")
    backlog = json.loads(original)
    for task in backlog["tasks"]:
        if task["id"] == "OCOR-DEV-0063":
            task["requirement_ids"] = ["BR-003"]
    backlog_path.write_text(json.dumps(backlog, indent=2) + "\n", encoding="utf-8")
    try:
        assert "AFF-010" in _rules(_rccad(repository_copy)), "a G6 task bound to BR-003 alone accepted"
    finally:
        backlog_path.write_text(original, encoding="utf-8")

    plan_path = repository_copy / TRACE_PLAN
    original = plan_path.read_text(encoding="utf-8")
    plan_path.write_text(original.replace("BR-002,DEC-017,WS-01,OCOR-DEV-0009,", "BR-002,DEC-017,WS-01,OCOR-DEV-0067,", 1), encoding="utf-8")
    try:
        assert original != plan_path.read_text(encoding="utf-8")
        assert "AFF-010" in _rules(_rccad(repository_copy)), "a requirement implemented by the ledger accepted"
    finally:
        plan_path.write_text(original, encoding="utf-8")
