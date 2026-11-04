"""Support of the C5 consumer tests (OCOR-DEV-0040, 0041, REM-0025 and REM-0026) on the 1.2 backbone.

NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 5, NCP-U06 row: the fixtures, support classes,
offset observations and fault points of these tests move to the in-process client of the C5
backbone and to the broker qualification tool ``c5_kafka_qualification``; the type of every
injected fault stays the same.

- ``draft`` builds the ``canonical-ingestion-envelope:1.2`` (ADD v1.3 :531-840) of an old
  fixture: ``aggregate_ref`` becomes ``ordering_key`` and ``aggregate.aggregate_id``, ``sequence``
  becomes ``aggregate.expected_revision``, ``schema_ref`` becomes the ``payload_schema`` pin
  (an unregistered schema keeps its own id), and an old event id or idempotency key that is not of the 1.2 form maps
  deterministically to one (uuid5, ``idempotency/`` prefix). It is signed only when published,
  so an incomplete draft is refused at the admission boundary, never at construction.
- An old fixture names its governed context by a digest label (``urn:sha256:<hex>``). In 1.2
  ``governed_context_digest`` is the digest of the GovernedContext record the envelope fields
  realise, ``correlation_id`` included, and the admission boundary reproduces it (ADD v1.3 :845):
  a label stands for one GovernedContext, whose ``correlation_id`` derives from the label
  (uuid5) unless the test fixes one, and the digest is computed from the fields when the draft
  is signed. Any other value of an old fixture (empty, ``None``, not a string) is written in the
  ``sha256:`` form if it is a string and as is otherwise, so the admission boundary judges it. A subscription of a label filters the digest it stands for.
- ``C5Rig`` composes the real backbone of one topic (Kafka through the in-process client,
  PostgreSQL for DLQ, quarantine, checkpoints and audit) and the oracles of the tests, which do
  not use the module under test: the topic content, the physical partitions and the record
  count come from the broker through the qualification tool; the records an admission set aside
  (``quarantine``: dead letters of ``PERMANENT``/``POISON`` and quarantine records of
  ``POLICY_DENIED``/``POISON``, ADD v1.3 :529, LLD v1.1 :160-163) are read with direct SQL.
- The policy decisions are an explicit test port of the C5 policy port (OPA owns them in
  production): publish and delivery are allowed; replay, reprocess and release are allowed for
  the operator with the replay authority only.
"""

from __future__ import annotations

import hashlib
import os
import re
import socket
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import psycopg
import psycopg.rows
from c5_kafka_qualification import QualificationKafkaBroker
from ocor_runtime.audit import AuditSigner, PostgresAuditLog
from ocor_runtime.c1.signing import Ed25519SigningKey
from ocor_runtime.c5.adapters.kafka import KafkaJournal
from ocor_runtime.c5.adapters.postgres import PostgresC5Store
from ocor_runtime.c5.backbone import CanonicalEventBackbone
from ocor_runtime.c5.envelope import ProducerKeyring, ProducerSigner, SignedEnvelope
from ocor_runtime.c5.operations import EventOperationsCoordinator, ResourceClass
from ocor_runtime.c5.policy import PolicyDecision
from ocor_runtime.c5.retry import RetryPolicy
from ocor_runtime.c5.schema import SchemaRegistry
from ocor_runtime.kernel.canonical import canonical_bytes
from ocor_runtime.kernel.governed_context import GovernedContext

PRODUCER = "urn:ocor:principal:c6-engine"
CONSUMER = "urn:ocor:principal:c4-projector"
OPERATOR = "urn:ocor:principal:c5-operator"
AUTHORITY = "urn:ocor:authority:replay-ops"
EVENT_TYPE = "urn:ocor:event-type:mission-effect-recorded"
PAYLOAD_SCHEMA_ID = "urn:ocor:schema:mission-effect-recorded"
PAYLOAD_SCHEMA_VERSION = "1.0.0"
PAYLOAD_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": {"type": "string"},
}
OLD_SCHEMA = "urn:ocor:schema:canonical-ingestion-envelope:1"
AGGREGATE_TYPE = "urn:ocor:aggregate-type:mission-object"
TENANT = "urn:ocor:tenant:tenant-a"
NAMESPACE = uuid.UUID("5d2f3b84-6a51-4f0e-9a41-2c0d5e7b9c13")
SEED = hashlib.sha256(b"ocor-c5-consumer-producer").digest()
AUDIT_SEED = hashlib.sha256(b"ocor-c5-consumer-audit").digest()
MARKING = {
    "scheme_id": "urn:ocor:marking-scheme:poc",
    "labels": ["RESTRICTED"],
    "mandatory_markings": [],
    "caveats": [],
    "dissemination_controls": [],
    "permitted_purposes": ["urn:ocor:purpose:mission-planning"],
    "handling_instructions": [],
}
MARKING_DIGEST = "sha256:" + hashlib.sha256(canonical_bytes(MARKING)).hexdigest()


def tenant(name: str) -> str:
    """The stable tenant id of an old fixture tenant name."""
    return name if name.startswith("urn:ocor:tenant:") else f"urn:ocor:tenant:{name}"


def event_uuid(event_id: str) -> str:
    """An old fixture event id in the ``uuid`` form of the 1.2 envelope (stable, deterministic)."""
    try:
        return str(uuid.UUID(event_id))
    except ValueError:
        return str(uuid.uuid5(NAMESPACE, event_id))


CONTEXT_LABEL = re.compile(r"urn:sha256:[0-9a-f]{64}")


def context_label(context: Any) -> str | None:
    """The digest label by which an old fixture names a governed context, if it is one."""
    return context if isinstance(context, str) and CONTEXT_LABEL.fullmatch(context) else None


def label_correlation(label: str) -> str:
    """The ``correlation_id`` of the GovernedContext a label stands for (stable, deterministic)."""
    return str(uuid.uuid5(NAMESPACE, f"correlation/{label}"))


def realised_context_digest(raw: Mapping[str, Any]) -> str:
    """The ``sha256:`` digest of the GovernedContext record the fields of a 1.2 draft realise
    (ADD v1.3 :845), computed with the sealed kernel record, not with the C5 module under test."""
    context = GovernedContext.from_mapping(
        {
            "tenant_id": raw["tenant_id"],
            "organization_id": raw["organization_id"],
            "domain_id": raw["domain_id"],
            "compartments": list(raw["compartments"]),
            "classification_marking_ref": "urn:" + str(raw["classification_marking"]["marking_digest"]),
            "purpose": raw["purpose"],
            "effective_principal_id": raw["effective_principal_id"],
            "actor_chain": list(raw["actor_chain"]),
            "ontology_release_digest": "urn:" + str(raw["ontology_release_digest"]),
            "policy_bundle_digest": "urn:" + str(raw["policy_bundle_digest"]),
            "correlation_id": raw["correlation_id"],
        }
    )
    return context.digest().removeprefix("urn:")


def schema_pin(schema_ref: str = OLD_SCHEMA) -> dict[str, str]:
    """The ``payload_schema`` pin of an old ``schema_ref``: the registered payload schema, or an
    unregistered schema with its own id."""
    if schema_ref == OLD_SCHEMA:
        return {
            "schema_id": PAYLOAD_SCHEMA_ID,
            "schema_version": PAYLOAD_SCHEMA_VERSION,
            "schema_digest": "sha256:" + hashlib.sha256(canonical_bytes(PAYLOAD_SCHEMA)).hexdigest(),
        }
    return {
        "schema_id": schema_ref.rsplit(":", 1)[0],
        "schema_version": "1.0.0",
        "schema_digest": "sha256:" + hashlib.sha256(schema_ref.encode("utf-8")).hexdigest(),
    }


class Draft:
    """An unsigned ``canonical-ingestion-envelope:1.2`` of a test, signed when published."""

    def __init__(self, raw: dict[str, Any], context: str | None = None) -> None:
        self.raw = raw
        self.context = context

    def realise_context(self) -> None:
        """Write the digest of the GovernedContext the current fields realise, when the draft
        names its context by a label; a draft without a complete context is left as is."""
        if self.context is None:
            return
        try:
            self.raw["governed_context_digest"] = realised_context_digest(self.raw)
        except (KeyError, TypeError, ValueError):
            return

    def __getitem__(self, name: str) -> Any:
        return self.raw[name]

    def to_mapping(self) -> dict[str, Any]:
        return thaw_copy(self.raw)

    @property
    def event_id(self) -> str:
        return str(self.raw["event_id"])

    @property
    def idempotency_key(self) -> str:
        return str(self.raw["idempotency_key"])

    @property
    def correlation_id(self) -> str:
        return str(self.raw["correlation_id"])

    @property
    def causation_id(self) -> str | None:
        return self.raw["causation_id"]

    @property
    def sequence(self) -> int:
        return int(self.raw["aggregate"]["expected_revision"])


def thaw_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: thaw_copy(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [thaw_copy(item) for item in value]
    return value


def draft(
    *,
    aggregate_ref: str,
    sequence: int | None = 1,
    event_id: str | None = None,
    idempotency_key: str | None = None,
    schema_ref: str = OLD_SCHEMA,
    context: Any = "urn:sha256:" + "a" * 64,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    payload: dict[str, Any] | None = None,
    tenant_id: str = TENANT,
    principal: str = PRODUCER,
) -> Draft:
    identifier = event_uuid(event_id) if event_id else str(uuid.uuid4())
    label = context_label(context)
    if correlation_id is None:
        correlation_id = label_correlation(label) if label is not None else str(uuid.uuid4())
    key = idempotency_key or identifier
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    aggregate: dict[str, Any] = {"aggregate_type_id": AGGREGATE_TYPE, "aggregate_id": aggregate_ref}
    if sequence is not None:
        aggregate["expected_revision"] = sequence
    value = Draft(
        {
            "envelope_version": "1.2",
            "event_id": identifier,
            "tenant_id": tenant_id,
            "organization_id": "urn:ocor:organization:alpha",
            "domain_id": "urn:ocor:domain:mission",
            "compartments": ["urn:ocor:compartment:ops"],
            "world_ref": "urn:ocor:world:main",
            "ingest_mode": "STREAM",
            "semantic_class": "OBSERVED_EVENT",
            "event_type_id": EVENT_TYPE,
            "event_time": now,
            "ingest_time": now,
            "ordering_key": aggregate_ref,
            "idempotency_key": key if len(key) >= 16 else f"idempotency/{key}",
            "purpose": "urn:ocor:purpose:mission-planning",
            "source": {
                "source_id": "urn:ocor:source:backbone-fixture",
                "source_record_id": event_id or identifier,
                "adapter_id": "urn:ocor:adapter:c5-consumer-fixture",
                "adapter_version": "1.0.0",
            },
            "aggregate": aggregate,
            "payload_schema": schema_pin(schema_ref),
            "payload": payload if payload is not None else {"status": "ASSESSED"},
            "classification_marking": {**MARKING, "marking_digest": MARKING_DIGEST},
            "provenance_ref": "urn:sha256:" + "e" * 64,
            "integrity": {"payload_digest": "sha256:" + "0" * 64, "source_producer_principal_ref": principal},
            "effective_principal_id": principal,
            "actor_chain": [principal],
            "governed_context_digest": context.removeprefix("urn:") if isinstance(context, str) else context,
            "ontology_release_digest": "sha256:" + "1" * 64,
            "policy_bundle_digest": "sha256:" + "2" * 64,
            "correlation_id": correlation_id,
            "causation_id": causation_id,
            "transport": {"mode": "STREAM", "stream_id": "urn:ocor:stream:mission", "partition": 0, "offset": "0"},
        },
        label,
    )
    value.realise_context()
    return value


@dataclass
class AllowingPolicy:
    """Explicit test port of the C5 policy port."""

    calls: list[tuple[str, str]] = field(default_factory=list)

    def authorize_publish(self, principal: str, envelope: Any) -> PolicyDecision:
        self.calls.append(("publish", envelope.event_id))
        return PolicyDecision(allowed=True, reason_code="PERMITTED")

    def authorize_delivery(self, principal: str, subscription_id: str, envelope: Any) -> PolicyDecision:
        self.calls.append(("delivery", envelope.event_id))
        return PolicyDecision(allowed=True, reason_code="PERMITTED")

    def authorize_replay(self, principal: str, request: Any) -> PolicyDecision:
        self.calls.append(("replay", principal))
        allowed = principal == OPERATOR and request.authority_ref == AUTHORITY
        return PolicyDecision(allowed=allowed, reason_code="PERMITTED" if allowed else "REPLAY_DENIED")


@dataclass(frozen=True)
class SetAside:
    """A record an admission set aside without publishing it, read with direct SQL."""

    table: str
    reason_code: str
    failure_class: str
    raw: Mapping[str, Any]


def live_dsn() -> str:
    value = os.environ.get("OCOR_LIVE_POSTGRES_DSN", "")
    if not value:
        raise AssertionError("OCOR_LIVE_POSTGRES_DSN is mandatory: the C5 DLQ, quarantine and checkpoints are durable")
    return value


class C5Rig:
    """The real C5 backbone of one topic with the oracles of the consumer tests."""

    def __init__(
        self,
        broker: QualificationKafkaBroker | None,
        topic: str,
        *,
        dsn: str,
        schema: str,
        quotas: Mapping[ResourceClass, int] | None = None,
        journal_type: type[KafkaJournal] = KafkaJournal,
        journal_timeout_s: float = 10.0,
        bootstrap_servers: str | None = None,
    ) -> None:
        self.broker = broker
        self.topic = topic
        self.dsn = dsn
        self.schema = schema
        self.quotas = dict(quotas or {})
        self.contexts: dict[str, set[str]] = {}
        self.policy = AllowingPolicy()
        self.registry = SchemaRegistry()
        pin = self.registry.register_schema(PAYLOAD_SCHEMA_ID, PAYLOAD_SCHEMA_VERSION, PAYLOAD_SCHEMA)
        self.registry.register_event_type(EVENT_TYPE, payload_schema=pin, resource_class=ResourceClass.BATCH)
        self.pin = pin
        key = Ed25519SigningKey.from_seed(SEED)
        self.signer = ProducerSigner(PRODUCER, key)
        self.keyring = ProducerKeyring({PRODUCER: key.public_key})
        self.audit = PostgresAuditLog(
            dsn, schema=f"{schema}_audit",
            signer=AuditSigner(key=Ed25519SigningKey.from_seed(AUDIT_SEED), keyid="c5-audit"),
        )
        self.audit.initialize()
        self.store = PostgresC5Store(dsn, schema=schema)
        self.store.initialize()
        if bootstrap_servers is None:
            if broker is None:
                raise ValueError("a broker or explicit bootstrap servers are required")
            bootstrap_servers = broker.bootstrap_servers
        servers = bootstrap_servers
        self.journal = journal_type(servers, topic, timeout_s=journal_timeout_s)
        self.backbone = CanonicalEventBackbone(
            journal=self.journal, registry=self.registry, keyring=self.keyring, policy=self.policy,
            audit=self.audit, store=self.store, retry=RetryPolicy(max_attempts=1), quotas=self.quotas or None,
        )

    def restarted(self, *, journal_type: type[KafkaJournal] | None = None) -> C5Rig:
        """A new process on the same topic and stores: process state is gone, journal and DLQ are not."""
        return C5Rig(self.broker, self.topic, dsn=self.dsn, schema=self.schema, quotas=self.quotas,
                     journal_type=journal_type or type(self.journal))

    def coordinator(self) -> EventOperationsCoordinator:
        return EventOperationsCoordinator(self.backbone, transport_principal=PRODUCER)

    # -- producer side -------------------------------------------------------------------------

    def sign(self, value: Draft | Mapping[str, Any]) -> SignedEnvelope:
        """Sign a draft; an incomplete envelope is refused here, ``REJECTED`` (ADD v1.3 :379)."""
        if isinstance(value, Draft):
            value.realise_context()
            if value.context is not None:
                self.contexts.setdefault(value.context, set()).add(str(value.raw["governed_context_digest"]))
            return self.signer.sign(value.raw)
        return self.signer.sign(value)

    def publish(self, value: Draft | Mapping[str, Any]) -> Any:
        return self.backbone.publish(self.sign(value), transport_principal=PRODUCER)

    def publish_from_mapping(self, raw: Mapping[str, Any]) -> Any:
        return self.publish(raw)

    # -- consumer side (the product Subscribe surface) --------------------------------------------

    def context_ref(self, label: str) -> str:
        """The ``urn:sha256:`` reference of the GovernedContext a label stands for: the digest the
        drafts of that label signed by this rig carry (one only), else the digest of a default
        draft of the label."""
        digests = self.contexts.get(label) or {realised_context_digest(draft(aggregate_ref="ref", context=label).raw)}
        if len(digests) != 1:
            raise AssertionError(f"the drafts of context {label} realise {len(digests)} governed contexts")
        return "urn:" + next(iter(digests))

    def subscription(self, *, context: str = "urn:sha256:" + "a" * 64) -> str:
        if context_label(context) is not None:
            context = self.context_ref(context)
        contract = {
            "subscription_contract_id": f"urn:ocor:subscription-contract:{uuid.uuid4().hex}",
            "version": "1.0.0",
            "contract_digest": "sha256:" + "f" * 64,
            "governed_context_ref": context,
            "event_type_refs": [EVENT_TYPE],
            "delivery": {"semantics": "AT_LEAST_ONCE", "consumer_must_deduplicate": True, "dedup_key": "event_id"},
            "ordering": {"guarantee": "PER_ORDERING_KEY", "ordering_key_field": "ordering_key"},
            "filter": {"filter_contract_id": "urn:ocor:filter:all-mission-effects", "arbitrary_predicates_allowed": False},
            "payload_schema": {
                "schema_id": PAYLOAD_SCHEMA_ID, "version": PAYLOAD_SCHEMA_VERSION, "digest": self.pin["schema_digest"],
            },
            "marking_policy": {"propagate_marking": True, "redact_unauthorized": True, "declare_redactions": True},
            "replay": {"replay_allowed": True, "cursor_opaque": True, "authorization_required": True,
                       "max_replay_window": "P1D"},
            "error_codes": ["POLICY_DENIED", "REPLAY_DENIED", "CURSOR_EXPIRED", "SCHEMA_VIOLATION"],
        }
        return self.backbone.subscribe(contract, principal=CONSUMER)

    def consume(self, count: int, *, context: str = "urn:sha256:" + "a" * 64) -> tuple[Any, ...]:
        """The first ``count`` events delivered by a new subscription from the start of the journal."""
        batch = self.backbone.poll(self.subscription(context=context), cursor=None, max_records=count, timeout_s=20)
        if len(batch.events) != count:
            raise AssertionError(f"expected {count} delivered events, received {len(batch.events)}")
        return batch.events

    # -- oracles independent of the module under test ---------------------------------------------

    def _broker(self) -> QualificationKafkaBroker:
        if self.broker is None:
            raise AssertionError("this rig has no qualification broker")
        return self.broker

    def topic_records(self) -> int:
        """Exact number of records on the real topic (sum of the partition end offsets)."""
        return self._broker().record_count(self.topic)

    def topic_envelopes(self) -> list[dict[str, Any]]:
        """Every record of the real topic, read by the broker, in partition and offset order."""
        return [record.json() for record in self._broker().records(self.topic)]

    def partitions_of(self, event_ids: list[str]) -> set[int]:
        """The physical partitions that hold ``event_ids``, observed on the broker."""
        found = {record.json()["event_id"]: record.partition for record in self._broker().records(self.topic)}
        return {found[event_id] for event_id in event_ids}

    def rows(self, table: str) -> list[dict[str, Any]]:
        with psycopg.connect(self.dsn, row_factory=psycopg.rows.dict_row) as connection:
            return list(connection.execute(f'SELECT * FROM "{self.schema}".{table} WHERE topic = %s', (self.topic,)))  # noqa: S608

    @property
    def quarantine(self) -> tuple[SetAside, ...]:
        rows = [("c5_dead_letter", row) for row in self.rows("c5_dead_letter")]
        rows += [("c5_quarantine", row) for row in self.rows("c5_quarantine")]
        rows.sort(key=lambda item: (item[1]["recorded_at"], item[0]))
        return tuple(
            SetAside(table, row["reason_code"], row["failure_class"], row["envelope"] or {}) for table, row in rows
        )

    def drop(self) -> None:
        with psycopg.connect(self.dsn, autocommit=True) as connection:
            connection.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
            connection.execute(f'DROP SCHEMA IF EXISTS "{self.schema}_audit" CASCADE')


def unreachable_bootstrap() -> str:
    """A loopback ``host:port`` nobody listens on: the fault point of an unreachable broker."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return f"127.0.0.1:{probe.getsockname()[1]}"


def schema_name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
