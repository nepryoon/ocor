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


def schema_report_accepted(stdout: str) -> bool:
    """Return whether stdout is the one known schema conformance report.

    The schema script's process status is not an acceptance signal. Only this
    report is accepted: one exact total line, 97 lines that start with
    ``PASS ``, and one exact ``FAIL`` line.
    """
    lines = stdout.splitlines()
    totals = [line for line in lines if line == KNOWN_SCHEMA_TOTAL]
    passes = [line for line in lines if line.startswith("PASS ")]
    fails = [line for line in lines if line.startswith("FAIL")]
    return len(totals) == 1 and len(passes) == 97 and fails == [KNOWN_SCHEMA_FAIL]


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
    python = str(args.python)
    commands = gate_commands(python, str(args.base_ref), str(args.branch))
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
