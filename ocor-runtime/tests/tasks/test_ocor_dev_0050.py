"""OCOR-DEV-0050: Implement GovernedMemoryItem admission and immutable versions.

Acceptance (backlog): all 8 kinds and 7 scopes validate with provenance,
evidence, markings, taint and immutable version lineage; missing metadata,
invalid scope/kind or a mutable overwrite is rejected before persistence.

Oracles come from ADD v1.3 Part II §§2.3-2.5, 2.10, 2.12, LLD v1.1 §§2.8.1-2.8.2
and 7.2 (FGM-01 closed schema/immutable version/provenance/audit, FGM-02
rejection before persistence, FGM-09 new immutable version with exact-version
replay), and the normative closed contract
``reports/contracts/governed-memory-item.schema.json``.  Every conditional
branch of that schema is exercised with a positive and a negative case against
both the normative JSON Schema (Draft 2020-12) and the runtime record, so a
negative never passes for the wrong reason.

The component is backend-free by policy (OCOR_LANGUAGE_POLICY row 8): the
qualifying persistence cases use the real hash-chained journal on the local
filesystem and real separate interpreter processes (cross-run persistence,
cross-process append race, tamper and torn-write detection).  Policy and
reference resolution are ports; their in-test implementations are explicit
fixture registries, never a mock of the admission boundary itself.
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import textwrap
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import FrozenInstanceError, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator
from ocor_runtime.c4_marking import MarkingSchemeDefinition
from ocor_runtime.kernel.canonical import format_utc_timestamp
from ocor_runtime.kernel.governance import EvidenceRecord, InMemoryTrustedClock, ProvenanceRecord
from ocor_runtime.kernel.governed_context import GovernedContext, VerifiedGovernedContextBinding
from ocor_runtime.memory.model import (
    CAPABILITY_MATRIX,
    AdmissionLimits,
    AdmittedMemoryVersion,
    FederationPolicy,
    GovernedMemoryItem,
    InMemoryMemoryVersionLedger,
    InstructionApproval,
    JournalMemoryVersionLedger,
    LatticeMarkingResolver,
    MemoryAdmissionError,
    MemoryAdmissionService,
    MemoryKind,
    MemoryLedgerCorrupted,
    MemoryPolicyDecision,
    MemoryScope,
    memory_version_ref,
)

REPO = Path(__file__).resolve().parents[3]
RUNTIME_SRC = REPO / "ocor-runtime" / "src"
SCHEMA = json.loads(
    (REPO / "reports/contracts/governed-memory-item.schema.json").read_text(encoding="utf-8")
)
OPENAPI = yaml.safe_load(
    (REPO / "reports/contracts/ocor-governed-memory.openapi.yaml").read_text(encoding="utf-8")
)
VALIDATOR = Draft202012Validator(SCHEMA)

NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
CORRELATION = "6f1c3c4e-7d0a-4c7e-9a51-2b7c1f0d9e11"
CAUSATION = "0b7f9d5e-3a41-4f7a-8c2d-6e5f4a3b2c1d"


def d(label: str | bytes) -> str:
    raw = label.encode() if isinstance(label, str) else label
    return "urn:sha256:" + hashlib.sha256(raw).hexdigest()


M_UNCLASSIFIED = d("marking:UNCLASSIFIED")
M_RESTRICTED = d("marking:RESTRICTED")
M_SECRET = d("marking:SECRET")
POLICY_BUNDLE = d("policy-bundle:memory:1")
ONTOLOGY = d("ontology-release:1")
PAYLOAD = b'{"note":"pump P-101 vibration exceeded threshold at 11:42"}'
SOURCE_DIGEST = d("source:telemetry-1")
SCOPE_FIELDS: dict[str, dict[str, str]] = {
    "RUN": {"agent_run_id": "run-1"},
    "TASK": {"agent_run_id": "run-1", "task_id": "task-1"},
    "AGENT": {"agent_id": "agent-1"},
    "TEAM": {"team_id": "team-1"},
    "PROJECT": {"project_id": "project-1"},
    "DOMAIN": {},
    "FEDERATED": {"federation_policy_ref": "federation-policy-1"},
}
VECTOR_BINDING = {
    "embedding_model_ref": "embedding-model:e5-small:1",
    "embedding_model_digest": d("embedding-model:e5-small:1"),
    "embedding_dimensions": 384,
    "embedding_normalization_profile": "l2-unit",
    "embedding_ref": "embedding:mem-1:v1",
    "embedding_digest": d("embedding:mem-1:v1"),
}


def context(**overrides: Any) -> GovernedContext:
    values: dict[str, Any] = {
        "tenant_id": "tenant-a",
        "organization_id": "org-a",
        "domain_id": "domain-ops",
        "compartments": ("ops",),
        "classification_marking_ref": M_RESTRICTED,
        "purpose": "mission-planning",
        "effective_principal_id": "agent-principal-1",
        "actor_chain": ("human-operator-1", "agent-principal-1"),
        "ontology_release_digest": ONTOLOGY,
        "policy_bundle_digest": POLICY_BUNDLE,
        "correlation_id": CORRELATION,
    }
    values.update(overrides)
    return GovernedContext(**values)


GCS = context()


def candidate(
    kind: str = "EPISODIC", scope: str = "RUN", *, item_id: str = "mem-1", **overrides: Any
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "memory_item_id": item_id,
        "memory_version": 1,
        "memory_kind": kind,
        "memory_scope": scope,
        "owner_principal_id": GCS.effective_principal_id,
        "tenant_id": GCS.tenant_id,
        "organization_id": GCS.organization_id,
        "domain_id": GCS.domain_id,
        "compartments": list(GCS.compartments),
        "classification_marking_ref": M_RESTRICTED,
        "purpose": GCS.purpose,
        "content_schema_ref": "urn:ocor:memory-content:episode:1.0",
        "content_ref": "content:" + d(PAYLOAD).removeprefix("urn:sha256:"),
        "content_digest": d(PAYLOAD),
        "source_kind": "OBSERVATION",
        "source_ref": "src-telemetry-1",
        "source_digest": SOURCE_DIGEST,
        "evidence_refs": ["ev-1"],
        "provenance_refs": ["prov-1"],
        "derived_from_refs": [],
        "consolidates_refs": [],
        "created_at": format_utc_timestamp(NOW),
        "valid_from": format_utc_timestamp(NOW - timedelta(minutes=18)),
        "retention_policy_ref": "retention:standard",
        "confidence": 0.8,
        "policy_bundle_digest": POLICY_BUNDLE,
        "ontology_release_digest": ONTOLOGY,
        "governed_context_digest": GCS.digest(),
        "instruction_eligible": False,
        "taint_labels": ["EXTERNAL_DATA"],
        "representation_kinds": ["STRUCTURED", "FULL_TEXT"],
        "lifecycle_status": "ACTIVE",
    }
    value.update(SCOPE_FIELDS[scope])
    if kind == "WORKING":
        value["expires_at"] = format_utc_timestamp(NOW + timedelta(hours=4))
        value["content_schema_ref"] = "urn:ocor:memory-content:plan:1.0"
    if kind == "TEAM_SHARED":
        value["team_id"] = "team-1"
    if kind == "REFLECTION":
        value["source_kind"] = "MODEL_OUTPUT"
        value["taint_labels"] = ["MODEL_GENERATED", "REFLECTION"]
        value["content_schema_ref"] = "urn:ocor:memory-content:reflection:1.0"
    if kind == "PROCEDURAL":
        value["source_kind"] = "PROCEDURE"
        value["content_schema_ref"] = "urn:ocor:memory-content:procedure:1.0"
    if kind == "PREFERENCE":
        value["source_kind"] = "PREFERENCE"
        value["taint_labels"] = ["HUMAN_SUPPLIED"]
        value["content_schema_ref"] = "urn:ocor:memory-content:preference:1.0"
    if kind == "DISSENT":
        value["source_kind"] = "HUMAN_INPUT"
        value["taint_labels"] = ["HUMAN_SUPPLIED"]
        value["content_schema_ref"] = "urn:ocor:memory-content:dissent:1.0"
    value.update(overrides)
    return value


def envelope(cand: dict[str, Any], *, operation_id: str = "op-1", **overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "operation_id": operation_id,
        "governed_context": GCS.to_mapping(),
        "governed_context_digest": GCS.digest(),
        "deadline": format_utc_timestamp(NOW + timedelta(seconds=30)),
        "candidate": cand,
    }
    value.update(overrides)
    return value


@dataclass
class FixtureResolver:
    """Explicit fixture registry for the reference-resolution port."""

    sources: dict[str, str] = field(default_factory=lambda: {"src-telemetry-1": SOURCE_DIGEST})
    evidence_records: dict[str, EvidenceRecord] = field(default_factory=dict)
    provenance_records: dict[str, ProvenanceRecord] = field(default_factory=dict)
    approvals: dict[str, InstructionApproval] = field(default_factory=dict)
    federation: dict[str, FederationPolicy] = field(default_factory=dict)
    fail: bool = False
    seen_contexts: list[GovernedContext] = field(default_factory=list)

    def _check(self, ctx: GovernedContext) -> None:
        self.seen_contexts.append(ctx)
        if self.fail:
            raise ConnectionError("resolver backend unavailable")

    def source_digest(self, source_ref: str, ctx: GovernedContext) -> str | None:
        self._check(ctx)
        return self.sources.get(source_ref)

    def evidence(self, evidence_ref: str, ctx: GovernedContext) -> EvidenceRecord | None:
        self._check(ctx)
        return self.evidence_records.get(evidence_ref)

    def provenance(self, provenance_ref: str, ctx: GovernedContext) -> ProvenanceRecord | None:
        self._check(ctx)
        return self.provenance_records.get(provenance_ref)

    def instruction_approval(self, approval_ref: str, ctx: GovernedContext) -> InstructionApproval | None:
        self._check(ctx)
        return self.approvals.get(approval_ref)

    def federation_policy(self, policy_ref: str, ctx: GovernedContext) -> FederationPolicy | None:
        self._check(ctx)
        return self.federation.get(policy_ref)


@dataclass
class FixturePolicy:
    """Explicit policy port: permits unless told to deny, fail or go stale."""

    mode: str = "permit"
    calls: int = 0

    def authorize_admission(self, item: GovernedMemoryItem, ctx: GovernedContext) -> MemoryPolicyDecision:
        self.calls += 1
        if self.mode == "fail":
            raise TimeoutError("policy decision point timeout")
        bundle = d("policy-bundle:stale") if self.mode == "stale" else ctx.policy_bundle_digest
        return MemoryPolicyDecision(
            permitted=self.mode != "deny",
            decision_ref=f"decision:{item.version_ref}",
            policy_bundle_digest=bundle,
        )


class CountingLedger(InMemoryMemoryVersionLedger):
    """The reference ledger plus an observable append counter."""

    def __init__(self) -> None:
        super().__init__()
        self.append_calls = 0

    def append(self, record: AdmittedMemoryVersion) -> None:
        self.append_calls += 1
        super().append(record)


def evidence_record(evidence_id: str = "ev-1", marking: str = M_UNCLASSIFIED, **overrides: Any) -> EvidenceRecord:
    values: dict[str, Any] = {
        "evidence_id": evidence_id,
        "content_digest": d("evidence:" + evidence_id),
        "source_ref": "src-telemetry-1",
        "acquired_at": NOW - timedelta(hours=1),
        "acquirer_principal_id": "sensor-gateway-1",
        "method_ref": "method:telemetry-capture:1",
        "chain_of_custody": ("sensor-gateway-1",),
        "marking_ref": marking,
        "retention_until": NOW + timedelta(days=30),
    }
    values.update(overrides)
    return EvidenceRecord(**values)


def provenance_record(provenance_id: str = "prov-1", **overrides: Any) -> ProvenanceRecord:
    values: dict[str, Any] = {
        "provenance_id": provenance_id,
        "evidence_refs": ("ev-1",),
        "source_refs": ("src-telemetry-1",),
        "activity_refs": ("activity:capture-1",),
        "actor_refs": ("sensor-gateway-1",),
        "governed_context_digest": GCS.digest(),
        "correlation_id": CORRELATION,
        "causation_id": CAUSATION,
        "created_at": NOW - timedelta(hours=1),
    }
    values.update(overrides)
    return ProvenanceRecord(**values)


@dataclass
class World:
    service: MemoryAdmissionService
    ledger: Any
    resolver: FixtureResolver
    policy: FixturePolicy
    clock: InMemoryTrustedClock
    binding: VerifiedGovernedContextBinding

    def admit(self, cand: dict[str, Any], *, payload: bytes = PAYLOAD, operation_id: str = "op-1", **env: Any) -> Any:
        return self.service.admit(envelope(cand, operation_id=operation_id, **env), binding=self.binding, payload=payload)


def markings() -> LatticeMarkingResolver:
    scheme = MarkingSchemeDefinition("ocor-classification", ["UNCLASSIFIED", "RESTRICTED", "SECRET"])
    return LatticeMarkingResolver(
        scheme,
        {M_UNCLASSIFIED: "UNCLASSIFIED", M_RESTRICTED: "RESTRICTED", M_SECRET: "SECRET"},
    )


def make_world(ledger: Any | None = None) -> World:
    resolver = FixtureResolver()
    resolver.evidence_records["ev-1"] = evidence_record()
    resolver.provenance_records["prov-1"] = provenance_record()
    resolver.federation["federation-policy-1"] = FederationPolicy(
        policy_ref="federation-policy-1",
        tenant_ids=frozenset({"tenant-a"}),
        purposes=frozenset({"mission-planning"}),
        valid_until=NOW + timedelta(days=1),
    )
    policy = FixturePolicy()
    clock = InMemoryTrustedClock(NOW)
    ledger = ledger if ledger is not None else CountingLedger()
    service = MemoryAdmissionService(
        ledger=ledger,
        resolver=resolver,
        policy=policy,
        markings=markings(),
        clock=clock,
        limits=AdmissionLimits(
            retention_horizons={
                "retention:standard": timedelta(days=365),
                "retention:working": timedelta(days=1),
            }
        ),
    )
    binding = VerifiedGovernedContextBinding(binding_ref="binding:keycloak-session-1", expected=GCS)
    return World(service, ledger, resolver, policy, clock, binding)


@pytest.fixture
def world() -> World:
    return make_world()


def assert_rejected_before_persistence(
    w: World, action: Callable[[], object], reason_code: str, detail_code: str | None = None
) -> MemoryAdmissionError:
    before_calls = w.ledger.append_calls
    before = w.ledger.records()
    with pytest.raises(MemoryAdmissionError) as caught:
        action()
    assert caught.value.reason_code == reason_code, caught.value
    if detail_code is not None:
        assert caught.value.detail_code == detail_code, caught.value
    assert w.ledger.append_calls == before_calls, "a rejected candidate reached persistence"
    assert w.ledger.records() == before
    return caught.value


def supported_pairs() -> list[tuple[str, str]]:
    return [(k.value, s.value) for (k, s), ok in CAPABILITY_MATRIX.items() if ok]


def admit_semantic_base(w: World) -> str:
    w.admit(candidate("EPISODIC", "RUN", item_id="episode-base"), operation_id="op-base")
    return memory_version_ref("episode-base", 1)


def valid_for_pair(w: World, kind: str, scope: str, item_id: str) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if kind == "SEMANTIC":
        overrides["derived_from_refs"] = [admit_semantic_base(w)]
        overrides["source_kind"] = "DERIVED_SUMMARY"
        overrides["taint_labels"] = ["DERIVED", "EXTERNAL_DATA"]
        overrides["content_schema_ref"] = "urn:ocor:memory-content:summary:1.0"
    return candidate(kind, scope, item_id=item_id, **overrides)


# --------------------------------------------------------------------------
# Normative contract conformance (closed schema, every conditional branch)
# --------------------------------------------------------------------------


def schema_accepts(value: dict[str, Any]) -> bool:
    return not list(VALIDATOR.iter_errors(value))


def model_accepts(value: dict[str, Any]) -> bool:
    try:
        GovernedMemoryItem.from_mapping(value)
    except MemoryAdmissionError:
        return False
    return True


def test_the_runtime_field_set_is_exactly_the_normative_closed_schema() -> None:
    from ocor_runtime.memory.model import MEMORY_ITEM_FIELDS, REQUIRED_FIELDS

    assert set(REQUIRED_FIELDS) == set(SCHEMA["required"])
    assert MEMORY_ITEM_FIELDS == set(SCHEMA["properties"])
    assert SCHEMA["additionalProperties"] is False
    assert {k.value for k in MemoryKind} == set(SCHEMA["properties"]["memory_kind"]["enum"])
    assert {s.value for s in MemoryScope} == set(SCHEMA["properties"]["memory_scope"]["enum"])
    assert len(SCHEMA["allOf"]) == 10


CONDITIONAL_BRANCHES: list[tuple[str, dict[str, Any], dict[str, Any], str]] = [
    # (branch, positive overrides on a base fixture, field removed/changed for the negative, detail)
    ("scope RUN", {"memory_scope": "RUN", "agent_run_id": "run-1"}, {"drop": "agent_run_id"}, "SCOPE_BINDING_MISSING"),
    ("scope TASK", {"memory_scope": "TASK", "agent_run_id": "run-1", "task_id": "t-1"}, {"drop": "task_id"}, "SCOPE_BINDING_MISSING"),
    ("scope AGENT", {"memory_scope": "AGENT", "agent_id": "agent-1"}, {"drop": "agent_id"}, "SCOPE_BINDING_MISSING"),
    ("scope TEAM", {"memory_scope": "TEAM", "team_id": "team-1"}, {"drop": "team_id"}, "SCOPE_BINDING_MISSING"),
    ("scope PROJECT", {"memory_scope": "PROJECT", "project_id": "p-1"}, {"drop": "project_id"}, "SCOPE_BINDING_MISSING"),
    ("scope FEDERATED", {"memory_scope": "FEDERATED", "federation_policy_ref": "fp-1"}, {"drop": "federation_policy_ref"}, "SCOPE_BINDING_MISSING"),
    ("VECTOR representation", {"representation_kinds": ["VECTOR"], **VECTOR_BINDING}, {"drop": "embedding_digest"}, "EMBEDDING_BINDING_MISSING"),
    ("instruction eligible", {"instruction_eligible": True, "instruction_approval_ref": "approval-1"}, {"drop": "instruction_approval_ref"}, "INSTRUCTION_APPROVAL_MISSING"),
    ("LEGAL_HOLD", {"lifecycle_status": "LEGAL_HOLD", "legal_hold_ref": "hold-1", "prior_lifecycle_status": "ACTIVE"}, {"drop": "prior_lifecycle_status"}, "LEGAL_HOLD_BINDING_MISSING"),
    ("DELETION_PENDING", {"lifecycle_status": "DELETION_PENDING", "deletion_epoch": 3}, {"drop": "deletion_epoch"}, "DELETION_EPOCH_MISSING"),
    ("DELETION_INCOMPLETE", {"lifecycle_status": "DELETION_INCOMPLETE", "deletion_epoch": 3}, {"drop": "deletion_epoch"}, "DELETION_EPOCH_MISSING"),
    ("DELETED", {"lifecycle_status": "DELETED", "deletion_epoch": 0}, {"drop": "deletion_epoch"}, "DELETION_EPOCH_MISSING"),
]


def _bare_domain_fixture() -> dict[str, Any]:
    value = candidate("EPISODIC", "DOMAIN")
    return value


@pytest.mark.parametrize(("branch", "positive", "negative", "detail"), CONDITIONAL_BRANCHES, ids=[b[0] for b in CONDITIONAL_BRANCHES])
def test_every_schema_conditional_branch_has_a_positive_and_a_negative_case(
    branch: str, positive: dict[str, Any], negative: dict[str, Any], detail: str
) -> None:
    accepted = _bare_domain_fixture()
    accepted.update(positive)
    assert schema_accepts(accepted), branch
    assert model_accepts(accepted), branch

    rejected = copy.deepcopy(accepted)
    del rejected[negative["drop"]]
    # The negative differs from an accepted positive by exactly one field, so
    # both validators reject it for this branch and not for another reason.
    assert not schema_accepts(rejected), branch
    errors = list(VALIDATOR.iter_errors(rejected))
    assert all(error.validator in {"required"} for error in errors), errors
    with pytest.raises(MemoryAdmissionError) as caught:
        GovernedMemoryItem.from_mapping(rejected)
    assert caught.value.reason_code == "MEMORY_SCHEMA_INVALID"
    assert caught.value.detail_code == detail


def test_the_domain_scope_and_non_vector_representation_need_no_conditional_binding() -> None:
    value = _bare_domain_fixture()
    assert schema_accepts(value) and model_accepts(value)
    value["representation_kinds"] = ["STRUCTURED"]
    assert schema_accepts(value) and model_accepts(value)


@pytest.mark.parametrize("missing", sorted(SCHEMA["required"]))
def test_every_required_field_missing_is_rejected_by_schema_and_runtime(missing: str) -> None:
    value = candidate("EPISODIC", "DOMAIN")
    del value[missing]
    assert not schema_accepts(value)
    with pytest.raises(MemoryAdmissionError) as caught:
        GovernedMemoryItem.from_mapping(value)
    assert caught.value.reason_code == "MEMORY_SCHEMA_INVALID"
    assert caught.value.detail_code == "REQUIRED_FIELD_MISSING"


MALFORMED: list[tuple[str, Any]] = [
    ("memory_kind", "LONG_TERM"),
    ("memory_scope", "GLOBAL"),
    ("memory_version", 0),
    ("memory_version", True),
    ("memory_version", "1"),
    ("content_digest", "sha256:abc"),
    ("classification_marking_ref", "SECRET"),
    ("compartments", []),
    ("compartments", ["ops", "ops"]),
    ("evidence_refs", []),
    ("provenance_refs", []),
    ("taint_labels", []),
    ("representation_kinds", ["GRAPH"]),
    ("representation_kinds", []),
    ("confidence", 1.5),
    ("confidence", True),
    ("instruction_eligible", "false"),
    ("source_kind", "RUMOUR"),
    ("lifecycle_status", "ARCHIVED"),
    ("language", "english!"),
    ("owner_principal_id", ""),
    ("deletion_epoch", -1),
    ("embedding_dimensions", 0),
    ("prior_lifecycle_status", "PROPOSED"),
]


@pytest.mark.parametrize(("name", "bad"), MALFORMED, ids=[f"{n}={b!r}" for n, b in MALFORMED])
def test_malformed_fields_are_rejected_identically_by_schema_and_runtime(name: str, bad: Any) -> None:
    value = candidate("EPISODIC", "DOMAIN")
    value[name] = bad
    assert not schema_accepts(value)
    assert not model_accepts(value)


def test_undeclared_fields_and_aliases_are_rejected() -> None:
    for alias in ("kind", "scope", "memoryKind", "tenant", "marking"):
        value = candidate("EPISODIC", "DOMAIN")
        value[alias] = "x"
        assert not schema_accepts(value)
        with pytest.raises(MemoryAdmissionError) as caught:
            GovernedMemoryItem.from_mapping(value)
        assert caught.value.detail_code == "ADDITIONAL_PROPERTY"


def test_runtime_is_stricter_than_format_annotation_on_timestamps() -> None:
    value = candidate("EPISODIC", "DOMAIN", created_at="2026-10-08T14:00:00+02:00")
    assert schema_accepts(value)  # format is an annotation in Draft 2020-12
    with pytest.raises(MemoryAdmissionError) as caught:
        GovernedMemoryItem.from_mapping(value)
    assert caught.value.detail_code == "FIELD_INVALID"


def test_round_trip_is_exact_and_set_order_does_not_change_the_digest() -> None:
    value = candidate("EPISODIC", "DOMAIN", taint_labels=["TOOL_OUTPUT", "EXTERNAL_DATA"])
    item = GovernedMemoryItem.from_mapping(value)
    assert schema_accepts(item.to_mapping())
    assert GovernedMemoryItem.from_mapping(item.to_mapping()) == item
    reordered = dict(value, taint_labels=["EXTERNAL_DATA", "TOOL_OUTPUT"])
    assert GovernedMemoryItem.from_mapping(reordered).digest() == item.digest()
    with pytest.raises(FrozenInstanceError):
        item.memory_version = 2  # type: ignore[misc]


# --------------------------------------------------------------------------
# Capability matrix and all kinds/scopes (FGM-01)
# --------------------------------------------------------------------------


def test_capability_matrix_declares_all_56_pairs_and_covers_every_kind_and_scope() -> None:
    assert len(CAPABILITY_MATRIX) == 56
    assert {k for (k, _s), ok in CAPABILITY_MATRIX.items() if ok} == set(MemoryKind)
    assert {s for (_k, s), ok in CAPABILITY_MATRIX.items() if ok} == set(MemoryScope)


@pytest.mark.parametrize(("kind", "scope"), supported_pairs())
def test_every_supported_kind_scope_pair_is_admitted_with_audit_and_provenance(world: World, kind: str, scope: str) -> None:
    cand = valid_for_pair(world, kind, scope, item_id=f"mem-{kind}-{scope}".lower())
    assert schema_accepts(cand)
    receipt = world.admit(cand, operation_id=f"op-{kind}-{scope}")
    record = world.ledger.get(cand["memory_item_id"], 1)
    assert record is not None
    assert record.item.memory_kind.value == kind and record.item.memory_scope.value == scope
    assert schema_accepts(record.item.to_mapping())
    assert record.item.evidence_refs == ("ev-1",) and record.item.provenance_refs == ("prov-1",)
    assert record.audit_event["policy_decision_ref"] == f"decision:{record.item.version_ref}"
    assert record.audit_event["correlation_id"] == CORRELATION
    assert record.lifecycle_event["to_status"] == "ACTIVE"
    assert receipt == record.receipt
    receipt_schema = OPENAPI["components"]["schemas"]["MemoryReceipt"]
    receipt_schema = json.loads(json.dumps(receipt_schema).replace("#/components/schemas/Digest", "#/$defs/Digest"))
    receipt_schema["$defs"] = {"Digest": OPENAPI["components"]["schemas"]["Digest"]}
    assert not list(Draft202012Validator(receipt_schema).iter_errors(receipt.to_mapping()))


@pytest.mark.parametrize(("kind", "scope"), [(k.value, s.value) for (k, s), ok in CAPABILITY_MATRIX.items() if not ok])
def test_every_unsupported_pair_fails_with_unsupported_capability_before_persistence(world: World, kind: str, scope: str) -> None:
    cand = candidate(kind, scope, item_id="unsupported")
    assert schema_accepts(cand)  # the contract allows it; the capability matrix refuses it
    assert_rejected_before_persistence(world, lambda: world.admit(cand), "UNSUPPORTED_CAPABILITY", "KIND_SCOPE_UNSUPPORTED")


# --------------------------------------------------------------------------
# Rejection before persistence (FGM-02)
# --------------------------------------------------------------------------


def test_missing_metadata_invalid_kind_and_invalid_scope_never_reach_the_ledger(world: World) -> None:
    for mutate in (
        lambda c: c.pop("provenance_refs"),
        lambda c: c.pop("evidence_refs"),
        lambda c: c.pop("classification_marking_ref"),
        lambda c: c.pop("taint_labels"),
        lambda c: c.__setitem__("memory_kind", "LONG_TERM"),
        lambda c: c.__setitem__("memory_scope", "GLOBAL"),
    ):
        cand = candidate()
        mutate(cand)
        assert_rejected_before_persistence(world, lambda cand=cand: world.admit(cand), "MEMORY_SCHEMA_INVALID")


def test_authentication_and_gcs_binding_are_required(world: World) -> None:
    cand = candidate()
    assert_rejected_before_persistence(
        world,
        lambda: world.service.admit(envelope(cand), binding=None, payload=PAYLOAD),
        "AUTHENTICATION_REQUIRED",
    )
    other = VerifiedGovernedContextBinding("binding:other", context(tenant_id="tenant-b"))
    assert_rejected_before_persistence(
        world,
        lambda: world.service.admit(envelope(cand), binding=other, payload=PAYLOAD),
        "GOVERNED_CONTEXT_MISMATCH",
    )
    assert_rejected_before_persistence(
        world, lambda: world.admit(cand, governed_context_digest=d("forged")), "GOVERNED_CONTEXT_MISMATCH"
    )
    for name, bad in (
        ("tenant_id", "tenant-b"),
        ("compartments", ["ops", "intel"]),
        ("purpose", "marketing"),
        ("owner_principal_id", "someone-else"),
        ("policy_bundle_digest", d("other-bundle")),
        ("governed_context_digest", d("stale-gcs")),
    ):
        assert_rejected_before_persistence(
            world, lambda name=name, bad=bad: world.admit(candidate(**{name: bad})), "GOVERNED_CONTEXT_MISMATCH", "ITEM_NOT_BOUND_TO_GCS"
        )


def test_the_admission_envelope_is_closed_and_the_deadline_uses_the_boundary_clock(world: World) -> None:
    cand = candidate()
    request = envelope(cand)
    request["extra"] = True
    assert_rejected_before_persistence(
        world, lambda: world.service.admit(request, binding=world.binding, payload=PAYLOAD), "MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID"
    )
    world.clock.advance(timedelta(seconds=31))
    assert_rejected_before_persistence(world, lambda: world.admit(cand), "POLICY_DENIED", "DEADLINE_EXCEEDED")


@pytest.mark.parametrize(
    ("schema_ref", "reason", "detail"),
    [
        ("urn:ocor:memory-content:chain-of-thought:1.0", "POLICY_DENIED", "PROHIBITED_CONTENT_CLASS"),
        ("urn:ocor:memory-content:scratchpad:1.0", "POLICY_DENIED", "PROHIBITED_CONTENT_CLASS"),
        ("urn:ocor:memory-content:credential:1.0", "POLICY_DENIED", "PROHIBITED_CONTENT_CLASS"),
        ("urn:ocor:memory-content:secret:1.0", "POLICY_DENIED", "PROHIBITED_CONTENT_CLASS"),
        ("urn:ocor:memory-content:token:1.0", "POLICY_DENIED", "PROHIBITED_CONTENT_CLASS"),
        ("urn:ocor:memory-content:raw-conversation:1.0", "POLICY_DENIED", "PROHIBITED_CONTENT_CLASS"),
        ("urn:ocor:memory-content:unregistered:1.0", "MEMORY_SCHEMA_INVALID", "CONTENT_SCHEMA_UNKNOWN"),
    ],
)
def test_prohibited_and_unregistered_content_classes_are_rejected(world: World, schema_ref: str, reason: str, detail: str) -> None:
    assert_rejected_before_persistence(world, lambda: world.admit(candidate(content_schema_ref=schema_ref)), reason, detail)


@pytest.mark.parametrize(
    ("payload", "marker"),
    [
        (b"".join((b"-----BEGIN RSA ", b"PRIVATE KEY-----\nMIIB")), "PRIVATE_KEY"),
        (b"".join((b"aws key AKIA", b"ABCDEFGHIJKLMNOP leaked")), "CLOUD_ACCESS_KEY"),
        (b"Authorization: Bearer abc.def", "BEARER_TOKEN"),
        (b"token eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4", "JWT"),
        (b"password = hunter2", "CREDENTIAL_ASSIGNMENT"),
        (b"<thinking>step one, then</thinking>", "HIDDEN_REASONING"),
    ],
)
def test_secrets_credentials_tokens_and_hidden_reasoning_inside_allowed_classes_are_refused(world: World, payload: bytes, marker: str) -> None:
    cand = candidate(content_digest=d(payload))
    assert_rejected_before_persistence(
        world, lambda: world.admit(cand, payload=payload), "POLICY_DENIED", f"PROHIBITED_PAYLOAD_{marker}"
    )


def test_content_digest_must_bind_the_payload(world: World) -> None:
    assert_rejected_before_persistence(
        world, lambda: world.admit(candidate(), payload=PAYLOAD + b" "), "MEMORY_SCHEMA_INVALID", "CONTENT_DIGEST_MISMATCH"
    )


def test_source_evidence_and_provenance_must_resolve_under_the_same_gcs(world: World) -> None:
    assert_rejected_before_persistence(
        world, lambda: world.admit(candidate(source_digest=d("other-source"))), "MEMORY_SCHEMA_INVALID", "SOURCE_UNRESOLVED"
    )
    assert_rejected_before_persistence(
        world, lambda: world.admit(candidate(evidence_refs=["ev-unknown"])), "MEMORY_SCHEMA_INVALID", "EVIDENCE_UNRESOLVED"
    )
    assert_rejected_before_persistence(
        world, lambda: world.admit(candidate(provenance_refs=["prov-unknown"])), "MEMORY_SCHEMA_INVALID", "PROVENANCE_UNRESOLVED"
    )
    # Provenance laundering: evidence not covered by any provenance record.
    world.resolver.evidence_records["ev-2"] = evidence_record("ev-2")
    assert_rejected_before_persistence(
        world, lambda: world.admit(candidate(evidence_refs=["ev-1", "ev-2"])), "MEMORY_SCHEMA_INVALID", "PROVENANCE_INCOMPLETE"
    )
    world.resolver.provenance_records["prov-2"] = provenance_record("prov-2", evidence_refs=("ev-2",), source_refs=("src-x",))
    world.admit(candidate(evidence_refs=["ev-1", "ev-2"], provenance_refs=["prov-1", "prov-2"]))
    assert world.ledger.get("mem-1", 1) is not None
    assert all(ctx == GCS for ctx in world.resolver.seen_contexts)


def test_expired_evidence_is_refused_on_the_boundary_clock(world: World) -> None:
    world.resolver.evidence_records["ev-1"] = evidence_record(retention_until=NOW + timedelta(minutes=1))
    world.clock.advance(timedelta(minutes=2))
    cand = candidate(created_at=format_utc_timestamp(world.clock.now()))
    assert_rejected_before_persistence(
        world,
        lambda: world.admit(cand, deadline=format_utc_timestamp(world.clock.now() + timedelta(seconds=5))),
        "POLICY_DENIED",
        "EVIDENCE_RETENTION_ELAPSED",
    )


def test_temporal_and_retention_rules_use_the_boundary_clock_not_caller_values(world: World) -> None:
    backdated = candidate(created_at=format_utc_timestamp(NOW - timedelta(hours=1)))
    assert_rejected_before_persistence(world, lambda: world.admit(backdated), "POLICY_DENIED", "CREATED_AT_OUTSIDE_BOUNDARY_WINDOW")
    future = candidate(created_at=format_utc_timestamp(NOW + timedelta(minutes=5)))
    assert_rejected_before_persistence(world, lambda: world.admit(future), "POLICY_DENIED", "CREATED_AT_OUTSIDE_BOUNDARY_WINDOW")
    expired = candidate(expires_at=format_utc_timestamp(NOW - timedelta(seconds=1)))
    assert_rejected_before_persistence(world, lambda: world.admit(expired), "POLICY_DENIED", "ALREADY_EXPIRED")
    beyond = candidate(expires_at=format_utc_timestamp(NOW + timedelta(days=400)))
    assert_rejected_before_persistence(world, lambda: world.admit(beyond), "POLICY_DENIED", "RETENTION_HORIZON_EXCEEDED")
    unknown = candidate(retention_policy_ref="retention:forever")
    assert_rejected_before_persistence(world, lambda: world.admit(unknown), "POLICY_DENIED", "RETENTION_POLICY_UNKNOWN")
    inverted = candidate(valid_until=format_utc_timestamp(NOW - timedelta(hours=1)))
    assert_rejected_before_persistence(world, lambda: world.admit(inverted), "MEMORY_SCHEMA_INVALID", "VALIDITY_WINDOW_INVALID")
    working = candidate("WORKING", "RUN")
    del working["expires_at"]
    assert_rejected_before_persistence(world, lambda: world.admit(working), "POLICY_DENIED", "WORKING_MEMORY_TTL_REQUIRED")
    within = candidate(created_at=format_utc_timestamp(NOW - timedelta(seconds=20)), expires_at=format_utc_timestamp(NOW + timedelta(days=364)))
    world.admit(within)
    assert world.ledger.get("mem-1", 1) is not None


def test_admission_enters_the_lifecycle_only_at_proposed_active_or_quarantined(world: World) -> None:
    for status, extra in (
        ("SUPERSEDED", {}),
        ("REVOKED", {}),
        ("EXPIRED", {}),
        ("LEGAL_HOLD", {"legal_hold_ref": "hold-1", "prior_lifecycle_status": "ACTIVE"}),
        ("DELETION_PENDING", {"deletion_epoch": 1}),
        ("DELETED", {"deletion_epoch": 1}),
        ("ACTIVE", {"deletion_epoch": 1}),
    ):
        cand = candidate(lifecycle_status=status, **extra)
        assert_rejected_before_persistence(world, lambda cand=cand: world.admit(cand), "LIFECYCLE_TRANSITION_INVALID", "ADMISSION_STATUS_INVALID")
    for index, status in enumerate(("PROPOSED", "ACTIVE", "QUARANTINED")):
        receipt = world.admit(candidate(item_id=f"status-{index}", lifecycle_status=status), operation_id=f"op-status-{index}")
        assert receipt.lifecycle_status == status


def test_kind_semantics_are_enforced(world: World) -> None:
    semantic = candidate("SEMANTIC", "DOMAIN", item_id="sem")
    assert_rejected_before_persistence(world, lambda: world.admit(semantic), "MEMORY_SCHEMA_INVALID", "SEMANTIC_DERIVATION_MISSING")
    team_shared = candidate("TEAM_SHARED", "PROJECT", item_id="team")
    del team_shared["team_id"]
    assert_rejected_before_persistence(world, lambda: world.admit(team_shared), "MEMORY_SCHEMA_INVALID", "TEAM_BINDING_MISSING")
    consolidation = candidate(source_kind="MEMORY_CONSOLIDATION", taint_labels=["DERIVED"])
    assert_rejected_before_persistence(world, lambda: world.admit(consolidation), "MEMORY_SCHEMA_INVALID", "CONSOLIDATION_LINEAGE_INVALID")
    stray = candidate("EPISODIC", "RUN", federation_policy_ref="federation-policy-1")
    assert_rejected_before_persistence(world, lambda: world.admit(stray), "MEMORY_SCHEMA_INVALID", "FEDERATION_BINDING_UNEXPECTED")


# --------------------------------------------------------------------------
# Markings and taint
# --------------------------------------------------------------------------


def test_marking_is_the_conservative_join_and_cannot_be_downgraded(world: World) -> None:
    downgraded = candidate(classification_marking_ref=M_UNCLASSIFIED)
    assert_rejected_before_persistence(world, lambda: world.admit(downgraded), "POLICY_DENIED", "MARKING_DOWNGRADE")
    world.resolver.evidence_records["ev-1"] = evidence_record(marking=M_SECRET)
    assert_rejected_before_persistence(world, lambda: world.admit(candidate()), "AUTHORITY_DENIED", "INPUT_MARKING_EXCEEDS_CONTEXT")
    world.resolver.evidence_records["ev-1"] = evidence_record(marking=M_RESTRICTED)
    world.admit(candidate(classification_marking_ref=M_SECRET))  # stricter than the join is conservative
    record = world.ledger.get("mem-1", 1)
    assert record is not None and record.item.classification_marking_ref == M_SECRET
    unknown = candidate(item_id="mem-unknown-marking", classification_marking_ref=d("marking:UNLISTED"))
    assert_rejected_before_persistence(world, lambda: world.admit(unknown, operation_id="op-u"), "POLICY_DENIED", "MARKING_UNKNOWN")


@pytest.mark.parametrize(
    ("source_kind", "required"),
    [
        ("OBSERVATION", "EXTERNAL_DATA"),
        ("EVIDENCE", "EXTERNAL_DATA"),
        ("TOOL_RESULT", "TOOL_OUTPUT"),
        ("HUMAN_INPUT", "HUMAN_SUPPLIED"),
        ("MODEL_OUTPUT", "MODEL_GENERATED"),
        ("DERIVED_SUMMARY", "DERIVED"),
        ("PROCEDURE", "EXTERNAL_DATA"),
        ("PREFERENCE", "HUMAN_SUPPLIED"),
    ],
)
def test_every_source_kind_requires_its_taint_label(world: World, source_kind: str, required: str) -> None:
    wrong = "UNREVIEWED" if required != "UNREVIEWED" else "OTHER"
    assert_rejected_before_persistence(
        world, lambda: world.admit(candidate(source_kind=source_kind, taint_labels=[wrong])), "MEMORY_TAINTED", "TAINT_LABEL_MISSING"
    )
    world.admit(candidate(source_kind=source_kind, taint_labels=[required, wrong]))
    assert world.ledger.get("mem-1", 1) is not None


def test_reflection_is_always_model_generated_tainted(world: World) -> None:
    reflection = candidate("REFLECTION", "AGENT", item_id="refl", source_kind="HUMAN_INPUT", taint_labels=["HUMAN_SUPPLIED"])
    assert_rejected_before_persistence(world, lambda: world.admit(reflection), "MEMORY_TAINTED", "TAINT_LABEL_MISSING")


def test_taint_is_inherited_along_lineage_and_cannot_be_laundered(world: World) -> None:
    world.admit(candidate(source_kind="MODEL_OUTPUT", taint_labels=["MODEL_GENERATED"]), operation_id="op-v1")
    laundered = candidate(
        memory_version=2,
        supersedes_ref=memory_version_ref("mem-1", 1),
        source_kind="OBSERVATION",
        taint_labels=["EXTERNAL_DATA"],
    )
    assert_rejected_before_persistence(world, lambda: world.admit(laundered, operation_id="op-v2"), "MEMORY_TAINTED", "TAINT_LABEL_MISSING")
    derived = candidate(
        "SEMANTIC",
        "DOMAIN",
        item_id="sem-1",
        source_kind="DERIVED_SUMMARY",
        taint_labels=["DERIVED"],
        derived_from_refs=[memory_version_ref("mem-1", 1)],
    )
    assert_rejected_before_persistence(world, lambda: world.admit(derived, operation_id="op-sem"), "MEMORY_TAINTED", "TAINT_LABEL_MISSING")
    derived["taint_labels"] = ["DERIVED", "MODEL_GENERATED"]
    world.admit(derived, operation_id="op-sem")
    assert world.ledger.get("sem-1", 1) is not None


# --------------------------------------------------------------------------
# Scope authority and instruction eligibility
# --------------------------------------------------------------------------


def test_federated_scope_requires_an_applicable_federation_policy(world: World) -> None:
    for ref, policy in (
        ("federation-policy-missing", None),
        ("fp-other-tenant", FederationPolicy("fp-other-tenant", frozenset({"tenant-b"}), frozenset({"mission-planning"}), NOW + timedelta(days=1))),
        ("fp-other-purpose", FederationPolicy("fp-other-purpose", frozenset({"tenant-a"}), frozenset({"training"}), NOW + timedelta(days=1))),
        ("fp-expired", FederationPolicy("fp-expired", frozenset({"tenant-a"}), frozenset({"mission-planning"}), NOW)),
    ):
        if policy is not None:
            world.resolver.federation[ref] = policy
        cand = candidate("EPISODIC", "FEDERATED", item_id="fed", federation_policy_ref=ref)
        assert_rejected_before_persistence(world, lambda cand=cand: world.admit(cand), "AUTHORITY_DENIED", "FEDERATION_POLICY_NOT_APPLICABLE")


def _approval(**overrides: Any) -> InstructionApproval:
    values: dict[str, Any] = {
        "approval_ref": "approval-1",
        "memory_item_id": "proc-1",
        "approved_content_digest": d(PAYLOAD),
        "approver_principal_id": "human-approver-1",
        "tenant_id": "tenant-a",
        "valid_until": NOW + timedelta(days=1),
    }
    values.update(overrides)
    return InstructionApproval(**values)


def test_procedural_instruction_eligibility_needs_a_separate_exact_current_approval(world: World) -> None:
    proc = candidate("PROCEDURAL", "TEAM", item_id="proc-1", instruction_eligible=True, instruction_approval_ref="approval-1")
    assert_rejected_before_persistence(world, lambda: world.admit(proc), "AUTHORITY_DENIED", "INSTRUCTION_APPROVAL_INVALID")
    for bad in (
        _approval(memory_item_id="proc-other"),
        _approval(approved_content_digest=d("other-content")),
        _approval(approver_principal_id=GCS.effective_principal_id),
        _approval(tenant_id="tenant-b"),
        _approval(valid_until=NOW),
    ):
        world.resolver.approvals["approval-1"] = bad
        assert_rejected_before_persistence(world, lambda: world.admit(proc), "AUTHORITY_DENIED", "INSTRUCTION_APPROVAL_INVALID")
    world.resolver.approvals["approval-1"] = _approval()
    receipt = world.admit(proc)
    assert receipt.memory_item_id == "proc-1"


def test_only_procedural_human_or_external_content_may_be_instruction_eligible(world: World) -> None:
    world.resolver.approvals["approval-1"] = _approval(memory_item_id="x")
    reflection = candidate("REFLECTION", "AGENT", item_id="x", instruction_eligible=True, instruction_approval_ref="approval-1")
    assert_rejected_before_persistence(world, lambda: world.admit(reflection), "MEMORY_TAINTED", "MODEL_GENERATED_INSTRUCTION")
    episodic = candidate("EPISODIC", "AGENT", item_id="x", instruction_eligible=True, instruction_approval_ref="approval-1")
    assert_rejected_before_persistence(world, lambda: world.admit(episodic), "UNSUPPORTED_CAPABILITY", "INSTRUCTION_ELIGIBILITY_UNSUPPORTED")
    model_proc = candidate(
        "PROCEDURAL", "AGENT", item_id="x", source_kind="MODEL_OUTPUT", taint_labels=["MODEL_GENERATED"],
        instruction_eligible=True, instruction_approval_ref="approval-1",
    )
    assert_rejected_before_persistence(world, lambda: world.admit(model_proc), "MEMORY_TAINTED", "MODEL_GENERATED_INSTRUCTION")


# --------------------------------------------------------------------------
# Policy port and fault handling
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "reason", "detail"),
    [
        ("deny", "POLICY_DENIED", "ADMISSION_DENIED"),
        ("stale", "STALE_POLICY", "POLICY_BUNDLE_MISMATCH"),
        ("fail", "CONTROL_PLANE_UNAVAILABLE", "POLICY_UNAVAILABLE"),
    ],
)
def test_policy_denial_staleness_and_outage_fail_closed(world: World, mode: str, reason: str, detail: str) -> None:
    world.policy.mode = mode
    error = assert_rejected_before_persistence(world, lambda: world.admit(candidate()), reason, detail)
    problem = error.to_problem()
    problem_schema = OPENAPI["components"]["schemas"]["Problem"]
    assert not list(Draft202012Validator(problem_schema).iter_errors(problem))
    assert problem["correlation_id"] == CORRELATION
    assert "pump" not in json.dumps(problem)


def test_resolver_outage_fails_closed(world: World) -> None:
    world.resolver.fail = True
    assert_rejected_before_persistence(world, lambda: world.admit(candidate()), "CONTROL_PLANE_UNAVAILABLE", "REFERENCE_RESOLVER_UNAVAILABLE")


def test_policy_is_never_consulted_for_a_candidate_rejected_earlier(world: World) -> None:
    assert_rejected_before_persistence(world, lambda: world.admit(candidate(memory_kind="LONG_TERM")), "MEMORY_SCHEMA_INVALID")
    assert world.policy.calls == 0


# --------------------------------------------------------------------------
# Idempotency and immutable version lineage (FGM-09)
# --------------------------------------------------------------------------


def test_same_idempotency_key_and_digest_returns_the_original_receipt(world: World) -> None:
    first = world.admit(candidate())
    world.clock.advance(timedelta(seconds=10))
    again = world.admit(candidate(), deadline=format_utc_timestamp(world.clock.now() + timedelta(seconds=30)))
    assert again == first
    assert world.ledger.append_calls == 1


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        (b'{"note":"different observation"}', "CONTENT_DIGEST_MISMATCH"),
        (b"", "CONTENT_DIGEST_MISMATCH"),
        (b"password = hunter2", "CONTENT_DIGEST_MISMATCH"),
        (b"".join((b"-----BEGIN RSA ", b"PRIVATE KEY-----\nMIIB")), "CONTENT_DIGEST_MISMATCH"),
        (b"Authorization: Bearer abc.def", "CONTENT_DIGEST_MISMATCH"),
        (b"<thinking>hidden reasoning</thinking>", "CONTENT_DIGEST_MISMATCH"),
        (bytearray(b"altered bytes"), "CONTENT_DIGEST_MISMATCH"),
        ("not bytes", "PAYLOAD_INVALID"),
        (None, "PAYLOAD_INVALID"),
    ],
)
def test_same_idempotency_key_revalidates_payload_before_returning_receipt(
    journal: Path, payload: Any, detail: str
) -> None:
    # The first admission and a fresh service share the real durable journal.
    original = make_world(JournalMemoryVersionLedger(journal))
    receipt = original.admit(candidate())
    before = journal.read_bytes()
    later = make_world(JournalMemoryVersionLedger(journal))
    head = later.ledger.head
    with pytest.raises(MemoryAdmissionError) as caught:
        later.admit(candidate(), payload=payload)
    error = caught.value
    assert (error.reason_code, error.detail_code) == ("MEMORY_SCHEMA_INVALID", detail)
    assert error.correlation_id == GCS.correlation_id
    assert journal.read_bytes() == before
    assert later.ledger.head == head
    assert len(journal.read_bytes().splitlines()) == 1
    assert later.ledger.get("mem-1", 1).receipt == receipt
    assert later.policy.calls == 0
    # Rejection must not poison the key: identical bytes still replay exactly.
    assert later.admit(candidate(), payload=PAYLOAD) == receipt
    assert journal.read_bytes() == before
    assert later.policy.calls == 0


def test_same_idempotency_key_revalidates_the_current_content_registry(journal: Path) -> None:
    original = make_world(JournalMemoryVersionLedger(journal))
    receipt = original.admit(candidate())
    before = journal.read_bytes()
    later = make_world(JournalMemoryVersionLedger(journal))
    service = MemoryAdmissionService(
        ledger=later.ledger,
        resolver=later.resolver,
        policy=later.policy,
        markings=markings(),
        clock=later.clock,
        limits=AdmissionLimits(retention_horizons={}, content_schemas=frozenset()),
    )
    with pytest.raises(MemoryAdmissionError) as caught:
        service.admit(envelope(candidate()), binding=later.binding, payload=PAYLOAD)
    assert (caught.value.reason_code, caught.value.detail_code) == (
        "MEMORY_SCHEMA_INVALID", "CONTENT_SCHEMA_UNKNOWN"
    )
    assert journal.read_bytes() == before
    assert later.ledger.get("mem-1", 1).receipt == receipt
    assert later.policy.calls == 0


def test_same_idempotency_key_with_a_different_digest_is_a_conflict(world: World) -> None:
    world.admit(candidate())
    assert_rejected_before_persistence(
        world, lambda: world.admit(candidate(confidence=0.1)), "MEMORY_IDEMPOTENCY_CONFLICT", "IDEMPOTENCY_DIGEST_MISMATCH"
    )


def test_mutable_overwrite_of_an_admitted_version_is_rejected_before_persistence(world: World) -> None:
    world.admit(candidate())
    overwrite = candidate(confidence=0.1, source_digest=SOURCE_DIGEST)
    assert_rejected_before_persistence(
        world, lambda: world.admit(overwrite, operation_id="op-overwrite"), "MEMORY_IDEMPOTENCY_CONFLICT", "IMMUTABLE_VERSION_OCCUPIED"
    )
    duplicate = candidate()
    assert_rejected_before_persistence(
        world, lambda: world.admit(duplicate, operation_id="op-dup"), "MEMORY_IDEMPOTENCY_CONFLICT", "VERSION_ALREADY_ADMITTED"
    )
    record = world.ledger.get("mem-1", 1)
    assert record is not None and record.item.confidence == 0.8


def test_a_correction_creates_a_new_immutable_version_with_exact_version_replay(world: World) -> None:
    v1 = world.admit(candidate())
    corrected_payload = b'{"note":"pump P-101 vibration exceeded threshold at 11:41"}'
    v2_candidate = candidate(
        memory_version=2,
        supersedes_ref=memory_version_ref("mem-1", 1),
        correction_of_ref=memory_version_ref("mem-1", 1),
        content_digest=d(corrected_payload),
        content_ref="content:" + d(corrected_payload).removeprefix("urn:sha256:"),
    )
    v2 = world.admit(v2_candidate, payload=corrected_payload, operation_id="op-correction")
    assert (v1.memory_version, v2.memory_version) == (1, 2)
    old = world.ledger.get("mem-1", 1)
    new = world.ledger.get("mem-1", 2)
    assert old is not None and new is not None
    assert old.receipt == v1 and old.item.content_digest == d(PAYLOAD)
    assert new.item.supersedes_ref == memory_version_ref("mem-1", 1)
    assert world.ledger.latest_version("mem-1") == 2
    assert GovernedMemoryItem.from_mapping(old.item.to_mapping()).digest() == old.item_digest


def test_lineage_must_be_contiguous_and_bound_to_the_same_item(world: World) -> None:
    v2_unknown = candidate(item_id="ghost", memory_version=2, supersedes_ref=memory_version_ref("ghost", 1))
    assert_rejected_before_persistence(world, lambda: world.admit(v2_unknown), "MEMORY_NOT_FOUND", "ITEM_UNKNOWN")
    world.admit(candidate())
    gap = candidate(memory_version=3, supersedes_ref=memory_version_ref("mem-1", 2))
    assert_rejected_before_persistence(world, lambda: world.admit(gap, operation_id="op-gap"), "MEMORY_VERSION_NOT_FOUND", "VERSION_GAP")
    unlinked = candidate(memory_version=2, confidence=0.5)
    assert_rejected_before_persistence(world, lambda: world.admit(unlinked, operation_id="op-unlinked"), "MEMORY_SCHEMA_INVALID", "LINEAGE_INVALID")
    first_superseding = candidate(item_id="fresh", supersedes_ref=memory_version_ref("mem-1", 1))
    assert_rejected_before_persistence(world, lambda: world.admit(first_superseding, operation_id="op-fresh"), "MEMORY_SCHEMA_INVALID", "LINEAGE_INVALID")
    bad_correction = candidate(memory_version=2, supersedes_ref=memory_version_ref("mem-1", 1), correction_of_ref=memory_version_ref("other", 1))
    assert_rejected_before_persistence(world, lambda: world.admit(bad_correction, operation_id="op-badcorr"), "MEMORY_SCHEMA_INVALID", "LINEAGE_INVALID")
    for name, value in (("memory_kind", "SEMANTIC"), ("memory_scope", "AGENT"), ("agent_run_id", "run-2")):
        changed = candidate(memory_version=2, supersedes_ref=memory_version_ref("mem-1", 1), **{name: value})
        if name == "memory_kind":
            changed["derived_from_refs"] = [memory_version_ref("mem-1", 1)]
        if name == "memory_scope":
            changed["agent_id"] = "agent-1"
        assert_rejected_before_persistence(
            world, lambda changed=changed: world.admit(changed, operation_id=f"op-{name}"), "MEMORY_SCHEMA_INVALID", "LINEAGE_IDENTITY_CHANGED"
        )
    missing_source = candidate("SEMANTIC", "DOMAIN", item_id="sem", derived_from_refs=[memory_version_ref("absent", 1)])
    assert_rejected_before_persistence(world, lambda: world.admit(missing_source, operation_id="op-ms"), "MEMORY_VERSION_NOT_FOUND", "LINEAGE_SOURCE_MISSING")
    malformed = candidate("SEMANTIC", "DOMAIN", item_id="sem", derived_from_refs=["mem-1@1"])
    assert_rejected_before_persistence(world, lambda: world.admit(malformed, operation_id="op-mf"), "MEMORY_SCHEMA_INVALID", "VERSION_REF_INVALID")


def test_lineage_cannot_cross_tenant_or_unauthorized_compartments() -> None:
    ledger = CountingLedger()
    world_b = make_world(ledger)
    ctx_b = context(tenant_id="tenant-b", compartments=("ops", "intel"))
    world_b.binding = VerifiedGovernedContextBinding("binding:b", ctx_b)
    cand_b = candidate(
        item_id="foreign", tenant_id="tenant-b", compartments=["intel", "ops"], governed_context_digest=ctx_b.digest()
    )
    world_b.resolver.provenance_records["prov-1"] = provenance_record(governed_context_digest=ctx_b.digest())
    world_b.service.admit(
        envelope(cand_b, governed_context=ctx_b.to_mapping(), governed_context_digest=ctx_b.digest()),
        binding=world_b.binding,
        payload=PAYLOAD,
    )
    world_a = make_world(ledger)
    derived = candidate("SEMANTIC", "DOMAIN", item_id="sem", derived_from_refs=[memory_version_ref("foreign", 1)])
    assert_rejected_before_persistence(world_a, lambda: world_a.admit(derived, operation_id="op-x"), "AUTHORITY_DENIED", "CROSS_TENANT_LINEAGE")

    ctx_wide = context(compartments=("ops", "intel"))
    world_w = make_world(ledger)
    world_w.binding = VerifiedGovernedContextBinding("binding:w", ctx_wide)
    wide = candidate(item_id="wide", compartments=["intel", "ops"], governed_context_digest=ctx_wide.digest())
    world_w.service.admit(envelope(wide, governed_context=ctx_wide.to_mapping(), governed_context_digest=ctx_wide.digest()), binding=world_w.binding, payload=PAYLOAD)
    narrow = candidate("SEMANTIC", "DOMAIN", item_id="sem", derived_from_refs=[memory_version_ref("wide", 1)])
    assert_rejected_before_persistence(world_a, lambda: world_a.admit(narrow, operation_id="op-y"), "AUTHORITY_DENIED", "LINEAGE_COMPARTMENT_NOT_AUTHORIZED")


def test_concurrent_writers_of_the_same_next_version_cannot_both_win() -> None:
    world = make_world()
    world.admit(candidate())
    outcomes: list[str] = []
    barrier = threading.Barrier(8)

    def writer(index: int) -> None:
        payload = f'{{"note":"concurrent correction {index}"}}'.encode()
        cand = candidate(
            memory_version=2,
            supersedes_ref=memory_version_ref("mem-1", 1),
            content_digest=d(payload),
        )
        barrier.wait()
        try:
            world.admit(cand, payload=payload, operation_id=f"op-race-{index}")
            outcomes.append("won")
        except MemoryAdmissionError as exc:
            outcomes.append(exc.reason_code)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("won") == 1
    assert set(outcomes) - {"won"} == {"MEMORY_IDEMPOTENCY_CONFLICT"}
    assert world.ledger.latest_version("mem-1") == 2


# --------------------------------------------------------------------------
# Durable journal: cross-run persistence, tamper and torn writes (real FS,
# real separate interpreter processes)
# --------------------------------------------------------------------------


def run_python(code: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code), *args],
        capture_output=True,
        text=True,
        check=False,
        env={"PYTHONPATH": str(RUNTIME_SRC), "PATH": "/usr/bin:/bin"},
        timeout=60,
    )


READER = """
import json, sys
from pathlib import Path
from ocor_runtime.memory.model import JournalMemoryVersionLedger
ledger = JournalMemoryVersionLedger(Path(sys.argv[1]))
record = ledger.get(sys.argv[2], int(sys.argv[3]))
print(json.dumps({"digest": record.item_digest, "receipt": record.receipt.to_mapping(),
                  "latest": ledger.latest_version(sys.argv[2]), "head": ledger.head}))
"""


@pytest.fixture
def journal(tmp_path: Path) -> Iterator[Path]:
    yield tmp_path / "memory" / "versions.jsonl"


def test_admitted_versions_persist_across_runs_and_replay_exactly(journal: Path) -> None:
    world = make_world(JournalMemoryVersionLedger(journal))
    receipt = world.admit(candidate())
    payload_v2 = b'{"note":"follow-up"}'
    world.admit(
        candidate(memory_version=2, supersedes_ref=memory_version_ref("mem-1", 1), content_digest=d(payload_v2)),
        payload=payload_v2,
        operation_id="op-2",
    )
    result = run_python(READER, str(journal), "mem-1", "1")
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    record = world.ledger.get("mem-1", 1)
    assert observed["digest"] == record.item_digest
    assert observed["receipt"] == receipt.to_mapping()
    assert observed["latest"] == 2
    assert observed["head"] == world.ledger.head
    reopened = JournalMemoryVersionLedger(journal)
    assert reopened.get("mem-1", 2).item == world.ledger.get("mem-1", 2).item
    # A later run with a fresh service continues the lineage and cannot overwrite.
    later = make_world(JournalMemoryVersionLedger(journal))
    with pytest.raises(MemoryAdmissionError) as caught:
        later.admit(candidate(confidence=0.2), operation_id="op-later")
    assert caught.value.detail_code == "IMMUTABLE_VERSION_OCCUPIED"


def test_rejected_candidates_leave_the_journal_byte_identical(journal: Path) -> None:
    world = make_world(JournalMemoryVersionLedger(journal))
    world.admit(candidate())
    before = journal.read_bytes()
    for cand in (candidate(memory_kind="LONG_TERM"), candidate(confidence=0.3), candidate(item_id="x", memory_scope="GLOBAL")):
        with pytest.raises(MemoryAdmissionError):
            world.admit(cand, operation_id="op-reject")
    assert journal.read_bytes() == before


WRITER = """
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
sys.path.insert(0, sys.argv[3])
import test_ocor_dev_0050 as t
from ocor_runtime.memory.model import JournalMemoryVersionLedger, MemoryAdmissionError, memory_version_ref
import time
world = t.make_world(JournalMemoryVersionLedger(Path(sys.argv[1])))
index = sys.argv[2]
start_at = float(sys.argv[4])
while time.time() < start_at:
    time.sleep(0.0005)
payload = ("{\\"note\\":\\"process correction " + index + "\\"}").encode()
cand = t.candidate(memory_version=2, supersedes_ref=memory_version_ref("mem-1", 1), content_digest=t.d(payload))
try:
    world.admit(cand, payload=payload, operation_id="op-proc-" + index)
    print("won")
except MemoryAdmissionError as exc:
    print(exc.reason_code)
"""


def test_separate_processes_racing_for_the_same_version_cannot_overwrite(journal: Path) -> None:
    make_world(JournalMemoryVersionLedger(journal)).admit(candidate())
    tests_dir = str(Path(__file__).resolve().parent)
    start_at = time.time() + 4.0  # every process is fully initialised before the race
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", textwrap.dedent(WRITER), str(journal), str(i), tests_dir, str(start_at)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={"PYTHONPATH": str(RUNTIME_SRC), "PATH": "/usr/bin:/bin"},
        )
        for i in range(8)
    ]
    outputs = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=120)
        assert process.returncode == 0, stderr
        outputs.append(stdout.strip())
    assert outputs.count("won") == 1, outputs
    assert set(outputs) - {"won"} == {"MEMORY_IDEMPOTENCY_CONFLICT"}
    reopened = JournalMemoryVersionLedger(journal)
    assert reopened.latest_version("mem-1") == 2
    assert len(journal.read_bytes().splitlines()) == 2


def test_tampering_with_an_acknowledged_version_is_detected_fail_closed(journal: Path) -> None:
    world = make_world(JournalMemoryVersionLedger(journal))
    world.admit(candidate())
    original = journal.read_bytes()
    journal.write_bytes(original.replace(b'"confidence":0.8', b'"confidence":0.9'))
    with pytest.raises(MemoryLedgerCorrupted):
        JournalMemoryVersionLedger(journal)
    result = run_python(READER, str(journal), "mem-1", "1")
    assert result.returncode != 0 and "MEMORY_LEDGER_CORRUPTED" in result.stderr


def test_a_torn_unacknowledged_write_blocks_the_journal(journal: Path) -> None:
    world = make_world(JournalMemoryVersionLedger(journal))
    world.admit(candidate())
    with journal.open("ab") as handle:
        handle.write(b'{"entry_digest":"urn:sha256:')
    with pytest.raises(MemoryLedgerCorrupted) as caught:
        JournalMemoryVersionLedger(journal)
    assert "torn" in str(caught.value)


def test_removed_or_reordered_entries_break_the_chain(journal: Path) -> None:
    world = make_world(JournalMemoryVersionLedger(journal))
    world.admit(candidate())
    world.admit(candidate(item_id="mem-2"), operation_id="op-2")
    lines = journal.read_bytes().splitlines(keepends=True)
    journal.write_bytes(lines[1] + lines[0])
    with pytest.raises(MemoryLedgerCorrupted):
        JournalMemoryVersionLedger(journal)
    journal.write_bytes(lines[1])
    with pytest.raises(MemoryLedgerCorrupted):
        JournalMemoryVersionLedger(journal)


def test_the_ledger_refuses_a_record_whose_receipt_or_audit_was_altered(world: World) -> None:
    world.admit(candidate())
    record = world.ledger.get("mem-1", 1)
    forged = AdmittedMemoryVersion(
        item=record.item,
        item_digest=record.item_digest,
        idempotency_key=("tenant-a", "RUN", SOURCE_DIGEST, d(PAYLOAD), "op-forged"),
        lifecycle_event=record.lifecycle_event,
        audit_event=dict(record.audit_event, policy_decision_ref="decision:forged"),
        receipt=record.receipt,
    )
    with pytest.raises(MemoryLedgerCorrupted):
        InMemoryMemoryVersionLedger().append(forged)


def test_memory_identifiers_are_backend_free_and_opaque() -> None:
    ref = memory_version_ref("mem-1", 7)
    assert ref == "urn:ocor:memory:mem-1:v7"
    assert uuid.UUID(CORRELATION)  # correlation ids are canonical UUIDs at the boundary


def _record_for(world: World, cand: dict[str, Any], payload: bytes, operation_id: str) -> AdmittedMemoryVersion:
    """Admit on a scratch ledger to obtain a genuine, self-consistent record."""

    world.admit(cand, payload=payload, operation_id=operation_id)
    record = world.ledger.get(cand["memory_item_id"], cand["memory_version"])
    assert record is not None
    return record


@pytest.mark.parametrize("ledger_kind", ["memory", "journal"])
def test_the_ledger_itself_refuses_gaps_occupied_slots_and_reused_keys(tmp_path: Path, ledger_kind: str) -> None:
    scratch = make_world()
    v1 = _record_for(scratch, candidate(), PAYLOAD, "op-1")
    payload_v2 = b'{"note":"v2"}'
    v2 = _record_for(
        scratch,
        candidate(memory_version=2, supersedes_ref=memory_version_ref("mem-1", 1), content_digest=d(payload_v2)),
        payload_v2,
        "op-2",
    )
    other = _record_for(scratch, candidate(item_id="mem-other"), PAYLOAD, "op-other")
    reused_key = AdmittedMemoryVersion(
        item=other.item,
        item_digest=other.item_digest,
        idempotency_key=v1.idempotency_key,
        lifecycle_event=other.lifecycle_event,
        audit_event=other.audit_event,
        receipt=other.receipt,
    )
    ledger: Any = (
        InMemoryMemoryVersionLedger() if ledger_kind == "memory" else JournalMemoryVersionLedger(tmp_path / "j.jsonl")
    )
    with pytest.raises(MemoryAdmissionError) as gap:
        ledger.append(v2)
    assert (gap.value.reason_code, gap.value.detail_code) == ("MEMORY_VERSION_NOT_FOUND", "VERSION_GAP")
    ledger.append(v1)
    with pytest.raises(MemoryAdmissionError) as occupied:
        ledger.append(v1)
    assert occupied.value.detail_code == "IMMUTABLE_VERSION_OCCUPIED"
    with pytest.raises(MemoryAdmissionError) as reused:
        ledger.append(reused_key)
    assert reused.value.detail_code == "IDEMPOTENCY_KEY_REUSED"
    ledger.append(v2)
    assert ledger.latest_version("mem-1") == 2
    assert ledger.by_idempotency_key(v1.idempotency_key) == v1
