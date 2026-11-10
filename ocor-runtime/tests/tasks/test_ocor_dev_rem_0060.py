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
from typing import Any

import pytest
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


def test_ncr_tests_004_conforms():
    """OCOR_TEST_STRATEGY.md :28-29 (failure codes), option D1: complete coverage of the inventory."""
    assertions = _reason_code_assertions()
    uncovered = [f"{component} {code} ({source}:{line})" for component, packages, source, line, code in CLOSED_REASON_CODES
                 if not any(code in constants and _credited(test, touched, code) & set(packages)
                            and (record or component not in RECORD_FIELD_COMPONENTS) for test, touched, constants, record in assertions)]
    assert uncovered == [], f"closed reason codes without a negative test asserting them: {uncovered}"


# LLD v1.1 :304-305: a refusal of C3 to the command C6 sent (CANONICAL_COMMIT_PENDING) ends the
# action with ACT-T31a (precondition/invariant failure, EXECUTION_FAILED) or ACT-T31b
# (revision/GatePackage drift, INVALIDATED) and its reason code. Row: (fault, code, transition).
C3_REFUSALS_AFTER_THE_SEND = (
    ("precondition-does-not-hold", "PRECONDITION_FAILED", "ACT-T31a"),
    ("invariant-does-not-hold", "INVARIANT_VIOLATION", "ACT-T31a"),
    ("concurrent-commit-on-the-target", "REVISION_CONFLICT", "ACT-T31b"),
    ("gate-package-not-resolvable-at-c3", "GATE_PACKAGE_MISMATCH", "ACT-T31b"),
)


@pytest.mark.parametrize(("fault", "code", "transition_id"), C3_REFUSALS_AFTER_THE_SEND)
def test_ncr_tests_004_the_c6_engine_ends_the_action_on_the_c3_refusal_after_the_send(
    fault: str, code: str, transition_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Option D1: the retained C6 engine (c6/engine.py) sends the governed command through the
    EMISSION-FENCE (ACT-T29) to the real C3 on PostgreSQL, which refuses it with ``code``; the
    action ends with ``transition_id`` and that reason code, not as an ambiguous send."""
    import test_ocor_dev_rem_0050 as governed_path
    import test_ocor_dev_rem_0053 as action_path
    from ocor_runtime.c3.admission import CommitAdmission, InMemoryGovernanceRecordStore
    from ocor_runtime.c3.ports import C3Error
    from ocor_runtime.c6.fsm import load_transitions
    from ocor_runtime.c7_emission import EmissionFence

    def admission(governed: Any) -> Any:
        # The C3 admission of the engine suite whose bound precondition or invariant does not
        # hold on the state, or whose record store does not resolve the frozen GatePackage.
        def holds(kind: str) -> Any:
            return lambda state: not fault.startswith(kind)

        return CommitAdmission(
            records=InMemoryGovernanceRecordStore() if fault.startswith("gate-package") else governed.records,
            fence=governed.fence,
            trusted_keys={governed_path.CONSUMER_KEYID: governed_path.CONSUMER_KEY.public_key},
            clock=governed.clock,
            preconditions={item: holds("precondition") for item in governed.preconditions},
            invariants={item: holds("invariant") for item in governed.invariants},
        )

    monkeypatch.setattr(governed_path.GovernedC3, "admission", admission)
    suite = action_path.EngineSuite()
    world = suite.world
    raced = action_path._admitted(suite) if fault.startswith("concurrent") else None
    racer = world.engine(commit_port=suite.c3, relay=EmissionFence(store=suite.store),  # type: ignore[arg-type]
                         canonical_path=suite.path, emission_outbox=suite.store)

    class RefusingC3(action_path.OrderedC3):
        """The real C3; for the concurrent commit another action commits on the same target
        after the fence of this one and before its command reaches C3."""

        def __init__(self, c3: Any, ledger: Any) -> None:
            super().__init__(c3, ledger)
            self.refusals: list[str] = []

        def commit(self, command: Any) -> Any:
            if raced is not None:
                other, other_set, other_decision = raced
                racer.execute(other, lease=suite.lease(other, other_decision), approval=other_set,
                              decision=other_decision, sink=suite.sink, at=action_path.ENGINE_NOW)
            try:
                return super().commit(command)
            except C3Error as error:
                self.refusals.append(error.reason_code)
                raise

    c3 = RefusingC3(suite.c3, world.ledger)
    engine = world.engine(commit_port=c3, relay=EmissionFence(store=suite.store),  # type: ignore[arg-type]
                          canonical_path=suite.path, emission_outbox=suite.store)
    proposal, approval_set, decision = action_path._admitted(suite)
    outcome: object
    try:
        outcome = engine.execute(proposal, lease=suite.lease(proposal, decision), approval=approval_set,
                                 decision=decision, sink=suite.sink, at=action_path.ENGINE_NOW)
    except Exception as error:  # noqa: BLE001 -- the norm fixes the transition, not the error type
        outcome = error
    action = [effect for effect in world.trace.effects if effect.correlation_id == proposal.action_instance_id]
    # the scenario: the command crossed the fence and C3 refused it with the code
    assert "ACT-T29" in [effect.transition_id for effect in action]
    assert c3.refusals == [code]
    # the norm (LLD v1.1 :304-305)
    destination = {item.transition_id: item for item in load_transitions()}[transition_id].destination
    assert world.fsm.current_state(proposal.action_instance_id) == destination, (
        f"{code}: the action stays {world.fsm.current_state(proposal.action_instance_id)} "
        f"({type(outcome).__name__}, notes {getattr(outcome, '__notes__', [])})"
    )
    assert (action[-1].transition_id, action[-1].context.get("reason_code")) == (transition_id, code)


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
