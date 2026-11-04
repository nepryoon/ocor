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
  (``QUARANTINED{reason=PRINCIPAL_BINDING_MISMATCH}`` with an Audit Record); ADD v1.3 :402-411
  (the inline marking is resolved at the C5 admission boundary; a ``marking_digest`` that does
  not match the object is ``DENY``); LLD v1.1 :154
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
# the correlation of the test context: ``correlation_id`` is a field of the GovernedContext
# record (ADD v1.3 :845), so the envelopes of one context share it
CORRELATION = "6f1c2d4e-8a3b-4c5d-9e6f-7a8b9c0d1e2f"
# a well-formed digest that no envelope of these cases reproduces
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
    """An inline marking object carrying its own digest (ADD v1.3 :408-411): the sha256 of the
    RFC 8785 bytes of the object without ``marking_digest``."""
    value: dict[str, Any] = {
        "scheme_id": "urn:ocor:marking-scheme:poc",
        "labels": ["RESTRICTED"],
        "mandatory_markings": [],
        "caveats": [],
        "dissemination_controls": [],
        "permitted_purposes": ["urn:ocor:purpose:mission-planning"],
        "handling_instructions": [],
    }
    value["marking_digest"] = "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()
    return value


def raw_envelope(
    *,
    mode: str = "STREAM",
    event_type: str = EVENT_TYPE,
    payload: dict[str, Any] | None = None,
    ordering_key: str | None = None,
    tenant: str = "urn:ocor:tenant:alpha",
    gcs: str | None = None,
    principal: str = PRODUCER,
    expected_revision: int | None = None,
    ingest_time: datetime | None = None,
    pin: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A complete ``canonical-ingestion-envelope:1.2`` (ADD v1.3 :531-840) before signing; its
    ``governed_context_digest`` is the digest of the GovernedContext its fields realise, unless
    ``gcs`` names another one."""
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
    value: dict[str, Any] = {
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
        "governed_context_digest": OTHER_GCS,
        "ontology_release_digest": "sha256:" + "1" * 64,
        "policy_bundle_digest": "sha256:" + "2" * 64,
        "correlation_id": CORRELATION,
        "causation_id": None,
        "transport": transport,
    }
    value["governed_context_digest"] = context_digest_of(value) if gcs is None else gcs
    return value


def context_digest_of(value: dict[str, Any]) -> str:
    """The ``sha256:`` digest of the RFC 8785 bytes of the GovernedContext record that the fields
    of an envelope realise (ADD v1.3 :845), computed here, not by the module under test: the
    inline marking as ``urn:`` + its ``marking_digest``, the digests in their ``urn:sha256:`` form."""
    realised = {
        "tenant_id": value["tenant_id"], "organization_id": value["organization_id"], "domain_id": value["domain_id"],
        "compartments": value["compartments"],
        "classification_marking_ref": "urn:" + value["classification_marking"]["marking_digest"],
        "purpose": value["purpose"], "effective_principal_id": value["effective_principal_id"],
        "actor_chain": value["actor_chain"], "ontology_release_digest": "urn:" + value["ontology_release_digest"],
        "policy_bundle_digest": "urn:" + value["policy_bundle_digest"], "correlation_id": value["correlation_id"],
    }
    return "sha256:" + hashlib.sha256(canonical_bytes(realised)).hexdigest()


# the GovernedContext of the default test envelope: tenant alpha, producer principal
GCS = context_digest_of(raw_envelope())


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
    kafka = _c5("adapters.kafka")
    dlq = _c5("adapters.postgres")
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
        "governed_context_ref": "urn:" + GCS,
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


def test_ncr_c5_001_admission_denies_a_marking_digest_that_does_not_match_the_marking(env: tuple[Any, ...]) -> None:
    """ADD v1.3 :402-411: at the C5 admission boundary of ingestion the inline marking is resolved
    to ``classification_marking_ref``; a ``marking_digest`` that does not match the object is
    ``DENY``, never a permissive posture; an external mismatch is quarantined with an Audit Record
    (ADD v1.3 :406, :199 ``GOVERNED_CONTEXT_MISMATCH``). ADD v1.3 :845: the admitted envelope
    realises the GovernedContext."""
    rig = build_rig(*env)
    envelope = _c5("envelope")
    raw = raw_envelope(pin=rig.pin)
    raw["classification_marking"] = {**raw["classification_marking"], "labels": ["SECRET"]}
    signed = rig.signer.sign(raw)
    code, failure_class, _ = reason_of(lambda: rig.backbone.publish(signed, transport_principal=PRODUCER))
    assert (code, failure_class) == ("GOVERNED_CONTEXT_MISMATCH", "POLICY_DENIED")
    assert rig.topic_records() == 0
    [row] = [row for row in rig.rows("c5_quarantine") if row["event_id"] == signed.envelope.event_id]
    assert row["reason_code"] == "GOVERNED_CONTEXT_MISMATCH"
    assert any(record.record["reason_code"] == "GOVERNED_CONTEXT_MISMATCH" and record.record["outcome"] == "DENIED"
               for record in rig.audit_records())
    valid = rig.signed()
    assert valid.envelope["classification_marking"]["marking_digest"] == envelope.marking_digest(
        valid.envelope["classification_marking"])
    rig.backbone.publish(valid, transport_principal=PRODUCER)
    assert rig.topic_records() == 1


def test_ncr_c5_001_admission_denies_a_governed_context_digest_the_envelope_does_not_reproduce(
    env: tuple[Any, ...],
) -> None:
    """ADD v1.3 :845 (the admitted envelope realises the GovernedContext integrally and its digest
    is verifiable), :199 and :379: an envelope whose fields do not reproduce
    ``governed_context_digest`` -- another tenant claiming the context of tenant alpha, or a
    digest of no context -- is ``QUARANTINED{GOVERNED_CONTEXT_MISMATCH}`` with an Audit Record,
    never published, so it is never deduplicated or delivered under the context it claims."""
    rig = build_rig(*env)
    claimed = rig.signed(tenant="urn:ocor:tenant:bravo", gcs=GCS)
    unrelated = rig.signed(gcs=OTHER_GCS)
    for signed in (claimed, unrelated):
        code, failure_class, _ = reason_of(lambda signed=signed: rig.backbone.publish(signed, transport_principal=PRODUCER))
        assert (code, failure_class) == ("GOVERNED_CONTEXT_MISMATCH", "POLICY_DENIED")
    assert rig.topic_records() == 0
    rows = {row["event_id"]: (row["reason_code"], row["failure_class"]) for row in rig.rows("c5_quarantine")}
    assert rows == {
        claimed.envelope.event_id: ("GOVERNED_CONTEXT_MISMATCH", "POLICY_DENIED"),
        unrelated.envelope.event_id: ("GOVERNED_CONTEXT_MISMATCH", "POLICY_DENIED"),
    }
    denials = [record for record in rig.audit_records()
               if record.record["reason_code"] == "GOVERNED_CONTEXT_MISMATCH" and record.record["outcome"] == "DENIED"]
    assert len(denials) == 2
    valid = rig.signed(tenant="urn:ocor:tenant:bravo")
    assert valid.envelope.governed_context_digest == context_digest_of(valid.envelope.to_mapping()) != GCS
    rig.backbone.publish(valid, transport_principal=PRODUCER)
    assert rig.topic_records() == 1


def plant(rig: Rig, signed: Any) -> None:
    """Write a signed envelope on the journal out of band, bypassing the admission boundary, with
    the in-process client and the record layout of the backbone."""
    backbone = _c5("backbone")
    rig.journal.append(
        key=signed.envelope.ordering_key.encode("utf-8"), value=signed.envelope.canonical_bytes(),
        headers=[(backbone.SIGNATURE_HEADER, signed.signature), (backbone.VERSION_HEADER, b"1.2")],
        timestamp_ms=int(signed.envelope.ingest_time.timestamp() * 1000),
    )


def test_ncr_c5_001_journal_records_are_reverified_against_their_governed_context(env: tuple[Any, ...]) -> None:
    """ADD v1.3 :845 and :380-381 (delivery is authorised per governed context): a record that
    reached the journal out of band with a valid producer signature, but whose fields do not
    reproduce the ``governed_context_digest`` of the subscription it claims, is never delivered:
    its partition is quarantined ``POISON`` with ``GOVERNED_CONTEXT_MISMATCH`` (LLD v1.1 :163);
    a new process rebuilding deduplication from that journal fails closed (``JOURNAL_UNREADABLE``)."""
    rig = build_rig(*env)
    valid = rig.signed()
    rig.backbone.publish(valid, transport_principal=PRODUCER)
    forged = rig.signed(tenant="urn:ocor:tenant:bravo", gcs=GCS)
    plant(rig, forged)
    assert rig.topic_records() == 2

    subscription = rig.backbone.subscribe(subscription_contract(), principal=CONSUMER)
    batch = rig.backbone.poll(subscription, cursor=None, max_records=10, timeout_s=20)
    assert [event.envelope.event_id for event in batch.events] == [valid.envelope.event_id]
    poisoned = [row for row in rig.rows("c5_quarantine") if row["subscription_id"] == subscription]
    assert [(row["reason_code"], row["failure_class"]) for row in poisoned] == [("GOVERNED_CONTEXT_MISMATCH", "POISON")]

    restarted = build_rig(rig.broker, rig.topic, rig.dsn, rig.schema)
    code, failure_class, _ = reason_of(lambda: restarted.backbone.publish(rig.signed(), transport_principal=PRODUCER))
    assert (code, failure_class) == ("JOURNAL_UNREADABLE", "PERMANENT")
    assert rig.topic_records() == 2


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
        kafka = _c5("adapters.kafka")

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
        kafka = _c5("adapters.kafka")

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


# --------------------------------------------------------------------------------------------
# Input robustness of the C5 adapters (PRE-REVIEW-INPUT-ROBUSTNESS (2026-10-29)): the shape of
# every answer of the broker client and of the database is verified without coercion, every
# anomaly is the typed error of the adapter, tampered data is refused. Local responders stand in
# for the client and the connection; the external services are not changed.
# --------------------------------------------------------------------------------------------


class FakeKafkaError:
    """A client error object of the shape the confluent-kafka client answers."""

    def __init__(self, code: int) -> None:
        self._code = code

    def code(self) -> int:
        return self._code

    def __str__(self) -> str:
        return f"fake-kafka-error-{self._code}"


class FakeMessage:
    def __init__(self, *, partition: Any = 0, offset: Any = 0, key: Any = b"k", value: Any = b"{}",
                 headers: Any = None, timestamp: Any = (1, 1000), error: Any = None) -> None:
        self._values = {"partition": partition, "offset": offset, "key": key, "value": value, "headers": headers,
                        "timestamp": timestamp, "error": error}

    def __getattr__(self, name: str) -> Any:
        values = self.__dict__["_values"]
        if name not in values:
            raise AttributeError(name)
        return lambda: values[name]


RESPONDER_TOPIC = "ocor-rem0051-responder"


def topic_metadata(partitions: Any = None, *, error: Any = None, topic: str = RESPONDER_TOPIC) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(topics={topic: SimpleNamespace(error=error, partitions={0: None} if partitions is None
                                                          else partitions)})


class FakeConsumer:
    """Local responder of the consumer surface used by the journal."""

    def __init__(self, *, metadata: Any = "default", watermarks: Any = (0, 1), times: Any = None,
                 messages: tuple[Any, ...] = (), raises: BaseException | None = None) -> None:
        self.metadata = topic_metadata() if metadata == "default" else metadata
        self.watermarks = watermarks
        self.times = times
        self.messages = list(messages)
        self.raises = raises

    def list_topics(self, timeout: float) -> Any:
        if self.raises is not None:
            raise self.raises
        return self.metadata

    def get_watermark_offsets(self, partition: Any, timeout: float) -> Any:
        return self.watermarks

    def offsets_for_times(self, partitions: Any, timeout: float) -> Any:
        return self.times

    def assign(self, partitions: Any) -> None:
        return None

    def poll(self, timeout: float) -> Any:
        return self.messages.pop(0) if self.messages else None

    def close(self) -> None:
        return None


class FakeProducer:
    """Local responder of the producer surface: the delivery callback answers ``message``."""

    def __init__(self, message: Any, error: Any = None) -> None:
        self.message = message
        self.error = error
        self.callback: Any = None

    def produce(self, topic: str, **kwargs: Any) -> None:
        self.callback = kwargs["on_delivery"]

    def flush(self, timeout: float) -> int:
        if self.callback is not None:
            self.callback(self.error, self.message)
            self.callback = None
        return 0

    def purge(self) -> None:
        return None


def responder_journal(consumer: FakeConsumer | None = None, producer: FakeProducer | None = None) -> Any:
    kafka = _c5("adapters.kafka")
    answers = consumer if consumer is not None else FakeConsumer()

    class _Responder(kafka.KafkaJournal):  # type: ignore[misc,name-defined]
        def _consumer(self) -> Any:
            return answers

        def _producer_instance(self) -> Any:
            return producer

    return _Responder("127.0.0.1:9", RESPONDER_TOPIC)


def journal_error(call: Any) -> str:
    """Run ``call``; it must raise the typed error of the journal adapter, nothing else."""
    kafka = _c5("adapters.kafka")
    with pytest.raises(kafka.KafkaJournalError) as excinfo:
        call()
    return str(excinfo.value)


@pytest.mark.parametrize(
    "consumer",
    [
        FakeConsumer(raises=__import__("confluent_kafka").KafkaException(FakeKafkaError(-195))),
        FakeConsumer(metadata=None),
        FakeConsumer(metadata=topic_metadata({})),
        FakeConsumer(metadata=topic_metadata({True: None})),
        FakeConsumer(metadata=topic_metadata({-1: None})),
        FakeConsumer(metadata=topic_metadata({"0": None})),
        FakeConsumer(metadata=topic_metadata(error=FakeKafkaError(3))),
        FakeConsumer(metadata=topic_metadata(topic="another-topic")),
        FakeConsumer(metadata=type("Metadata", (), {"topics": None})()),
    ],
    ids=["protocol-error", "null-metadata", "empty-partitions", "bool-partition", "negative-partition",
         "string-partition", "topic-error", "topic-absent", "null-topics"],
)
def test_kafka_journal_partitions_refuse_malformed_metadata(consumer: FakeConsumer) -> None:
    journal_error(responder_journal(consumer).partitions)


def test_kafka_journal_partitions_accept_well_formed_metadata() -> None:
    assert responder_journal(FakeConsumer(metadata=topic_metadata({1: None, 0: None}))).partitions() == (0, 1)


@pytest.mark.parametrize(
    ("message", "error"),
    [
        (FakeMessage(partition=None, offset=0), None),
        (FakeMessage(partition=True, offset=0), None),
        (FakeMessage(partition=0, offset=-1001), None),
        (FakeMessage(partition=0, offset=None), None),
        (FakeMessage(partition=0, offset="3"), None),
        (FakeMessage(partition=0.0, offset=3), None),
        (None, None),
        (FakeMessage(partition=0, offset=3), FakeKafkaError(-185)),
    ],
    ids=["null-partition", "bool-partition", "invalid-offset", "null-offset", "string-offset", "float-partition",
         "null-message", "delivery-error"],
)
def test_kafka_journal_append_refuses_a_malformed_acknowledgement(message: Any, error: Any) -> None:
    journal = responder_journal(producer=FakeProducer(message, error))
    journal_error(lambda: journal.append(key=b"k", value=b"{}", headers=[], timestamp_ms=1))


def test_kafka_journal_append_returns_a_well_formed_position() -> None:
    journal = responder_journal(producer=FakeProducer(FakeMessage(partition=2, offset=7)))
    assert journal.append(key=b"k", value=b"{}", headers=[], timestamp_ms=1) == (2, 7)


@pytest.mark.parametrize(
    "marks",
    [None, (0,), (0, 1, 2), (True, 1), (0, False), (-1, 1), (2, 1), ("0", "1"), [0, 1.0], {}],
    ids=["null", "short", "long", "bool-low", "bool-high", "negative", "inverted", "strings", "float", "empty-dict"],
)
def test_kafka_journal_watermarks_refuse_malformed_offsets(marks: Any) -> None:
    journal_error(responder_journal(FakeConsumer(watermarks=marks)).watermarks)


def test_kafka_journal_watermarks_accept_well_formed_offsets() -> None:
    assert responder_journal(FakeConsumer(watermarks=(0, 3))).watermarks() == {0: (0, 3)}


def time_entry(partition: Any = 0, offset: Any = 1, error: Any = None) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(partition=partition, offset=offset, error=error)


@pytest.mark.parametrize(
    "times",
    [
        None,
        [],
        [time_entry(offset=None)],
        [time_entry(offset=True)],
        [time_entry(offset=-5)],
        [time_entry(offset="1")],
        [time_entry(partition=7, offset=-1)],
        [time_entry(partition=True)],
        [time_entry(), time_entry()],
        [time_entry(error=FakeKafkaError(-185))],
        [None],
    ],
    ids=["null", "empty", "null-offset", "bool-offset", "negative-offset", "string-offset", "unknown-partition",
         "bool-partition", "duplicate-partition", "entry-error", "null-entry"],
)
def test_kafka_journal_offsets_for_time_refuse_malformed_answers(times: Any) -> None:
    journal = responder_journal(FakeConsumer(watermarks=(0, 3), times=times))
    journal_error(lambda: journal.offsets_for_time(1000))


def test_kafka_journal_offsets_for_time_accept_well_formed_answers() -> None:
    assert responder_journal(FakeConsumer(watermarks=(0, 3), times=[time_entry(offset=1)])).offsets_for_time(1) == {0: 1}
    assert responder_journal(FakeConsumer(watermarks=(0, 3), times=[time_entry(offset=-1)])).offsets_for_time(1) == {0: 3}


EOF = __import__("confluent_kafka").KafkaError._PARTITION_EOF  # noqa: SLF001 -- the client's end-of-partition code


@pytest.mark.parametrize(
    ("start", "end", "messages"),
    [
        ({}, {0: 1}, ()),
        ({0: -1}, {0: 1}, ()),
        ({0: True}, {0: 1}, ()),
        ({0: 0}, {0: "1"}, ()),
        ({0: 0}, {0: 1}, (FakeMessage(timestamp=None),)),
        ({0: 0}, {0: 1}, (FakeMessage(timestamp=(1,)),)),
        ({0: 0}, {0: 1}, (FakeMessage(timestamp=(1, True)),)),
        ({0: 0}, {0: 1}, (FakeMessage(timestamp=(1, -1)),)),
        ({0: 0}, {0: 1}, (FakeMessage(timestamp=(1, 1.5)),)),
        ({0: 0}, {0: 1}, (FakeMessage(partition=True),)),
        ({0: 0}, {0: 1}, (FakeMessage(offset=-1),)),
        ({0: 0}, {0: 1}, (FakeMessage(offset=None),)),
        ({0: 0}, {0: 1}, (FakeMessage(key="text"),)),
        ({0: 0}, {0: 1}, (FakeMessage(value="text"),)),
        ({0: 0}, {0: 1}, (FakeMessage(headers={"ocor-c5-signature": b"x"}),)),
        ({0: 0}, {0: 1}, (FakeMessage(headers=[("ocor-c5-signature", "text")]),)),
        ({0: 0}, {0: 1}, (FakeMessage(headers=[("ocor-c5-signature", b"x", b"y")]),)),
        ({0: 0}, {0: 1}, (FakeMessage(headers=[(None, b"x")]),)),
        ({0: 0}, {0: 1}, (FakeMessage(error=FakeKafkaError(-191)),)),
        ({0: 0}, {0: 1}, ()),
    ],
    ids=["start-missing", "start-negative", "start-bool", "end-string", "null-timestamp", "short-timestamp",
         "bool-timestamp", "negative-timestamp", "float-timestamp", "bool-partition", "negative-offset",
         "null-offset", "string-key", "string-value", "headers-not-a-list", "string-header-value",
         "long-header", "null-header-name", "protocol-error", "timeout"],
)
def test_kafka_journal_read_refuses_malformed_records(start: Any, end: Any, messages: tuple[Any, ...]) -> None:
    journal = responder_journal(FakeConsumer(messages=messages))
    journal_error(lambda: journal.read(start, end))


def test_kafka_journal_read_keeps_absent_fields_absent() -> None:
    """A record without key, value or header value (a Kafka tombstone, a null header) is returned
    as such, never coerced to empty bytes; the backbone judges it unreadable."""
    message = FakeMessage(key=None, value=None, headers=[("ocor-c5-signature", None)])
    [record] = responder_journal(FakeConsumer(messages=(message,))).read({0: 0}, {0: 1})
    assert (record.key, record.value, record.headers, record.timestamp_ms) == (None, None, (("ocor-c5-signature", None),), 1000)
    assert record.header("ocor-c5-signature") is None
    [plain] = responder_journal(FakeConsumer(messages=(FakeMessage(),))).read({0: 0}, {0: 1})
    assert (plain.partition, plain.offset, plain.key, plain.value, plain.headers) == (0, 0, b"k", b"{}", ())


@pytest.mark.parametrize(
    "body",
    [b"\xff\xfe\x00not-utf-8", b"null", b"{}", b"[]", None],
    ids=["non-utf-8", "json-null", "empty-object", "array", "tombstone"],
)
def test_ncr_c5_002_journal_records_with_malformed_bodies_fail_closed(env: tuple[Any, ...], body: bytes | None) -> None:
    """LLD v1.1 :163 and :165: a journal record whose body is not a canonical envelope (not UTF-8,
    JSON null, an empty object, an array, a tombstone) is never delivered -- its partition is
    quarantined ``POISON`` for the subscription -- and a new process fails closed on it."""
    rig = build_rig(*env)
    signed = rig.signed()
    backbone = _c5("backbone")
    rig.journal.append(key=b"foreign", value=body, headers=[(backbone.SIGNATURE_HEADER, signed.signature)],
                       timestamp_ms=int(datetime.now(UTC).timestamp() * 1000))
    assert rig.topic_records() == 1
    subscription = rig.backbone.subscribe(subscription_contract(), principal=CONSUMER)
    batch = rig.backbone.poll(subscription, cursor=None, max_records=10, timeout_s=20)
    assert batch.events == ()
    poisoned = [row for row in rig.rows("c5_quarantine") if row["subscription_id"] == subscription]
    assert [(row["reason_code"], row["failure_class"]) for row in poisoned] == [("SCHEMA_VIOLATION", "POISON")]
    code, failure_class, _ = reason_of(lambda: rig.backbone.publish(signed, transport_principal=PRODUCER))
    assert (code, failure_class) == ("JOURNAL_UNREADABLE", "PERMANENT")
    assert rig.topic_records() == 1


class RowResponder:
    """Local responder of the PostgreSQL connection: each statement answers the next row list."""

    def __init__(self, answers: list[list[Any]]) -> None:
        self.answers = list(answers)
        self.current: list[Any] = []

    def execute(self, *args: Any, **kwargs: Any) -> RowResponder:
        self.current = self.answers.pop(0) if self.answers else []
        return self

    def fetchall(self) -> list[Any]:
        return list(self.current)

    def fetchone(self) -> Any:
        return self.current[0] if self.current else None


def responder_store(*answers: list[Any]) -> Any:
    dlq = _c5("adapters.postgres")

    class _Responder(dlq.PostgresC5Store):  # type: ignore[misc,name-defined]
        def _run(self, work: Any) -> Any:
            return work(RowResponder(list(answers)))

    return _Responder("postgresql://responder.invalid/ocor", schema="ocor_rem0051_responder")


def store_error(call: Any) -> None:
    """Run ``call``; it must raise the typed error of the store (``CONTROL_PLANE_UNAVAILABLE``)."""
    code, failure_class, _ = reason_of(call)
    assert (code, failure_class) == ("CONTROL_PLANE_UNAVAILABLE", "TRANSIENT")


AWARE = datetime(2026, 11, 4, 1, 0, tzinfo=UTC)
NAIVE = datetime(2026, 11, 4, 1, 0)
DEAD_LETTER_ROW = {
    "dead_letter_id": "dl-1", "event_id": "event-1", "failure_class": "PERMANENT", "reason_code": "SCHEMA_VIOLATION",
    "envelope": {"event_id": "event-1"}, "signature": None, "attempt": 1, "recorded_at": AWARE,
}


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("envelope", {}), ("envelope", None), ("envelope", []), ("envelope", "text"),
        ("failure_class", "INVALID_CLASS"), ("failure_class", None), ("failure_class", "POLICY_DENIED"),
        ("attempt", 0), ("attempt", -5), ("attempt", True), ("attempt", "1"), ("attempt", None),
        ("recorded_at", NAIVE), ("recorded_at", None), ("recorded_at", "2026-11-04T01:00:00Z"),
        ("signature", "text"), ("dead_letter_id", ""), ("event_id", 5), ("reason_code", None),
    ],
)
def test_c5_store_dead_letters_refuse_malformed_rows(column: str, value: Any) -> None:
    store_error(lambda: responder_store([{**DEAD_LETTER_ROW, column: value}]).dead_letters("topic"))


def test_c5_store_dead_letters_accept_well_formed_rows() -> None:
    [letter] = responder_store([DEAD_LETTER_ROW]).dead_letters("topic")
    assert (letter.event_id, letter.failure_class, letter.attempts) == ("event-1", "PERMANENT", 1)


@pytest.mark.parametrize(
    "answers",
    [
        [[], [], [{"recorded_at": AWARE}]],
        [[], [{"n": None}], [{"recorded_at": AWARE}]],
        [[], [{"n": True}], [{"recorded_at": AWARE}]],
        [[], [{"n": -1}], [{"recorded_at": AWARE}]],
        [[], [{"n": "2"}], [{"recorded_at": AWARE}]],
        [[], [{}], [{"recorded_at": AWARE}]],
        [[], [{"n": 0}], []],
        [[], [{"n": 0}], [{"recorded_at": NAIVE}]],
    ],
    ids=["no-count-row", "null-count", "bool-count", "negative-count", "string-count", "count-missing",
         "insert-unconfirmed", "naive-time"],
)
def test_c5_store_record_dead_letter_refuses_malformed_answers(answers: list[list[Any]]) -> None:
    store = responder_store(*answers)
    store_error(lambda: store.record_dead_letter(event_id="event-1", topic="topic", tenant_id="tenant",
                                                 reason_code="SCHEMA_VIOLATION", envelope={"event_id": "event-1"},
                                                 signature=None, poison_threshold=3))


def test_c5_store_record_dead_letter_accepts_well_formed_answers() -> None:
    store = responder_store([], [{"n": 2}], [{"recorded_at": AWARE}])
    letter = store.record_dead_letter(event_id="event-1", topic="topic", tenant_id="tenant", reason_code="SCHEMA_VIOLATION",
                                      envelope={"event_id": "event-1"}, signature=None, poison_threshold=3)
    assert (letter.attempts, letter.failure_class) == (3, "POISON")


QUARANTINE_ROW = {
    "quarantine_id": "q-1", "event_id": "event-1", "failure_class": "POISON", "reason_code": "HANDLER_FAILED",
    "subscription_id": "urn:ocor:subscription:1", "journal_partition": 0, "journal_offset": 3, "released": False,
}


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("released", None), ("released", 0), ("released", "yes"),
        ("journal_partition", -1), ("journal_partition", True), ("journal_partition", "0"),
        ("journal_offset", -1), ("journal_offset", 1.5),
        ("failure_class", "PERMANENT"), ("failure_class", "INVALID_CLASS"),
        ("subscription_id", 5), ("subscription_id", ""), ("quarantine_id", None),
    ],
)
def test_c5_store_quarantined_refuses_malformed_rows(column: str, value: Any) -> None:
    store_error(lambda: responder_store([{**QUARANTINE_ROW, column: value}]).quarantined("topic"))


def test_c5_store_quarantined_accepts_well_formed_rows() -> None:
    [record] = responder_store([{**QUARANTINE_ROW, "released": True}]).quarantined("topic")
    assert (record.partition, record.offset, record.released) == (0, 3, True)
    [open_record] = responder_store([{**QUARANTINE_ROW, "journal_partition": None, "journal_offset": None,
                                      "subscription_id": None, "failure_class": "POLICY_DENIED"}]).quarantined("topic")
    assert (open_record.partition, open_record.released) == (None, False)


@pytest.mark.parametrize(
    "row",
    [
        {"principal": "p", "contract": {}, "topic": "topic"},
        {"principal": "p", "contract": {"event_type_refs": []}, "topic": "topic"},
        {"principal": "p", "contract": [], "topic": "topic"},
        {"principal": "p", "contract": None, "topic": "topic"},
        {"principal": "", "contract": "valid", "topic": "topic"},
        {"principal": "p", "contract": "valid", "topic": None},
    ],
    ids=["empty-contract", "malformed-contract", "array-contract", "null-contract", "empty-principal", "null-topic"],
)
def test_c5_store_subscription_refuses_malformed_rows(row: dict[str, Any]) -> None:
    if row["contract"] == "valid":
        row = {**row, "contract": subscription_contract()}
    store_error(lambda: responder_store([row]).subscription("urn:ocor:subscription:1"))


def test_c5_store_subscription_accepts_a_well_formed_row() -> None:
    contract = subscription_contract()
    found = responder_store([{"principal": "p", "contract": contract, "topic": "topic"}]).subscription("s")
    assert found == ("p", contract, "topic")


CHECKPOINT_ROW = {
    "cursor_id": "cursor-1", "subscription_id": "urn:ocor:subscription:1", "topic": "topic", "positions": {"0": 3},
    "end_positions": None, "window_start": None, "window_end": None, "replay_reason": None,
    "schema_registry_digest": "sha256:" + "1" * 64, "release_digest": "", "governed_context_digest": GCS,
}


@pytest.mark.parametrize(
    "changes",
    [
        {"positions": {}}, {"positions": {"²": 0}}, {"positions": {"0": True}}, {"positions": {"0": -1}},
        {"positions": {"-1": 0}}, {"positions": None}, {"positions": []}, {"positions": {"0": "3"}},
        {"positions": {"00": 1, "0": 2}}, {"end_positions": {}}, {"end_positions": {"0": None}},
        {"window_start": AWARE}, {"window_end": AWARE},
        {"window_start": AWARE, "window_end": AWARE - timedelta(hours=1)},
        {"window_start": AWARE, "window_end": AWARE},
        {"window_start": NAIVE, "window_end": NAIVE + timedelta(hours=1)},
        {"window_start": "2026-11-04", "window_end": AWARE},
        {"release_digest": None}, {"governed_context_digest": ""},
    ],
    ids=["empty-positions", "superscript-partition", "bool-offset", "negative-offset", "negative-partition",
         "null-positions", "array-positions", "string-offset", "duplicate-partition", "empty-end", "null-end-offset",
         "start-without-end", "end-without-start", "inverted-window", "empty-window", "naive-window",
         "string-window", "null-release", "empty-context"],
)
def test_c5_store_checkpoint_refuses_malformed_rows(changes: dict[str, Any]) -> None:
    store_error(lambda: responder_store([{**CHECKPOINT_ROW, **changes}]).checkpoint("cursor-1"))


def test_c5_store_checkpoint_accepts_well_formed_rows() -> None:
    found = responder_store([{**CHECKPOINT_ROW, "end_positions": {"0": 5}, "window_start": AWARE,
                              "window_end": AWARE + timedelta(hours=1)}]).checkpoint("cursor-1")
    assert (dict(found.positions), dict(found.end_positions), found.window_end - found.window_start) == (
        {0: 3}, {0: 5}, timedelta(hours=1))


def test_c5_store_refuses_rows_tampered_on_the_real_database(env: tuple[Any, ...]) -> None:
    """The same checks on the real driver path: rows written to PostgreSQL out of band with a
    JSON ``null`` or empty envelope, an empty contract or an empty position map are refused."""
    rig = build_rig(*env)
    store = _c5("adapters.postgres").PostgresC5Store(rig.dsn, schema=rig.schema)
    with psycopg.connect(rig.dsn, autocommit=True) as connection:
        connection.execute(
            f'INSERT INTO "{rig.schema}".c5_dead_letter (dead_letter_id, event_id, topic, tenant_id, failure_class, '  # noqa: S608
            "reason_code, envelope, attempt) VALUES ('dl-null', 'e', %s, 't', 'PERMANENT', 'X', 'null'::jsonb, 1)",
            (rig.topic,),
        )
    store_error(lambda: store.dead_letters(rig.topic))
    with psycopg.connect(rig.dsn, autocommit=True) as connection:
        connection.execute(
            f'INSERT INTO "{rig.schema}".c5_subscription (subscription_id, principal, contract, topic) '  # noqa: S608
            "VALUES ('urn:ocor:subscription:tampered', 'p', '{}'::jsonb, %s)", (rig.topic,),
        )
        connection.execute(
            f'INSERT INTO "{rig.schema}".c5_checkpoint (cursor_id, subscription_id, topic, positions, '  # noqa: S608
            "schema_registry_digest, release_digest, governed_context_digest) VALUES ('cursor-tampered', "
            "'urn:ocor:subscription:tampered', %s, '{}'::jsonb, 'sha256:x', '', 'sha256:y')", (rig.topic,),
        )
    store_error(lambda: store.subscription("urn:ocor:subscription:tampered"))
    store_error(lambda: store.checkpoint("cursor-tampered"))
