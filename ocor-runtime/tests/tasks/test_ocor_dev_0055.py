"""OCOR-DEV-0055: Implement retention expiry revocation forgetting and legal hold.

Acceptance (backlog): policy transitions deterministically exclude
revoked/expired items while legal hold blocks deletion.  Negative: held
content cannot be deleted; excluded items cannot influence results or caches;
a SKIPPED, UNAVAILABLE, mock-only or NOT_EXECUTED qualifying case is not
accepted.

Oracles: ADD v1.3 Part II §2.10 (the lifecycle FSM verbatim; forgetting
triggers; legal hold blocks deletion; deletion is a saga over content,
embeddings, indexes and caches; partial completion blocks retrieval and stays
visible as ``DELETION_INCOMPLETE``), §2.5 (every change is a new immutable
version), §2.7 (excluded items never reach ranking, normalisation, counts,
explanations or caches), §2.8 (revocation invalidates the representation),
§2.13 (configured retention horizon); LLD v1.1 §2.8.6 (``DELETION_INCOMPLETE``
retry; leaving legal hold restores the recorded prior disposition; deletion
epoch and non-content tombstone; retrieval fails closed until completion) and
§7.2 ``FGM-10`` (absence from result, rank, count, cache and explanation),
``FGM-11`` (deletion blocked, prior disposition restored), ``FGM-12``
(``DELETION_INCOMPLETE`` fail closed, then completion) and ``FGM-19``
(deterministic selection, legal hold protected).

Qualifying cases run on the real, pinned backends of OCOR-DEV-0051/0053:
PostgreSQL 16 from ``OCOR_LIVE_POSTGRES_DSN`` (metadata, encrypted content,
full-text index and representation descriptors, one schema per world), Qdrant
1.15.1 (native and parallel vector indexes, one namespace per world) and
OpenBao 2.6.2 transit.  Items come from the real OCOR-DEV-0050 admission
service, are stored by the real OCOR-DEV-0053 embedding lifecycle coordinator
and searched by the real OCOR-DEV-0052 retrieval service.  A missing backend
fails, it never skips.  The unit cases use the 0051 in-memory port fixtures
only for envelope, FSM, journal and guard branch logic; none of them is
qualifying.
"""

from __future__ import annotations

import ast
import json
import re
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
import test_ocor_dev_0051 as base
import test_ocor_dev_0052 as t52
import test_ocor_dev_0053 as t53
import yaml
from ocor_runtime.kernel.canonical import canonical_bytes, canonical_digest, format_utc_timestamp
from ocor_runtime.kernel.governed_context import GovernedContext
from ocor_runtime.memory.lifecycle import (
    FORGETTING_TRIGGERS,
    TRANSITIONS,
    ContentParticipant,
    InMemoryTombstoneStore,
    JournalTombstoneStore,
    LegalHoldStatus,
    LifecycleGuardPolicy,
    LifecycleReceipt,
    MemoryLifecycleCoordinator,
    MemoryLifecycleError,
    NativeProjectionParticipant,
    RepresentationParticipant,
    TombstoneEntry,
)
from ocor_runtime.memory.model import (
    PROBLEM_REASON_CODES,
    AdmissionLimits,
    AdmittedMemoryVersion,
    JournalMemoryVersionLedger,
    LifecycleStatus,
    MemoryAdmissionError,
    MemoryAdmissionService,
    MemoryPolicyDecision,
)
from ocor_runtime.memory.retrieval import MemoryRetrievalError, MemorySearchResponse, RetrievalMode
from ocor_runtime.memory.stores import MemoryPartition, VectorProfile, content_object_ref

REPO = Path(__file__).resolve().parents[3]
MODULE = REPO / "ocor-runtime/src/ocor_runtime/memory/lifecycle.py"
ADD = REPO / "ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md"
OPENAPI = yaml.safe_load(
    (REPO / "reports/contracts/ocor-governed-memory.openapi.yaml").read_text(encoding="utf-8")
)
NOW = base.NOW
S = LifecycleStatus
CALLER = t52.CALLER
OUTSIDER = t52.context(compartments=("charlie",))
HORIZON = timedelta(days=365)
TEXT = "border checkpoint traffic"
HOLD = "urn:ocor:legal-hold:case-2026-17"


# --------------------------------------------------------------------------
# Test ports (explicit fixtures, never a mock of the lifecycle boundary)
# --------------------------------------------------------------------------


@dataclass
class LifecycleGrant:
    """Live lifecycle policy double: explicit decisions, recorded calls."""

    permitted: bool = True
    bundle: str | None = None
    fail: bool = False
    calls: list[tuple[str, str, str]] = field(default_factory=list)

    def authorize_lifecycle(self, action: str, item: Any, target: LifecycleStatus, ctx: GovernedContext) -> MemoryPolicyDecision:
        self.calls.append((action, item.version_ref, target.value))
        if self.fail:
            raise ConnectionError("opa unavailable")
        return MemoryPolicyDecision(
            permitted=self.permitted,
            decision_ref=f"decision:lifecycle:{action}:{item.version_ref}:{target.value}",
            policy_bundle_digest=self.bundle or ctx.policy_bundle_digest,
        )


@dataclass
class HoldRegistry:
    """Legal hold authority double: holds by ref, recorded reads."""

    holds: dict[str, LegalHoldStatus] = field(default_factory=dict)
    fail: bool = False
    reads: list[str] = field(default_factory=list)

    def place(self, ref: str = HOLD, tenant: str = "tenant-a") -> None:
        self.holds[ref] = LegalHoldStatus(legal_hold_ref=ref, tenant_id=tenant, active=True)

    def lift(self, ref: str = HOLD) -> None:
        held = self.holds[ref]
        self.holds[ref] = LegalHoldStatus(legal_hold_ref=ref, tenant_id=held.tenant_id, active=False)

    def status(self, ref: str, ctx: GovernedContext) -> LegalHoldStatus | None:
        self.reads.append(ref)
        if self.fail:
            raise TimeoutError("legal hold registry unavailable")
        return self.holds.get(ref)


class FailingParticipant:
    """A cache/replica/export participant whose first purges fail (fault injection)."""

    name = "replica"

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.present: set[str] = set()
        self.purges = 0

    def track(self, record: AdmittedMemoryVersion) -> None:
        self.present.add(record.item.version_ref)

    def purge(self, target: Any) -> None:
        self.purges += 1
        if self.failures > 0:
            self.failures -= 1
            raise ConnectionError("replica unreachable")
        self.present -= set(target.version_refs)

    def residue(self, target: Any) -> tuple[str, ...]:
        return tuple(sorted(self.present & set(target.version_refs)))


class World(t53.World):
    """0053 world (real admission, embedding coordinator, retrieval) plus the lifecycle."""

    def __init__(self, *, tombstones: Any | None = None, replica: FailingParticipant | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.admission = MemoryAdmissionService(
            ledger=self.ledger,
            resolver=t52.Resolver(),
            policy=LifecycleGuardPolicy(base.Policy(), ledger=self.ledger),
            markings=self.markings,
            clock=self.clock,
            limits=AdmissionLimits(retention_horizons={"retention:standard": HORIZON, "retention:short": timedelta(days=30)}),
        )
        self.lc_policy = LifecycleGrant()
        self.holds = HoldRegistry()
        self.lc_audit = t52.Audit()
        self.lc_stop = t52.StopState()
        self.tombstones = tombstones if tombstones is not None else InMemoryTombstoneStore()
        self.replica = replica
        self.lifecycle = self.build_lifecycle()
        self._lc_ops = 0

    def participants(self) -> list[Any]:
        found: list[Any] = [
            NativeProjectionParticipant(self.lexical, self.vector),  # type: ignore[arg-type]
            RepresentationParticipant(self.coordinator, models=self.registry, representations=self.representations, index=self.parallel),  # type: ignore[arg-type]
            ContentParticipant(self.content, self.metadata),
        ]
        if self.replica is not None:
            found.append(self.replica)
        return found

    def build_lifecycle(self, **overrides: Any) -> MemoryLifecycleCoordinator:
        arguments: dict[str, Any] = {
            "ledger": self.ledger,
            "metadata": self.metadata,
            "store": self.coordinator,
            "lexical": self.lexical,
            "vector": self.vector,
            "policy": self.lc_policy,
            "markings": self.markings,
            "legal_holds": self.holds,
            "stop": self.lc_stop,
            "audit": self.lc_audit,
            "tombstones": self.tombstones,
            "clock": self.clock,
            "participants": self.participants(),
            "retention_horizons": {"retention:standard": HORIZON, "retention:short": timedelta(days=30)},
            "representations": (self.registry, self.representations),
        }
        arguments.update(overrides)
        return MemoryLifecycleCoordinator(**arguments)

    def deadline(self) -> str:
        return format_utc_timestamp(self.clock.now() + timedelta(seconds=30))

    def body(self, ctx: GovernedContext = CALLER, op: str | None = None, **fields: Any) -> dict[str, Any]:
        self._lc_ops += 1
        body: dict[str, Any] = {
            "operation_id": op or f"lc-{self._lc_ops}",
            "governed_context": ctx.to_mapping(),
            "governed_context_digest": ctx.digest(),
            "deadline": self.deadline(),
        }
        body.update(fields)
        return body

    def move(
        self,
        item_id: str,
        target: str,
        *,
        reason: str = "OPERATOR_DECISION",
        version: int | None = None,
        hold: str | None = None,
        ctx: GovernedContext = CALLER,
        op: str | None = None,
    ) -> LifecycleReceipt:
        if version is None:
            head = self.lifecycle.head(item_id)
            version = head.item.memory_version if head is not None else 1
        fields: dict[str, Any] = {"memory_version": version, "target_status": target, "reason_code": reason}
        if hold is not None:
            fields["legal_hold_ref"] = hold
        return self.lifecycle.transition(item_id, self.body(ctx, op, **fields), binding=t52.binding(ctx))

    def delete(
        self,
        item_id: str,
        *,
        reason: str = "AUTHORIZED_REQUEST",
        scope: str = "ALL_VERSIONS",
        ctx: GovernedContext = CALLER,
        op: str | None = None,
    ) -> LifecycleReceipt:
        body = self.body(ctx, op, reason_code=reason, deletion_scope=scope)
        return self.lifecycle.request_deletion(item_id, body, binding=t52.binding(ctx))

    def status(self, item_id: str) -> str:
        head = self.lifecycle.head(item_id)
        assert head is not None
        return head.item.lifecycle_status.value

    def search(self, mode: RetrievalMode, text: str = TEXT, *, ctx: GovernedContext = CALLER, **extra: Any) -> MemorySearchResponse:
        body = t52.request(mode, text=text, ctx=ctx, deadline=self.deadline(), **extra)
        return self.service().search(body, binding=t52.binding(ctx))

    def every_mode(self, text: str = TEXT, *, v2: bool = False) -> dict[str, list[str]]:
        found = {mode.value: t52.refs(self.search(mode, text)) for mode in RetrievalMode}
        if v2:  # the parallel representation of the partition, once rebuilt
            found["VECTOR_V2"] = t52.refs(self.search_v2(text))
        return found


def unit_world(**kwargs: Any) -> World:
    return World(
        metadata=base.MemMetadata(),
        content=base.MemContent(),
        lexical=base.MemIndex(),
        vector=base.MemIndex(),
        cipher=base.FixtureCipher(),
        representations=t53.MemRepresentations(),
        parallel=base.MemIndex(),
        **kwargs,
    )


def assert_error(action: Any, reason: str, detail: str) -> MemoryAdmissionError:
    with pytest.raises(MemoryAdmissionError) as caught:
        action()
    assert (caught.value.reason_code, caught.value.detail_code) == (reason, detail), caught.value
    assert caught.value.reason_code in PROBLEM_REASON_CODES
    return caught.value


def denials(world: World) -> list[tuple[str, str]]:
    return [
        (str(event["reason_code"]), str(event["detail_code"]))
        for event in world.lc_audit.events
        if event.get("outcome") == "DENIED"
    ]


def ledger_snapshot(world: World) -> list[str]:
    return [record.item_digest for record in world.ledger.records()]


def native_entries(world: World, record: AdmittedMemoryVersion) -> dict[str, int]:
    """Native lexical and vector entries of every version of the record's item."""

    item = record.item
    partition = MemoryPartition.for_item(item)
    lexical = world.coordinator._limits.lexical_profile.representation_version
    vector = VectorProfile.for_item(item).representation_version
    prefix = f"urn:ocor:memory:{item.memory_item_id}:v"
    count = {"lexical": 0, "vector": 0}
    for name, index, version in (("lexical", world.lexical, lexical), ("vector", world.vector, vector)):
        for hit in index.inner.entries(partition, version):
            if str(hit.payload.get("memory_version_ref", "")).startswith(prefix):
                count[name] += 1
    return count


def parallel_descriptors(world: World, record: AdmittedMemoryVersion) -> list[str]:
    partition = MemoryPartition.for_item(record.item)
    prefix = f"urn:ocor:memory:{record.item.memory_item_id}:v"
    return [
        d.memory_version_ref
        for d in world.representations.descriptors(partition.digest, t53.PIN_V2.representation_version)
        if d.memory_version_ref.startswith(prefix)
    ]


def content_present(world: World, record: AdmittedMemoryVersion) -> bool:
    partition = MemoryPartition.for_item(record.item)
    return world.content.get(content_object_ref(partition, record.item.content_digest)) is not None


def no_content_in(events: Sequence[Mapping[str, object]], *texts: str) -> bool:
    blob = json.dumps(list(events), sort_keys=True, default=str)
    return not any(text in blob for text in texts)


# --------------------------------------------------------------------------
# Unit branch logic (0051 in-memory fixtures; not qualifying evidence)
# --------------------------------------------------------------------------


def _add_fsm() -> dict[str, set[str]]:
    """Parse the lifecycle FSM block of ADD v1.3 Part II §2.10 (the normative text)."""

    text = ADD.read_text(encoding="utf-8")
    section = text[text.index("### 2.10 Lifecycle, forgetting and deletion") :]
    block = section[section.index("```text") + len("```text") : section.index("```", section.index("```text") + 7)]
    fsm: dict[str, set[str]] = {status.value: set() for status in LifecycleStatus}
    for line in block.strip().splitlines():
        left, right = (part.strip() for part in line.split("→"))
        targets = {t.strip() for t in right.split("|")}
        for source in (s.strip() for s in left.split("|")):
            fsm[source] |= targets
    return fsm


def test_the_fsm_is_exactly_the_one_of_add_part_ii_section_2_10() -> None:
    fsm = _add_fsm()
    assert fsm["LEGAL_HOLD"] == {"prior logical disposition", "DELETION_PENDING"}
    declared = {source.value: {t.value for t in targets} for source, targets in TRANSITIONS.items()}
    priors = {"ACTIVE", "SUPERSEDED", "REVOKED", "EXPIRED"}  # the statuses that can enter LEGAL_HOLD
    assert {source for source, targets in fsm.items() if "LEGAL_HOLD" in targets} == priors
    expected = dict(fsm, LEGAL_HOLD=priors | {"DELETION_PENDING"})
    assert declared == expected
    assert declared["DELETED"] == set()


def test_forgetting_triggers_and_reason_codes_are_the_declared_vocabulary() -> None:
    assert FORGETTING_TRIGGERS == {
        "EXPIRY", "PURPOSE_COMPLETION", "REVOCATION", "SUPERSESSION", "CONFIDENCE_DECAY",
        "QUOTA_PRESSURE", "AUTHORIZED_REQUEST", "RETENTION_ELAPSED",
    }
    schemas = OPENAPI["components"]["schemas"]
    lifecycle = schemas["MemoryLifecycleRequest"]["allOf"][1]
    deletion = schemas["MemoryDeletionRequest"]["allOf"][1]
    assert set(lifecycle["required"]) == {"memory_version", "target_status", "reason_code"}
    assert set(lifecycle["properties"]) == {"memory_version", "target_status", "reason_code", "legal_hold_ref"}
    assert set(deletion["properties"]["deletion_scope"]["enum"]) == {"LATEST_VERSION", "ALL_VERSIONS", "PROJECT_SCOPE", "PRINCIPAL_SCOPE"}
    for reason in ("LIFECYCLE_TRANSITION_INVALID", "LEGAL_HOLD_ACTIVE", "DELETION_INCOMPLETE"):
        assert reason in schemas["Problem"]["properties"]["reason_code"]["enum"]


def _move_body(world: World, **changes: Any) -> dict[str, Any]:
    body = world.body(memory_version=1, target_status="REVOKED", reason_code="OPERATOR_DECISION")
    for name, value in changes.items():
        if value is _DROP:
            body.pop(name)
        else:
            body[name] = value
    return body


_DROP = object()
INVALID_TRANSITIONS = [
    ("extra field", {"comment": "free text"}, "MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID"),
    ("missing reason", {"reason_code": _DROP}, "MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID"),
    ("bool version", {"memory_version": True}, "MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID"),
    ("zero version", {"memory_version": 0}, "MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID"),
    ("unknown status", {"target_status": "ARCHIVED"}, "MEMORY_SCHEMA_INVALID", "TARGET_STATUS_INVALID"),
    ("free text reason", {"reason_code": "revoked because the source lied"}, "MEMORY_SCHEMA_INVALID", "REASON_CODE_INVALID"),
    ("past deadline", {"deadline": format_utc_timestamp(NOW - timedelta(seconds=1))}, "POLICY_DENIED", "DEADLINE_EXCEEDED"),
    ("bad deadline", {"deadline": "tomorrow"}, "MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID"),
    ("gcs not object", {"governed_context": "ctx"}, "GOVERNED_CONTEXT_MISMATCH", "GCS_INVALID"),
    ("gcs digest", {"governed_context_digest": base.d("other")}, "GOVERNED_CONTEXT_MISMATCH", "GOVERNED_CONTEXT_MISMATCH"),
    ("hold ref without hold", {"legal_hold_ref": HOLD}, "MEMORY_SCHEMA_INVALID", "LEGAL_HOLD_REF_UNEXPECTED"),
    ("deleted target", {"target_status": "DELETED"}, "LIFECYCLE_TRANSITION_INVALID", "SAGA_OWNED_STATUS"),
    ("incomplete target", {"target_status": "DELETION_INCOMPLETE"}, "LIFECYCLE_TRANSITION_INVALID", "SAGA_OWNED_STATUS"),
    ("forgetting without trigger", {"target_status": "DELETION_PENDING"}, "MEMORY_SCHEMA_INVALID", "FORGETTING_TRIGGER_INVALID"),
    ("stale version", {"memory_version": 2}, "LIFECYCLE_TRANSITION_INVALID", "STALE_VERSION"),
    ("undeclared edge", {"target_status": "QUARANTINED"}, "LIFECYCLE_TRANSITION_INVALID", "TRANSITION_NOT_DECLARED"),
    ("hold without ref", {"target_status": "LEGAL_HOLD"}, "MEMORY_SCHEMA_INVALID", "LEGAL_HOLD_REF_MISSING"),
]


@pytest.mark.parametrize(("label", "changes", "reason", "detail"), INVALID_TRANSITIONS, ids=[c[0] for c in INVALID_TRANSITIONS])
def test_invalid_transition_requests_change_nothing_and_are_audited(label: str, changes: dict[str, Any], reason: str, detail: str) -> None:
    world = unit_world()
    world.admit("item", TEXT)
    before = ledger_snapshot(world)
    body = _move_body(world, **changes)
    assert_error(lambda: world.lifecycle.transition("item", body, binding=t52.binding()), reason, detail)
    assert ledger_snapshot(world) == before and world.status("item") == "ACTIVE"
    assert denials(world) == [(reason, detail)]
    assert world.lc_audit.events[-1]["action"] == "transitionMemoryLifecycle.denied"


def test_a_valid_transition_request_of_the_closed_envelope_is_accepted() -> None:
    world = unit_world()
    world.admit("item", TEXT)
    receipt = world.lifecycle.transition("item", _move_body(world), binding=t52.binding())
    assert set(receipt.to_mapping()) == set(OPENAPI["components"]["schemas"]["OperationReceipt"]["required"])
    assert receipt.to_mapping()["status"] == "COMPLETED" and receipt.lifecycle_status == "REVOKED"


def test_missing_binding_unknown_and_invisible_items_are_refused_alike() -> None:
    world = unit_world()
    world.admit("item", TEXT)
    assert_error(lambda: world.lifecycle.transition("item", _move_body(world), binding=None), "AUTHENTICATION_REQUIRED", "BINDING_MISSING")
    unknown = assert_error(lambda: world.move("ghost", "REVOKED"), "MEMORY_NOT_FOUND", "ITEM_NOT_VISIBLE")
    hidden = assert_error(lambda: world.move("item", "REVOKED", ctx=OUTSIDER), "MEMORY_NOT_FOUND", "ITEM_NOT_VISIBLE")
    assert str(unknown) == str(hidden)
    assert world.status("item") == "ACTIVE"
    for foreign in (
        t52.context(compartments=("alpha", "bravo"), tenant="tenant-b"),
        t52.context(compartments=("alpha", "bravo"), organization="org-b"),
        t52.context(compartments=("alpha", "bravo"), domain="domain-intel"),
    ):
        assert_error(lambda: world.move("item", "REVOKED", ctx=foreign), "MEMORY_NOT_FOUND", "ITEM_NOT_VISIBLE")
    other_purpose = t52.context(compartments=("alpha", "bravo"), purpose="logistics")
    assert_error(lambda: world.move("item", "REVOKED", ctx=other_purpose), "MEMORY_NOT_FOUND", "ITEM_NOT_VISIBLE")
    secret_item = t52.context(marking=t52.M_SECRET)
    world.admit("secret", TEXT, ctx=secret_item)
    assert_error(lambda: world.move("secret", "REVOKED"), "MEMORY_NOT_FOUND", "ITEM_NOT_VISIBLE")


INVALID_DELETIONS = [
    ("extra field", {"memory_version": 1}, "MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID"),
    ("missing scope", {"deletion_scope": _DROP}, "MEMORY_SCHEMA_INVALID", "ENVELOPE_INVALID"),
    ("undeclared scope", {"deletion_scope": "EVERYTHING"}, "MEMORY_SCHEMA_INVALID", "DELETION_SCOPE_INVALID"),
    ("not a trigger", {"reason_code": "BECAUSE"}, "MEMORY_SCHEMA_INVALID", "FORGETTING_TRIGGER_INVALID"),
    ("latest only", {"deletion_scope": "LATEST_VERSION"}, "UNSUPPORTED_CAPABILITY", "DELETION_SCOPE_UNSUPPORTED"),
    ("project scope", {"deletion_scope": "PROJECT_SCOPE"}, "UNSUPPORTED_CAPABILITY", "DELETION_SCOPE_UNSUPPORTED"),
    ("principal scope", {"deletion_scope": "PRINCIPAL_SCOPE"}, "UNSUPPORTED_CAPABILITY", "DELETION_SCOPE_UNSUPPORTED"),
]


@pytest.mark.parametrize(("label", "changes", "reason", "detail"), INVALID_DELETIONS, ids=[c[0] for c in INVALID_DELETIONS])
def test_invalid_deletion_requests_change_nothing_and_are_audited(label: str, changes: dict[str, Any], reason: str, detail: str) -> None:
    world = unit_world()
    record = world.admit("item", TEXT)
    body = world.body(reason_code="AUTHORIZED_REQUEST", deletion_scope="ALL_VERSIONS")
    for name, value in changes.items():
        if value is _DROP:
            body.pop(name)
        else:
            body[name] = value
    before = ledger_snapshot(world)
    assert_error(lambda: world.lifecycle.request_deletion("item", body, binding=t52.binding()), reason, detail)
    assert ledger_snapshot(world) == before and content_present(world, record)
    assert world.tombstones.latest_epoch() == 0
    assert denials(world) == [(reason, detail)]


def test_policy_denial_stale_bundle_and_outage_fail_closed_before_any_write() -> None:
    world = unit_world()
    world.admit("item", TEXT)
    before = ledger_snapshot(world)
    world.lc_policy.permitted = False
    assert_error(lambda: world.move("item", "REVOKED"), "POLICY_DENIED", "LIFECYCLE_DENIED")
    world.lc_policy.permitted, world.lc_policy.bundle = True, base.d("old-bundle")
    assert_error(lambda: world.move("item", "REVOKED"), "STALE_POLICY", "POLICY_BUNDLE_MISMATCH")
    world.lc_policy.bundle, world.lc_policy.fail = None, True
    assert_error(lambda: world.move("item", "REVOKED"), "CONTROL_PLANE_UNAVAILABLE", "POLICY_UNAVAILABLE")
    assert_error(lambda: world.delete("item"), "CONTROL_PLANE_UNAVAILABLE", "POLICY_UNAVAILABLE")
    assert ledger_snapshot(world) == before and world.tombstones.latest_epoch() == 0
    world.lc_policy.fail = False
    assert world.move("item", "REVOKED").lifecycle_status == "REVOKED"


def test_an_unaudited_denial_and_an_unaudited_transition_fail_closed() -> None:
    world = unit_world()
    world.admit("item", TEXT)
    world.lc_audit.fail = True
    assert_error(lambda: world.move("item", "QUARANTINED"), "CONTROL_PLANE_UNAVAILABLE", "AUDIT_UNAVAILABLE")
    assert_error(lambda: world.move("item", "REVOKED", op="op-audit"), "CONTROL_PLANE_UNAVAILABLE", "AUDIT_UNAVAILABLE")
    # The exclusion is durable (fail closed); the replay writes the audit event and the receipt.
    assert world.status("item") == "REVOKED"
    world.lc_audit.fail = False
    receipt = world.move("item", "REVOKED", version=1, op="op-audit")
    assert receipt.lifecycle_status == "REVOKED" and world.lc_audit.events[-1]["to_status"] == "REVOKED"


def test_the_admission_guard_refuses_a_new_version_on_an_excluded_head() -> None:
    world = unit_world()
    record = world.admit("item", TEXT)
    world.move("item", "REVOKED")
    with pytest.raises(MemoryAdmissionError) as caught:
        world.admit("item", TEXT + " corrected", version=3)
    assert caught.value.reason_code == "POLICY_DENIED"
    assert world.status("item") == "REVOKED" and world.ledger.latest_version("item") == 2
    # An ACTIVE head still accepts a new version through the same guard.
    world.admit("other", TEXT)
    assert world.admit("other", TEXT + " corrected", version=2).item.memory_version == 2
    assert record.item.lifecycle_status is S.ACTIVE


def test_tombstone_entries_are_closed_canonical_records() -> None:
    entry = TombstoneEntry(
        memory_item_id="item", tenant_id="tenant-a", partition_digests=(base.d("p"),),
        version_refs=("urn:ocor:memory:item:v1",), deletion_epoch=1, phase="COMPLETED",
        reason_code="AUTHORIZED_REQUEST", operation_id="op", participants=("content",),
        residue_counts=(), retained_shared_objects=0, at=format_utc_timestamp(NOW),
    )
    assert TombstoneEntry.from_mapping(entry.to_mapping()) == entry
    assert entry.digest == canonical_digest(entry.to_mapping())
    for mutate in (
        lambda m: m.update(content_digest=base.d("x")),
        lambda m: m.pop("reason_code"),
        lambda m: m.update(deletion_epoch=0),
        lambda m: m.update(deletion_epoch=True),
        lambda m: m.update(phase="DONE"),
        lambda m: m.update(retained_shared_objects=-1),
        lambda m: m.update(residue_counts=[["content", 0]]),
    ):
        mapping = entry.to_mapping()
        mutate(mapping)
        with pytest.raises(MemoryLifecycleError):
            TombstoneEntry.from_mapping(mapping)


def _entry(item: str, epoch: int, phase: str) -> TombstoneEntry:
    return TombstoneEntry(
        memory_item_id=item, tenant_id="tenant-a", partition_digests=(base.d("p"),),
        version_refs=(f"urn:ocor:memory:{item}:v1",), deletion_epoch=epoch, phase=phase,
        reason_code="AUTHORIZED_REQUEST", operation_id=f"op-{item}", participants=("content",),
        residue_counts=(), retained_shared_objects=0, at=format_utc_timestamp(NOW),
    )


def test_deletion_epochs_are_reserved_in_order_and_completion_is_terminal(tmp_path: Path) -> None:
    for store in (InMemoryTombstoneStore(), JournalTombstoneStore(tmp_path / "t.jsonl")):
        store.append(_entry("a", 1, "STARTED"))
        assert store.latest_epoch() == 1
        with pytest.raises(MemoryLifecycleError):
            store.append(_entry("b", 1, "STARTED"))  # epoch already reserved
        with pytest.raises(MemoryLifecycleError):
            store.append(_entry("b", 3, "STARTED"))  # gap
        with pytest.raises(MemoryLifecycleError):
            store.append(_entry("b", 2, "COMPLETED"))  # outcome without its saga
        store.append(_entry("a", 1, "INCOMPLETE"))
        store.append(_entry("a", 1, "STARTED"))  # governed retry under the same epoch
        store.append(_entry("a", 1, "COMPLETED"))
        with pytest.raises(MemoryLifecycleError):
            store.append(_entry("a", 1, "STARTED"))  # DELETED is terminal
        store.append(_entry("b", 2, "STARTED"))
        assert [e.phase for e in store.entries("a")] == ["STARTED", "INCOMPLETE", "STARTED", "COMPLETED"]


def test_the_tombstone_journal_survives_reopen_and_detects_tampering(tmp_path: Path) -> None:
    path = tmp_path / "tombstones.jsonl"
    journal = JournalTombstoneStore(path)
    journal.append(_entry("a", 1, "STARTED"))
    journal.append(_entry("a", 1, "COMPLETED"))
    reopened = JournalTombstoneStore(path)
    assert reopened.latest_epoch() == 1 and reopened.head == journal.head
    assert [e.phase for e in reopened.entries("a")] == ["STARTED", "COMPLETED"]
    lines = path.read_bytes().splitlines(keepends=True)
    for tampered in (
        lines[1:],  # removal
        [lines[1], lines[0]],  # reordering
        [lines[0], lines[1].replace(b"COMPLETED", b"STARTED\x22")],  # rewrite
        [lines[0], lines[1][:-5]],  # torn write
        [lines[0], lines[1].rstrip(b"\n")],  # complete entry, unacknowledged (no newline)
    ):
        broken = tmp_path / f"broken-{uuid.uuid4().hex}.jsonl"
        broken.write_bytes(b"".join(tampered))
        with pytest.raises(MemoryLifecycleError):
            JournalTombstoneStore(broken)
    # A self-consistent entry chained to the wrong predecessor is refused by the chain alone.
    relinked = json.loads(lines[1])
    body = {"seq": relinked["seq"], "prev": "urn:sha256:" + "1" * 64, "entry": relinked["entry"]}
    broken = tmp_path / "relinked.jsonl"
    broken.write_bytes(lines[0] + canonical_bytes(dict(body, entry_digest=canonical_digest(body))) + b"\n")
    with pytest.raises(MemoryLifecycleError):
        JournalTombstoneStore(broken)
    chained = json.loads(lines[1])
    chained["entry"]["reason_code"] = "QUOTA_PRESSURE"
    broken = tmp_path / "rewritten.jsonl"
    broken.write_bytes(lines[0] + canonical_bytes(chained) + b"\n")
    with pytest.raises(MemoryLifecycleError):
        JournalTombstoneStore(broken)


def test_participants_must_be_named_uniquely() -> None:
    world = unit_world()
    with pytest.raises(ValueError):
        world.build_lifecycle(participants=[])
    with pytest.raises(ValueError):
        world.build_lifecycle(participants=[ContentParticipant(world.content, world.metadata)] * 2)


def test_metrics_use_a_bounded_label_set() -> None:
    world = unit_world()
    world.admit("item", TEXT)
    world.move("item", "REVOKED", op="op-1")
    world.move("item", "REVOKED", version=1, op="op-1")
    assert_error(lambda: world.move("item", "ACTIVE"), "LIFECYCLE_TRANSITION_INVALID", "TRANSITION_NOT_DECLARED")
    world.delete("item")
    for (operation, outcome, reason) in world.lifecycle.metrics:
        assert operation in {"transitionMemoryLifecycle", "requestMemoryDeletion", "enforceMemoryExpiry", "enforceMemoryRetention", "deletionParticipant"}
        assert outcome in {"COMPLETED", "REPLAYED", "DENIED", "INCOMPLETE"}
        assert reason == "NONE" or reason in PROBLEM_REASON_CODES or reason in {"content", "native-projections", "embedding-representations", "replica"}


def test_the_module_has_no_canonical_authority_or_backend_client() -> None:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported = {
        (node.module or "") if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    for forbidden in ("psycopg", "requests", "httpx", "urllib", "qdrant_client", "hvac", "socket"):
        assert not any(name.split(".")[0] == forbidden for name in imported), forbidden
    source = MODULE.read_text(encoding="utf-8")
    for authority in ("CapabilityLease(", "Approval(", "GovernedCanonicalCommitCommand", "ActionCommand("):
        assert authority not in source


# --------------------------------------------------------------------------
# Qualifying worlds on the real backends of OCOR-DEV-0051/0053
# --------------------------------------------------------------------------


class OpenBaoHarness(base.OpenBaoHarness):
    PREFIX = "ocor-test-0055-openbao-"


@dataclass
class Backends:
    dsn: str
    qdrant: Any
    bao: OpenBaoHarness
    schemas: list[str] = field(default_factory=list)

    def release(self) -> None:
        """Drop every schema and Qdrant collection created by the current test."""

        try:
            with psycopg.connect(self.dsn, autocommit=True) as conn:
                for schema in self.schemas:
                    conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        finally:
            for schema in self.schemas:
                index = t52.CompactQdrantVectorIndex(self.qdrant.endpoint, schema)
                for name in index.collections():
                    status, _ = index._call("DELETE", f"/collections/{name}")
                    assert status == 200, (name, status)
            self.schemas.clear()

    def world(self, *, schema: str | None = None, **kwargs: Any) -> World:
        if schema is None:
            schema = f"ocor_t0055_{uuid.uuid4().hex[:12]}"
            self.schemas.append(schema)
        postgres = base.PostgresStores(self.dsn, schema)
        return World(
            metadata=postgres,
            content=base.PostgresContentStore(postgres),
            lexical=base.PostgresLexicalIndex(postgres),
            vector=t52.CompactQdrantVectorIndex(self.qdrant.endpoint, schema),
            cipher=base.OpenBaoTransitCipher(self.bao),
            representations=t53.PostgresRepresentationStore(self.dsn, schema),
            parallel=t52.CompactQdrantVectorIndex(self.qdrant.endpoint, schema),
            **kwargs,
        )


@pytest.fixture(scope="module")
def live_backends() -> Iterator[Backends]:
    import os

    dsn = os.environ.get("OCOR_LIVE_POSTGRES_DSN")
    if not dsn:
        pytest.fail("OCOR_LIVE_POSTGRES_DSN is mandatory qualifying evidence (real PostgreSQL)")
    qdrant = base.QdrantHarness.provision()
    bao: OpenBaoHarness | None = None
    state: Backends | None = None
    try:
        bao = OpenBaoHarness.provision()
        state = Backends(dsn=dsn, qdrant=qdrant, bao=bao)
        yield state
    finally:
        try:
            if state is not None:
                state.release()
        finally:
            try:
                if bao is not None:
                    bao.destroy()
            finally:
                qdrant.destroy()


@pytest.fixture
def backends(live_backends: Backends) -> Iterator[Backends]:
    try:
        yield live_backends
    finally:
        live_backends.release()


def test_qualifying_backends_are_real_and_pinned(backends: Backends) -> None:
    assert base.QDRANT_IMAGE.endswith(base.LOCKED_IMAGES["qdrant"].split("@", 1)[1])
    assert base._docker("inspect", backends.qdrant.container, "--format", "{{.Config.Image}}") == base.QDRANT_IMAGE
    assert base._docker("inspect", backends.bao.container, "--format", "{{.Config.Image}}") == base.LOCKED_IMAGES["openbao"]
    with psycopg.connect(backends.dsn) as conn:
        row = conn.execute("SHOW server_version").fetchone()
    assert row is not None and str(row[0]).startswith("16.")
    world = backends.world()
    assert isinstance(world.vector.inner, base.QdrantVectorIndex) and isinstance(world.parallel.inner, base.QdrantVectorIndex)
    assert isinstance(world.metadata, base.PostgresStores) and isinstance(world.representations, t53.PostgresRepresentationStore)
    assert isinstance(world.cipher, base.OpenBaoTransitCipher)


def populate(world: World) -> dict[str, AdmittedMemoryVersion]:
    return {name: world.admit(name, TEXT + suffix) for name, suffix in (("keep", ""), ("x", " north"), ("y", " south"))}


def test_revocation_is_a_new_immutable_version_that_leaves_every_output(backends: Backends) -> None:
    world = backends.world()
    items = populate(world)
    world.rebuild(items["keep"])  # a parallel v2 representation of the partition
    before = world.every_mode(v2=True)
    assert all("urn:ocor:memory:x:v1" in refs for refs in before.values()), before
    assert parallel_descriptors(world, items["x"]) == ["urn:ocor:memory:x:v1"]
    original = world.ledger.get("x", 1)
    receipt = world.move("x", "REVOKED", reason="SOURCE_RETRACTED")
    assert receipt.memory_version_ref == "urn:ocor:memory:x:v2" and receipt.lifecycle_status == "REVOKED"
    head = world.lifecycle.head("x")
    assert head is not None and head.item.supersedes_ref == "urn:ocor:memory:x:v1"
    assert head.item.content_digest == items["x"].item.content_digest  # content unchanged
    assert world.ledger.get("x", 1) == original and original.item.lifecycle_status is S.ACTIVE  # v1 immutable
    after = world.every_mode(v2=True)
    for mode, refs in after.items():
        assert not any(ref.startswith("urn:ocor:memory:x:") for ref in refs), mode
        assert refs == [r for r in before[mode] if not r.startswith("urn:ocor:memory:x:")], mode
    # The parallel representation is invalidated by the same transition.
    assert parallel_descriptors(world, items["x"]) == []
    # The audit record carries codes, refs and digests only, never content.
    event = world.lc_audit.events[-1]
    assert event["to_status"] == "REVOKED" and event["reason_code"] == "SOURCE_RETRACTED"
    assert receipt.to_mapping()["audit_ref"] == canonical_digest(event)
    assert no_content_in(world.lc_audit.events, TEXT)
    # Not re-openable: REVOKED -> ACTIVE is not a lifecycle transition, and admission is guarded.
    assert_error(lambda: world.move("x", "ACTIVE"), "LIFECYCLE_TRANSITION_INVALID", "TRANSITION_NOT_DECLARED")
    with pytest.raises(MemoryAdmissionError):
        world.admit("x", TEXT + " north", version=3)
    assert world.every_mode(v2=True) == after


def test_excluded_items_do_not_influence_rank_scores_counts_or_explanations(backends: Backends) -> None:
    excluded = backends.world()
    reference = backends.world()
    names = [f"n{i}" for i in range(6)]
    for world in (excluded, reference):
        for i, name in enumerate(names):
            world.admit(name, f"{TEXT} report {i}")
    for name in ("hold", "revoke", "quarantine", "forget"):
        excluded.admit(name, f"{TEXT} {TEXT} {TEXT}")  # the strongest lexical and vector matches
    excluded.holds.place()
    excluded.move("hold", "LEGAL_HOLD", hold=HOLD)
    excluded.move("revoke", "REVOKED")
    excluded.move("quarantine", "SUPERSEDED")
    excluded.delete("forget")
    for mode in RetrievalMode:
        got = excluded.search(mode, top_k=5)
        want = reference.search(mode, top_k=5)
        assert t52.refs(got) == t52.refs(want), mode
        assert [h.final_score for h in got.hits] == [h.final_score for h in want.hits], mode
        assert [h.score_factors for h in got.hits] == [h.score_factors for h in want.hits], mode
        assert len(got.explanations) == len(want.explanations)
    # In-query exclusion: the raw index answer never carries an excluded entry.
    calls = [c for c in excluded.lexical.calls + excluded.vector.calls if c[0] == "search_eligible"]
    assert calls
    partition = MemoryPartition.for_item(excluded.ledger.get("n0", 1).item)  # type: ignore[union-attr]
    lexical_version = excluded.coordinator._limits.lexical_profile.representation_version
    hits = excluded.lexical.inner.search_eligible(
        partition, lexical_version, TEXT,
        where=_predicate(excluded), limit=50, offset=0,
    )
    assert {str(h.payload["memory_version_ref"]).split(":")[3] for h in hits} == set(names)


def _predicate(world: World) -> Any:
    from ocor_runtime.memory.stores import EligibilityPredicate

    return EligibilityPredicate(
        memory_kinds=frozenset({"EPISODIC"}), memory_scopes=frozenset({"PROJECT"}),
        valid_at=world.clock.now(), now=world.clock.now(),
    )


def test_expiry_is_deterministic_bounded_and_never_reopens(backends: Backends) -> None:
    world = backends.world()
    world.admit("late", TEXT + " late", expires_at=NOW + timedelta(hours=3))
    world.admit("early", TEXT + " early", expires_at=NOW + timedelta(hours=1))
    world.admit("mid", TEXT + " mid", expires_at=NOW + timedelta(hours=2))
    world.admit("future", TEXT + " future", expires_at=NOW + timedelta(days=30))
    world.admit("forever", TEXT + " forever")
    world.admit("gone", TEXT + " gone", expires_at=NOW + timedelta(minutes=30))
    world.move("gone", "REVOKED")
    world.clock.advance(timedelta(hours=4))
    # Retrieval already excludes elapsed items on the boundary clock.
    assert sorted(r.split(":")[3] for r in t52.refs(world.search(RetrievalMode.FULL_TEXT))) == ["forever", "future"]
    first = world.lifecycle.enforce_expiry(binding=t52.binding(), operation_id="expiry-1", limit=1)
    assert first.processed == ("urn:ocor:memory:early:v2",)
    assert first.deferred == ("urn:ocor:memory:mid:v1", "urn:ocor:memory:late:v1")
    assert world.status("gone") == "REVOKED" and world.ledger.latest_version("gone") == 2
    assert first.unresolved == () and first.held == ()  # a non-ACTIVE head is never an expiry candidate
    second = world.lifecycle.enforce_expiry(binding=t52.binding(), operation_id="expiry-2")
    assert second.processed == ("urn:ocor:memory:mid:v2", "urn:ocor:memory:late:v2") and not second.deferred
    replay = world.lifecycle.enforce_expiry(binding=t52.binding(), operation_id="expiry-2")
    assert replay.processed == () and world.ledger.latest_version("mid") == 2
    assert {n: world.status(n) for n in ("early", "mid", "late", "future", "forever")} == {
        "early": "EXPIRED", "mid": "EXPIRED", "late": "EXPIRED", "future": "ACTIVE", "forever": "ACTIVE"
    }
    sweep_event = world.lc_audit.events[-1]
    assert sweep_event["action"] == "enforceMemoryExpiry" and sweep_event["processed"] == []
    assert replay.audit_ref == canonical_digest(sweep_event)
    assert_error(lambda: world.move("early", "ACTIVE"), "LIFECYCLE_TRANSITION_INVALID", "TRANSITION_NOT_DECLARED")
    assert sorted(r.split(":")[3] for r in t52.refs(world.search(RetrievalMode.FULL_TEXT))) == ["forever", "future"]
    # The same sweep on a second world selects in exactly the same order.
    twin = backends.world()
    for name, hours in (("late", 3), ("early", 1), ("mid", 2)):
        twin.admit(name, TEXT + " " + name, expires_at=NOW + timedelta(hours=hours))
    twin.clock.advance(timedelta(hours=4))
    assert twin.lifecycle.enforce_expiry(binding=t52.binding(), operation_id="e").processed == first.processed + second.processed


def test_legal_hold_blocks_deletion_and_release_restores_the_prior_disposition(backends: Backends) -> None:
    world = backends.world()
    items = populate(world)
    world.holds.place()
    world.move("x", "LEGAL_HOLD", hold=HOLD, reason="LITIGATION_HOLD")
    head = world.lifecycle.head("x")
    assert head is not None and head.item.legal_hold_ref == HOLD and head.item.prior_lifecycle_status is S.ACTIVE
    assert all(not any(r.startswith("urn:ocor:memory:x:") for r in refs) for refs in world.every_mode().values())
    snapshot = (ledger_snapshot(world), native_entries(world, items["x"]), world.tombstones.latest_epoch())
    # Held content cannot be deleted: request, forgetting transition and retention all refused.
    assert_error(lambda: world.delete("x"), "LEGAL_HOLD_ACTIVE", "LEGAL_HOLD_NOT_RELEASED")
    assert_error(lambda: world.move("x", "DELETION_PENDING", reason="AUTHORIZED_REQUEST"), "LEGAL_HOLD_ACTIVE", "LEGAL_HOLD_NOT_RELEASED")
    world.clock.advance(HORIZON + timedelta(days=1))
    report = world.lifecycle.enforce_retention(binding=t52.binding(), operation_id="retention-1")
    assert report.held == ("urn:ocor:memory:x:v2",) and "urn:ocor:memory:x:v2" not in report.processed
    assert content_present(world, items["x"]) and native_entries(world, items["x"]) == snapshot[1]
    assert world.status("x") == "LEGAL_HOLD" and world.status("keep") == "DELETED"
    # Leaving the hold needs the registry to report it released, then only to the prior disposition.
    assert_error(lambda: world.move("x", "ACTIVE"), "LEGAL_HOLD_ACTIVE", "LEGAL_HOLD_NOT_RELEASED")
    world.holds.fail = True
    assert_error(lambda: world.move("x", "ACTIVE"), "CONTROL_PLANE_UNAVAILABLE", "LEGAL_HOLD_REGISTRY_UNAVAILABLE")
    world.holds.fail = False
    world.holds.lift()
    assert_error(lambda: world.move("x", "REVOKED"), "LIFECYCLE_TRANSITION_INVALID", "PRIOR_DISPOSITION_REQUIRED")
    released = world.move("x", "ACTIVE", reason="HOLD_RELEASED")
    assert released.lifecycle_status == "ACTIVE"
    restored = world.lifecycle.head("x")
    assert restored is not None and restored.item.legal_hold_ref is None and restored.item.prior_lifecycle_status is None
    assert "urn:ocor:memory:x:v3" in world.every_mode()["FULL_TEXT"]


def test_a_hold_on_an_excluded_item_restores_that_exclusion(backends: Backends) -> None:
    world = backends.world()
    world.admit("x", TEXT)
    world.move("x", "REVOKED")
    world.holds.place()
    world.move("x", "LEGAL_HOLD", hold=HOLD)
    world.holds.lift()
    assert_error(lambda: world.move("x", "ACTIVE"), "LIFECYCLE_TRANSITION_INVALID", "PRIOR_DISPOSITION_REQUIRED")
    world.move("x", "REVOKED", reason="HOLD_RELEASED")
    assert world.status("x") == "REVOKED"
    assert all(not refs for refs in world.every_mode().values())
    # A released hold also allows forgetting straight from LEGAL_HOLD.
    world.holds.place("urn:ocor:legal-hold:case-2")
    world.move("x", "LEGAL_HOLD", hold="urn:ocor:legal-hold:case-2")
    world.holds.lift("urn:ocor:legal-hold:case-2")
    assert world.delete("x").lifecycle_status == "DELETED"


@pytest.mark.parametrize(
    ("label", "setup", "detail"),
    [
        ("unknown", lambda h: None, "LEGAL_HOLD_NOT_ACTIVE"),
        ("foreign tenant", lambda h: h.place(tenant="tenant-b"), "LEGAL_HOLD_NOT_ACTIVE"),
        ("released", lambda h: (h.place(), h.lift()), "LEGAL_HOLD_NOT_ACTIVE"),
    ],
)
def test_a_hold_must_be_an_active_hold_of_the_items_tenant(backends: Backends, label: str, setup: Any, detail: str) -> None:
    world = backends.world()
    world.admit("x", TEXT)
    setup(world.holds)
    before = ledger_snapshot(world)
    assert_error(lambda: world.move("x", "LEGAL_HOLD", hold=HOLD), "POLICY_DENIED", detail)
    assert ledger_snapshot(world) == before and world.status("x") == "ACTIVE"


def test_the_deletion_saga_purges_every_store_and_writes_a_non_content_tombstone(backends: Backends, tmp_path: Path) -> None:
    world = backends.world(tombstones=JournalTombstoneStore(tmp_path / "tombstones.jsonl"))
    items = populate(world)
    twin = world.admit("twin", TEXT + " north")  # same partition, same content as x
    world.rebuild(items["keep"])
    world.admit("x", TEXT + " north corrected", version=2)  # a semantic version with other content
    assert parallel_descriptors(world, items["x"]) == ["urn:ocor:memory:x:v1"]
    world.rebuild(items["keep"], op="rebuild-2")
    v2 = world.ledger.get("x", 2)
    assert v2 is not None and content_present(world, v2) and native_entries(world, items["x"]) == {"lexical": 2, "vector": 2}
    receipt = world.delete("x", op="forget-x")
    assert receipt.lifecycle_status == "DELETED" and receipt.to_mapping()["status"] == "COMPLETED"
    assert receipt.deletion_epoch == 1 and receipt.tombstone_digest is not None
    # Every native projection, parallel representation and private content object is gone.
    assert native_entries(world, items["x"]) == {"lexical": 0, "vector": 0}
    assert parallel_descriptors(world, items["x"]) == []
    assert not content_present(world, v2)
    # The content shared with an undeleted item is retained for that item only.
    assert content_present(world, twin)
    assert world.coordinator.read_version(MemoryPartition.for_item(twin.item), "twin", 1).payload == (TEXT + " north").encode()
    # Old exact versions fail closed instead of resurrecting content.
    with pytest.raises(MemoryAdmissionError) as caught:
        world.coordinator.read_version(MemoryPartition.for_item(v2.item), "x", 2)
    assert caught.value.reason_code == "REPRESENTATION_NOT_READY"
    # The tombstone is durable and content-free; the version chain records the saga.
    entries = JournalTombstoneStore(tmp_path / "tombstones.jsonl").entries("x")
    assert [e.phase for e in entries] == ["STARTED", "COMPLETED"]
    tombstone = entries[-1]
    assert tombstone.digest == receipt.tombstone_digest and tombstone.deletion_epoch == 1
    assert tombstone.retained_shared_objects == 1 and tombstone.residue_counts == ()
    assert set(tombstone.participants) == {"native-projections", "embedding-representations", "content"}
    assert no_content_in([e.to_mapping() for e in entries], TEXT, items["x"].item.content_digest, v2.item.content_digest)
    statuses = [world.ledger.get("x", v).item.lifecycle_status.value for v in range(1, 5)]  # type: ignore[union-attr]
    assert statuses == ["ACTIVE", "ACTIVE", "DELETION_PENDING", "DELETED"]
    deleted = world.lifecycle.head("x")
    assert deleted is not None and deleted.item.deletion_epoch == 1
    assert [k.value for k in deleted.item.representation_kinds] == ["STRUCTURED"] and deleted.item.embedding_ref is None
    # Retrieval: absent everywhere; the twin is still served.
    found = world.every_mode("north", v2=True)
    assert all(not any(r.startswith("urn:ocor:memory:x:") for r in refs) for refs in found.values())
    assert "urn:ocor:memory:twin:v1" in found["FULL_TEXT"]
    # Once the twin is forgotten too, nothing references the object any more: it is purged.
    assert world.delete("twin").lifecycle_status == "DELETED"
    assert not content_present(world, twin) and world.tombstones.entries("twin")[-1].retained_shared_objects == 0
    # Replay returns the same receipt; a second deletion of a DELETED item is refused.
    again = world.delete("x", op="forget-x")
    assert again.to_mapping() == receipt.to_mapping() and world.ledger.latest_version("x") == 4
    assert_error(lambda: world.delete("x"), "LIFECYCLE_TRANSITION_INVALID", "TRANSITION_NOT_DECLARED")
    assert_error(lambda: world.delete("x", op="forget-x", reason="QUOTA_PRESSURE"), "MEMORY_IDEMPOTENCY_CONFLICT", "OPERATION_REUSED")
    with pytest.raises(MemoryAdmissionError):
        world.admit("x", TEXT, version=5)


def test_a_partial_deletion_stays_incomplete_and_closed_until_a_retry_completes_it(backends: Backends) -> None:
    replica = FailingParticipant(failures=2)
    world = backends.world(replica=replica)
    items = populate(world)
    replica.track(items["x"])
    first = world.delete("x", op="forget-1")
    assert first.lifecycle_status == "DELETION_INCOMPLETE" and first.to_mapping()["status"] == "FAILED"
    assert world.status("x") == "DELETION_INCOMPLETE"
    entries = world.tombstones.entries("x")
    assert [e.phase for e in entries] == ["STARTED", "INCOMPLETE"] and entries[-1].residue_counts == (("replica", 1),)
    # Fail closed: absent from every retrieval mode although the replica still holds it.
    assert all(not any(r.startswith("urn:ocor:memory:x:") for r in refs) for refs in world.every_mode().values())
    assert not content_present(world, items["x"])  # the other participants did purge
    assert_error(lambda: world.move("x", "REVOKED"), "LIFECYCLE_TRANSITION_INVALID", "TRANSITION_NOT_DECLARED")
    second = world.delete("x", op="forget-2")
    assert second.lifecycle_status == "DELETION_INCOMPLETE" and world.tombstones.latest_epoch() == 1
    third = world.delete("x", op="forget-3")
    assert third.lifecycle_status == "DELETED" and third.deletion_epoch == 1 == first.deletion_epoch
    assert replica.residue(_Target(items["x"])) == () and replica.purges == 3
    assert [e.phase for e in world.tombstones.entries("x")] == ["STARTED", "INCOMPLETE", "STARTED", "INCOMPLETE", "STARTED", "COMPLETED"]
    assert [world.ledger.get("x", v).item.lifecycle_status.value for v in range(2, 8)] == [  # type: ignore[union-attr]
        "DELETION_PENDING", "DELETION_INCOMPLETE", "DELETION_PENDING", "DELETION_INCOMPLETE", "DELETION_PENDING", "DELETED",
    ]
    assert world.lifecycle.metrics[("requestMemoryDeletion", "INCOMPLETE", "NONE")] == 2


@dataclass
class _Target:
    record: AdmittedMemoryVersion

    @property
    def version_refs(self) -> frozenset[str]:
        return frozenset({self.record.item.version_ref})


def test_an_interrupted_transition_or_saga_is_completed_by_its_replay(backends: Backends) -> None:
    world = backends.world()
    items = populate(world)
    # Crash after the ledger append, before the store commit: the request fails, the replay completes it.
    real_commit = world.coordinator.commit
    world.coordinator.commit = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("postgres lost"))  # type: ignore[method-assign]
    with pytest.raises(ConnectionError):
        world.move("x", "REVOKED", op="revoke-x")
    assert world.ledger.latest_version("x") == 2 and world.metadata.head("x") == 1
    assert_error(lambda: world.move("x", "QUARANTINED", version=2), "REPRESENTATION_NOT_READY", "HEAD_NOT_COMMITTED")
    world.coordinator.commit = real_commit  # type: ignore[method-assign]
    receipt = world.move("x", "REVOKED", version=1, op="revoke-x")
    assert receipt.lifecycle_status == "REVOKED" and world.metadata.head("x") == 2
    assert not any(r.startswith("urn:ocor:memory:x:") for r in world.every_mode()["HYBRID"])
    # Crash inside the saga after DELETION_PENDING: retrieval already fails closed, the replay finishes.
    participant = world.lifecycle._participants[0]
    real_purge = participant.purge
    participant.purge = lambda target: (_ for _ in ()).throw(KeyboardInterrupt())  # type: ignore[method-assign]
    with pytest.raises(KeyboardInterrupt):
        world.delete("y", op="forget-y")
    assert world.status("y") == "DELETION_PENDING" and native_entries(world, items["y"]) == {"lexical": 1, "vector": 1}
    # Nothing purged yet, but the pending item is already out of every backend query.
    partition = MemoryPartition.for_item(items["y"].item)
    lexical_version = world.coordinator._limits.lexical_profile.representation_version
    raw = world.lexical.inner.search_eligible(partition, lexical_version, TEXT, where=_predicate(world), limit=50, offset=0)
    assert all(":y:" not in str(h.payload["memory_version_ref"]) for h in raw) and raw
    assert not any(r.startswith("urn:ocor:memory:y:") for r in world.every_mode()["FULL_TEXT"])
    assert_error(lambda: world.delete("y", op="other"), "LIFECYCLE_TRANSITION_INVALID", "DELETION_IN_PROGRESS")
    participant.purge = real_purge  # type: ignore[method-assign]
    done = world.delete("y", op="forget-y")
    assert done.lifecycle_status == "DELETED" and not content_present(world, items["y"])
    assert [e.phase for e in world.tombstones.entries("y")] == ["STARTED", "COMPLETED"]


def test_retention_forgets_deterministically_and_protects_held_items(backends: Backends) -> None:
    world = backends.world()
    world.admit("b-old", TEXT + " b")
    world.admit("a-old", TEXT + " a")
    world.holds.place()
    world.admit("held", TEXT + " h")
    world.move("held", "LEGAL_HOLD", hold=HOLD)
    world.admit("proposed", TEXT + " p", lifecycle="PROPOSED")
    world.admit("revised", TEXT + " r")
    world.clock.advance(timedelta(days=20))  # inside the 30-day evidence retention of the fixtures
    world.admit("young", TEXT + " y")
    world.move("revised", "REVOKED")  # version 2 is created 20 days after the first admission
    world.clock.advance(timedelta(days=350))  # 370 days after the first admissions, 350 after "young"
    report = world.lifecycle.enforce_retention(binding=t52.binding(), operation_id="retention-1", limit=1)
    assert report.processed == ("urn:ocor:memory:a-old:v3",)  # due instant, then item id
    assert report.deferred == ("urn:ocor:memory:b-old:v1", "urn:ocor:memory:revised:v2")
    assert report.held == ("urn:ocor:memory:held:v2",)
    assert report.unresolved == ("urn:ocor:memory:proposed:v1",)
    rest = world.lifecycle.enforce_retention(binding=t52.binding(), operation_id="retention-2")
    assert rest.processed == ("urn:ocor:memory:b-old:v3", "urn:ocor:memory:revised:v4")
    assert rest.held == ("urn:ocor:memory:held:v2",)
    assert {n: world.status(n) for n in ("a-old", "b-old", "held", "proposed", "young")} == {
        "a-old": "DELETED", "b-old": "DELETED", "held": "LEGAL_HOLD", "proposed": "PROPOSED", "young": "ACTIVE"
    }
    assert [e.deletion_epoch for e in world.tombstones.entries("a-old")] == [1, 1]
    assert [e.deletion_epoch for e in world.tombstones.entries("b-old")] == [2, 2]
    assert content_present(world, world.ledger.get("held", 1))  # type: ignore[arg-type]


def test_a_non_reproducible_embedding_refuses_the_transition_before_any_write(backends: Backends) -> None:
    world = backends.world()
    world.admit("x", TEXT)
    real = world.coordinator.embed_query
    world.coordinator.embed_query = lambda profile, text: tuple(reversed(real(profile, text)))  # type: ignore[method-assign]
    before = ledger_snapshot(world)
    assert_error(lambda: world.move("x", "REVOKED"), "REPRESENTATION_NOT_READY", "EMBEDDING_NOT_REPRODUCIBLE")
    assert ledger_snapshot(world) == before and world.metadata.head("x") == 1
    world.coordinator.embed_query = real  # type: ignore[method-assign]
    assert world.move("x", "REVOKED").lifecycle_status == "REVOKED"


def test_retention_with_an_unconfigured_horizon_is_reported_never_deleted(backends: Backends) -> None:
    world = backends.world()
    world.admit("x", TEXT)
    world.clock.advance(timedelta(days=400))
    lifecycle = world.build_lifecycle(retention_horizons={})
    report = lifecycle.enforce_retention(binding=t52.binding(), operation_id="r")
    assert report.unresolved == ("urn:ocor:memory:x:v1",) and report.processed == ()
    assert world.status("x") == "ACTIVE"


def test_reopening_requires_a_readable_unchanged_stop_epoch_but_exclusion_never_waits(backends: Backends) -> None:
    world = backends.world()
    world.admit("q", TEXT, lifecycle="QUARANTINED")
    world.admit("x", TEXT + " north")
    world.lc_stop.fail = True
    assert_error(lambda: world.move("q", "ACTIVE"), "CONTROL_PLANE_UNAVAILABLE", "STOP_STATE_UNKNOWN")
    assert world.move("x", "REVOKED").lifecycle_status == "REVOKED"  # exclusion under an unknown stop state
    world.lc_stop.fail = False
    world.lc_stop.bump_after = world.lc_stop.reads + 1
    assert_error(lambda: world.move("q", "ACTIVE"), "STOP_EPOCH_MISMATCH", "STOP_EPOCH_CHANGED")
    assert world.status("q") == "QUARANTINED" and world.ledger.latest_version("q") == 1
    world.lc_stop.bump_after = None
    assert world.move("q", "ACTIVE", reason="REVIEW_PASSED").lifecycle_status == "ACTIVE"
    assert "urn:ocor:memory:q:v2" in world.every_mode()["FULL_TEXT"]


def _during_read(world: World, item_id: str, action: Any) -> list[str]:
    """Run ``action()`` once, inside the first real content read of ``item_id``."""

    original = world.coordinator.read_version
    fired: list[str] = []

    def read(partition: MemoryPartition, memory_item_id: str, memory_version: int) -> Any:
        materialized = original(partition, memory_item_id, memory_version)
        if memory_item_id == item_id and not fired:
            fired.append(f"{memory_item_id}:v{memory_version}")
            action()
        return materialized

    world.coordinator.read_version = read  # type: ignore[method-assign]
    return fired


def test_a_stop_epoch_changed_during_the_content_read_refuses_reopening_before_any_write(backends: Backends) -> None:
    """VF-001: the stop epoch is re-read after content verification, right before the append."""

    world = backends.world()
    world.admit("q", TEXT, lifecycle="QUARANTINED")
    ledger = ledger_snapshot(world)
    reads = world.lc_stop.reads
    fired = _during_read(world, "q", lambda: setattr(world.lc_stop, "epoch", world.lc_stop.epoch + 1))
    assert_error(lambda: world.move("q", "ACTIVE", reason="REVIEW_PASSED"), "STOP_EPOCH_MISMATCH", "STOP_EPOCH_CHANGED")
    assert fired == ["q:v1"]  # the epoch moved inside the only content read
    assert world.lc_stop.reads - reads == 2  # read before the content I/O and right before the append
    assert world.status("q") == "QUARANTINED" and world.ledger.latest_version("q") == 1
    assert ledger_snapshot(world) == ledger and world.metadata.get("q", 2) is None
    assert denials(world) == [("STOP_EPOCH_MISMATCH", "STOP_EPOCH_CHANGED")]
    assert all("urn:ocor:memory:q:" not in ref for refs in world.every_mode().values() for ref in refs)
    # The same re-opening under the new, now stable epoch succeeds.
    assert world.move("q", "ACTIVE", reason="REVIEW_PASSED").lifecycle_status == "ACTIVE"
    assert "urn:ocor:memory:q:v2" in world.every_mode()["FULL_TEXT"]


def test_a_stop_epoch_changed_during_the_content_read_refuses_a_hold_release_to_active(backends: Backends) -> None:
    world = backends.world()
    populate(world)
    world.holds.place()
    world.move("x", "LEGAL_HOLD", hold=HOLD, reason="LITIGATION_HOLD")
    world.holds.lift()
    ledger = ledger_snapshot(world)
    fired = _during_read(world, "x", lambda: setattr(world.lc_stop, "epoch", world.lc_stop.epoch + 1))
    assert_error(lambda: world.move("x", "ACTIVE", reason="HOLD_RELEASED"), "STOP_EPOCH_MISMATCH", "STOP_EPOCH_CHANGED")
    assert fired == ["x:v2"] and world.status("x") == "LEGAL_HOLD" and ledger_snapshot(world) == ledger
    assert denials(world) == [("STOP_EPOCH_MISMATCH", "STOP_EPOCH_CHANGED")]
    assert all(not ref.startswith("urn:ocor:memory:x:") for refs in world.every_mode().values() for ref in refs)
    assert world.move("x", "ACTIVE", reason="HOLD_RELEASED").lifecycle_status == "ACTIVE"
    assert "urn:ocor:memory:x:v3" in world.every_mode()["FULL_TEXT"]


def test_an_exclusion_never_waits_on_a_stop_epoch_changed_during_the_content_read(backends: Backends) -> None:
    world = backends.world()
    populate(world)
    fired = _during_read(world, "x", lambda: setattr(world.lc_stop, "epoch", world.lc_stop.epoch + 1))
    assert world.move("x", "REVOKED", reason="SOURCE_RETRACTED").lifecycle_status == "REVOKED"
    assert fired == ["x:v1"] and denials(world) == []
    assert all(not ref.startswith("urn:ocor:memory:x:") for refs in world.every_mode().values() for ref in refs)


@pytest.mark.parametrize("mode", list(RetrievalMode))
@pytest.mark.parametrize("target", ["REVOKED", "EXPIRED", "SUPERSEDED"])
def test_a_lifecycle_exclusion_committed_during_the_search_read_leaves_no_hit(
    backends: Backends, mode: RetrievalMode, target: str
) -> None:
    """VF-002 on 0055: this coordinator excludes the item while retrieval reads its content."""

    world = backends.world()
    populate(world)
    fired = _during_read(world, "x", lambda: world.move("x", target, reason="SOURCE_RETRACTED" if target == "REVOKED" else "OPERATOR_DECISION"))
    with pytest.raises(MemoryRetrievalError) as caught:
        world.search(mode)
    assert (caught.value.reason_code, caught.value.detail_code) == ("REPRESENTATION_NOT_READY", "CANDIDATE_CHANGED")
    assert fired == ["x:v1"] and world.status("x") == target
    assert [(str(e["reason_code"]), str(e["detail_code"])) for e in world.audit.events if e["action"] == "searchMemory.denied"] == [
        ("REPRESENTATION_NOT_READY", "CANDIDATE_CHANGED")
    ]
    assert [e for e in world.audit.events if e["action"] == "searchMemory"] == []
    # Afterwards the excluded item is absent and every other hit is served.
    refs = t52.refs(world.search(mode))
    assert sorted(refs) == ["urn:ocor:memory:keep:v1", "urn:ocor:memory:y:v1"], refs


def test_a_deletion_saga_started_during_the_search_read_leaves_no_hit(backends: Backends) -> None:
    world = backends.world()
    populate(world)
    fired = _during_read(world, "x", lambda: world.delete("x"))
    with pytest.raises(MemoryRetrievalError) as caught:
        world.search(RetrievalMode.FULL_TEXT)
    assert (caught.value.reason_code, caught.value.detail_code) == ("REPRESENTATION_NOT_READY", "CANDIDATE_CHANGED")
    assert fired == ["x:v1"] and world.status("x") == "DELETED"
    assert sorted(t52.refs(world.search(RetrievalMode.FULL_TEXT))) == ["urn:ocor:memory:keep:v1", "urn:ocor:memory:y:v1"]


@pytest.mark.parametrize("mode", list(RetrievalMode))
def test_a_search_without_lifecycle_changes_during_the_read_is_unchanged(backends: Backends, mode: RetrievalMode) -> None:
    world = backends.world()
    populate(world)
    before = t52.refs(world.search(mode))
    fired = _during_read(world, "x", lambda: None)
    assert t52.refs(world.search(mode)) == before and fired == ["x:v1"]
    assert sorted(before) == ["urn:ocor:memory:keep:v1", "urn:ocor:memory:x:v1", "urn:ocor:memory:y:v1"]
    assert [e for e in world.audit.events if e["action"] == "searchMemory.denied"] == []


def test_lifecycle_state_is_durable_across_fresh_adapters(backends: Backends, tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    world = backends.world(tombstones=JournalTombstoneStore(tmp_path / "t.jsonl"))
    world.ledger = JournalMemoryVersionLedger(ledger_path)  # type: ignore[assignment]
    world.admission = MemoryAdmissionService(
        ledger=world.ledger, resolver=t52.Resolver(), policy=LifecycleGuardPolicy(base.Policy(), ledger=world.ledger),
        markings=world.markings, clock=world.clock, limits=AdmissionLimits(retention_horizons={"retention:standard": HORIZON}),
    )
    world.coordinator = world.build()
    world.lifecycle = world.build_lifecycle()
    populate(world)
    world.move("x", "REVOKED")
    world.delete("y")
    fresh = backends.world(schema=world.metadata.schema, tombstones=JournalTombstoneStore(tmp_path / "t.jsonl"))
    fresh.ledger = JournalMemoryVersionLedger(ledger_path)  # type: ignore[assignment]
    fresh.clock = world.clock
    fresh.coordinator = fresh.build()
    fresh.lifecycle = fresh.build_lifecycle()
    assert fresh.status("x") == "REVOKED" and fresh.status("y") == "DELETED"
    assert fresh.tombstones.latest_epoch() == 1
    assert sorted(r.split(":")[3] for r in fresh.every_mode()["HYBRID"]) == ["keep"]
    assert_error(lambda: fresh.move("x", "ACTIVE", op="reopen-x"), "LIFECYCLE_TRANSITION_INVALID", "TRANSITION_NOT_DECLARED")
    # Operation ids are durable too: the first run's "lc-1" is bound to its revocation.
    assert_error(lambda: fresh.move("x", "ACTIVE", op="lc-1"), "MEMORY_IDEMPOTENCY_CONFLICT", "OPERATION_REUSED")


def test_every_lifecycle_refusal_on_the_real_stack_is_an_audited_denial(backends: Backends) -> None:
    world = backends.world()
    world.admit("x", TEXT)
    assert_error(lambda: world.move("x", "EXPIRED", version=2), "LIFECYCLE_TRANSITION_INVALID", "STALE_VERSION")
    assert_error(lambda: world.delete("x", ctx=OUTSIDER), "MEMORY_NOT_FOUND", "ITEM_NOT_VISIBLE")
    world.lc_policy.permitted = False
    assert_error(lambda: world.delete("x"), "POLICY_DENIED", "LIFECYCLE_DENIED")
    assert denials(world) == [
        ("LIFECYCLE_TRANSITION_INVALID", "STALE_VERSION"),
        ("MEMORY_NOT_FOUND", "ITEM_NOT_VISIBLE"),
        ("POLICY_DENIED", "LIFECYCLE_DENIED"),
    ]
    assert [e["action"] for e in world.lc_audit.events] == [
        "transitionMemoryLifecycle.denied", "requestMemoryDeletion.denied", "requestMemoryDeletion.denied"
    ]
    assert world.status("x") == "ACTIVE" and content_present(world, world.ledger.get("x", 1))  # type: ignore[arg-type]
    assert re.fullmatch(r"urn:sha256:[0-9a-f]{64}", str(world.lc_audit.events[-1]["governed_context_digest"]))


def test_forgetting_a_reclassified_item_purges_every_partition_of_its_versions(backends: Backends) -> None:
    world = backends.world()
    secret = t52.context(compartments=("alpha", "bravo"), marking=t52.M_SECRET)
    v1 = world.admit("x", TEXT + " north")
    v2 = world.admit("x", TEXT + " north reclassified", version=2, ctx=t52.context(marking=t52.M_SECRET))
    assert MemoryPartition.for_item(v1.item) != MemoryPartition.for_item(v2.item)
    assert content_present(world, v1) and content_present(world, v2)
    # The restricted caller cannot see the reclassified head: refused like an unknown item.
    assert_error(lambda: world.move("x", "DELETION_PENDING", reason="PURPOSE_COMPLETION", version=2), "MEMORY_NOT_FOUND", "ITEM_NOT_VISIBLE")
    receipt = world.move("x", "DELETION_PENDING", reason="PURPOSE_COMPLETION", version=2, ctx=secret)
    assert receipt.lifecycle_status == "DELETED" and receipt.to_mapping()["operation_kind"] == "transitionMemoryLifecycle"
    assert not content_present(world, v1) and not content_present(world, v2)
    assert native_entries(world, v1) == {"lexical": 0, "vector": 0} and native_entries(world, v2) == {"lexical": 0, "vector": 0}
    tombstone = world.tombstones.entries("x")[-1]
    assert tombstone.phase == "COMPLETED" and len(tombstone.partition_digests) == 2
    assert tombstone.reason_code == "PURPOSE_COMPLETION"
    cleared = world.search(RetrievalMode.HYBRID, ctx=secret)
    assert not any(r.startswith("urn:ocor:memory:x:") for r in t52.refs(cleared))
