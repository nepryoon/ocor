#!/usr/bin/env python3
"""Acceptance tests for DEC-212 OCOR_LANGUAGE_POLICY.md and its executable gate."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "scripts/validate_language_policy.py"
SPEC = importlib.util.spec_from_file_location("validate_language_policy", TOOL_PATH)
validate_language_policy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validate_language_policy
SPEC.loader.exec_module(validate_language_policy)

evaluate = validate_language_policy.evaluate

POSITIVE_CASES = (
    "ocor-runtime/src/ocor_runtime/canonical.py",
    "ocor-runtime/tests/test_c1_compiler.py",
    "ocor-runtime/tools/generate_contracts.py",
    "scripts/validate_language_policy.py",
    "reports/tests/test_validate_language_policy.py",
    "deploy/bootstrap/services/opa/qualify.py",
    "spikes/c3_atomicity/oracle.py",
    ".github/workflows/ocor-rccad.yml",
    "deploy/bootstrap/compose.yaml",
    "deploy/bootstrap/kubernetes/namespace.yaml",
    "ocor-runtime/schemas/ocor_runtime.proto",
    "reports/contracts/ocor-governed-memory.openapi.yaml",
    "ocor-runtime/docs/governance_dossier/contracts/ocor_registry.proto",
    "infra/fuseki/Dockerfile",
    "policy/mission_thread_authorization.rego",
    "ocor-runtime/sdk/typescript/src/index.ts",
    "docs/development_methodology/OCOR_LANGUAGE_POLICY.md",
    "reports/development/EXECUTION_STATE.json",
    "deploy/bootstrap/fuseki/config.ttl",
)

NEGATIVE_CASES = (
    "docs/notes.go",
    "scripts/legacy_helper.rb",
    "app.sh",
    "tools/experimental/client.ts",
    "src/experimental/authorization.rego",
    "notes/random.yaml",
    "src/random.proto",
    "tools/Dockerfile",
    "ocor-runtime/src/ocor_runtime/native_kernel.rs",
    "deploy/bootstrap/fuseki/other.ttl",
    "deploy/bootstrap/config.ttl",
)


class LanguagePolicyGateTests(unittest.TestCase):
    def test_policy_document_and_gate_exist(self) -> None:
        self.assertTrue((ROOT / "docs/development_methodology/OCOR_LANGUAGE_POLICY.md").is_file())
        self.assertTrue(TOOL_PATH.is_file())

    def test_positive_cases_are_authorized(self) -> None:
        violations = evaluate(list(POSITIVE_CASES))
        self.assertEqual([], violations)

    def test_negative_cases_are_each_rejected(self) -> None:
        for path in NEGATIVE_CASES:
            with self.subTest(path=path):
                violations = evaluate([path])
                self.assertEqual(1, len(violations), violations)
                self.assertEqual(path, violations[0]["path"])

    def test_negative_cases_are_not_silently_authorized_by_a_positive_case(self) -> None:
        # A single unauthorized file must fail even when mixed with an
        # authorized tree, proving the gate does not short-circuit on the
        # first PASS-worthy path.
        violations = evaluate(list(POSITIVE_CASES) + ["docs/notes.go"])
        self.assertEqual([{"path": "docs/notes.go", "extension": ".go", "reason": "extension '.go' has no authorized area for this path in OCOR_LANGUAGE_POLICY.md"}], violations)

    def test_gate_passes_on_the_real_tracked_tree(self) -> None:
        result = subprocess.run(
            [sys.executable, str(TOOL_PATH)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
