#!/usr/bin/env python3
"""Integrity test for reports/development/NORMATIVE_CONFORMANCE_REGISTER.json.

NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29), point 4.c, extended by
NORMATIVE-CONFORMANCE-PROGRAMME-SUPPLEMENT (2026-10-29), point 2. It checks
schema, unique ids and allowed values, normative anchors resolvable at HEAD,
seed and supplement coverage, the HIGH/plan_unit/blocks rules, the
IN_REMEDIATION and DEFERRED_BY_PO references, and prints the resolved entries
computed from the remediation records (never read from the register).

Since iteration 6 it also checks the remediation plan (point 4.e) and the G6/G7
proposals (point 4.f).

It stays outside CI workflows and guards: the units that touch the register
and the verifier run it locally.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REGISTER = ROOT / "reports" / "development" / "NORMATIVE_CONFORMANCE_REGISTER.json"

SEVERITIES = {"HIGH", "MEDIUM", "LOW"}
TYPES = {"MISSING", "DIVERGENT", "EXTRA", "CONFLICT"}
STATUSES = {"OPEN", "REFUTED", "DECISION_REQUIRED", "IN_REMEDIATION", "DEFERRED_BY_PO"}
ENTRY_FIELDS = {
    "id",
    "component",
    "severity",
    "type",
    "statement",
    "norm_refs",
    "requirement_ids",
    "code_refs",
    "test_refs",
    "verification",
    "seed_ref",
    "status",
    "plan_unit",
    "remediation_unit",
    "remediation_record",
    "po_decision_ref",
    "depends_on",
    "blocks",
}
REQUIREMENT_ID = re.compile(r"^(BR|FR|NFR)-[0-9]{3}$")
TASK_ID = re.compile(r"^OCOR-DEV-[0-9]{4}$")
PLAN_UNIT = re.compile(r"^NCP-U[0-9]{2}$")
SEED_ID = re.compile(r"^[A-Z0-9]+-[0-9]+$")
SUPPLEMENT_ID = re.compile(r"^NCP-S(0[1-9]|1[01])$")
LINES = re.compile(r"^([0-9]+)(?:-([0-9]+))?$")
SHA = re.compile(r"^[0-9a-f]{40}$")
PLAN_UNIT_FIELDS = (
    "scope",
    "resolves",
    "depends_on_units",
    "acceptance_criteria",
    "red_tests",
    "existing_tests_to_realign_or_adapt",
    "consumers_to_inventory",
    "requalifications",
    "g6_tasks_unblocked",
    "estimate_iterations",
)
REALIGN_KINDS = {
    "REALIGN",
    "ADAPT_CONSTRUCTION",
    "ADAPT_PRECONDITION",
    "PO_CHOICE_REQUIRED",
}
PROPOSAL_TASKS = {
    "OCOR-DEV-0060",
    "OCOR-DEV-0062",
    "OCOR-DEV-0063",
    "OCOR-DEV-0064",
    "OCOR-DEV-0065",
    "OCOR-DEV-0066",
    "OCOR-DEV-0067",
}
SEED_COUNT = 59
SUPPLEMENT_COUNT = 11


def _load() -> dict:
    return json.loads(REGISTER.read_text(encoding="utf-8"))


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _in_main_history(sha: str) -> bool:
    if not SHA.fullmatch(sha or ""):
        return False
    for ref in ("origin/main", "main"):
        if _git("merge-base", "--is-ancestor", sha, ref).returncode == 0:
            return True
    return False


def resolved_entries(register: dict) -> list[str]:
    """Entries resolved by the definition of the programme decision.

    An IN_REMEDIATION entry is resolved when its remediation record, read at
    the verified head with git show, has task_id equal to remediation_unit,
    status SEALED, a GO_FOR_EVIDENCE_SEAL independent verification whose
    head_sha is in the history of main, and lists the entry id in
    resolved_register_entries.
    """
    resolved: list[str] = []
    for entry in register.get("entries", []):
        if entry.get("status") != "IN_REMEDIATION":
            continue
        record_path = entry.get("remediation_record") or ""
        current = ROOT / record_path
        if not record_path or not current.is_file():
            continue
        try:
            record = json.loads(current.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        verification = record.get("independent_verification") or {}
        head = verification.get("head_sha") or ""
        if (
            record.get("task_id") != entry.get("remediation_unit")
            or record.get("status") != "SEALED"
            or verification.get("verdict_status") != "GO_FOR_EVIDENCE_SEAL"
            or not _in_main_history(head)
        ):
            continue
        shown = _git("show", f"{head}:{record_path}")
        if shown.returncode != 0:
            continue
        try:
            at_head = json.loads(shown.stdout)
        except json.JSONDecodeError:
            continue
        if entry["id"] in (at_head.get("resolved_register_entries") or []):
            resolved.append(entry["id"])
    return resolved


class NormativeConformanceRegisterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.register = _load()
        cls.entries = cls.register["entries"]
        cls.by_id = {entry["id"]: entry for entry in cls.entries}

    def test_canonical_json(self) -> None:
        text = REGISTER.read_text(encoding="utf-8")
        self.assertEqual(
            text, json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"
        )

    def test_top_level_schema(self) -> None:
        for key in (
            "schema_version",
            "language",
            "entries",
            "seed_coverage",
            "supplement_coverage",
            "plan_units",
            "claims",
        ):
            self.assertIn(key, self.register)
        self.assertEqual(self.register["language"], "en-GB")
        self.assertEqual(
            self.register["claims"],
            {
                "E1": 0,
                "E2": 0,
                "Verified": 0,
                "runtime_conformance": "NOT_ESTABLISHED",
                "PoC_GO": "NO-GO",
                "Production_readiness": "NO-GO",
            },
        )

    def test_entry_schema_and_allowed_values(self) -> None:
        for entry in self.entries:
            with self.subTest(entry=entry.get("id")):
                self.assertLessEqual(ENTRY_FIELDS, set(entry))
                self.assertIn(entry["severity"], SEVERITIES)
                self.assertIn(entry["type"], TYPES)
                self.assertIn(entry["status"], STATUSES)
                self.assertTrue(entry["statement"].strip())
                self.assertTrue(
                    entry["norm_refs"], "an entry needs at least one normative anchor"
                )
                for requirement in entry["requirement_ids"]:
                    self.assertRegex(requirement, REQUIREMENT_ID)
                if entry["requirement_ids"]:
                    self.assertNotEqual(
                        entry["requirement_ids"],
                        ["BR-003"],
                        "never only the generic BR-003",
                    )
                for task in entry["blocks"]:
                    self.assertRegex(task, TASK_ID)
                for dependency in entry["depends_on"]:
                    self.assertIn(dependency, self.by_id)
                verification = entry["verification"]
                self.assertTrue(verification.get("command", "").strip())
                self.assertTrue(verification.get("outcome", "").strip())
                if entry["plan_unit"]:
                    self.assertRegex(entry["plan_unit"], PLAN_UNIT)
                    self.assertIn(entry["plan_unit"], self.register["plan_units"])

    def test_ids_are_unique(self) -> None:
        ids = [entry["id"] for entry in self.entries]
        self.assertEqual(len(ids), len(set(ids)))

    def test_normative_anchors_resolve_at_head(self) -> None:
        for entry in self.entries:
            for ref in entry["norm_refs"]:
                with self.subTest(entry=entry["id"], ref=ref.get("path")):
                    path = ROOT / ref["path"]
                    self.assertTrue(path.is_file(), ref["path"])
                    match = LINES.fullmatch(str(ref["lines"]))
                    self.assertIsNotNone(match, ref["lines"])
                    assert match is not None
                    first = int(match.group(1))
                    last = int(match.group(2) or first)
                    self.assertTrue(
                        1 <= first <= last <= _line_count(path),
                        (ref["path"], ref["lines"]),
                    )

    def test_code_and_test_anchors_name_an_existing_commit(self) -> None:
        for entry in self.entries:
            for ref in entry["code_refs"] + entry["test_refs"]:
                with self.subTest(entry=entry["id"], ref=ref.get("path")):
                    self.assertRegex(ref["commit"], SHA)
                    self.assertRegex(str(ref["lines"]), LINES)
                    shown = _git("cat-file", "-e", f"{ref['commit']}:{ref['path']}")
                    self.assertEqual(
                        shown.returncode, 0, f"{ref['path']} absent at {ref['commit']}"
                    )

    def test_seed_coverage(self) -> None:
        coverage = self.register["seed_coverage"]
        self.assertEqual(
            len(coverage), SEED_COUNT, "seed_coverage must bind all 59 seed identifiers"
        )
        for seed_id, link in coverage.items():
            with self.subTest(seed=seed_id):
                self.assertRegex(seed_id, SEED_ID)
                self.assertIn(link["entry_id"], self.by_id)

    def test_supplement_coverage(self) -> None:
        coverage = self.register["supplement_coverage"]
        self.assertEqual(
            len(coverage),
            SUPPLEMENT_COUNT,
            "supplement_coverage must bind NCP-S01..NCP-S11",
        )
        self.assertEqual(
            set(coverage),
            {f"NCP-S{index:02d}" for index in range(1, SUPPLEMENT_COUNT + 1)},
        )
        for supplement_id, link in coverage.items():
            with self.subTest(supplement=supplement_id):
                self.assertRegex(supplement_id, SUPPLEMENT_ID)
                self.assertIn(link["entry_id"], self.by_id)

    def test_high_entries_have_plan_unit_and_blocks(self) -> None:
        resolved = set(resolved_entries(self.register))
        for entry in self.entries:
            if entry["severity"] != "HIGH":
                continue
            with self.subTest(entry=entry["id"]):
                if entry["status"] == "OPEN" or (
                    entry["status"] == "IN_REMEDIATION" and entry["id"] not in resolved
                ):
                    self.assertTrue(
                        entry["plan_unit"],
                        "HIGH open or unresolved entry needs a plan_unit",
                    )
                if entry["status"] in {"OPEN", "DECISION_REQUIRED", "IN_REMEDIATION"}:
                    self.assertTrue(
                        entry["blocks"]
                        or (entry.get("blocks_none_reason") or "").strip(),
                        "HIGH entry needs blocks or blocks_none_reason",
                    )

    def test_refuted_entries_block_nothing(self) -> None:
        for entry in self.entries:
            if entry["status"] == "REFUTED":
                with self.subTest(entry=entry["id"]):
                    self.assertEqual(entry["blocks"], [])

    def test_in_remediation_entries_name_unit_and_record(self) -> None:
        for entry in self.entries:
            if entry["status"] == "IN_REMEDIATION":
                with self.subTest(entry=entry["id"]):
                    self.assertRegex(
                        entry["remediation_unit"], r"^OCOR-DEV-REM-[0-9]{4}$"
                    )
                    self.assertTrue(entry["remediation_record"].strip())

    def test_deferred_entries_cite_a_matching_po_decision(self) -> None:
        for entry in self.entries:
            if entry["status"] != "DEFERRED_BY_PO":
                continue
            with self.subTest(entry=entry["id"]):
                ref = entry["po_decision_ref"]
                self.assertIsInstance(ref, dict)
                path = ROOT / ref["path"]
                self.assertTrue(path.is_file(), ref["path"])
                data = path.read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), ref["sha256"])
                self.assertIn(entry["id"], data.decode("utf-8"))

    def test_plan_units_cover_the_open_entries_in_dependency_order(self) -> None:
        """Point 4.e: every planned unit lists the entries it resolves, in order."""
        units = self.register["plan_units"]
        order = self.register.get("plan_order") or []
        if not all(unit.get("status") == "PROPOSED" for unit in units.values()):
            self.skipTest("plan not built yet")
        self.assertEqual(sorted(order), sorted(units))
        position = {unit_id: index for index, unit_id in enumerate(order)}
        for unit_id, unit in units.items():
            with self.subTest(unit=unit_id):
                for key in PLAN_UNIT_FIELDS:
                    self.assertIn(key, unit)
                self.assertTrue(unit["resolves"])
                self.assertIsInstance(unit["estimate_iterations"], int)
                for dependency in unit["depends_on_units"]:
                    self.assertLess(position[dependency], position[unit_id])
                criteria = {item["entry"] for item in unit["acceptance_criteria"]}
                reds = {item["entry"] for item in unit["red_tests"]}
                self.assertEqual(criteria, set(unit["resolves"]))
                self.assertEqual(reds, set(unit["resolves"]))
                for item in unit["acceptance_criteria"]:
                    self.assertTrue(item["norm_refs"])
                for item in unit["existing_tests_to_realign_or_adapt"]:
                    self.assertIn(item["kind"], REALIGN_KINDS)
                    self.assertTrue((ROOT / item["path"]).is_file(), item["path"])
                    self.assertTrue(item["norm_refs"])
                    self.assertEqual(unit_id, self.by_id[item["entry"]]["plan_unit"])
        for entry in self.entries:
            if entry["status"] == "OPEN" and entry["plan_unit"]:
                with self.subTest(entry=entry["id"]):
                    self.assertIn(entry["id"], units[entry["plan_unit"]]["resolves"])
                    for dependency in entry["depends_on"]:
                        other = self.by_id[dependency]["plan_unit"]
                        if other:
                            self.assertLessEqual(
                                position[other], position[entry["plan_unit"]]
                            )

    def test_g6_g7_proposals_are_requirement_specific(self) -> None:
        """Point 4.f: proposals for OCOR-DEV-0060 and 0062-0067, never BR-003 alone."""
        proposals = self.register["g6_g7_proposals"]
        if not proposals:
            self.skipTest("proposals not built yet")
        self.assertEqual(set(proposals["tasks"]), PROPOSAL_TASKS)
        for task, proposal in proposals["tasks"].items():
            with self.subTest(task=task):
                self.assertTrue(proposal["proposed_requirement_ids"])
                self.assertNotEqual(proposal["proposed_requirement_ids"], ["BR-003"])
                for requirement in proposal["proposed_requirement_ids"]:
                    self.assertRegex(requirement, REQUIREMENT_ID)
                self.assertTrue(proposal["normative_anchors"])
                for case in proposal["requirement_cases"]:
                    self.assertIn(
                        case["requirement_id"], proposal["proposed_requirement_ids"]
                    )
        fields = proposals["tasks"]["OCOR-DEV-0067"]["evidence_package_fields"]
        self.assertLessEqual(
            {"metric", "threshold", "baseline", "result", "owner", "signature"},
            set(fields["union"]),
        )

    def test_print_resolved_entries(self) -> None:
        resolved = resolved_entries(self.register)
        print(
            f"resolved_register_entries ({len(resolved)}): {', '.join(resolved) or '-'}"
        )
        for entry_id in resolved:
            self.assertIn(entry_id, self.by_id)


def _load_probe():
    path = ROOT / "scripts" / "probe_ncr_claim_identity_mission.py"
    spec = importlib.util.spec_from_file_location("probe_ncr_claim_identity_mission", path)
    if spec is None or spec.loader is None:
        raise AssertionError("probe module did not load")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProbeNcrClaimIdentityMissionTest(unittest.TestCase):
    """Advisory P2 of OCOR-DEV-REM-0064-9b2845f0e0a3-pre: the probe observes git HEAD."""

    def test_main_prints_the_git_head(self) -> None:
        probe = ROOT / "scripts" / "probe_ncr_claim_identity_mission.py"
        git = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        run = subprocess.run(
            ["python3", str(probe)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        first = run.stdout.splitlines()[0]
        self.assertEqual(first, "HEAD_OBSERVED " + git.stdout.strip())
        self.assertIn("\nCONFIRMED\n", run.stdout if run.stdout.endswith("\n") else run.stdout + "\n")

    def test_source_does_not_hardcode_the_reviewed_base_head(self) -> None:
        text = (ROOT / "scripts" / "probe_ncr_claim_identity_mission.py").read_text(encoding="utf-8")
        self.assertNotIn("41abc9cc28f1cba91b51401bcbb1bee9acdcd93b", text)

    def test_accept_head_rejects_empty_non_ascii_and_bad_form(self) -> None:
        accept = _load_probe().accept_head
        self.assertEqual(accept("a" * 40), "a" * 40)
        for bad in ("", "a" * 39, "g" * 40, "A" * 40, "à" + ("a" * 39), "a" * 39 + "\n"):
            with self.subTest(bad=bad):
                with self.assertRaises(SystemExit) as caught:
                    accept(bad)
                self.assertEqual(str(caught.exception), "HEAD_OBSERVED_INVALID")

    def test_read_repository_text_rejects_non_utf8(self) -> None:
        read = _load_probe().read_repository_text
        path = ROOT / "reports" / "tests" / "_probe_non_utf8_fixture.tmp"
        path.write_bytes(b"\xff\xfe not utf-8")
        try:
            with self.assertRaises(SystemExit) as caught:
                read(path)
            self.assertEqual(str(caught.exception), "TEXT_DECODE_REJECTED")
        finally:
            path.unlink(missing_ok=True)

    def test_line_text_rejects_bool_and_out_of_range_before_use(self) -> None:
        line_text = _load_probe().line_text
        self.assertEqual(line_text(["only"], 1), "only")
        for bad in (True, False, 0, 2, -1, 1.0):
            with self.subTest(bad=bad):
                with self.assertRaises(SystemExit) as caught:
                    line_text(["only"], bad)
                self.assertEqual(str(caught.exception), "LINE_INDEX_REJECTED")

    def test_observed_head_rejects_a_directory_without_git(self) -> None:
        observed_head = _load_probe().observed_head
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as caught:
                observed_head(Path(tmp))
            self.assertEqual(str(caught.exception), "HEAD_OBSERVED_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
