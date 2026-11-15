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

RUNTIME_EVIDENCE = (
    ("OCOR-DEV-0005", "reports/evidence/G0/MANIFEST.json"),
    ("OCOR-DEV-0049", "reports/evidence/G4/MANIFEST.json"),
    ("OCOR-DEV-0050", "reports/evidence/G5/MANIFEST.json"),
    ("OCOR-DEV-0082", "reports/evidence/G2/MANIFEST.json"),
)


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
        [python, "-m", "pytest", "reports/tests", "-m", "not requires_live_stack", "-q"]
    )
    return commands


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args(list(argv) if argv is not None else None)
    commands = gate_commands(str(args.python), str(args.base_ref), str(args.branch))
    return execute_commands(commands, _subprocess_runner)


if __name__ == "__main__":
    raise SystemExit(main())
