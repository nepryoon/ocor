#!/usr/bin/env python3
"""RED/GREEN tests for the state-only CI route of CI-STATO-RAPIDA.

The classifier decides whether a pull request may skip the real-stack
regression parts. These tests do not start that stack.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CLASSIFIER = ROOT / "scripts" / "classify_pull_request_ci_route.py"
RUNNER = ROOT / "scripts" / "run_state_only_ci_path.py"
WORKFLOWS = (
    ROOT / ".github/workflows/ocor-rccad.yml",
    ROOT / ".github/workflows/ocor-delivery-activation.yml",
    ROOT / ".github/workflows/ocor-validation-closure.yml",
)
STATE_FILES = (
    "reports/development/EXECUTION_STATE.json",
    "reports/development/MODEL_HANDOFF.json",
    "reports/development/ITERATION_LOG.md",
    "reports/development/TERMINAL_BLOCKED_REPORT.json",
)


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"missing module {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "OCOR Test",
            "GIT_AUTHOR_EMAIL": "ocor-test@example.com",
            "GIT_COMMITTER_NAME": "OCOR Test",
            "GIT_COMMITTER_EMAIL": "ocor-test@example.com",
        }
    )
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
        env=env,
    )


def _init_repo(repo: Path) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "ocor-test@example.com")
    _git(repo, "config", "user.name", "OCOR Test")
    for relative in STATE_FILES:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative + "\n", encoding="utf-8")
    decision = repo / "reports/development/decision_requests"
    decision.mkdir(parents=True)
    (decision / "KEEP.md").write_text("# Keep\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _classify(repo: Path, base: str, head: str) -> dict[str, Any]:
    proc = subprocess.run(
        [
            "python3",
            str(CLASSIFIER),
            "--root",
            str(repo),
            "--base",
            base,
            "--head",
            head,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


def _run_blocks(text: str) -> list[str]:
    lines = text.splitlines()
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped == "run: |" or stripped.startswith("run: >"):
            block = [lines[index]]
            index += 1
            while index < len(lines) and (
                lines[index].startswith("          ") or lines[index].strip() == ""
            ):
                if lines[index].startswith("      - "):
                    break
                block.append(lines[index])
                index += 1
            blocks.append("\n".join(block).rstrip() + "\n")
            continue
        if stripped.startswith("run:") and not stripped.endswith("|"):
            blocks.append(lines[index].rstrip() + "\n")
        index += 1
    return blocks


class ClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load(CLASSIFIER, "classify_pull_request_ci_route")

    def _entry(self, status: str, path: str, **kwargs: Any) -> Any:
        return self.module.DiffEntry(status=status, path=path, **kwargs)

    def test_state_files_and_one_decision_request_are_state_only(self) -> None:
        module = self.module
        for path in STATE_FILES:
            for status in ("A", "M"):
                route, reason = module.classify_entries([self._entry(status, path)])
                self.assertEqual(route, "state_only", path)
                self.assertEqual(reason, "state_files")
        route, reason = module.classify_entries(
            [self._entry("M", path) for path in STATE_FILES]
        )
        self.assertEqual((route, reason), ("state_only", "state_files"))
        decision = "reports/development/decision_requests/REM-EXAMPLE.md"
        for status in ("A", "M"):
            route, reason = module.classify_entries([self._entry(status, decision)])
            self.assertEqual((route, reason), ("state_only", "single_decision_request"))

    def test_order_does_not_change_the_route(self) -> None:
        entries = [self._entry("M", path) for path in reversed(STATE_FILES)]
        self.assertEqual(
            self.module.classify_entries(entries),
            self.module.classify_entries(list(reversed(entries))),
        )

    def test_adding_a_disallowed_entry_stays_full(self) -> None:
        base = [self._entry("M", STATE_FILES[0])]
        extra = self._entry("M", "README.md")
        self.assertEqual(self.module.classify_entries(base)[0], "state_only")
        self.assertEqual(self.module.classify_entries([*base, extra])[0], "full")
        self.assertEqual(self.module.classify_entries([extra])[0], "full")

    def test_outside_list_unicode_and_escapes_are_full(self) -> None:
        cases = {
            "README.md": "outside_closed_list",
            "reports/development/EXECUTION_STATE.json.bak": "outside_closed_list",
            "reports/development/EXECUTI\u039fN_STATE.json": "outside_closed_list",
            "reports/development/EXECUTION_STATE.jso\uff4e": "outside_closed_list",
            "reports/development/../development/EXECUTION_STATE.json": "path_escape",
            "/reports/development/EXECUTION_STATE.json": "absolute_path",
            "reports/development/decision_requests/nested/ONE.md": "decision_request_not_direct",
            "reports/development/decision_requests/ONE.txt": "decision_request_not_markdown",
            "reports/development/decision_requests/ONE.MD": "decision_request_not_markdown",
            "scripts/classify_pull_request_ci_route.py": "outside_closed_list",
            "scripts/run_state_only_ci_path.py": "outside_closed_list",
            "reports/tests/test_classify_pull_request_ci_route.py": "outside_closed_list",
            "reports/tests/conftest.py": "outside_closed_list",
            ".github/workflows/ocor-rccad.yml": "outside_closed_list",
        }
        for path, reason in cases.items():
            route, actual = self.module.classify_entries([self._entry("M", path)])
            self.assertEqual(route, "full", path)
            self.assertEqual(actual, reason, path)

    def test_status_mode_symlink_binary_and_mixtures_are_full(self) -> None:
        state = STATE_FILES[0]
        decision = "reports/development/decision_requests/ONE.md"
        cases = [
            (self._entry("D", state), "deletion"),
            (self._entry("R100", state, old_path="other.json"), "rename"),
            (self._entry("C100", state, old_path="other.json"), "copy"),
            (self._entry("T", state), "type_change"),
            (self._entry("U", state), "unmerged"),
            (
                self._entry("M", state, old_mode="100644", new_mode="100755"),
                "mode_change",
            ),
            (
                self._entry("M", state, old_mode="100644", new_mode="120000"),
                "symlink",
            ),
            (
                self._entry("A", state, old_mode="000000", new_mode="120000"),
                "symlink",
            ),
            (self._entry("M", state, binary=True), "binary"),
            (
                self._entry("A", state, old_mode="000000", new_mode="160000"),
                "submodule",
            ),
        ]
        for entry, reason in cases:
            route, actual = self.module.classify_entries([entry])
            self.assertEqual(route, "full", reason)
            self.assertEqual(actual, reason)
        mixed = [
            self._entry("M", state),
            self._entry("A", decision),
        ]
        self.assertEqual(
            self.module.classify_entries(mixed),
            ("full", "mixed_state_and_decision_request"),
        )
        two = [
            self._entry("A", decision),
            self._entry("A", "reports/development/decision_requests/TWO.md"),
        ]
        self.assertEqual(
            self.module.classify_entries(two),
            ("full", "multiple_decision_requests"),
        )
        self.assertEqual(
            self.module.classify_entries([]),
            ("full", "empty_diff"),
        )

    def test_pair_combinations_of_full_reasons_stay_full(self) -> None:
        state = STATE_FILES[0]
        offenders = [
            self._entry("D", state),
            self._entry("M", "README.md"),
            self._entry("M", state, binary=True),
            self._entry("M", state, old_mode="100644", new_mode="100755"),
        ]
        for left in offenders:
            for right in offenders:
                route, _reason = self.module.classify_entries([left, right])
                self.assertEqual(route, "full")


class GitClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.base = _init_repo(self.repo)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_git_positive_state_and_decision_request(self) -> None:
        path = self.repo / STATE_FILES[0]
        path.write_text("changed\n", encoding="utf-8")
        head = _commit_all(self.repo, "state")
        result = _classify(self.repo, self.base, head)
        self.assertEqual(result["route"], "state_only")
        decision = self.repo / "reports/development/decision_requests/NEW.md"
        # Reset to a decision-only commit from the base tree.
        _git(self.repo, "checkout", "-q", "-B", "decision", self.base)
        decision.write_text("# New\n", encoding="utf-8")
        head = _commit_all(self.repo, "decision")
        result = _classify(self.repo, self.base, head)
        self.assertEqual(result["route"], "state_only")

    def test_git_negative_class(self) -> None:
        repo = self.repo
        base = self.base

        def at(message: str, mutate) -> dict[str, Any]:  # type: ignore[no-untyped-def]
            _git(repo, "checkout", "-q", "-B", "case", base)
            mutate()
            head = _commit_all(repo, message)
            return _classify(repo, base, head)

        empty = _classify(repo, base, base)
        self.assertEqual(empty["route"], "full")
        self.assertEqual(empty["reason"], "empty_diff")

        missing = _classify(repo, "0" * 40, base)
        self.assertEqual(missing["route"], "full")
        self.assertEqual(missing["reason"], "git_error")

        renamed = at(
            "rename",
            lambda: _git(
                repo,
                "mv",
                STATE_FILES[0],
                "reports/development/EXECUTION_STATE_moved.json",
            ),
        )
        self.assertEqual(renamed["route"], "full")

        deleted = at(
            "delete",
            lambda: (repo / STATE_FILES[0]).unlink(),
        )
        self.assertEqual(deleted["route"], "full")
        self.assertEqual(deleted["reason"], "deletion")

        def mode() -> None:
            path = repo / "reports/development/ITERATION_LOG.md"
            path.chmod(0o755)
            _git(repo, "update-index", "--chmod=+x", "reports/development/ITERATION_LOG.md")

        self.assertEqual(at("mode", mode)["reason"], "mode_change")

        def symlink() -> None:
            target = repo / "reports/development/MODEL_HANDOFF.json"
            target.unlink()
            target.symlink_to("EXECUTION_STATE.json")

        self.assertEqual(at("symlink", symlink)["reason"], "symlink")

        def binary() -> None:
            (repo / STATE_FILES[0]).write_bytes(b"\0\1\2")

        self.assertEqual(at("binary", binary)["reason"], "binary")

        outside = at(
            "outside",
            lambda: (repo / "README.md").write_text("x\n", encoding="utf-8"),
        )
        self.assertEqual(outside["reason"], "outside_closed_list")

    def test_missing_arguments_are_full_and_github_output_is_one_field(self) -> None:
        proc = subprocess.run(
            ["python3", str(CLASSIFIER), "--base", "", "--head", ""],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["route"], "full")
        self.assertEqual(payload["reason"], "missing_base_or_head")
        output = self.repo / "github.out"
        proc = subprocess.run(
            [
                "python3",
                str(CLASSIFIER),
                "--base",
                "",
                "--head",
                "",
                "--github-output",
                str(output),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(output.read_text(encoding="utf-8"), "route=full\n")
        self.assertNotIn("route=", proc.stdout)


class FastPathCommandTests(unittest.TestCase):
    def test_commands_use_the_folder_marker_and_not_a_hand_written_list(self) -> None:
        module = _load(RUNNER, "run_state_only_ci_path")
        commands = module.gate_commands(
            "/opt/venv/bin/python",
            "origin/main",
            "governed/state-sync-example",
        )
        rendered = [" ".join(command) for command in commands]
        joined = "\n".join(rendered)
        self.assertIn("/opt/venv/bin/python scripts/validate_evidence_input_drift.py", rendered)
        self.assertIn("/opt/venv/bin/python scripts/verify.py --json", rendered)
        self.assertIn("sha256sum -c inputs/normative/SHA256SUMS", rendered)
        self.assertIn("/opt/venv/bin/python scripts/validate_language_policy.py", rendered)
        self.assertIn("/opt/venv/bin/python -m mypy", rendered)
        self.assertIn(
            "/opt/venv/bin/python scripts/validate_ocor_development_plan.py --authorized-extension --base-ref origin/main",
            rendered,
        )
        self.assertIn(
            "/opt/venv/bin/python scripts/validate_rccad.py --base-ref origin/main",
            rendered,
        )
        self.assertIn("ruff check .", rendered)
        self.assertIn(
            "/opt/venv/bin/python scripts/validate_ocor_change_scope.py --base origin/main --head HEAD --branch governed/state-sync-example",
            rendered,
        )
        for task, manifest in (
            ("OCOR-DEV-0005", "reports/evidence/G0/MANIFEST.json"),
            ("OCOR-DEV-0049", "reports/evidence/G4/MANIFEST.json"),
            ("OCOR-DEV-0050", "reports/evidence/G5/MANIFEST.json"),
            ("OCOR-DEV-0082", "reports/evidence/G2/MANIFEST.json"),
        ):
            self.assertIn(
                f"/opt/venv/bin/python scripts/validate_runtime_evidence.py --task {task} --non-skipped --manifest {manifest}",
                rendered,
            )
        pytest_commands = [command for command in commands if "pytest" in command]
        self.assertEqual(len(pytest_commands), 1)
        self.assertEqual(
            pytest_commands[0],
            [
                "/opt/venv/bin/python",
                "-m",
                "pytest",
                "reports/tests",
                "-m",
                "not requires_live_stack",
                "-q",
            ],
        )
        self.assertNotIn("bootstrap_ci_environment.py", joined)
        self.assertNotIn("run_qualifying_campaign.py", joined)
        self.assertNotRegex(joined, r"reports/tests/test_[A-Za-z0-9_]+\.py")

    def test_a_failing_command_fails_closed(self) -> None:
        module = _load(RUNNER, "run_state_only_ci_path_exec")
        seen: list[list[str]] = []

        def runner(command: list[str]) -> int:
            seen.append(command)
            return 7 if len(seen) == 2 else 0

        code = module.execute_commands([["one"], ["two"], ["three"]], runner)
        self.assertEqual(code, 7)
        self.assertEqual(seen, [["one"], ["two"]])


class WorkflowInvariantTests(unittest.TestCase):
    def test_original_run_blocks_remain_and_the_fast_path_is_gated(self) -> None:
        for path in WORKFLOWS:
            old = subprocess.run(
                ["git", "show", f"origin/main:{path.relative_to(ROOT).as_posix()}"],
                check=True,
                capture_output=True,
                text=True,
                cwd=ROOT,
            ).stdout
            new = path.read_text(encoding="utf-8")
            for block in _run_blocks(old):
                self.assertIn(block, new, path.name)
            self.assertIn("classify-ci-route:", new)
            self.assertIn("scripts/classify_pull_request_ci_route.py", new)
            self.assertIn("scripts/run_state_only_ci_path.py", new)
            self.assertIn(
                "needs.classify-ci-route.outputs.route != 'state_only'",
                new,
            )
            self.assertIn(
                "needs.classify-ci-route.outputs.route == 'state_only'",
                new,
            )
            self.assertEqual(old.count("run_qualifying_campaign.py"), new.count("run_qualifying_campaign.py"))
            self.assertEqual(old.count("timeout-minutes:"), new.count("timeout-minutes:") - 1)

    def test_required_aggregator_names_stay(self) -> None:
        text = "\n".join(path.read_text(encoding="utf-8") for path in WORKFLOWS)
        for name in ("rccad-methodology:", "delivery-activation:", "validation-closure:"):
            self.assertIn(f"\n  {name}\n", text)
        self.assertNotIn("name: rccad-methodology-renamed", text)


class LiveStackMarkerTests(unittest.TestCase):
    def test_reports_tests_marker_selects_only_the_live_relay_cases(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "reports/tests/test_rem0032_relay_probe.py",
                "-m",
                "requires_live_stack",
                "--collect-only",
                "-q",
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        names = [
            line.strip()
            for line in proc.stdout.splitlines()
            if line.startswith("reports/tests/test_rem0032_relay_probe.py")
        ]
        self.assertEqual(
            names,
            [
                "reports/tests/test_rem0032_relay_probe.py::test_dead_relay_after_start_period_turns_unhealthy_within_bound",
                "reports/tests/test_rem0032_relay_probe.py::test_red_task_stage_probe_turns_relays_unhealthy_under_cpu_limit",
                "reports/tests/test_rem0032_relay_probe.py::test_green_probe_keeps_every_relay_healthy_under_cpu_limit",
            ],
        )
        other = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "reports/tests/test_rem0032_relay_probe.py::test_everything_else_is_identical_to_the_0049_task_stage",
                "-m",
                "requires_live_stack",
                "--collect-only",
                "-q",
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        self.assertEqual(other.returncode, 5, other.stdout + other.stderr)


if __name__ == "__main__":
    unittest.main()
