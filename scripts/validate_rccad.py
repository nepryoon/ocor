#!/usr/bin/env python3
"""Fail-closed, dependency-free validator for OCOR-RCCAD process controls."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


REQUIRED_ARTIFACTS = (
    "AGENTS.md",
    "PLANS.md",
    "docs/development_methodology/README.md",
    "docs/development_methodology/OCOR_RCCAD_v1.0.md",
    "docs/development_methodology/OCOR_TEST_STRATEGY.md",
    "docs/development_methodology/OCOR_ARCHITECTURE_FITNESS_FUNCTIONS.md",
    "docs/development_methodology/OCOR_DEFINITION_OF_DONE.md",
    "docs/development_methodology/OCOR_MODEL_OPERATING_PROFILE.md",
    "docs/development_methodology/methodology.json",
    "docs/development_methodology/methodology.schema.json",
    "reports/development/EXECUTION_STATE.json",
    "reports/development/ITERATION_LOG.md",
    "reports/development/MODEL_HANDOFF.json",
    "reports/development/METHOD_COMPLIANCE.json",
    "reports/tests/rccad_tdd_evidence.json",
    "reports/tests/autonomous_tooling_tdd_evidence.json",
    "infra/toolchain.lock.json",
    "infra/services.lock.json",
    "ocor-runtime/docs/governance_dossier/ARA_DECISION_RECORD_v1.5.md",
    "ocor-runtime/docs/governance_dossier/ARA_DECISION_RECORD_v1.4.md",
    "ocor-runtime/docs/governance_dossier/registers/OCOR_Decision_Register_v1.4_APPROVED.md",
    "ocor-runtime/docs/governance_dossier/registers/OCOR_Decision_Traceability_Index_v1.4_APPROVED.md",
)
EXPECTED_AFF = {f"AFF-{number:03d}" for number in range(1, 11)}
BACKENDS = re.compile(r"postgres|kafka|qdrant|terminus|typedb|fuseki|openbao|spiffe", re.I)
DIRECT_CLIENTS = re.compile(r"^\s*(?:from|import)\s+(?:psycopg|kafka|qdrant_client|terminusdb_client|typedb)", re.M)


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def canonical(path: Path, value: dict[str, Any]) -> bool:
    return path.read_text(encoding="utf-8") == json.dumps(value, indent=2, sort_keys=True) + "\n"


def git_changed(root: Path, base_ref: str | None) -> list[str]:
    commands = [
        ["git", "diff", "--name-only", "-z", "--no-renames"],
        ["git", "diff", "--cached", "--name-only", "-z", "--no-renames"],
    ]
    if base_ref:
        commands.append(["git", "diff", "--name-only", "-z", "--no-renames", base_ref, "HEAD"])
    changed: set[str] = set()
    for command in commands:
        result = subprocess.run(command, cwd=root, capture_output=True, check=False)
        if result.returncode:
            raise RuntimeError(result.stderr.decode("utf-8", "replace").strip() or "git diff failed")
        changed.update(os.fsdecode(name) for name in result.stdout.split(b"\0") if name)
    return sorted(changed)


LEGACY_SLICE_MODULES = {
    "c1_compiler.py", "c2_identity.py", "c3_store.py", "c4_marking.py", "c5_actions.py",
    "c6_capabilities.py", "c7_emission.py", "c8_agent.py", "__init__.py", "canonical.py", "errors.py",
}
# AFF-009 (authorization defaults fail closed) on the current components: a parameter or
# field whose name grants authorization never defaults to a permissive value, and an
# exception handler never returns a permissive decision (NCR-GOVERNANCE-001, NCP-U13).
AUTHORIZATION_NAME = re.compile(
    r"(?:^|_)(?:allow|allowed|permit|permitted|authori[sz]ed|approved|granted|fail_open|bypass|skip_(?:auth\w*|policy|check|gate))(?:$|_)",
    re.IGNORECASE,
)
PERMISSIVE_VALUES = {"ALLOW", "ALLOWED", "PERMIT", "PERMITTED", "GRANTED", "NOT_REQUIRED", "APPROVED"}


def _permissive(node: ast.AST | None, *, bare_true: bool) -> bool:
    if isinstance(node, ast.Constant):
        return (bare_true and node.value is True) or (isinstance(node.value, str) and node.value.upper() in PERMISSIVE_VALUES)
    if isinstance(node, ast.Attribute):
        return node.attr.upper() in PERMISSIVE_VALUES
    if isinstance(node, ast.Call):
        name = ast.unparse(node.func)
        return any(token in name for token in ("Permissive", "AllowAll", "PermitAll"))
    return False


def aff009_current_component_findings(package_root: Path) -> list[tuple[str, str]]:
    """(relative path, detail) of permissive authorization defaults in current components."""
    findings: list[tuple[str, str]] = []
    for path in sorted(package_root.rglob("*.py")):
        relative = path.relative_to(package_root).as_posix()
        if relative in LEGACY_SLICE_MODULES or relative.startswith("fallback/"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                arguments = node.args
                positional = arguments.posonlyargs + arguments.args
                defaults = [None] * (len(positional) - len(arguments.defaults)) + list(arguments.defaults)
                pairs = list(zip(positional, defaults)) + list(zip(arguments.kwonlyargs, arguments.kw_defaults))
                for argument, default in pairs:
                    if default is not None and AUTHORIZATION_NAME.search(argument.arg) and _permissive(default, bare_true=True):
                        findings.append((relative, f"permissive authorization default {node.name}({argument.arg}={ast.unparse(default)})"))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if AUTHORIZATION_NAME.search(node.target.id) and _permissive(node.value, bare_true=True):
                    findings.append((relative, f"permissive authorization default field {node.target.id}"))
            elif isinstance(node, ast.ExceptHandler):
                for inner in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                    if isinstance(inner, ast.Return) and inner.value is not None and _permissive(inner.value, bare_true=False):
                        findings.append((relative, f"fail-open exception fallback returns {ast.unparse(inner.value)} (line {inner.lineno})"))
    return findings


G6_G7_VERIFICATION_TASKS = {f"OCOR-DEV-{n:04d}" for n in range(60, 68)}
LEDGER_OR_PACKAGE = {"OCOR-DEV-0067", "OCOR-DEV-0068", "OCOR-DEV-0069"}


def aff010_binding_findings(backlog: dict[str, Any], trace_rows: list[dict[str, str]]) -> list[tuple[str, str]]:
    """(subject, detail) where a requirement does not map to its own implementation and
    test plan: a G6/G7 campaign bound to BR-003 alone or without per-requirement cases,
    a requirement implemented by the ledger or decision package, or an implementation
    task that does not declare its requirement (NCR-GOVERNANCE-001, NCP-U13)."""
    findings: list[tuple[str, str]] = []
    tasks = {task.get("id"): task for task in backlog.get("tasks", [])}
    for task_id in sorted(G6_G7_VERIFICATION_TASKS & set(tasks)):
        task = tasks[task_id]
        requirements = list(task.get("requirement_ids") or [])
        if not requirements or set(requirements) == {"BR-003"}:
            findings.append((task_id, "campaign is bound to BR-003 alone, not to the requirements it qualifies"))
        if task_id != "OCOR-DEV-0061":
            cases = [case.get("requirement_id") for case in task.get("requirement_cases") or []]
            if cases != requirements:
                findings.append((task_id, "requirement_cases do not list exactly the task requirement_ids"))
    for row in trace_rows:
        rid, implementation = row.get("requirement_id", ""), row.get("implementation_task", "")
        if implementation in LEDGER_OR_PACKAGE or implementation in G6_G7_VERIFICATION_TASKS:
            findings.append((rid, f"implementation task {implementation} is a campaign, the ledger or the decision package"))
        elif rid not in (tasks.get(implementation) or {}).get("requirement_ids", []):
            findings.append((rid, f"implementation task {implementation} does not declare the requirement"))
        if row.get("verification_task") not in tasks:
            findings.append((rid, f"verification task {row.get('verification_task')} is not in the backlog"))
    return findings


def validate(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    findings: list[dict[str, str]] = []
    fitness_results = {identifier: "PASS_STATIC_PRECHECK" for identifier in sorted(EXPECTED_AFF)}

    def fail(rule_id: str, detail: str, path: str = "") -> None:
        findings.append({"detail": detail, "path": path, "rule_id": rule_id})
        if rule_id in fitness_results:
            fitness_results[rule_id] = "FAIL"

    simulated_missing = set(args.simulate_missing)
    for relative in REQUIRED_ARTIFACTS:
        if relative in simulated_missing or not (root / relative).is_file():
            fail("RCCAD-ARTIFACT-MISSING", "required governed artifact is absent", relative)

    manifest: dict[str, Any] = {}
    state: dict[str, Any] = {}
    compliance: dict[str, Any] = {}
    handoff: dict[str, Any] = {}
    for relative, target in (
        ("docs/development_methodology/methodology.json", "manifest"),
        ("reports/development/EXECUTION_STATE.json", "state"),
        ("reports/development/METHOD_COMPLIANCE.json", "compliance"),
        ("reports/development/MODEL_HANDOFF.json", "handoff"),
    ):
        path = root / relative
        if not path.is_file():
            continue
        try:
            value = load_object(path)
            if not canonical(path, value):
                fail("RCCAD-NONCANONICAL-JSON", "JSON must use sorted keys and stable indentation", relative)
            if target == "manifest":
                manifest = value
            elif target == "state":
                state = value
            elif target == "compliance":
                compliance = value
            else:
                handoff = value
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            fail("RCCAD-JSON-INVALID", str(exc), relative)

    if manifest:
        identity = (manifest.get("schema_version"), manifest.get("methodology_id"), manifest.get("version"), manifest.get("decision_id"))
        if identity != ("1.0", "OCOR-RCCAD", "1.0", "DEC-210"):
            fail("RCCAD-MANIFEST-IDENTITY", f"unexpected identity {identity}", "docs/development_methodology/methodology.json")
        if manifest.get("lifecycle") != [f"G{number}" for number in range(8)]:
            fail("RCCAD-LIFECYCLE", "G0-G7 must be preserved in order")
        if manifest.get("evidence_fence") != {"E1": 0, "E2": 0}:
            fail("RCCAD-EVIDENCE-FENCE", "E1/E2 may not be promoted")
        functions = manifest.get("architecture_fitness_functions", [])
        identifiers = {item.get("id") for item in functions if isinstance(item, dict)}
        if len(functions) != 10 or identifiers != EXPECTED_AFF or not all(item.get("blocking") is True and item.get("command") for item in functions if isinstance(item, dict)):
            fail("RCCAD-FITNESS-INCOMPLETE", "AFF-001..AFF-010 must be executable and blocking")
        sources = manifest.get("authoritative_sources", {})
        expected_sources = {"backlog", "definition_of_done", "dependency_dag", "execution_state", "handoff", "test_strategy"}
        if not isinstance(sources, dict) or set(sources) != expected_sources:
            fail("RCCAD-SOURCE-SET", "authoritative source map must contain the six governed roles")
            sources = {}
        for relative in sources.values():
            if not isinstance(relative, str) or not (root / relative).is_file():
                fail("RCCAD-SOURCE-MISSING", "authoritative source is absent", str(relative))

    for value, label in ((state, "execution state"), (compliance, "method compliance")):
        if not value:
            continue
        fence = value.get("evidence_fence") or {"E1": value.get("claims", {}).get("E1"), "E2": value.get("claims", {}).get("E2")}
        if fence != {"E1": 0, "E2": 0}:
            fail("RCCAD-EVIDENCE-FENCE", f"{label} promotes evidence")
    if state and (state.get("claims", {}).get("runtime_conformance") != "NOT_ESTABLISHED" or state.get("claims", {}).get("Production_readiness") != "NO-GO"):
        fail("RCCAD-CLAIM-LEAK", "runtime/Production claims must remain fenced")
    if state and handoff and state.get("baseline_commit") != handoff.get("baseline_commit"):
        fail("RCCAD-STATE-HANDOFF-DRIFT", "baseline commits disagree")
    if state and handoff and state.get("active_iteration", {}).get("branch") != handoff.get("branch"):
        fail("RCCAD-STATE-HANDOFF-DRIFT", "branches disagree")
    for relative in handoff.get("evidence_paths", []) if handoff else []:
        if not isinstance(relative, str) or not (root / relative).is_file():
            fail("AFF-008", "handoff evidence reference is absent", str(relative))

    tdd_path = root / "reports/tests/rccad_tdd_evidence.json"
    if tdd_path.is_file():
        try:
            tdd = load_object(tdd_path)
            if not canonical(tdd_path, tdd):
                fail("AFF-008", "TDD evidence JSON is not canonical", str(tdd_path.relative_to(root)))
            phases = tdd.get("phases", [])
            if [item.get("phase") for item in phases] != ["RED", "GREEN", "REFACTOR"]:
                fail("AFF-008", "TDD evidence must contain ordered RED/GREEN/REFACTOR phases", str(tdd_path.relative_to(root)))
            for item in phases:
                fingerprint = item.get("fingerprint")
                expected = item.get("fingerprint_sha256")
                if not isinstance(fingerprint, str) or hashlib.sha256(fingerprint.encode()).hexdigest() != expected:
                    fail("AFF-008", f"invalid {item.get('phase')} failure/result fingerprint", str(tdd_path.relative_to(root)))
            if len(phases) == 3 and (
                phases[0].get("exit_code") == 0
                or phases[0].get("result") != "EXPECTED_FAILURE"
                or any(item.get("exit_code") != 0 or item.get("result") != "PASS" for item in phases[1:])
            ):
                fail("AFF-008", "TDD phase exit/result semantics are invalid", str(tdd_path.relative_to(root)))
            implementation_commit = str(tdd.get("implementation_commit", ""))
            commit_check = subprocess.run(
                ["git", "cat-file", "-e", f"{implementation_commit}^{{commit}}"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            ancestry = subprocess.run(
                ["git", "merge-base", "--is-ancestor", implementation_commit, "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            local_commit_valid = commit_check.returncode == 0 and ancestry.returncode == 0
            remote_parent = str(tdd.get("remote_materialization_commit", ""))
            remote_check = subprocess.run(
                ["git", "cat-file", "-e", f"{remote_parent}^{{commit}}"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            remote_ancestry = subprocess.run(
                ["git", "merge-base", "--is-ancestor", remote_parent, "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            # Once the remote materialization commit is part of the integrated
            # history, local clones can prove the same ancestry without relying
            # on a CI-only environment marker.
            remote_commit_valid = remote_check.returncode == 0 and remote_ancestry.returncode == 0
            if not (local_commit_valid or remote_commit_valid):
                fail("AFF-008", "neither local TDD commit nor remote materialization parent is an ancestor of HEAD", str(tdd_path.relative_to(root)))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            fail("AFF-008", str(exc), str(tdd_path.relative_to(root)))

    register_expectations = {
        "ocor-runtime/docs/governance_dossier/registers/OCOR_Decision_Register_v1.4_APPROVED.md": (
            "ocor-runtime/docs/governance_dossier/registers/OCOR_Decision_Register_v1.3_APPROVED.md",
            "467bc77b582041c3b10cbdf4d111da21cb92e035a04ee0ae02936b0a44c68ef6",
        ),
        "ocor-runtime/docs/governance_dossier/registers/OCOR_Decision_Traceability_Index_v1.4_APPROVED.md": (
            "ocor-runtime/docs/governance_dossier/registers/OCOR_Decision_Traceability_Index_v1.3_APPROVED.md",
            "a8952aadb4c4ae53af7f31c606cd853bd041562d18b13c5f55776e7053772905",
        ),
    }
    for current, (prior, expected_digest) in register_expectations.items():
        current_path, prior_path = root / current, root / prior
        if current_path.is_file() and "DEC-210" not in current_path.read_text(encoding="utf-8"):
            fail("AFF-010", "DEC-210 is absent from the current decision index", current)
        if prior_path.is_file() and hashlib.sha256(prior_path.read_bytes()).hexdigest() != expected_digest:
            fail("AFF-008", "incorporated prior register digest drift", prior)

    changed = set(git_changed(root, args.base_ref)) | set(args.simulate_changed_path)
    for relative in sorted(changed):
        if relative == "inputs" or relative.startswith("inputs/"):
            fail("RCCAD-IMMUTABLE-INPUT", "immutable input path changed", relative)

    package_root = root / "ocor-runtime/src/ocor_runtime"
    allowed_component_imports = {
        "c1_compiler.py": {"canonical", "errors"},
        "c2_identity.py": {"errors"},
        "c3_store.py": {"canonical", "errors"},
        "c4_marking.py": {"errors"},
        "c5_actions.py": {"canonical", "c3_store", "errors"},
        "c6_capabilities.py": {"c3_store", "errors"},
        "c7_emission.py": {"c3_store", "c4_marking", "c6_capabilities", "errors"},
        "c8_agent.py": {"canonical", "c2_identity", "c3_store", "c6_capabilities", "errors"},
        "canonical.py": {"errors"},
        "errors.py": set(),
    }
    for name, allowed in allowed_component_imports.items():
        path = package_root / name
        if not path.is_file():
            fail("AFF-001", "required component module is absent", str(path.relative_to(root)))
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        actual = {
            (node.module or "").split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.level == 1
        }
        forbidden = sorted(actual - allowed)
        if forbidden:
            fail("AFF-001", f"forbidden component imports: {forbidden}", str(path.relative_to(root)))

    canonical_path = package_root / "canonical.py"
    if canonical_path.is_file() and BACKENDS.search(canonical_path.read_text(encoding="utf-8")):
        fail("AFF-003", "backend identifier leaked into canonical domain module", str(canonical_path.relative_to(root)))
    for path in package_root.rglob("*.py"):
        relative_parts = path.relative_to(package_root).parts
        if DIRECT_CLIENTS.search(path.read_text(encoding="utf-8")):
            if "adapters" not in relative_parts:
                fail("AFF-002", "infrastructure client leaked outside adapters", str(path.relative_to(root)))
                fail("AFF-006", "direct backend client import outside an adapter", str(path.relative_to(root)))
    for path in (root / "ocor-runtime/schemas").glob("*.json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            fail("AFF-004", str(exc), str(path.relative_to(root)))
    openapi = root / "ocor-runtime/schemas/ocor.openapi.yaml"
    proto = root / "ocor-runtime/schemas/ocor_runtime.proto"
    if not openapi.is_file() or not openapi.read_text(encoding="utf-8").lstrip().startswith("openapi: 3.1"):
        fail("AFF-004", "OpenAPI 3.1 contract is absent or unidentified", str(openapi.relative_to(root)))
    if not proto.is_file() or 'syntax = "proto3";' not in proto.read_text(encoding="utf-8"):
        fail("AFF-004", "Proto3 contract is absent or unidentified", str(proto.relative_to(root)))
    canonical_source = canonical_path.read_text(encoding="utf-8") if canonical_path.is_file() else ""
    for token in ("_utf16_sort_key", "canonicalize_json", "hashlib.sha256", "reject_duplicate_keys"):
        if token not in canonical_source:
            fail("AFF-005", f"canonical determinism control absent: {token}", str(canonical_path.relative_to(root)))

    idempotency_surfaces = {
        "ocor-runtime/src/ocor_runtime/c3_store.py": ("idempotency_key", "_idempotency"),
        "ocor-runtime/src/ocor_runtime/c7_emission.py": ("idempotency_key", "deduplicated"),
    }
    for relative, tokens in idempotency_surfaces.items():
        source = (root / relative).read_text(encoding="utf-8") if (root / relative).is_file() else ""
        if any(token not in source for token in tokens):
            fail("AFF-007", "idempotency/dedup control is absent", relative)

    for manifest_path in sorted((root / "reports/evidence").glob("G[0-7]/MANIFEST.json")):
        try:
            evidence_manifest = load_object(manifest_path)
            for item in evidence_manifest.get("artifacts", []):
                artifact = manifest_path.parent / item["path"]
                if not artifact.is_file() or hashlib.sha256(artifact.read_bytes()).hexdigest() != item.get("sha256"):
                    fail("AFF-008", "evidence artifact missing or digest mismatch", str(artifact.relative_to(root)))
            forbidden_statuses = {"SKIPPED", "UNAVAILABLE", "NOT_EXECUTED", "XFAIL"}
            for item in evidence_manifest.get("requirement_results", []):
                if str(item.get("status", "")).upper() in forbidden_statuses:
                    fail("AFF-008", "non-qualifying status appears in accepted evidence manifest", str(manifest_path.relative_to(root)))
        except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
            fail("AFF-008", str(exc), str(manifest_path.relative_to(root)))

    for path in package_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                fail("AFF-009", "silent exception fallback is prohibited", str(path.relative_to(root)))
    for relative, token in (
        ("ocor-runtime/src/ocor_runtime/c6_capabilities.py", "AuthorizationError"),
        ("ocor-runtime/src/ocor_runtime/c7_emission.py", "EmissionBlocked"),
        ("ocor-runtime/src/ocor_runtime/c8_agent.py", "SandboxViolation"),
    ):
        if token not in (root / relative).read_text(encoding="utf-8"):
            fail("AFF-009", f"fail-closed control absent: {token}", relative)
    for relative, detail in aff009_current_component_findings(package_root):
        fail("AFF-009", detail, f"ocor-runtime/src/ocor_runtime/{relative}")

    backlog_path = root / "docs/development_plan/OCOR_IMPLEMENTATION_BACKLOG.json"
    trace_path = root / "reports/traceability/OCOR_IRB_ADD_LLD_v1.1_Matrix.json"
    try:
        backlog = load_object(backlog_path)
        for task in backlog.get("tasks", []):
            if not all(task.get(field) for field in ("id", "requirement_ids", "validation_commands", "acceptance_criteria", "negative_acceptance_criteria", "evidence_outputs")):
                fail("AFF-010", "backlog task lacks requirement/test/evidence traceability", str(task.get("id", "UNKNOWN")))
        trace = load_object(trace_path)
        requirement_identifiers = [row.get("requirement_id") for row in trace.get("rows", [])]
        if len(requirement_identifiers) != 285 or len(set(requirement_identifiers)) != 285:
            fail("AFF-010", "authoritative requirement traceability is not a 285-row bijection", str(trace_path.relative_to(root)))
        plan_path = root / "docs/development_plan/OCOR_TRACEABILITY_PLAN.csv"
        with plan_path.open(encoding="utf-8", newline="") as handle:
            plan_rows = list(csv.DictReader(handle))
        if sorted(str(row.get("requirement_id")) for row in plan_rows) != sorted(str(rid) for rid in requirement_identifiers):
            fail("AFF-010", "traceability plan rows are not the 285 requirements of the matrix", str(plan_path.relative_to(root)))
        for subject, detail in aff010_binding_findings(backlog, plan_rows):
            fail("AFF-010", detail, subject)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        fail("AFF-010", str(exc), str(backlog_path.relative_to(root)))

    exceptions = compliance.get("test_exceptions", []) if compliance else []
    allowed_skip_paths = {item.get("path") for item in exceptions if isinstance(item, dict) and item.get("justification") and item.get("qualifying_ci_must_execute") is True}
    test_paths = list((root / "ocor-runtime/tests").rglob("*.py")) + list((root / "reports/tests").rglob("*.py"))
    for path in test_paths:
        source = path.read_text(encoding="utf-8")
        relative = path.relative_to(root).as_posix()
        if re.search(r"pytest\.skip|mark\.skip|unittest\.skip", source) and relative not in allowed_skip_paths:
            fail("RCCAD-UNJUSTIFIED-SKIP", "skip control lacks qualifying-CI justification", relative)

    methodology_path = root / "docs/development_methodology/methodology.json"
    payload = {
        "checked_artifacts": len(REQUIRED_ARTIFACTS),
        "dynamic_assurance": "CI_REQUIRED",
        "findings": sorted(findings, key=lambda item: (item["rule_id"], item["path"], item["detail"])),
        "fitness_results": fitness_results,
        "methodology_sha256": hashlib.sha256(methodology_path.read_bytes()).hexdigest() if methodology_path.is_file() else None,
        "status": "FAIL" if findings else "PASS_LOCAL_PRECHECK",
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--base-ref")
    parser.add_argument("--simulate-missing", action="append", default=[])
    parser.add_argument("--simulate-changed-path", action="append", default=[])
    args = parser.parse_args()
    try:
        payload = validate(args)
    except Exception as exc:  # fail closed at the process boundary
        payload = {"checked_artifacts": 0, "dynamic_assurance": "NOT_EXECUTED", "findings": [{"detail": str(exc), "path": "", "rule_id": "RCCAD-VALIDATOR-ERROR"}], "fitness_results": {}, "methodology_sha256": None, "status": "FAIL"}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "PASS_LOCAL_PRECHECK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
