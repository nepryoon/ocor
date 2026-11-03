"""OCOR-DEV-REM-0051 (NCP-U06): C5 event backbone conformant to the closed normative elements.

One test per register entry resolved by NCP-U06 of the approved plan
(``reports/development/NORMATIVE_CONFORMANCE_REGISTER.json`` ``plan_units.NCP-U06``,
NORMATIVE-CONFORMANCE-PLAN (2026-10-30)), plus the detailed cases of each entry.
The normative elements realised or verified are cited with file and line:

- ADD v1.3 = ``ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md``
- LLD v1.1 = ``docs/OCOR_LLD_v1.1.md``
- Register = ``ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md``

- NCR-C5-001: ADD v1.3 :527-840 (``canonical-ingestion-envelope:1.2``, closed, 29 required
  fields; the payload is validated a second time against the content-addressed schema named
  by ``payload_schema``: failure, absent schema or discordant digest produce a ``Violation``
  and quarantine); ADD v1.3 :379 (ingestion: ``effective_principal_id`` comes from the
  transport, external mismatch -> ``QUARANTINED``, incomplete -> ``REJECTED``) and :199
  (``QUARANTINED{reason=PRINCIPAL_BINDING_MISMATCH}`` with an Audit Record); LLD v1.1 :154
  (closed envelope; the producer signs envelope and digest); Register :199 (FR-069: batch,
  streaming and CDC fixtures produce a conformant envelope or a typed Violation), :192
  (FR-068) and :49 (FR-006).
- NCR-C5-002: LLD v1.1 :156-165 (failure taxonomy ``TRANSIENT`` exponential backoff with
  bounded jitter and retry budget, ``PERMANENT`` immutable DLQ without automatic retry,
  ``POLICY_DENIED`` audit and non-disclosing quarantine, ``POISON`` partition quarantine
  and operator gate; checkpoint binds topic/partition/offset, schema registry digest,
  release and GCS; replay declares window and reason, preserves the event ID, does not
  bypass policy and never publishes a canonical effect twice); ADD v1.3 :286 (C5 ports
  ``Publish``, ``Subscribe``, ``Replay``, ``Quarantine``, ``ReprocessAuthorized``); ADD v1.3
  :2573-2575 and :2577-2700 (Event Subscription Contract through the port ``Subscribe``: no
  physical broker offsets, the consumer moves by ``subscription_id`` and opaque cursor;
  replay needs authorisation and a bounded ``max_replay_window``); Register :205 (FR-074),
  :79 (FR-016) and :202 (FR-072).
- NCR-C5-003: LLD v1.1 :165 (quotas per tenant and priority class; audit/security are never
  dropped); LLD v1.1 :161 (``PERMANENT`` -> immutable DLQ); LLD v1.1 :338 (ResourceClass
  ``CONTROL``, ``INTERACTIVE``, ``BATCH``, ``AUDIT`` determines quota, priority and
  backpressure; control/audit do not share an exhaustible pool with batch); Register :406
  (NFR-079: backpressure and priority without disabling authentication, policy or audit).

Oracles are independent of the module under test: the topic content is read back from the
real broker through the qualification tool (Kafka CLI end offsets), dead letters,
quarantine and checkpoints are read with direct SQL (``psycopg``), audit records with the
sealed audit chain verifier, signatures are produced in the test with the sealed C1 Ed25519
signer. Backends are real: Kafka (an isolated, pinned single-node KRaft broker of the
qualification tool ``c5_kafka_qualification``) and PostgreSQL (``OCOR_LIVE_POSTGRES_DSN``);
without them every case fails, never skips. The policy decisions are an explicit test port
of the C5 policy port (OPA owns them in production). Journal fault points are explicit
instruments over the real in-process client.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from c5_kafka_qualification import KafkaBrokerError, QualificationKafkaBroker
from ocor_runtime.audit import AuditSigner, PostgresAuditLog, verify_audit_chain
from ocor_runtime.c1.signing import Ed25519SigningKey, dsse_pae, ed25519_verify
from ocor_runtime.kernel.canonical import canonical_bytes

ROOT = Path(__file__).resolve().parents[2]
ADD = ROOT / "docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md"

PRODUCER = "urn:ocor:principal:c3-outbox-relay"
OTHER_PRINCIPAL = "urn:ocor:principal:rogue-adapter"
CONSUMER = "urn:ocor:principal:c4-projector"
OPERATOR = "urn:ocor:principal:c5-operator"
EVENT_TYPE = "urn:ocor:event-type:mission-effect-recorded"
AUDIT_EVENT_TYPE = "urn:ocor:event-type:security-audit-recorded"
CONTROL_EVENT_TYPE = "urn:ocor:event-type:control-stop-issued"
PAYLOAD_SCHEMA_ID = "urn:ocor:schema:mission-effect-recorded"
PAYLOAD_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["status"],
    "properties": {"status": {"enum": ["ASSESSED", "CONFIRMED"]}},
}
GCS = "sha256:" + "a" * 64
OTHER_GCS = "sha256:" + "b" * 64
SIGNATURE_PAYLOAD_TYPE = "application/vnd.ocor.canonical-ingestion-envelope+json"
SEED = hashlib.sha256(b"ocor-rem-0051-producer").digest()
ROGUE_SEED = hashlib.sha256(b"ocor-rem-0051-rogue").digest()
AUDIT_SEED = hashlib.sha256(b"ocor-rem-0051-audit").digest()


def _c5(name: str) -> Any:
    """Resolve a C5 module lazily, so each case fails on its own on the code under remediation."""
    return importlib.import_module(f"ocor_runtime.c5.{name}")


def add_envelope_schema() -> dict[str, Any]:
    """The JSON Schema block of ADD v1.3 section 3.2, read from the approved baseline."""
    text = ADD.read_text(encoding="utf-8")
    start = text.index("## 3.2 Canonical Ingestion Envelope")
    block = text[text.index("~~~json\n", start) + len("~~~json\n") :]
    return json.loads(block[: block.index("\n~~~")])


def add_subscription_schema() -> dict[str, Any]:
    text = ADD.read_text(encoding="utf-8")
    start = text.index("## 3.8 Event Subscription Contract")
    block = text[text.index("~~~json\n", start) + len("~~~json\n") :]
    return json.loads(block[: block.index("\n~~~")])


def schema_digest(document: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(document)).hexdigest()


def stable(kind: str) -> str:
    return f"urn:ocor:{kind}:{uuid.uuid4().hex}"


def marking() -> dict[str, Any]:
    return {
        "scheme_id": "urn:ocor:marking-scheme:poc",
        "labels": ["RESTRICTED"],
        "mandatory_markings": [],
        "caveats": [],
        "dissemination_controls": [],
        "permitted_purposes": ["urn:ocor:purpose:mission-planning"],
        "handling_instructions": [],
        "marking_digest": "sha256:" + "c" * 64,
    }


def raw_envelope(
    *,
    mode: str = "STREAM",
    event_type: str = EVENT_TYPE,
    payload: dict[str, Any] | None = None,
    ordering_key: str | None = None,
    tenant: str = "urn:ocor:tenant:alpha",
    gcs: str = GCS,
    principal: str = PRODUCER,
    expected_revision: int | None = None,
    ingest_time: datetime | None = None,
    pin: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A complete ``canonical-ingestion-envelope:1.2`` (ADD v1.3 :531-840) before signing."""
    event_id = str(uuid.uuid4())
    now = ingest_time or datetime.now(UTC)
    transport: dict[str, Any]
    semantic_class = "OBSERVED_EVENT"
    if mode == "BATCH":
        transport = {"mode": "BATCH", "batch_id": str(uuid.uuid4()), "record_index": 0}
    elif mode == "CDC":
        semantic_class = "CDC_CHANGE"
        transport = {
            "mode": "CDC",
            "operation": "UPDATE",
            "source_transaction_id": "tx-1",
            "source_position": "lsn-1",
            "before_digest": "sha256:" + "d" * 64,
            "after_digest": None,
        }
    else:
        transport = {"mode": "STREAM", "stream_id": "urn:ocor:stream:mission", "partition": 0, "offset": "0"}
    aggregate: dict[str, Any] = {"aggregate_type_id": "urn:ocor:aggregate-type:mission-object", "aggregate_id": "mo-1"}
    if expected_revision is not None:
        aggregate["expected_revision"] = expected_revision
    return {
        "envelope_version": "1.2",
        "event_id": event_id,
        "tenant_id": tenant,
        "organization_id": "urn:ocor:organization:alpha",
        "domain_id": "urn:ocor:domain:mission",
        "compartments": ["urn:ocor:compartment:ops"],
        "world_ref": "urn:ocor:world:main",
        "ingest_mode": mode,
        "semantic_class": semantic_class,
        "event_type_id": event_type,
        "event_time": now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "ingest_time": now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "ordering_key": ordering_key or f"mission-object/{uuid.uuid4().hex}",
        "idempotency_key": f"idem-{event_id}",
        "purpose": "urn:ocor:purpose:mission-planning",
        "source": {
            "source_id": "urn:ocor:source:c3-outbox",
            "source_record_id": f"outbox-{event_id}",
            "adapter_id": "urn:ocor:adapter:c3-relay",
            "adapter_version": "1.0.0",
        },
        "aggregate": aggregate,
        "payload_schema": pin or {},
        "payload": payload if payload is not None else {"status": "ASSESSED"},
        "classification_marking": marking(),
        "provenance_ref": "urn:sha256:" + "e" * 64,
        "integrity": {"payload_digest": "sha256:" + "0" * 64, "source_producer_principal_ref": principal},
        "effective_principal_id": principal,
        "actor_chain": [principal],
        "governed_context_digest": gcs,
        "ontology_release_digest": "sha256:" + "1" * 64,
        "policy_bundle_digest": "sha256:" + "2" * 64,
        "correlation_id": str(uuid.uuid4()),
        "causation_id": None,
        "transport": transport,
    }


@dataclass
class RulePolicy:
    """Explicit test port of the C5 policy port: publish, delivery and replay decisions."""

    denied_publish_event_types: set[str] = field(default_factory=set)
    denied_delivery_event_ids: set[str] = field(default_factory=set)
    replay_authorities: set[str] = field(default_factory=lambda: {"urn:ocor:authority:replay-ops"})
    calls: list[tuple[str, str]] = field(default_factory=list)

    def authorize_publish(self, principal: str, envelope: Any) -> Any:
        self.calls.append(("publish", envelope.event_id))
        allowed = envelope.event_type_id not in self.denied_publish_event_types
        return _c5("policy").PolicyDecision(allowed=allowed, reason_code="PERMITTED" if allowed else "POLICY_DENIED")

    def authorize_delivery(self, principal: str, subscription_id: str, envelope: Any) -> Any:
        self.calls.append(("delivery", envelope.event_id))
        allowed = envelope.event_id not in self.denied_delivery_event_ids
        return _c5("policy").PolicyDecision(allowed=allowed, reason_code="PERMITTED" if allowed else "POLICY_DENIED")

    def authorize_replay(self, principal: str, request: Any) -> Any:
        self.calls.append(("replay", request.subscription_id))
        allowed = principal == OPERATOR and request.authority_ref in self.replay_authorities
        return _c5("policy").PolicyDecision(allowed=allowed, reason_code="PERMITTED" if allowed else "REPLAY_DENIED")


@pytest.fixture(scope="module")
def broker() -> Iterator[QualificationKafkaBroker]:
    try:
        value, _container, volume = QualificationKafkaBroker.provision(f"ocor-rem0051-{uuid.uuid4().hex[:12]}")
    except KafkaBrokerError as error:
        pytest.fail(f"a real, isolated Kafka broker is mandatory qualifying evidence: {error}")
    try:
        yield value
    finally:
        value.destroy(volume)


@pytest.fixture
def topic(broker: QualificationKafkaBroker) -> str:
    return broker.create_topic(f"ocor-rem0051-{uuid.uuid4().hex[:12]}")


@pytest.fixture
def dsn() -> str:
    value = os.environ.get("OCOR_LIVE_POSTGRES_DSN", "")
    if not value:
        pytest.fail("OCOR_LIVE_POSTGRES_DSN is mandatory: the C5 DLQ, quarantine and checkpoints are durable on PostgreSQL")
    return value


@pytest.fixture
def schema_name(dsn: str) -> Iterator[str]:
    name = f"ocor_rem0051_{uuid.uuid4().hex[:12]}"
    try:
        yield name
    finally:
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')
            connection.execute(f'DROP SCHEMA IF EXISTS "{name}_audit" CASCADE')


@dataclass
class Rig:
    """The composed C5 backbone of one test, with its real backends and oracles."""

    backbone: Any
    broker: QualificationKafkaBroker
    topic: str
    dsn: str
    schema: str
    policy: RulePolicy
    audit: PostgresAuditLog
    audit_key: bytes
    signer: Any
    pin: dict[str, Any]
    journal: Any
    sleeps: list[float]

    def signed(self, **kwargs: Any) -> Any:
        kwargs.setdefault("pin", self.pin)
        return self.signer.sign(raw_envelope(**kwargs))

    def topic_records(self) -> int:
        return self.broker.record_count(self.topic)

    def rows(self, table: str) -> list[dict[str, Any]]:
        with psycopg.connect(self.dsn, row_factory=psycopg.rows.dict_row) as connection:
            return list(connection.execute(f'SELECT * FROM "{self.schema}".{table}').fetchall())  # noqa: S608

    def audit_records(self) -> list[Any]:
        records = self.audit.records()
        verify_audit_chain(records, {"c5-audit": self.audit_key})
        return records


def build_rig(
    broker: QualificationKafkaBroker,
    topic: str,
    dsn: str,
    schema: str,
    *,
    journal_type: Any = None,
    quotas: dict[str, int] | None = None,
    max_attempts: int = 4,
) -> Rig:
    envelope = _c5("envelope")
    registry_module = _c5("schema")
    operations = _c5("operations")
    retry = _c5("retry")
    kafka = _c5("kafka")
    dlq = _c5("dlq")
    backbone_module = _c5("backbone")

    registry = registry_module.SchemaRegistry()
    pin = registry.register_schema(PAYLOAD_SCHEMA_ID, "1.0.0", PAYLOAD_SCHEMA)
    registry.register_event_type(EVENT_TYPE, payload_schema=pin, resource_class=operations.ResourceClass.BATCH)
    registry.register_event_type(AUDIT_EVENT_TYPE, payload_schema=pin, resource_class=operations.ResourceClass.AUDIT)
    registry.register_event_type(CONTROL_EVENT_TYPE, payload_schema=pin, resource_class=operations.ResourceClass.CONTROL)
    key = Ed25519SigningKey.from_seed(SEED)
    keyring = envelope.ProducerKeyring({PRODUCER: key.public_key, OTHER_PRINCIPAL: key.public_key})
    audit_key = Ed25519SigningKey.from_seed(AUDIT_SEED)
    audit = PostgresAuditLog(dsn, schema=f"{schema}_audit", signer=AuditSigner(key=audit_key, keyid="c5-audit"))
    audit.initialize()
    store = dlq.PostgresC5Store(dsn, schema=schema)
    store.initialize()
    journal = (journal_type or kafka.KafkaJournal)(broker.bootstrap_servers, topic)
    sleeps: list[float] = []
    policy = RulePolicy()
    resolved = {operations.ResourceClass[name]: limit for name, limit in (quotas or {}).items()}
    value = backbone_module.CanonicalEventBackbone(
        journal=journal,
        registry=registry,
        keyring=keyring,
        policy=policy,
        audit=audit,
        store=store,
        retry=retry.RetryPolicy(
            max_attempts=max_attempts, base_delay_s=0.05, max_delay_s=0.4, jitter_ratio=0.5,
            sleep=sleeps.append, rng=lambda: 1.0,
        ),
        quotas=resolved or None,
    )
    return Rig(
        backbone=value, broker=broker, topic=topic, dsn=dsn, schema=schema, policy=policy, audit=audit,
        audit_key=audit_key.public_key, signer=envelope.ProducerSigner(PRODUCER, key), pin=pin,
        journal=journal, sleeps=sleeps,
    )


@pytest.fixture
def env(broker: QualificationKafkaBroker, topic: str, dsn: str, schema_name: str) -> tuple[Any, ...]:
    """The real backends of one case; each case composes its backbone in its own body."""
    return broker, topic, dsn, schema_name


def reason_of(call: Any) -> tuple[str, str | None, str]:
    """Run ``call``; return reason code, failure class and message of the C5 error it raises."""
    with pytest.raises(_c5("envelope").BackboneError) as excinfo:
        call()
    return excinfo.value.reason_code, getattr(excinfo.value, "failure_class", None), str(excinfo.value)


def subscription_contract(*, replay_allowed: bool = True, event_types: list[str] | None = None) -> dict[str, Any]:
    contract: dict[str, Any] = {
        "subscription_contract_id": stable("subscription-contract"),
        "version": "1.0.0",
        "contract_digest": "sha256:" + "f" * 64,
        "governed_context_ref": "urn:sha256:" + "a" * 64,
        "event_type_refs": event_types or [EVENT_TYPE],
        "delivery": {"semantics": "AT_LEAST_ONCE", "consumer_must_deduplicate": True, "dedup_key": "event_id"},
        "ordering": {"guarantee": "PER_ORDERING_KEY", "ordering_key_field": "ordering_key"},
        "filter": {"filter_contract_id": "urn:ocor:filter:all-mission-effects", "arbitrary_predicates_allowed": False},
        "payload_schema": {
            "schema_id": PAYLOAD_SCHEMA_ID,
            "version": "1.0.0",
            "digest": schema_digest(PAYLOAD_SCHEMA),
        },
        "marking_policy": {"propagate_marking": True, "redact_unauthorized": True, "declare_redactions": True},
        "replay": {"replay_allowed": replay_allowed, "cursor_opaque": True, "authorization_required": True},
        "error_codes": ["POLICY_DENIED", "REPLAY_DENIED", "CURSOR_EXPIRED", "SCHEMA_VIOLATION"],
    }
    if replay_allowed:
        contract["replay"]["max_replay_window"] = "P1D"
    return contract


# --------------------------------------------------------------------------------------------
# NCR-C5-001 -- canonical-ingestion-envelope:1.2, second payload validation, producer signature
# --------------------------------------------------------------------------------------------


def test_ncr_c5_001_conforms(env: tuple[Any, ...]) -> None:
    """ADD v1.3 :531-840 and Register :199 (FR-069): the backbone validates the closed 1.2
    envelope of the approved baseline; batch, streaming and CDC fixtures publish and are
    delivered unchanged; a non-conformant envelope is a typed Violation, never published."""
    rig = build_rig(*env)
    envelope = _c5("envelope")
    schema = add_envelope_schema()
    assert envelope.ENVELOPE_SCHEMA_ID == "urn:ocor:schema:canonical-ingestion-envelope:1.2"
    assert envelope.ENVELOPE_SCHEMA == schema
    assert len(schema["required"]) == 29 and schema["additionalProperties"] is False

    sent = [rig.signed(mode=mode) for mode in ("BATCH", "STREAM", "CDC")]
    for signed in sent:
        receipt = rig.backbone.publish(signed, transport_principal=PRODUCER)
        assert receipt.event_id == signed.envelope.event_id and receipt.duplicate is False
    assert rig.topic_records() == 3

    subscription = rig.backbone.subscribe(subscription_contract(), principal=CONSUMER)
    batch = rig.backbone.poll(subscription, cursor=None, max_records=3, timeout_s=20)
    received = {event.envelope.event_id: event.envelope.to_mapping() for event in batch.events}
    assert received == {signed.envelope.event_id: signed.envelope.to_mapping() for signed in sent}

    # a missing required field and an undeclared extra field are typed Violations (REJECTED)
    incomplete = raw_envelope(pin=rig.pin)
    del incomplete["purpose"]
    code, failure_class, _ = reason_of(lambda: envelope.CanonicalIngestionEnvelope.from_mapping(incomplete))
    assert (code, failure_class) == ("SCHEMA_VIOLATION", "PERMANENT")
    extra = raw_envelope(pin=rig.pin)
    extra["sequence"] = 1
    code, _, _ = reason_of(lambda: envelope.CanonicalIngestionEnvelope.from_mapping(extra))
    assert code == "SCHEMA_VIOLATION"
    cdc_mismatch = raw_envelope(mode="CDC", pin=rig.pin)
    cdc_mismatch["semantic_class"] = "OBSERVATION"
    code, _, _ = reason_of(lambda: envelope.CanonicalIngestionEnvelope.from_mapping(cdc_mismatch))
    assert code == "SCHEMA_VIOLATION"
    assert rig.topic_records() == 3


def test_ncr_c5_001_second_payload_validation_quarantines_failures(env: tuple[Any, ...]) -> None:
    """ADD v1.3 :529: the payload is validated again against the content-addressed schema of
    ``payload_schema``; failure, absent schema or discordant digest -> Violation and quarantine."""
    rig = build_rig(*env)
    invalid_payload = rig.signed(payload={"status": "UNKNOWN"})
    absent = rig.signed(pin={"schema_id": "urn:ocor:schema:not-registered", "schema_version": "1.0.0",
                             "schema_digest": schema_digest({"type": "object"})})
    discordant = rig.signed(pin={**rig.pin, "schema_digest": "sha256:" + "9" * 64})
    outcomes = {}
    for name, signed in (("payload", invalid_payload), ("absent", absent), ("digest", discordant)):
        outcomes[name] = reason_of(lambda signed=signed: rig.backbone.publish(signed, transport_principal=PRODUCER))[0]
    assert outcomes == {"payload": "SCHEMA_VIOLATION", "absent": "UNKNOWN_SCHEMA", "digest": "SCHEMA_DIGEST_MISMATCH"}
    assert rig.topic_records() == 0
    rows = {row["event_id"]: row for row in rig.rows("c5_dead_letter")}
    for signed, code in ((invalid_payload, "SCHEMA_VIOLATION"), (absent, "UNKNOWN_SCHEMA"),
                         (discordant, "SCHEMA_DIGEST_MISMATCH")):
        row = rows[signed.envelope.event_id]
        assert (row["reason_code"], row["failure_class"]) == (code, "PERMANENT")


def test_ncr_c5_001_producer_signature_covers_envelope_and_digest(env: tuple[Any, ...]) -> None:
    """LLD v1.1 :154: the producer signs envelope and digest; the backbone verifies both."""
    rig = build_rig(*env)
    signed = rig.signed()
    mapping = signed.envelope.to_mapping()
    assert mapping["integrity"]["payload_digest"] == "sha256:" + hashlib.sha256(
        canonical_bytes(mapping["payload"])).hexdigest()
    assert mapping["integrity"]["signature_ref"] == "urn:sha256:" + hashlib.sha256(signed.signature).hexdigest()
    unsigned_view = json.loads(json.dumps(mapping))
    del unsigned_view["integrity"]["signature_ref"]
    assert ed25519_verify(
        Ed25519SigningKey.from_seed(SEED).public_key,
        dsse_pae(SIGNATURE_PAYLOAD_TYPE, canonical_bytes(unsigned_view)),
        signed.signature,
    )

    envelope = _c5("envelope")
    tampered = dict(mapping, payload={"status": "CONFIRMED"})
    forged = envelope.SignedEnvelope(envelope.CanonicalIngestionEnvelope.from_mapping(tampered), signed.signature)
    assert reason_of(lambda: rig.backbone.publish(forged, transport_principal=PRODUCER))[0] == "PAYLOAD_DIGEST_MISMATCH"
    rogue = envelope.ProducerSigner(PRODUCER, Ed25519SigningKey.from_seed(ROGUE_SEED)).sign(raw_envelope(pin=rig.pin))
    assert reason_of(lambda: rig.backbone.publish(rogue, transport_principal=PRODUCER))[0] == "SIGNATURE_INVALID"
    assert rig.topic_records() == 0
    rig.backbone.publish(signed, transport_principal=PRODUCER)
    assert rig.topic_records() == 1


def test_ncr_c5_001_transport_principal_binding(env: tuple[Any, ...]) -> None:
    """ADD v1.3 :379 and :199: ``effective_principal_id`` is bound to the transport principal;
    an external mismatch is ``QUARANTINED{PRINCIPAL_BINDING_MISMATCH}`` with an Audit Record."""
    rig = build_rig(*env)
    signed = rig.signed()
    code, _, _ = reason_of(lambda: rig.backbone.publish(signed, transport_principal=OTHER_PRINCIPAL))
    assert code == "PRINCIPAL_BINDING_MISMATCH"
    assert rig.topic_records() == 0
    [row] = [row for row in rig.rows("c5_quarantine") if row["event_id"] == signed.envelope.event_id]
    assert row["reason_code"] == "PRINCIPAL_BINDING_MISMATCH"
    assert any(record.record["reason_code"] == "PRINCIPAL_BINDING_MISMATCH" and record.record["outcome"] == "DENIED"
               for record in rig.audit_records())


# The C3 relay as a producer of the C5 admission boundary (ADD v1.3 :845: the admitted envelope
# realises the GovernedContext integrally and its digest is verifiable; :408-411: a marking
# reference resolves to the marking object whose digest it carries, otherwise DENY).

RELAY_MARKING = {
    "scheme_id": "urn:ocor:marking-scheme:poc",
    "labels": ["RESTRICTED"],
    "mandatory_markings": [],
    "caveats": [],
    "dissemination_controls": [],
    "permitted_purposes": ["urn:ocor:purpose:mission-planning"],
    "handling_instructions": [],
}
RELAY_MARKING_DIGEST = "sha256:" + hashlib.sha256(canonical_bytes(RELAY_MARKING)).hexdigest()


def commit_context(*, marking_ref: str = "urn:" + RELAY_MARKING_DIGEST) -> Any:
    from ocor_runtime.kernel.governed_context import GovernedContext

    return GovernedContext.from_mapping(
        {
            "tenant_id": "urn:ocor:tenant:alpha",
            "organization_id": "urn:ocor:organization:alpha",
            "domain_id": "urn:ocor:domain:mission",
            "compartments": ["urn:ocor:compartment:ops"],
            "classification_marking_ref": marking_ref,
            "purpose": "urn:ocor:purpose:mission-planning",
            "effective_principal_id": "urn:ocor:principal:analyst-1",
            "actor_chain": ["urn:ocor:principal:analyst-1", "urn:ocor:component:c6"],
            "ontology_release_digest": "urn:sha256:" + "1" * 64,
            "policy_bundle_digest": "urn:sha256:" + "2" * 64,
            "correlation_id": str(uuid.uuid4()),
        }
    )


def outbox_entry(*, revision: int = 1, context: Any = None) -> Any:
    """A committed C3 outbox entry with the canonical-state-committed payload of OCOR-DEV-REM-0050."""
    from ocor_runtime.c3.ports import OutboxEnvelope

    context = context or commit_context()
    state = {"status": "ASSESSED"}
    state_digest = "urn:sha256:" + hashlib.sha256(canonical_bytes(state)).hexdigest()
    commit_id = "urn:ocor:commit:sha256:" + uuid.uuid4().hex * 2
    event_id = "urn:ocor:event:sha256:" + uuid.uuid4().hex * 2
    aggregate_ref = f"urn:ocor:mission-object:{uuid.uuid4().hex}"
    payload = {
        "event_type": "canonical-state-committed", "commit_id": commit_id, "command_id": stable("command"),
        "action_instance_id": stable("action-instance"), "tenant_id": context.tenant_id,
        "aggregate_type": "MissionObject", "aggregate_ref": aggregate_ref, "from_revision": revision - 1,
        "to_revision": revision, "state": state, "state_digest": state_digest, "decision_ref": stable("decision"),
        "authority_ref": stable("authority"), "evidence_refs": [stable("evidence")],
        "gate_package_digest": "urn:sha256:" + "9" * 64, "governed_context_digest": context.digest(),
        "ontology_release_digest": context.ontology_release_digest,
        "boundary": {
            "tenant_id": context.tenant_id, "domain_id": context.domain_id, "compartments": list(context.compartments),
            "classification_marking_ref": context.classification_marking_ref, "purpose": context.purpose,
        },
        "actor_chain": list(context.actor_chain), "correlation_id": context.correlation_id,
        "causation_id": stable("action-instance"), "branch": "main", "governed_context": context.to_mapping(),
    }
    digest = "urn:sha256:" + hashlib.sha256(canonical_bytes(payload)).hexdigest()
    return OutboxEnvelope(event_id, commit_id, aggregate_ref, revision, payload, digest, "main", datetime.now(UTC))


@dataclass
class MarkingTable:
    """Explicit test port of the marking resolution (``GetProvenance`` in production)."""

    markings: dict[str, Any]

    def resolve(self, marking_ref: str) -> Any:
        if marking_ref not in self.markings:
            raise LookupError("unknown marking")
        return self.markings[marking_ref]


def resolvable() -> MarkingTable:
    return MarkingTable({"urn:" + RELAY_MARKING_DIGEST: {**RELAY_MARKING, "marking_digest": RELAY_MARKING_DIGEST}})


def relayed(entry: Any, markings: Any = None) -> Any:
    return importlib.import_module("ocor_runtime.c3.relay").canonical_event(
        entry, signer=_c5("envelope").ProducerSigner(PRODUCER, Ed25519SigningKey.from_seed(SEED)), principal=PRODUCER,
        markings=markings or resolvable(), ingest_time=datetime.now(UTC),
    )


def test_ncr_c5_001_relay_envelope_realises_the_commit_context() -> None:
    """ADD v1.3 :531-840, :845, :846 and :197/:844: the relayed envelope is a signed CDC
    ``canonical-ingestion-envelope:1.2`` that realises the commit context, with the relay's
    transport principal as effective principal; its payload passes the second validation."""
    entry = outbox_entry(revision=2)
    signed = relayed(entry)
    _c5("envelope").ProducerKeyring({PRODUCER: Ed25519SigningKey.from_seed(SEED).public_key}).verify(signed)
    value = signed.envelope.to_mapping()
    payload = json.loads(canonical_bytes(entry.payload))
    commit = payload["governed_context"]
    realised = {
        "tenant_id": value["tenant_id"], "organization_id": value["organization_id"], "domain_id": value["domain_id"],
        "compartments": value["compartments"],
        "classification_marking_ref": "urn:" + value["classification_marking"]["marking_digest"],
        "purpose": value["purpose"], "effective_principal_id": value["effective_principal_id"],
        "actor_chain": value["actor_chain"], "ontology_release_digest": "urn:" + value["ontology_release_digest"],
        "policy_bundle_digest": "urn:" + value["policy_bundle_digest"], "correlation_id": value["correlation_id"],
    }
    assert realised == {**commit, "effective_principal_id": PRODUCER, "actor_chain": [*commit["actor_chain"], PRODUCER]}
    assert "sha256:" + hashlib.sha256(canonical_bytes(realised)).hexdigest() == value["governed_context_digest"]
    assert value["classification_marking"] == {**RELAY_MARKING, "marking_digest": RELAY_MARKING_DIGEST}
    assert str(uuid.UUID(value["event_id"])) == value["event_id"] == relayed(entry).envelope.event_id
    assert value["idempotency_key"] == value["source"]["source_record_id"] == entry.event_id
    assert (value["ingest_mode"], value["semantic_class"]) == ("CDC", "CDC_CHANGE")
    assert value["transport"]["source_transaction_id"] == entry.commit_id
    assert value["transport"]["source_position"] == "2" and value["transport"]["operation"] == "UPDATE"
    assert value["aggregate"]["aggregate_id"] == entry.aggregate_ref and value["aggregate"]["expected_revision"] == 2
    assert value["payload"] == payload
    assert value["effective_principal_id"] == PRODUCER != commit["effective_principal_id"]
    registry = _c5("schema").SchemaRegistry()
    importlib.import_module("ocor_runtime.c3.relay").register_canonical_state_committed(registry)
    registration = registry.validate_payload(signed.envelope)
    assert registration.resource_class == _c5("operations").ResourceClass.CONTROL
    assert signed.envelope.governed_context().digest() == "urn:" + value["governed_context_digest"]


@pytest.mark.parametrize(
    "markings",
    [
        MarkingTable({}),
        MarkingTable({"urn:" + RELAY_MARKING_DIGEST: {**RELAY_MARKING, "marking_digest": "sha256:" + "c" * 64}}),
        MarkingTable({"urn:" + RELAY_MARKING_DIGEST: {**RELAY_MARKING, "labels": ["SECRET"],
                                                      "marking_digest": RELAY_MARKING_DIGEST}}),
        MarkingTable({"urn:" + RELAY_MARKING_DIGEST: ["not", "an", "object"]}),
    ],
    ids=["unresolvable", "digest-not-the-reference", "digest-not-the-object", "not-an-object"],
)
def test_ncr_c5_001_relay_denies_a_marking_that_does_not_resolve_to_its_reference(markings: MarkingTable) -> None:
    """ADD v1.3 :408-411: an unresolvable ``*_marking_ref``, or a ``marking_digest`` that does not
    match the object, is ``DENY``; nothing is signed or published."""
    from ocor_runtime.c3.ports import C3Error

    with pytest.raises(C3Error) as caught:
        relayed(outbox_entry(), markings)
    assert caught.value.reason_code == "MARKING_UNRESOLVED"


def test_ncr_c5_001_envelope_context_is_verifiable() -> None:
    """ADD v1.3 :845 and :411: an envelope whose marking digest does not match the marking, or
    whose fields do not reproduce ``governed_context_digest``, does not realise its context."""
    value = relayed(outbox_entry()).envelope.to_mapping()
    envelope = _c5("envelope")
    tampered_marking = {**value, "classification_marking": {**value["classification_marking"], "labels": ["SECRET"]}}
    tampered_purpose = {**value, "purpose": "urn:ocor:purpose:other"}
    for candidate in (tampered_marking, tampered_purpose):
        with pytest.raises(envelope.BackboneError) as caught:
            envelope.CanonicalIngestionEnvelope.from_mapping(candidate).governed_context()
        assert caught.value.reason_code == "GOVERNED_CONTEXT_MISMATCH"


# --------------------------------------------------------------------------------------------
# NCR-C5-002 -- failure taxonomy, Subscribe surface, authorised windowed replay
# --------------------------------------------------------------------------------------------


class FlakyJournal:
    """Fault-injection instrument over the real in-process journal: the next ``failures``
    appends raise the client's transient error before reaching the broker."""

    def __new__(cls, bootstrap_servers: str, topic: str) -> Any:
        kafka = _c5("kafka")

        class _Flaky(kafka.KafkaJournal):  # type: ignore[misc,name-defined]
            failures = 0
            appends = 0

            def append(self, *args: Any, **kwargs: Any) -> Any:
                self.appends += 1
                if self.failures > 0:
                    self.failures -= 1
                    raise kafka.KafkaJournalError("injected: broker unavailable before the write")
                return super().append(*args, **kwargs)

        return _Flaky(bootstrap_servers, topic)


def test_ncr_c5_002_conforms(broker: QualificationKafkaBroker, topic: str, dsn: str, schema_name: str) -> None:
    """LLD v1.1 :156-163 and Register :205 (FR-074): the four failure classes follow their
    declared paths with no infinite loop."""
    retry = _c5("retry")
    assert [member.value for member in retry.FailureClass] == ["TRANSIENT", "PERMANENT", "POLICY_DENIED", "POISON"]
    rig = build_rig(broker, topic, dsn, schema_name, journal_type=FlakyJournal, max_attempts=4)

    # TRANSIENT: exponential backoff with bounded jitter inside the retry budget
    rig.journal.failures = 2
    rig.backbone.publish(rig.signed(), transport_principal=PRODUCER)
    assert rig.sleeps == pytest.approx([0.075, 0.15])  # min(0.4, 0.05 * 2**k * (1 + 0.5 * rng)), rng = 1.0
    assert rig.topic_records() == 1
    # ... and a spent budget fails closed without a dead letter
    rig.journal.failures = 100
    before = rig.journal.appends
    signed = rig.signed()
    code, failure_class, _ = reason_of(lambda: rig.backbone.publish(signed, transport_principal=PRODUCER))
    assert (code, failure_class) == ("RETRY_BUDGET_EXHAUSTED", "TRANSIENT")
    assert rig.journal.appends - before == 4
    assert rig.sleeps[2:] == pytest.approx([0.075, 0.15, 0.3]) and all(delay <= 0.4 for delay in rig.sleeps)
    assert signed.envelope.event_id not in {row["event_id"] for row in rig.rows("c5_dead_letter")}
    rig.journal.failures = 0

    # PERMANENT: immutable DLQ, no automatic retry
    before = rig.journal.appends
    bad = rig.signed(payload={"status": 7})
    code, failure_class, _ = reason_of(lambda: rig.backbone.publish(bad, transport_principal=PRODUCER))
    assert failure_class == "PERMANENT" and rig.journal.appends == before
    assert [row["failure_class"] for row in rig.rows("c5_dead_letter") if row["event_id"] == bad.envelope.event_id] == [
        "PERMANENT"
    ]

    # POLICY_DENIED: audit and non-disclosing quarantine
    rig.policy.denied_publish_event_types.add(EVENT_TYPE)
    denied = rig.signed(payload={"status": "CONFIRMED"})
    code, failure_class, message = reason_of(lambda: rig.backbone.publish(denied, transport_principal=PRODUCER))
    assert (code, failure_class) == ("POLICY_DENIED", "POLICY_DENIED")
    assert denied.envelope.event_id not in message and EVENT_TYPE not in message and "CONFIRMED" not in message
    [row] = [row for row in rig.rows("c5_quarantine") if row["event_id"] == denied.envelope.event_id]
    assert row["failure_class"] == "POLICY_DENIED"
    assert any(record.record["reason_code"] == "POLICY_DENIED" for record in rig.audit_records())
    rig.policy.denied_publish_event_types.clear()
    assert rig.topic_records() == 1

    # POISON: partition quarantine and operator gate on delivery
    key = f"mission-object/{uuid.uuid4().hex}"
    poison, follower = rig.signed(ordering_key=key), rig.signed(ordering_key=key)
    rig.backbone.publish(poison, transport_principal=PRODUCER)
    rig.backbone.publish(follower, transport_principal=PRODUCER)
    subscription = rig.backbone.subscribe(subscription_contract(), principal=CONSUMER)
    handled: list[str] = []

    def handler(event: Any) -> None:
        if event.envelope.event_id == poison.envelope.event_id:
            raise RuntimeError("consumer cannot process this event")
        handled.append(event.envelope.event_id)

    outcome = rig.backbone.deliver(subscription, handler, cursor=None, max_records=3, timeout_s=20)
    assert poison.envelope.event_id in outcome.quarantined
    assert follower.envelope.event_id not in handled  # the partition is held behind the operator gate
    [row] = [row for row in rig.rows("c5_quarantine") if row["event_id"] == poison.envelope.event_id]
    assert row["failure_class"] == "POISON"
    code, _, _ = reason_of(lambda: rig.backbone.release_quarantine(row["quarantine_id"], operator=CONSUMER,
                                                                   authority_ref="urn:ocor:authority:none"))
    assert code == "OPERATOR_GATE_CLOSED"
    rig.backbone.release_quarantine(row["quarantine_id"], operator=OPERATOR, authority_ref="urn:ocor:authority:replay-ops")
    handled.clear()
    rig.backbone.deliver(subscription, lambda event: handled.append(event.envelope.event_id),
                         cursor=outcome.cursor, max_records=1, timeout_s=20)
    assert handled == [follower.envelope.event_id]


def test_ncr_c5_002_subscribe_surface_has_opaque_cursor(env: tuple[Any, ...]) -> None:
    """ADD v1.3 :2573-2575 and Register :79 (FR-016): ``Subscribe`` validates the Event
    Subscription Contract and moves by ``subscription_id`` and opaque cursor, never by broker
    partition or offset; the checkpoint is durable (LLD v1.1 :165)."""
    rig = build_rig(*env)
    subscription_module = _c5("subscription")
    assert subscription_module.SUBSCRIPTION_CONTRACT_SCHEMA == add_subscription_schema()
    bad = subscription_contract()
    bad["delivery"]["semantics"] = "EXACTLY_ONCE"
    assert reason_of(lambda: rig.backbone.subscribe(bad, principal=CONSUMER))[0] == "SCHEMA_VIOLATION"

    sent = [rig.signed() for _ in range(3)]
    for signed in sent:
        rig.backbone.publish(signed, transport_principal=PRODUCER)
    subscription = rig.backbone.subscribe(subscription_contract(), principal=CONSUMER)
    first = rig.backbone.poll(subscription, cursor=None, max_records=2, timeout_s=20)
    assert len(first.events) == 2
    for event in first.events:
        assert not hasattr(event, "partition") and not hasattr(event, "offset")
        assert event.subscription_id == subscription
    assert isinstance(first.cursor, str) and re.fullmatch(r"[A-Za-z0-9_-]{32,}", first.cursor)
    assert "offset" not in first.cursor and "partition" not in first.cursor
    [checkpoint] = [row for row in rig.rows("c5_checkpoint") if row["cursor_id"] == first.cursor]
    assert checkpoint["topic"] == rig.topic and checkpoint["governed_context_digest"]
    assert checkpoint["schema_registry_digest"].startswith("sha256:") and checkpoint["release_digest"]

    restarted = build_rig(rig.broker, rig.topic, rig.dsn, rig.schema)  # durable checkpoint, new process state
    rest = restarted.backbone.poll(subscription, cursor=first.cursor, max_records=5, timeout_s=20)
    delivered = [event.envelope.event_id for event in (*first.events, *rest.events)]
    assert sorted(delivered) == sorted(signed.envelope.event_id for signed in sent)
    assert reason_of(lambda: rig.backbone.poll(subscription, cursor="0" * 43, max_records=1, timeout_s=1))[0] == (
        "CURSOR_EXPIRED"
    )


def test_ncr_c5_002_replay_is_authorised_windowed_and_never_republishes(env: tuple[Any, ...]) -> None:
    """LLD v1.1 :165 and Register :202 (FR-072): replay declares window and reason, needs
    authorisation, preserves event ID, schema and provenance, re-evaluates policy and never
    publishes a canonical effect twice."""
    rig = build_rig(*env)
    replay = _c5("replay")
    sent = [rig.signed() for _ in range(3)]
    for signed in sent:
        rig.backbone.publish(signed, transport_principal=PRODUCER)
    records_before = rig.topic_records()
    subscription = rig.backbone.subscribe(subscription_contract(), principal=CONSUMER)
    now = datetime.now(UTC)

    def request(**overrides: Any) -> Any:
        values = {
            "subscription_id": subscription, "window_start": now - timedelta(hours=1), "window_end": now + timedelta(minutes=5),
            "reason": "rebuild of the C4 projection after drift", "requested_by": OPERATOR,
            "authority_ref": "urn:ocor:authority:replay-ops",
        }
        values.update(overrides)
        return replay.ReplayRequest(**values)

    assert reason_of(lambda: rig.backbone.replay(request(requested_by=CONSUMER)))[0] == "REPLAY_DENIED"
    assert reason_of(lambda: rig.backbone.replay(request(reason="")))[0] == "REPLAY_DENIED"
    assert reason_of(lambda: rig.backbone.replay(request(window_start=now - timedelta(days=3))))[0] == "REPLAY_DENIED"
    closed = rig.backbone.subscribe(subscription_contract(replay_allowed=False), principal=CONSUMER)
    assert reason_of(lambda: rig.backbone.replay(request(subscription_id=closed)))[0] == "REPLAY_DENIED"

    rig.policy.denied_delivery_event_ids.add(sent[1].envelope.event_id)  # policy re-evaluated on replay
    cursor = rig.backbone.replay(request())
    batch = rig.backbone.poll(subscription, cursor=cursor, max_records=5, timeout_s=20)
    replayed = {event.envelope.event_id: event.envelope.to_mapping() for event in batch.events}
    assert replayed == {signed.envelope.event_id: signed.envelope.to_mapping()
                        for signed in (sent[0], sent[2])}
    assert rig.topic_records() == records_before  # replay re-delivers, it never republishes
    assert any(record.record["event_type"] == "c5.replay" for record in rig.audit_records())


# --------------------------------------------------------------------------------------------
# NCR-C5-003 -- priority-class backpressure with audit/security exemption, durable DLQ
# --------------------------------------------------------------------------------------------


class HeldJournal:
    """Observation instrument over the real in-process journal: while ``hold`` is set, every
    append waits until ``release`` is set, so admitted publishes stay in flight."""

    def __new__(cls, bootstrap_servers: str, topic: str) -> Any:
        kafka = _c5("kafka")

        class _Held(kafka.KafkaJournal):  # type: ignore[misc,name-defined]
            hold = threading.Event()
            release = threading.Event()
            entered = threading.Semaphore(0)

            def append(self, *args: Any, **kwargs: Any) -> Any:
                if type(self).hold.is_set():
                    type(self).entered.release()
                    type(self).release.wait(timeout=30)
                return super().append(*args, **kwargs)

        return _Held(bootstrap_servers, topic)


def test_ncr_c5_003_conforms(broker: QualificationKafkaBroker, topic: str, dsn: str, schema_name: str) -> None:
    """LLD v1.1 :165 and :338, Register :406 (NFR-079): quotas per tenant and ResourceClass;
    batch saturation never starves control; audit/security are never dropped; refusals keep
    authentication, policy and audit."""
    operations = _c5("operations")
    assert [member.value for member in operations.ResourceClass] == ["CONTROL", "INTERACTIVE", "BATCH", "AUDIT"]
    rig = build_rig(broker, topic, dsn, schema_name, journal_type=HeldJournal,
                    quotas={"CONTROL": 1, "INTERACTIVE": 1, "BATCH": 1, "AUDIT": 1})
    errors: list[BaseException] = []

    def background(signed: Any) -> threading.Thread:
        def run() -> None:
            try:
                rig.backbone.publish(signed, transport_principal=PRODUCER)
            except BaseException as error:  # noqa: BLE001 -- asserted below
                errors.append(error)
        thread = threading.Thread(target=run)
        thread.start()
        return thread

    rig.journal.hold.set()
    held = [background(rig.signed()), background(rig.signed(event_type=AUDIT_EVENT_TYPE))]
    assert rig.journal.entered.acquire(timeout=30) and rig.journal.entered.acquire(timeout=30)
    # BATCH of tenant alpha is at quota: refused, audited
    refused = rig.signed()
    assert reason_of(lambda: rig.backbone.publish(refused, transport_principal=PRODUCER))[0] == "BACKPRESSURE_EXCEEDED"
    assert any(record.record["reason_code"] == "BACKPRESSURE_EXCEEDED" for record in rig.audit_records())
    # another tenant has its own quota; CONTROL does not share the BATCH pool
    other_tenant = background(rig.signed(tenant="urn:ocor:tenant:bravo"))
    control = background(rig.signed(event_type=CONTROL_EVENT_TYPE))
    # AUDIT at quota is still admitted: never dropped
    audit_over_quota = background(rig.signed(event_type=AUDIT_EVENT_TYPE))
    for _ in range(3):
        assert rig.journal.entered.acquire(timeout=30), "an admitted publish never reached the journal"
    # under saturation the checks still run: an unauthenticated AUDIT event is refused
    forged = rig.signed(event_type=AUDIT_EVENT_TYPE)
    assert reason_of(lambda: rig.backbone.publish(forged, transport_principal=OTHER_PRINCIPAL))[0] == (
        "PRINCIPAL_BINDING_MISMATCH"
    )
    rig.journal.hold.clear()
    rig.journal.release.set()
    for thread in (*held, other_tenant, control, audit_over_quota):
        thread.join(timeout=60)
    assert errors == []
    assert rig.topic_records() == 5


def test_ncr_c5_003_dead_letters_are_durable_and_immutable(env: tuple[Any, ...]) -> None:
    """LLD v1.1 :161: ``PERMANENT`` -> immutable DLQ, durable on PostgreSQL across processes."""
    rig = build_rig(*env)
    bad = rig.signed(payload={"status": "UNKNOWN"})
    reason_of(lambda: rig.backbone.publish(bad, transport_principal=PRODUCER))
    restarted = build_rig(rig.broker, rig.topic, rig.dsn, rig.schema)
    [letter] = [letter for letter in restarted.backbone.dead_letters() if letter.event_id == bad.envelope.event_id]
    assert letter.failure_class == "PERMANENT" and letter.reason_code == "SCHEMA_VIOLATION"
    with pytest.raises(TypeError):
        letter.envelope["payload"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        letter.envelope["payload"]["status"] = "CONFIRMED"
    with psycopg.connect(rig.dsn, autocommit=True) as connection:
        for statement in (
            f'UPDATE "{rig.schema}".c5_dead_letter SET reason_code = %s',  # noqa: S608
            f'DELETE FROM "{rig.schema}".c5_dead_letter WHERE reason_code <> %s',  # noqa: S608
        ):
            with pytest.raises(psycopg.errors.RaiseException):
                connection.execute(statement, ("TAMPERED",))
    assert [row["reason_code"] for row in rig.rows("c5_dead_letter")] == ["SCHEMA_VIOLATION"]
