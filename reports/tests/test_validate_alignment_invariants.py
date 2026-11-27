#!/usr/bin/env python3
"""Positive and negative cases for scripts/validate_alignment_invariants.py.

Hermetic: snapshot checks run on an in-memory tree, difference checks on a
temporary git repository with one base commit and one head commit. Every rule has
a case that passes and a case that fails for the reason the rule states, so that a
rejection for another reason is not mistaken for the rule working.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def load_validator() -> ModuleType:
    path = ROOT / "scripts" / "validate_alignment_invariants.py"
    spec = importlib.util.spec_from_file_location("validate_alignment_invariants", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V = load_validator()
FENCE = {"E1": 0, "E2": 0, "PoC_GO": "NO-GO", "Production_readiness": "NO-GO", "runtime_conformance": "NOT_ESTABLISHED"}


class MemoryTree(V.Tree):  # type: ignore[misc, name-defined]
    def __init__(self, files: dict[str, str]) -> None:
        self.entries = files

    def read(self, path: str) -> str | None:
        return self.entries.get(path)

    def exists(self, path: str) -> bool:
        prefix = path.rstrip("/") + "/"
        return path in self.entries or any(name.startswith(prefix) for name in self.entries)

    def files(self, prefix: str, suffix: str) -> list[str]:
        start = prefix.rstrip("/") + "/"
        return sorted(name for name in self.entries if name.startswith(start) and name.endswith(suffix))


def keys(check: Any) -> list[str]:
    return [item.key for item in check.findings]


def plan_tree(stated_tasks: int, stated_waves: int, gate_row: str) -> MemoryTree:
    backlog = {
        "gates": {"G0": {"required_tasks": ["OCOR-DEV-0001", "OCOR-DEV-0002"]}},
        "graph_analysis": {"parallel_waves": 2},
        "tasks": [{"id": "OCOR-DEV-0001"}, {"id": "OCOR-DEV-0002"}],
    }
    plan = (
        f"All workstreams are represented in the {stated_tasks}-task backlog.\n"
        f"The machine DAG has {stated_waves} waves.\n"
        f"| G0 | {gate_row} | entry |\n"
    )
    return MemoryTree({V.BACKLOG: json.dumps(backlog), V.PLAN_MD: plan})


class SnapshotChecks(unittest.TestCase):
    def test_plan_parity_passes_when_text_and_backlog_agree(self) -> None:
        check = V.check_plan_parity(plan_tree(2, 2, "OCOR-DEV-0001, OCOR-DEV-0002"))
        self.assertEqual(keys(check), [])

    def test_plan_parity_reports_each_disagreement(self) -> None:
        check = V.check_plan_parity(plan_tree(1, 3, "OCOR-DEV-0001"))
        self.assertEqual(keys(check), ["S01:task-count", "S01:waves", "S01:gate:G0"])

    def test_workflow_pins(self) -> None:
        pinned = "    steps:\n      - uses: actions/checkout@" + "a" * 40 + " # v4\n    runs-on: ubuntu-24.04\n"
        floating = "    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: ./local\n"
        good = V.check_workflow_pins(MemoryTree({".github/workflows/a.yml": pinned}))
        bad = V.check_workflow_pins(MemoryTree({".github/workflows/a.yml": floating}))
        self.assertEqual(keys(good), [])
        self.assertEqual(
            keys(bad),
            ["S05:.github/workflows/a.yml:runs-on:ubuntu-latest", "S05:.github/workflows/a.yml:actions/checkout@v4"],
        )

    def test_dependency_pins_and_runtime_imports(self) -> None:
        pyproject = (
            '[build-system]\nrequires = ["setuptools==80.0.0"]\n'
            '[project]\ndependencies = ["PyYAML==6.0.2", "jsonschema>=4.18"]\n'
            '[project.optional-dependencies]\ntest = ["psycopg[binary]==3.2.10"]\n'
        )
        source = "import json\nimport yaml\nimport psycopg\nfrom ocor_runtime import errors\nfrom . import local\n"
        tree = MemoryTree(
            {
                V.RUNTIME_PYPROJECT: pyproject,
                "ocor-runtime/src/ocor_runtime/__init__.py": "",
                "ocor-runtime/src/ocor_runtime/adapter.py": source,
            }
        )
        self.assertEqual(keys(V.check_dependency_pins(tree)), ["S06:jsonschema"])
        self.assertEqual(keys(V.check_runtime_imports(tree)), ["S07:psycopg"])

    def test_document_links(self) -> None:
        readme = "[plan](docs/plan.md) [ci](.github/workflows) [gone](docs/missing.md#x) [web](https://example.org)"
        tree = MemoryTree({"README.md": readme, "docs/plan.md": "", ".github/workflows/a.yml": ""})
        self.assertEqual(keys(V.check_document_links(tree)), ["S08:README.md:docs/missing.md"])

    def test_fence_parity(self) -> None:
        def tree(e1: int) -> MemoryTree:
            claims = dict(FENCE, E1=e1)
            return MemoryTree(
                {
                    V.STATE: json.dumps({"claims": claims}),
                    V.METHODOLOGY: json.dumps({"evidence_fence": {"E1": 0, "E2": 0}}),
                }
            )

        self.assertEqual(keys(V.check_fence_parity(tree(0))), [])
        self.assertEqual(keys(V.check_fence_parity(tree(1))), [f"S09:{V.STATE}:E1"])

    def test_register_status_follows_merged_units(self) -> None:
        def tree(unit_status: str) -> MemoryTree:
            state = {"remediation_status": {"REM_0047_NCP_U01": {"status": unit_status}}}
            entries = [{"id": "NCR-C1-002", "remediation_unit": "OCOR-DEV-REM-0047", "status": "IN_REMEDIATION"}]
            return MemoryTree({V.STATE: json.dumps(state), V.NCR_REGISTER: json.dumps({"entries": entries})})

        self.assertEqual(keys(V.check_register_status(tree("IN_PROGRESS"))), [])
        merged = V.check_register_status(tree("RESOLVED_VERIFIED_SEALED_MERGED"))
        self.assertEqual(keys(merged), ["S10:in-remediation-with-merged-unit"])

    def test_unreadable_input_is_not_executed_never_pass(self) -> None:
        check = V.execute("S01", V.check_plan_parity, MemoryTree({}))
        self.assertTrue(check.not_executed)
        result = V.report([check], {"S01": V.BLOCKING}, {}, {})
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["checks"][0]["status"], "NOT_EXECUTED")


class Repository:
    """Temporary git repository: files of the base commit, then of the head commit."""

    def __init__(self, base: dict[str, str], head: dict[str, str | None]) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name)
        self.git("init", "-q", "-b", "main")
        self.commit(base)
        self.base = self.git("rev-parse", "HEAD")
        self.commit(head)
        self.head = self.git("rev-parse", "HEAD")

    def git(self, *args: str) -> str:
        address = "@".join(("test", "example.org"))
        identity = ["-c", "user.name=test", "-c", f"user.email={address}", "-c", "commit.gpgsign=false"]
        done = subprocess.run(["git", "-C", str(self.path), *identity, *args], capture_output=True, text=True, check=True)
        return done.stdout.strip()

    def commit(self, files: dict[str, str] | dict[str, str | None]) -> None:
        for name, content in files.items():
            target = self.path / name
            if content is None:
                target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", "change")

    def difference(self) -> Any:
        return V.difference(self.path, self.base, self.head)

    def close(self) -> None:
        self.directory.cleanup()


BASE_FILES = {
    "inputs/normative/a.md": "source\n",
    "docs/OCOR_LLD_v1.1.md": "lld\n",
    V.DOSSIER + "registers/r.md": "register\n",
    V.STATE: json.dumps({"claims": FENCE}),
    V.METHODOLOGY: json.dumps({"evidence_fence": {"E1": 0, "E2": 0}}),
    "reports/evidence/G1/sealed.json": json.dumps({"status": "SEALED", "task_id": "T"}),
    "reports/evidence/G1/sealed.log": "raw\n",
    "reports/evidence/G1/candidate.json": json.dumps({"status": "CANDIDATE", "task_id": "T"}),
    "reports/evidence/G1/MANIFEST.json": json.dumps({"artifacts": [{"path": "sealed.json", "sha256": "1", "task_id": "T"}]}),
}


class DifferenceChecks(unittest.TestCase):
    def run_checks(self, head: dict[str, str | None]) -> dict[str, list[str]]:
        repository = Repository(BASE_FILES, head)
        self.addCleanup(repository.close)
        diff = repository.difference()
        return {identifier: keys(function(diff)) for identifier, function in V.DIFFERENCE_CHECKS}

    def test_permitted_change_passes_every_blocking_check(self) -> None:
        manifest = {
            "artifacts": [
                {"path": "sealed.json", "sha256": "1", "task_id": "T"},
                {"path": "new.json", "sha256": "2", "task_id": "U"},
            ]
        }
        found = self.run_checks(
            {
                V.DOSSIER + "registers/r2.md": "new register version\n",
                "reports/evidence/G1/new.json": json.dumps({"status": "SEALED", "tool": "scripts/verify.py"}),
                "reports/evidence/G1/candidate.json": json.dumps({"status": "SEALED", "task_id": "T"}),
                "reports/evidence/G1/MANIFEST.json": json.dumps(manifest),
                "ocor-runtime/src/x.py": "VALUE = 1\n",
            }
        )
        self.assertEqual([found[name] for name in ("D01", "D02", "D03", "D04", "D05", "D06", "D07")], [[]] * 7)

    def test_immutable_surfaces(self) -> None:
        found = self.run_checks(
            {
                "inputs/normative/b.md": "added\n",
                "docs/OCOR_LLD_v1.1.md": "edited\n",
                V.DOSSIER + "registers/r.md": None,
            }
        )
        self.assertEqual(
            found["D01"],
            ["D01:docs/OCOR_LLD_v1.1.md", "D01:inputs/normative/b.md", f"D01:{V.DOSSIER}registers/r.md"],
        )

    def test_claim_change_and_fence_change(self) -> None:
        found = self.run_checks(
            {
                V.STATE: json.dumps({"claims": dict(FENCE, PoC_GO="GO", Verified=0)}),
                V.METHODOLOGY: json.dumps({"evidence_fence": {"E1": 1, "E2": 0}}),
            }
        )
        self.assertEqual(found["D02"], [f"D02:{V.STATE}:PoC_GO", f"D02:{V.METHODOLOGY}:evidence_fence"])

    def test_sealed_evidence_is_append_only(self) -> None:
        found = self.run_checks(
            {
                "reports/evidence/G1/sealed.json": json.dumps({"status": "SEALED", "task_id": "changed"}),
                "reports/evidence/G1/sealed.log": "rewritten\n",
                "reports/evidence/G1/candidate.json": None,
                "reports/evidence/G1/MANIFEST.json": json.dumps({"artifacts": []}),
            }
        )
        self.assertEqual(
            found["D03"],
            [
                "D03:reports/evidence/G1/MANIFEST.json:sealed.json",
                "D03:reports/evidence/G1/candidate.json",
                "D03:reports/evidence/G1/sealed.json",
                "D03:reports/evidence/G1/sealed.log",
            ],
        )

    def test_out_of_repo_tool_personal_data_workflow_and_control_surface(self) -> None:
        # Fixture strings are assembled here so that this file holds no address or home path of its own.
        home = "/" + "home"
        record = {"tool": "~/.ocor-codex/unit/check_evidence.py", "contact": "@".join(("someone", "mail.example.net"))}
        found = self.run_checks(
            {
                "reports/assurance/U/record.json": json.dumps(record),
                "reports/assurance/U/notes.md": f"run in {home}/someone/projects and {home}/runner/work\n",
                ".github/workflows/new.yml": "jobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n",
            }
        )
        self.assertEqual(found["D04"], ["D04:reports/assurance/U/record.json:~/.ocor-codex/unit/check_evidence.py"])
        self.assertEqual(
            found["D05"],
            ["D05:reports/assurance/U/notes.md:home path", "D05:reports/assurance/U/record.json:e-mail address"],
        )
        self.assertEqual(
            found["D06"],
            ["D06:.github/workflows/new.yml:runs-on:ubuntu-latest", "D06:.github/workflows/new.yml:actions/checkout@v4"],
        )
        self.assertEqual(found["D07"], ["D07:.github/workflows/new.yml"])


class BaselineAndReport(unittest.TestCase):
    def finding(self, identifier: str, key: str) -> Any:
        check = V.Check(identifier, "title")
        check.add(key, "detail")
        return check

    def test_new_finding_fails_only_in_a_blocking_check(self) -> None:
        advisory = V.report([self.finding("S05", "x")], {}, {}, {})
        blocking = V.report([self.finding("S05", "x")], {"S05": V.BLOCKING}, {}, {})
        default_blocking = V.report([self.finding("D01", "inputs/a")], {}, {}, {})
        self.assertEqual((advisory["status"], blocking["status"], default_blocking["status"]), ("PASS", "FAIL", "FAIL"))

    def test_baselined_finding_does_not_fail_and_a_second_one_does(self) -> None:
        check = self.finding("S05", "x")
        accepted = {"S05:x": "F-08"}
        self.assertEqual(V.report([check], {"S05": V.BLOCKING}, accepted, {})["checks"][0]["status"], "BASELINED")
        check.add("y", "detail")
        result = V.report([check], {"S05": V.BLOCKING}, accepted, {})
        self.assertEqual((result["status"], result["summary"]["blocking_new_findings"]), ("FAIL", 1))

    def test_baseline_round_trip_and_rejections(self) -> None:
        document = V.baseline_document([self.finding("S05", "x")], "c" * 40, "F-08")
        modes, accepted = V.load_baseline(json.dumps(document))
        self.assertEqual((modes["D01"], modes["S05"], accepted), (V.BLOCKING, V.ADVISORY, {"S05:x": "F-08"}))
        with self.assertRaises(V.ValidatorError):
            V.load_baseline(json.dumps({"schema": "other"}))
        with self.assertRaises(V.ValidatorError):
            V.load_baseline(json.dumps(dict(document, modes={"S05": "OFF"})))


if __name__ == "__main__":
    unittest.main()
