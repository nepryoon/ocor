"""OCOR-DEV-REM-0060 (NCP-U12): test-suite conformance.

Unit of NORMATIVE-CONFORMANCE-PLAN (2026-10-30); entries NCR-TESTS-001..005 of
``reports/development/NORMATIVE_CONFORMANCE_REGISTER.json``. Each test function is named
after the entry it realises (``test_ncr_tests_NNN_*``); ``test_ncr_tests_NNN_conforms`` is the
RED test of the plan unit for that entry.

Normative anchors (file:line):

* Requirement Register v1.1 FR-172 (ocor-runtime/docs/governance_dossier/registers/
  OCOR_Requirement_Register_v1.1_APPROVED.md:427): the PoC really executes every critical
  capability of the mission thread; trace and log prove the real passage through Gateway,
  Canonical State/projections, Causal/Scenario, Agent Kernel and Action Engine;
* LLD v1.1 §7.3 (docs/OCOR_LLD_v1.1.md:409): the versioned synthetic fixture really crosses
  C1-C8; NCP-U01-RETAINED-C1-BUILDERS (2026-11-01) point 4: the mission thread uses the
  conforming C1 pipeline (OaC source and signer), not the retained builders;
* LLD v1.1 §7.2 (docs/OCOR_LLD_v1.1.md:378): schema/meta tests verify closed records, exact
  field set, canonical bytes, digest and negative corpus;
* LLD v1.1 §0.2 (docs/OCOR_LLD_v1.1.md:20-31): the materialised contracts; generation and
  fixtures start exclusively from the manifested files;
* OCOR test strategy (docs/development_methodology/OCOR_TEST_STRATEGY.md:14-26): technique
  routing (property tests and differential oracle for the canonical kernel; stateful
  properties for the FSM; reference model, faults and bounded model checking for
  saga/lease/fence/outbox/deletion; golden data, metamorphic and reproducibility tests for the
  causal logic).

These tests are structural: they inspect the test suite itself, never a runtime backend.
"""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
RUNTIME_TESTS = ROOT / "ocor-runtime/tests"
MISSION_THREAD = RUNTIME_TESTS / "mission_thread/test_first_governed_slice.py"
CONTRACTS = ROOT / "ocor-runtime/docs/governance_dossier/contracts"
ADD = ROOT / "ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md"
LLD = ROOT / "docs/OCOR_LLD_v1.1.md"
AUTHORITY_SEAL = ROOT / "ocor-runtime/docs/governance_dossier/OCOR_IRB_ADD_LLD_AUTHORITY_SEAL_SHA256SUMS"
META_CORPUS = RUNTIME_TESTS / "schemas/test_contract_meta_corpus.py"
CONTRACT_INTEGRITY = RUNTIME_TESTS / "schemas/test_materialised_contract_integrity.py"

# The legacy slice of NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29), "Definizioni".
LEGACY_MODULES = frozenset(
    f"ocor_runtime.{name}"
    for name in (
        "c1_compiler",
        "c2_identity",
        "c3_store",
        "c4_marking",
        "c5_actions",
        "c6_capabilities",
        "c7_emission",
        "c8_agent",
    )
)
# FR-172 (Register v1.1 :427): Gateway, Canonical State/projections, Causal/Scenario, Agent
# Kernel and Action Engine; LLD v1.1 :409: C1-C8.
RETAINED_PACKAGES = (
    "ocor_runtime.c1",
    "ocor_runtime.c2",
    "ocor_runtime.c3",
    "ocor_runtime.c4",
    "ocor_runtime.c5",
    "ocor_runtime.c6",
    "ocor_runtime.c7",
    "ocor_runtime.c8",
)
RETAINED_C1_BUILDERS = frozenset({"RetainedCanonicalIrBuilder", "FrontendCanonicalIrBuilder"})


def _imported_modules(tree: ast.Module) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def _names(tree: ast.Module) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.alias):
            found.add(node.name.rsplit(".", 1)[-1])
    return found


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _test_modules() -> list[Path]:
    return sorted(path for path in RUNTIME_TESTS.rglob("test_*.py") if ".venv" not in path.parts)


# --- contract surfaces (LLD v1.1 §0.2, ADD v1.3 embedded schemas) ---------------------------


def _openapi_component_schemas() -> set[str]:
    surface: set[str] = set()
    for name in ("ocor-named-query-gateway.openapi.yaml", "ocor-governed-memory.openapi.yaml"):
        document = yaml.safe_load((CONTRACTS / name).read_text(encoding="utf-8"))
        surface.update(f"{name}#/components/schemas/{schema}" for schema in document["components"]["schemas"])
    return surface


def _proto_messages() -> set[str]:
    text = (CONTRACTS / "ocor_registry.proto").read_text(encoding="utf-8")
    return {f"ocor_registry.proto#{name}" for name in re.findall(r"^message\s+(\w+)\s*\{", text, re.MULTILINE)}


def _add_embedded_schemas() -> set[str]:
    import json

    lines = ADD.read_text(encoding="utf-8").split("\n")
    found: set[str] = set()
    index = 0
    while index < len(lines):
        fence = lines[index].strip()
        if fence in ("~~~json", "```json"):
            end = index + 1
            while not lines[end].strip().startswith(fence[:3]):
                end += 1
            body = "\n".join(lines[index + 1 : end])
            if '"$schema"' in body:
                found.add(f"ADD#{json.loads(body)['$id']}")
            index = end
        index += 1
    return found


def _lld_materialised_contracts() -> set[str]:
    rows = LLD.read_text(encoding="utf-8").split("\n")[19:31]
    return set(re.findall(r"`(ocor-runtime/docs/governance_dossier/contracts/[^`]+)`", "\n".join(rows)))


def _sealed_digests() -> dict[str, str]:
    digests: dict[str, str] = {}
    for line in AUTHORITY_SEAL.read_text(encoding="utf-8").splitlines():
        digest, _, path = line.partition("  ")
        digests[path.strip()] = digest
    return digests


# --- NCR-TESTS-001 -------------------------------------------------------------------------


def test_ncr_tests_001_conforms():
    """FR-172 (Register v1.1 :427), LLD v1.1 :409, NCP-U01-RETAINED-C1-BUILDERS point 4."""
    tree = _parse(MISSION_THREAD)
    modules = _imported_modules(tree)
    legacy = sorted(module for module in modules if module in LEGACY_MODULES or module.split(".")[0] == "spikes")
    assert legacy == [], f"the mission thread imports legacy-slice or spike modules: {legacy}"
    missing = [package for package in RETAINED_PACKAGES if not any(m == package or m.startswith(package + ".") for m in modules)]
    assert missing == [], f"the mission thread does not import the retained packages {missing}"
    builders = sorted(RETAINED_C1_BUILDERS & _names(tree))
    assert builders == [], f"the mission thread compiles with the retained C1 builders {builders}"


# --- NCR-TESTS-002 -------------------------------------------------------------------------


def test_ncr_tests_002_conforms():
    """LLD v1.1 :378 (closed records, exact field set, canonical bytes, digest, negative
    corpus) over every schema of the LLD v1.1 §0.2 contracts and of ADD v1.3."""
    surface = _openapi_component_schemas() | _proto_messages() | _add_embedded_schemas()
    assert len(surface) == 25 + 16 + 19 + 5
    assert META_CORPUS.is_file(), f"no schema/meta corpus test at {META_CORPUS.relative_to(ROOT)}"
    tree = _parse(META_CORPUS)
    declared: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "COVERED_SURFACE" for t in node.targets):
            declared = set(ast.literal_eval(node.value))
    assert declared == surface, f"uncovered: {sorted(surface - declared)}; extra: {sorted(declared - surface)}"
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    for check in ("closed_record", "exact_field_set", "canonical_bytes", "digest", "negative_corpus"):
        assert any(check in name for name in functions if name.startswith("test_")), f"no {check} test"


# --- NCR-TESTS-003 -------------------------------------------------------------------------


def test_ncr_tests_003_conforms():
    """LLD v1.1 :20-31: the schema-integrity test starts from the manifested contracts."""
    materialised = _lld_materialised_contracts()
    assert len(materialised) == 6
    sealed = _sealed_digests()
    assert materialised <= set(sealed)
    assert CONTRACT_INTEGRITY.is_file(), f"no integrity test at {CONTRACT_INTEGRITY.relative_to(ROOT)}"
    text = CONTRACT_INTEGRITY.read_text(encoding="utf-8")
    assert "OCOR_IRB_ADD_LLD_AUTHORITY_SEAL_SHA256SUMS" in text
    for path in sorted(materialised):
        assert Path(path).name in text, f"{path} is not checked by the integrity test"
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == sealed[path]


# --- NCR-TESTS-005 -------------------------------------------------------------------------


def _decorated_with(function: ast.FunctionDef, name: str) -> bool:
    for decorator in function.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if (isinstance(target, ast.Name) and target.id == name) or (isinstance(target, ast.Attribute) and target.attr == name):
            return True
    return False


def _subclasses(tree: ast.Module, base: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for parent in node.bases:
                if (isinstance(parent, ast.Name) and parent.id == base) or (isinstance(parent, ast.Attribute) and parent.attr == base):
                    return True
    return False


def _technique_index() -> dict[str, set[str]]:
    index: dict[str, set[str]] = {
        "property:kernel.canonical": set(),
        "stateful:c6.fsm": set(),
        "stateful:lease": set(),
        "bounded_model_checking": set(),
        "golden:c7": set(),
        "metamorphic:c7": set(),
    }
    for path in _test_modules():
        tree = _parse(path)
        modules = _imported_modules(tree)
        relative = str(path.relative_to(ROOT))
        functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")]
        if any(m.startswith("ocor_runtime.kernel.canonical") for m in modules) and any(_decorated_with(f, "given") for f in functions):
            index["property:kernel.canonical"].add(relative)
        if _subclasses(tree, "RuleBasedStateMachine"):
            if any(m.startswith("ocor_runtime.c6.fsm") for m in modules):
                index["stateful:c6.fsm"].add(relative)
            if any("lease" in m.lower() for m in modules) or "Lease" in _names(tree):
                index["stateful:lease"].add(relative)
        if any("bounded_model" in f.name for f in functions):
            index["bounded_model_checking"].add(relative)
        if any(m.startswith("ocor_runtime.c7") for m in modules):
            if any("golden" in f.name for f in functions):
                index["golden:c7"].add(relative)
            if any("metamorphic" in f.name for f in functions):
                index["metamorphic:c7"].add(relative)
    return index


def test_ncr_tests_005_conforms():
    """OCOR_TEST_STRATEGY.md:14-26 technique routing."""
    index = _technique_index()
    missing = sorted(technique for technique, modules in index.items() if not modules)
    assert missing == [], f"technique routing not applied: {missing}"
