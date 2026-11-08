"""OCOR-DEV-REM-0058 (NCP-U10): C8 Governed Agent Kernel conformance.

Unit of NORMATIVE-CONFORMANCE-PLAN (2026-10-30); entries NCR-C8-001..005, 007 and 008 of
``reports/development/NORMATIVE_CONFORMANCE_REGISTER.json``. Each test function is named
after the entry it realises (``test_ncr_c8_NNN_*``); ``test_ncr_c8_NNN_conforms`` is the RED
test of the plan unit for that entry.

Normative anchors (file:line):

* ADD v1.3 §3.5 MCP Governed Tool Contract, schema ``urn:ocor:schema:mcp-tool-contract:1.2``
  (ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:1589-1985, required
  fields :1599-1620, ``error_codes`` enum :1759-1778); every ``tools/call`` carries an invocation
  envelope and non allow-listed tools are not exportable capabilities (same file :1988);
* ADD v1.3 §4.3.1 invariant 4: every tool call is allow-listed, schema-bound,
  parameter-constrained and mediated by Kernel, Gateway and Policy Engine (same file :3117);
* Requirement Register v1.1 (ocor-runtime/docs/governance_dossier/registers/
  OCOR_Requirement_Register_v1.1_APPROVED.md) FR-108 :255 (an incomplete contract is not
  exported) and FR-127 :277 (schema validation, provenance or taint, allow-list, parameter
  constraints, sandbox and egress policy before and after every tool call).
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from ocor_runtime.kernel.canonical import canonical_bytes

ROOT = Path(__file__).resolve().parents[3]
ADD = ROOT / "ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md"
CONTEXT_REF = "urn:sha256:" + "d" * 64

ADD_ERROR_CODES = (
    "POLICY_DENIED",
    "AUTHORITY_MISSING",
    "CAPABILITY_DENIED",
    "APPROVAL_REQUIRED",
    "APPROVAL_EXPIRED",
    "CAPABILITY_REVOKED",
    "BUDGET_EXCEEDED",
    "SCHEMA_VIOLATION",
    "STALE_CONTEXT",
    "EMERGENCY_STOP_ACTIVE",
    "EXECUTION_UNKNOWN",
    "COMPENSATION_REQUIRED",
    "COMPENSATION_UNKNOWN",
)


def add_tool_contract_schema() -> dict[str, Any]:
    """The JSON block of ADD v1.3 §3.5, read from the approved baseline itself."""
    lines = ADD.read_text(encoding="utf-8").split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith("## 3.5 MCP Governed Tool Contract"))
    begin = next(i for i in range(start, len(lines)) if lines[i] == "~~~json")
    end = next(i for i in range(begin + 1, len(lines)) if lines[i] == "~~~")
    return json.loads("\n".join(lines[begin + 1 : end]))


def wire_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


INPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["name"],
    "properties": {"name": {"type": "string", "pattern": "^svc-[0-9]{1,4}$"}},
}
OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "string",
    "maxLength": 64,
}
INPUT_PIN = {"schema_id": "urn:ocor:schema:tool:restart-service:input", "version": "1.0.0", "digest": wire_digest(INPUT_SCHEMA)}
OUTPUT_PIN = {"schema_id": "urn:ocor:schema:tool:restart-service:output", "version": "1.0.0", "digest": wire_digest(OUTPUT_SCHEMA)}


def contract_body(**changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "contract_id": "urn:ocor:tool-contract:restart-service",
        "version": "1.0.0",
        "governed_context_ref": CONTEXT_REF,
        "capability_id": "urn:ocor:capability:tool:restart-service",
        "input_schema": dict(INPUT_PIN),
        "output_schema": dict(OUTPUT_PIN),
        "effect_class": "ANALYZE",
        "risk_class": "LOW",
        "allowed_autonomy_tiers": ["ANALYZE", "SIMULATE"],
        "preconditions": [],
        "policy_refs": ["urn:ocor:policy:c8:tool-call"],
        "approval": {"mode": "NONE", "self_approval_allowed": False, "timeout_action": "DENY"},
        "idempotency": {"scope": "REQUEST", "key_required": True, "duplicate_semantics": "REPLAY_RECEIPT"},
        "timeout_ms": 5000,
        "retry": {"retry_safe": False, "max_attempts": 1},
        "compensation": {"mode": "NOT_APPLICABLE", "irreversibility_class": "REVERSIBLE"},
        "provenance_requirements": {
            "record_input_digest": True,
            "record_output_digest": True,
            "record_policy_decision": True,
            "record_actor_chain": True,
            "record_tool_binding": True,
        },
        "evidence_requirements": {"input_evidence": "OPTIONAL", "output_evidence": "OPTIONAL", "minimum_count": 0},
        "error_codes": ["POLICY_DENIED", "CAPABILITY_DENIED", "SCHEMA_VIOLATION", "EXECUTION_UNKNOWN"],
    }
    body.update(changes)
    return body


def sealed(body: dict[str, Any]) -> dict[str, Any]:
    document = copy.deepcopy(body)
    document.pop("contract_digest", None)
    document["contract_digest"] = wire_digest(document)
    return document


def contract_document(**changes: Any) -> dict[str, Any]:
    return sealed(contract_body(**changes))


def catalog() -> Any:
    from ocor_runtime.c8.tool_contract import SchemaCatalog

    schemas = SchemaCatalog()
    schemas.add(INPUT_PIN["schema_id"], INPUT_PIN["version"], INPUT_SCHEMA)
    schemas.add(OUTPUT_PIN["schema_id"], OUTPUT_PIN["version"], OUTPUT_SCHEMA)
    return schemas


def restart_registry(effects: list[str], *, egress: tuple[str, ...] = ("svc-registry.ocor.internal",), adapter: Any = None) -> Any:
    from ocor_runtime.c8.tool_contract import ToolBinding, ToolContract, ToolRegistry, egress_checkpoint

    def restart_service(name: str) -> str:
        egress_checkpoint("svc-registry.ocor.internal")
        effects.append(name)
        return f"restarted {name}"

    contract = ToolContract.from_document(contract_document(), schemas=catalog())
    registry = ToolRegistry(governed_context_ref=CONTEXT_REF, schemas=catalog())
    registry.register(
        contract,
        ToolBinding(
            tool_name="restart_service",
            binding_id="urn:ocor:tool-binding:restart-service:local",
            contract_id=contract.contract_id,
            contract_version=contract.version,
            contract_digest=contract.contract_digest,
            adapter=adapter or restart_service,
            egress_destinations=egress,
        ),
    )
    return registry


def reason(excinfo: pytest.ExceptionInfo[BaseException]) -> str:
    return str(getattr(excinfo.value, "reason_code", ""))


# --- NCR-C8-004: contract-bound tool registry (ADD v1.3 §3.5; FR-108; FR-127) ---------------------


def test_ncr_c8_004_conforms() -> None:
    """RED of NCR-C8-004: a Tool Contract exists in C8 with the ADD v1.3 §3.5 schema, an
    incomplete contract is not exported, arguments are schema-bound before the adapter runs and
    every reason code the C8 tool runtime raises belongs to the closed error_codes enum."""
    from ocor_runtime.c8 import tool_runtime
    from ocor_runtime.c8.tool_contract import TOOL_CONTRACT_SCHEMA, TOOL_ERROR_CODES, ToolContract, ToolContractError

    assert TOOL_CONTRACT_SCHEMA == add_tool_contract_schema()
    assert TOOL_ERROR_CODES == ADD_ERROR_CODES
    for field in add_tool_contract_schema()["required"]:
        incomplete = contract_document()
        incomplete.pop(field)
        if field != "contract_digest":
            incomplete = sealed(incomplete)
        with pytest.raises(ToolContractError) as excinfo:
            ToolContract.from_document(incomplete, schemas=catalog())
        assert reason(excinfo) == "SCHEMA_VIOLATION", field
    effects: list[str] = []
    registry = restart_registry(effects)
    with pytest.raises(ToolContractError) as excinfo:
        registry.invoke("restart_service", (), {"name": "svc-1; rm -rf /"})
    assert reason(excinfo) == "SCHEMA_VIOLATION"
    assert effects == []
    assert set(tool_runtime.TOOL_RUNTIME_REASON_CODES) <= set(TOOL_ERROR_CODES)


def test_ncr_c8_004_the_contract_schema_is_the_add_block_and_meta_validates() -> None:
    from jsonschema import Draft202012Validator
    from ocor_runtime.c8.tool_contract import TOOL_CONTRACT_SCHEMA

    Draft202012Validator.check_schema(TOOL_CONTRACT_SCHEMA)
    assert TOOL_CONTRACT_SCHEMA["$id"] == "urn:ocor:schema:mcp-tool-contract:1.2"
    assert TOOL_CONTRACT_SCHEMA == add_tool_contract_schema()


def _approval(mode: str, **extra: Any) -> dict[str, Any]:
    return {"mode": mode, "self_approval_allowed": False, "timeout_action": "DENY", **extra}


EXECUTE_APPROVED = {
    "effect_class": "EXECUTE_APPROVED_ACTION",
    "allowed_autonomy_tiers": ["EXECUTE_APPROVED"],
    "approval": _approval("HUMAN_GATE", independent_approver_count=1, required_approver_roles=["urn:ocor:role:safety-officer"]),
    "idempotency": {"scope": "RESOURCE", "key_required": True, "duplicate_semantics": "REJECT_DUPLICATE"},
    "evidence_requirements": {"input_evidence": "REQUIRED", "output_evidence": "REQUIRED", "minimum_count": 1},
    "error_codes": ["EXECUTION_UNKNOWN", "POLICY_DENIED"],
    "compensation": {"mode": "NOT_APPLICABLE", "irreversibility_class": "IRREVERSIBLE"},
}
DUAL = _approval("DUAL_CONTROL", independent_approver_count=2, required_approver_roles=["urn:ocor:role:safety-officer"])

# One positive and one negative case for every conditional branch of the schema (the retry
# branch and the ten allOf branches), so that a refusal is proven for the branch's own reason.
BRANCH_CASES = [
    ("retry_safe_false", {"retry": {"retry_safe": False, "max_attempts": 1}}, {"retry": {"retry_safe": False, "max_attempts": 2}}),
    ("retry_safe_true_is_outside_the_branch", {"retry": {"retry_safe": True, "max_attempts": 3, "backoff": ["PT1S"]}}, {"retry": {"retry_safe": False, "max_attempts": 3, "backoff": ["PT1S"]}}),
    ("high_risk_dual_control", {"risk_class": "HIGH", "approval": DUAL}, {"risk_class": "HIGH", "approval": _approval("HUMAN_GATE", independent_approver_count=1, required_approver_roles=["urn:ocor:role:a"])}),
    ("critical_risk_two_approvers", {"risk_class": "CRITICAL", "approval": DUAL}, {"risk_class": "CRITICAL", "approval": _approval("DUAL_CONTROL")}),
    ("execute_approved_tier", EXECUTE_APPROVED, {**EXECUTE_APPROVED, "allowed_autonomy_tiers": ["PROPOSE"]}),
    ("execute_approved_idempotency", EXECUTE_APPROVED, {**EXECUTE_APPROVED, "idempotency": {"scope": "NONE", "key_required": True, "duplicate_semantics": "NOT_APPLICABLE"}}),
    ("execute_approved_approval_mode", EXECUTE_APPROVED, {**EXECUTE_APPROVED, "approval": _approval("NONE", independent_approver_count=1, required_approver_roles=["urn:ocor:role:a"])}),
    ("execute_approved_error_codes", EXECUTE_APPROVED, {**EXECUTE_APPROVED, "error_codes": ["POLICY_DENIED"]}),
    ("execute_approved_evidence", EXECUTE_APPROVED, {**EXECUTE_APPROVED, "evidence_requirements": {"input_evidence": "OPTIONAL", "output_evidence": "REQUIRED", "minimum_count": 1}}),
    ("dual_control_two", {"approval": DUAL}, {"approval": _approval("DUAL_CONTROL", independent_approver_count=1)}),
    ("human_authorized_compensation", {"compensation": {"mode": "HUMAN_AUTHORIZED", "compensation_contract_id": "urn:ocor:tool-contract:undo", "irreversibility_class": "COMPENSATABLE"}}, {"compensation": {"mode": "HUMAN_AUTHORIZED", "irreversibility_class": "COMPENSATABLE"}}),
    ("human_gate_roles", {"approval": _approval("HUMAN_GATE", independent_approver_count=1, required_approver_roles=["urn:ocor:role:a"])}, {"approval": _approval("HUMAN_GATE", independent_approver_count=1)}),
    ("propose_tier", {"effect_class": "PROPOSE_ACTION", "allowed_autonomy_tiers": ["PROPOSE"]}, {"effect_class": "PROPOSE_ACTION", "allowed_autonomy_tiers": ["ANALYZE"]}),
    ("simulate_tier", {"effect_class": "SIMULATE", "allowed_autonomy_tiers": ["SIMULATE"]}, {"effect_class": "SIMULATE", "allowed_autonomy_tiers": ["ANALYZE"]}),
    ("analyze_tier", {"effect_class": "ANALYZE", "allowed_autonomy_tiers": ["ANALYZE"]}, {"effect_class": "ANALYZE", "allowed_autonomy_tiers": ["OBSERVE"]}),
    ("read_only_tier", {"effect_class": "READ_ONLY", "allowed_autonomy_tiers": ["OBSERVE"]}, {"effect_class": "READ_ONLY", "allowed_autonomy_tiers": ["OBSERVE", "EXECUTE_APPROVED"]}),
]


@pytest.mark.parametrize(("branch", "positive", "negative"), BRANCH_CASES, ids=[case[0] for case in BRANCH_CASES])
def test_ncr_c8_004_each_conditional_branch_admits_its_positive_and_refuses_its_negative(
    branch: str, positive: dict[str, Any], negative: dict[str, Any]
) -> None:
    from jsonschema import Draft202012Validator
    from ocor_runtime.c8.tool_contract import TOOL_CONTRACT_SCHEMA, ToolContract, ToolContractError

    validator = Draft202012Validator(TOOL_CONTRACT_SCHEMA)
    good = contract_document(**positive)
    bad = contract_document(**negative)
    assert list(validator.iter_errors(good)) == [], branch
    assert ToolContract.from_document(good, schemas=catalog()).contract_digest == good["contract_digest"]
    errors = list(validator.iter_errors(bad))
    assert errors, branch
    # the refusal comes from the conditional branch (allOf / if-then), not from another rule
    assert all("allOf" in error.absolute_schema_path or "then" in error.absolute_schema_path for error in errors), (branch, errors)
    with pytest.raises(ToolContractError) as excinfo:
        ToolContract.from_document(bad, schemas=catalog())
    assert reason(excinfo) == "SCHEMA_VIOLATION"


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param(lambda d: d.__setitem__("contract_digest", "sha256:" + "0" * 64), id="digest_of_another_body"),
        pytest.param(lambda d: d.__setitem__("timeout_ms", 6000), id="body_changed_after_sealing"),
        pytest.param(lambda d: d.__setitem__("contract_digest", "urn:sha256:" + "0" * 64), id="digest_not_in_wire_form"),
        pytest.param(lambda d: d.__setitem__("extra", True), id="field_outside_the_closed_schema"),
    ],
)
def test_ncr_c8_004_a_contract_whose_digest_does_not_hold_is_refused(tamper: Any) -> None:
    from ocor_runtime.c8.tool_contract import ToolContract, ToolContractError

    document = contract_document()
    tamper(document)
    with pytest.raises(ToolContractError) as excinfo:
        ToolContract.from_document(document, schemas=catalog())
    assert reason(excinfo) == "SCHEMA_VIOLATION"


def test_ncr_c8_004_schema_pins_resolve_to_meta_valid_schemas_with_the_pinned_digest() -> None:
    from ocor_runtime.c8.tool_contract import SchemaCatalog, ToolContract, ToolContractError

    unresolved = SchemaCatalog()
    unresolved.add(INPUT_PIN["schema_id"], INPUT_PIN["version"], INPUT_SCHEMA)
    with pytest.raises(ToolContractError) as excinfo:
        ToolContract.from_document(contract_document(), schemas=unresolved)
    assert reason(excinfo) == "SCHEMA_VIOLATION"

    other = dict(OUTPUT_SCHEMA, maxLength=65)
    drifted = SchemaCatalog()
    drifted.add(INPUT_PIN["schema_id"], INPUT_PIN["version"], INPUT_SCHEMA)
    drifted.add(OUTPUT_PIN["schema_id"], OUTPUT_PIN["version"], other)
    with pytest.raises(ToolContractError) as excinfo:
        ToolContract.from_document(contract_document(), schemas=drifted)
    assert reason(excinfo) == "SCHEMA_VIOLATION"

    with pytest.raises(ToolContractError) as excinfo:
        SchemaCatalog().add("urn:ocor:schema:broken", "1.0.0", {"type": "no-such-type"})
    assert reason(excinfo) == "SCHEMA_VIOLATION"


def test_ncr_c8_004_only_allow_listed_tools_are_exported_and_callable() -> None:
    from ocor_runtime.c8.tool_contract import ToolContractError

    effects: list[str] = []
    registry = restart_registry(effects)
    assert [contract.contract_id for contract in registry.export()] == ["urn:ocor:tool-contract:restart-service"]
    assert registry.tool_names == ("restart_service",)
    with pytest.raises(ToolContractError) as excinfo:
        registry.invoke("shell", (), {"command": "id"})
    assert reason(excinfo) == "CAPABILITY_DENIED"
    assert effects == []


def test_ncr_c8_004_a_binding_cannot_change_the_contract_or_bind_another_context() -> None:
    from ocor_runtime.c8.tool_contract import ToolBinding, ToolContract, ToolContractError, ToolRegistry

    contract = ToolContract.from_document(contract_document(), schemas=catalog())

    def binding(**changes: Any) -> ToolBinding:
        fields: dict[str, Any] = {
            "tool_name": "restart_service",
            "binding_id": "urn:ocor:tool-binding:restart-service:local",
            "contract_id": contract.contract_id,
            "contract_version": contract.version,
            "contract_digest": contract.contract_digest,
            "adapter": lambda name: name,
            "egress_destinations": (),
        }
        fields.update(changes)
        return ToolBinding(**fields)

    for changes in ({"contract_digest": "sha256:" + "1" * 64}, {"contract_version": "2.0.0"}, {"contract_id": "urn:ocor:tool-contract:other"}):
        with pytest.raises(ToolContractError) as excinfo:
            ToolRegistry(governed_context_ref=CONTEXT_REF, schemas=catalog()).register(contract, binding(**changes))
        assert reason(excinfo) == "SCHEMA_VIOLATION", changes
    with pytest.raises(ToolContractError) as excinfo:
        ToolRegistry(governed_context_ref="urn:sha256:" + "e" * 64, schemas=catalog()).register(contract, binding())
    assert reason(excinfo) == "STALE_CONTEXT"
    registry = ToolRegistry(governed_context_ref=CONTEXT_REF, schemas=catalog())
    registry.register(contract, binding())
    with pytest.raises(ToolContractError) as excinfo:
        registry.register(contract, binding(binding_id="urn:ocor:tool-binding:restart-service:other"))
    assert reason(excinfo) == "SCHEMA_VIOLATION"


@pytest.mark.parametrize(
    ("args", "kwargs"),
    [
        pytest.param((), {"name": "svc-1; rm -rf /"}, id="pattern"),
        pytest.param((), {"name": 7}, id="type"),
        pytest.param((), {}, id="missing"),
        pytest.param(("svc-1", "svc-2"), {}, id="extra_positional"),
        pytest.param((), {"name": "svc-1", "force": True}, id="extra_keyword"),
    ],
)
def test_ncr_c8_004_arguments_are_parameter_constrained_before_the_adapter_runs(args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
    from ocor_runtime.c8.tool_contract import ToolContractError

    effects: list[str] = []
    registry = restart_registry(effects)
    with pytest.raises(ToolContractError) as excinfo:
        registry.invoke("restart_service", args, kwargs)
    assert reason(excinfo) == "SCHEMA_VIOLATION"
    assert effects == []


def test_ncr_c8_004_the_output_is_schema_bound_tainted_and_digested_after_the_call() -> None:
    from ocor_runtime.c8.tool_contract import ToolContractError

    effects: list[str] = []
    output = restart_registry(effects).invoke("restart_service", ("svc-1",), {})
    assert output.value == "restarted svc-1"
    assert effects == ["svc-1"]
    assert output.contract_id == "urn:ocor:tool-contract:restart-service"
    assert output.binding_id == "urn:ocor:tool-binding:restart-service:local"
    assert "TOOL_OUTPUT" in output.taint_labels and "UNTRUSTED" in output.taint_labels
    assert output.input_digest == wire_digest({"name": "svc-1"})
    assert output.output_digest == wire_digest("restarted svc-1")

    effects.clear()
    oversized = restart_registry(effects, adapter=lambda name: "x" * 65)
    with pytest.raises(ToolContractError) as excinfo:
        oversized.invoke("restart_service", ("svc-1",), {})
    assert reason(excinfo) == "SCHEMA_VIOLATION"


def test_ncr_c8_004_egress_outside_the_binding_allow_list_is_denied_and_nothing_is_done() -> None:
    from ocor_runtime.c8.tool_contract import ToolContractError, egress_checkpoint

    effects: list[str] = []
    registry = restart_registry(effects, egress=("other.ocor.internal",))
    with pytest.raises(ToolContractError) as excinfo:
        registry.invoke("restart_service", ("svc-1",), {})
    assert reason(excinfo) == "POLICY_DENIED"
    assert effects == []
    # outside a governed invocation there is no egress at all
    with pytest.raises(ToolContractError) as excinfo:
        egress_checkpoint("svc-registry.ocor.internal")
    assert reason(excinfo) == "POLICY_DENIED"


def test_ncr_c8_004_preconditions_are_evaluated_and_fail_closed() -> None:
    from ocor_runtime.c8.tool_contract import ToolBinding, ToolContract, ToolContractError, ToolRegistry

    deny = {"predicate_id": "urn:ocor:predicate:service-known", "version": "1.0.0", "failure_action": "DENY"}
    escalate = {"predicate_id": "urn:ocor:predicate:change-window", "version": "1.0.0", "failure_action": "ESCALATE"}
    contract = ToolContract.from_document(contract_document(preconditions=[deny, escalate]), schemas=catalog())
    effects: list[str] = []

    def registry(predicates: dict[tuple[str, str], Any]) -> ToolRegistry:
        value = ToolRegistry(governed_context_ref=CONTEXT_REF, schemas=catalog(), predicates=predicates)
        value.register(
            contract,
            ToolBinding(
                tool_name="restart_service",
                binding_id="urn:ocor:tool-binding:restart-service:local",
                contract_id=contract.contract_id,
                contract_version=contract.version,
                contract_digest=contract.contract_digest,
                adapter=lambda name: effects.append(name) or "ok",
                egress_destinations=(),
            ),
        )
        return value

    known = ("urn:ocor:predicate:service-known", "1.0.0")
    window = ("urn:ocor:predicate:change-window", "1.0.0")
    assert registry({known: lambda arguments: True, window: lambda arguments: True}).invoke("restart_service", ("svc-1",), {}).value == "ok"
    for predicates, expected in (
        ({known: lambda arguments: False, window: lambda arguments: True}, "POLICY_DENIED"),
        ({known: lambda arguments: True, window: lambda arguments: False}, "APPROVAL_REQUIRED"),
        ({window: lambda arguments: True}, "POLICY_DENIED"),
        ({known: lambda arguments: "yes", window: lambda arguments: True}, "POLICY_DENIED"),
    ):
        with pytest.raises(ToolContractError) as excinfo:
            registry(predicates).invoke("restart_service", ("svc-2",), {})
        assert reason(excinfo) == expected
    assert effects == ["svc-1"]


def test_ncr_c8_004_error_codes_are_the_closed_enum_of_the_contract() -> None:
    from ocor_runtime.c8.tool_contract import TOOL_ERROR_CODES, ToolContractError

    assert TOOL_ERROR_CODES == tuple(add_tool_contract_schema()["properties"]["error_codes"]["items"]["enum"])
    for code in TOOL_ERROR_CODES:
        assert ToolContractError(code, "x").reason_code == code
    for code in ("MARKING_DENIED", "PURPOSE_REQUIRED", "RECONCILIATION_UNAVAILABLE", "STOP_BOUND_DENIED", "TOOL_DEADLINE_EXCEEDED"):
        with pytest.raises(ValueError):
            ToolContractError(code, "x")


# --- the C8 tool runtime world (NCR-C8-004 runtime part, 005, 007, 008) ----------------------------
#
# Anchors: ADD v1.3 Part II §2.12 (:3856) -- tool invocation always re-evaluates live capability,
# delegation, policy, memory instruction eligibility and stop epoch; §4.3.1 invariants 2, 4, 6 and 8
# (:3115, :3117, :3119, :3121); §5.1 agent identity (:3140); §5.2 rule 5 (:3220); §5.5 point 6
# (:3358); error_codes enum (:1759-1778). Register v1.1 FR-004 :47, FR-110 :258, FR-120 :269,
# NFR-036 :271, FR-162 :404, FR-163 :407. LLD v1.1 §6 (:358) and §7.2 FGM-17 (:398).

import ast as _ast  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from collections.abc import Callable  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402

WORLD_NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)
DELEGATION = "urn:sha256:" + "e" * 64
OTHER_DELEGATION = "urn:sha256:" + "f" * 64
SCOPE = "urn:ocor:scope:services"
TOOL_SCHEMA_IN = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["name"],
    "properties": {"name": {"type": "string", "pattern": "^[a-z0-9-]{1,32}$"}},
}
TOOL_SCHEMA_OUT = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "string", "maxLength": 128}
TOOL_PIN_IN = {"schema_id": "urn:ocor:schema:tool:service-name:input", "version": "1.0.0", "digest": wire_digest(TOOL_SCHEMA_IN)}
TOOL_PIN_OUT = {"schema_id": "urn:ocor:schema:tool:service-text:output", "version": "1.0.0", "digest": wire_digest(TOOL_SCHEMA_OUT)}
WORLD_TOOLS = ("note", "restart_service", "slow_restart")


def world_context(*, purpose: str = "incident-response", principal: str = "agent-1") -> Any:
    from ocor_runtime.kernel.governed_context import GovernedContext

    return GovernedContext(
        tenant_id="t1",
        organization_id="o1",
        domain_id="d1",
        compartments=("default",),
        classification_marking_ref="urn:sha256:" + "a" * 64,
        purpose=purpose,
        effective_principal_id=principal,
        actor_chain=(principal,),
        ontology_release_digest="urn:sha256:" + "b" * 64,
        policy_bundle_digest="urn:sha256:" + "c" * 64,
        correlation_id="urn:ocor:correlation:rem-0058",
    )


def later_than(instant: datetime) -> datetime:
    """The current instant, strictly after ``instant`` (a revocation recorded while a call runs)."""
    now = datetime.now(UTC)
    return now if now > instant else instant + timedelta(microseconds=1)


class RecordingPolicy:
    """``security.ports.PolicyDecisionPort`` whose effect the test switches between calls; every
    request it evaluates is recorded."""

    def __init__(self) -> None:
        self.effect = "PERMIT"
        self.unavailable = False
        self.requests: list[Any] = []

    def evaluate(self, request: Any) -> Any:
        from ocor_runtime.security.ports import ControlName, ControlStatus, PolicyDecision, PolicyEffect

        self.requests.append(request)
        if self.unavailable:
            raise RuntimeError("policy decision point unreachable")
        effect = PolicyEffect(self.effect)
        obligations = ("urn:ocor:approval:tool-call",) if effect is PolicyEffect.REQUIRE_APPROVAL else ()
        return PolicyDecision.from_request(
            request,
            effect=effect,
            decision_id=f"urn:ocor:policy-decision:{len(self.requests)}",
            valid_until=request.at + timedelta(hours=1),
            status=ControlStatus.available(
                ControlName.POLICY, observed_at=request.at, source_digest=request.governed_context.policy_bundle_digest
            ),
            obligations=obligations,
        )


def audited_reconciler(schema: str = "ocor_audit_rem_0058_tool_runtime") -> Any:
    """The C6 reconciler appending to the signed audit chain on the live PostgreSQL (FR-163)."""
    from ocor_runtime import audit
    from ocor_runtime.c6.safety import OutcomeReconciler

    dsn = os.environ.get("OCOR_LIVE_POSTGRES_DSN")
    if not dsn:
        raise RuntimeError("OCOR_LIVE_POSTGRES_DSN is mandatory: the reconciliation audit is on PostgreSQL")
    from c6_action_fixture import seeded_key

    log = audit.PostgresAuditLog(
        dsn, schema=schema, signer=audit.AuditSigner(key=seeded_key("rem-0058-tool-runtime-audit"), keyid="rem-0058-tool-runtime-audit")
    )
    log.initialize()
    return OutcomeReconciler(audit=log)


class World:
    """The real collaborators of the C8 tool runtime: contract registry, C8 tool grants, governance
    controls (Authority and Delegation), policy decision port, memory instruction eligibility, the
    signed stop epoch, the resolved marking engine, the audited reconciler and the budget ledger.
    ``effects`` is appended to only by the tool adapters."""

    def __init__(self, *, deadline: timedelta | None = None, timeout_ms: int = 5000, reconciler: Any = None, policy: Any = None) -> None:
        from c6_safety_fixture import stop_controller
        from ocor_runtime.c4.marking_resolution import ResolvedMarkingEngine
        from ocor_runtime.c4_marking import MarkingSchemeDefinition
        from ocor_runtime.c8 import tool_runtime
        from ocor_runtime.c8.tool_contract import SchemaCatalog, ToolRegistry
        from ocor_runtime.kernel.governance import Authority, RiskClass

        self.module = tool_runtime
        self.effects: list[str] = []
        self.bodies: dict[str, Callable[[], None]] = {}
        self.context = world_context()
        self.schemas = SchemaCatalog()
        self.schemas.add(TOOL_PIN_IN["schema_id"], TOOL_PIN_IN["version"], TOOL_SCHEMA_IN)
        self.schemas.add(TOOL_PIN_OUT["schema_id"], TOOL_PIN_OUT["version"], TOOL_SCHEMA_OUT)
        self.registry = ToolRegistry(governed_context_ref=self.context.digest(), schemas=self.schemas)
        for name in WORLD_TOOLS:
            self.register(name, timeout_ms=timeout_ms)
        self.stop = stop_controller()
        self.grants = tool_runtime.ToolGrantLedger(stop=self.stop.reader)
        self.controls = tool_runtime.InMemoryGovernanceControls()
        self.authority = Authority(
            authority_id="urn:ocor:authority:agent-1",
            effective_principal_id="agent-1",
            capability_ids=tuple(f"urn:ocor:capability:tool:{name}" for name in WORLD_TOOLS),
            resource_scopes=(SCOPE,),
            tenant_id="t1",
            domains=("d1",),
            compartments=("default",),
            permitted_purposes=("incident-response",),
            risk_ceiling=RiskClass.R1_ANALYZE,
            not_before=WORLD_NOW - timedelta(days=1),
            expires_at=WORLD_NOW + timedelta(days=1),
            delegation_ref=DELEGATION,
            policy_bundle_digest=self.context.policy_bundle_digest,
            signature_ref="urn:ocor:signature:authority-agent-1",
        )
        self.controls.add_authority(self.authority, signature_verified=True)
        self.controls.bind_delegation("agent-1", DELEGATION)
        self.policy = RecordingPolicy() if policy is None else policy
        self.eligibility = tool_runtime.InMemoryInstructionEligibility()
        self.agent = self.binding()
        self.eligibility.allow(self.agent.agent_run_id)
        self.marking = ResolvedMarkingEngine([MarkingSchemeDefinition("classification", levels=("UNCLASSIFIED", "SECRET", "TOP_SECRET"))])
        self.budgets = tool_runtime.AgentBudgetLedger()
        for level, key in (("agent", "agent-1"), ("run", self.agent.agent_run_id), ("team", "team-1"), ("tenant", "t1")):
            self.budgets.set_quota(level, key, self.quota())
        options: dict[str, Any] = {} if deadline is None else {"tool_call_deadline": deadline}
        self.reconciler = audited_reconciler() if reconciler is None else reconciler
        self.runtime = tool_runtime.ToolCallRuntime(
            registry=self.registry,
            grants=self.grants,
            controls=self.controls,
            policy=self.policy,
            eligibility=self.eligibility,
            marking_engine=self.marking,
            stop=self.stop.reader,
            reconciler=self.reconciler,
            **options,
        )
        self.invoked_at = WORLD_NOW

    @staticmethod
    def quota(**changes: int) -> Any:
        from ocor_runtime.c8.tool_runtime import BudgetQuota

        values = {
            "tool_calls": 100,
            "steps": 100,
            "tokens": 10_000,
            "cost": 10_000,
            "wall_time_ms": 600_000,
            "compute_ms": 600_000,
            "risk_exposure": 100,
        }
        values.update(changes)
        return BudgetQuota(**values)

    def register(self, name: str, *, timeout_ms: int = 5000, **contract_changes: Any) -> None:
        from ocor_runtime.c8.tool_contract import ToolBinding, ToolContract

        document = contract_document(
            contract_id=f"urn:ocor:tool-contract:{name.replace('_', '-')}",
            capability_id=f"urn:ocor:capability:tool:{name}",
            governed_context_ref=self.context.digest(),
            input_schema=dict(TOOL_PIN_IN),
            output_schema=dict(TOOL_PIN_OUT),
            timeout_ms=timeout_ms,
            **contract_changes,
        )
        contract = ToolContract.from_document(document, schemas=self.schemas)

        def adapter(name_: str) -> Callable[..., str]:
            def call(name: str) -> str:
                body = self.bodies.get(name_)
                if body is not None:
                    body()
                self.effects.append(name_)
                return f"{name_} {name}"

            return call

        self.registry.register(
            contract,
            ToolBinding(
                tool_name=name,
                binding_id=f"urn:ocor:tool-binding:{name.replace('_', '-')}:local",
                contract_id=contract.contract_id,
                contract_version=contract.version,
                contract_digest=contract.contract_digest,
                adapter=adapter(name),
                egress_destinations=(),
            ),
        )

    def binding(self, *, tier: str = "ANALYZE", run: str = "urn:ocor:agent-run:1", principal: str = "agent-1", team: str = "team-1") -> Any:
        return self.module.AgentIdentityBinding(
            agent_principal_id=principal,
            agent_run_id=run,
            workload_identity=f"spiffe://ocor.internal/agent/{principal}/run/{run.rsplit(':', 1)[-1]}",
            owner="urn:ocor:human:owner-1",
            autonomy_tier=tier,
            agent_version="1.0.0",
            team_id=team,
            tenant_id="t1",
        )

    def principal(self, principal: str = "agent-1") -> Any:
        from ocor_runtime.security.ports import AuthenticatedPrincipal, ControlName, ControlStatus

        return AuthenticatedPrincipal(
            principal_id=principal,
            session_id="urn:ocor:session:rem-0058",
            actor_chain=(principal,),
            assurance_level="spiffe-svid",
            authenticated_at=WORLD_NOW - timedelta(hours=1),
            expires_at=WORLD_NOW + timedelta(hours=1),
            status=ControlStatus.available(ControlName.IDENTITY, observed_at=WORLD_NOW, source_digest="urn:sha256:" + "9" * 64),
        )

    def grant(self, *tools: str, agent: Any = None, ttl: timedelta = timedelta(hours=1), **options: Any) -> Any:
        return self.grants.issue(
            agent=agent or self.agent,
            tools=tools or ("note", "restart_service"),
            scope=SCOPE,
            delegation_ref=DELEGATION,
            authority_id=self.authority.authority_id,
            issued_at=self.invoked_at - timedelta(minutes=1),
            ttl=ttl,
            **options,
        )

    def budget(self, agent: Any = None) -> Any:
        return self.budgets.budget(agent or self.agent)

    def revoke_now(self, grant: Any) -> None:
        self.grants.revoke(grant.lease_id, at=later_than(self.invoked_at))

    def accept_stop(self) -> None:
        from c6_safety_fixture import INCIDENT, SAFETY_OFFICER

        worker = threading.Thread(
            target=lambda: self.stop.activate(
                activator=SAFETY_OFFICER, incident_ref=INCIDENT, reason="external emergency stop", at=datetime.now(UTC)
            )
        )
        worker.start()
        worker.join()

    def invoke(self, expression: str, grant: Any, *, tool_name: str = "note", agent: Any = None, budget: Any = None, **changes: Any) -> Any:
        from ocor_runtime.c4_marking import MarkingSet

        agent = agent or self.agent
        arguments: dict[str, Any] = {
            "bindings": {"name": "svc"},
            "lease": grant,
            "agent": agent,
            "principal": self.principal(agent.agent_principal_id),
            "context": self.context,
            "content_marking": MarkingSet({"classification": "SECRET"}),
            "clearance": MarkingSet({"classification": "TOP_SECRET"}),
            "budget": budget if budget is not None else self.budget(agent),
            "estimated_tokens": 10,
            "stop_epoch": self.stop.epoch,
            "at": self.invoked_at,
        }
        arguments.update(changes)
        return self.runtime.invoke(tool_name, expression, **arguments)

    def refused(self, expression: str, grant: Any, code: str, **kwargs: Any) -> Any:
        with pytest.raises(self.module.ToolRuntimeError) as refused:
            self.invoke(expression, grant, **kwargs)
        assert refused.value.reason_code == code, str(refused.value)
        return refused.value


TWO_TOOLS = "[note(name), restart_service(name)]"


# --- NCR-C8-005: live policy, autonomy tier, eligibility, Authority, agent binding, budget --------


def test_ncr_c8_005_conforms() -> None:
    """RED of NCR-C8-005: every dispatch re-evaluates the policy decision, the autonomy tier and the
    memory instruction eligibility (ADD v1.3 :3856, :3115; FR-110 :258), the receipt records agent
    ID, run, delegator, scope, budget and autonomy tier with the taint of the output (FR-004 :47,
    ADD v1.3 :3140) and the budget is multidimensional at agent, run, team and tenant (FR-120 :269,
    ADD v1.3 :3119)."""
    world = World()
    grant = world.grant()
    budget = world.budget()

    receipt = world.invoke(TWO_TOOLS, grant, budget=budget)

    assert world.effects == ["note", "restart_service"]
    assert receipt.result == ["note svc", "restart_service svc"]
    assert receipt.agent_principal_id == "agent-1"
    assert receipt.agent_run_id == "urn:ocor:agent-run:1"
    assert receipt.agent_version == "1.0.0"
    assert receipt.workload_identity == world.agent.workload_identity
    assert receipt.delegation_ref == DELEGATION
    assert receipt.delegator == world.authority.authority_id
    assert receipt.scope == SCOPE
    assert receipt.autonomy_tier == "ANALYZE"
    assert receipt.authority_id == world.authority.authority_id
    assert receipt.governed_context_digest == world.context.digest()
    assert receipt.taint_labels == ("TOOL_OUTPUT", "UNTRUSTED")
    assert [invocation.tool_name for invocation in receipt.invocations] == ["note", "restart_service"]
    assert all(invocation.input_digest.startswith("sha256:") and invocation.output_digest.startswith("sha256:") for invocation in receipt.invocations)
    # the policy is evaluated for the call, for each called tool and again at each dispatch
    dispatched = [request.action for request in world.policy.requests]
    assert dispatched.count("urn:ocor:capability:tool:restart_service") >= 2
    assert receipt.policy_decision_ids and len(receipt.policy_decision_ids) == len(world.policy.requests)
    assert set(receipt.budget_charged) == set(world.module.BUDGET_DIMENSIONS)
    assert receipt.budget_charged["tool_calls"] == 2 and receipt.budget_charged["steps"] == 1 and receipt.budget_charged["tokens"] == 10
    for level in world.module.BUDGET_LEVELS:
        assert budget.spent("tool_calls", level=level) == 2
    assert world.module.POC_AUTONOMY_TIERS == ("OBSERVE", "ANALYZE", "SIMULATE", "PROPOSE")
    # an autonomy tier the contract does not allow never dispatches
    observer = world.binding(tier="OBSERVE", run="urn:ocor:agent-run:2")
    world.eligibility.allow(observer.agent_run_id)
    world.budgets.set_quota("run", observer.agent_run_id, world.quota())
    world.refused("note(name)", world.grant("note", agent=observer), "POLICY_DENIED", agent=observer)
    assert world.effects == ["note", "restart_service"]


def test_ncr_c8_005_the_policy_is_evaluated_live_at_every_dispatch() -> None:
    world = World()
    grant = world.grant()
    world.bodies["note"] = lambda: setattr(world.policy, "effect", "DENY")

    refused = world.refused(TWO_TOOLS, grant, "POLICY_DENIED")

    assert world.effects == ["note"]
    assert refused.execution_unknown is False


@pytest.mark.parametrize(("effect", "code"), [("DENY", "POLICY_DENIED"), ("REQUIRE_APPROVAL", "APPROVAL_REQUIRED")])
def test_ncr_c8_005_a_policy_that_does_not_permit_refuses_before_any_effect(effect: str, code: str) -> None:
    world = World()
    world.policy.effect = effect
    budget = world.budget()

    world.refused("note(name)", world.grant(), code, budget=budget)

    assert world.effects == []
    assert all(budget.spent(dimension) == 0 for dimension in world.module.BUDGET_DIMENSIONS)


def test_ncr_c8_005_an_unavailable_policy_decision_point_fails_closed() -> None:
    world = World()
    world.policy.unavailable = True

    world.refused("note(name)", world.grant(), "POLICY_DENIED")

    assert world.effects == []


@pytest.mark.parametrize("tier", ["OBSERVE", "PROPOSE", "EXECUTE_APPROVED"])
def test_ncr_c8_005_an_autonomy_tier_outside_the_contract_or_the_poc_profile_is_denied(tier: str) -> None:
    world = World()
    agent = world.binding(tier=tier, run="urn:ocor:agent-run:tier")
    world.eligibility.allow(agent.agent_run_id)
    world.budgets.set_quota("run", agent.agent_run_id, world.quota())

    world.refused("note(name)", world.grant("note", agent=agent), "POLICY_DENIED", agent=agent)

    assert world.effects == []


def test_ncr_c8_005_memory_instruction_eligibility_is_reevaluated_at_every_dispatch() -> None:
    world = World()
    grant = world.grant()
    world.bodies["note"] = lambda: world.eligibility.withdraw(world.agent.agent_run_id)

    world.refused(TWO_TOOLS, grant, "POLICY_DENIED")

    assert world.effects == ["note"]


def test_ncr_c8_005_a_run_without_instruction_eligibility_never_dispatches() -> None:
    world = World()
    agent = world.binding(run="urn:ocor:agent-run:ineligible")
    world.budgets.set_quota("run", agent.agent_run_id, world.quota())

    world.refused("note(name)", world.grant("note", agent=agent), "POLICY_DENIED", agent=agent)

    assert world.effects == []


def test_ncr_c8_005_the_authority_is_required_and_evaluated_live() -> None:
    from ocor_runtime.kernel.governance import Authority

    missing = World()
    grant = missing.grants.issue(
        agent=missing.agent,
        tools=("note",),
        scope=SCOPE,
        delegation_ref=DELEGATION,
        authority_id="urn:ocor:authority:never-registered",
        issued_at=missing.invoked_at - timedelta(minutes=1),
        ttl=timedelta(hours=1),
    )
    missing.refused("note(name)", grant, "AUTHORITY_MISSING")

    revoked = World()
    grant = revoked.grant()
    revoked.bodies["note"] = lambda: revoked.controls.revoke(revoked.authority.authority_id)
    revoked.refused(TWO_TOOLS, grant, "CAPABILITY_REVOKED")
    assert revoked.effects == ["note"]

    narrow = World()
    fields = {name: getattr(narrow.authority, name) for name in narrow.authority.__dataclass_fields__}
    fields.update(authority_id="urn:ocor:authority:narrow", capability_ids=("urn:ocor:capability:tool:note",))
    narrow.controls.add_authority(Authority(**fields), signature_verified=True)
    grant = narrow.grants.issue(
        agent=narrow.agent,
        tools=("note", "restart_service"),
        scope=SCOPE,
        delegation_ref=DELEGATION,
        authority_id="urn:ocor:authority:narrow",
        issued_at=narrow.invoked_at - timedelta(minutes=1),
        ttl=timedelta(hours=1),
    )
    narrow.refused(TWO_TOOLS, grant, "CAPABILITY_DENIED")
    assert narrow.effects == []

    unsigned = World()
    fields = {name: getattr(unsigned.authority, name) for name in unsigned.authority.__dataclass_fields__}
    fields.update(authority_id="urn:ocor:authority:unsigned")
    unsigned.controls.add_authority(Authority(**fields), signature_verified=False)
    grant = unsigned.grants.issue(
        agent=unsigned.agent,
        tools=("note",),
        scope=SCOPE,
        delegation_ref=DELEGATION,
        authority_id="urn:ocor:authority:unsigned",
        issued_at=unsigned.invoked_at - timedelta(minutes=1),
        ttl=timedelta(hours=1),
    )
    unsigned.refused("note(name)", grant, "AUTHORITY_MISSING")
    assert unsigned.effects == []


def test_ncr_c8_005_the_delegation_is_evaluated_live_at_every_dispatch() -> None:
    world = World()
    grant = world.grant()
    world.bodies["note"] = lambda: world.controls.revoke(DELEGATION)

    world.refused(TWO_TOOLS, grant, "CAPABILITY_REVOKED")

    assert world.effects == ["note"]

    rebound = World()
    rebound.controls.rebind_delegation("agent-1", OTHER_DELEGATION)
    rebound.refused("note(name)", rebound.grant(), "CAPABILITY_DENIED")
    assert rebound.effects == []


def test_ncr_c8_005_the_agent_binding_must_match_the_principal_the_context_and_the_grant() -> None:
    world = World()
    grant = world.grant()
    world.refused("note(name)", grant, "CAPABILITY_DENIED", principal=world.principal("agent-2"))
    other_run = world.binding(run="urn:ocor:agent-run:other")
    world.eligibility.allow(other_run.agent_run_id)
    world.budgets.set_quota("run", other_run.agent_run_id, world.quota())
    world.refused("note(name)", grant, "CAPABILITY_DENIED", agent=other_run)
    world.refused("note(name)", grant, "CAPABILITY_DENIED", agent=world.binding(principal="agent-2"))
    assert world.effects == []


@pytest.mark.parametrize("level", ["agent", "run", "team", "tenant"])
@pytest.mark.parametrize("dimension", ["tool_calls", "steps", "tokens", "cost", "wall_time_ms", "compute_ms", "risk_exposure"])
def test_ncr_c8_005_every_budget_dimension_is_enforced_at_every_level(dimension: str, level: str) -> None:
    world = World()
    key = {"agent": "agent-1", "run": world.agent.agent_run_id, "team": "team-1", "tenant": "t1"}[level]
    world.budgets.set_quota(level, key, world.quota(**{dimension: 0}))
    budget = world.budget()

    world.refused("note(name)", world.grant(), "BUDGET_EXCEEDED", budget=budget, estimated_cost=5)

    assert world.effects == []
    # an exceeded dimension charges nothing at any level (no partial charge)
    for each_level in world.module.BUDGET_LEVELS:
        for each in world.module.BUDGET_DIMENSIONS:
            assert budget.spent(each, level=each_level) == 0, (each, each_level)


def test_ncr_c8_005_measured_wall_time_and_compute_are_charged_and_then_enforced() -> None:
    world = World()
    world.budgets.set_quota("run", world.agent.agent_run_id, world.quota(wall_time_ms=40))
    world.bodies["note"] = lambda: time.sleep(0.06)
    budget = world.budget()

    receipt = world.invoke("note(name)", world.grant(), budget=budget)

    assert receipt.budget_charged["wall_time_ms"] >= 60
    assert budget.spent("wall_time_ms", level="run") >= 60
    assert budget.spent("compute_ms", level="run") >= 0
    world.refused("note(name)", world.grant(), "BUDGET_EXCEEDED", budget=budget)
    assert world.effects == ["note"]


def test_ncr_c8_005_team_and_tenant_quotas_are_shared_by_the_runs_of_the_team() -> None:
    world = World()
    world.budgets.set_quota("team", "team-1", world.quota(tool_calls=1))
    second = world.binding(run="urn:ocor:agent-run:2")
    world.eligibility.allow(second.agent_run_id)
    world.budgets.set_quota("run", second.agent_run_id, world.quota())

    world.invoke("note(name)", world.grant())
    world.refused("note(name)", world.grant("note", agent=second), "BUDGET_EXCEEDED", agent=second)

    assert world.effects == ["note"]


def test_ncr_c8_005_a_budget_without_a_quota_at_some_level_fails_closed() -> None:
    world = World()
    orphan = world.binding(run="urn:ocor:agent-run:no-quota")
    world.eligibility.allow(orphan.agent_run_id)

    world.refused("note(name)", world.grant("note", agent=orphan), "BUDGET_EXCEEDED", agent=orphan)

    assert world.effects == []


# --- NCR-C8-004, runtime part: the runtime dispatches only through the contract registry ----------


def test_ncr_c8_004_the_runtime_dispatches_only_contract_bound_allow_listed_tools() -> None:
    world = World()
    grant = world.grant()

    world.refused("note(name)", grant, "SCHEMA_VIOLATION", bindings={"name": "Not A Service!"})
    world.refused("note(name)", grant, "CAPABILITY_DENIED", tool_name="shell")
    world.refused("slow_restart(name)", grant, "CAPABILITY_DENIED", tool_name="slow_restart")
    assert world.effects == []
    assert world.runtime.tool_names == ("note", "restart_service", "slow_restart")


def test_ncr_c8_004_a_registry_of_another_governed_context_is_stale() -> None:
    world = World()

    world.refused("note(name)", world.grant(), "STALE_CONTEXT", context=world_context(purpose="other-purpose"))

    assert world.effects == []


def test_ncr_c8_004_marking_refusals_are_policy_denials_keeping_the_marking_outcome() -> None:
    from ocor_runtime.c4_marking import MarkingSet

    world = World()
    denied = world.refused("note(name)", world.grant(), "POLICY_DENIED", clearance=MarkingSet({"classification": "UNCLASSIFIED"}))
    assert denied.marking_outcome == "MARKING_DENIED"
    unresolved = world.refused("note(name)", world.grant(), "POLICY_DENIED", content_marking=MarkingSet({"classification": "COSMIC"}))
    assert unresolved.marking_outcome == "MARKING_UNRESOLVED"
    assert world.effects == []


def test_ncr_c8_004_the_runtime_raises_only_contract_error_codes() -> None:
    from ocor_runtime.c8.tool_contract import TOOL_ERROR_CODES

    world = World()
    assert set(world.module.TOOL_RUNTIME_REASON_CODES) <= set(TOOL_ERROR_CODES)
    for code in ("MARKING_DENIED", "PURPOSE_REQUIRED", "RECONCILIATION_UNAVAILABLE", "STOP_BOUND_DENIED", "TOOL_DEADLINE_EXCEEDED"):
        with pytest.raises(ValueError):
            world.module.ToolRuntimeError(code, "x")


# --- NCR-C8-007: dispatch-time live revocation (OCOR-DEV-REM-0043 cases on the C8 grants) ---------


def test_ncr_c8_007_conforms() -> None:
    """RED of NCR-C8-007 (the OCOR-DEV-REM-0043 RED case, 81a8b76): a grant revoked now, while the
    expression runs and later than the presented ``at``, refuses the next tool before its dispatch
    (ADD v1.3 :3856, :3121; NFR-036 :271; FGM-17, LLD v1.1 :398)."""
    world = World()
    holder: dict[str, Any] = {}
    world.bodies["note"] = lambda: world.revoke_now(holder["grant"])
    holder["grant"] = world.grant()

    refused = world.refused(TWO_TOOLS, holder["grant"], "CAPABILITY_REVOKED")

    revoked = world.grants.get(holder["grant"].lease_id)
    assert revoked is not None and revoked.revoked_at is not None and revoked.revoked_at > world.invoked_at
    assert world.effects == ["note"]
    assert refused.execution_unknown is False and refused.reconciliation is None
    assert world.runtime.unknown_outcomes == ()


def test_ncr_c8_007_without_a_revocation_every_tool_of_the_expression_is_dispatched() -> None:
    world = World()
    grant = world.grant()

    receipt = world.invoke(TWO_TOOLS, grant)

    assert world.effects == ["note", "restart_service"]
    assert receipt.result == ["note svc", "restart_service svc"]
    assert receipt.lease_id == grant.lease_id
    assert world.runtime.unknown_outcomes == ()


def test_ncr_c8_007_a_revocation_after_the_last_tool_changes_nothing_already_dispatched() -> None:
    world = World()
    holder: dict[str, Any] = {}
    world.bodies["restart_service"] = lambda: world.revoke_now(holder["grant"])
    holder["grant"] = world.grant()

    receipt = world.invoke(TWO_TOOLS, holder["grant"])

    assert world.effects == ["note", "restart_service"]
    assert receipt.result == ["note svc", "restart_service svc"]
    budget = world.budget()
    world.refused("note(name)", holder["grant"], "CAPABILITY_REVOKED", budget=budget)
    assert world.effects == ["note", "restart_service"] and budget.spent("tokens", level="run") == 10


def test_ncr_c8_007_a_lease_revoked_at_the_current_instant_during_the_expression_refuses_the_next_tool() -> None:
    world = World()
    holder: dict[str, Any] = {}
    world.bodies["note"] = lambda: world.revoke_now(holder["grant"])
    holder["grant"] = world.grant()

    refused = world.refused(TWO_TOOLS, holder["grant"], "CAPABILITY_REVOKED")

    assert world.effects == ["note"]
    assert refused.execution_unknown is False and refused.reconciliation is None


def test_ncr_c8_007_a_delegation_revoked_during_the_expression_refuses_the_next_tool_of_the_delegate() -> None:
    world = World()
    delegator = world.binding(principal="agent-0", run="urn:ocor:agent-run:0")
    parent = world.grant(agent=delegator, redelegation_allowed=True)
    child = world.grants.delegate(parent.lease_id, agent=world.agent, tools=("note", "restart_service"), issued_at=world.invoked_at, ttl=timedelta(minutes=30))
    world.bodies["note"] = lambda: world.revoke_now(parent)

    refused = world.refused(TWO_TOOLS, child, "CAPABILITY_REVOKED")

    assert world.effects == ["note"]
    assert refused.execution_unknown is False
    delegate = world.grants.get(child.lease_id)
    assert delegate is not None and delegate.revoked_at is None


def test_ncr_c8_007_a_lease_revoked_after_the_presented_instant_is_refused_before_anything_is_charged() -> None:
    world = World()
    grant = world.grant("note")
    world.revoke_now(grant)
    budget = world.budget()

    world.refused("note(name)", grant, "CAPABILITY_REVOKED", budget=budget)

    assert world.effects == [] and budget.spent("tokens", level="run") == 0
    assert world.grants.usage(grant.lease_id) == 0


def test_ncr_c8_007_a_revoked_lease_is_refused_on_the_effect_channel_whatever_instant_is_presented() -> None:
    world = World()
    grant = world.grant("note")
    assert world.runtime.authorize_effect(grant, "note", agent=world.agent, at=world.invoked_at).lease_id == grant.lease_id
    world.revoke_now(grant)

    with pytest.raises(world.module.ToolRuntimeError) as refused:
        world.runtime.authorize_effect(grant, "note", agent=world.agent, at=world.invoked_at)

    assert refused.value.reason_code == "CAPABILITY_REVOKED"


def test_ncr_c8_007_a_delegation_revoked_after_the_presented_instant_is_refused_on_the_effect_channel() -> None:
    world = World()
    delegator = world.binding(principal="agent-0", run="urn:ocor:agent-run:0")
    parent = world.grant("note", agent=delegator, redelegation_allowed=True)
    child = world.grants.delegate(parent.lease_id, agent=world.agent, tools=("note",), issued_at=world.invoked_at, ttl=timedelta(minutes=30))
    world.revoke_now(parent)

    with pytest.raises(world.module.ToolRuntimeError) as refused:
        world.runtime.authorize_effect(child, "note", agent=world.agent, at=world.invoked_at)

    assert refused.value.reason_code == "CAPABILITY_REVOKED"


def test_ncr_c8_007_a_stop_and_a_revocation_during_the_expression_refuse_the_next_tool_as_stop_bound() -> None:
    world = World()
    holder: dict[str, Any] = {}

    def revoke_and_stop() -> None:
        world.revoke_now(holder["grant"])
        world.accept_stop()

    world.bodies["note"] = revoke_and_stop
    holder["grant"] = world.grant()

    world.refused(TWO_TOOLS, holder["grant"], "EMERGENCY_STOP_ACTIVE")

    assert world.effects == ["note"]


def test_ncr_c8_007_a_stop_accepted_after_the_gates_stays_stop_bound() -> None:
    world = World()
    grant = world.grant("note")
    budget = world.budget()
    charge = budget.charge

    def stop_while_charging(**amounts: int) -> Any:
        world.accept_stop()  # after every gate, before the sandbox
        return charge(**amounts)

    budget.charge = stop_while_charging  # type: ignore[method-assign]

    world.refused("note(name)", grant, "EMERGENCY_STOP_ACTIVE", budget=budget)

    assert world.effects == []


def test_ncr_c8_007_the_effect_channel_refuses_a_stopped_and_revoked_lease_as_stop_bound() -> None:
    world = World()
    grant = world.grant("note")
    world.revoke_now(grant)
    world.accept_stop()

    with pytest.raises(world.module.ToolRuntimeError) as refused:
        world.runtime.authorize_effect(grant, "note", agent=world.agent, at=world.invoked_at)

    assert refused.value.reason_code == "EMERGENCY_STOP_ACTIVE"


def test_ncr_c8_007_a_revocation_racing_the_dispatch_from_another_thread_never_reaches_the_second_tool() -> None:
    world = World()
    holder: dict[str, Any] = {}
    revoked = threading.Event()

    def revoke_from_control_plane() -> None:
        worker = threading.Thread(target=lambda: (world.revoke_now(holder["grant"]), revoked.set()))
        worker.start()
        worker.join()

    world.bodies["note"] = revoke_from_control_plane
    holder["grant"] = world.grant()

    started = time.monotonic()
    world.refused(TWO_TOOLS, holder["grant"], "CAPABILITY_REVOKED")

    assert revoked.is_set() and world.effects == ["note"]
    assert time.monotonic() - started < 5.0


def test_ncr_c8_007_a_grant_cannot_be_redelegated_or_widened_by_default() -> None:
    world = World()
    delegator = world.binding(principal="agent-0", run="urn:ocor:agent-run:0")
    closed = world.grant("note", agent=delegator)
    with pytest.raises(world.module.ToolRuntimeError) as refused:
        world.grants.delegate(closed.lease_id, agent=world.agent, tools=("note",), issued_at=world.invoked_at, ttl=timedelta(minutes=1))
    assert refused.value.reason_code == "CAPABILITY_DENIED"
    open_ = world.grant("note", agent=delegator, redelegation_allowed=True)
    for tools, ttl in ((("note", "restart_service"), timedelta(minutes=1)), (("note",), timedelta(hours=2))):
        with pytest.raises(world.module.ToolRuntimeError) as refused:
            world.grants.delegate(open_.lease_id, agent=world.agent, tools=tools, issued_at=world.invoked_at, ttl=ttl)
        assert refused.value.reason_code == "CAPABILITY_DENIED"


# --- NCR-C8-008: no legacy lease, no unaudited reconciler, no permissive default ------------------


def _imports(path: Path) -> set[str]:
    tree = _ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in _ast.walk(tree):
        if isinstance(node, _ast.ImportFrom):
            names.add(("." * node.level) + (node.module or ""))
        elif isinstance(node, _ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def test_ncr_c8_008_conforms() -> None:
    """RED of NCR-C8-008 (PO decision NCP-U07-C8-TOOL-RUNTIME-LEASE, option 2): the C8 tool runtime
    does not use ``ocor_runtime.c6_capabilities``, builds no unaudited OutcomeReconciler by default
    and records every EXECUTION_UNKNOWN outcome on the reconciler of the signed audit port (ADD v1.3
    :3220, :3360, :3856; FR-162 :404, NFR-036 :271, FR-163 :407)."""
    from ocor_runtime.c6.safety import OutcomeReconciler, OutcomeStatus

    source = ROOT / "ocor-runtime/src/ocor_runtime/c8/tool_runtime.py"
    assert not any(name.endswith("c6_capabilities") for name in _imports(source))
    assert "c6_capabilities" not in source.read_text(encoding="utf-8").split('"""', 2)[-1]
    world = World(deadline=timedelta(milliseconds=300))
    common = {
        "registry": world.registry,
        "grants": world.grants,
        "controls": world.controls,
        "policy": world.policy,
        "eligibility": world.eligibility,
        "marking_engine": world.marking,
        "stop": world.stop.reader,
    }
    with pytest.raises(TypeError):
        world.module.ToolCallRuntime(**common)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        world.module.ToolCallRuntime(**common, reconciler=OutcomeReconciler())
    world.bodies["slow_restart"] = lambda: time.sleep(1.0)

    refused = world.refused("slow_restart(name)", world.grant("slow_restart"), "EXECUTION_UNKNOWN", tool_name="slow_restart")

    assert refused.execution_unknown is True and refused.reconciliation is not None
    assert world.reconciler.audited is True
    record = world.reconciler.record(refused.reconciliation.command_id)
    assert record is not None and record.status is OutcomeStatus.UNKNOWN


def test_ncr_c8_008_the_runtime_is_never_built_without_its_governance_controls() -> None:
    world = World()
    full = {
        "registry": world.registry,
        "grants": world.grants,
        "controls": world.controls,
        "policy": world.policy,
        "eligibility": world.eligibility,
        "marking_engine": world.marking,
        "stop": world.stop.reader,
        "reconciler": world.reconciler,
    }
    for missing in ("registry", "grants", "controls", "policy", "eligibility"):
        with pytest.raises(TypeError):
            world.module.ToolCallRuntime(**{key: value for key, value in full.items() if key != missing})
        with pytest.raises(TypeError):
            world.module.ToolCallRuntime(**{**full, missing: None})


def test_ncr_c8_008_a_stop_while_a_tool_runs_records_its_unknown_outcome_on_the_audited_reconciler() -> None:
    from ocor_runtime.c6.safety import OutcomeStatus

    world = World()
    started = threading.Event()

    def slow() -> None:
        started.set()
        time.sleep(1.5)

    world.bodies["slow_restart"] = slow

    def stop_when_started() -> None:
        started.wait(5)
        world.accept_stop()

    threading.Thread(target=stop_when_started, daemon=True).start()
    refused = world.refused("slow_restart(name)", world.grant("slow_restart"), "EMERGENCY_STOP_ACTIVE", tool_name="slow_restart")

    assert refused.execution_unknown is True and refused.reconciliation is not None
    assert world.reconciler.record(refused.reconciliation.command_id).status is OutcomeStatus.UNKNOWN


def test_ncr_c8_008_an_unavailable_audited_reconciler_fails_closed_as_execution_unknown() -> None:
    from ocor_runtime import audit
    from ocor_runtime.c6.safety import OutcomeReconciler
    from c6_action_fixture import seeded_key

    dead = audit.PostgresAuditLog(
        "postgresql://ocor:unused@127.0.0.1:1/ocor",
        schema="ocor_audit_rem_0058_dead",
        signer=audit.AuditSigner(key=seeded_key("rem-0058-dead"), keyid="rem-0058-dead"),
        connect_timeout=1,
    )
    world = World(deadline=timedelta(milliseconds=300), reconciler=OutcomeReconciler(audit=dead))
    world.bodies["slow_restart"] = lambda: time.sleep(1.0)

    refused = world.refused("slow_restart(name)", world.grant("slow_restart"), "EXECUTION_UNKNOWN", tool_name="slow_restart")

    assert refused.execution_unknown is True and refused.reconciliation is None
    assert world.runtime.unknown_outcomes == ()


def test_ncr_c8_008_the_contract_timeout_bounds_the_dispatch() -> None:
    world = World(timeout_ms=200)
    world.bodies["slow_restart"] = lambda: time.sleep(1.0)
    started = time.monotonic()

    refused = world.refused("slow_restart(name)", world.grant("slow_restart"), "EXECUTION_UNKNOWN", tool_name="slow_restart")

    assert time.monotonic() - started < 1.0
    assert refused.execution_unknown is True


def test_ncr_c8_008_a_grant_is_bound_to_the_stop_epoch_of_its_issuance() -> None:
    world = World()
    grant = world.grant("note")
    world.accept_stop()
    with pytest.raises(world.module.ToolRuntimeError) as refused:
        world.grant("note")
    assert refused.value.reason_code == "EMERGENCY_STOP_ACTIVE"
    world.refused("note(name)", grant, "EMERGENCY_STOP_ACTIVE", stop_epoch=world.stop.epoch)
    assert world.effects == []


# =================================================================================================
# NCR-C8-001, 002, 003: the AgentRun orchestrator of the Governed Agent Kernel
# =================================================================================================
#
# Normative anchors (file:line). ADD v1.3 (ocor-runtime/docs/governance_dossier/
# OCOR_ADD_v1.3_APPROVED_BASELINE.md): §2.5 rules 7 and 10 (:339, :342); §1.4 GCS table, agent
# handoff (:388); §4.3 mediated coordination (:3042), roles, typed outputs and hard prohibitions
# (:3057-3064), HandoffEnvelope (:3068-3098), task lifecycle, Commitment, attempts, cycle detection,
# maximum delegation depth, timeout, termination and Critical dissent (:3101-3110); §4.3.1 invariant 3
# (:3116). LLD v1.1 (docs/OCOR_LLD_v1.1.md) §2.8 (:183) and §6 (:358). Register v1.1 FR-010 :62,
# FR-114 :263, FR-115 :264, FR-117 :266, FR-121 :270, FR-128 :278.

from dataclasses import FrozenInstanceError, fields, replace  # noqa: E402

import c8_orchestrator_fixture as team  # noqa: E402

ORCHESTRATOR = ROOT / "ocor-runtime/src/ocor_runtime/c8/orchestrator.py"


def add_handoff_envelope_fields() -> list[str]:
    """The HandoffEnvelope block of ADD v1.3 §4.3, read from the approved baseline itself."""
    lines = ADD.read_text(encoding="utf-8").split("\n")
    begin = lines.index("HandoffEnvelope {")
    end = next(i for i in range(begin, len(lines)) if lines[i] == "}")
    return [line.strip().rstrip(",").rstrip("?").replace("[]", "") for line in lines[begin + 1 : end]]


@pytest.fixture
def world() -> Any:
    return team.TeamWorld(team.live_dsn())


def orchestration_refused(excinfo: pytest.ExceptionInfo[BaseException]) -> str:
    return getattr(excinfo.value, "reason_code", repr(excinfo.value))


def test_ncr_c8_001_conforms(world: Any) -> None:
    """RED of NCR-C8-001: every coordination record is a closed C8 record of the AgentRun state in
    the Run Ledger, never a canonical aggregate, and C8 holds no canonical port (ADD v1.3 :342,
    :339, :3116; LLD v1.1 :183; FR-117 :266, FR-115 :264)."""
    from ocor_runtime.c8 import orchestrator as module

    imports = _imports(ORCHESTRATOR)
    assert not any(name.endswith(("c3_store", "c3", "c3.service", "c3.admission")) for name in imports), sorted(imports)
    for record in (
        "AgentRun",
        "Task",
        "Assignment",
        "Commitment",
        "HandoffEnvelope",
        "Dissent",
        "DissentResolution",
        "DecisionProposal",
        "ToolInvocation",
        "Message",
    ):
        cls = getattr(module, record)
        assert cls.__dataclass_params__.frozen, record
        assert hasattr(cls, "__slots__"), record

    task = world.propose("t-001")
    assert isinstance(task, module.Task) and task.state is module.TaskState.PROPOSED
    assignment = world.assign("t-001", "agent-1")
    assert isinstance(assignment, module.Assignment)
    world.commit("t-001", "agent-1")
    assert [entry.kind for entry in world.ledger.entries(world.team_run_id)] == ["RUN_STARTED", "TASK_PROPOSED"]
    assert [entry.kind for entry in world.ledger.entries("t-001")] == ["TASK_ASSIGNED", "TASK_COMMITTED"]
    rows = _sql_rows(world.dsn, "SELECT to_regclass('c3_aggregate') IS NOT NULL")
    if rows[0][0]:
        assert _sql_rows(world.dsn, "SELECT count(*) FROM c3_aggregate WHERE aggregate_ref LIKE 'urn:ocor:agentrun:%%'") == [(0,)]

    message = world.orchestrator.send_message(
        world.team_run_id,
        recipient="agent-2",
        speech_act="INFORM",
        payload={"grant": "agent:assign", "authority": "urn:ocor:authority:root", "assertion": "target confirmed"},
        at=NOW_C8,
        **team.caller("agent-1"),
    )
    assert isinstance(message, module.Message)
    assert message.canonical is False
    assert {"AGENT_MESSAGE", "UNTRUSTED"} <= set(message.taint_labels)
    with pytest.raises(module.OrchestratorError) as refused:
        world.orchestrator.assign(
            "t-001", "agent-2", capability="act:analyze", lease=message.message_id, assigned_by="agent-1", at=NOW_C8, **team.caller("agent-1")
        )
    assert orchestration_refused(refused) == "CAPABILITY_DENIED"
    assert world.orchestrator.assignment("t-001").agent_id == "agent-1"


def _sql_rows(dsn: str, statement: str, *params: Any) -> list[tuple[Any, ...]]:
    import psycopg

    with psycopg.connect(dsn) as connection:
        return [tuple(row) for row in connection.execute(statement, params).fetchall()]


NOW_C8 = team.NOW


def test_ncr_c8_001_every_record_is_closed_and_immutable(world: Any) -> None:
    from ocor_runtime.c8 import orchestrator as module

    world.accepted("t-002", "agent-1")
    task = world.orchestrator.task("t-002")
    with pytest.raises(FrozenInstanceError):
        task.state = module.TaskState.COMPLETED  # type: ignore[misc]
    dissent = world.dissent("t-002", "agent-3")
    with pytest.raises(FrozenInstanceError):
        dissent.severity = module.DissentSeverity.CRITICAL  # type: ignore[misc]
    assert world.orchestrator.task("t-002").state is module.TaskState.ACCEPTED


def test_ncr_c8_001_a_message_injection_changes_neither_state_nor_capability(world: Any) -> None:
    """FR-117 :266: a Message claiming a grant, an Authority or a completed task changes nothing."""
    from ocor_runtime.c8 import orchestrator as module

    world.accepted("t-003", "agent-1")
    before = [entry.kind for entry in world.ledger.entries("t-003")]
    world.orchestrator.send_message(
        world.team_run_id,
        recipient="team-lead-1",
        speech_act="REQUEST",
        payload={"task_id": "t-003", "state": "COMPLETED", "lease": "agent:handoff"},
        at=NOW_C8,
        **team.caller("agent-1"),
    )
    assert world.orchestrator.task("t-003").state is module.TaskState.ACCEPTED
    assert [entry.kind for entry in world.ledger.entries("t-003")] == before
    spoofed = {"principal": team.principal("agent-1"), "context": team.context("agent-2")}
    with pytest.raises(module.OrchestratorError) as refused:
        world.orchestrator.send_message(world.team_run_id, recipient="agent-2", speech_act="INFORM", payload={"x": "y"}, at=NOW_C8, **spoofed)
    assert orchestration_refused(refused) == "CAPABILITY_DENIED"


def test_ncr_c8_001_a_tool_invocation_is_a_c8_record_of_the_task(world: Any) -> None:
    from ocor_runtime.c8 import orchestrator as module

    world.accepted("t-004", "agent-1")
    receipt = _tool_receipt()
    record = world.orchestrator.record_tool_invocation("t-004", receipt, at=NOW_C8, **team.caller("agent-1"))
    assert isinstance(record, module.ToolInvocation)
    assert (record.task_id, record.tool_name, record.lease_id, record.agent_run_id) == ("t-004", "note", receipt.lease_id, receipt.agent_run_id)
    assert set(record.taint_labels) == {"TOOL_OUTPUT", "UNTRUSTED"}
    assert record.input_digests == tuple(item.input_digest for item in receipt.invocations)
    assert world.ledger.entries("t-004")[-1].kind == "TOOL_INVOKED"
    with pytest.raises(module.OrchestratorError) as refused:
        world.orchestrator.record_tool_invocation("t-004", receipt, at=NOW_C8, **team.caller("agent-2"))
    assert orchestration_refused(refused) == "CAPABILITY_DENIED"


def _tool_receipt() -> Any:
    """A receipt of the governed tool runtime for the run of agent-1 in the team world."""
    tool_world = World()
    run = "urn:ocor:agent-run:agent-1"
    tool_world.budgets.set_quota("run", run, World.quota())
    tool_world.eligibility.allow(run)
    tool_world.agent = tool_world.binding(run=run)
    return tool_world.invoke("note(name)", tool_world.grant("note"))


# --- NCR-C8-002: kernel-attested HandoffEnvelope ---------------------------------------------------


def test_ncr_c8_002_conforms(world: Any) -> None:
    """RED of NCR-C8-002: the handoff is the 28-field HandoffEnvelope of ADD v1.3 :3068-3098 attested
    by the Kernel, with accepted/rejected status (LLD v1.1 :183); it is authorised for the sender
    holding the commitment, compared with the transport Principal (ADD v1.3 :388, :3042); a lease
    held by the recipient alone moves nothing."""
    from ocor_runtime.c1.signing import ed25519_verify
    from ocor_runtime.c8 import orchestrator as module

    names = [field.name for field in fields(module.HandoffEnvelope)]
    assert names[:28] == add_handoff_envelope_fields()
    assert names[28:] == ["status", "rejection_reason"]

    world.accepted("t-010", "agent-1")
    recipient_lease = world.grant(subject="agent-2", capability="agent:handoff", resource="agent-2")
    with pytest.raises(module.OrchestratorError) as refused:
        world.orchestrator.handoff(
            "t-010",
            sender="agent-1",
            to_agent_id="agent-2",
            reason="rebalancing",
            payload={"state_summary": "partial"},
            lease=recipient_lease,
            at=NOW_C8,
            **team.caller("agent-2"),
        )
    assert orchestration_refused(refused) == "CAPABILITY_DENIED"
    assert world.orchestrator.commitment("t-010").agent_id == "agent-1"

    envelope = world.handoff("t-010", sender="agent-1", to="agent-2")
    assert envelope.status == "ACCEPTED" and envelope.rejection_reason is None
    assert (envelope.asserted_sender_principal, envelope.recipient_principal) == ("agent-1", "agent-2")
    assert envelope.team_run_id == world.team_run_id and envelope.task_id == "t-010"
    assert envelope.assignment_id == world.orchestrator.assignment("t-010").assignment_id
    assert envelope.governed_context_digest == team.context("agent-1").digest()
    assert envelope.governed_context == team.context("agent-1").to_mapping()
    assert envelope.ontology_release_digest == team.context("agent-1").ontology_release_digest
    assert envelope.payload_digest == "urn:sha256:" + hashlib.sha256(canonical_bytes({"state_summary": "partial portfolio"})).hexdigest()
    assert (envelope.contract_id, envelope.contract_version) == ("urn:ocor:contract:c8:TaskHandoff", "1.0.0")
    assert envelope.delegation_ref == team.delegation_of("agent-1")
    assert envelope.expires_at > envelope.created_at
    assert ed25519_verify(world.kernel_key.public_key, module.envelope_signing_bytes(envelope), module.envelope_signature(envelope))
    assert world.orchestrator.commitment("t-010").agent_id == "agent-2"
    assert world.ledger.entries("t-010")[-1].kind == "TASK_HANDED_OFF"


def test_ncr_c8_002_a_sender_that_is_not_the_transport_principal_is_denied_and_audited(world: Any) -> None:
    """ADD v1.3 :388: the declared sender is compared with the transport Principal; a mismatch is
    CAPABILITY_DENIED with an audit record, and the rejected envelope is kept in the Run Ledger."""
    from ocor_runtime.c8 import orchestrator as module

    world.accepted("t-011", "agent-1")
    with pytest.raises(module.OrchestratorError) as refused:
        world.handoff("t-011", sender="agent-1", to="agent-2", transport="agent-2")
    assert orchestration_refused(refused) == "CAPABILITY_DENIED"
    assert world.orchestrator.commitment("t-011").agent_id == "agent-1"
    rejected = world.ledger.entries("t-011")[-1]
    assert rejected.kind == "HANDOFF_REJECTED"
    assert rejected.payload["status"] == "REJECTED" and rejected.payload["rejection_reason"] == "CAPABILITY_DENIED"
    (audited,) = [record for record in world.audited() if record["resource"] == "t-011"]
    assert (audited["outcome"], audited["reason_code"]) == ("DENIED", "CAPABILITY_DENIED")


def test_ncr_c8_002_every_handoff_validates_its_schema(world: Any) -> None:
    """FR-010 :62: every handoff validates a schema; a non-conforming payload is rejected and audited."""
    from ocor_runtime.c8 import orchestrator as module

    world.accepted("t-012", "agent-1")
    for payload in ({"state_summary": ""}, {"state_summary": "x", "authority": "root"}, {"other": 1}, ["state_summary"]):
        with pytest.raises(module.OrchestratorError) as refused:
            world.handoff("t-012", sender="agent-1", to="agent-2", payload=payload)
        assert orchestration_refused(refused) == "SCHEMA_VIOLATION"
    assert world.orchestrator.commitment("t-012").agent_id == "agent-1"
    assert [entry.payload["rejection_reason"] for entry in world.ledger.entries("t-012") if entry.kind == "HANDOFF_REJECTED"] == [
        "SCHEMA_VIOLATION"
    ] * 4


def test_ncr_c8_002_actor_chain_purpose_and_effective_authority_are_checked_at_every_hop(world: Any) -> None:
    """FR-128 :278: a hop whose sender or recipient Delegation is withdrawn, whose actor chain does not
    end in the sender, whose context is of another tenant or whose policy does not permit is denied."""
    from ocor_runtime.c8 import orchestrator as module

    world.accepted("t-013", "agent-1")
    lease = world.grant(subject="agent-1", capability="agent:handoff", resource="agent-2")
    laundered = {"principal": team.principal("agent-1"), "context": replace(team.context("agent-1"), actor_chain=("agent-1", "agent-9"))}
    cases = {
        "CAPABILITY_DENIED": laundered,
        "STALE_CONTEXT": team.caller("agent-1", tenant="t2"),
    }
    for code, call in cases.items():
        with pytest.raises(module.OrchestratorError) as refused:
            world.orchestrator.handoff(
                "t-013", sender="agent-1", to_agent_id="agent-2", reason="r", payload={"state_summary": "s"}, lease=lease, at=NOW_C8, **call
            )
        assert orchestration_refused(refused) == code
    world.policy.by_action["urn:ocor:capability:c8:handoff"] = "DENY"
    with pytest.raises(module.OrchestratorError) as refused:
        world.handoff("t-013", sender="agent-1", to="agent-2")
    assert orchestration_refused(refused) == "POLICY_DENIED"
    world.policy.by_action.clear()
    world.revoke_delegation("agent-2")
    with pytest.raises(module.OrchestratorError) as refused:
        world.handoff("t-013", sender="agent-1", to="agent-2")
    assert orchestration_refused(refused) == "CAPABILITY_REVOKED"
    world.controls.rebind_delegation("agent-2", "urn:sha256:" + "7" * 64)
    world.revoke_delegation("agent-1")
    with pytest.raises(module.OrchestratorError) as refused:
        world.handoff("t-013", sender="agent-1", to="agent-2")
    assert orchestration_refused(refused) == "CAPABILITY_REVOKED"
    assert world.orchestrator.commitment("t-013").agent_id == "agent-1"


def test_ncr_c8_002_a_handoff_after_the_stop_or_the_task_deadline_is_refused(world: Any) -> None:
    from ocor_runtime.c8 import orchestrator as module

    world.accepted("t-014", "agent-1", timeout=timedelta(minutes=5))
    with pytest.raises(module.OrchestratorError) as refused:
        world.handoff("t-014", sender="agent-1", to="agent-2", at=NOW_C8 + timedelta(minutes=6))
    assert orchestration_refused(refused) == "TASK_EXPIRED"
    assert world.orchestrator.task("t-014").state is module.TaskState.EXPIRED
    world.accepted("t-015", "agent-1")
    world.accept_stop()
    with pytest.raises(module.OrchestratorError) as refused:
        world.handoff("t-015", sender="agent-1", to="agent-2")
    assert orchestration_refused(refused) == "EMERGENCY_STOP_ACTIVE"


# --- NCR-C8-003: roles, task lifecycle, attempts, cycles, depth, timeout, termination, dissent -----


ADD_ROLE_OUTPUTS = {
    "FUSION_IDENTITY": ("FusionIdentityFinding@1", "CandidateMatchSet@1", "ResolutionProposal@1"),
    "HYPOTHESIS": ("HypothesisPortfolio@1",),
    "CAUSAL": ("CausalAnalysisResult@1", "SimulationResult@1"),
    "POLICY": ("PolicyEvaluationPackage@1",),
    "CHALLENGER": ("DissentRecord@1", "CounterEvidence@1", "AssumptionChallenge@1", "ResidualRisk@1"),
    "COORDINATOR": ("DecisionProposal@1", "EscalationPackage@1", "TerminationRecord@1"),
}


def test_ncr_c8_003_conforms(world: Any) -> None:
    """RED of NCR-C8-003: distinct roles with their typed outputs, the task lifecycle of ADD v1.3
    :3101-3104, logical tasks with attempts and dependencies, cycle detection, maximum delegation
    depth, timeout and termination, the checks of an assignment (LLD v1.1 :183) and dissent severity
    with a separate resolution (FR-010 :62, FR-114 :263, FR-121 :270)."""
    from ocor_runtime.c8 import orchestrator as module

    assert {role.name: module.ROLE_OUTPUTS[role] for role in module.AgentRole} == ADD_ROLE_OUTPUTS
    assert [state.name for state in module.TaskState] == [
        "PROPOSED",
        "POLICY_AUTHORIZED",
        "ACCEPTED",
        "COMPLETED",
        "ABSTAINED",
        "FAILED",
        "EXPIRED",
        "CANCELLED",
    ]
    task = world.propose("t-020", dependencies=())
    assert (task.logical_task_id, task.attempt, task.dependencies, task.delegation_depth) == ("t-020", 1, (), 0)
    world.propose("t-021", dependencies=("t-020",))
    with pytest.raises(module.OrchestratorError) as refused:
        world.assign("t-021", "agent-1")
    assert orchestration_refused(refused) == "DEPENDENCY_PENDING"
    world.propose("t-022", dependencies=("t-023",))
    with pytest.raises(module.OrchestratorError) as refused:
        world.propose("t-023", dependencies=("t-022",))
    assert orchestration_refused(refused) == "TASK_CYCLE_DETECTED"
    assignment = world.assign("t-020", "agent-1")
    assert world.orchestrator.task("t-020").state is module.TaskState.POLICY_AUTHORIZED
    assert (assignment.agent_run_id, assignment.workload_identity, assignment.delegation_ref, assignment.autonomy_tier) == (
        "urn:ocor:agent-run:agent-1",
        "spiffe://ocor.internal/agent/agent-1/run/agent-1",
        team.delegation_of("agent-1"),
        "ANALYZE",
    )
    assert assignment.policy_decision_id.startswith("urn:ocor:policy-decision:")
    commitment = world.commit("t-020", "agent-1")
    assert commitment.assignment_id == assignment.assignment_id
    assert world.orchestrator.task("t-020").state is module.TaskState.ACCEPTED
    done = world.orchestrator.complete(
        "t-020", output={"summary": "two hypotheses"}, evidence_refs=("urn:ocor:evidence:e1",), at=NOW_C8, **team.caller("agent-1")
    )
    assert done.state is module.TaskState.COMPLETED
    assert done.output_digest == "urn:sha256:" + hashlib.sha256(canonical_bytes({"summary": "two hypotheses"})).hexdigest()
    world.assign("t-021", "agent-2")

    sub = world.propose("t-024", parent_task_id="t-021", by="team-lead-1")
    assert sub.delegation_depth == 1
    world.propose("t-025", parent_task_id="t-024")
    with pytest.raises(module.OrchestratorError) as refused:
        world.propose("t-026", parent_task_id="t-025")
    assert orchestration_refused(refused) == "DELEGATION_DEPTH_EXCEEDED"

    critical = world.dissent("t-020", "agent-3", severity="CRITICAL", category="PROVENANCE_GAP", reason="source unverifiable")
    minor = world.dissent("t-020", "agent-3", severity="LOW", category="COUNTER_EVIDENCE", reason="weak counter-evidence")
    with pytest.raises(module.OrchestratorError) as refused:
        _propose_decision(world, impact="HIGH_IMPACT")
    assert orchestration_refused(refused) == "CRITICAL_DISSENT_BLOCKS"
    resolution = world.orchestrator.resolve_dissent(
        critical.dissent_id, resolution="provenance restored", at=NOW_C8, **team.caller("agent-3")
    )
    assert isinstance(resolution, module.DissentResolution) and resolution.dissent_id == critical.dissent_id
    assert world.orchestrator.dissents[0] == critical
    proposal = _propose_decision(world, impact="HIGH_IMPACT")
    assert proposal.executable is False
    assert proposal.dissent_ids == (minor.dissent_id,)


def _propose_decision(world: Any, *, impact: str, by: str = "team-lead-1") -> Any:
    from ocor_runtime.c8 import orchestrator as module

    return world.orchestrator.propose_decision(
        world.team_run_id,
        impact=module.ProposalImpact[impact],
        alternatives=("restart service", "fail over"),
        assumptions=("telemetry is current",),
        uncertainty="medium",
        provenance_refs=("urn:ocor:evidence:e1",),
        at=NOW_C8,
        **team.caller(by),
    )


@pytest.mark.parametrize(
    "case, code",
    [
        ("unknown-agent", "UNKNOWN_AGENT"),
        ("role-mismatch", "ROLE_MISMATCH"),
        ("delegation-revoked", "CAPABILITY_REVOKED"),
        ("tier-below-task", "POLICY_DENIED"),
        ("budget-exhausted", "BUDGET_EXCEEDED"),
        ("policy-deny", "POLICY_DENIED"),
        ("policy-approval", "APPROVAL_REQUIRED"),
        ("not-coordinator", "ROLE_FORBIDDEN"),
        ("transport-mismatch", "CAPABILITY_DENIED"),
        ("stop", "EMERGENCY_STOP_ACTIVE"),
    ],
)
def test_ncr_c8_003_an_assignment_checks_identity_capability_delegation_tier_budget_and_policy(world: Any, case: str, code: str) -> None:
    from ocor_runtime.c8 import orchestrator as module

    world.propose("t-030", autonomy_tier="SIMULATE" if case == "tier-below-task" else "ANALYZE")
    agent, by, transport = "agent-1", "team-lead-1", "team-lead-1"
    if case == "unknown-agent":
        agent = "agent-99"
    elif case == "role-mismatch":
        agent = "agent-3"
    elif case == "delegation-revoked":
        world.revoke_delegation("agent-1")
    elif case == "budget-exhausted":
        world.budgets.set_quota("run", "urn:ocor:agent-run:agent-1", team.quota(steps=0))
    elif case == "policy-deny":
        world.policy.effect = "DENY"
    elif case == "policy-approval":
        world.policy.effect = "REQUIRE_APPROVAL"
    elif case == "not-coordinator":
        by = transport = "agent-2"
    elif case == "transport-mismatch":
        transport = "agent-2"
    elif case == "stop":
        world.accept_stop()
    lease = world.grant(subject=by, capability="agent:assign", resource=agent)
    with pytest.raises(module.OrchestratorError) as refused:
        world.orchestrator.assign("t-030", agent, capability="act:analyze", lease=lease, assigned_by=by, at=NOW_C8, **team.caller(transport))
    assert orchestration_refused(refused) == code
    assert world.orchestrator.assignment("t-030") is None
    assert world.ledger.entries("t-030") == () or world.ledger.entries("t-030")[-1].kind == "TASK_FAILED"


def test_ncr_c8_003_a_member_cannot_hold_a_tier_outside_the_poc_profile_or_share_an_identity() -> None:
    from ocor_runtime.c8 import orchestrator as module

    with pytest.raises(module.OrchestratorError) as refused:
        team.TeamWorld(team.live_dsn(), tiers={"agent-1": "EXECUTE_APPROVED"})
    assert orchestration_refused(refused) == "POLICY_DENIED"
    world = team.TeamWorld(team.live_dsn())
    twin = module.TeamMember(role=module.AgentRole.HYPOTHESIS, binding=world.members["agent-1"].binding)
    with pytest.raises(module.OrchestratorError) as refused:
        world.orchestrator.start_run(
            f"urn:ocor:team-run:{uuid_hex()}",
            team_id="team-1",
            members=(*world.members.values(), twin),
            termination=world.termination,
            at=NOW_C8,
            **team.caller("team-lead-1"),
        )
    assert orchestration_refused(refused) == "CAPABILITY_DENIED"


def uuid_hex() -> str:
    import uuid

    return str(uuid.uuid4())


def test_ncr_c8_003_completion_requires_the_typed_conforming_output_of_the_role_and_evidence(world: Any) -> None:
    from ocor_runtime.c8 import orchestrator as module

    world.accepted("t-040", "agent-1")
    attempts = [
        ({"summary": "ok"}, (), "SCHEMA_VIOLATION"),
        ({"summary": ""}, ("urn:ocor:evidence:e1",), "SCHEMA_VIOLATION"),
        ({"summary": "ok", "canonical": True}, ("urn:ocor:evidence:e1",), "SCHEMA_VIOLATION"),
    ]
    for output, evidence, code in attempts:
        with pytest.raises(module.OrchestratorError) as refused:
            world.orchestrator.complete("t-040", output=output, evidence_refs=evidence, at=NOW_C8, **team.caller("agent-1"))
        assert orchestration_refused(refused) == code
    with pytest.raises(module.OrchestratorError) as refused:
        world.orchestrator.complete("t-040", output={"summary": "ok"}, evidence_refs=("urn:ocor:evidence:e1",), at=NOW_C8, **team.caller("agent-2"))
    assert orchestration_refused(refused) == "CAPABILITY_DENIED"
    with pytest.raises(module.OrchestratorError) as refused:
        world.propose("t-041", role="HYPOTHESIS", output_type="DecisionProposal@1")
    assert orchestration_refused(refused) == "ROLE_OUTPUT_FORBIDDEN"
    assert world.orchestrator.task("t-040").state is module.TaskState.ACCEPTED


def test_ncr_c8_003_the_coordinator_has_no_domain_inference_approval_or_dissent_suppression(world: Any) -> None:
    from ocor_runtime.c8 import orchestrator as module

    world.accepted("t-050", "agent-1")
    dissent = world.dissent("t-050", "agent-3", severity="CRITICAL", category="POLICY_VIOLATION")
    with pytest.raises(module.OrchestratorError) as refused:
        world.orchestrator.resolve_dissent(dissent.dissent_id, resolution="overruled", at=NOW_C8, **team.caller("team-lead-1"))
    assert orchestration_refused(refused) == "ROLE_FORBIDDEN"
    with pytest.raises(module.OrchestratorError) as refused:
        _propose_decision(world, impact="STANDARD", by="agent-1")
    assert orchestration_refused(refused) == "ROLE_FORBIDDEN"
    with pytest.raises(module.OrchestratorError) as refused:
        world.propose("t-051", role="COORDINATOR")
        world.assign("t-051", "agent-1")
    assert orchestration_refused(refused) == "ROLE_MISMATCH"
    assert not any(
        name.startswith(("remove", "retract", "delete", "clear", "update", "suppress", "approve"))
        for name in dir(world.orchestrator)
        if not name.startswith("_")
    )
    proposal = _propose_decision(world, impact="STANDARD")
    assert proposal.dissent_ids == (dissent.dissent_id,)


def test_ncr_c8_003_retries_keep_the_logical_task_with_a_distinct_attempt_up_to_the_limit(world: Any) -> None:
    from ocor_runtime.c8 import orchestrator as module

    world.accepted("t-060", "agent-1")
    failed = world.orchestrator.fail("t-060", reason="tool unavailable", at=NOW_C8, **team.caller("agent-1"))
    assert failed.state is module.TaskState.FAILED
    second = world.orchestrator.retry("t-060", at=NOW_C8, **team.caller("team-lead-1"))
    assert (second.logical_task_id, second.attempt, second.state) == ("t-060", 2, module.TaskState.PROPOSED)
    assert second.task_id != "t-060"
    world.assign(second.task_id, "agent-2")
    world.commit(second.task_id, "agent-2")
    world.orchestrator.fail(second.task_id, reason="again", at=NOW_C8, **team.caller("agent-2"))
    third = world.orchestrator.retry(second.task_id, at=NOW_C8, **team.caller("team-lead-1"))
    assert third.attempt == 3
    world.assign(third.task_id, "agent-1")
    world.commit(third.task_id, "agent-1")
    world.orchestrator.fail(third.task_id, reason="once more", at=NOW_C8, **team.caller("agent-1"))
    with pytest.raises(module.OrchestratorError) as refused:
        world.orchestrator.retry(third.task_id, at=NOW_C8, **team.caller("team-lead-1"))
    assert orchestration_refused(refused) == "TERMINATION_CONDITION_MET"
    with pytest.raises(module.OrchestratorError) as refused:
        world.orchestrator.retry("t-060", at=NOW_C8, **team.caller("team-lead-1"))
    assert orchestration_refused(refused) == "INVALID_TRANSITION"
    world.propose("t-061")
    cancelled = world.orchestrator.cancel("t-061", reason="superseded", at=NOW_C8, **team.caller("team-lead-1"))
    assert cancelled.state is module.TaskState.CANCELLED
    with pytest.raises(module.OrchestratorError) as refused:
        world.orchestrator.cancel("t-061", reason="again", at=NOW_C8, **team.caller("team-lead-1"))
    assert orchestration_refused(refused) == "INVALID_TRANSITION"
    with pytest.raises(module.OrchestratorError) as refused:
        world.orchestrator.retry("t-061", at=NOW_C8, **team.caller("team-lead-1"))
    assert orchestration_refused(refused) == "INVALID_TRANSITION"


def test_ncr_c8_003_a_budget_exhausted_during_the_task_stops_it(world: Any) -> None:
    from ocor_runtime.c8 import orchestrator as module

    world.propose("t-070")
    world.assign("t-070", "agent-1")
    world.budgets.set_quota("agent", "agent-1", team.quota(steps=1))
    with pytest.raises(module.OrchestratorError) as refused:
        world.commit("t-070", "agent-1")
    assert orchestration_refused(refused) == "BUDGET_EXCEEDED"
    assert world.orchestrator.task("t-070").state is module.TaskState.FAILED
    assert world.ledger.entries("t-070")[-1].kind == "TASK_FAILED"


def test_ncr_c8_003_the_run_timeout_and_task_limit_terminate_with_the_escalation_target() -> None:
    from ocor_runtime.c8 import orchestrator as module

    termination = module.TerminationCondition(
        max_delegation_depth=1, timeout=timedelta(minutes=10), max_attempts=2, max_tasks=2, escalation_target=team.ESCALATION_TARGET
    )
    world = team.TeamWorld(team.live_dsn(), termination=termination)
    world.propose("t-080")
    world.propose("t-081")
    with pytest.raises(module.OrchestratorError) as refused:
        world.propose("t-082")
    assert orchestration_refused(refused) == "TERMINATION_CONDITION_MET"
    with pytest.raises(module.OrchestratorError) as refused:
        world.assign("t-080", "agent-1", at=NOW_C8 + timedelta(minutes=11))
    assert orchestration_refused(refused) == "RUN_TERMINATED"
    run = world.orchestrator.run(world.team_run_id)
    assert run.status == "TERMINATED"
    assert run.termination_reason == "TIMEOUT" and run.termination.escalation_target == team.ESCALATION_TARGET
    assert world.orchestrator.task("t-080").state is module.TaskState.EXPIRED
    assert world.ledger.entries(world.team_run_id)[-1].kind == "RUN_TERMINATED"
    with pytest.raises(ValueError):
        module.TerminationCondition(max_delegation_depth=-1, timeout=timedelta(0), max_attempts=0, max_tasks=0, escalation_target="")


def test_ncr_c8_003_a_task_beyond_its_timeout_expires_and_a_proposal_carries_unresolved_dissent(world: Any) -> None:
    from ocor_runtime.c8 import orchestrator as module

    world.propose("t-090", timeout=timedelta(minutes=1))
    with pytest.raises(module.OrchestratorError) as refused:
        world.assign("t-090", "agent-1", at=NOW_C8 + timedelta(minutes=2))
    assert orchestration_refused(refused) == "TASK_EXPIRED"
    assert world.orchestrator.task("t-090").state is module.TaskState.EXPIRED
    world.accepted("t-091", "agent-4", role="CAUSAL")
    abstained = world.orchestrator.abstain("t-091", reason="identification fails", at=NOW_C8, **team.caller("agent-4"))
    assert abstained.state is module.TaskState.ABSTAINED
    critical = world.dissent("t-091", "agent-3", severity="CRITICAL", category="CAUSAL_ABSTENTION")
    with pytest.raises(module.OrchestratorError) as refused:
        _propose_decision(world, impact="HIGH_IMPACT")
    assert orchestration_refused(refused) == "CRITICAL_DISSENT_BLOCKS"
    standard = _propose_decision(world, impact="STANDARD")
    assert standard.dissent_ids == (critical.dissent_id,)
    assert world.ledger.entries(world.team_run_id)[-1].kind == "DECISION_PROPOSED"


# --- NCR-C8-005 on the real policy decision point: OPA over mTLS for a Keycloak principal ---------
#
# The required backend of the unit (plan unit NCP-U10: OPA, Keycloak/SPIFFE, PostgreSQL). The real
# signed bundle decides every tool dispatch and every coordination action: ADD v1.3 :3856 (live
# re-evaluation of policy), :3117 (mediated by Kernel, Gateway and Policy Engine), :3141 (the five
# effects). The fixtures of the sealed OCOR-DEV-0048 module are reused unmodified.

import importlib.util as _importlib_util  # noqa: E402
import sys as _sys  # noqa: E402
import uuid as _uuid  # noqa: E402

_M0048_PATH = Path(__file__).resolve().parent / "test_ocor_dev_0048.py"
_M0048_SPEC = _importlib_util.spec_from_file_location(
    "ocor_dev_0048_fixtures_for_rem0058", _M0048_PATH
)
assert _M0048_SPEC is not None and _M0048_SPEC.loader is not None
m0048 = _importlib_util.module_from_spec(_M0048_SPEC)
_sys.modules[_M0048_SPEC.name] = m0048
_M0048_SPEC.loader.exec_module(m0048)

env = m0048.env
live_stack = m0048.live_stack
admin_token = m0048.admin_token
principals = m0048.principals
mtls = m0048.mtls
principal = m0048.principal


def _opa(mtls: dict[str, object]) -> Any:
    from ocor_runtime.security import control_plane

    return control_plane.OpaPolicyDecisionProvider(
        str(mtls["opa"]),
        m0048.POLICY_ID,
        signer_public_key=(m0048._SIGNER_N, m0048._SIGNER_E),
        ssl_context=mtls["ssl_context"],
    )


def _opa_bundle(principal_id: str, actions: tuple[str, ...], *qualifiers: str) -> str:
    """The signed package: ``allow`` only for ``principal_id`` on the listed actions."""
    allowed = ", ".join(json.dumps(action) for action in actions)
    return (
        "package ocor.control_plane\n\ndefault allow := false\n\n"
        f"allowed_actions := {{{allowed}}}\n\n"
        "allow if {\n"
        f'    input.principal_id == "{principal_id}"\n'
        "    allowed_actions[input.action]\n"
        "}\n" + "".join(f"\n{item}\n" for item in qualifiers)
    )


def _opa_context(principal_id: str, policy_digest: str) -> Any:
    from ocor_runtime.kernel.governed_context import GovernedContext

    return GovernedContext(
        tenant_id="t1",
        organization_id="o1",
        domain_id="d1",
        compartments=("default",),
        classification_marking_ref="urn:sha256:" + "a" * 64,
        purpose="incident-response",
        effective_principal_id=principal_id,
        actor_chain=(principal_id,),
        ontology_release_digest="urn:sha256:" + "b" * 64,
        policy_bundle_digest=policy_digest,
        correlation_id=str(_uuid.uuid4()),
    )


class OpaToolWorld:
    """The governed tool runtime of the shared fixture, decided by the real OPA for the real
    Keycloak principal, at the current instant (the principal and the decision are live)."""

    def __init__(
        self,
        principal: Any,
        mtls: dict[str, object],
        *qualifiers: str,
        actions: tuple[str, ...] | None = None,
    ) -> None:
        from c6_safety_fixture import stop_controller
        from ocor_runtime.c4.marking_resolution import ResolvedMarkingEngine
        from ocor_runtime.c4_marking import MarkingSchemeDefinition
        from ocor_runtime.c8 import tool_runtime

        import c8_tool_runtime_fixture as tools

        self.module = tool_runtime
        self.effects: list[str] = []
        self.opa = _opa(mtls)
        granted = (
            actions
            if actions is not None
            else (
                "urn:ocor:capability:tool:note",
                "urn:ocor:capability:tool:restart_service",
            )
        )
        self.digest = self.opa.install_policy(
            m0048._sign_bundle(
                _opa_bundle(principal.principal_id, granted, *qualifiers)
            )
        )
        self.now = datetime.now(UTC)
        self.stop = stop_controller()
        self.world = tools.ToolRuntimeWorld(
            context=_opa_context(principal.principal_id, self.digest),
            marking_engine=ResolvedMarkingEngine(
                [
                    MarkingSchemeDefinition(
                        "classification", levels=("UNCLASSIFIED", "SECRET")
                    )
                ]
            ),
            stop=self.stop,
            now=self.now,
        )
        for name in ("note", "restart_service"):
            self.world.tool(name, self._adapter(name))
        self.principal = principal
        self.runtime = tool_runtime.ToolCallRuntime(
            registry=self.world.registry,
            grants=self.world.grants,
            controls=self.world.controls,
            policy=self.opa,
            eligibility=self.world.eligibility,
            marking_engine=self.world.runtime._marking_engine,
            stop=self.world.reader,
            reconciler=self.world.reconciler,
        )

    def _adapter(self, tool: str) -> Callable[[str], str]:
        def call(name: str) -> str:
            self.effects.append(tool)
            return f"{tool} {name}"

        return call

    def invoke(self, expression: str) -> Any:
        from ocor_runtime.c4_marking import MarkingSet

        grant = self.world.grant("note", "restart_service")
        return self.runtime.invoke(
            "note",
            expression,
            bindings={"name": "svc"},
            lease=grant,
            agent=self.world.agent,
            principal=self.principal,
            context=self.world.context,
            content_marking=MarkingSet({"classification": "UNCLASSIFIED"}),
            clearance=MarkingSet({"classification": "SECRET"}),
            budget=self.world.budget(100),
            estimated_tokens=1,
            stop_epoch=self.stop.epoch,
            at=datetime.now(UTC),
        )


def test_ncr_c8_005_the_real_opa_permit_admits_every_dispatch_with_its_decisions(
    principal: Any, mtls: dict[str, object]
) -> None:
    world = OpaToolWorld(principal, mtls)

    receipt = world.invoke(TWO_TOOLS)

    assert world.effects == ["note", "restart_service"]
    assert receipt.agent_principal_id == principal.principal_id
    # one OPA decision for the call, one per named tool and one per dispatch, each a distinct URN
    assert len(receipt.policy_decision_ids) >= 5
    assert all(item.startswith("urn:sha256:") for item in receipt.policy_decision_ids)


@pytest.mark.parametrize(
    ("qualifier", "actions", "code"),
    [
        ("", (), "POLICY_DENIED"),
        (
            'approval_requirements contains "approval:domain-owner" if input.action == "urn:ocor:capability:tool:note"',
            None,
            "APPROVAL_REQUIRED",
        ),
        (
            'obligations contains "audit:access" if input.action == "urn:ocor:capability:tool:note"',
            None,
            "POLICY_DENIED",
        ),
    ],
    ids=["deny", "require-approval", "obligate-not-honoured"],
)
def test_ncr_c8_005_the_real_opa_refuses_before_any_effect(
    principal: Any,
    mtls: dict[str, object],
    qualifier: str,
    actions: tuple[str, ...] | None,
    code: str,
) -> None:
    world = OpaToolWorld(
        principal, mtls, *((qualifier,) if qualifier else ()), actions=actions
    )

    with pytest.raises(world.module.ToolRuntimeError) as refused:
        world.invoke("note(name)")

    assert refused.value.reason_code == code, str(refused.value)
    assert world.effects == []


def test_ncr_c8_005_a_tool_the_real_opa_does_not_permit_is_refused_before_its_dispatch(
    principal: Any, mtls: dict[str, object]
) -> None:
    world = OpaToolWorld(principal, mtls, actions=("urn:ocor:capability:tool:note",))

    with pytest.raises(world.module.ToolRuntimeError) as refused:
        world.invoke(TWO_TOOLS)

    assert refused.value.reason_code == "POLICY_DENIED", str(refused.value)
    assert world.effects == []


def test_ncr_c8_005_the_coordination_kernel_is_decided_by_the_real_opa(
    principal: Any, mtls: dict[str, object]
) -> None:
    from c6_safety_fixture import stop_controller
    from ocor_runtime.c8 import orchestrator as module
    from ocor_runtime.c8 import tool_runtime
    from ocor_runtime.c8.tool_contract import SchemaCatalog

    opa = _opa(mtls)
    assign = module.ACTIONS["assign"]
    digest = opa.install_policy(
        m0048._sign_bundle(_opa_bundle(principal.principal_id, (assign,)))
    )
    schemas = SchemaCatalog()
    kernel = module.CoordinationKernel(
        controls=tool_runtime.InMemoryGovernanceControls(),
        policy=opa,
        stop=stop_controller().reader,
        budgets=tool_runtime.AgentBudgetLedger(),
        schemas=schemas,
        contracts=team.output_contracts(schemas),
        handoff_contract=team.handoff_contract(schemas),
        audit=team.audit_log(team.live_dsn(), schema="ocor_audit_rem_0058_opa"),
        signing_key=team.seeded_key("rem-0058-opa-kernel"),
        keyid="urn:ocor:key:rem-0058-opa-kernel",
    )
    context = _opa_context(principal.principal_id, digest)

    decision = kernel.decide(
        principal, context, context.digest(), assign, "agent-2", datetime.now(UTC)
    )

    assert decision.startswith("urn:sha256:")
    with pytest.raises(module.OrchestratorError) as refused:
        kernel.decide(
            principal,
            context,
            context.digest(),
            module.ACTIONS["handoff"],
            "agent-2",
            datetime.now(UTC),
        )
    assert orchestration_refused(refused) == "POLICY_DENIED"


class _ShiftedPolicy(RecordingPolicy):
    """Permits, but evaluated ``evaluated`` after the presented instant and valid for ``valid``."""

    def __init__(self, *, evaluated: timedelta, valid: timedelta) -> None:
        super().__init__()
        self.evaluated, self.valid = evaluated, valid

    def evaluate(self, request: Any) -> Any:
        from ocor_runtime.security.ports import ControlName, ControlStatus, PolicyDecision, PolicyEffect

        self.requests.append(request)
        at = request.at + self.evaluated
        return PolicyDecision(
            decision_id=f"urn:ocor:policy-decision:shifted:{len(self.requests)}",
            effect=PolicyEffect.PERMIT,
            principal_id=request.principal.principal_id,
            action=request.action,
            resource=request.resource,
            purpose=request.governed_context.purpose,
            governed_context_digest=request.governed_context_digest,
            policy_bundle_digest=request.governed_context.policy_bundle_digest,
            evaluated_at=at,
            valid_until=at + self.valid,
            obligations=(),
            status=ControlStatus.available(ControlName.POLICY, observed_at=at, source_digest=request.governed_context.policy_bundle_digest),
        )


@pytest.mark.parametrize(
    ("evaluated", "valid"),
    [(datetime.now(UTC) - WORLD_NOW + timedelta(days=1), timedelta(hours=1)), (-timedelta(hours=2), timedelta(hours=1))],
    ids=["evaluated-after-the-runtime-clock", "expired-at-the-presented-instant"],
)
def test_ncr_c8_005_a_decision_from_the_future_or_expired_at_the_call_is_denied(evaluated: timedelta, valid: timedelta) -> None:
    from ocor_runtime.c8 import orchestrator as module

    world = World(policy=_ShiftedPolicy(evaluated=evaluated, valid=valid))
    world.refused("note(name)", world.grant(), "POLICY_DENIED")
    assert world.effects == []
    team_world = team.TeamWorld(team.live_dsn())
    team_world.kernel.policy = _ShiftedPolicy(evaluated=evaluated, valid=valid)
    with pytest.raises(module.OrchestratorError) as refused:
        team_world.propose("t-shifted")
    assert orchestration_refused(refused) == "POLICY_DENIED"


# --- SELF-CHECK-CHECKLIST (2026-11-08): negative tests of the whole touched modules ---------------
#
# One test per parsing or adapter path of c8/tool_contract.py and c8/adapters/postgres_ledger.py
# that the self-check found without a typed refusal: types before conversions, no raw exception out
# of the boundary, payloads canonical I-JSON before they are written.


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "enum": [{1, 2}]},
        {"type": "object", "description": b"\xff"},
        {"type": "object", "maximum": float("inf")},
        {1: "x"},
    ],
    ids=["set", "bytes", "infinity", "non-string-key"],
)
def test_ncr_c8_004_a_schema_that_is_not_i_json_is_a_schema_violation(schema: Any) -> None:
    from ocor_runtime.c8.tool_contract import SchemaCatalog, ToolContractError

    with pytest.raises(ToolContractError) as refused:
        SchemaCatalog().add("urn:ocor:schema:tool:x", "1.0.0", schema)
    assert refused.value.reason_code == "SCHEMA_VIOLATION"


@pytest.mark.parametrize("pin", ["urn:ocor:schema:tool:x", None, {"schema_id": "urn:ocor:schema:tool:x", "version": "1.0.0", "digest": "x"}])
def test_ncr_c8_004_only_a_schema_pin_resolves(pin: Any) -> None:
    from ocor_runtime.c8.tool_contract import SchemaCatalog, ToolContractError

    catalog = SchemaCatalog()
    catalog.add("urn:ocor:schema:tool:x", "1.0.0", {"type": "object"})
    with pytest.raises(ToolContractError) as refused:
        catalog.resolve(pin)
    assert refused.value.reason_code == "SCHEMA_VIOLATION"


class _UnreadableSignature:
    __signature__ = "not a signature"

    def __call__(self, name: str) -> str:
        return name


@pytest.mark.parametrize(
    "adapter",
    [_UnreadableSignature(), lambda *names: "x", lambda **names: "x"],
    ids=["unreadable-signature", "variadic-positional", "variadic-keyword"],
)
def test_ncr_c8_004_a_binding_whose_adapter_signature_is_unreadable_or_variadic_is_refused(adapter: Any) -> None:
    from ocor_runtime.c8.tool_contract import ToolBinding, ToolContractError

    with pytest.raises(ToolContractError) as refused:
        ToolBinding(
            tool_name="restart_service",
            binding_id="urn:ocor:tool-binding:restart-service:x",
            contract_id="urn:ocor:tool-contract:restart-service",
            contract_version="1.0.0",
            contract_digest="sha256:" + "0" * 64,
            adapter=adapter,
            egress_destinations=(),
        )
    assert refused.value.reason_code == "SCHEMA_VIOLATION"


def _ledger() -> Any:
    from ocor_runtime.c8.adapters.postgres_ledger import PostgresRunLedger

    ledger = PostgresRunLedger(team.live_dsn())
    ledger.initialize()
    return ledger


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"kind": ["TASK_PROPOSED"]}, "kind"),
        ({"kind": None}, "kind"),
        ({"payload": {"value": float("nan")}}, "payload"),
        ({"payload": {"value": float("-inf")}}, "payload"),
        ({"payload": {"value": {1, 2}}}, "payload"),
        ({"payload": {1: "x"}}, "payload"),
        ({"payload": {"value": b"\xff"}}, "payload"),
    ],
    ids=["kind-list", "kind-none", "nan", "negative-infinity", "set", "non-string-key", "bytes"],
)
def test_ncr_c8_001_the_run_ledger_refuses_a_malformed_entry_before_writing(changes: dict[str, Any], field: str) -> None:
    from ocor_runtime.c8.adapters.postgres_ledger import RunLedgerError

    ledger = _ledger()
    task = f"t-malformed-{_uuid.uuid4()}"
    entry: dict[str, Any] = {
        "idempotency_key": f"k-{_uuid.uuid4()}",
        "task_id": task,
        "kind": "TASK_PROPOSED",
        "agent_id": "agent-1",
        "payload": {"value": 1},
        "recorded_at": NOW_C8,
    }
    entry.update(changes)
    with pytest.raises(RunLedgerError) as refused:
        ledger.append(**entry)
    assert refused.value.reason_code == "SCHEMA_VIOLATION", str(refused.value)
    assert field in str(refused.value)
    assert ledger.entries(task) == ()


def test_ncr_c8_001_the_run_ledger_replays_an_idempotent_entry_with_json_equal_content() -> None:
    ledger = _ledger()
    entry: dict[str, Any] = {
        "idempotency_key": f"k-{_uuid.uuid4()}",
        "task_id": f"t-replay-{_uuid.uuid4()}",
        "kind": "TASK_PROPOSED",
        "agent_id": "agent-1",
        "payload": {"dependencies": ("t-1", "t-2"), "attempt": 1},
        "recorded_at": NOW_C8,
    }
    first = ledger.append(**entry)
    assert ledger.append(**entry) == first
    assert first.payload == {"dependencies": ["t-1", "t-2"], "attempt": 1}


class _UndecodableConnection:
    """A psycopg connection whose every statement fails to decode the server's answer."""

    def __enter__(self) -> _UndecodableConnection:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def transaction(self) -> _UndecodableConnection:
        return self

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")


@pytest.mark.parametrize("operation", ["initialize", "append", "entries"])
def test_ncr_c8_001_an_undecodable_backend_answer_is_a_typed_run_ledger_error(operation: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from ocor_runtime.c8.adapters import postgres_ledger

    monkeypatch.setattr(postgres_ledger.psycopg, "connect", lambda *args, **kwargs: _UndecodableConnection())
    ledger = postgres_ledger.PostgresRunLedger("postgresql://scripted")
    calls = {
        "initialize": lambda: ledger.initialize(),
        "append": lambda: ledger.append(
            idempotency_key="k", task_id="t", kind="TASK_PROPOSED", agent_id="a", payload={}, recorded_at=NOW_C8
        ),
        "entries": lambda: ledger.entries("t"),
    }
    with pytest.raises(postgres_ledger.RunLedgerError) as refused:
        calls[operation]()
    assert refused.value.reason_code == "BACKEND_ERROR"
    assert "\\xff" not in str(refused.value)


# SELF-CHECK-CHECKLIST: c8/tool_runtime.py (whole module) ------------------------------------------


@pytest.mark.parametrize(
    "amounts",
    [{"tokens": float("nan")}, {"tokens": float("inf")}, {"tokens": -5}, {"steps": True}, {"tokens": 1.5}, {"bogus": 1}],
    ids=["nan", "infinity", "negative", "bool", "float", "unknown-dimension"],
)
def test_ncr_c8_005_the_budget_ledger_refuses_malformed_amounts_and_stays_enforced(amounts: dict[str, Any]) -> None:
    world = World()
    ledger, agent = world.budgets, world.agent
    for charge in (lambda: ledger.charge(agent, amounts, {}), lambda: ledger.charge(agent, {}, amounts), lambda: ledger.record(agent, amounts)):
        with pytest.raises(ValueError):
            charge()
    assert all(ledger.spent("run", agent.agent_run_id, dimension) == 0 for dimension in world.module.BUDGET_DIMENSIONS)
    with pytest.raises(world.module.ToolRuntimeError) as refused:
        ledger.charge(agent, {"tokens": 10**12}, {})
    assert refused.value.reason_code == "BUDGET_EXCEEDED"


def test_ncr_c8_005_the_budget_ledger_charges_only_an_agent_binding() -> None:
    world = World()
    for call in (
        lambda: world.budgets.charge("agent-1", {"tokens": 1}, {}),
        lambda: world.budgets.record(None, {"tokens": 1}),
        lambda: world.budgets.remaining("agent-1"),
        lambda: world.module.AgentBudget(None, None),  # type: ignore[arg-type]
    ):
        with pytest.raises(TypeError):
            call()


def test_ncr_c8_005_an_authority_port_answer_that_is_not_an_authority_is_authority_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    world = World()
    grant = world.grant()
    monkeypatch.setattr(world.controls, "authority", lambda ref: SimpleNamespace(authority_id=ref))
    monkeypatch.setattr(world.controls, "signature_verified", lambda authority: True)
    monkeypatch.setattr(world.controls, "revoked", lambda ref: False)
    world.refused("note(name)", grant, "AUTHORITY_MISSING")
    assert world.effects == []


def test_ncr_c8_008_a_worker_that_cannot_start_is_a_typed_refusal_and_nothing_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    world = World()
    grant = world.grant()
    start = threading.Thread.start

    def refuse_tool_workers(thread: threading.Thread) -> None:
        if thread.name.startswith("ocor-c8-tool-"):
            raise RuntimeError("can't start new thread")
        start(thread)

    monkeypatch.setattr(threading.Thread, "start", refuse_tool_workers)
    refused = world.refused("note(name)", grant, "EXECUTION_UNKNOWN")
    assert world.effects == []
    assert refused.execution_unknown is False


@pytest.mark.parametrize("bindings", [[1], "name=svc", {1: "svc"}], ids=["list", "text", "non-string-key"])
def test_ncr_c8_004_malformed_call_bindings_are_a_schema_violation_before_anything_is_charged(bindings: Any) -> None:
    world = World()
    budget = world.budget()
    world.refused("note(name)", world.grant(), "SCHEMA_VIOLATION", bindings=bindings, budget=budget)
    assert world.effects == []
    assert all(budget.spent(dimension) == 0 for dimension in world.module.BUDGET_DIMENSIONS)


def test_ncr_c8_005_a_rejected_rebinding_keeps_the_verified_delegation() -> None:
    world = World()
    with pytest.raises(ValueError):
        world.controls.rebind_delegation("agent-1", "not-a-digest")
    assert world.controls.verified_delegation("agent-1") == DELEGATION


def test_ncr_c8_007_a_use_is_recorded_only_for_an_issued_grant() -> None:
    world = World()
    with pytest.raises(world.module.ToolRuntimeError) as refused:
        world.grants.record_use("urn:ocor:c8:tool-grant:ghost")
    assert refused.value.reason_code == "CAPABILITY_DENIED"
    assert world.grants.usage("urn:ocor:c8:tool-grant:ghost") == 0


# SELF-CHECK-CHECKLIST: c8/orchestrator.py (whole module) ------------------------------------------


@pytest.mark.parametrize("instant", [NOW_C8.replace(tzinfo=None), "2026-09-14T12:00:00Z", None], ids=["naive", "text", "none"])
def test_ncr_c8_003_an_instant_that_is_not_timezone_aware_is_a_typed_refusal(world: Any, instant: Any) -> None:
    from ocor_runtime.c8 import orchestrator as module

    with pytest.raises(module.OrchestratorError) as refused:
        world.propose("t-naive", at=instant)
    assert orchestration_refused(refused) == "SCHEMA_VIOLATION"
    assert world.orchestrator.task("t-naive") is None


def test_ncr_c8_003_an_unrepresentable_timeout_is_a_typed_refusal(world: Any) -> None:
    from ocor_runtime.c8 import orchestrator as module

    with pytest.raises(module.OrchestratorError) as refused:
        world.propose("t-overflow", timeout=timedelta.max)
    assert orchestration_refused(refused) == "SCHEMA_VIOLATION"
    assert world.orchestrator.task("t-overflow") is None
    with pytest.raises(module.OrchestratorError) as refused:
        team.TeamWorld(
            team.live_dsn(),
            termination=module.TerminationCondition(
                max_delegation_depth=2, timeout=timedelta.max, max_attempts=3, max_tasks=50, escalation_target=team.ESCALATION_TARGET
            ),
        )
    assert orchestration_refused(refused) == "SCHEMA_VIOLATION"


def test_ncr_c8_003_a_retry_never_overwrites_another_task(world: Any) -> None:
    from ocor_runtime.c8 import orchestrator as module

    world.accepted("c1", "agent-1")
    other = world.propose("c1#attempt-2")
    world.orchestrator.fail("c1", reason="no answer", at=NOW_C8, **team.caller("agent-1"))
    with pytest.raises(module.OrchestratorError) as refused:
        world.orchestrator.retry("c1", at=NOW_C8, **team.caller("team-lead-1"))
    assert orchestration_refused(refused) == "INVALID_TRANSITION"
    assert world.orchestrator.task("c1#attempt-2") == other


def test_ncr_c8_003_a_refused_call_does_not_consume_its_lease(world: Any) -> None:
    from ocor_runtime.c8 import orchestrator as module

    world.propose("t-lease")
    lease = world.grant(subject="team-lead-1", capability="agent:assign", resource="agent-3")
    with pytest.raises(module.OrchestratorError) as refused:
        world.orchestrator.assign(
            "t-lease", "agent-3", capability="act:analyze", lease=lease, assigned_by="team-lead-1", at=NOW_C8, **team.caller("team-lead-1")
        )
    assert orchestration_refused(refused) == "ROLE_MISMATCH"
    assert world.authority.usage(lease.lease_id) == 0


class _FailingLedger:
    """The real PostgreSQL Run Ledger, failing the appends of one kind while ``failing`` is set."""

    def __init__(self, dsn: str, kind: str) -> None:
        from ocor_runtime.c8.adapters.postgres_ledger import PostgresRunLedger

        self._ledger = PostgresRunLedger(dsn)
        self._ledger.initialize()
        self.kind = kind
        self.failing = False

    def append(self, **entry: Any) -> Any:
        if self.failing and entry["kind"] == self.kind:
            raise RuntimeError("PostgreSQL is down")
        return self._ledger.append(**entry)

    def append_all(self, entries: Any, *, before_commit: Any) -> Any:
        if self.failing and any(entry["kind"] == self.kind for entry in entries):
            raise RuntimeError("PostgreSQL is down")
        return self._ledger.append_all(entries, before_commit=before_commit)

    def entries(self, task_id: str) -> tuple[Any, ...]:
        return self._ledger.entries(task_id)


@pytest.mark.parametrize("kind", ["TASK_PROPOSED", "TASK_ASSIGNED"])
def test_ncr_c8_001_a_run_ledger_failure_leaves_no_state_the_ledger_does_not_have(kind: str) -> None:
    from ocor_runtime.c8 import orchestrator as module

    ledger = _FailingLedger(team.live_dsn(), kind)
    world = team.TeamWorld(team.live_dsn(), ledger=ledger)
    if kind == "TASK_ASSIGNED":
        world.propose("t-ledger")
    ledger.failing = True
    with pytest.raises(module.OrchestratorError) as refused:
        world.propose("t-ledger") if kind == "TASK_PROPOSED" else world.assign("t-ledger", "agent-1")
    assert orchestration_refused(refused) == "LEDGER_UNAVAILABLE"
    task = world.orchestrator.task("t-ledger")
    assert task is None if kind == "TASK_PROPOSED" else task.state is module.TaskState.PROPOSED
    assert world.orchestrator.assignment("t-ledger") is None


@pytest.mark.parametrize("answer", [42, "", "urn:sha256:short", None], ids=["integer", "empty", "malformed", "none"])
def test_ncr_c8_003_a_delegation_port_answer_that_is_not_a_delegation_ref_is_revoked(world: Any, answer: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from ocor_runtime.c8 import orchestrator as module

    world.propose("t-delegation")
    monkeypatch.setattr(world.controls, "verified_delegation", lambda agent_id: answer)
    with pytest.raises(module.OrchestratorError) as refused:
        world.assign("t-delegation", "agent-1")
    assert orchestration_refused(refused) == "CAPABILITY_REVOKED"
    assert world.orchestrator.assignment("t-delegation") is None


@pytest.mark.parametrize(
    "changes",
    [{"invocations": (None,)}, {"policy_decision_ids": None}, {"policy_decision_ids": ("",)}, {"lease_id": ""}, {"tool_name": 7}],
    ids=["invocation-none", "decisions-none", "decision-empty", "lease-empty", "tool-name-integer"],
)
def test_ncr_c8_001_a_malformed_tool_receipt_is_a_schema_violation(world: Any, changes: dict[str, Any]) -> None:
    from ocor_runtime.c8 import orchestrator as module

    world.accepted("t-receipt", "agent-1")
    receipt = replace(_tool_receipt(), **changes)
    with pytest.raises(module.OrchestratorError) as refused:
        world.orchestrator.record_tool_invocation("t-receipt", receipt, at=NOW_C8, **team.caller("agent-1"))
    assert orchestration_refused(refused) == "SCHEMA_VIOLATION"
    assert world.ledger.entries("t-receipt")[-1].kind != "TOOL_INVOKED"


def test_ncr_c8_001_a_recorded_tool_invocation_is_always_untrusted_tool_output(world: Any) -> None:
    world.accepted("t-taint", "agent-1")
    record = world.orchestrator.record_tool_invocation("t-taint", replace(_tool_receipt(), taint_labels=()), at=NOW_C8, **team.caller("agent-1"))
    assert record.taint_labels == ("TOOL_OUTPUT", "UNTRUSTED")


@pytest.mark.parametrize("signature_ref", [None, "x:", "urn:ocor:signature:zz", 7], ids=["none", "empty-signature", "not-hex", "integer"])
def test_ncr_c8_002_a_signature_ref_without_an_ed25519_signature_is_a_typed_refusal(world: Any, signature_ref: Any) -> None:
    from ocor_runtime.c8 import orchestrator as module

    world.accepted("t-signature", "agent-1")
    envelope = world.handoff("t-signature", sender="agent-1", to="agent-2")
    with pytest.raises(module.OrchestratorError) as refused:
        module.envelope_signature(replace(envelope, signature_ref=signature_ref))
    assert orchestration_refused(refused) == "SCHEMA_VIOLATION"


@pytest.mark.parametrize("reason", ["", None], ids=["empty", "none"])
def test_ncr_c8_002_a_handoff_refused_before_its_checks_is_rejected_and_audited(world: Any, reason: Any) -> None:
    from ocor_runtime.c8 import orchestrator as module

    world.accepted("t-rejected", "agent-1")
    lease = world.grant(subject="agent-1", capability="agent:handoff", resource="agent-2")
    with pytest.raises(module.OrchestratorError) as refused:
        world.orchestrator.handoff(
            "t-rejected", sender="agent-1", to_agent_id="agent-2", reason=reason, payload={"state_summary": "x"}, lease=lease, at=NOW_C8,
            **team.caller("agent-1"),
        )
    assert orchestration_refused(refused) == "HANDOFF_REASON_REQUIRED"
    rejected = world.ledger.entries("t-rejected")[-1]
    assert rejected.kind == "HANDOFF_REJECTED"
    assert {"contract_id", "contract_version", "governed_context_digest", "correlation_id", "created_at"} <= set(rejected.payload)
    assert any(record["reason_code"] == "HANDOFF_REASON_REQUIRED" for record in world.audited())


def test_ncr_c8_002_a_rejected_envelope_keeps_the_handoff_fields_of_the_lld(world: Any) -> None:
    world.accepted("t-rejected-2", "agent-1")
    with pytest.raises(Exception):
        world.handoff("t-rejected-2", sender="agent-1", to="agent-2", transport="agent-3")
    rejected = world.ledger.entries("t-rejected-2")[-1].payload
    assert (rejected["status"], rejected["rejection_reason"]) == ("REJECTED", "CAPABILITY_DENIED")
    # LLD v1.1 :183: sender, recipient, schema, input/output refs, GCS digest and status
    assert rejected["asserted_sender_principal"] == "agent-1" and rejected["recipient_principal"] == "agent-2"
    assert rejected["contract_id"] == world.kernel.handoff_contract.contract_id
    assert rejected["payload_digest"].startswith("urn:sha256:")
    assert rejected["governed_context_digest"] == team.context("agent-3").digest()


@pytest.mark.parametrize("reason", ["   ", "x" * 600], ids=["blank", "oversized"])
def test_ncr_c8_003_a_dissent_reason_is_bounded_text(world: Any, reason: str) -> None:
    from ocor_runtime.c8 import orchestrator as module

    task = f"t-dissent-reason-{_uuid.uuid4()}"
    world.accepted(task, "agent-1")
    with pytest.raises(module.OrchestratorError):
        world.dissent(task, "agent-3", reason=reason)
    assert all(entry.kind != "DISSENT_REGISTERED" for entry in world.ledger.entries(task))


# --- preventive review OCOR-DEV-REM-0058-9f452aaa0f64-pre: blocking findings P1-P8 -------------------
# Every case below is RED on 9f452aa (the packaged head the review read).

MODEL_PIN = "urn:sha256:" + "1" * 64
INSTRUCTION_PIN = "urn:sha256:" + "2" * 64
TRUST_BUNDLE = "urn:sha256:" + "3" * 64


def attested_workload(spiffe_id: str, *, not_before: datetime | None = None, expires_at: datetime | None = None) -> Any:
    """The transport-attested workload identity (SVID) of the calling agent run."""
    from ocor_runtime.security.ports import ControlName, ControlStatus, WorkloadIdentity

    return WorkloadIdentity(
        spiffe_id=spiffe_id,
        svid_ref=f"urn:ocor:svid:{_uuid.uuid4()}",
        trust_bundle_digest=TRUST_BUNDLE,
        attested=True,
        not_before=WORLD_NOW - timedelta(hours=1) if not_before is None else not_before,
        expires_at=WORLD_NOW + timedelta(hours=1) if expires_at is None else expires_at,
        status=ControlStatus.available(ControlName.WORKLOAD_IDENTITY, observed_at=WORLD_NOW, source_digest=TRUST_BUNDLE),
    )


def envelope(world: World, agent: Any = None, **changes: Any) -> Any:
    """The invocation envelope of ADD v1.3 :1988 for a call of ``agent`` in ``world``."""
    agent = agent or world.agent
    values: dict[str, Any] = {
        "agent_run_id": agent.agent_run_id,
        "workload": attested_workload(agent.workload_identity),
        "delegation_ref": DELEGATION,
        "governed_context_digest": world.context.digest(),
        "ontology_release_digest": world.context.ontology_release_digest,
        "model_pin": getattr(agent, "model_pin", MODEL_PIN),
        "instruction_pin": getattr(agent, "instruction_pin", INSTRUCTION_PIN),
        "correlation_id": world.context.correlation_id,
        "idempotency_key": f"urn:ocor:idempotency:{_uuid.uuid4()}",
    }
    values.update(changes)
    return world.module.InvocationEnvelope(**values)


def expiring_soon(world: World) -> datetime:
    """An instant 200 ms after the presented instant of the call: valid when the call starts,
    passed while its first tool runs for 300 ms."""
    return world.invoked_at + timedelta(milliseconds=200)


def first_tool_runs_300_ms(world: World) -> None:
    world.bodies["note"] = lambda: time.sleep(0.3)


# P1: authorisations that expire during the expression ------------------------------------------------


def test_ncr_c8_007_a_grant_expiring_during_the_expression_refuses_the_next_tool() -> None:
    world = World()
    first_tool_runs_300_ms(world)
    grant = world.grant(ttl=expiring_soon(world) - (world.invoked_at - timedelta(minutes=1)))

    world.refused(TWO_TOOLS, grant, "CAPABILITY_DENIED")

    assert world.effects == ["note"]
    assert world.grants.usage(grant.lease_id) == 1


def test_ncr_c8_005_an_authority_expiring_during_the_expression_refuses_the_next_tool() -> None:
    world = World()
    first_tool_runs_300_ms(world)
    world.controls.add_authority(replace(world.authority, expires_at=expiring_soon(world)), signature_verified=True)

    world.refused(TWO_TOOLS, world.grant(), "AUTHORITY_MISSING")

    assert world.effects == ["note"]


def test_ncr_c8_005_an_agent_principal_expiring_during_the_expression_refuses_the_next_tool() -> None:
    world = World()
    first_tool_runs_300_ms(world)
    principal = replace(world.principal(), expires_at=expiring_soon(world))

    world.refused(TWO_TOOLS, world.grant(), "CAPABILITY_DENIED", principal=principal)

    assert world.effects == ["note"]


def test_ncr_c8_005_a_workload_svid_expiring_during_the_expression_refuses_the_next_tool() -> None:
    world = World()
    first_tool_runs_300_ms(world)
    svid = attested_workload(world.agent.workload_identity, expires_at=expiring_soon(world))

    world.refused(TWO_TOOLS, world.grant(), "CAPABILITY_DENIED", envelope=envelope(world, workload=svid))

    assert world.effects == ["note"]


def test_ncr_c8_005_each_dispatch_is_evaluated_at_its_own_instant() -> None:
    world = World()
    first_tool_runs_300_ms(world)

    world.invoke(TWO_TOOLS, world.grant())

    instants = [request.at for request in world.policy.requests]
    assert instants[0] == world.invoked_at
    assert instants[-1] >= world.invoked_at + timedelta(milliseconds=300)


# P2: the approval the admitted contract requires -----------------------------------------------------


def register_gated(world: World, approval: dict[str, Any]) -> None:
    """Allow-list ``gated`` with ``approval`` and extend the Authority to it: grant, Authority and a
    PERMIT of the policy all admit the call."""
    world.register("gated", approval=approval)
    capabilities = (*world.authority.capability_ids, "urn:ocor:capability:tool:gated")
    world.controls.add_authority(replace(world.authority, capability_ids=capabilities), signature_verified=True)


@pytest.mark.parametrize(
    "approval",
    [
        _approval("HUMAN_GATE", independent_approver_count=1, required_approver_roles=["urn:ocor:role:safety-officer"]),
        DUAL,
    ],
    ids=["human-gate", "dual-control"],
)
def test_ncr_c8_004_a_contract_requiring_approval_is_never_executed_on_a_policy_permit(approval: dict[str, Any]) -> None:
    world = World()
    register_gated(world, approval)
    grant = world.grant("note", "gated")

    world.refused("gated(name)", grant, "APPROVAL_REQUIRED", tool_name="gated")
    with pytest.raises(world.module.ToolRuntimeError) as effect:
        world.runtime.authorize_effect(grant, "gated", agent=world.agent, at=world.invoked_at)

    assert effect.value.reason_code == "APPROVAL_REQUIRED"
    assert world.effects == []
    assert world.grants.usage(grant.lease_id) == 0


def test_ncr_c8_004_an_approval_free_tool_cannot_call_a_gated_tool_inside_its_expression() -> None:
    world = World()
    register_gated(world, DUAL)

    world.refused("[note(name), gated(name)]", world.grant("note", "gated"), "APPROVAL_REQUIRED")

    assert world.effects == []


# P3: the agent binding and the transport-attested invocation envelope ---------------------------------


@pytest.mark.parametrize(
    "changes",
    [
        {"workload_identity": "spiffe://ocor.internal/unrelated/workload"},
        {"agent_version": "99.0.0"},
        {"owner": "urn:ocor:human:someone-else"},
    ],
    ids=["workload", "agent-version", "owner"],
)
def test_ncr_c8_005_a_binding_other_than_the_granted_one_is_refused(changes: dict[str, Any]) -> None:
    world = World()
    grant = world.grant()
    other = replace(world.agent, **changes)

    world.refused("note(name)", grant, "CAPABILITY_DENIED", agent=other, budget=world.budget(), envelope=envelope(world, other))

    assert world.effects == []


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"workload": "spiffe-workload"}, "CAPABILITY_DENIED"),
        ({"workload": "other-spiffe"}, "CAPABILITY_DENIED"),
        ({"workload": "expired-svid"}, "CAPABILITY_DENIED"),
        ({"agent_run_id": "urn:ocor:agent-run:other"}, "CAPABILITY_DENIED"),
        ({"delegation_ref": OTHER_DELEGATION}, "CAPABILITY_DENIED"),
        ({"governed_context_digest": "urn:sha256:" + "0" * 64}, "STALE_CONTEXT"),
        ({"ontology_release_digest": "urn:sha256:" + "0" * 64}, "STALE_CONTEXT"),
        ({"model_pin": "urn:sha256:" + "0" * 64}, "CAPABILITY_DENIED"),
        ({"instruction_pin": "urn:sha256:" + "0" * 64}, "CAPABILITY_DENIED"),
        ({"correlation_id": "urn:ocor:correlation:other"}, "CAPABILITY_DENIED"),
    ],
    ids=["workload-not-attested", "workload-other", "svid-expired", "run", "delegation", "context", "ontology", "model", "instruction",
         "correlation"],
)
def test_ncr_c8_004_every_field_of_the_invocation_envelope_is_verified_at_the_boundary(changes: dict[str, Any], code: str) -> None:
    world = World()
    workload = changes.get("workload")
    if workload == "spiffe-workload":
        changes["workload"] = world.agent.workload_identity
    elif workload == "other-spiffe":
        changes["workload"] = attested_workload("spiffe://ocor.internal/agent/agent-2/run/1")
    elif workload == "expired-svid":
        changes["workload"] = attested_workload(
            world.agent.workload_identity, not_before=WORLD_NOW - timedelta(hours=2), expires_at=WORLD_NOW - timedelta(hours=1)
        )
    grant = world.grant()
    remaining = dict(world.budgets.remaining(world.agent))

    world.refused("note(name)", grant, code, envelope=envelope(world, **changes))

    assert world.effects == []
    assert world.grants.usage(grant.lease_id) == 0
    assert dict(world.budgets.remaining(world.agent)) == remaining


def test_ncr_c8_004_a_call_without_its_invocation_envelope_is_refused() -> None:
    world = World()

    world.refused("note(name)", world.grant(), "CAPABILITY_DENIED", envelope=None)

    assert world.effects == []


@pytest.mark.parametrize(
    "changes",
    [
        {"idempotency_key": "short"},
        {"idempotency_key": 12345678901234567},
        {"idempotency_key": "x" * 257},
        {"idempotency_key": "has spaces in the key"},
        {"model_pin": "sha256:" + "1" * 64},
        {"instruction_pin": None},
        {"agent_run_id": ""},
        {"correlation_id": 7},
    ],
    ids=["key-short", "key-integer", "key-oversized", "key-whitespace", "model-pin-form", "instruction-pin-none", "run-empty",
         "correlation-integer"],
)
def test_ncr_c8_004_a_malformed_invocation_envelope_is_a_schema_violation(changes: dict[str, Any]) -> None:
    world = World()
    with pytest.raises(world.module.ToolRuntimeError) as refused:
        envelope(world, **changes)
    assert refused.value.reason_code == "SCHEMA_VIOLATION"


def test_ncr_c8_004_the_receipt_carries_the_envelope_pins_and_idempotency_key() -> None:
    world = World()
    presented = envelope(world)

    receipt = world.invoke("note(name)", world.grant(), envelope=presented)

    assert (receipt.idempotency_key, receipt.model_pin, receipt.instruction_pin, receipt.workload_identity) == (
        presented.idempotency_key,
        world.agent.model_pin,
        world.agent.instruction_pin,
        presented.workload.spiffe_id,
    )


@pytest.mark.parametrize("pin", ["model_pin", "instruction_pin"])
def test_ncr_c8_005_the_agent_binding_pins_its_model_and_instructions(pin: str) -> None:
    world = World()
    with pytest.raises(ValueError):
        replace(world.agent, **{pin: "not-a-digest"})


# P4: the marking of a handoff against the clearance of its recipient ---------------------------------


def test_ncr_c8_002_a_recipient_without_the_clearance_of_the_payload_marking_is_denied_and_audited(world: Any) -> None:
    from ocor_runtime.c4_marking import MarkingSet
    from ocor_runtime.c8 import orchestrator as module

    task = f"t-marking-{_uuid.uuid4()}"
    world.accepted(task, "agent-1")
    world.markings.set_clearance("agent-2", MarkingSet({"classification": "UNCLASSIFIED"}))
    with pytest.raises(module.OrchestratorError) as refused:
        world.handoff(task, sender="agent-1", to="agent-2")
    assert orchestration_refused(refused) == "POLICY_DENIED"
    assert world.orchestrator.commitment(task).agent_id == "agent-1"
    assert world.ledger.entries(task)[-1].kind == "HANDOFF_REJECTED"
    assert world.audited()[-1]["reason_code"] == "POLICY_DENIED"

    world.markings.set_clearance("agent-2", MarkingSet({"classification": "TOP_SECRET"}))
    assert world.handoff(task, sender="agent-1", to="agent-2").recipient_principal == "agent-2"


@pytest.mark.parametrize("failure", ["unknown-marking", "unreadable-clearance", "unresolvable-clearance"])
def test_ncr_c8_002_a_marking_or_clearance_that_cannot_be_resolved_is_denied(world: Any, failure: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from ocor_runtime.c4_marking import MarkingSet
    from ocor_runtime.c8 import orchestrator as module

    task = f"t-marking-{_uuid.uuid4()}"
    world.accepted(task, "agent-1")
    if failure == "unknown-marking":
        monkeypatch.setattr(world.markings, "marking", lambda ref: (_ for _ in ()).throw(KeyError(ref)))
    elif failure == "unreadable-clearance":
        monkeypatch.setattr(world.markings, "clearance", lambda agent_id: "TOP_SECRET")
    else:
        world.markings.set_clearance("agent-2", MarkingSet({"compartment": "UNKNOWN-SCHEME"}))
    with pytest.raises(module.OrchestratorError) as refused:
        world.handoff(task, sender="agent-1", to="agent-2")
    assert orchestration_refused(refused) == "POLICY_DENIED"
    assert world.orchestrator.commitment(task).agent_id == "agent-1"


def test_ncr_c8_002_the_coordination_kernel_is_never_built_without_its_marking_controls() -> None:
    from ocor_runtime.c8 import orchestrator as module

    world = team.TeamWorld(team.live_dsn())
    arguments = {name: getattr(world.kernel, name) for name in ("controls", "policy", "stop", "budgets", "audit", "keyid")}
    with pytest.raises(TypeError):
        module.CoordinationKernel(
            **arguments,
            schemas=world.schemas,
            contracts=team.output_contracts(world.schemas),
            handoff_contract=team.handoff_contract(world.schemas),
            signing_key=world.kernel_key,
        )


# P5: everything the Run Ledger reads back from PostgreSQL -------------------------------------------


class _ScriptedCursor:
    def __init__(self, rows: Any) -> None:
        self.rows = rows

    def fetchall(self) -> Any:
        return self.rows

    def fetchone(self) -> Any:
        return self.rows[0] if isinstance(self.rows, list) and self.rows else None


class _ScriptedConnection:
    """A psycopg connection answering every statement with ``rows`` (or raising ``error``)."""

    def __init__(self, rows: Any = None, error: BaseException | None = None) -> None:
        self.rows = rows
        self.error = error

    def __enter__(self) -> _ScriptedConnection:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def transaction(self) -> _ScriptedConnection:
        return self

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        if self.error is not None:
            raise self.error
        return _ScriptedCursor(self.rows)


def _stored_row(**changes: Any) -> dict[str, Any]:
    row = {
        "entry_no": 1,
        "idempotency_key": "k",
        "task_id": "t",
        "kind": "TASK_PROPOSED",
        "agent_id": "a",
        "payload": {"x": 1},
        "recorded_at": NOW_C8,
    }
    row.update(changes)
    return row


def _ledger_call(postgres_ledger: Any, operation: str) -> Any:
    ledger = postgres_ledger.PostgresRunLedger("postgresql://scripted")
    calls = {
        "initialize": lambda: ledger.initialize(),
        "append": lambda: ledger.append(
            idempotency_key="k", task_id="t", kind="TASK_PROPOSED", agent_id="a", payload={"x": 1}, recorded_at=NOW_C8
        ),
        "entries": lambda: ledger.entries("t"),
    }
    return calls[operation]


@pytest.mark.parametrize("operation", ["initialize", "append", "entries"])
def test_ncr_c8_001_a_json_body_the_driver_cannot_decode_is_a_typed_run_ledger_error(operation: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from ocor_runtime.c8.adapters import postgres_ledger

    error = json.JSONDecodeError("Expecting property name enclosed in double quotes", "{bad", 1)
    monkeypatch.setattr(postgres_ledger.psycopg, "connect", lambda *args, **kwargs: _ScriptedConnection(error=error))
    with pytest.raises(postgres_ledger.RunLedgerError) as refused:
        _ledger_call(postgres_ledger, operation)()
    assert refused.value.reason_code == "BACKEND_ERROR"


@pytest.mark.parametrize(
    "payload",
    [{"x": float("nan")}, {"x": {"y": float("inf")}}, {"x": [float("-inf")]}, {1: "non-string key"}, {"x": {1, 2}}],
    ids=["nan", "nested-infinity", "listed-negative-infinity", "integer-key", "set"],
)
def test_ncr_c8_001_a_stored_payload_that_is_not_i_json_is_a_typed_run_ledger_error(payload: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from ocor_runtime.c8.adapters import postgres_ledger

    monkeypatch.setattr(postgres_ledger.psycopg, "connect", lambda *args, **kwargs: _ScriptedConnection(rows=[_stored_row(payload=payload)]))
    with pytest.raises(postgres_ledger.RunLedgerError) as refused:
        _ledger_call(postgres_ledger, "entries")()
    assert refused.value.reason_code == "BACKEND_ERROR"


@pytest.mark.parametrize("operation", ["initialize", "entries"])
@pytest.mark.parametrize("rows", [None, {}, "rows", 7], ids=["none", "mapping", "text", "integer"])
def test_ncr_c8_001_a_result_set_that_is_not_a_list_of_rows_is_a_typed_run_ledger_error(
    operation: str, rows: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ocor_runtime.c8.adapters import postgres_ledger

    monkeypatch.setattr(postgres_ledger.psycopg, "connect", lambda *args, **kwargs: _ScriptedConnection(rows=rows))
    with pytest.raises(postgres_ledger.RunLedgerError) as refused:
        _ledger_call(postgres_ledger, operation)()
    assert refused.value.reason_code == "BACKEND_ERROR"


# P6: schema pins and schema references -----------------------------------------------------------------


@pytest.mark.parametrize(
    "fields_",
    [
        ([], "1.0.0", "sha256:" + "0" * 64),
        ("urn:ocor:schema:x", ["1"], "sha256:" + "0" * 64),
        ("urn:ocor:schema:x", "1.0.0", None),
        ("urn:ocor:schema:x", "1.0.0", "sha256:short"),
        ("not-a-urn", "1.0.0", "sha256:" + "0" * 64),
        ("urn:ocor:schema:x", "one", "sha256:" + "0" * 64),
    ],
    ids=["id-list", "version-list", "digest-none", "digest-form", "id-form", "version-form"],
)
def test_ncr_c8_004_a_schema_pin_with_malformed_fields_is_a_schema_violation(fields_: tuple[Any, Any, Any]) -> None:
    from ocor_runtime.c8.tool_contract import SchemaCatalog, SchemaPin, ToolContractError

    with pytest.raises(ToolContractError) as refused:
        SchemaCatalog().resolve(SchemaPin(*fields_))
    assert refused.value.reason_code == "SCHEMA_VIOLATION"


@pytest.mark.parametrize(
    "schema",
    [
        {"$ref": "urn:ocor:schema:not-registered"},
        {"type": "object", "properties": {"x": {"$ref": "https://example.org/remote.json"}}},
        {"$ref": "#/$defs/missing"},
        {"$defs": {"a": {"type": "string"}}, "properties": {"x": {"$ref": "#/$defs/a/missing"}}},
        {"$dynamicRef": "#unknown-anchor"},
    ],
    ids=["unregistered-urn", "remote-url", "missing-local-def", "missing-local-path", "dynamic-ref"],
)
def test_ncr_c8_004_a_schema_with_a_reference_that_does_not_resolve_is_refused_on_admission(schema: dict[str, Any]) -> None:
    from ocor_runtime.c8.tool_contract import SchemaCatalog, ToolContractError

    document = {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}
    with pytest.raises(ToolContractError) as refused:
        SchemaCatalog().add("urn:ocor:schema:tool:referencing", "1.0.0", document)
    assert refused.value.reason_code == "SCHEMA_VIOLATION"


def test_ncr_c8_004_a_schema_with_a_resolvable_local_reference_is_admitted_and_enforced() -> None:
    from ocor_runtime.c8.tool_contract import SchemaCatalog, SchemaPin, ToolContractError

    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {"name": {"type": "string", "pattern": "^svc-[0-9]+$"}},
        "type": "object",
        "properties": {"name": {"$ref": "#/$defs/name"}},
    }
    catalog_ = SchemaCatalog()
    digest = catalog_.add("urn:ocor:schema:tool:local-ref", "1.0.0", document)
    validator = catalog_.resolve(SchemaPin("urn:ocor:schema:tool:local-ref", "1.0.0", digest))
    assert validator.is_valid({"name": "svc-1"}) and not validator.is_valid({"name": "other"})
    with pytest.raises(ToolContractError):
        catalog_.resolve(SchemaPin("urn:ocor:schema:tool:local-ref", "1.0.0", "sha256:" + "0" * 64))


# P7: the contract invocations of a recorded tool receipt ------------------------------------------------


@pytest.mark.parametrize(
    "changes",
    [
        {"contract_id": 42},
        {"contract_digest": "not-a-digest"},
        {"binding_id": None},
        {"tool_name": 7},
        {"input_digest": None},
        {"output_digest": "not-a-digest"},
        {"output_digest": "sha256:" + "0" * 64},
        {"value": float("nan")},
    ],
    ids=["contract-id-integer", "contract-digest-form", "binding-none", "tool-name-integer", "input-digest-none", "output-digest-form",
         "output-digest-of-another-value", "value-not-i-json"],
)
def test_ncr_c8_001_a_receipt_invocation_with_malformed_fields_is_a_schema_violation(world: Any, changes: dict[str, Any]) -> None:
    from ocor_runtime.c8 import orchestrator as module

    task = f"t-invocation-{_uuid.uuid4()}"
    world.accepted(task, "agent-1")
    receipt = _tool_receipt()
    receipt = replace(receipt, invocations=(replace(receipt.invocations[0], **changes),))
    with pytest.raises(module.OrchestratorError) as refused:
        world.orchestrator.record_tool_invocation(task, receipt, at=NOW_C8, **team.caller("agent-1"))
    assert orchestration_refused(refused) == "SCHEMA_VIOLATION"
    assert all(entry.kind != "TOOL_INVOKED" for entry in world.ledger.entries(task))


# P8: one public transition, one Run Ledger transaction; leases spent only with it ------------------------


def test_ncr_c8_003_a_run_timeout_that_the_ledger_cannot_record_leaves_no_expired_task_behind() -> None:
    from ocor_runtime.c8 import orchestrator as module

    ledger = _FailingLedger(team.live_dsn(), "RUN_TERMINATED")
    world = team.TeamWorld(team.live_dsn(), ledger=ledger)
    first, second = (f"t-timeout-{_uuid.uuid4()}" for _ in range(2))
    world.accepted(first, "agent-1")
    world.accepted(second, "agent-2")
    late = NOW_C8 + timedelta(hours=2)

    ledger.failing = True
    with pytest.raises(module.OrchestratorError) as refused:
        world.propose(f"t-timeout-{_uuid.uuid4()}", at=late)
    assert orchestration_refused(refused) == "LEDGER_UNAVAILABLE"
    assert world.orchestrator.run(world.team_run_id).status == "RUNNING"
    for task in (first, second):
        assert world.orchestrator.task(task).state is module.TaskState.ACCEPTED
        assert all(entry.kind != "TASK_EXPIRED" for entry in ledger.entries(task))

    ledger.failing = False
    with pytest.raises(module.OrchestratorError) as terminated:
        world.propose(f"t-timeout-{_uuid.uuid4()}", at=late)
    assert orchestration_refused(terminated) == "RUN_TERMINATED"
    for task in (first, second):
        assert world.orchestrator.task(task).state is module.TaskState.EXPIRED
        assert [entry.kind for entry in ledger.entries(task)].count("TASK_EXPIRED") == 1


@pytest.mark.parametrize(("kind", "operation"), [("TASK_ASSIGNED", "assign"), ("TASK_COMMITTED", "commit"), ("TASK_HANDED_OFF", "handoff")])
def test_ncr_c8_003_a_single_use_lease_is_not_spent_when_the_ledger_does_not_record_the_transition(kind: str, operation: str) -> None:
    from ocor_runtime.c8 import orchestrator as module

    ledger = _FailingLedger(team.live_dsn(), kind)
    world = team.TeamWorld(team.live_dsn(), ledger=ledger)
    task = f"t-lease-{_uuid.uuid4()}"
    world.propose(task)
    if operation != "assign":
        world.assign(task, "agent-1")
    if operation == "handoff":
        world.commit(task, "agent-1")
    subject, capability, resource = {
        "assign": ("team-lead-1", "agent:assign", "agent-1"),
        "commit": ("agent-1", "agent:commit", "agent-1"),
        "handoff": ("agent-1", "agent:handoff", "agent-2"),
    }[operation]
    lease = world.authority.issue(subject=subject, capabilities=[capability], resources=[resource], issued_at=NOW_C8, ttl=timedelta(hours=1), max_uses=1)

    def call() -> Any:
        if operation == "assign":
            return world.orchestrator.assign(
                task, "agent-1", capability="act:analyze", lease=lease, assigned_by="team-lead-1", at=NOW_C8, **team.caller("team-lead-1")
            )
        if operation == "commit":
            return world.orchestrator.commit(task, lease=lease, at=NOW_C8, **team.caller("agent-1"))
        return world.orchestrator.handoff(
            task, sender="agent-1", to_agent_id="agent-2", reason="rebalancing", payload={"state_summary": "partial"}, lease=lease, at=NOW_C8,
            **team.caller("agent-1"),
        )

    ledger.failing = True
    with pytest.raises(module.OrchestratorError) as refused:
        call()
    assert orchestration_refused(refused) == "LEDGER_UNAVAILABLE"
    assert world.authority.usage(lease.lease_id) == 0

    ledger.failing = False
    call()
    assert world.authority.usage(lease.lease_id) == 1
    assert [entry.kind for entry in ledger.entries(task)].count(kind) == 1
