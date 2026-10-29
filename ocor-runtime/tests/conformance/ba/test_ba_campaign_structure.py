"""OCOR-DEV-0060: structural checks of the BA-01..BA-08 qualifying campaign.

These tests take no backend fixture and are never counted as BA results. They bind the
campaign modules (``test_ba_0N_*.py``, one per BA identifier) to the normative rows they
qualify: the ``BA_CASE`` literal of each module must quote verbatim the ADD v1.3 Part I
§2.6 row and the LLD v1.1 §7.1 oracle of its BA, name a component pinned in
``infra/services.lock.json`` and run by the bootstrap Compose stack, bind requirements of ``OCOR_TRACEABILITY_PLAN.csv`` other than
the generic ``BR-003``, and declare positive and negative cases that exist, take a real
backend fixture and cannot be skipped.
"""

from __future__ import annotations

import ast
import csv
import json
import re
from pathlib import Path
from typing import Any

import yaml

CAMPAIGN_DIR = Path(__file__).resolve().parent
RUNTIME_ROOT = CAMPAIGN_DIR.parents[2]
REPOSITORY_ROOT = RUNTIME_ROOT.parent
ADD_PATH = RUNTIME_ROOT / "docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md"
LLD_PATH = REPOSITORY_ROOT / "docs/OCOR_LLD_v1.1.md"
PLAN_PATH = REPOSITORY_ROOT / "docs/development_plan/OCOR_TRACEABILITY_PLAN.csv"
SERVICES_LOCK_PATH = REPOSITORY_ROOT / "infra/services.lock.json"
COMPOSE_PATH = REPOSITORY_ROOT / "deploy/bootstrap/compose.yaml"
BA_IDS = [f"BA-0{index}" for index in range(1, 9)]
CASE_KINDS = ("positive_tests", "negative_tests", "fault_tests")
FORBIDDEN_CALLS = {"skip", "skipif", "xfail", "importorskip"}


def _modules() -> list[Path]:
    return sorted(CAMPAIGN_DIR.glob("test_ba_0[1-8]_*.py"))


def _ba_case(tree: ast.Module) -> dict[str, Any]:
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "BA_CASE"
        ):
            value = ast.literal_eval(node.value)
            assert isinstance(value, dict)
            return value
    raise AssertionError("module has no literal BA_CASE")


def _cases() -> dict[str, tuple[Path, ast.Module, dict[str, Any]]]:
    cases: dict[str, tuple[Path, ast.Module, dict[str, Any]]] = {}
    for path in _modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        case = _ba_case(tree)
        assert case["ba_id"] not in cases, f"{case['ba_id']} is declared twice"
        assert path.name.startswith(f"test_ba_0{case['ba_id'][-1]}_"), path.name
        cases[case["ba_id"]] = (path, tree, case)
    return cases


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _add_row(ba_id: str) -> str:
    rows = [
        line
        for line in ADD_PATH.read_text(encoding="utf-8").splitlines()
        if line.startswith(f"| `{ba_id}` |")
    ]
    assert len(rows) == 1, (ba_id, len(rows))
    return rows[0]


def _lld_row(ba_id: str) -> str:
    rows = [line for line in LLD_PATH.read_text(encoding="utf-8").splitlines() if line.startswith(f"| {ba_id} |")]
    assert len(rows) == 1, (ba_id, len(rows))
    return rows[0]


def test_the_campaign_has_exactly_one_module_per_ba_identifier() -> None:
    cases = _cases()
    assert sorted(cases) == BA_IDS
    assert len(_modules()) == len(BA_IDS)


def test_every_ba_case_quotes_its_normative_add_and_lld_rows_verbatim() -> None:
    for ba_id, (_, _, case) in _cases().items():
        add_row = _normalized(_add_row(ba_id))
        quotes = case["add_v1_3_part_i_2_6"]
        assert set(quotes) == {"required_property", "conformance_test"}, ba_id
        for column, quote in quotes.items():
            assert len(_normalized(quote)) >= 20, (ba_id, column)
            assert _normalized(quote) in add_row, (ba_id, column, quote)
        oracle = _normalized(case["lld_v1_1_7_1_oracle"])
        assert oracle and oracle in _normalized(_lld_row(ba_id)), (ba_id, oracle)


def test_every_ba_case_names_a_component_pinned_in_the_services_lock() -> None:
    lock = json.loads(SERVICES_LOCK_PATH.read_text(encoding="utf-8"))
    versions = {service["id"]: service["version"] for service in lock["services"]}
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    for ba_id, (_, _, case) in _cases().items():
        services = case["backend_services"]
        assert services and set(services) <= set(compose["services"]), (ba_id, services)
        assert services[0] in versions, (ba_id, services[0])
        assert versions[services[0]] in case["component_version"], (ba_id, case["component_version"])
        assert case["component"].strip(), ba_id


def test_every_ba_case_binds_specific_requirements_of_the_traceability_plan() -> None:
    with PLAN_PATH.open(encoding="utf-8", newline="") as handle:
        planned = {row["requirement_id"] for row in csv.DictReader(handle)}
    for ba_id, (_, _, case) in _cases().items():
        requirements = case["requirement_ids"]
        assert requirements and len(requirements) == len(set(requirements)), ba_id
        assert set(requirements) <= planned, (ba_id, sorted(set(requirements) - planned))
        assert "BR-003" not in requirements, ba_id
        binding = case["requirement_binding"]
        assert set(binding) == set(requirements), ba_id
        assert all(isinstance(text, str) and len(text) >= 20 for text in binding.values()), ba_id


def test_every_declared_case_exists_takes_a_backend_fixture_and_cannot_be_skipped() -> None:
    for ba_id, (path, tree, case) in _cases().items():
        functions = {
            node.name: node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        }
        prefix = f"test_ba_0{ba_id[-1]}_"
        declared: list[str] = []
        for kind in CASE_KINDS:
            names = case[kind]
            assert isinstance(names, list), (ba_id, kind)
            for name in names:
                assert name.startswith(prefix + kind.split("_")[0] + "_"), (ba_id, kind, name)
            declared += names
        assert case["positive_tests"] and case["negative_tests"], ba_id
        assert sorted(declared) == sorted(functions), (ba_id, sorted(set(functions) ^ set(declared)))
        for name, function in functions.items():
            assert function.args.args, f"{path.name}::{name} takes no backend fixture"
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr not in FORBIDDEN_CALLS, (path.name, node.attr, node.lineno)
            if isinstance(node, ast.Name):
                assert node.id not in FORBIDDEN_CALLS, (path.name, node.id, node.lineno)
