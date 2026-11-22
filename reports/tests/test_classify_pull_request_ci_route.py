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
import tempfile
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CLASSIFIER = ROOT / "scripts" / "classify_pull_request_ci_route.py"
RUNNER = ROOT / "scripts" / "run_state_only_ci_path.py"
FORMAT = ROOT / "scripts" / "validate_decision_request_format.py"
DECISION_DIR = "reports/development/decision_requests"
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
IMPORT_EXIT_SCRIPTS = (
    "reports/tests/test_schema_conformance.py",
    "reports/tests/test_v12_approval_readiness.py",
    "reports/tests/test_v12_candidate.py",
    "reports/tests/test_v12_release_gate.py",
    "reports/tests/test_v12_semantics.py",
)
KNOWN_SCHEMA_TOTAL = "TOTAL 98 PASS 97 FAIL 1"
KNOWN_SCHEMA_FAIL = (
    "FAIL urn:ocor:schema:action-type-contract:1.0 — negativo semantico: "
    "CANONICAL_COMMIT R1 senza Human Gate [ACCEPT]"
)


def _schema_stdout(
    *,
    pass_count: int = 97,
    fails: list[str] | None = None,
    total: str = KNOWN_SCHEMA_TOTAL,
) -> str:
    fail_lines = [KNOWN_SCHEMA_FAIL] if fails is None else fails
    lines = [f"PASS case-{index:02d}" for index in range(pass_count)]
    lines.extend(fail_lines)
    lines.append(total)
    return "\n".join(lines) + "\n"


def _canonical_schema_stdout(module: Any) -> str:
    """Return the one schema report the runner accepts."""
    lines = [
        *module.EXPECTED_SCHEMA_PASS_LINES,
        module.KNOWN_SCHEMA_FAIL,
        module.KNOWN_SCHEMA_TOTAL,
        module.KNOWN_SCHEMA_RESULTS,
    ]
    return "\n".join(lines) + "\n"


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


def _diff_names(repo: Path, *revs: str) -> list[str]:
    proc = _git(
        repo,
        "diff",
        "--name-only",
        "--no-ext-diff",
        "--no-textconv",
        "-M",
        *revs,
    )
    return [line for line in proc.stdout.splitlines() if line]


def _format_run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(FORMAT), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _format_payload(*args: str) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    proc = _format_run(*args)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return proc, payload


_VALID_DIRECT = (
    "# Decision\n\n"
    "## Opzioni\n\n"
    "1. **Titolo.** testo\n\n"
    "## Raccomandazione\n\n"
    "Nessuna.\n"
)
_VALID_LETTERS = (
    "# Decision\n\n"
    "### Opzioni del quesito A\n\n"
    "A1. **Prima.** testo\n\n"
    "A2. **Seconda.** testo\n\n"
    "### Opzioni del quesito B\n\n"
    "B1. **Terza.** testo\n\n"
    "## Raccomandazione\n\n"
    "Nessuna.\n"
)


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


class RepairCycle2Tests(unittest.TestCase):
    """VF-001 of OCOR-DEV-REM-0066-2ab8577d5b0a-1.

    The violated property is the pull-request diff: GitHub compares the
    unique merge-base of the pinned base and head commits with the pinned
    head. A two-dot diff of the branch tips is a different class member.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.base = _init_repo(self.repo)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_three_dot_keeps_a_change_the_base_also_adopted(self) -> None:
        repo = self.repo
        _git(repo, "checkout", "-q", "-B", "headside", self.base)
        (repo / "README.md").write_text("shared\n", encoding="utf-8")
        (repo / "reports/development/ITERATION_LOG.md").write_text("v1\n", encoding="utf-8")
        head = _commit_all(repo, "head adds readme and state")
        _git(repo, "checkout", "-q", "-B", "baseside", self.base)
        (repo / "README.md").write_text("shared\n", encoding="utf-8")
        base_tip = _commit_all(repo, "base adopts the same readme")
        two = _diff_names(repo, base_tip, head)
        three = _diff_names(repo, f"{base_tip}...{head}")
        self.assertEqual(two, ["reports/development/ITERATION_LOG.md"])
        self.assertCountEqual(
            three,
            ["README.md", "reports/development/ITERATION_LOG.md"],
        )
        result = _classify(repo, base_tip, head)
        self.assertEqual(result["route"], "full")
        self.assertEqual(result["reason"], "outside_closed_list")
        self.assertEqual(result["merge_base"], self.base)

    def test_three_dot_ignores_a_change_that_exists_only_on_the_base(self) -> None:
        repo = self.repo
        _git(repo, "checkout", "-q", "-B", "headside", self.base)
        (repo / "reports/development/ITERATION_LOG.md").write_text("v1\n", encoding="utf-8")
        head = _commit_all(repo, "head state")
        _git(repo, "checkout", "-q", "-B", "baseside", self.base)
        (repo / "README.md").write_text("advanced\n", encoding="utf-8")
        base_tip = _commit_all(repo, "base readme")
        two = _diff_names(repo, base_tip, head)
        three = _diff_names(repo, f"{base_tip}...{head}")
        self.assertCountEqual(
            two,
            ["README.md", "reports/development/ITERATION_LOG.md"],
        )
        self.assertEqual(three, ["reports/development/ITERATION_LOG.md"])
        by_sha = _classify(repo, base_tip, head)
        by_name = _classify(repo, "baseside", "headside")
        self.assertEqual(by_sha["route"], "state_only")
        self.assertEqual(by_sha["reason"], "state_files")
        self.assertEqual(by_sha["merge_base"], self.base)
        self.assertEqual(by_name["route"], by_sha["route"])
        self.assertEqual(by_name["reason"], by_sha["reason"])
        self.assertEqual(by_name["merge_base"], by_sha["merge_base"])
        self.assertEqual(by_name["base_sha"], base_tip)
        self.assertEqual(by_name["head_sha"], head)

    def test_unrelated_histories_stay_full(self) -> None:
        repo = self.repo
        _git(repo, "checkout", "--orphan", "unrelated")
        (repo / "reports/development/ITERATION_LOG.md").write_text("v1\n", encoding="utf-8")
        _git(repo, "add", "-A")
        head = _commit_all(repo, "orphan state")
        merged = _git(repo, "merge-base", "--all", self.base, head, check=False)
        self.assertNotEqual(merged.returncode, 0)
        self.assertEqual(
            _diff_names(repo, self.base, head),
            ["reports/development/ITERATION_LOG.md"],
        )
        result = _classify(repo, self.base, head)
        self.assertEqual(result["route"], "full")
        self.assertEqual(result["reason"], "git_error")
        self.assertEqual(result["merge_base"], "")

    def test_multiple_merge_bases_stay_full(self) -> None:
        repo = self.repo
        base_branch = _git(repo, "branch", "--show-current").stdout.strip()
        _git(repo, "checkout", "-q", "-b", "left")
        (repo / "README.md").write_text("L\n", encoding="utf-8")
        left = _commit_all(repo, "L")
        _git(repo, "checkout", "-q", base_branch)
        (repo / "reports/development/ITERATION_LOG.md").write_text("R\n", encoding="utf-8")
        _commit_all(repo, "R")
        _git(repo, "checkout", "-q", "left")
        _git(repo, "merge", "--no-ff", "-q", "-m", "M1", base_branch)
        first = _git(repo, "rev-parse", "HEAD").stdout.strip()
        _git(repo, "checkout", "-q", base_branch)
        _git(repo, "merge", "--no-ff", "-q", "-m", "M2", left)
        (repo / "reports/development/ITERATION_LOG.md").write_text("R2\n", encoding="utf-8")
        head = _commit_all(repo, "Y")
        bases = _git(repo, "merge-base", "--all", first, head).stdout.split()
        self.assertEqual(len(bases), 2)
        self.assertEqual(
            _diff_names(repo, first, head),
            ["reports/development/ITERATION_LOG.md"],
        )
        result = _classify(repo, first, head)
        self.assertEqual(result["route"], "full")
        self.assertEqual(result["reason"], "git_error")
        self.assertEqual(result["merge_base"], "")

    def test_missing_head_and_empty_diff_stay_full(self) -> None:
        missing = _classify(self.repo, self.base, "f" * 40)
        self.assertEqual(missing["route"], "full")
        self.assertEqual(missing["reason"], "git_error")
        self.assertEqual(missing["merge_base"], "")
        empty = _classify(self.repo, self.base, self.base)
        self.assertEqual(empty["route"], "full")
        self.assertEqual(empty["reason"], "empty_diff")
        self.assertEqual(empty["merge_base"], self.base)

    def test_payload_pins_the_linear_merge_base(self) -> None:
        path = self.repo / STATE_FILES[0]
        path.write_text("changed\n", encoding="utf-8")
        head = _commit_all(self.repo, "state")
        result = _classify(self.repo, self.base, head)
        self.assertEqual(result["route"], "state_only")
        self.assertEqual(result["reason"], "state_files")
        self.assertEqual(result["base_sha"], self.base)
        self.assertEqual(result["head_sha"], head)
        self.assertEqual(result["merge_base"], self.base)

    def test_classifier_workflow_and_test_paths_stay_full(self) -> None:
        cases = (
            "scripts/classify_pull_request_ci_route.py",
            "scripts/run_state_only_ci_path.py",
            "reports/tests/test_classify_pull_request_ci_route.py",
            ".github/workflows/ocor-rccad.yml",
        )
        for relative in cases:
            _git(self.repo, "checkout", "-q", "-B", "case", self.base)
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# changed\n", encoding="utf-8")
            head = _commit_all(self.repo, relative)
            result = _classify(self.repo, self.base, head)
            self.assertEqual(result["route"], "full", relative)
            self.assertEqual(result["reason"], "outside_closed_list", relative)


class DecisionRequestFormatTests(unittest.TestCase):
    """VF-002 of OCOR-DEV-REM-0066-2ab8577d5b0a-1.

    The violated property is DR-FORMATO-OPZIONI on the decision-request file
    the pull request adds or modifies. Classification stays path-only.
    """

    def test_gate_command_checks_the_diff_between_base_and_head(self) -> None:
        module = _load(RUNNER, "run_state_only_format_command")
        commands = module.gate_commands(
            "/opt/venv/bin/python",
            "origin/main",
            "governed/state-sync-example",
        )
        rendered = [" ".join(command) for command in commands]
        self.assertIn(
            "/opt/venv/bin/python scripts/validate_decision_request_format.py "
            "--base origin/main --head HEAD",
            rendered,
        )

    def test_valid_pull_request_file_passes_and_malformed_stays_classified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            base = _init_repo(repo)
            path = repo / DECISION_DIR / "NEW.md"
            path.write_text(_VALID_DIRECT, encoding="utf-8")
            head = _commit_all(repo, "decision")
            self.assertEqual(_classify(repo, base, head)["route"], "state_only")
            proc, payload = _format_payload("--root", str(repo), "--base", base, "--head", head)
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertEqual(payload["reason"], "ok")
            self.assertEqual(payload["checked"], [f"{DECISION_DIR}/NEW.md"])

    def test_malformed_pull_request_file_fails_without_reclassification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            base = _init_repo(repo)
            path = repo / DECISION_DIR / "NEW.md"
            path.write_text("# Decision\n\nNessuna opzione.\n", encoding="utf-8")
            head = _commit_all(repo, "decision")
            self.assertEqual(_classify(repo, base, head)["route"], "state_only")
            self.assertEqual(_classify(repo, base, head)["reason"], "single_decision_request")
            proc, payload = _format_payload("--root", str(repo), "--base", base, "--head", "HEAD")
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(payload["reason"], "no_options_heading")
            self.assertEqual(payload["path"], f"{DECISION_DIR}/NEW.md")

    def test_state_only_diff_does_not_scan_the_historical_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            base = _init_repo(repo)
            historical = repo / DECISION_DIR / "KEEP.md"
            self.assertNotIn("## Opzioni", historical.read_text(encoding="utf-8"))
            (repo / STATE_FILES[0]).write_text("changed\n", encoding="utf-8")
            head = _commit_all(repo, "state")
            proc, payload = _format_payload("--root", str(repo), "--base", base, "--head", head)
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertEqual(payload["checked"], [])

    def test_missing_path_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            missing = f"{DECISION_DIR}/MISSING-OPTIONS-EXAMPLE.md"
            proc, payload = _format_payload("--root", str(root), "--path", missing)
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(payload["reason"], "missing_file")
            self.assertEqual(payload["path"], missing)

    def test_option_class_fails_closed_and_the_two_valid_forms_pass(self) -> None:
        samples = (
            ("no_options_heading", "# Decision\n\nNessuna opzione.\n"),
            (
                "plain_list",
                "# Decision\n\n## Opzioni\n\n1. Titolo senza grassetto\n",
            ),
            (
                "numbering_gap",
                "# Decision\n\n## Opzioni\n\n1. **Titolo.** testo\n3. **Altro.** testo\n",
            ),
            (
                "numbering_gap",
                "# Decision\n\n### Opzioni del quesito A\n\nA1. **Prima.** testo\nA3. **Terza.** testo\n",
            ),
            (
                "empty_options",
                "# Decision\n\n## Opzioni\n\n## Raccomandazione\n\nNessuna.\n",
            ),
            (
                "empty_options",
                "# Decision\n\n### Opzioni del quesito A\n\n"
                "### Opzioni del quesito B\n\nB1. **Titolo.** testo\n",
            ),
            (
                "wrong_letter",
                "# Decision\n\n### Opzioni del quesito A\n\nB1. **Titolo.** testo\n",
            ),
            (
                "option_outside_heading",
                "# Decision\n\n1. **Fuori.** testo\n\n## Opzioni\n\n1. **Titolo.** testo\n",
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "REQUEST.md"
            for reason, body in samples:
                with self.subTest(reason=reason, body=body):
                    target.write_text(body, encoding="utf-8")
                    proc, payload = _format_payload("--root", str(root), "--path", "REQUEST.md")
                    self.assertNotEqual(proc.returncode, 0)
                    self.assertEqual(payload["reason"], reason)
            target.write_text(_VALID_DIRECT, encoding="utf-8")
            direct, direct_payload = _format_payload("--root", str(root), "--path", "REQUEST.md")
            self.assertEqual(direct.returncode, 0, direct.stderr + direct.stdout)
            self.assertEqual(direct_payload["reason"], "ok")
            target.write_text(_VALID_LETTERS, encoding="utf-8")
            letters, letter_payload = _format_payload("--root", str(root), "--path", "REQUEST.md")
            self.assertEqual(letters.returncode, 0, letters.stderr + letters.stdout)
            self.assertEqual(letter_payload["reason"], "ok")

    def test_non_utf8_body_fails_closed(self) -> None:
        """A body that is not UTF-8 is not_utf8 on both entry points."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "REQUEST.md"
            target.write_bytes(b"# Decision\n\xff\n")
            proc, payload = _format_payload("--root", str(root), "--path", "REQUEST.md")
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(payload["reason"], "not_utf8")
            self.assertEqual(payload["path"], "REQUEST.md")
            self.assertEqual(payload["checked"], [])

            repo = root / "repo"
            base = _init_repo(repo)
            decision = repo / DECISION_DIR / "NEW.md"
            decision.write_bytes(_VALID_DIRECT.encode("utf-8") + b"\xff")
            head = _commit_all(repo, "binary decision")
            diff, diff_payload = _format_payload(
                "--root", str(repo), "--base", base, "--head", head
            )
            self.assertNotEqual(diff.returncode, 0)
            self.assertEqual(diff_payload["reason"], "not_utf8")
            self.assertEqual(diff_payload["path"], f"{DECISION_DIR}/NEW.md")

    def test_git_protocol_error_fails_closed(self) -> None:
        """Missing objects and a truncated name-status stream are git_error."""
        missing = "0123456789abcdef0123456789abcdef01234567"
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            base = _init_repo(repo)
            absent, absent_payload = _format_payload(
                "--root", str(repo), "--base", base, "--head", missing
            )
            self.assertNotEqual(absent.returncode, 0)
            self.assertEqual(absent_payload["reason"], "git_error")
            empty, empty_payload = _format_payload(
                "--root", str(repo), "--base", "", "--head", base
            )
            self.assertNotEqual(empty.returncode, 0)
            self.assertEqual(empty_payload["reason"], "git_error")

            bindir = repo / "fake-bin"
            bindir.mkdir()
            wrapper = bindir / "git"
            wrapper.write_text(
                "#!/usr/bin/env python3\n"
                "import os\n"
                "import sys\n"
                "argv = sys.argv[1:]\n"
                "if argv[:1] == ['-C']:\n"
                "    argv = argv[2:]\n"
                "command = argv[0] if argv else ''\n"
                "mode = os.environ.get('OCOR_FAKE_GIT', 'truncated')\n"
                "if command == 'rev-parse':\n"
                "    sys.stdout.buffer.write(b'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\\n')\n"
                "    raise SystemExit(0)\n"
                "if command == 'merge-base':\n"
                "    sys.stdout.buffer.write(b'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\n')\n"
                "    raise SystemExit(0)\n"
                "if command == 'diff':\n"
                "    if mode == 'nonzero':\n"
                "        sys.stderr.buffer.write(b'fatal: protocol\\n')\n"
                "        raise SystemExit(1)\n"
                "    sys.stdout.buffer.write(b'M')\n"
                "    raise SystemExit(0)\n"
                "sys.stderr.buffer.write(b'unexpected\\n')\n"
                "raise SystemExit(99)\n",
                encoding="utf-8",
            )
            wrapper.chmod(0o755)
            saved = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{bindir}{os.pathsep}{saved}"
            try:
                os.environ["OCOR_FAKE_GIT"] = "truncated"
                truncated, truncated_payload = _format_payload(
                    "--root", str(repo), "--base", base, "--head", base
                )
                self.assertNotEqual(truncated.returncode, 0)
                self.assertEqual(truncated_payload["reason"], "git_error")
                os.environ["OCOR_FAKE_GIT"] = "nonzero"
                failed, failed_payload = _format_payload(
                    "--root", str(repo), "--base", base, "--head", base
                )
                self.assertNotEqual(failed.returncode, 0)
                self.assertEqual(failed_payload["reason"], "git_error")
            finally:
                os.environ["PATH"] = saved
                os.environ.pop("OCOR_FAKE_GIT", None)


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
        self.assertIn(
            "/opt/venv/bin/python scripts/validate_decision_request_format.py --base origin/main --head HEAD",
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
                *[f"--ignore={path}" for path in IMPORT_EXIT_SCRIPTS],
                "-q",
            ],
        )
        self.assertEqual(
            commands[-len(IMPORT_EXIT_SCRIPTS) :],
            [["/opt/venv/bin/python", path] for path in IMPORT_EXIT_SCRIPTS],
        )
        self.assertNotIn("bootstrap_ci_environment.py", joined)
        self.assertNotIn("run_qualifying_campaign.py", joined)
        residual = joined
        for path in IMPORT_EXIT_SCRIPTS:
            self.assertEqual(residual.count(path), 2)
            residual = residual.replace(path, "")
        self.assertNotRegex(residual, r"reports/tests/test_[A-Za-z0-9_]+\.py")

    def test_known_schema_report_is_accepted(self) -> None:
        module = _load(RUNNER, "run_state_only_schema_report")
        self.assertTrue(
            module.schema_report_accepted(_canonical_schema_stdout(module))
        )

    def test_extra_fail_is_rejected(self) -> None:
        module = _load(RUNNER, "run_state_only_extra_fail")
        stdout = _schema_stdout(fails=[KNOWN_SCHEMA_FAIL, "FAIL urn:ocor:schema:extra"])
        self.assertFalse(module.schema_report_accepted(stdout))
        self.assertNotEqual(self._script_step(module, [(1, stdout)]), 0)

    def test_missing_case_is_rejected(self) -> None:
        module = _load(RUNNER, "run_state_only_missing_case")
        stdout = _schema_stdout(pass_count=96, total="TOTAL 97 PASS 96 FAIL 1")
        self.assertFalse(module.schema_report_accepted(stdout))
        self.assertNotEqual(self._script_step(module, [(1, stdout)]), 0)

    def test_different_observation_is_rejected(self) -> None:
        module = _load(RUNNER, "run_state_only_different_observation")
        stdout = _schema_stdout(
            fails=[
                "FAIL urn:ocor:schema:action-type-contract:1.0 — negativo semantico: "
                "CANONICAL_COMMIT R1 senza Human Gate [REJECT]"
            ]
        )
        self.assertFalse(module.schema_report_accepted(stdout))
        self.assertNotEqual(self._script_step(module, [(0, stdout)]), 0)

    def test_schema_process_code_does_not_decide_and_v12_code_does(self) -> None:
        module = _load(RUNNER, "run_state_only_process_codes")
        report = _canonical_schema_stdout(module)
        accepted = self._script_step(
            module, [(1, report), (0, ""), (0, ""), (0, ""), (0, "")]
        )
        self.assertEqual(accepted, 0)
        rejected = self._script_step(module, [(1, report), (5, "")])
        self.assertEqual(rejected, 5)

    def test_invalid_script_stdout_fails_closed(self) -> None:
        module = _load(RUNNER, "run_state_only_invalid_stdout")
        self.assertNotEqual(self._script_step(module, [(0, b"\xff")]), 0)

    def test_tracked_json_bytes_are_restored(self) -> None:
        module = _load(RUNNER, "run_state_only_restore_bytes")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            photos = {}
            for relative in module.TRACKED_JSON:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                payload = b"photo-" + relative.encode("ascii")
                path.write_bytes(payload)
                photos[relative] = payload
            self.assertEqual(module.snapshot_tracked_json(root), photos)
            calls: list[list[str]] = []
            report = _canonical_schema_stdout(module).encode("utf-8")

            def runner(command: list[str]) -> subprocess.CompletedProcess[bytes]:
                calls.append(list(command))
                for relative in module.TRACKED_JSON:
                    (root / relative).write_bytes(b"changed")
                stdout = report if len(calls) == 1 else b""
                code = 1 if len(calls) == 1 else 0
                return subprocess.CompletedProcess(command, code, stdout=stdout)

            def snapshot() -> dict[str, bytes]:
                return module.snapshot_tracked_json(root)

            def restore(saved: dict[str, bytes]) -> bool:
                return bool(module.restore_tracked_json(saved, root))

            code = module.run_tracked_scripts("/opt/venv/bin/python", runner, snapshot, restore)
            self.assertEqual(code, 0)
            self.assertEqual(calls, [["/opt/venv/bin/python", path] for path in IMPORT_EXIT_SCRIPTS])
            for relative, payload in photos.items():
                self.assertEqual((root / relative).read_bytes(), payload)

    def test_restore_mismatch_fails_closed(self) -> None:
        module = _load(RUNNER, "run_state_only_restore_mismatch")
        code = self._script_step(
            module,
            [(1, _canonical_schema_stdout(module)), (0, ""), (0, ""), (0, ""), (0, "")],
            restore_result=False,
        )
        self.assertNotEqual(code, 0)

    def test_snapshot_oserror_does_not_run_scripts(self) -> None:
        module = _load(RUNNER, "run_state_only_snapshot_oserror")
        calls: list[list[str]] = []

        def runner(command: list[str]) -> subprocess.CompletedProcess[bytes]:
            calls.append(list(command))
            return subprocess.CompletedProcess(command, 0, stdout=b"")

        def snapshot() -> dict[str, bytes]:
            raise OSError("snapshot unreadable")

        code = module.run_tracked_scripts("/opt/venv/bin/python", runner, snapshot, lambda _photos: True)
        self.assertNotEqual(code, 0)
        self.assertEqual(calls, [])

    def _script_step(
        self,
        module: Any,
        results: list[tuple[int, str | bytes]],
        *,
        restore_result: bool = True,
    ) -> int:
        pending = list(results)

        def runner(command: list[str]) -> subprocess.CompletedProcess[bytes]:
            code, stdout = pending.pop(0)
            return subprocess.CompletedProcess(command, code, stdout=stdout)

        photos = {"reports/tests/conformance_results.json": b"photo"}
        return int(
            module.run_tracked_scripts(
                "/opt/venv/bin/python",
                runner,
                lambda: dict(photos),
                lambda _photos: restore_result,
            )
        )

    def test_a_failing_command_fails_closed(self) -> None:
        module = _load(RUNNER, "run_state_only_ci_path_exec")
        seen: list[list[str]] = []

        def runner(command: list[str]) -> int:
            seen.append(command)
            return 7 if len(seen) == 2 else 0

        code = module.execute_commands([["one"], ["two"], ["three"]], runner)
        self.assertEqual(code, 7)
        self.assertEqual(seen, [["one"], ["two"]])


def _step_run_body(workflow: str, step_name: str) -> str:
    """Return the shell of one workflow step, without its YAML indentation."""
    marker = f"      - name: {step_name}\n"
    start = workflow.index(marker)
    rest = workflow[start:]
    run_at = rest.index("        run: |\n")
    body = rest[run_at + len("        run: |\n") :]
    lines: list[str] = []
    for line in body.splitlines():
        if line.startswith("          "):
            lines.append(line[10:])
        elif line.strip() == "":
            lines.append("")
        else:
            break
    return "\n".join(lines).rstrip() + "\n"


def _live_schema_stdout() -> str:
    """Run the schema script and restore the JSON it rewrites."""
    photo_path = ROOT / "reports/tests/conformance_results.json"
    photo = photo_path.read_bytes()
    try:
        proc = subprocess.run(
            [sys.executable, "reports/tests/test_schema_conformance.py"],
            check=False,
            capture_output=True,
            cwd=ROOT,
        )
        if proc.returncode not in (0, 1):
            raise AssertionError(proc.stderr.decode("utf-8", errors="replace"))
        return proc.stdout.decode("utf-8")
    finally:
        photo_path.write_bytes(photo)


class RepairCycle1Tests(unittest.TestCase):
    """VF-001, VF-002, VF-003 and VF-007 of OCOR-DEV-REM-0066-3d6b2fd72bb7-0."""

    def test_duplicate_pass_line_replacing_a_missing_case_is_rejected(self) -> None:
        module = _load(RUNNER, "run_state_only_duplicate_pass")
        authentic = _live_schema_stdout()
        self.assertTrue(module.schema_report_accepted(authentic))
        lines = authentic.splitlines()
        missing = (
            "PASS urn:ocor:schema:signed-canonical-ir:1.0 — "
            "digest malformato [REJECT]"
        )
        duplicate = (
            "PASS urn:ocor:schema:signed-canonical-ir:1.0 — "
            "baseline positivo [ACCEPT]"
        )
        self.assertEqual(lines.count(missing), 1)
        self.assertEqual(lines.count(duplicate), 1)
        lines[lines.index(missing)] = duplicate
        mutated = "\n".join(lines) + "\n"
        pass_lines = [line for line in lines if line.startswith("PASS ")]
        self.assertEqual(len(pass_lines), 97)
        self.assertEqual(len(set(pass_lines)), 96)
        self.assertFalse(module.schema_report_accepted(mutated))
        self.assertNotEqual(self._script_step(module, [(1, mutated)]), 0)

    def test_unique_forged_pass_line_is_rejected(self) -> None:
        module = _load(RUNNER, "run_state_only_forged_pass")
        lines = _live_schema_stdout().splitlines()
        replaced = False
        for index, line in enumerate(lines):
            if line.startswith("PASS "):
                lines[index] = "PASS urn:ocor:schema:forged — not a real case [ACCEPT]"
                replaced = True
                break
        self.assertTrue(replaced)
        mutated = "\n".join(lines) + "\n"
        pass_lines = [line for line in mutated.splitlines() if line.startswith("PASS ")]
        self.assertEqual(len(pass_lines), len(set(pass_lines)))
        self.assertFalse(module.schema_report_accepted(mutated))


    def test_frozen_catalogue_matches_the_live_script(self) -> None:
        module = _load(RUNNER, "run_state_only_catalogue_lock")
        authentic = _live_schema_stdout()
        passes = [line for line in authentic.splitlines() if line.startswith("PASS ")]
        self.assertEqual(passes, list(module.EXPECTED_SCHEMA_PASS_LINES))
        self.assertEqual(len(passes), len(set(passes)))
        self.assertTrue(module.schema_report_accepted(authentic))
        self.assertTrue(module.schema_report_accepted(_canonical_schema_stdout(module)))

    def test_fast_path_installs_node_and_does_not_interpolate_the_ref(self) -> None:
        for path in WORKFLOWS:
            text = path.read_text(encoding="utf-8")
            section = text.split("name: Set up Python for the state-only path", 1)[1]
            self.assertIn('node-version: "20.20.2"', section, path.name)
            self.assertIn("npm ci", section, path.name)
            self.assertIn("npm run build", section, path.name)
            body = _step_run_body(text, "Run state-only local gates and non-stack tests")
            self.assertNotIn("${{", body, path.name)
            self.assertIn('"$OCOR_CI_BRANCH"', body, path.name)
            self.assertIn('"$OCOR_CI_BASE_REF"', body, path.name)

    def test_classify_step_runs_the_base_blob(self) -> None:
        bodies = [
            _step_run_body(path.read_text(encoding="utf-8"), "Classify pull request CI route")
            for path in WORKFLOWS
        ]
        self.assertEqual(len(set(bodies)), 1)
        body = bodies[0]
        self.assertNotIn("${{", body)
        self.assertNotIn("python3 scripts/classify_pull_request_ci_route.py", body)
        self.assertIn(
            'git cat-file -e "${OCOR_CI_BASE_SHA}:scripts/classify_pull_request_ci_route.py"',
            body,
        )
        self.assertIn('python3 "$classifier"', body)

    def test_a_modified_classifier_cannot_force_state_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self._commit_base_classifier(repo)
            base = _git(repo, "rev-parse", "HEAD").stdout.strip()
            liar = repo / "scripts/classify_pull_request_ci_route.py"
            liar.write_text(_LIAR, encoding="utf-8")
            head = _commit_all(repo, "replace classifier")
            direct_out = repo / "direct.out"
            direct = subprocess.run(
                [
                    "python3",
                    str(liar),
                    "--base",
                    base,
                    "--head",
                    head,
                    "--root",
                    str(repo),
                    "--github-output",
                    str(direct_out),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(direct.returncode, 0, direct.stderr)
            self.assertEqual(direct_out.read_text(encoding="utf-8").strip(), "route=state_only")
            observed = self._run_trusted_shell(repo, base, head)
            self.assertEqual(observed.strip(), "route=full")

    def test_state_file_change_uses_the_base_classifier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self._commit_base_classifier(repo)
            base = _git(repo, "rev-parse", "HEAD").stdout.strip()
            target = repo / STATE_FILES[0]
            target.write_text("changed\n", encoding="utf-8")
            head = _commit_all(repo, "state")
            observed = self._run_trusted_shell(repo, base, head)
            self.assertEqual(observed.strip(), "route=state_only")

    def test_missing_base_classifier_stays_full(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            base = _init_repo(repo)
            target = repo / STATE_FILES[0]
            target.write_text("changed\n", encoding="utf-8")
            head = _commit_all(repo, "state without classifier")
            observed = self._run_trusted_shell(repo, base, head)
            self.assertEqual(observed.strip(), "route=full")

    def test_invalid_sha_stays_full(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self._commit_base_classifier(repo)
            head = _git(repo, "rev-parse", "HEAD").stdout.strip()
            observed = self._run_trusted_shell(repo, "not-a-sha", head)
            self.assertEqual(observed.strip(), "route=full")

    def test_branch_metacharacters_fail_the_fast_path_as_data(self) -> None:
        module = _load(RUNNER, "run_state_only_branch_data")
        malicious = "governed/ok; echo pwned"
        commands = module.gate_commands("/opt/venv/bin/python", "a" * 40, malicious)
        scope = next(
            command
            for command in commands
            if any(part.endswith("validate_ocor_change_scope.py") for part in command)
        )
        self.assertEqual(scope[-1], malicious)
        self.assertFalse(module.ref_is_data(malicious, module.BRANCH_PATTERN))
        scope_module = _load(
            ROOT / "scripts" / "validate_ocor_change_scope.py",
            "change_scope_branch_lock",
        )
        samples = (
            "governed/ocor-dev-rem-0066-state-only-ci",
            "governed/a",
            "task/OCOR-DEV-0003-state-only",
            "main",
            "governed/ok; echo pwned",
            "governed/../x",
            "origin/main",
            "",
        )
        for sample in samples:
            observed = module.ref_is_data(sample, module.BRANCH_PATTERN) and sample != "main"
            self.assertEqual(observed, bool(scope_module.valid_change_branch(sample)), sample)
        self.assertTrue(module.ref_is_data("origin/main", module.BASE_REF_PATTERN))
        self.assertTrue(module.ref_is_data("ab" * 20, module.BASE_REF_PATTERN))
        self.assertFalse(module.ref_is_data("origin/main; echo pwned", module.BASE_REF_PATTERN))
        self.assertEqual(
            module.main(["--base-ref", "origin/main", "--branch", malicious]),
            1,
        )
        self.assertEqual(
            module.main(
                [
                    "--base-ref",
                    "origin/main; echo pwned",
                    "--branch",
                    "governed/ocor-dev-rem-0066-state-only-ci",
                ]
            ),
            1,
        )
        body = _step_run_body(
            WORKFLOWS[0].read_text(encoding="utf-8"),
            "Run state-only local gates and non-stack tests",
        )
        env = os.environ.copy()
        env["OCOR_CI_BASE_REF"] = "origin/main"
        env["OCOR_CI_BRANCH"] = malicious
        proc = subprocess.run(
            ["bash", "-c", body],
            check=False,
            capture_output=True,
            text=True,
            cwd=ROOT,
            env=env,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("pwned", proc.stdout)

    def _commit_base_classifier(self, repo: Path) -> None:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "ocor-test@example.com")
        _git(repo, "config", "user.name", "OCOR Test")
        script = repo / "scripts/classify_pull_request_ci_route.py"
        script.parent.mkdir(parents=True)
        script.write_text(CLASSIFIER.read_text(encoding="utf-8"), encoding="utf-8")
        for relative in STATE_FILES:
            path = repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative + "\n", encoding="utf-8")
        decision = repo / "reports/development/decision_requests"
        decision.mkdir(parents=True, exist_ok=True)
        (decision / "KEEP.md").write_text("# Keep\n", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", "base")

    def _run_trusted_shell(self, repo: Path, base: str, head: str) -> str:
        body = _step_run_body(
            WORKFLOWS[0].read_text(encoding="utf-8"),
            "Classify pull request CI route",
        )
        self.assertNotIn("${{", body)
        output = repo / "github-output.txt"
        temp = repo / "runner-temp"
        temp.mkdir()
        env = os.environ.copy()
        env.update(
            {
                "GITHUB_OUTPUT": str(output),
                "GIT_PAGER": "cat",
                "OCOR_CI_BASE_SHA": base,
                "OCOR_CI_HEAD_SHA": head,
                "PAGER": "cat",
                "RUNNER_TEMP": str(temp),
            }
        )
        proc = subprocess.run(
            ["bash", "-c", body],
            check=False,
            capture_output=True,
            text=True,
            cwd=repo,
            env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return output.read_text(encoding="utf-8")

    def _script_step(self, module: Any, results: list[tuple[int, str | bytes]]) -> int:
        pending = list(results)

        def runner(command: list[str]) -> subprocess.CompletedProcess[bytes]:
            code, stdout = pending.pop(0)
            return subprocess.CompletedProcess(command, code, stdout=stdout)

        photos = {"reports/tests/conformance_results.json": b"photo"}
        return int(
            module.run_tracked_scripts(
                "/opt/venv/bin/python",
                runner,
                lambda: dict(photos),
                lambda _photos: True,
            )
        )


_LIAR = """#!/usr/bin/env python3
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--base", required=True)
parser.add_argument("--head", required=True)
parser.add_argument("--root", default=".")
parser.add_argument("--github-output", default=None)
args = parser.parse_args()
if args.github_output:
    Path(args.github_output).write_text("route=state_only\\n", encoding="utf-8")
print('{"route": "state_only"}')
"""


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


_FAKE_GIT = """#!/usr/bin/env python3
import os
import sys

argv = sys.argv[1:]
if argv[:1] == ["-C"]:
    argv = argv[2:]
command = argv[0] if argv else ""
if command == "rev-parse":
    sys.stdout.buffer.write(b"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\\n")
    raise SystemExit(0)
if command == "merge-base":
    sys.stdout.buffer.write(b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\n")
    raise SystemExit(0)
if command == "show":
    sys.stdout.buffer.write(
        b"# Decision\\n\\n## Opzioni\\n\\n1. **Titolo.** testo\\n\\n"
        b"## Raccomandazione\\n\\nNessuna.\\n"
    )
    raise SystemExit(0)
if command != "diff":
    sys.stderr.buffer.write(b"unexpected\\n")
    raise SystemExit(99)
path = os.environ.get(
    "OCOR_FAKE_PATH", "reports/development/ITERATION_LOG.md"
).encode()
status = os.environ.get("OCOR_FAKE_STATUS", "M").encode()
raw_status = os.environ.get("OCOR_FAKE_RAW_STATUS", "M").encode()
if "--raw" in argv:
    meta = (
        b":100644 100644 "
        + b"a" * 40
        + b" "
        + b"b" * 40
        + b" "
        + raw_status
    )
    sys.stdout.buffer.write(meta + b"\\0" + path + b"\\0")
    raise SystemExit(0)
if "--name-status" in argv:
    spec = os.environ.get("OCOR_FAKE_RECORDS")
    if spec:
        parts = spec.split("|")
        if len(parts) % 2:
            raise SystemExit(98)
        blob = b""
        for index in range(0, len(parts), 2):
            blob += parts[index].encode() + b"\\0" + parts[index + 1].encode() + b"\\0"
        sys.stdout.buffer.write(blob)
    else:
        sys.stdout.buffer.write(status + b"\\0" + path + b"\\0")
    raise SystemExit(0)
if "--numstat" in argv:
    counters = os.environ.get("OCOR_FAKE_NUMSTAT", "1\\t1").encode()
    sys.stdout.buffer.write(counters + b"\\t" + path + b"\\0")
    raise SystemExit(0)
sys.stderr.buffer.write(b"unexpected diff\\n")
raise SystemExit(99)
"""


class RepairCycle3Tests(unittest.TestCase):
    """VF-001 and VF-002 of OCOR-DEV-REM-0066-ffc6dbfb55dc-2.

    Option 1 of REM-0066-CYCLE2-NO-GO-REFORMULATION. The fast path is the
    classifier CLI and scripts/validate_decision_request_format.py. A binary
    numstat stays on full CI. These tests do not start the stack.
    """

    def _classified(self, **env: str) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bindir = root / "bin"
            bindir.mkdir()
            fake = bindir / "git"
            fake.write_text(_FAKE_GIT, encoding="utf-8")
            fake.chmod(0o755)
            saved_path = os.environ.get("PATH", "")
            saved = {key: os.environ.get(key) for key in env}
            os.environ["PATH"] = f"{bindir}{os.pathsep}{saved_path}"
            for key, value in env.items():
                os.environ[key] = value
            try:
                return _classify(root, "BASE", "HEAD")
            finally:
                os.environ["PATH"] = saved_path
                for key, value in saved.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    def _format_with_git(self, **env: str) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bindir = root / "bin"
            bindir.mkdir()
            fake = bindir / "git"
            fake.write_text(_FAKE_GIT, encoding="utf-8")
            fake.chmod(0o755)
            saved_path = os.environ.get("PATH", "")
            saved = {key: os.environ.get(key) for key in env}
            os.environ["PATH"] = f"{bindir}{os.pathsep}{saved_path}"
            for key, value in env.items():
                os.environ[key] = value
            try:
                return _format_payload("--root", str(root), "--base", "BASE", "--head", "HEAD")
            finally:
                os.environ["PATH"] = saved_path
                for key, value in saved.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    def test_direct_options_and_one_question_exit_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "REQUEST.md"
            target.write_text(_VALID_DIRECT, encoding="utf-8")
            direct, direct_payload = _format_payload("--root", str(root), "--path", "REQUEST.md")
            self.assertEqual(direct.returncode, 0, direct.stderr + direct.stdout)
            self.assertEqual(direct_payload["reason"], "ok")
            target.write_text(
                "# Decision\n\n### Opzioni del quesito A\n\nA1. **Prima.** testo\n",
                encoding="utf-8",
            )
            single, single_payload = _format_payload("--root", str(root), "--path", "REQUEST.md")
            self.assertEqual(single.returncode, 0, single.stderr + single.stdout)
            self.assertEqual(single_payload["reason"], "ok")

    def test_integer_numstat_stays_state_only_and_binary_stays_full(self) -> None:
        integers = self._classified(OCOR_FAKE_NUMSTAT="3\t4")
        self.assertEqual(integers["route"], "state_only")
        self.assertEqual(integers["reason"], "state_files")
        binary = self._classified(OCOR_FAKE_NUMSTAT="-\t-")
        self.assertEqual(binary["route"], "full")
        self.assertEqual(binary["reason"], "binary")
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            base = _init_repo(repo)
            (repo / STATE_FILES[0]).write_text("changed\n", encoding="utf-8")
            head = _commit_all(repo, "state")
            live = _classify(repo, base, head)
            self.assertEqual(live["route"], "state_only")
            self.assertEqual(live["reason"], "state_files")

    def test_empty_non_numeric_and_single_dash_counters_select_full(self) -> None:
        cases = {
            "empty": "\t1",
            "non_numeric": "xx\t1",
            "single_dash": "-\t1",
            "sign": "-1\t1",
        }
        for name, counters in cases.items():
            with self.subTest(name=name):
                result = self._classified(OCOR_FAKE_NUMSTAT=counters)
                self.assertEqual(result["route"], "full")
                self.assertEqual(result["reason"], "git_error")

    def test_unreadable_status_selects_full_and_is_not_ok(self) -> None:
        for status in ("MM", "Z"):
            with self.subTest(status=status):
                result = self._classified(
                    OCOR_FAKE_STATUS=status,
                    OCOR_FAKE_RAW_STATUS=status,
                )
                self.assertEqual(result["route"], "full")
                self.assertEqual(result["reason"], "git_error")
                proc, payload = self._format_with_git(OCOR_FAKE_STATUS=status)
                self.assertNotEqual(proc.returncode, 0)
                self.assertEqual(payload["reason"], "git_error")
                self.assertNotEqual(payload["reason"], "ok")

    def test_unreadable_status_before_a_real_file_is_not_ok(self) -> None:
        spec = "MM|README.md|M|reports/development/decision_requests/NEW.md"
        proc, payload = self._format_with_git(OCOR_FAKE_RECORDS=spec)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(payload["reason"], "git_error")
        kept = "M|README.md|A|reports/development/decision_requests/NEW.md"
        ok, ok_payload = self._format_with_git(OCOR_FAKE_RECORDS=kept)
        self.assertEqual(ok.returncode, 0, ok.stderr + ok.stdout)
        self.assertEqual(ok_payload["reason"], "ok")
        self.assertEqual(
            ok_payload["checked"],
            ["reports/development/decision_requests/NEW.md"],
        )

    def test_option_only_inside_a_fence_fails(self) -> None:
        body = (
            "# Decision\n\n"
            "## Opzioni\n\n"
            "```\n"
            "1. **Titolo.** testo\n"
            "```\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "REQUEST.md").write_text(body, encoding="utf-8")
            proc, payload = _format_payload("--root", str(root), "--path", "REQUEST.md")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(payload["reason"], "option_only_in_fence")

    def test_repeated_question_letter_fails(self) -> None:
        body = (
            "# Decision\n\n"
            "### Opzioni del quesito A\n\n"
            "A1. **Prima.** testo\n\n"
            "### Opzioni del quesito A\n\n"
            "A1. **Seconda.** testo\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "REQUEST.md").write_text(body, encoding="utf-8")
            proc, payload = _format_payload("--root", str(root), "--path", "REQUEST.md")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(payload["reason"], "repeated_question")

    def test_repeated_identifier_fails(self) -> None:
        body = (
            "# Decision\n\n"
            "## Opzioni\n\n"
            "1. **Prima.** testo\n\n"
            "## Nota\n\n"
            "Nessuna.\n\n"
            "## Opzioni\n\n"
            "1. **Seconda.** testo\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "REQUEST.md").write_text(body, encoding="utf-8")
            proc, payload = _format_payload("--root", str(root), "--path", "REQUEST.md")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(payload["reason"], "repeated_identifier")


if __name__ == "__main__":
    unittest.main()
