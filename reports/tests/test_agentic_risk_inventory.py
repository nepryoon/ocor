#!/usr/bin/env python3
"""The agentic risk inventory is generated, and the map does not claim conformance."""

from __future__ import annotations

import importlib.util
import json
import re
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "generate_agentic_risk_inventory.py"
ASI_NAMES = (
    ("ASI01", "Agent Goal Hijack"),
    ("ASI02", "Tool Misuse and Exploitation"),
    ("ASI03", "Identity and Privilege Abuse"),
    ("ASI04", "Agentic Supply Chain Vulnerabilities"),
    ("ASI05", "Unexpected Code Execution"),
    ("ASI06", "Memory and Context Poisoning"),
    ("ASI07", "Insecure Inter-Agent Communication"),
    ("ASI08", "Cascading Failures"),
    ("ASI09", "Human-Agent Trust Exploitation"),
    ("ASI10", "Rogue Agents"),
)
OPTION_LINE = re.compile(r"^[A-Z]?[0-9]{1,2}\. \*\*")


def _load() -> Any:
    spec = importlib.util.spec_from_file_location(
        "generate_agentic_risk_inventory", MODULE_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgenticRiskInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load()
        cls.inventory = cls.mod.build(ROOT)

    def test_rows_follow_the_ten_named_categories(self) -> None:
        rows = self.inventory["rows"]
        self.assertEqual([(row["id"], row["name"]) for row in rows], list(ASI_NAMES))
        for row in rows:
            self.assertIn(row["outcome"], ("CONTROL_PRESENT", "PARTIAL", "GAP"))

    def test_no_row_is_control_present_while_the_review_is_unsealed(self) -> None:
        completed = set(self.inventory["completed_evidence_tasks"])
        self.assertNotIn("OCOR-DEV-0062", completed)
        self.assertTrue(self.inventory["rows"])
        self.assertTrue(
            all(row["outcome"] != "CONTROL_PRESENT" for row in self.inventory["rows"])
        )

    def test_every_citation_anchor_is_on_the_cited_line(self) -> None:
        for row in self.inventory["rows"]:
            for ref in row["references"]:
                path = ROOT / ref["path"]
                self.assertTrue(path.is_file(), ref["path"])
                line = path.read_text(encoding="utf-8").splitlines()[ref["line"] - 1]
                self.assertIn(ref["anchor"], line)

    def test_register_lines_are_the_approved_v1_1_rows(self) -> None:
        lines = self.inventory["register_lines"]
        self.assertEqual(lines["NFR-038"], 292)
        self.assertEqual(lines["NFR-048"], 314)
        self.assertEqual(lines["NFR-050"], 318)

    def test_roles_come_from_the_orchestrator_and_have_no_capability_list(self) -> None:
        labels = [role["label"] for role in self.inventory["agent_roles"]]
        self.assertEqual(
            labels,
            [
                "Fusion/Identity",
                "Hypothesis",
                "Causal",
                "Policy",
                "Challenger",
                "Coordinator",
            ],
        )
        for role in self.inventory["agent_roles"]:
            self.assertEqual(role["admitted_capabilities"], [])
            self.assertEqual(
                role["capability_binding"], "ABSENT_NO_ROLE_CAPABILITY_REGISTER"
            )
            self.assertTrue(role["outputs"])

    def test_a_declared_capability_map_is_read_and_a_schema_is_not_a_tool(self) -> None:
        source = (
            "class AgentRole:\n"
            "    POLICY = 'Policy'\n"
            "ROLE_CAPABILITIES = {'POLICY': ('cap:read',)}\n"
        )
        # The repository parser accepts the real Enum form, not this shorthand.
        parsed = self.mod.parse_agent_roles(
            "from enum import Enum\n"
            "class AgentRole(Enum):\n"
            "    POLICY = 'Policy'\n"
            "ROLE_CAPABILITIES = {AgentRole.POLICY: ('cap:read',)}\n"
        )
        self.assertEqual(parsed[0]["admitted_capabilities"], ["cap:read"])
        self.assertEqual(parsed[0]["capability_binding"], "DECLARED")
        self.assertFalse(
            self.mod.tool_record(
                {
                    "tool_name": {"type": "string"},
                    "effect_class": {"enum": ["ANALYZE"]},
                    "risk_class": {"enum": ["LOW"]},
                    "approval": {"type": "object"},
                }
            )
        )
        self.assertEqual(
            self.mod.tool_record(
                {
                    "tool_name": "note",
                    "effect_class": "ANALYZE",
                    "risk_class": "LOW",
                    "approval": {"mode": "HUMAN_GATE"},
                }
            ),
            {
                "approval": {"mode": "HUMAN_GATE"},
                "effect_class": "ANALYZE",
                "risk_class": "LOW",
                "tool_name": "note",
            },
        )
        self.assertIn("POLICY", source)

    def test_contract_directories_do_not_invent_tools(self) -> None:
        for tool in self.inventory["tools"]:
            self.assertRegex(tool["tool_name"], r"^[a-z][a-z0-9_-]{0,64}$")
            self.assertIsInstance(tool["effect_class"], str)
            self.assertIsInstance(tool["risk_class"], str)
            self.assertIsInstance(tool["approval"], dict)
            self.assertTrue(tool["source"].startswith(self.mod.SCAN_ROOTS))

    def test_document_is_not_a_conformance_claim(self) -> None:
        text = (ROOT / "docs" / "security" / "OCOR_AGENTIC_RISK_MAP.md").read_text(
            encoding="utf-8"
        )
        self.assertTrue(text.startswith("# "))
        self.assertIn("not evidence", text)
        self.assertIn("not a conformance claim", text)
        self.assertIn("NFR-050", text)
        self.assertIn("E1=0", text)
        self.assertNotIn("Agent Goal Hijack occurs", text)
        for _asi, name in ASI_NAMES:
            self.assertEqual(text.count(name), 1)

    def test_committed_outputs_match_the_generator(self) -> None:
        self.assertEqual(self.mod.differences(ROOT), [])

    def test_one_decision_request_lists_every_open_row_and_blocks_nobody(self) -> None:
        path = (
            ROOT
            / "reports"
            / "development"
            / "decision_requests"
            / "AGENTIC-RISK-MAP-PARTIAL-GAPS.md"
        )
        text = path.read_text(encoding="utf-8")
        options = [line for line in text.splitlines() if OPTION_LINE.match(line)]
        self.assertEqual(len(options), 3)
        self.assertIn("non blocca alcun task", text)
        open_rows = [
            row["id"]
            for row in self.inventory["rows"]
            if row["outcome"] in ("PARTIAL", "GAP")
        ]
        self.assertTrue(open_rows)
        for identifier in open_rows:
            self.assertIn(identifier, text)
        self.assertEqual(
            json.loads(
                (ROOT / "docs" / "security" / "agentic_risk_inventory.json").read_text(
                    encoding="utf-8"
                )
            )["rows"][0]["id"],
            "ASI01",
        )


if __name__ == "__main__":
    unittest.main()
