#!/usr/bin/env python3
"""Alignment invariants between documents, plan, state, evidence and CI.

Two families of checks, each with an identifier, a title and a PASS/FAIL outcome:

* snapshot checks (S01-S10) read one tree, either a directory (``--root``) or a
  git revision (``--repo`` with ``--head-ref``), and compare artefacts that must
  agree with each other;
* difference checks (D01-D07) compare ``--base-ref`` with ``--head-ref`` and
  reject changes that the project rules forbid whatever their purpose.

The tree under examination is read as data: nothing from it is imported or
executed, and git revisions are read through ``git show`` without a checkout, so
that the validator of one revision can judge another revision.

A baseline (``--baseline`` or ``--baseline-ref``) names the findings already
registered and the mode of every check. ``BLOCKING`` checks fail the run on any
finding absent from the baseline; ``ADVISORY`` checks only report. Without a
baseline D01, D02 and D03 are blocking and every other check is advisory.

The validator never edits a file of the tree, never turns a finding into PASS
and makes no statement about requirements, gates or claims: it only compares.
"""

from __future__ import annotations

import argparse
import ast
import csv
import io
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = "ocor-alignment-invariants/1"
BASELINE_SCHEMA = "ocor-alignment-baseline/1"
BASELINE_PATH = "reports/development/ALIGNMENT_BASELINE.json"
BLOCKING, ADVISORY = "BLOCKING", "ADVISORY"
DEFAULT_BLOCKING = frozenset({"D01", "D02", "D03"})

BACKLOG = "docs/development_plan/OCOR_IMPLEMENTATION_BACKLOG.json"
PLAN_MD = "docs/development_plan/OCOR_AI_FIRST_DEVELOPMENT_PLAN.md"
TRACE_CSV = "docs/development_plan/OCOR_TRACEABILITY_PLAN.csv"
RUNNER_CONFIG = "docs/development_plan/OCOR_DELIVERY_RUNNER_CONFIG.json"
REGISTER = "ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md"
MATRIX = "reports/traceability/OCOR_IRB_ADD_LLD_v1.1_Matrix.json"
STATE = "reports/development/EXECUTION_STATE.json"
NCR_REGISTER = "reports/development/NORMATIVE_CONFORMANCE_REGISTER.json"
TERMINAL_REPORT = "reports/development/TERMINAL_BLOCKED_REPORT.json"
METHOD_COMPLIANCE = "reports/development/METHOD_COMPLIANCE.json"
INFRASTRUCTURE_STATE = "reports/development/INFRASTRUCTURE_STATE.json"
SERVICES_LOCK = "infra/services.lock.json"
METHODOLOGY = "docs/development_methodology/methodology.json"
RUNTIME_PYPROJECT = "ocor-runtime/pyproject.toml"
RUNTIME_SOURCE = "ocor-runtime/src"
WORKFLOWS = ".github/workflows"
DOSSIER = "ocor-runtime/docs/governance_dossier/"
LINKED_DOCUMENTS = ("README.md", "AGENTS.md", "PLANS.md")
CLAIM_FILES = (STATE, NCR_REGISTER, TERMINAL_REPORT)
EXPECTED_CLAIMS: dict[str, object] = {
    "E1": 0,
    "E2": 0,
    "PoC_GO": "NO-GO",
    "Production_readiness": "NO-GO",
    "Verified": 0,
    "runtime_conformance": "NOT_ESTABLISHED",
}
CONTROL_SURFACES = (
    ".github/",
    ".githooks/",
    "scripts/validate_",
    "scripts/verify.py",
    "scripts/run_qualifying_campaign.py",
    BASELINE_PATH,
)

REQUIREMENT_ROW = re.compile(r"^\|\s*`?((?:BR|FR|NFR)-\d{3})`?\s*\|")
TASK_ID = re.compile(r"OCOR-DEV-\d{4}")
SHA40 = re.compile(r"[0-9a-f]{40}")
USES_LINE = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)")
FLOATING_RUNNER = re.compile(r"^\s*runs-on:\s*[\"']?([A-Za-z0-9._-]*-latest)\b")
MARKDOWN_LINK = re.compile(r"\]\(([^)\s]+)\)")
REQUIREMENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
OUT_OF_REPO_TOOL = re.compile(r"(?:~|/home/[A-Za-z0-9._-]+)/\.ocor-codex/[A-Za-z0-9._/-]+\.(?:py|sh)\b")
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
EMAIL_EXEMPT = re.compile(r"(?i)^git@|noreply|@example\.|@users\.")
HOME_PATH = re.compile(r"/home/([A-Za-z_][A-Za-z0-9_-]*)/")
HOME_EXEMPT = frozenset({"runner", "user", "ocor", "app", "node", "nonroot"})
# Import name -> distribution name, where they differ.
DISTRIBUTIONS = {"yaml": "pyyaml", "confluent_kafka": "confluent-kafka", "grpc": "grpcio", "google": "protobuf"}


class ValidatorError(RuntimeError):
    """The validator could not read what it needs: the run is NOT_EXECUTED."""


@dataclass(frozen=True)
class Finding:
    key: str
    detail: str


@dataclass
class Check:
    id: str
    title: str
    findings: list[Finding] = field(default_factory=list)
    not_executed: str = ""

    def add(self, key: str, detail: str) -> None:
        self.findings.append(Finding(f"{self.id}:{key}", detail))


class Tree:
    """Read-only view of one revision of the repository."""

    def read(self, path: str) -> str | None:
        raise NotImplementedError

    def exists(self, path: str) -> bool:
        raise NotImplementedError

    def files(self, prefix: str, suffix: str) -> list[str]:
        raise NotImplementedError

    def json(self, path: str) -> Any:
        text = self.read(path)
        if text is None:
            raise ValidatorError(f"{path} is absent")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValidatorError(f"{path} is not valid JSON: {exc}") from exc


class DirectoryTree(Tree):
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def read(self, path: str) -> str | None:
        target = self.root / path
        if not target.is_file():
            return None
        return target.read_text(encoding="utf-8", errors="replace")

    def exists(self, path: str) -> bool:
        return (self.root / path).exists()

    def files(self, prefix: str, suffix: str) -> list[str]:
        base = self.root / prefix
        if not base.is_dir():
            return []
        found = (item.relative_to(self.root).as_posix() for item in base.rglob(f"*{suffix}") if item.is_file())
        return sorted(found)


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


class GitTree(Tree):
    def __init__(self, repo: Path, ref: str) -> None:
        self.repo = repo
        resolved = run_git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
        if resolved.returncode:
            raise ValidatorError(f"revision {ref} is not available in {repo}")
        self.ref = resolved.stdout.strip()

    def read(self, path: str) -> str | None:
        shown = run_git(self.repo, "show", f"{self.ref}:{path}")
        return None if shown.returncode else shown.stdout

    def exists(self, path: str) -> bool:
        return run_git(self.repo, "cat-file", "-e", f"{self.ref}:{path.rstrip('/')}").returncode == 0

    def files(self, prefix: str, suffix: str) -> list[str]:
        listed = run_git(self.repo, "ls-tree", "-r", "--name-only", self.ref, "--", prefix)
        if listed.returncode:
            return []
        return sorted(line for line in listed.stdout.splitlines() if line.endswith(suffix))


# --------------------------------------------------------------------------- snapshot checks


def check_plan_parity(tree: Tree) -> Check:
    check = Check("S01", "development plan text agrees with the backlog")
    backlog = tree.json(BACKLOG)
    plan = tree.read(PLAN_MD)
    if plan is None:
        raise ValidatorError(f"{PLAN_MD} is absent")
    tasks = backlog["tasks"]
    stated = re.search(r"(\d+)-task backlog", plan)
    if stated is None or int(stated.group(1)) != len(tasks):
        check.add("task-count", f"plan states {stated.group(1) if stated else 'no'} tasks, backlog has {len(tasks)}")
    waves = re.search(r"machine DAG has (\d+) waves", plan)
    actual_waves = backlog["graph_analysis"]["parallel_waves"]
    if waves is None or int(waves.group(1)) != actual_waves:
        check.add("waves", f"plan states {waves.group(1) if waves else 'no'} waves, backlog has {actual_waves}")
    for line in plan.splitlines():
        row = re.match(r"^\|\s*(G[0-7])\s*\|([^|]*)\|", line)
        if row is None:
            continue
        gate = row.group(1)
        listed = set(TASK_ID.findall(row.group(2)))
        required = set(backlog["gates"][gate]["required_tasks"])
        if listed != required:
            check.add(f"gate:{gate}", f"plan lists {len(listed)} tasks for {gate}, backlog requires {len(required)}")
    return check


def register_requirements(tree: Tree) -> set[str]:
    text = tree.read(REGISTER)
    if text is None:
        raise ValidatorError(f"{REGISTER} is absent")
    return {match.group(1) for line in text.splitlines() if (match := REQUIREMENT_ROW.match(line))}


def check_requirement_universe(tree: Tree) -> Check:
    check = Check("S02", "register, matrix, traceability plan and backlog name the same requirements")
    register = register_requirements(tree)
    matrix = {row["requirement_id"] for row in tree.json(MATRIX)["rows"]}
    trace_text = tree.read(TRACE_CSV)
    if trace_text is None:
        raise ValidatorError(f"{TRACE_CSV} is absent")
    trace = {row["requirement_id"] for row in csv.DictReader(io.StringIO(trace_text))}
    backlog = {item for task in tree.json(BACKLOG)["tasks"] for item in task["requirement_ids"]}
    for name, other in (("matrix", matrix), ("traceability-plan", trace), ("backlog", backlog)):
        if other != register:
            missing, extra = sorted(register - other), sorted(other - register)
            check.add(name, f"missing {missing[:5]} ({len(missing)}), not in the register {extra[:5]} ({len(extra)})")
    return check


def check_state_satellites(tree: Tree) -> Check:
    check = Check("S03", "satellite state files agree with the execution state and the locks")
    state = tree.json(STATE)
    locked = {str(item.get("id")) for item in tree.json(SERVICES_LOCK)["services"]}
    ready = {str(item) for item in tree.json(INFRASTRUCTURE_STATE).get("services_ready", [])}
    if ready != locked:
        check.add(
            "infrastructure-services",
            f"INFRASTRUCTURE_STATE lists {sorted(ready - locked)} not in the lock and lacks {sorted(locked - ready)}",
        )
    remediation = {key.replace("_", "-"): value for key, value in state.get("remediation_status", {}).items()}
    for deviation in tree.json(METHOD_COMPLIANCE).get("deviations", []):
        identifier = str(deviation.get("id", ""))
        status = str(deviation.get("status", ""))
        closed = str((remediation.get(identifier) or {}).get("status", ""))
        if status.startswith("OPEN") and re.search(r"RESOLVED|CLOSED", closed):
            check.add(f"method-compliance:{identifier}", f"deviation is {status}, execution state records {closed}")
    return check


def check_runner_config(tree: Tree) -> Check:
    check = Check("S04", "delivery runner configuration agrees with the recorded server-side protection")
    config = tree.json(RUNNER_CONFIG)
    state = tree.json(STATE)
    required = set(state.get("latest_ci_evidence", {}).get("required_checks", []))
    declared = set(config.get("mandatory_check_contexts", []))
    if required and declared != required:
        check.add("mandatory-check-contexts", f"runner declares {len(declared)} contexts, state records {len(required)}")
    protection = str(config.get("compensating_protection", {}).get("status", ""))
    server_side = any(
        isinstance(item, dict)
        and item.get("id") == "GITHUB-BRANCH-PROTECTION-001"
        and str(item.get("status", "")).startswith("RESOLVED")
        for item in state.get("blockers", [])
    )
    if server_side and protection == "EXTERNAL_CONTROL_PENDING":
        check.add("compensating-protection", "runner says EXTERNAL_CONTROL_PENDING, state records the ruleset as resolved")
    return check


def workflow_findings(path: str, lines: Iterable[str]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for line in lines:
        uses = USES_LINE.match(line)
        if uses is not None:
            reference = uses.group(1).strip("\"'")
            if not reference.startswith("./") and not reference.startswith("docker://"):
                revision = reference.rsplit("@", 1)[1] if "@" in reference else ""
                if SHA40.fullmatch(revision) is None:
                    found.append((f"{path}:{reference}", "action is not pinned to a full commit SHA"))
        runner = FLOATING_RUNNER.match(line)
        if runner is not None:
            found.append((f"{path}:runs-on:{runner.group(1)}", "runner label floats with the hosted image"))
    return found


def check_workflow_pins(tree: Tree) -> Check:
    check = Check("S05", "workflows pin actions to commit SHAs and runners to fixed images")
    for path in tree.files(WORKFLOWS, ".yml") + tree.files(WORKFLOWS, ".yaml"):
        text = tree.read(path) or ""
        for key, detail in dict(workflow_findings(path, text.splitlines())).items():
            check.add(key, detail)
    return check


def runtime_requirements(tree: Tree) -> tuple[list[str], list[str]]:
    text = tree.read(RUNTIME_PYPROJECT)
    if text is None:
        raise ValidatorError(f"{RUNTIME_PYPROJECT} is absent")
    document = tomllib.loads(text)
    project = document.get("project", {})
    runtime = [str(item) for item in project.get("dependencies", [])]
    other = [str(item) for item in document.get("build-system", {}).get("requires", [])]
    for group in project.get("optional-dependencies", {}).values():
        other.extend(str(item) for item in group)
    return runtime, other


def requirement_name(requirement: str) -> str:
    match = REQUIREMENT_NAME.match(requirement.strip())
    return (match.group(0) if match else requirement).lower().replace("_", "-")


def check_dependency_pins(tree: Tree) -> Check:
    check = Check("S06", "runtime project pins every dependency to an exact version")
    runtime, other = runtime_requirements(tree)
    for requirement in runtime + other:
        if "==" not in requirement:
            check.add(requirement_name(requirement), f"constraint is not exact: {requirement}")
    return check


def check_runtime_imports(tree: Tree) -> Check:
    check = Check("S07", "third-party imports of the runtime are declared runtime dependencies")
    runtime, _ = runtime_requirements(tree)
    declared = {requirement_name(item) for item in runtime}
    sources = tree.files(RUNTIME_SOURCE, ".py")
    first_party = {Path(path).relative_to(RUNTIME_SOURCE).parts[0].removesuffix(".py") for path in sources}
    imported: dict[str, str] = {}
    for path in sources:
        try:
            module = ast.parse(tree.read(path) or "")
        except SyntaxError as exc:
            raise ValidatorError(f"{path} does not parse: {exc}") from exc
        for node in ast.walk(module):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for name in names:
                imported.setdefault(name.split(".")[0], path)
    for name, path in sorted(imported.items()):
        if name in sys.stdlib_module_names or name in first_party:
            continue
        distribution = DISTRIBUTIONS.get(name, name.lower().replace("_", "-"))
        if distribution not in declared:
            check.add(name, f"imported in {path}, absent from [project].dependencies")
    return check


def check_document_links(tree: Tree) -> Check:
    check = Check("S08", "orientation documents link to paths that exist")
    for document in LINKED_DOCUMENTS:
        text = tree.read(document)
        if text is None:
            continue
        for target in sorted(set(MARKDOWN_LINK.findall(text))):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
                continue
            path = target.split("#", 1)[0].removeprefix("./")
            if path and not tree.exists(path):
                check.add(f"{document}:{path}", "link target is absent")
    return check


def claims_of(tree: Tree, path: str) -> dict[str, object]:
    if tree.read(path) is None:
        return {}
    claims = tree.json(path).get("claims", {})
    return dict(claims) if isinstance(claims, dict) else {}


def check_fence_parity(tree: Tree) -> Check:
    check = Check("S09", "every state file carries the same fenced claims")
    for path in CLAIM_FILES:
        for name, value in claims_of(tree, path).items():
            if name in EXPECTED_CLAIMS and value != EXPECTED_CLAIMS[name]:
                check.add(f"{path}:{name}", f"value {value!r} differs from the fenced value {EXPECTED_CLAIMS[name]!r}")
    fence = tree.json(METHODOLOGY).get("evidence_fence", {})
    for name in ("E1", "E2"):
        if fence.get(name) != 0:
            check.add(f"{METHODOLOGY}:{name}", f"value {fence.get(name)!r} differs from the fenced value 0")
    return check


def check_register_status(tree: Tree) -> Check:
    check = Check("S10", "conformance register statuses follow the remediation units of the execution state")
    units: dict[str, str] = {}
    for key, value in tree.json(STATE).get("remediation_status", {}).items():
        number = re.match(r"REM[_-](\d{4})", key)
        if number is not None and isinstance(value, dict):
            units[f"OCOR-DEV-REM-{number.group(1)}"] = str(value.get("status", ""))
    lagging = sorted(
        str(entry.get("id"))
        for entry in tree.json(NCR_REGISTER).get("entries", [])
        if entry.get("status") == "IN_REMEDIATION" and "MERGED" in units.get(str(entry.get("remediation_unit")), "")
    )
    if lagging:
        check.add("in-remediation-with-merged-unit", f"{len(lagging)} entries, first {lagging[0]}, last {lagging[-1]}")
    return check


SNAPSHOT_CHECKS: tuple[tuple[str, Callable[[Tree], Check]], ...] = (
    ("S01", check_plan_parity),
    ("S02", check_requirement_universe),
    ("S03", check_state_satellites),
    ("S04", check_runner_config),
    ("S05", check_workflow_pins),
    ("S06", check_dependency_pins),
    ("S07", check_runtime_imports),
    ("S08", check_document_links),
    ("S09", check_fence_parity),
    ("S10", check_register_status),
)

# --------------------------------------------------------------------------- difference checks


@dataclass(frozen=True)
class Difference:
    repo: Path
    base: GitTree
    head: GitTree
    changes: tuple[tuple[str, str], ...]

    def added_lines(self, *paths: str) -> list[tuple[str, str]]:
        shown = run_git(self.repo, "diff", "--no-renames", "--unified=0", self.base.ref, self.head.ref, "--", *paths)
        if shown.returncode:
            raise ValidatorError(shown.stderr.strip() or "git diff failed")
        current, lines = "", []
        for line in shown.stdout.splitlines():
            if line.startswith("+++ "):
                current = line[6:] if line.startswith("+++ b/") else ""
            elif line.startswith("+") and current:
                lines.append((current, line[1:]))
        return lines


def difference(repo: Path, base_ref: str, head_ref: str) -> Difference:
    head = GitTree(repo, head_ref)
    merge_base = run_git(repo, "merge-base", base_ref, head.ref)
    if merge_base.returncode:
        raise ValidatorError(f"no merge base between {base_ref} and {head_ref}")
    base = GitTree(repo, merge_base.stdout.strip())
    listed = run_git(repo, "diff", "--no-renames", "--name-status", base.ref, head.ref)
    if listed.returncode:
        raise ValidatorError(listed.stderr.strip() or "git diff failed")
    changes = tuple((line.split("\t", 1)[0], line.split("\t", 1)[1]) for line in listed.stdout.splitlines() if "\t" in line)
    return Difference(repo, base, head, changes)


def check_immutable_surfaces(diff: Difference) -> Check:
    check = Check("D01", "immutable inputs and approved baselines are untouched")
    for status, path in diff.changes:
        if path.startswith("inputs/"):
            check.add(path, f"change ({status}) under inputs/")
        elif status != "A" and (path.startswith(DOSSIER) or path == "docs/OCOR_LLD_v1.1.md"):
            check.add(path, f"approved baseline file changed ({status})")
    return check


def check_claims_unchanged(diff: Difference) -> Check:
    check = Check("D02", "fenced claims are the same at base and head")
    for path in CLAIM_FILES:
        before, after = claims_of(diff.base, path), claims_of(diff.head, path)
        for name in sorted(set(before) | set(after)):
            if name in before and name in after:
                changed = before[name] != after[name]
            else:
                # A claim that only appears or disappears keeps the fence if its value is the fenced one.
                present = after[name] if name in after else before[name]
                changed = present != EXPECTED_CLAIMS.get(name, present)
            if changed:
                check.add(f"{path}:{name}", f"{before.get(name)!r} at base, {after.get(name)!r} at head")
    before_fence = diff.base.json(METHODOLOGY).get("evidence_fence") if diff.base.read(METHODOLOGY) else None
    after_fence = diff.head.json(METHODOLOGY).get("evidence_fence") if diff.head.read(METHODOLOGY) else None
    if before_fence != after_fence:
        check.add(f"{METHODOLOGY}:evidence_fence", f"{before_fence!r} at base, {after_fence!r} at head")
    return check


def sealed_at_base(diff: Difference, path: str) -> bool:
    record_path = path if path.endswith(".json") else str(Path(path).with_suffix(".json"))
    text = diff.base.read(record_path)
    if text is None:
        return False
    try:
        record = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(record, dict) and str(record.get("status", "")).startswith("SEALED")


def manifest_entries(tree: Tree, path: str) -> set[tuple[str, str, str]]:
    text = tree.read(path)
    if text is None:
        return set()
    try:
        artifacts = json.loads(text).get("artifacts", [])
    except (json.JSONDecodeError, AttributeError):
        return set()
    return {
        (str(item.get("path")), str(item.get("sha256")), str(item.get("task_id")))
        for item in artifacts
        if isinstance(item, dict)
    }


def check_sealed_evidence(diff: Difference) -> Check:
    check = Check("D03", "sealed evidence is append-only")
    for status, path in diff.changes:
        evidence, assurance = path.startswith("reports/evidence/"), path.startswith("reports/assurance/")
        if not (evidence or assurance) or status == "A":
            continue
        if path.endswith("/MANIFEST.json") and status == "M":
            lost = manifest_entries(diff.base, path) - manifest_entries(diff.head, path)
            for entry in sorted(lost)[:20]:
                check.add(f"{path}:{entry[0]}", "manifest entry present at base is absent or altered at head")
        elif status == "D":
            check.add(path, "evidence or assurance file deleted")
        elif sealed_at_base(diff, path):
            check.add(path, f"record sealed at base changed ({status})")
    return check


def check_out_of_repo_tools(diff: Difference) -> Check:
    check = Check("D04", "new evidence cites only tools versioned in the repository")
    for path, line in diff.added_lines("reports/evidence", "reports/assurance"):
        if not path.endswith(".json"):
            continue
        for tool in sorted(set(OUT_OF_REPO_TOOL.findall(line))):
            check.add(f"{path}:{tool}", "command or tool outside the repository")
    return check


def check_personal_data(diff: Difference) -> Check:
    check = Check("D05", "added lines carry no e-mail address and no personal home path")
    seen: set[str] = set()
    for path, line in diff.added_lines():
        kinds = []
        if any(EMAIL_EXEMPT.search(match) is None for match in EMAIL.findall(line)):
            kinds.append("e-mail address")
        if any(user not in HOME_EXEMPT for user in HOME_PATH.findall(line)):
            kinds.append("home path")
        for kind in kinds:
            key = f"{path}:{kind}"
            if key not in seen:
                seen.add(key)
                check.add(key, f"added line contains a personal {kind}")
    return check


def check_workflow_changes(diff: Difference) -> Check:
    check = Check("D06", "workflow lines added by the change keep the pinning rules")
    by_path: dict[str, list[str]] = {}
    for path, line in diff.added_lines(WORKFLOWS):
        by_path.setdefault(path, []).append(line)
    for path, lines in sorted(by_path.items()):
        for key, detail in dict(workflow_findings(path, lines)).items():
            check.add(key, detail)
    return check


def check_control_surfaces(diff: Difference) -> Check:
    check = Check("D07", "changes to control surfaces are listed")
    for status, path in diff.changes:
        if any(path.startswith(prefix) for prefix in CONTROL_SURFACES):
            check.add(path, f"control surface changed ({status})")
    return check


DIFFERENCE_CHECKS: tuple[tuple[str, Callable[[Difference], Check]], ...] = (
    ("D01", check_immutable_surfaces),
    ("D02", check_claims_unchanged),
    ("D03", check_sealed_evidence),
    ("D04", check_out_of_repo_tools),
    ("D05", check_personal_data),
    ("D06", check_workflow_changes),
    ("D07", check_control_surfaces),
)

# --------------------------------------------------------------------------- run and report


def execute(identifier: str, check_function: Callable[[Any], Check], subject: Any) -> Check:
    """Run one check; what it cannot read makes it NOT_EXECUTED, never PASS."""
    try:
        return check_function(subject)
    except (ValidatorError, KeyError, TypeError, ValueError, AttributeError) as exc:
        failed = Check(identifier, check_function.__name__.removeprefix("check_").replace("_", " "))
        failed.not_executed = f"{type(exc).__name__}: {exc}"
        return failed


def load_baseline(text: str | None) -> tuple[dict[str, str], dict[str, str]]:
    if text is None:
        return {}, {}
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidatorError(f"baseline is not valid JSON: {exc}") from exc
    if not isinstance(document, dict) or document.get("schema") != BASELINE_SCHEMA:
        raise ValidatorError("baseline has an unknown schema")
    modes = {str(key): str(value) for key, value in dict(document.get("modes", {})).items()}
    accepted = {str(key): str(value) for key, value in dict(document.get("accepted_findings", {})).items()}
    if any(value not in (BLOCKING, ADVISORY) for value in modes.values()):
        raise ValidatorError("baseline modes must be BLOCKING or ADVISORY")
    return modes, accepted


def report(checks: Sequence[Check], modes: dict[str, str], accepted: dict[str, str], context: dict[str, str]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    blocking_new = advisory_new = baselined = not_executed = 0
    for check in checks:
        mode = modes.get(check.id, BLOCKING if check.id in DEFAULT_BLOCKING else ADVISORY)
        findings = [
            {"baselined": item.key in accepted, "detail": item.detail, "key": item.key, "reference": accepted.get(item.key, "")}
            for item in check.findings
        ]
        new = sum(1 for item in findings if not item["baselined"])
        baselined += len(findings) - new
        if check.not_executed:
            status = "NOT_EXECUTED"
            not_executed += 1
        elif new:
            status = "FAIL"
            blocking_new += new if mode == BLOCKING else 0
            advisory_new += new if mode == ADVISORY else 0
        else:
            status = "BASELINED" if findings else "PASS"
        entries.append(
            {
                "findings": findings,
                "id": check.id,
                "mode": mode,
                "not_executed": check.not_executed,
                "status": status,
                "title": check.title,
            }
        )
    blocked = blocking_new > 0 or any(
        entry["status"] == "NOT_EXECUTED" and entry["mode"] == BLOCKING for entry in entries
    )
    return {
        "checks": entries,
        "context": context,
        "schema": SCHEMA,
        "status": "FAIL" if blocked else "PASS",
        "summary": {
            "advisory_new_findings": advisory_new,
            "baselined_findings": baselined,
            "blocking_new_findings": blocking_new,
            "checks": len(entries),
            "not_executed": not_executed,
        },
    }


def baseline_document(checks: Sequence[Check], commit: str, reference: str) -> dict[str, Any]:
    modes = {check.id: BLOCKING if check.id in DEFAULT_BLOCKING else ADVISORY for check in checks}
    for identifier in ("D01", "D02", "D03", "D04", "D05", "D06", "D07"):
        modes.setdefault(identifier, BLOCKING if identifier in DEFAULT_BLOCKING else ADVISORY)
    return {
        "accepted_findings": {item.key: reference for check in checks for item in check.findings},
        "analysed_commit": commit,
        "modes": dict(sorted(modes.items())),
        "note": (
            "Findings listed here were observed at analysed_commit and are registered, not accepted as correct: "
            "an entry leaves this file when its cause is removed. A mode changes only by a recorded decision."
        ),
        "schema": BASELINE_SCHEMA,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, help="directory to read for the snapshot checks")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="git repository for revision reads (default: cwd)")
    parser.add_argument("--head-ref", help="revision to examine; snapshot checks read it without a checkout")
    parser.add_argument("--base-ref", help="revision to compare with; enables the difference checks")
    parser.add_argument("--baseline", type=Path, help="baseline file")
    parser.add_argument("--baseline-ref", help=f"revision whose {BASELINE_PATH} is the baseline")
    parser.add_argument("--write-baseline", type=Path, help="write a baseline with the current findings and exit")
    parser.add_argument("--reference", default="UNREGISTERED", help="reference recorded by --write-baseline")
    args = parser.parse_args(argv)
    try:
        if args.root is None and args.head_ref is None:
            parser.error("give --root or --head-ref")
        if args.base_ref and not args.head_ref:
            parser.error("--base-ref needs --head-ref")
        tree: Tree = GitTree(args.repo, args.head_ref) if args.head_ref else DirectoryTree(args.root)
        checks = [execute(identifier, function, tree) for identifier, function in SNAPSHOT_CHECKS]
        context = {"head": tree.ref if isinstance(tree, GitTree) else str(args.root)}
        if args.base_ref:
            diff = difference(args.repo, args.base_ref, args.head_ref)
            context["base"] = diff.base.ref
            checks.extend(execute(identifier, function, diff) for identifier, function in DIFFERENCE_CHECKS)
        if args.write_baseline is not None:
            document = baseline_document(checks, context["head"], args.reference)
            args.write_baseline.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"baseline written: {len(document['accepted_findings'])} finding(s)")
            return 0
        baseline_text: str | None = None
        if args.baseline is not None:
            baseline_text = args.baseline.read_text(encoding="utf-8")
        elif args.baseline_ref:
            baseline_text = GitTree(args.repo, args.baseline_ref).read(BASELINE_PATH)
        modes, accepted = load_baseline(baseline_text)
        result = report(checks, modes, accepted, context)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1 if result["status"] == "FAIL" else 0
    except (ValidatorError, OSError) as exc:
        print(json.dumps({"error": str(exc), "schema": SCHEMA, "status": "NOT_EXECUTED"}, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
