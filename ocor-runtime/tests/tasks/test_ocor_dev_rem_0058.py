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
