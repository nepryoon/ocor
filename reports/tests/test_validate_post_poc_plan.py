#!/usr/bin/env python3
"""Fail-closed tests for the post-PoC plan validator.

The approved backlog and the traceability plan are inputs, not outputs: these
tests do not execute a campaign and do not start a service.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "validate_post_poc_plan.py"
APPROVED_BACKLOG = ROOT / "docs" / "development_plan" / "OCOR_IMPLEMENTATION_BACKLOG.json"


def _load():
    spec = importlib.util.spec_from_file_location(
        "validate_post_poc_plan", MODULE_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _req(
    requirement_id: str,
    type_cell: str,
    release: str,
    method: str = "test",
) -> dict[str, Any]:
    return {
        "id": requirement_id,
        "title": requirement_id,
        "type": type_cell,
        "release": release,
        "method": method,
        "acceptance": f"Acceptance text for {requirement_id}.",
        "priority": "P0",
        "line": 1,
    }


class PostPocPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load()

    def test_register_matches_traceability_on_release(self) -> None:
        requirements = self.mod.load_register(ROOT)
        self.assertEqual(len(requirements), 285)
        beyond = [item for item in requirements if self.mod.is_beyond_poc(item["release"])]
        self.assertEqual(len(beyond), 93)
        traced = self.mod.load_traceability(ROOT)
        self.assertEqual(set(traced), {item["id"] for item in requirements})
        for item in requirements:
            self.assertEqual(traced[item["id"]]["register_release"], item["release"])

    def test_gate_assignment_pins(self) -> None:
        cases = (
            ("BR-016", "BR", "PoC exit / MVP entry", "G8"),
            ("BR-004", "BR", "MVP", "G8"),
            ("BR-017", "BR", "MVP", "G8"),
            ("FR-015", "FR", "MVP", "G9"),
            ("FR-024", "Funzionale", "PoC thin slice; MVP completo", "G9"),
            ("NFR-001", "NFR", "MVP", "G10"),
            ("NFR-023", "Non funzionale", "MVP", "G10"),
            ("BR-018", "BR", "Production", "G11"),
            ("FR-048", "Funzionale", "Future", "G11"),
            ("NFR-073", "NFR", "Ogni release", "G11"),
            ("NFR-038", "NFR", "PoC→Production", "G11"),
            ("FR-153", "FR", "MVP/Future", "G11"),
            ("NFR-083", "NFR", "MVP, Production", "G11"),
        )
        for requirement_id, type_cell, release, gate in cases:
            with self.subTest(requirement_id=requirement_id):
                self.assertTrue(self.mod.is_beyond_poc(release))
                self.assertEqual(self.mod.assign_gate(release, type_cell), gate)
        self.assertFalse(self.mod.is_beyond_poc("PoC"))

    def test_real_plan_is_the_generated_plan_and_passes(self) -> None:
        requirements = self.mod.load_register(ROOT)
        trace = self.mod.load_traceability(ROOT)
        workstreams = self.mod.load_workstreams(ROOT)
        generated = self.mod.build_documents(ROOT, requirements, trace, workstreams)
        on_disk = self.mod.load_documents(ROOT)
        self.assertEqual(on_disk, generated)
        findings = self.mod.validate_documents(
            on_disk, requirements, trace, workstreams
        )
        self.assertEqual(findings, [], findings[:12])

    def test_approved_plan_files_are_not_rewritten_by_the_builder(self) -> None:
        before = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                APPROVED_BACKLOG,
                ROOT / "docs" / "development_plan" / "OCOR_TRACEABILITY_PLAN.csv",
                ROOT / "docs" / "development_plan" / "OCOR_DEPENDENCY_DAG.mmd",
            )
        }
        self.mod.build_documents(
            ROOT,
            self.mod.load_register(ROOT),
            self.mod.load_traceability(ROOT),
            self.mod.load_workstreams(ROOT),
        )
        for path, digest in before.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest, path)

    def test_missing_requirement_is_rejected(self) -> None:
        documents = self._mini()
        documents["allocation"]["requirements"] = [
            row
            for row in documents["allocation"]["requirements"]
            if row["requirement_id"] != "BR-900"
        ]
        realise = self._task(documents, "OCOR-POST-G8-WS11-REALISE")
        realise["requirement_ids"] = []
        self.assertIn(
            "MISSING_REQUIREMENT",
            self._codes(documents),
        )

    def test_poc_requirement_is_rejected(self) -> None:
        documents = self._mini()
        documents["allocation"]["requirements"].append(
            {
                "gate": "G8",
                "method": "test",
                "realise_task": "OCOR-POST-G8-WS11-REALISE",
                "register_line": 1,
                "release": "PoC",
                "requirement_id": "BR-001",
                "verify_task": "OCOR-POST-G8-WS11-VERIFY",
                "workstream": "WS-11",
            }
        )
        self.assertIn("POC_REQUIREMENT", self._codes(documents))

    def test_cycle_is_rejected(self) -> None:
        documents = self._mini()
        realise = self._task(documents, "OCOR-POST-G8-WS11-REALISE")
        verify = self._task(documents, "OCOR-POST-G8-WS11-VERIFY")
        realise["hard_dependencies"] = [verify["id"]]
        self.assertIn("CYCLE", self._codes(documents))

    def test_status_and_missing_field_are_rejected(self) -> None:
        documents = self._mini()
        task = documents["backlog"]["tasks"][0]
        task["status"] = "READY"
        self.assertIn("STATUS", self._codes(documents))
        task["status"] = "PLANNED_NOT_ACTIVE"
        task.pop("rollback_procedure")
        self.assertIn("FIELD", self._codes(documents))

    def test_g4_task_and_weak_g6_are_rejected(self) -> None:
        documents = self._mini()
        documents["external"]["observations"].append(
            {
                "disposition": "OBSERVE_ONLY",
                "id": "G-4",
                "task_id": "OCOR-POST-G11-G4-REALISE",
            }
        )
        self.assertIn("G4_TASK", self._codes(documents))
        documents = self._mini()
        g6 = self._task(documents, "OCOR-POST-G11-G6-REALISE")
        g6["negative_acceptance_criteria"] = ["A skipped case is not acceptance."]
        self.assertIn("G6_CRITERIA", self._codes(documents))

    def test_prohibited_claim_and_local_path_are_rejected(self) -> None:
        documents = self._mini()
        task = documents["backlog"]["tasks"][0]
        task["objective"] += " Production readiness: GO."
        self.assertIn("PROHIBITED_CLAIM", self._codes(documents))
        task["objective"] = task["objective"].replace(" Production readiness: GO.", "")
        task["rationale"] += " See /home/luca/notes."
        self.assertIn("LOCAL_PATH", self._codes(documents))

    def test_fr048_a2a_only_restriction_is_rejected(self) -> None:
        requirements = self.mod.load_register(ROOT)
        trace = self.mod.load_traceability(ROOT)
        workstreams = self.mod.load_workstreams(ROOT)
        documents = self.mod.build_documents(ROOT, requirements, trace, workstreams)
        task = self._task(documents, "OCOR-POST-G11-WS09-REALISE")
        task["acceptance_criteria"] = [
            "FR-048 is realised only as an A2A boundary adapter behind C8, "
            "after the Product Owner decision on G7, and it stays optional."
        ]
        findings = self.mod.validate_documents(
            documents, requirements, trace, workstreams
        )
        self.assertIn("FR048_SCOPE", {item.split(":", 1)[0] for item in findings})

    def test_generated_fr048_keeps_sdk_and_a2a_parts(self) -> None:
        requirements = self.mod.load_register(ROOT)
        trace = self.mod.load_traceability(ROOT)
        workstreams = self.mod.load_workstreams(ROOT)
        documents = self.mod.build_documents(ROOT, requirements, trace, workstreams)
        task = self._task(documents, "OCOR-POST-G11-WS09-REALISE")
        text = "\n".join(task["acceptance_criteria"])
        self.assertIn(self.mod.G2_POSITIVE, text)
        self.assertIn(self.mod.FR048_SDK_POSITIVE, text)
        self.assertNotIn("FR-048 is realised only as an A2A", text)
        self.assertIn("Rust", text)
        for command in task["validation_commands"]:
            self.assertTrue(
                command.startswith("python3 "),
                command,
            )

    def test_state_and_conformance_edits_still_pass(self) -> None:
        state = ROOT / self.mod.STATE_REL
        conformance = ROOT / self.mod.CONFORMANCE_REL
        saved = {path: path.read_bytes() for path in (state, conformance)}
        try:
            for path in saved:
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertIsInstance(payload, dict)
                payload["rem0062_repair_probe"] = True
                path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(self.mod.main(["--root", str(ROOT)]), 0)
        finally:
            for path, blob in saved.items():
                path.write_bytes(blob)

    def test_register_byte_change_fails_closed(self) -> None:
        path = ROOT / self.mod.REGISTER_REL
        saved = path.read_bytes()
        try:
            path.write_bytes(saved + b"\n")
            self.assertEqual(self.mod.main(["--root", str(ROOT)]), 1)
        finally:
            path.write_bytes(saved)

    def test_load_json_rejects_malformed_bytes_and_non_objects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            path.write_bytes(b"{")
            with self.assertRaises(json.JSONDecodeError):
                self.mod._load_json(path)
            path.write_bytes(b"\xff")
            with self.assertRaises(UnicodeDecodeError):
                self.mod._load_json(path)
            path.write_text("null", encoding="utf-8")
            with self.assertRaises(ValueError):
                self.mod._load_json(path)
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                self.mod._load_json(path)

    def test_decision_request_has_no_timing_recommendation(self) -> None:
        text = (
            ROOT / "reports" / "development" / "decision_requests" / "POST-POC-BACKLOG-ACTIVATION.md"
        ).read_text(encoding="utf-8")
        self.assertIn("OPEN_PO_NORMATIVE_DECISION_REQUIRED", text)
        self.assertIn("## Opzioni", text)
        self.assertIn("## Raccomandazione", text)
        self.assertIn("Nessuna raccomandazione sul momento", text)
        options = [
            line
            for line in text.splitlines()
            if line[:3] in {"1. ", "2. ", "3. "} and line[3:5] == "**"
        ]
        self.assertEqual(len(options), 3)
        recommendation = text.split("## Raccomandazione", 1)[1]
        self.assertNotIn("opzione 1", recommendation.lower())
        self.assertNotIn("si raccomanda", recommendation.lower())

    def _mini(self) -> dict[str, Any]:
        requirements = [
            _req("BR-900", "BR", "MVP", "ispezione"),
            _req("FR-900", "FR", "MVP", "test"),
        ]
        trace = {
            "BR-900": {"workstream": "WS-11", "register_release": "MVP"},
            "FR-900": {"workstream": "WS-02", "register_release": "MVP"},
        }
        workstreams = self.mod.load_workstreams(ROOT)
        return self.mod.build_documents(ROOT, requirements, trace, workstreams)

    def _task(self, documents: dict[str, Any], task_id: str) -> dict[str, Any]:
        for task in documents["backlog"]["tasks"]:
            if task["id"] == task_id:
                return task
        self.fail(task_id)
        return {}

    def _codes(self, documents: dict[str, Any]) -> set[str]:
        requirements = [
            _req("BR-900", "BR", "MVP", "ispezione"),
            _req("FR-900", "FR", "MVP", "test"),
        ]
        trace = {
            "BR-900": {"workstream": "WS-11", "register_release": "MVP"},
            "FR-900": {"workstream": "WS-02", "register_release": "MVP"},
        }
        findings = self.mod.validate_documents(
            copy.deepcopy(documents),
            requirements,
            trace,
            self.mod.load_workstreams(ROOT),
        )
        return {item.split(":", 1)[0] for item in findings}


if __name__ == "__main__":
    unittest.main()
