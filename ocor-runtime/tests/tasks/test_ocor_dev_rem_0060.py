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
import importlib.util
import re
import subprocess
import sys
import uuid
from functools import cache
from pathlib import Path
from typing import Any

import pytest
import yaml

from ocor_runtime.kernel.canonical import canonical_bytes, parse_i_json


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader whose mappings have unique string keys."""


def _unique_string_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode) -> dict[str, Any]:
    loader.flatten_mapping(node)
    mapping: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, str):
            raise yaml.constructor.ConstructorError(None, None, f"mapping key {key!r} is not a string", key_node.start_mark)
        if key in mapping:
            raise yaml.constructor.ConstructorError(None, None, f"duplicate mapping key {key!r}", key_node.start_mark)
        mapping[key] = loader.construct_object(value_node, deep=True)
    return mapping


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_string_mapping)


def _load_json(text: str) -> Any:
    """Parse the JSON text of a versioned file as I-JSON with the kernel codec: duplicate keys, NaN,
    Infinity and lone surrogates are refused (CanonicalizationError, a ValueError)."""
    return parse_i_json(text)


def _load_yaml(text: str) -> dict[str, Any]:
    """Parse the YAML text of a versioned contract: a mapping with unique string keys and I-JSON values
    only, checked with the kernel codec (non-finite numbers, timestamps, binary, sets and lone surrogates
    refused)."""
    loader = _UniqueKeyLoader(text)
    try:
        document = loader.get_single_data()
    finally:
        loader.dispose()
    canonical_bytes(document)
    if not isinstance(document, dict):
        raise ValueError("a versioned YAML contract is a mapping")
    return document


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
# NCP-U12-TEST-REALIGNMENT-SCOPE (2026-11-10) option A1: the mission thread exercises every capability
# through the retained component and may import from the legacy slice only the classes a retained
# signature requires as an argument, each with a comment that qualifies it as legacy and cites file and
# line of that signature; no method of those classes yields an outcome of the thread. No spikes module.
LEGACY_ARGUMENT_CLASSES = {
    "ocor_runtime.c2_identity": frozenset({"IdentityRegistry", "IdentityRecord"}),
    "ocor_runtime.c7_emission": frozenset({"EmissionFence"}),
    "ocor_runtime.c6_capabilities": frozenset({"CapabilityAuthority"}),
    "ocor_runtime.c4_marking": frozenset({"MarkingSet", "MarkingSchemeDefinition"}),
}
LEGACY_SETUP_METHODS = frozenset({"register"})
SIGNATURE_CITATION = re.compile(r"#.*\blegacy\b.*\b(?:c[1-8]|memory)/[a-z_]+\.py:\d+")


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
        document = _load_yaml((CONTRACTS / name).read_text(encoding="utf-8"))
        surface.update(f"{name}#/components/schemas/{schema}" for schema in document["components"]["schemas"])
    return surface


def _proto_messages() -> set[str]:
    text = (CONTRACTS / "ocor_registry.proto").read_text(encoding="utf-8")
    return {f"ocor_registry.proto#{name}" for name in re.findall(r"^message\s+(\w+)\s*\{", text, re.MULTILINE)}


def _add_embedded_schemas() -> set[str]:
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
                found.add(f"ADD#{_load_json(body)['$id']}")
            index = end
        index += 1
    return found


def _lld_materialised_contracts() -> set[str]:
    rows = LLD.read_text(encoding="utf-8").split("\n")[19:31]
    return set(re.findall(r"`(ocor-runtime/docs/governance_dossier/contracts/[^`]+)`", "\n".join(rows)))


def _sealed_digests() -> dict[str, str]:
    digests: dict[str, str] = {}
    for line in AUTHORITY_SEAL.read_text(encoding="utf-8").splitlines():
        digest, separator, path = line.partition("  ")
        assert separator and path.strip() and re.fullmatch(r"[0-9a-f]{64}", digest), f"malformed seal line {line!r}"
        digests[path.strip()] = digest
    return digests


# --- NCR-TESTS-001 -------------------------------------------------------------------------


def _legacy_imports(tree: ast.Module, lines: list[str]) -> tuple[list[str], set[str]]:
    """The legacy or spike imports outside option A1 and the legacy names A1 admits."""
    refused: list[str] = []
    admitted: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            refused.extend(alias.name for alias in node.names
                           if alias.name in LEGACY_MODULES or alias.name.split(".")[0] == "spikes")
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module.split(".")[0] == "spikes":
                refused.append(node.module)
            elif node.module in LEGACY_MODULES:
                allowed = LEGACY_ARGUMENT_CLASSES.get(node.module, frozenset())
                outside = [alias.name for alias in node.names if alias.name not in allowed or alias.asname]
                cited = SIGNATURE_CITATION.search(lines[node.lineno - 1])
                refused.extend(f"{node.module}.{name}" for name in outside)
                if not cited:
                    refused.append(f"{node.module} (line {node.lineno}: no legacy comment citing the retained signature)")
                admitted.update(alias.name for alias in node.names if alias.name in allowed)
    return refused, admitted


def _legacy_method_calls(tree: ast.Module, admitted: set[str]) -> list[str]:
    """Calls of methods of legacy objects other than their set-up (A1: no legacy outcome)."""
    instances = {target.id for node in ast.walk(tree) if isinstance(node, ast.Assign)
                 and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id in admitted
                 for target in node.targets if isinstance(target, ast.Name)}
    calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            owner = node.value
            legacy_owner = (isinstance(owner, ast.Name) and owner.id in instances | admitted) or (
                isinstance(owner, ast.Call) and isinstance(owner.func, ast.Name) and owner.func.id in admitted)
            if legacy_owner and node.attr not in LEGACY_SETUP_METHODS:
                calls.append(f"line {node.lineno}: {ast.unparse(node)}")
    return calls


def test_ncr_tests_001_conforms():
    """FR-172 (Register v1.1 :427), LLD v1.1 :409, NCP-U01-RETAINED-C1-BUILDERS point 4,
    NCP-U12-TEST-REALIGNMENT-SCOPE (2026-11-10) option A1."""
    source = MISSION_THREAD.read_text(encoding="utf-8")
    tree = _parse(MISSION_THREAD)
    modules = _imported_modules(tree)
    legacy, admitted = _legacy_imports(tree, source.split("\n"))
    assert legacy == [], f"the mission thread imports legacy-slice or spike modules outside option A1: {legacy}"
    calls = _legacy_method_calls(tree, admitted)
    assert calls == [], f"the mission thread obtains an outcome from a legacy class: {calls}"
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
            assert isinstance(node.value, ast.Set), "COVERED_SURFACE must be a set literal"
            for element in node.value.elts:
                assert isinstance(element, ast.Constant) and isinstance(element.value, str), "COVERED_SURFACE holds strings only"
                declared.add(element.value)
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


# --- NCR-TESTS-004 -------------------------------------------------------------------------

# NCP-U12-TEST-REALIGNMENT-SCOPE (2026-11-10) option D1: the closed reason codes that ADD v1.3, LLD v1.1
# and the LLD v1.1 par. 0.2 contracts define for C1-C8 and governed memory, with file and line; each needs
# a negative test of the suite that asserts reason_code equal to it on its component (OCOR_TEST_STRATEGY.md
# :28-29, "failure codes"). Row: (component, packages the test module exercises, source, line, code).
GATEWAY_CONTRACT = "ocor-runtime/docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml"
MEMORY_CONTRACT = "ocor-runtime/docs/governance_dossier/contracts/ocor-governed-memory.openapi.yaml"
ADD_PATH = "ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md"
LLD_PATH = "docs/OCOR_LLD_v1.1.md"
CLOSED_REASON_CODES = (
    ("C2", ('c2',), GATEWAY_CONTRACT, 454, "POLICY_DENIED"),
    ("C2", ('c2',), GATEWAY_CONTRACT, 455, "AUTHORITY_MISSING"),
    ("C2", ('c2',), GATEWAY_CONTRACT, 456, "CAPABILITY_DENIED"),
    ("C2", ('c2',), GATEWAY_CONTRACT, 457, "CONTRACT_NOT_FOUND"),
    ("C2", ('c2',), GATEWAY_CONTRACT, 458, "CONTRACT_DIGEST_MISMATCH"),
    ("C2", ('c2',), GATEWAY_CONTRACT, 459, "SCHEMA_VIOLATION"),
    ("C2", ('c2',), GATEWAY_CONTRACT, 460, "PROJECTION_NOT_READY"),
    ("C2", ('c2',), GATEWAY_CONTRACT, 461, "STALE_CONTEXT"),
    ("C2", ('c2',), GATEWAY_CONTRACT, 462, "RELEASE_MISMATCH"),
    ("C2", ('c2',), GATEWAY_CONTRACT, 463, "UNSUPPORTED_CAPABILITY"),
    ("C2", ('c2',), GATEWAY_CONTRACT, 464, "CAPABILITY_DEFERRED"),
    ("C2", ('c2',), GATEWAY_CONTRACT, 465, "CONTROL_PLANE_UNAVAILABLE"),
    ("C2", ('c2',), GATEWAY_CONTRACT, 466, "SCENARIO_ISOLATION_VIOLATION"),
    ("C2/C4", ('c2', 'c4'), LLD_PATH, 67, "MARKING_UNRESOLVED"),
    ("memory", ('memory',), MEMORY_CONTRACT, 319, "AUTHENTICATION_REQUIRED"),
    ("memory", ('memory',), MEMORY_CONTRACT, 319, "GOVERNED_CONTEXT_MISMATCH"),
    ("memory", ('memory',), MEMORY_CONTRACT, 319, "POLICY_DENIED"),
    ("memory", ('memory',), MEMORY_CONTRACT, 319, "AUTHORITY_DENIED"),
    ("memory", ('memory',), MEMORY_CONTRACT, 319, "MEMORY_NOT_FOUND"),
    ("memory", ('memory',), MEMORY_CONTRACT, 319, "MEMORY_VERSION_NOT_FOUND"),
    ("memory", ('memory',), MEMORY_CONTRACT, 319, "MEMORY_SCHEMA_INVALID"),
    ("memory", ('memory',), MEMORY_CONTRACT, 319, "MEMORY_IDEMPOTENCY_CONFLICT"),
    ("memory", ('memory',), MEMORY_CONTRACT, 319, "MEMORY_TAINTED"),
    ("memory", ('memory',), MEMORY_CONTRACT, 319, "REPRESENTATION_NOT_READY"),
    ("memory", ('memory',), MEMORY_CONTRACT, 319, "UNSUPPORTED_CAPABILITY"),
    ("memory", ('memory',), MEMORY_CONTRACT, 319, "LIFECYCLE_TRANSITION_INVALID"),
    ("memory", ('memory',), MEMORY_CONTRACT, 319, "LEGAL_HOLD_ACTIVE"),
    ("memory", ('memory',), MEMORY_CONTRACT, 319, "DELETION_INCOMPLETE"),
    ("memory", ('memory',), MEMORY_CONTRACT, 319, "STALE_POLICY"),
    ("memory", ('memory',), MEMORY_CONTRACT, 319, "STOP_EPOCH_MISMATCH"),
    ("memory", ('memory',), MEMORY_CONTRACT, 319, "CONTROL_PLANE_UNAVAILABLE"),
    ("memory", ('memory',), MEMORY_CONTRACT, 319, "INTERNAL_ERROR"),
    ("C3", ('c3',), ADD_PATH, 2569, "PRECONDITION_FAILED"),
    ("C3", ('c3',), ADD_PATH, 2569, "INVARIANT_VIOLATION"),
    ("C3", ('c3',), ADD_PATH, 2569, "REVISION_CONFLICT"),
    ("C3", ('c3',), ADD_PATH, 2569, "GATE_PACKAGE_MISMATCH"),
    ("C3", ('c3',), LLD_PATH, 97, "IDEMPOTENCY_CONFLICT"),
    ("C6", ('c6',), LLD_PATH, 264, "IDEMPOTENCY_CONFLICT"),
    ("C6", ('c6',), LLD_PATH, 304, "PRECONDITION_FAILED"),
    ("C6", ('c6',), LLD_PATH, 304, "INVARIANT_VIOLATION"),
    ("C6", ('c6',), LLD_PATH, 305, "REVISION_CONFLICT"),
    ("C6", ('c6',), LLD_PATH, 305, "GATE_PACKAGE_MISMATCH"),
    ("C6", ('c6',), LLD_PATH, 305, "GOVERNED_CONTEXT_MISMATCH"),
    ("C6", ('c6',), ADD_PATH, 2753, "SCHEMA_VIOLATION"),
    ("C6", ('c6',), ADD_PATH, 2753, "CONTRACT_REJECTED"),
    ("lease", ('kernel.governance', 'c6'), LLD_PATH, 81, "LEASE_INVALID"),
    ("lease", ('kernel.governance', 'c6'), LLD_PATH, 81, "LEASE_EXPIRED"),
    ("lease", ('kernel.governance', 'c6'), LLD_PATH, 81, "LEASE_REVOKED"),
    ("lease", ('kernel.governance', 'c6'), LLD_PATH, 81, "LEASE_CONTEXT_MISMATCH"),
    ("lease", ('kernel.governance', 'c6'), LLD_PATH, 81, "STOP_EPOCH_MISMATCH"),
    ("lease", ('kernel.governance', 'c6'), LLD_PATH, 81, "FENCING_TOKEN_STALE"),
    ("lease", ('kernel.governance', 'c6'), LLD_PATH, 81, "LEASE_ALREADY_CONSUMED"),
    ("C7", ('c7',), ADD_PATH, 3009, "NOT_IDENTIFIED"),
    ("C7", ('c7',), ADD_PATH, 3010, "INSUFFICIENT_EVIDENCE"),
    ("C7", ('c7',), ADD_PATH, 3011, "OUTSIDE_VALIDITY_ENVELOPE"),
    ("C7", ('c7',), ADD_PATH, 3012, "OUT_OF_DISTRIBUTION"),
    ("C7", ('c7',), ADD_PATH, 3013, "EXTRAPOLATIVE"),
    ("C7", ('c7',), ADD_PATH, 3014, "STALE_CONTEXT"),
    ("C7", ('c7',), ADD_PATH, 3015, "NOT_TRANSPORTABLE"),
    ("C7", ('c7',), ADD_PATH, 3016, "ASSUMPTION_VIOLATION"),
    ("C8 (TB-CXT-03)", ('c8',), ADD_PATH, 173, "CAPABILITY_DENIED"),
)
# Sets of the same documents left out of the inventory, with the reason: they are not reason codes.
NOT_REASON_CODES = {
    "LLD v1.1 :158-163 and ADD v1.3 :850 TRANSIENT/PERMANENT/POLICY_DENIED/POISON": "C5 failure classes, asserted as failure_class",
    "ADD v1.3 :170-172 DENY/REJECTED/QUARANTINED": "trust-boundary fail states that are outcomes, not codes",
    "LLD v1.1 :18 LLD_CONFORMANCE_FAILURE": "document conformance outcome, not a runtime code",
}


# Credits the static scan gives through a collaborator: the module builds the package as a
# collaborator of the component it tests and asserts the code on that component, not on the package.
# Key: (test module, package, code); value: the reason, with the lines that show it.
COLLABORATOR_CREDITS = {
    ("ocor-runtime/tests/tasks/test_ocor_dev_rem_0058.py", "c6", "SCHEMA_VIOLATION"): (
        "the C8 World builds the C6 OutcomeReconciler as the audited reconciler of the tool runtime "
        "(audited_reconciler :537-551, World.__init__ :608); SCHEMA_VIOLATION is asserted on the C8 "
        "ToolRuntimeError (:2949-2951), which c6 does not define"
    ),
}


def _credited(test: str, touched: set[str], code: str) -> set[str]:
    module = test.split("::")[0]
    return {package for package in touched if (module, package, code) not in COLLABORATOR_CREDITS}


# Option B2 of NCP-U12-UNPRODUCED-REASON-CODES: only reason_code counts. A cause_code assertion does not;
# for C6 the code must be asserted as the reason_code field of the FSM transition record (the context the
# engine persists with the transition, c6/engine.py:648-667, :707), not as the cause of the engine error.
REASON_FIELDS = frozenset({"reason_code"})
RECORD_FIELD_COMPONENTS = frozenset({"C6"})


def _asserts_reason_code(node: ast.AST) -> bool:
    return any((isinstance(n, ast.Attribute) and n.attr in REASON_FIELDS) or (isinstance(n, ast.Constant) and n.value in REASON_FIELDS)
               for n in ast.walk(node))


def _component_names(tree: ast.Module, package: str) -> set[str]:
    """Names a module imports from ``ocor_runtime.<package>`` (and its submodules)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module == f"ocor_runtime.{package}" or node.module.startswith(f"ocor_runtime.{package}."):
                names.update(alias.asname or alias.name for alias in node.names)
            elif node.module == "ocor_runtime" and any(alias.name == package.split(".")[0] for alias in node.names):
                names.update(alias.asname or alias.name for alias in node.names if alias.name == package.split(".")[0])
        elif isinstance(node, ast.Import):
            names.update((alias.asname or alias.name).split(".")[0] for alias in node.names
                         if alias.name == f"ocor_runtime.{package}" or alias.name.startswith(f"ocor_runtime.{package}."))
    return names


def _touches(node: ast.AST, names: set[str], package: str) -> bool:
    """The function names a component import, or loads the component dynamically by its dotted name."""
    dotted = re.compile(rf"^(?:ocor_runtime\.)?{re.escape(package)}(?:\.|$)")
    return any((isinstance(inner, ast.Name) and inner.id in names)
               or (isinstance(inner, ast.Constant) and isinstance(inner.value, str) and dotted.match(inner.value) is not None)
               for inner in ast.walk(node))


def _asserts_record_reason_code(node: ast.AST) -> bool:
    """The test asserts the ``reason_code`` field of a record (a mapping key), as the FSM transition record."""
    return any(isinstance(inner, ast.Assert) and any(isinstance(n, ast.Constant) and n.value == "reason_code" for n in ast.walk(inner))
               for inner in ast.walk(node))


def _reason_code_assertions() -> list[tuple[str, set[str], set[str], bool]]:
    """(test id, packages the test touches, string constants, whether it asserts the reason_code field of
    a record) of every test function that asserts a reason_code, directly or through a helper of its module that asserts or returns one; a package is
    touched when the test or one of the helpers it calls names an import of it or loads it by name."""
    packages = sorted({package for row in CLOSED_REASON_CODES for package in row[1]})
    found: list[tuple[str, set[str], set[str], bool]] = []
    for base in (RUNTIME_TESTS, ROOT / "reports/tests"):
        for path in sorted(base.rglob("test_*.py")):
            if ".venv" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
            definitions: dict[str, ast.AST] = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
            methods = {item.name: item for node in tree.body if isinstance(node, ast.ClassDef) for item in node.body if isinstance(item, ast.FunctionDef)}
            helpers = {name for name, node in {**methods, **functions}.items() if not name.startswith("test")
                       and any(isinstance(inner, (ast.Assert, ast.Return)) and _asserts_reason_code(inner) for inner in ast.walk(node))}
            imported = {package: _component_names(tree, package) for package in packages}
            # module-level tables a parametrisation names (for example ``@pytest.mark.parametrize(..., FAULTS)``)
            tables = {target.id: node.value for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None
                      for target in (node.targets if isinstance(node, ast.Assign) else [node.target]) if isinstance(target, ast.Name)}
            for node in ast.walk(tree):
                if not (isinstance(node, ast.FunctionDef) and node.name.startswith("test")):
                    continue
                called = {inner.func.id if isinstance(inner.func, ast.Name) else inner.func.attr for inner in ast.walk(node)
                          if isinstance(inner, ast.Call) and isinstance(inner.func, (ast.Name, ast.Attribute))}
                direct = any(isinstance(inner, ast.Assert) and _asserts_reason_code(inner) for inner in ast.walk(node))
                if not (direct or called & helpers):
                    continue
                parts: list[ast.AST] = [node, *node.decorator_list]
                parts += [tables[inner.id] for decorator in node.decorator_list for inner in ast.walk(decorator)
                          if isinstance(inner, ast.Name) and inner.id in tables]
                # the test, the module-level definitions it names and the fixtures it requests, two levels deep
                scope: list[ast.AST] = [node]
                frontier = {inner.id for inner in ast.walk(node) if isinstance(inner, ast.Name)} | {arg.arg for arg in node.args.args}
                for _level in range(2):
                    reached = [definitions[name] for name in frontier if name in definitions and definitions[name] not in scope]
                    scope += reached
                    frontier = {inner.id for part in reached for inner in ast.walk(part) if isinstance(inner, ast.Name)} | {
                        arg.arg for part in reached if isinstance(part, ast.FunctionDef) for arg in part.args.args}
                touched = {package for package in packages if any(_touches(part, imported[package], package) for part in scope)}
                constants = {inner.value for part in parts for inner in ast.walk(part) if isinstance(inner, ast.Constant) and isinstance(inner.value, str)}
                found.append((f"{path.relative_to(ROOT)}::{node.name}", touched, constants, _asserts_record_reason_code(node)))
    return found


def test_ncr_tests_004_inventory_is_anchored():
    """Every inventoried code is written at the cited line of its normative source."""
    for component, _packages, source, line, code in CLOSED_REASON_CODES:
        text = (ROOT / source).read_text(encoding="utf-8").split("\n")[line - 1]
        assert re.search(rf"\b{code}\b", text), f"{component} {code} is not at {source}:{line}"
    assert len({(row[0], row[4]) for row in CLOSED_REASON_CODES}) == len(CLOSED_REASON_CODES)
    # every collaborator credit removes a credit the scan gives today, so none is stale
    assertions = _reason_code_assertions()
    for module, package, code in COLLABORATOR_CREDITS:
        assert any(test.startswith(f"{module}::") and package in touched and code in constants
                   for test, touched, constants, _record in assertions), f"stale collaborator credit {module} {package} {code}"


# Known divergences: closed codes the retained component does not produce, each with the register entry
# (reports/development/NORMATIVE_CONFORMANCE_REGISTER.json, plan unit NCP-U15) that tracks it. Option A1 of
# NCP-U12-UNPRODUCED-REASON-CODES (2026-11-10), option B1 of NCP-U12-REASON-CODE-ENTRIES-PLAN (2026-11-10) and option
# A1 of NCP-U12-C6-COMMIT-REFUSAL-TRANSITIONS (2026-11-10).
# Key: (component, code); value: entry id.
KNOWN_DIVERGENCES = {
    ("C2", "CAPABILITY_DENIED"): "NCR-C2-014",
    ("C2", "SCENARIO_ISOLATION_VIOLATION"): "NCR-C2-014",
    ("C6", "SCHEMA_VIOLATION"): "NCR-C6-015",
    ("C6", "CONTRACT_REJECTED"): "NCR-C6-015",
    ("C7", "INSUFFICIENT_EVIDENCE"): "NCR-C7-008",
    ("C7", "EXTRAPOLATIVE"): "NCR-C7-008",
    ("C7", "STALE_CONTEXT"): "NCR-C7-008",
    ("C7", "NOT_TRANSPORTABLE"): "NCR-C7-008",
    # B1: the RED of the FSM record (d307a0b, lines 588-609) left the suite with this entry
    ("C6", "IDEMPOTENCY_CONFLICT"): "NCR-C6-016",
    # Option A1 of NCP-U12-C6-COMMIT-REFUSAL-TRANSITIONS (2026-11-10): the RED of ACT-T31a/ACT-T31b on a typed
    # C3 refusal after the send (689aff2, lines 469-552) left the suite with this entry
    ("C6", "PRECONDITION_FAILED"): "NCR-C6-017",
    ("C6", "INVARIANT_VIOLATION"): "NCR-C6-017",
    ("C6", "REVISION_CONFLICT"): "NCR-C6-017",
    ("C6", "GATE_PACKAGE_MISMATCH"): "NCR-C6-017",
}
REGISTER = ROOT / "reports/development/NORMATIVE_CONFORMANCE_REGISTER.json"


def _uncovered() -> list[tuple[str, str, str, int]]:
    assertions = _reason_code_assertions()
    return [(component, code, source, line) for component, packages, source, line, code in CLOSED_REASON_CODES
            if not any(code in constants and _credited(test, touched, code) & set(packages)
                       and (record or component not in RECORD_FIELD_COMPONENTS) for test, touched, constants, record in assertions)]


def test_ncr_tests_004_known_divergences_are_open_register_entries():
    """Every known divergence is an inventoried code and names an OPEN entry of its component in the register."""
    entries = {entry["id"]: entry for entry in _load_json(REGISTER.read_text(encoding="utf-8"))["entries"]}
    inventoried = {(row[0], row[4]) for row in CLOSED_REASON_CODES}
    for (component, code), entry_id in KNOWN_DIVERGENCES.items():
        assert (component, code) in inventoried, f"{component} {code} is not inventoried"
        entry = entries.get(entry_id)
        assert entry is not None and entry["status"] == "OPEN" and entry["component"] == component, (component, code, entry_id)
        assert code in entry["statement"], f"{entry_id} does not name {code}"


def test_ncr_tests_004_conforms():
    """OCOR_TEST_STRATEGY.md :28-29 (failure codes), option D1: complete coverage of the inventory, except the
    known divergences, each of which must still be uncovered (a covered one is stale)."""
    uncovered = _uncovered()
    unknown = [f"{component} {code} ({source}:{line})" for component, code, source, line in uncovered
               if (component, code) not in KNOWN_DIVERGENCES]
    assert unknown == [], f"closed reason codes without a negative test asserting them: {unknown}"
    stale = sorted(set(KNOWN_DIVERGENCES) - {(component, code) for component, code, _source, _line in uncovered})
    assert stale == [], f"known divergences now covered: {stale}"


def test_ncr_tests_004_a_proposal_of_another_governed_context_is_denied_with_the_code_on_its_transition() -> None:
    """Option B2 for C6 GOVERNED_CONTEXT_MISMATCH: the retained C6 engine denies at G-AUTHORITY a proposal
    bound to another GovernedContext and ends it with ACT-T05 (LLD v1.1 :266, fail-closed reason code);
    the code is the reason_code field of the FSM transition record, not only the cause of the error."""
    import test_ocor_dev_rem_0053 as action_path
    from ocor_runtime.c6.fsm import load_transitions

    suite = action_path.EngineSuite()
    world = suite.world
    proposal = world.proposal(suite.types["R3_HIGH_IMPACT"], action_id=f"urn:ocor:action:rem0060:{uuid.uuid4()}",
                              proposer=action_path.OPERATOR, target=action_path.TARGET,
                              governed_context_digest=action_path._sha("other-gcs"))
    approval_set = world.approval_set(proposal)
    decision = world.decide(proposal, approval_set)
    suite.denial(proposal, approval=approval_set, decision=decision, lease=suite.lease(proposal, decision))
    action = [effect for effect in world.trace.effects if effect.correlation_id == proposal.action_instance_id]
    destination = {item.transition_id: item for item in load_transitions()}["ACT-T05"].destination
    assert world.fsm.current_state(proposal.action_instance_id) == destination
    assert (action[-1].transition_id, action[-1].context.get("reason_code")) == ("ACT-T05", "GOVERNED_CONTEXT_MISMATCH")
    assert suite.untouched()


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


# --- SELF-CHECK-CHECKLIST (2026-11-08): file and process inputs of the touched modules -------
#
# The unit touches only tests. Their inputs are versioned files of the repository (contracts, ADD,
# LLD, the authority seal, the register, test sources, the golden dataset) and one process
# (protoc). A malformed input must fail the test with a typed error, never pass silently or be
# coerced: strict UTF-8, I-JSON through the kernel codec (duplicate keys, NaN, Infinity and lone
# surrogates refused), YAML restricted to I-JSON values with unique string keys, checked digest
# lines, typed protoc failures.

STRICT_PARSERS = (
    "ocor-runtime/tests/mission_thread/test_first_governed_slice.py",
    "ocor-runtime/tests/schemas/test_contract_meta_corpus.py",
    "ocor-runtime/tests/schemas/test_materialised_contract_integrity.py",
    "ocor-runtime/tests/tasks/test_ocor_dev_rem_0060.py",
    "ocor-runtime/tests/techniques/test_c6_fsm_and_lease_state_models.py",
    "ocor-runtime/tests/techniques/test_c7_golden_and_metamorphic.py",
    "ocor-runtime/tests/techniques/test_canonical_kernel_properties.py",
)
RAW_PARSERS = frozenset({"json.loads", "json.load", "yaml.safe_load", "yaml.load", "yaml.full_load", "yaml.unsafe_load"})
JSON_REFUSED = [
    pytest.param('{"a": NaN}', id="NaN"),
    pytest.param('{"a": Infinity}', id="Infinity"),
    pytest.param('{"a": -Infinity}', id="-Infinity"),
    pytest.param('{"a": [1, {"b": NaN}]}', id="nested-NaN"),
    pytest.param('{"a": 1, "a": 2}', id="duplicate-key"),
    pytest.param('{"a": {"b": 1, "b": 1}}', id="nested-duplicate-key"),
    pytest.param('{"a": "\\ud800"}', id="lone-surrogate-value"),
    pytest.param('{"\\udc00": 1}', id="lone-surrogate-key"),
    pytest.param('{"a": ["x", {"b": "\\ud83d"}]}', id="nested-lone-surrogate"),
    pytest.param('{"a": 1} 2', id="trailing-data"),
    pytest.param("", id="empty"),
    pytest.param("{a: 1}", id="not-json"),
]
YAML_REFUSED = [
    pytest.param("a: .nan", id="nan"),
    pytest.param("a: .inf", id="inf"),
    pytest.param("a: -.inf", id="minus-inf"),
    pytest.param("a: [1, {b: .NaN}]", id="nested-nan"),
    pytest.param("1: a", id="integer-key"),
    pytest.param("true: a", id="boolean-key"),
    pytest.param("~: a", id="null-key"),
    pytest.param("1.5: a", id="float-key"),
    pytest.param("[a]: b", id="sequence-key"),
    pytest.param("a: 1\na: 2", id="duplicate-key"),
    pytest.param("a:\n  b: 1\n  b: 2", id="nested-duplicate-key"),
    pytest.param("a: 2001-12-14", id="timestamp"),
    pytest.param("a: !!binary aGVsbG8=", id="binary"),
    pytest.param("a: !!set {x: null}", id="set"),
    pytest.param('a: "\\ud800"', id="lone-surrogate-value"),
    pytest.param('"\\udc00": 1', id="lone-surrogate-key"),
    pytest.param('a: [x, {b: "\\ud83d"}]', id="nested-lone-surrogate"),
    pytest.param("", id="empty"),
    pytest.param("- a", id="not-a-mapping"),
    pytest.param("a: [1, 2", id="not-yaml"),
    pytest.param("a: !!python/name:os.system", id="python-tag"),
]
LOADER_MODULES = ("meta-corpus", "integrity", "unit")


@cache
def _loaded(path: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"ocor_rem0060_{Path(path).stem}", ROOT / path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _loader_module(key: str) -> Any:
    if key == "unit":
        return sys.modules[__name__]
    return _loaded({"meta-corpus": STRICT_PARSERS[1], "integrity": STRICT_PARSERS[2]}[key])


@pytest.mark.parametrize("key", LOADER_MODULES)
@pytest.mark.parametrize("text", JSON_REFUSED)
def test_ncr_tests_002_versioned_json_is_parsed_as_strict_i_json(key: str, text: str) -> None:
    with pytest.raises(ValueError):
        _loader_module(key)._load_json(text)


@pytest.mark.parametrize("key", LOADER_MODULES)
@pytest.mark.parametrize("text", YAML_REFUSED)
def test_ncr_tests_002_versioned_yaml_is_restricted_to_i_json_values_with_unique_string_keys(key: str, text: str) -> None:
    with pytest.raises((ValueError, yaml.YAMLError)):
        _loader_module(key)._load_yaml(text)


@pytest.mark.parametrize("key", LOADER_MODULES)
def test_ncr_tests_002_well_formed_versioned_json_and_yaml_are_accepted(key: str) -> None:
    module = _loader_module(key)
    expected = {"a": "\U0001f600", "b": [1, 2.5, True, None], "c": {"d": "x"}}
    assert module._load_json('{"a": "\\ud83d\\ude00", "b": [1, 2.5, true, null], "c": {"d": "x"}}') == expected
    assert module._load_yaml('a: "\\U0001F600"\nb: [1, 2.5, true, null]\nc: {d: x}') == expected


def test_ncr_tests_002_touched_modules_read_versioned_files_strictly(tmp_path: Path) -> None:
    undecodable = tmp_path / "undecodable.txt"
    undecodable.write_bytes(b"contract \xff\xfe")
    with pytest.raises(UnicodeDecodeError):
        undecodable.read_text(encoding="utf-8")
    violations: list[str] = []
    for relative in STRICT_PARSERS:
        tree = _parse(ROOT / relative)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = ast.unparse(node.func)
            where = f"{relative}:{node.lineno}"
            if called in RAW_PARSERS and not (node.args and isinstance(node.args[0], ast.Call) and ast.unparse(node.args[0].func) == "json.dumps"):
                violations.append(f"{where} {called} parses outside the strict loaders")
            if called == "open" or called.endswith(".open"):
                violations.append(f"{where} {called} opens a file outside read_text/read_bytes")
            if called.endswith(".read_text") and [ast.unparse(keyword) for keyword in node.keywords] != ["encoding='utf-8'"]:
                violations.append(f"{where} read_text without exactly encoding='utf-8'")
            if called.endswith(".decode"):
                arguments = [ast.unparse(argument) for argument in node.args] + [ast.unparse(keyword) for keyword in node.keywords]
                if arguments not in (["'utf-8'"], ["'utf-8'", "errors='strict'"]):
                    violations.append(f"{where} decode is not strict UTF-8: {arguments}")
    assert violations == []


def _fake_protoc(behaviour: str) -> Any:
    def run(arguments: list[str], **_: Any) -> Any:
        output = next(Path(argument.split("=", 1)[1]) for argument in arguments if argument.startswith("--descriptor_set_out="))
        if behaviour == "timeout":
            raise subprocess.TimeoutExpired(arguments, 120)
        if behaviour == "cannot-start":
            raise FileNotFoundError(2, "No such file or directory", arguments[0])
        if behaviour == "failed-undecodable-stderr":
            return subprocess.CompletedProcess(arguments, 1, b"", b"protoc \xff\xfe")
        if behaviour == "failed":
            return subprocess.CompletedProcess(arguments, 1, b"", b"registry.proto:1: syntax error")
        if behaviour == "garbage-descriptor":
            output.write_bytes(b"\xff\xff\xff\xff not a descriptor set")
        return subprocess.CompletedProcess(arguments, 0, b"", b"")

    return run


@pytest.mark.parametrize("behaviour", ["timeout", "cannot-start", "failed", "failed-undecodable-stderr", "garbage-descriptor", "no-descriptor"])
def test_ncr_tests_002_protoc_failures_of_the_meta_corpus_are_typed_test_failures(behaviour: str, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _loader_module("meta-corpus")
    monkeypatch.setattr(module.subprocess, "run", _fake_protoc(behaviour))
    with pytest.raises(pytest.fail.Exception, match="protoc"):
        module._proto_pool.__wrapped__()


SEAL_LINE_REFUSED = [
    pytest.param("{digest}", id="no-separator"),
    pytest.param("  {path}", id="empty-digest"),
    pytest.param("{short}  {path}", id="short-digest"),
    pytest.param("{upper}  {path}", id="uppercase-digest"),
    pytest.param("{non_ascii}  {path}", id="non-ascii-digest"),
    pytest.param("{digest}x  {path}", id="long-digest"),
    pytest.param("{digest}  ", id="empty-path"),
]


def _seal_line(template: str) -> str:
    digest = "0" * 63 + "a"
    return template.format(
        digest=digest,
        short=digest[:63],
        upper=digest.upper(),
        non_ascii="\u0661" * 64,
        path="ocor-runtime/docs/governance_dossier/contracts/ocor_registry.proto",
    )


@pytest.mark.parametrize("key", ["integrity", "unit"])
@pytest.mark.parametrize("template", SEAL_LINE_REFUSED)
def test_ncr_tests_003_a_malformed_authority_seal_line_fails_the_test(key: str, template: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _loader_module(key)
    seal = tmp_path / "SHA256SUMS"
    seal.write_text(_seal_line(template) + "\n", encoding="utf-8")
    monkeypatch.setattr(module, "AUTHORITY_SEAL", seal)
    reader = module._sealed if key == "integrity" else module._sealed_digests
    with pytest.raises(AssertionError, match="malformed seal line"):
        reader()


# --- NCR-TESTS-001: resources and port answers of the mission thread ------------------------

MISSION_THREAD = "ocor-runtime/tests/mission_thread/test_first_governed_slice.py"


@cache
def _mission_thread() -> Any:
    """The mission-thread module, registered under its own name (its dataclasses resolve their module)."""
    name = "ocor_rem0060_mission_thread"
    spec = importlib.util.spec_from_file_location(name, ROOT / MISSION_THREAD)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _Resource:
    """A backend stand-in that records its acquisition and release and can fail at either."""

    def __init__(self, events: list[str], name: str, fail: str) -> None:
        self.events, self.name, self.fail = events, name, fail
        self._step(f"provision-{name}")

    def _step(self, step: str) -> None:
        self.events.append(step)
        if step == self.fail:
            raise OSError(f"{step} failed")

    def destroy(self) -> None:
        self._step(f"destroy-{self.name}")

    def release(self) -> None:
        self._step(f"release-{self.name}")


def _memory_world(events: list[str], fail: str) -> Any:
    from types import SimpleNamespace

    class Qdrant:
        @staticmethod
        def provision() -> _Resource:
            return _Resource(events, "qdrant", fail)

    class Bao:
        @staticmethod
        def provision() -> _Resource:
            return _Resource(events, "bao", fail)

    def backends(*, dsn: str, qdrant: _Resource, bao: _Resource) -> _Resource:
        assert (dsn, qdrant.name, bao.name) == ("dsn", "qdrant", "bao")
        return _Resource(events, "backends", fail)

    return SimpleNamespace(r=SimpleNamespace(base=SimpleNamespace(QdrantHarness=Qdrant)), OpenBaoHarness=Bao, Backends=backends)


# (failing step, expected events): every resource acquired before the failure is released, in reverse order
MEMORY_SETUP_FAILURES = [
    pytest.param("provision-qdrant", ["provision-qdrant"], id="qdrant-provision"),
    pytest.param("provision-bao", ["provision-qdrant", "provision-bao", "destroy-qdrant"], id="openbao-provision"),
    pytest.param("provision-backends", ["provision-qdrant", "provision-bao", "provision-backends", "destroy-bao", "destroy-qdrant"], id="backends"),
    pytest.param("body", ["provision-qdrant", "provision-bao", "provision-backends", "body", "release-backends", "destroy-bao", "destroy-qdrant"], id="body"),
    pytest.param("release-backends", ["provision-qdrant", "provision-bao", "provision-backends", "body", "release-backends", "destroy-bao", "destroy-qdrant"], id="release"),
    pytest.param("destroy-bao", ["provision-qdrant", "provision-bao", "provision-backends", "body", "release-backends", "destroy-bao", "destroy-qdrant"], id="openbao-destroy"),
]


@pytest.mark.parametrize(("fail", "expected"), MEMORY_SETUP_FAILURES)
def test_ncr_tests_001_the_memory_backends_of_the_mission_thread_are_released_on_every_exit(fail: str, expected: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    thread = _mission_thread()
    events: list[str] = []
    monkeypatch.setattr(thread, "memory_world", _memory_world(events, fail))
    with pytest.raises(OSError, match="failed"):
        with thread._memory_backends("dsn") as (backends, collection):
            assert (backends.name, collection) == ("backends", None)
            events.append("body")
            raise OSError("body failed")
    assert events == expected


def test_ncr_tests_001_the_memory_backends_of_the_mission_thread_are_released_after_a_clean_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    thread = _mission_thread()
    events: list[str] = []
    monkeypatch.setattr(thread, "memory_world", _memory_world(events, "none"))
    with thread._memory_backends("dsn") as (backends, _collection):
        assert backends.name == "backends"
    assert events == ["provision-qdrant", "provision-bao", "provision-backends", "release-backends", "destroy-bao", "destroy-qdrant"]


def _kafka_world(thread: Any, events: list[str], fail: str, monkeypatch: pytest.MonkeyPatch) -> None:
    class Broker:
        def create_topic(self, name: str) -> str:
            events.append("create-topic")
            if fail == "create-topic":
                raise OSError("create-topic failed")
            return name

        def destroy(self, volume: str) -> None:
            events.append(f"destroy-{volume}")

    class Kafka:
        @staticmethod
        def provision(name: str) -> tuple[Broker, str, str]:
            events.append("provision")
            if fail == "provision":
                raise thread.KafkaBrokerError("no broker")
            return Broker(), "container", "volume"

    def backbone(broker: Broker, topic: str, dsn: str) -> tuple[str, str]:
        events.append("backbone")
        if fail == "backbone":
            raise OSError("backbone failed")
        return ("backbone", dsn)

    monkeypatch.setattr(thread, "QualificationKafkaBroker", Kafka)
    monkeypatch.setattr(thread, "_Backbone", backbone)


KAFKA_SETUP_FAILURES = [
    pytest.param("create-topic", ["provision", "create-topic", "destroy-volume"], id="create-topic"),
    pytest.param("backbone", ["provision", "create-topic", "backbone", "destroy-volume"], id="backbone"),
    pytest.param("body", ["provision", "create-topic", "backbone", "body", "destroy-volume"], id="body"),
]


@pytest.mark.parametrize(("fail", "expected"), KAFKA_SETUP_FAILURES)
def test_ncr_tests_001_the_kafka_broker_of_the_mission_thread_is_destroyed_on_every_exit(fail: str, expected: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    thread = _mission_thread()
    events: list[str] = []
    _kafka_world(thread, events, fail, monkeypatch)
    with pytest.raises(OSError, match="failed"):
        with thread._kafka_backbone("dsn") as (backbone, _topic):
            assert backbone == ("backbone", "dsn")
            events.append("body")
            raise OSError("body failed")
    assert events == expected


def test_ncr_tests_001_a_kafka_broker_that_cannot_be_provisioned_fails_the_mission_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    thread = _mission_thread()
    events: list[str] = []
    _kafka_world(thread, events, "provision", monkeypatch)
    with pytest.raises(pytest.fail.Exception, match="real, isolated Kafka broker"):
        with thread._kafka_backbone("dsn"):
            events.append("body")
    assert events == ["provision"]


def _envelope(value: Any) -> Any:
    """A C5 envelope carrying ``value`` as returned by a port without an exception, unvalidated."""
    from ocor_runtime.c5.envelope import CanonicalIngestionEnvelope

    envelope = CanonicalIngestionEnvelope.__new__(CanonicalIngestionEnvelope)
    object.__setattr__(envelope, "_value", value)
    return envelope


_UNSET: Any = object()


def _delivered(payload: Any = _UNSET, digest: Any = _UNSET, *, integrity: Any = _UNSET, envelope: Any = _UNSET) -> Any:
    from ocor_runtime.c5.envelope import payload_digest
    from ocor_runtime.c5.subscription import DeliveredEvent

    if envelope is _UNSET:
        value: dict[str, Any] = {"payload": {"phase": "before-restart"} if payload is _UNSET else payload}
        if integrity is _UNSET:
            integrity = {"payload_digest": payload_digest({"phase": "before-restart"}) if digest is _UNSET else digest}
        if integrity is not None:
            value["integrity"] = integrity
        envelope = _envelope(value)
    return DeliveredEvent(subscription_id="urn:ocor:subscription:rem0060", envelope=envelope)


GOOD_DIGEST = "sha256:" + hashlib.sha256(b'{"phase":"before-restart"}').hexdigest()
MALFORMED_C5_ANSWERS = [
    pytest.param(lambda: None, "events", id="none"),
    pytest.param(lambda: [_delivered()], "events", id="list-not-tuple"),
    pytest.param(lambda: (), "events", id="fewer-events"),
    pytest.param(lambda: (_delivered(), _delivered()), "events", id="more-events"),
    pytest.param(lambda: (None,), "delivered event", id="none-event"),
    pytest.param(lambda: ({},), "delivered event", id="empty-mapping-event"),
    pytest.param(lambda: (_delivered(envelope={"payload": {"phase": "before-restart"}}),), "envelope", id="mapping-envelope"),
    pytest.param(lambda: (_delivered(envelope=_envelope(None)),), "envelope", id="envelope-of-none"),
    pytest.param(lambda: (_delivered(envelope=_envelope({"integrity": {"payload_digest": GOOD_DIGEST}})),), "payload", id="no-payload"),
    pytest.param(lambda: (_delivered([("phase", "before-restart")]),), "payload", id="payload-pairs"),
    pytest.param(lambda: (_delivered({1: "before-restart"}),), "payload", id="non-string-key"),
    pytest.param(lambda: (_delivered({"phase": float("nan")}),), "payload", id="nan-value"),
    pytest.param(lambda: (_delivered({"phase": float("inf")}),), "payload", id="infinity-value"),
    pytest.param(lambda: (_delivered({"phase": float("-inf")}),), "payload", id="minus-infinity-value"),
    pytest.param(lambda: (_delivered({"phase": 1}),), "payload", id="integer-value"),
    pytest.param(lambda: (_delivered({"phase": True}),), "payload", id="boolean-value"),
    pytest.param(lambda: (_delivered({"phase": None}),), "payload", id="null-value"),
    pytest.param(lambda: (_delivered({"phase": b"before-restart"}),), "payload", id="bytes-value"),
    pytest.param(lambda: (_delivered({"phase": {"nested": "x"}}),), "payload", id="nested-value"),
    pytest.param(lambda: (_delivered({"phase": "\ud800"}),), "payload", id="lone-surrogate-value"),
    pytest.param(lambda: (_delivered(integrity=None),), "integrity", id="no-integrity"),
    pytest.param(lambda: (_delivered(integrity=[GOOD_DIGEST]),), "integrity", id="list-integrity"),
    pytest.param(lambda: (_delivered(integrity={}),), "digest", id="empty-integrity"),
    pytest.param(lambda: (_delivered(digest=True),), "digest", id="boolean-digest"),
    pytest.param(lambda: (_delivered(digest=1),), "digest", id="integer-digest"),
    pytest.param(lambda: (_delivered(integrity={"payload_digest": None}),), "digest", id="null-digest"),
    pytest.param(lambda: (_delivered(digest=""),), "digest", id="empty-digest"),
    pytest.param(lambda: (_delivered(digest="sha256:" + "١" * 64),), "digest", id="non-ascii-digest"),
    pytest.param(lambda: (_delivered(digest=GOOD_DIGEST.upper()),), "digest", id="uppercase-digest"),
    pytest.param(lambda: (_delivered(digest=GOOD_DIGEST[7:]),), "digest", id="no-prefix-digest"),
    pytest.param(lambda: (_delivered(digest=GOOD_DIGEST + "0"),), "digest", id="long-digest"),
    pytest.param(lambda: (_delivered(digest="sha256:" + "0" * 64),), "digest", id="mismatching-digest"),
]


def _backbone_answering(thread: Any, answer: Any) -> Any:
    from types import SimpleNamespace

    backbone = thread._Backbone.__new__(thread._Backbone)
    backbone.rig = SimpleNamespace(consume=lambda count: answer)
    return backbone


@pytest.mark.parametrize(("answer", "reason"), MALFORMED_C5_ANSWERS)
def test_ncr_tests_001_a_malformed_c5_answer_fails_the_mission_thread(answer: Any, reason: str) -> None:
    thread = _mission_thread()
    with pytest.raises(pytest.fail.Exception, match=f"C5 answer: .*{reason}"):
        _backbone_answering(thread, answer()).consume(1)


def test_ncr_tests_001_a_well_formed_c5_answer_is_read_by_the_mission_thread() -> None:
    thread = _mission_thread()
    (record,) = _backbone_answering(thread, (_delivered(),)).consume(1)
    assert (record.value, record.payload_digest) == ({"phase": "before-restart"}, GOOD_DIGEST)
