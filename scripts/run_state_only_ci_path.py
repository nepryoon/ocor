#!/usr/bin/env python3
"""Run the state-only CI gates. This path never starts the real stack.

The commands are the recorded ``state_sync_local_gates`` kinds, replayed with
the CI interpreter instead of a worktree-absolute path, plus the non-stack
suite under ``reports/tests``. Live-stack tests are excluded by the
``requires_live_stack`` marker applied in ``reports/tests/conftest.py``.
The marker is mechanical: the file list is not written here.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

RUNTIME_EVIDENCE = (
    ("OCOR-DEV-0005", "reports/evidence/G0/MANIFEST.json"),
    ("OCOR-DEV-0049", "reports/evidence/G4/MANIFEST.json"),
    ("OCOR-DEV-0050", "reports/evidence/G5/MANIFEST.json"),
    ("OCOR-DEV-0082", "reports/evidence/G2/MANIFEST.json"),
)
SCRIPT_PATHS = (
    "reports/tests/test_schema_conformance.py",
    "reports/tests/test_v12_approval_readiness.py",
    "reports/tests/test_v12_candidate.py",
    "reports/tests/test_v12_release_gate.py",
    "reports/tests/test_v12_semantics.py",
)
TRACKED_JSON = (
    "reports/tests/conformance_results.json",
    "reports/tests/v12_approval_readiness_results.json",
    "reports/tests/v12_conformance_results.json",
    "reports/tests/v12_release_gate_results.json",
    "reports/tests/v12_semantic_results.json",
)
KNOWN_SCHEMA_TOTAL = "TOTAL 98 PASS 97 FAIL 1"
KNOWN_SCHEMA_FAIL = (
    "FAIL urn:ocor:schema:action-type-contract:1.0 — negativo semantico: "
    "CANONICAL_COMMIT R1 senza Human Gate [ACCEPT]"
)
KNOWN_SCHEMA_RESULTS = "RESULTS reports/tests/conformance_results.json"
BASE_REF_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|origin/main)$")
BRANCH_PATTERN = re.compile(
    r"^(?:task/OCOR-DEV-[0-9]{4}-[a-z0-9][a-z0-9-]*|"
    r"governed/[a-z0-9][a-z0-9._/-]*)$"
)
EXPECTED_SCHEMA_PASS_LINES: tuple[str, ...] = (
    "PASS urn:ocor:schema:signed-canonical-ir:1.0 — baseline positivo [ACCEPT]",
    "PASS urn:ocor:schema:signed-canonical-ir:1.0 — digest malformato [REJECT]",
    "PASS urn:ocor:schema:canonical-ingestion-envelope:1.1 — positivo "
    "ingest_mode=BATCH [ACCEPT]",
    "PASS urn:ocor:schema:canonical-ingestion-envelope:1.1 — positivo "
    "ingest_mode=STREAM [ACCEPT]",
    "PASS urn:ocor:schema:canonical-ingestion-envelope:1.1 — positivo ingest_mode=CDC "
    "[ACCEPT]",
    "PASS urn:ocor:schema:canonical-ingestion-envelope:1.1 — negativo ramo BATCH: "
    "transport STREAM [REJECT]",
    "PASS urn:ocor:schema:canonical-ingestion-envelope:1.1 — negativo ramo STREAM: "
    "transport BATCH [REJECT]",
    "PASS urn:ocor:schema:canonical-ingestion-envelope:1.1 — negativo ramo ingest CDC: "
    "semantic_class non CDC_CHANGE [REJECT]",
    "PASS urn:ocor:schema:canonical-ingestion-envelope:1.1 — negativo ramo ingest CDC: "
    "transport non CDC [REJECT]",
    "PASS urn:ocor:schema:canonical-ingestion-envelope:1.1 — negativo ramo semantic "
    "CDC_CHANGE: ingest non CDC [REJECT]",
    "PASS urn:ocor:schema:canonical-ingestion-envelope:1.1 — positivo oneOf "
    "effective_time.to='2026-08-30T10:00:00Z' [ACCEPT]",
    "PASS urn:ocor:schema:canonical-ingestion-envelope:1.1 — positivo oneOf "
    "effective_time.to=None [ACCEPT]",
    "PASS urn:ocor:schema:canonical-ingestion-envelope:1.1 — negativo oneOf "
    "effective_time.to [REJECT]",
    "PASS urn:ocor:schema:canonical-ingestion-envelope:1.1 — positivo oneOf "
    "causation_id='11111111-1111-4111-8111-111111111111' [ACCEPT]",
    "PASS urn:ocor:schema:canonical-ingestion-envelope:1.1 — positivo oneOf "
    "causation_id=None [ACCEPT]",
    "PASS urn:ocor:schema:canonical-ingestion-envelope:1.1 — negativo oneOf "
    "causation_id [REJECT]",
    "PASS urn:ocor:schema:canonical-ingestion-envelope:1.1 — positivo oneOf "
    "before_digest='sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    "aaaa' [ACCEPT]",
    "PASS urn:ocor:schema:canonical-ingestion-envelope:1.1 — positivo oneOf "
    "before_digest=None [ACCEPT]",
    "PASS urn:ocor:schema:canonical-ingestion-envelope:1.1 — negativo oneOf "
    "before_digest [REJECT]",
    "PASS urn:ocor:schema:canonical-ingestion-envelope:1.1 — positivo oneOf "
    "after_digest='sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    "aaa' [ACCEPT]",
    "PASS urn:ocor:schema:canonical-ingestion-envelope:1.1 — positivo oneOf "
    "after_digest=None [ACCEPT]",
    "PASS urn:ocor:schema:canonical-ingestion-envelope:1.1 — negativo oneOf "
    "after_digest [REJECT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — positivo ramo retry_safe=false "
    "[ACCEPT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — negativo ramo retry_safe=false "
    "[REJECT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — positivo ramo HIGH/CRITICAL [ACCEPT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — negativo ramo HIGH/CRITICAL quorum "
    "[REJECT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — positivo ramo "
    "EXECUTE_APPROVED_ACTION (vincoli 1) [ACCEPT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — positivo ramo "
    "EXECUTE_APPROVED_ACTION (vincoli 2) [ACCEPT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — negativo EXECUTE: tier mancante "
    "[REJECT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — negativo EXECUTE: approval NONE "
    "[REJECT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — negativo EXECUTE: key_required false "
    "[REJECT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — negativo EXECUTE: EXECUTION_UNKNOWN "
    "mancante [REJECT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — positivo ramo DUAL_CONTROL [ACCEPT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — negativo ramo DUAL_CONTROL [REJECT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — positivo ramo compensation "
    "HUMAN_AUTHORIZED [ACCEPT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — negativo ramo compensation "
    "HUMAN_AUTHORIZED [REJECT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — positivo ramo HUMAN_GATE [ACCEPT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — negativo ramo HUMAN_GATE [REJECT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — positivo ramo PROPOSE_ACTION "
    "[ACCEPT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — negativo ramo PROPOSE_ACTION "
    "[REJECT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — positivo ramo SIMULATE [ACCEPT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — negativo ramo SIMULATE [REJECT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — positivo ramo ANALYZE [ACCEPT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — negativo ramo ANALYZE [REJECT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — positivo ramo READ_ONLY [ACCEPT]",
    "PASS urn:ocor:schema:mcp-tool-contract:1.1 — negativo ramo READ_ONLY con execute "
    "[REJECT]",
    "PASS urn:ocor:schema:action-type-contract:1.0 — positivo ramo target "
    "CANONICAL_COMMIT [ACCEPT]",
    "PASS urn:ocor:schema:action-type-contract:1.0 — positivo ramo produced "
    "CanonicalAssertion [ACCEPT]",
    "PASS urn:ocor:schema:action-type-contract:1.0 — negativo canonical: binding "
    "assente [REJECT]",
    "PASS urn:ocor:schema:action-type-contract:1.0 — negativo canonical: effect errato "
    "[REJECT]",
    "PASS urn:ocor:schema:action-type-contract:1.0 — negativo canonical: "
    "accepted_from_claim false [REJECT]",
    "PASS urn:ocor:schema:action-type-contract:1.0 — positivo ramo target "
    "EXTERNAL_ADAPTER [ACCEPT]",
    "PASS urn:ocor:schema:action-type-contract:1.0 — negativo external con canonical "
    "binding [REJECT]",
    "PASS urn:ocor:schema:action-type-contract:1.0 — positivo ramo R3_HIGH_IMPACT "
    "[ACCEPT]",
    "PASS urn:ocor:schema:action-type-contract:1.0 — negativo ramo R3_HIGH_IMPACT "
    "[REJECT]",
    "PASS urn:ocor:schema:action-type-contract:1.0 — positivo ramo R2_CONTROLLED "
    "[ACCEPT]",
    "PASS urn:ocor:schema:action-type-contract:1.0 — negativo ramo R2_CONTROLLED "
    "[REJECT]",
    "PASS urn:ocor:schema:action-type-contract:1.0 — positivo ramo compensation "
    "HUMAN_AUTHORIZED [ACCEPT]",
    "PASS urn:ocor:schema:action-type-contract:1.0 — negativo ramo compensation "
    "HUMAN_AUTHORIZED [REJECT]",
    "PASS urn:ocor:schema:action-type-contract:1.0 — positivo ramo IRREVERSIBLE "
    "[ACCEPT]",
    "PASS urn:ocor:schema:action-type-contract:1.0 — negativo ramo IRREVERSIBLE risk "
    "R2 [REJECT]",
    "PASS urn:ocor:schema:action-type-contract:1.0 — positivo ramo retry_safe=false "
    "annidato [ACCEPT]",
    "PASS urn:ocor:schema:action-type-contract:1.0 — positivo ramo retry_safe=false "
    "root [ACCEPT]",
    "PASS urn:ocor:schema:action-type-contract:1.0 — negativo retry_safe=false "
    "max_attempts [REJECT]",
    "PASS urn:ocor:schema:action-type-contract:1.0 — negativo retry_safe=false error "
    "code [REJECT]",
    "PASS urn:ocor:schema:event-subscription-contract:1.0 — baseline positivo [ACCEPT]",
    "PASS urn:ocor:schema:event-subscription-contract:1.0 — negativo exactly once "
    "vietato [REJECT]",
    "PASS urn:ocor:schema:event-subscription-contract:1.0 — negativo cursor non opaco "
    "[REJECT]",
    "PASS urn:ocor:schema:event-subscription-contract:1.0 — negativo predicate "
    "arbitrario [REJECT]",
    "PASS urn:ocor:schema:event-subscription-contract:1.0 — negativo marking non "
    "propagato [REJECT]",
    "PASS OpenAPI 1.1.0 — positivo request GetObjectRequest [ACCEPT]",
    "PASS OpenAPI 1.1.0 — negativo required request GetObjectRequest [REJECT]",
    "PASS OpenAPI 1.1.0 — positivo request ObjectSetRequest [ACCEPT]",
    "PASS OpenAPI 1.1.0 — negativo required request ObjectSetRequest [REJECT]",
    "PASS OpenAPI 1.1.0 — positivo request SearchRequest [ACCEPT]",
    "PASS OpenAPI 1.1.0 — negativo required request SearchRequest [REJECT]",
    "PASS OpenAPI 1.1.0 — positivo request TraverseRequest [ACCEPT]",
    "PASS OpenAPI 1.1.0 — negativo required request TraverseRequest [REJECT]",
    "PASS OpenAPI 1.1.0 — positivo request ExplainRequest [ACCEPT]",
    "PASS OpenAPI 1.1.0 — negativo required request ExplainRequest [REJECT]",
    "PASS OpenAPI 1.1.0 — positivo request ProvenanceRequest [ACCEPT]",
    "PASS OpenAPI 1.1.0 — negativo required request ProvenanceRequest [REJECT]",
    "PASS OpenAPI 1.1.0 — positivo ramo Consistency AT_LEAST_COMMIT [ACCEPT]",
    "PASS OpenAPI 1.1.0 — positivo ramo Consistency EXACT_AT_COMMIT [ACCEPT]",
    "PASS OpenAPI 1.1.0 — negativo ramo Consistency senza required_commit [REJECT]",
    "PASS OpenAPI 1.1.0 — positivo Consistency BEST_AVAILABLE senza commit [ACCEPT]",
    "PASS OpenAPI 1.1.0 — positivo ramo Problem version-sensitive [ACCEPT]",
    "PASS OpenAPI 1.1.0 — negativo ramo Problem version-sensitive [REJECT]",
    "PASS OpenAPI 1.1.0 — positivo ramo Problem CAPABILITY_DEFERRED [ACCEPT]",
    "PASS OpenAPI 1.1.0 — negativo ramo Problem CAPABILITY_DEFERRED [REJECT]",
    "PASS OpenAPI 1.1.0 — positivo oneOf TemporalInterval.to='2026-08-30T10:00:00Z' "
    "[ACCEPT]",
    "PASS OpenAPI 1.1.0 — positivo oneOf TemporalInterval.to=None [ACCEPT]",
    "PASS OpenAPI 1.1.0 — negativo oneOf TemporalInterval.to [REJECT]",
    "PASS OpenAPI 1.1.0 — positivo oneOf "
    "EpistemicStatus.accepting_decision_ref='urn:ocor:test:decision' [ACCEPT]",
    "PASS OpenAPI 1.1.0 — positivo oneOf EpistemicStatus.accepting_decision_ref=None "
    "[ACCEPT]",
    "PASS OpenAPI 1.1.0 — negativo oneOf EpistemicStatus.accepting_decision_ref "
    "[REJECT]",
    "PASS suite — conteggio if/then estratti "
    "[{'urn:ocor:schema:signed-canonical-ir:1.0': 0, "
    "'urn:ocor:schema:canonical-ingestion-envelope:1.1': 4, "
    "'urn:ocor:schema:mcp-tool-contract:1.1': 11, "
    "'urn:ocor:schema:action-type-contract:1.0': 9, "
    "'urn:ocor:schema:event-subscription-contract:1.0': 0, 'OpenAPI 1.1.0': 3}]",
)
ScriptRunner = Callable[[list[str]], subprocess.CompletedProcess[bytes]]


def gate_commands(python: str, base_ref: str, branch: str) -> list[list[str]]:
    """Return the fast-path commands in state-sync gate order."""
    commands = [
        [python, "scripts/validate_evidence_input_drift.py"],
        [python, "scripts/verify.py", "--json"],
        ["sha256sum", "-c", "inputs/normative/SHA256SUMS"],
        [python, "scripts/validate_language_policy.py"],
        [python, "-m", "mypy"],
        [
            python,
            "scripts/validate_ocor_development_plan.py",
            "--authorized-extension",
            "--base-ref",
            base_ref,
        ],
        [python, "scripts/validate_rccad.py", "--base-ref", base_ref],
        ["ruff", "check", "."],
        [
            python,
            "scripts/validate_ocor_change_scope.py",
            "--base",
            base_ref,
            "--head",
            "HEAD",
            "--branch",
            branch,
        ],
        [
            python,
            "scripts/validate_decision_request_format.py",
            "--base",
            base_ref,
            "--head",
            "HEAD",
        ],
    ]
    for task, manifest in RUNTIME_EVIDENCE:
        commands.append(
            [
                python,
                "scripts/validate_runtime_evidence.py",
                "--task",
                task,
                "--non-skipped",
                "--manifest",
                manifest,
            ]
        )
    commands.append(
        [
            python,
            "-m",
            "pytest",
            "reports/tests",
            "-m",
            "not requires_live_stack",
            *[f"--ignore={path}" for path in SCRIPT_PATHS],
            "-q",
        ]
    )
    for path in SCRIPT_PATHS:
        commands.append([python, path])
    return commands


def ref_is_data(value: str, pattern: re.Pattern[str]) -> bool:
    """Return whether value is one complete governed token and nothing else."""
    return pattern.fullmatch(value) is not None


def schema_report_accepted(stdout: str) -> bool:
    """Accept only the known schema report, case by case.

    A PASS line is accepted only when it is one frozen case identity and it
    appears once, in the script order. Replacing a missing case with a
    duplicate PASS line leaves 97 PASS lines and 96 identities, and is
    refused. The one known FAIL line stays the sole authorized exception.
    The schema script process status is not an acceptance signal.
    """
    passes: list[str] = []
    fails: list[str] = []
    totals: list[str] = []
    results: list[str] = []
    for line in stdout.splitlines():
        if line.startswith("PASS "):
            passes.append(line)
        elif line.startswith("FAIL"):
            fails.append(line)
        elif line == KNOWN_SCHEMA_TOTAL:
            totals.append(line)
        elif line == KNOWN_SCHEMA_RESULTS:
            results.append(line)
        else:
            return False
    return (
        passes == list(EXPECTED_SCHEMA_PASS_LINES)
        and fails == [KNOWN_SCHEMA_FAIL]
        and totals == [KNOWN_SCHEMA_TOTAL]
        and results == [KNOWN_SCHEMA_RESULTS]
    )


def snapshot_tracked_json(root: Path | None = None) -> dict[str, bytes]:
    """Read the bytes of the JSON files the import-exit scripts rewrite."""
    base = Path.cwd() if root is None else root
    return {relative: (base / relative).read_bytes() for relative in TRACKED_JSON}


def restore_tracked_json(photos: dict[str, bytes], root: Path | None = None) -> bool:
    """Write the photographed bytes back and read them again."""
    base = Path.cwd() if root is None else root
    try:
        for relative, payload in photos.items():
            (base / relative).write_bytes(payload)
        for relative, payload in photos.items():
            if (base / relative).read_bytes() != payload:
                return False
    except OSError:
        return False
    return True


def _stdout_text(completed: subprocess.CompletedProcess[bytes]) -> str | None:
    payload = completed.stdout
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, (bytes, bytearray)):
        return None
    try:
        return bytes(payload).decode("utf-8")
    except UnicodeDecodeError:
        return None


def run_tracked_scripts(
    python: str,
    runner: ScriptRunner,
    snapshot: Callable[[], dict[str, bytes]],
    restore: Callable[[dict[str, bytes]], bool],
) -> int:
    """Run the five import-exit scripts and restore the JSON they rewrite.

    Pytest must already have exited 0. The schema script is accepted only by
    its known report. Each of the four v12 scripts is accepted only when its
    process exits 0. The photographed JSON is restored on every path.
    """
    try:
        photos = snapshot()
    except OSError:
        return 1
    code = 0
    try:
        try:
            completed = runner([python, SCRIPT_PATHS[0]])
            stdout = _stdout_text(completed)
            if stdout is None or not schema_report_accepted(stdout):
                code = 1
            else:
                for path in SCRIPT_PATHS[1:]:
                    completed = runner([python, path])
                    status = int(completed.returncode)
                    if status != 0:
                        code = status
                        break
        except OSError:
            code = 1
    finally:
        try:
            restored = bool(restore(photos))
        except OSError:
            restored = False
    if not restored:
        return 1 if code == 0 else code
    return code


def execute_commands(
    commands: Sequence[Sequence[str]],
    runner: Callable[[list[str]], int],
) -> int:
    """Run commands in order and stop at the first non-zero status."""
    for command in commands:
        code = runner(list(command))
        if code != 0:
            return code
    return 0


def _subprocess_runner(command: list[str]) -> int:
    completed = subprocess.run(command, check=False)
    return int(completed.returncode)


def _capturing_runner(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if isinstance(completed.stdout, bytes) and completed.stdout:
        sys.stdout.buffer.write(completed.stdout)
        sys.stdout.buffer.flush()
    if isinstance(completed.stderr, bytes) and completed.stderr:
        sys.stderr.buffer.write(completed.stderr)
        sys.stderr.buffer.flush()
    return completed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args(list(argv) if argv is not None else None)
    base_ref = str(args.base_ref)
    branch = str(args.branch)
    if branch == "main" or not ref_is_data(branch, BRANCH_PATTERN):
        return 1
    if not ref_is_data(base_ref, BASE_REF_PATTERN):
        return 1
    python = str(args.python)
    commands = gate_commands(python, base_ref, branch)
    scripts = [[python, path] for path in SCRIPT_PATHS]
    if commands[-len(scripts) :] != scripts:
        return 1
    code = execute_commands(commands[: -len(scripts)], _subprocess_runner)
    if code != 0:
        return code
    return run_tracked_scripts(
        python,
        _capturing_runner,
        lambda: snapshot_tracked_json(),
        lambda photos: restore_tracked_json(photos),
    )


if __name__ == "__main__":
    raise SystemExit(main())
