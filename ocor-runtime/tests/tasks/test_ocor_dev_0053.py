"""OCOR-DEV-0053: Implement embedding lifecycle and deterministic rebuild.

Acceptance (backlog): parallel versioned representations rebuild
deterministically without changing immutable memory items.  Negative:
unpinned model/vector dimensions or mixed representation versions fail
retrieval; a SKIPPED, UNAVAILABLE, mock-only or NOT_EXECUTED qualifying case
is not accepted.

Oracles: ADD v1.3 Part II §§2.6-2.8 and 2.10 (each embedding binds
item/version, content digest, model/version/digest, tokenizer, dimensions,
normalization profile, purpose and marking; a model upgrade creates a parallel
representation version and a deterministic rebuild and does not mutate source
memory; representation generation executes under an authorized GCS; no
cross-compartment centroid, global ANN graph or shared vector cache; raw
vectors are not part of the default response) and LLD v1.1 §§2.8.1, 2.8.4,
2.8.6 and §7.2 (``FGM-07`` upgrade embedding model -> parallel versioned
representation and deterministic rebuild; ``FGM-06``, ``FGM-10`` and
``FGM-16`` oracles where the parallel representation is searched, exercised
here at component level).

Qualifying cases run on the real, pinned backends of OCOR-DEV-0051/0052:
PostgreSQL 16 from ``OCOR_LIVE_POSTGRES_DSN`` (metadata, encrypted content,
full-text index and the representation records/descriptors, one schema per
world), Qdrant 1.15.1 (native and parallel vector layouts, one namespace per
world) and OpenBao 2.6.2 transit.  Records come from the real OCOR-DEV-0050
admission service, are committed by the real store coordinator and searched by
the real OCOR-DEV-0052 retrieval service.  The embedding models are governed
deterministic fixtures (GPU 0): the 0051 fixture hash model as the native v1
model and a signed feature-hashing model as the upgraded v2 model; both are
real deterministic computations, not doubles of a boundary.  A missing backend
fails, it never skips.  The unit cases at the top use the 0051 in-memory port
fixtures only for branch logic; none of them is qualifying.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
import threading
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import psycopg
import pytest
import test_ocor_dev_0051 as base
import test_ocor_dev_0052 as t52
from ocor_runtime.kernel.canonical import canonical_bytes, canonical_digest, format_utc_timestamp
from ocor_runtime.kernel.governed_context import GovernedContext
from ocor_runtime.memory.embeddings import (
    EMBEDDING_PREFIX,
    EmbeddingDescriptor,
    EmbeddingLifecycleCoordinator,
    EmbeddingModelPin,
    EmbeddingModelRegistry,
    EmbeddingSearchService,
    MemoryEmbeddingError,
    ParallelLayout,
    RepresentationReceipt,
    RepresentationRecord,
    RepresentationState,
    _entry_binds,
    _unit_vector,
    manifest_digest,
    record_conflict,
)
from ocor_runtime.memory.model import (
    AdmittedMemoryVersion,
    GovernedMemoryItem,
    MemoryAdmissionError,
    MemoryPolicyDecision,
    MemoryReceipt,
    idempotency_key,
)
from ocor_runtime.memory.retrieval import MemorySearchResponse, MemorySearchService, RetrievalMode
from ocor_runtime.memory.stores import (
    IndexEntry,
    MemoryPartition,
    VectorProfile,
    stored_vector_digest,
    vector_digest,
)

NOW = base.NOW
d = base.d
context = t52.context
binding = t52.binding
request = t52.request
CALLER = t52.CALLER
M_SECRET = t52.M_SECRET
VECTOR_MODEL = base.VECTOR_MODEL


# --------------------------------------------------------------------------
# Governed deterministic embedding fixtures (pinned models)
# --------------------------------------------------------------------------

BYTES_TOKENIZER = {"tokenizer": "utf8-bytes", "version": "1"}
PIN_V1 = EmbeddingModelPin(
    model_ref=str(VECTOR_MODEL["embedding_model_ref"]),
    model_version="1",
    model_digest=str(VECTOR_MODEL["embedding_model_digest"]),
    tokenizer_ref="urn:ocor:tokenizer:utf8-bytes",
    tokenizer_digest=canonical_digest(BYTES_TOKENIZER),
    dimensions=base.DIMENSIONS,
    normalization_profile="l2-unit",
)


class FixtureHashModel:
    """The 0051 fixture hash model, pinned as the native v1 representation."""

    def __init__(self, pin: EmbeddingModelPin = PIN_V1) -> None:
        self.pin = pin
        self.calls = 0

    def embed(self, text: str) -> list[float]:
        self.calls += 1
        return base.embed(text)


WORD = re.compile(r"\w+")


class FeatureHashingModel:
    """Signed feature hashing of lower-cased word tokens, L2-normalised.

    Deterministic by construction; the model digest pins algorithm, seed,
    dimensions and tokenizer, so any change is a different pin.
    """

    def __init__(self, *, seed: str = "ocor-feature-hash:2", dimensions: int = 16, version: str = "2") -> None:
        self.seed = seed
        self.dimensions = dimensions
        tokenizer = {"tokenizer": "unicode-word-lower", "pattern": WORD.pattern}
        self.pin = EmbeddingModelPin(
            model_ref="embedding-model:feature-hash-16",
            model_version=version,
            model_digest=canonical_digest(
                {"algorithm": "signed-feature-hashing", "seed": seed, "dimensions": dimensions, "tokenizer": tokenizer}
            ),
            tokenizer_ref="urn:ocor:tokenizer:unicode-word-lower",
            tokenizer_digest=canonical_digest(tokenizer),
            dimensions=dimensions,
            normalization_profile="l2-unit",
        )
        self.calls = 0

    def embed(self, text: str) -> list[float]:
        self.calls += 1
        values = [0.0] * self.dimensions
        for token in WORD.findall(text.lower()):
            digest = hashlib.sha256(f"{self.seed}|{token}".encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            values[index] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(math.fsum(v * v for v in values))
        if norm == 0.0:
            values[0], norm = 1.0, 1.0
        return [v / norm for v in values]


V2 = FeatureHashingModel()
PIN_V2 = V2.pin
PROFILE_V1 = PIN_V1.vector_profile
PROFILE_V2 = PIN_V2.vector_profile
MODEL_V2 = {
    "embedding_model_ref": PIN_V2.model_ref,
    "embedding_model_digest": PIN_V2.model_digest,
    "embedding_dimensions": PIN_V2.dimensions,
    "embedding_normalization_profile": PIN_V2.normalization_profile,
}
assert PROFILE_V1.representation_version == VectorProfile(**VECTOR_MODEL).representation_version  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Representation policy, audit and in-memory record store (unit) ports
# --------------------------------------------------------------------------


@dataclass
class RepresentationGrant:
    permitted: bool = True
    bundle: str | None = None
    fail: bool = False
    calls: list[str] = field(default_factory=list)

    def authorize_representation(self, partition: MemoryPartition, pin: EmbeddingModelPin, ctx: GovernedContext) -> MemoryPolicyDecision:
        self.calls.append(partition.digest)
        if self.fail:
            raise ConnectionError("opa unavailable")
        return MemoryPolicyDecision(
            permitted=self.permitted,
            decision_ref=f"decision:representation:{partition.digest}:{pin.digest}",
            policy_bundle_digest=self.bundle or ctx.policy_bundle_digest,
        )


@dataclass
class RepAudit(t52.Audit):
    """Representation audit store: append plus success-receipt lookup.

    ``accept`` (when set) refuses the events it rejects, like a store that is
    up for some writes only; ``lookup_fails`` makes the receipt lookup raise.
    """

    accept: Any = None
    lookup_fails: bool = False

    def record(self, event: Any) -> None:
        if self.accept is not None and not self.accept(event):
            raise OSError("audit store refused the event")
        super().record(event)

    def contains(self, audit_ref: str) -> bool:
        if self.lookup_fails:
            raise OSError("audit store unavailable")
        return any(event.get("audit_ref") == audit_ref for event in self.events)


class MemRepresentations:
    """In-memory record/descriptor store (unit branch logic only)."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str], RepresentationRecord] = {}
        self.items: dict[str, EmbeddingDescriptor] = {}

    def record(self, partition_digest: str, representation_version: str) -> RepresentationRecord | None:
        return self.records.get((partition_digest, representation_version))

    def put_record(self, record: RepresentationRecord, *, expected_digest: str | None) -> None:
        key = (record.partition_digest, record.representation_version)
        current = self.records.get(key)
        if (None if current is None else current.digest) != expected_digest:
            raise record_conflict()
        self.records[key] = record

    def put_descriptor(self, descriptor: EmbeddingDescriptor) -> None:
        self.items.setdefault(descriptor.store_ref, descriptor)

    def descriptor(self, store_ref: str) -> EmbeddingDescriptor | None:
        return self.items.get(store_ref)

    def descriptors(self, partition_digest: str, representation_version: str) -> tuple[EmbeddingDescriptor, ...]:
        return tuple(
            sorted(
                (x for x in self.items.values() if (x.partition_digest, x.representation_version) == (partition_digest, representation_version)),
                key=lambda x: x.store_ref,
            )
        )

    def remove_descriptor(self, store_ref: str) -> None:
        self.items.pop(store_ref, None)


class PostgresRepresentationStore:
    """Representation records and descriptors on the world's PostgreSQL schema."""

    def __init__(self, dsn: str, schema: str) -> None:
        self.dsn = dsn
        self.schema = schema
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            conn.execute(
                f'CREATE TABLE IF NOT EXISTS "{schema}".representation_records ('
                "partition_digest text NOT NULL, representation_version text NOT NULL, "
                "record_digest text NOT NULL, body text NOT NULL, "
                "PRIMARY KEY (partition_digest, representation_version))"
            )
            conn.execute(
                f'CREATE TABLE IF NOT EXISTS "{schema}".embedding_descriptors ('
                "store_ref text PRIMARY KEY, partition_digest text NOT NULL, "
                "representation_version text NOT NULL, body text NOT NULL)"
            )

    def connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.dsn)

    def record(self, partition_digest: str, representation_version: str) -> RepresentationRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                f'SELECT body FROM "{self.schema}".representation_records '
                "WHERE partition_digest = %s AND representation_version = %s",
                (partition_digest, representation_version),
            ).fetchone()
        return None if row is None else RepresentationRecord.from_mapping(json.loads(row[0]))

    def put_record(self, record: RepresentationRecord, *, expected_digest: str | None) -> None:
        s = self.schema
        body = canonical_bytes(record.to_mapping()).decode()
        key = (record.partition_digest, record.representation_version)
        with self.connect() as conn, conn.transaction():
            row = conn.execute(
                f'SELECT record_digest FROM "{s}".representation_records '
                "WHERE partition_digest = %s AND representation_version = %s FOR UPDATE",
                key,
            ).fetchone()
            if row is None:
                if expected_digest is not None:
                    raise record_conflict()
                inserted = conn.execute(
                    f'INSERT INTO "{s}".representation_records VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING 1',
                    (*key, record.digest, body),
                ).fetchone()
                if inserted is None:
                    raise record_conflict()
                return
            if row[0] != expected_digest:
                raise record_conflict()
            conn.execute(
                f'UPDATE "{s}".representation_records SET record_digest = %s, body = %s '
                "WHERE partition_digest = %s AND representation_version = %s",
                (record.digest, body, *key),
            )

    def put_descriptor(self, descriptor: EmbeddingDescriptor) -> None:
        with self.connect() as conn:
            conn.execute(
                f'INSERT INTO "{self.schema}".embedding_descriptors VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING',
                (
                    descriptor.store_ref,
                    descriptor.partition_digest,
                    descriptor.representation_version,
                    canonical_bytes(descriptor.to_mapping()).decode(),
                ),
            )

    def descriptor(self, store_ref: str) -> EmbeddingDescriptor | None:
        with self.connect() as conn:
            row = conn.execute(
                f'SELECT body FROM "{self.schema}".embedding_descriptors WHERE store_ref = %s', (store_ref,)
            ).fetchone()
        return None if row is None else EmbeddingDescriptor.from_mapping(json.loads(row[0]))

    def descriptors(self, partition_digest: str, representation_version: str) -> tuple[EmbeddingDescriptor, ...]:
        with self.connect() as conn:
            rows = conn.execute(
                f'SELECT body FROM "{self.schema}".embedding_descriptors '
                "WHERE partition_digest = %s AND representation_version = %s ORDER BY store_ref",
                (partition_digest, representation_version),
            ).fetchall()
        return tuple(EmbeddingDescriptor.from_mapping(json.loads(row[0])) for row in rows)

    def remove_descriptor(self, store_ref: str) -> None:
        with self.connect() as conn:
            conn.execute(f'DELETE FROM "{self.schema}".embedding_descriptors WHERE store_ref = %s', (store_ref,))


# --------------------------------------------------------------------------
# World: 0052 world plus the embedding lifecycle coordinator
# --------------------------------------------------------------------------


class World(t52.World):
    def __init__(self, *, representations: Any, parallel: Any, models: Sequence[Any] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.v1 = FixtureHashModel()
        self.v2 = FeatureHashingModel()
        self.registry = EmbeddingModelRegistry(models if models is not None else (self.v1, self.v2))
        self.representations = representations
        self.parallel = t52.TracingIndex(parallel)
        self.rep_policy = RepresentationGrant()
        self.rep_audit = RepAudit()
        self.coordinator = self.build()

    def build(self, **overrides: Any) -> EmbeddingLifecycleCoordinator:
        arguments: dict[str, Any] = {
            "ledger": self.ledger,
            "metadata": self.metadata,
            "content": self.content,
            "cipher": self.cipher,
            "lexical": self.lexical,
            "vector": self.vector,
            "clock": self.clock,
            "models": self.registry,
            "representations": self.representations,
            "representation_index": self.parallel,
            "policy": self.rep_policy,
            "markings": self.markings,
            "audit": self.rep_audit,
        }
        arguments.update(overrides)
        return EmbeddingLifecycleCoordinator(**arguments)

    def service(self, **overrides: Any) -> MemorySearchService:
        """The search service of the embedding lifecycle (caller scope for representation lookups)."""

        arguments: dict[str, Any] = {
            "coordinator": self.coordinator,
            "metadata": self.metadata,
            "policy": self.policy,
            "markings": self.markings,
            "stop": self.stop,
            "audit": self.audit,
            "clock": self.clock,
        }
        arguments.update(overrides)
        return EmbeddingSearchService(**arguments)

    def rebuild(self, item: AdmittedMemoryVersion, profile: VectorProfile = PROFILE_V2, *, ctx: GovernedContext = CALLER, op: str = "rebuild-1") -> RepresentationReceipt:
        return self.coordinator.rebuild(MemoryPartition.for_item(item.item).ref, profile, binding=binding(ctx), operation_id=op)

    def invalidate(self, item: AdmittedMemoryVersion, profile: VectorProfile = PROFILE_V2, *, op: str = "invalidate-1") -> RepresentationReceipt:
        return self.coordinator.invalidate(MemoryPartition.for_item(item.item).ref, profile, binding=binding(), operation_id=op)

    def search_v2(self, text: str, *, ctx: GovernedContext = CALLER, mode: RetrievalMode = RetrievalMode.VECTOR, **extra: Any) -> MemorySearchResponse:
        vector = self.coordinator.embed_query(PROFILE_V2, text)
        extra.setdefault("deadline", format_utc_timestamp(self.clock.now() + timedelta(seconds=30)))
        body = request(mode, text=text, query_vector=vector, model=MODEL_V2, ctx=ctx, **extra)
        return self.service().search(body, binding=binding(ctx))

    def search_v1(self, text: str, *, ctx: GovernedContext = CALLER) -> MemorySearchResponse:
        body = request(RetrievalMode.VECTOR, text=text, ctx=ctx, deadline=format_utc_timestamp(self.clock.now() + timedelta(seconds=30)))
        return self.service().search(body, binding=binding(ctx))

    def transition(self, record: AdmittedMemoryVersion, status: str, text: str, **fields: Any) -> AdmittedMemoryVersion:
        """Append version n+1 with ``status`` (and e.g. ``deletion_epoch``), committed."""

        mapping = record.item.to_mapping()
        version = record.item.memory_version + 1
        mapping.update(
            memory_version=version,
            supersedes_ref=record.item.version_ref,
            lifecycle_status=status,
            created_at=format_utc_timestamp(self.clock.now()),
            embedding_ref=f"embedding:{record.item.memory_item_id}:v{version}",
            **fields,
        )
        item = GovernedMemoryItem.from_mapping(mapping)
        audit_event = {"action": "transitionMemoryLifecycle", "item_digest": item.digest(), "to_status": status}
        following = AdmittedMemoryVersion(
            item=item,
            item_digest=item.digest(),
            idempotency_key=idempotency_key(item, f"lifecycle-{version}"),
            lifecycle_event={"event_type": "MEMORY_LIFECYCLE", "to_status": status},
            audit_event=audit_event,
            receipt=MemoryReceipt(
                memory_item_id=item.memory_item_id,
                memory_version=version,
                content_digest=item.content_digest,
                lifecycle_status=status,
                governed_context_digest=item.governed_context_digest,
                audit_ref=canonical_digest(audit_event),
            ),
        )
        self.ledger.append(following)
        self.coordinator.commit(following, payload=text.encode(), embedding=base.embed(text))
        return following


def unit_world(**kwargs: Any) -> World:
    return World(
        metadata=base.MemMetadata(),
        content=base.MemContent(),
        lexical=base.MemIndex(),
        vector=base.MemIndex(),
        cipher=base.FixtureCipher(),
        representations=MemRepresentations(),
        parallel=base.MemIndex(),
        **kwargs,
    )


def refs(response: MemorySearchResponse) -> list[str]:
    return t52.refs(response)


def assert_error(action: Any, reason: str, detail: str) -> MemoryAdmissionError:
    with pytest.raises(MemoryAdmissionError) as caught:
        action()
    assert (caught.value.reason_code, caught.value.detail_code) == (reason, detail), caught.value
    return caught.value


REBUILD = "rebuildEmbeddingRepresentation"
INVALIDATE = "invalidateEmbeddingRepresentation"
SEARCH = "searchEmbeddingRepresentation"


def denials(world: World, action: str) -> list[tuple[str, str]]:
    """(reason, detail) of every denial event of ``action``, in order."""

    return [(str(e["reason_code"]), str(e["detail_code"])) for e in world.rep_audit.events if e["action"] == action + ".denied"]


def successes(world: World, action: str) -> list[dict[str, Any]]:
    return [dict(e) for e in world.rep_audit.events if e["action"] == action]


def assert_denied(world: World, action: str, call: Any, reason: str, detail: str) -> MemoryAdmissionError:
    """The refusal raises ``reason``/``detail`` and appends exactly one matching denial event."""

    before = len(world.rep_audit.events)
    error = assert_error(call, reason, detail)
    added = world.rep_audit.events[before:]
    assert [(e["action"], e["reason_code"], e["detail_code"]) for e in added] == [(action + ".denied", reason, detail)], added
    event = added[0]
    assert event["audit_ref"] == canonical_digest({k: v for k, v in event.items() if k != "audit_ref"})
    assert "vector" not in event and "embedding" not in json.dumps(event).replace("Embedding", "")
    return error


CORPUS = (
    ("conv-1", "convoy moving along the northern supply route"),
    ("conv-2", "supply route blocked by flooding near the bridge"),
    ("conv-3", "radar contact over the eastern ridge at dawn"),
)


def populate(world: World, corpus: Sequence[tuple[str, str]] = CORPUS, **kwargs: Any) -> list[AdmittedMemoryVersion]:
    return [world.admit(item_id, text, **kwargs) for item_id, text in corpus]


# --------------------------------------------------------------------------
# Unit branch logic (0051 in-memory fixtures; not qualifying evidence)
# --------------------------------------------------------------------------


PIN_FIELDS = dataclasses.asdict(PIN_V2)
INVALID_PINS = [
    ("model_ref-empty", {"model_ref": ""}, "MEMORY_SCHEMA_INVALID", "EMBEDDING_PIN_INVALID"),
    ("model_version-padded", {"model_version": " 2"}, "MEMORY_SCHEMA_INVALID", "EMBEDDING_PIN_INVALID"),
    ("tokenizer_ref-missing", {"tokenizer_ref": None}, "MEMORY_SCHEMA_INVALID", "EMBEDDING_PIN_INVALID"),
    ("model_digest-not-digest", {"model_digest": "sha256:abc"}, "MEMORY_SCHEMA_INVALID", "EMBEDDING_PIN_INVALID"),
    ("tokenizer_digest-not-digest", {"tokenizer_digest": d("t").upper()}, "MEMORY_SCHEMA_INVALID", "EMBEDDING_PIN_INVALID"),
    ("dimensions-zero", {"dimensions": 0}, "MEMORY_SCHEMA_INVALID", "EMBEDDING_PIN_INVALID"),
    ("dimensions-too-large", {"dimensions": 4097}, "MEMORY_SCHEMA_INVALID", "EMBEDDING_PIN_INVALID"),
    ("dimensions-bool", {"dimensions": True}, "MEMORY_SCHEMA_INVALID", "EMBEDDING_PIN_INVALID"),
    ("dimensions-float", {"dimensions": 16.0}, "MEMORY_SCHEMA_INVALID", "EMBEDDING_PIN_INVALID"),
    ("normalization-unpinned", {"normalization_profile": "none"}, "UNSUPPORTED_CAPABILITY", "EMBEDDING_NORMALIZATION_UNSUPPORTED"),
]


@pytest.mark.parametrize(("label", "changes", "reason", "detail"), INVALID_PINS, ids=[c[0] for c in INVALID_PINS])
def test_embedding_pins_are_closed_and_validated(label: str, changes: dict[str, Any], reason: str, detail: str) -> None:
    assert_error(lambda: EmbeddingModelPin(**{**PIN_FIELDS, **changes}), reason, detail)


def test_a_valid_pin_names_its_representation_version_and_maximum_dimensions_are_accepted() -> None:
    pin = EmbeddingModelPin(**{**PIN_FIELDS, "dimensions": 4096})
    assert pin.representation_version == pin.vector_profile.representation_version
    assert PIN_V2.digest == canonical_digest(PIN_V2.to_mapping())
    for name, value in PIN_FIELDS.items():
        other = {**PIN_FIELDS, name: (value + 1 if isinstance(value, int) else (d(str(value)) if str(value).startswith("urn:sha256:") else f"{value}-x"))}
        if name == "normalization_profile":
            continue
        assert EmbeddingModelPin(**other).digest != PIN_V2.digest, name


def test_the_registry_resolves_only_exactly_pinned_profiles() -> None:
    registry = EmbeddingModelRegistry((FixtureHashModel(), FeatureHashingModel()))
    assert registry.resolve(PROFILE_V2)[1] == PIN_V2 and registry.resolve(PROFILE_V1)[1] == PIN_V1
    assert set(registry.pins()) == {PIN_V1, PIN_V2}
    for changes in (
        {"embedding_model_digest": d("other-model")},
        {"embedding_dimensions": 32},
        {"embedding_normalization_profile": "none"},
        {"embedding_model_ref": "embedding-model:unregistered"},
    ):
        profile = dataclasses.replace(PROFILE_V2, **changes)
        assert_error(lambda profile=profile: registry.resolve(profile), "UNSUPPORTED_CAPABILITY", "EMBEDDING_MODEL_UNPINNED")
    assert_error(lambda: registry.resolve(MODEL_V2), "MEMORY_SCHEMA_INVALID", "VECTOR_PROFILE_INVALID")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        EmbeddingModelRegistry((FeatureHashingModel(), FeatureHashingModel()))
    with pytest.raises(ValueError):
        EmbeddingModelRegistry((type("Unpinned", (), {"pin": dict(PIN_FIELDS), "embed": lambda self, t: []})(),))


def _unit(dimensions: int = 4) -> list[float]:
    return [1.0 / math.sqrt(dimensions)] * dimensions


SMALL_PIN = EmbeddingModelPin(**{**PIN_FIELDS, "dimensions": 4})
INVALID_OUTPUTS = [
    ("not-a-sequence", 1.0, "REPRESENTATION_NOT_READY", "EMBEDDING_OUTPUT_INVALID"),
    ("string", "abcd", "REPRESENTATION_NOT_READY", "EMBEDDING_OUTPUT_INVALID"),
    ("bool-component", [True, 0.0, 0.0, 0.0], "REPRESENTATION_NOT_READY", "EMBEDDING_OUTPUT_INVALID"),
    ("nan-component", [math.nan, 0.0, 0.0, 1.0], "REPRESENTATION_NOT_READY", "EMBEDDING_OUTPUT_INVALID"),
    ("short", _unit(3), "MEMORY_SCHEMA_INVALID", "EMBEDDING_DIMENSION_MISMATCH"),
    ("long", _unit(5), "MEMORY_SCHEMA_INVALID", "EMBEDDING_DIMENSION_MISMATCH"),
    ("overflow-binary32", [1e300, 0.0, 0.0, 0.0], "MEMORY_SCHEMA_INVALID", "EMBEDDING_INVALID"),
    ("vanishes-binary32", [1e-50, 0.0, 0.0, 0.0], "REPRESENTATION_NOT_READY", "EMBEDDING_OUTPUT_INVALID"),
    ("not-unit", [0.5, 0.5, 0.5, 0.4], "REPRESENTATION_NOT_READY", "EMBEDDING_OUTPUT_INVALID"),
]


@pytest.mark.parametrize(("label", "output", "reason", "detail"), INVALID_OUTPUTS, ids=[c[0] for c in INVALID_OUTPUTS])
def test_model_output_must_fit_its_pin(label: str, output: Any, reason: str, detail: str) -> None:
    assert_error(lambda: _unit_vector(SMALL_PIN, output), reason, detail)


def test_a_unit_model_output_of_the_pinned_dimensions_is_accepted() -> None:
    assert _unit_vector(SMALL_PIN, _unit(4)) == tuple(_unit(4))
    assert _unit_vector(SMALL_PIN, [0, 1, 0, 0]) == (0.0, 1.0, 0.0, 0.0)


class BrokenModel(FeatureHashingModel):
    def __init__(self, mode: str) -> None:
        super().__init__()
        self.mode = mode

    def embed(self, text: str) -> list[float]:
        if self.mode == "outage":
            raise TimeoutError("embedding worker unavailable")
        values = super().embed(text)
        if self.mode == "nondeterministic" and self.calls % 2 == 0:
            values = list(reversed(values))
        if self.mode == "drift":
            self.pin = dataclasses.replace(self.pin, model_version="2-hotfix")
        return values


@pytest.mark.parametrize(
    ("mode", "reason", "detail"),
    [
        ("outage", "REPRESENTATION_NOT_READY", "EMBEDDING_WORKER_UNAVAILABLE"),
        ("nondeterministic", "REPRESENTATION_NOT_READY", "EMBEDDING_NONDETERMINISTIC"),
        ("drift", "INTERNAL_ERROR", "EMBEDDING_MODEL_DRIFT"),
    ],
)
def test_model_outage_nondeterminism_and_drift_fail_closed(mode: str, reason: str, detail: str) -> None:
    world = unit_world(models=(FixtureHashModel(), BrokenModel(mode)))
    assert_error(lambda: world.coordinator.embed_query(PROFILE_V2, "convoy route"), reason, detail)


def test_query_embedding_uses_exactly_the_pinned_model() -> None:
    world = unit_world()
    assert world.coordinator.embed_query(PROFILE_V2, "Convoy route") == tuple(V2.embed("convoy ROUTE"))
    assert world.coordinator.embed_query(PROFILE_V1, "convoy route") == tuple(base.embed("convoy route"))
    assert_error(lambda: world.coordinator.embed_query(PROFILE_V2, "  "), "MEMORY_SCHEMA_INVALID", "QUERY_INVALID")
    unpinned = dataclasses.replace(PROFILE_V2, embedding_dimensions=8)
    assert_error(lambda: world.coordinator.embed_query(unpinned, "convoy"), "UNSUPPORTED_CAPABILITY", "EMBEDDING_MODEL_UNPINNED")


def _descriptor() -> EmbeddingDescriptor:
    world = unit_world()
    record = world.admit("unit-1", "convoy route")
    values = V2.embed("convoy route")
    return EmbeddingDescriptor.build(record.item, record.item_digest, MemoryPartition.for_item(record.item), PIN_V2, values)


def test_descriptor_binds_source_partition_purpose_marking_and_full_pin() -> None:
    world = unit_world()
    record = world.admit("unit-1", "convoy route")
    values = V2.embed("convoy route")
    descriptor = EmbeddingDescriptor.build(record.item, record.item_digest, MemoryPartition.for_item(record.item), PIN_V2, values)
    assert descriptor.memory_version_ref == record.item.version_ref and descriptor.item_digest == record.item_digest
    assert descriptor.content_digest == record.item.content_digest
    assert descriptor.partition_digest == MemoryPartition.for_item(record.item).digest
    assert (descriptor.purpose, descriptor.classification_marking_ref) == (record.item.purpose, record.item.classification_marking_ref)
    assert descriptor.pin == PIN_V2 and descriptor.representation_version == PIN_V2.representation_version
    assert descriptor.embedding_digest == vector_digest(values) and descriptor.stored_vector_digest == stored_vector_digest(values)
    assert descriptor.store_ref == EMBEDDING_PREFIX + descriptor.digest.removeprefix("urn:sha256:")
    assert EmbeddingDescriptor.from_mapping(descriptor.to_mapping()) == descriptor
    for name, value in descriptor.to_mapping().items():
        changed = value + 1 if isinstance(value, int) else (d(str(value)) if str(value).startswith("urn:sha256:") else f"{value}-x")
        assert dataclasses.replace(descriptor, **{name: changed}).digest != descriptor.digest, name
    assert "vector" not in json.dumps(descriptor.to_mapping()).replace("stored_vector_digest", "")


DESCRIPTOR_MUTATIONS = [
    ("extra-field", lambda m: {**m, "raw_vector": [0.1]}),
    ("missing-field", lambda m: {k: v for k, v in m.items() if k != "tokenizer_digest"}),
    ("empty-string", lambda m: {**m, "purpose": ""}),
    ("non-digest", lambda m: {**m, "embedding_digest": "sha256:1"}),
    ("dimensions-bool", lambda m: {**m, "dimensions": True}),
    ("dimensions-zero", lambda m: {**m, "dimensions": 0}),
    ("not-a-mapping", lambda m: [m]),
]


@pytest.mark.parametrize(("label", "mutate"), DESCRIPTOR_MUTATIONS, ids=[c[0] for c in DESCRIPTOR_MUTATIONS])
def test_descriptors_are_closed_records(label: str, mutate: Any) -> None:
    assert_error(lambda: EmbeddingDescriptor.from_mapping(mutate(_descriptor().to_mapping())), "INTERNAL_ERROR", "DESCRIPTOR_INVALID")


def _record(**changes: Any) -> RepresentationRecord:
    descriptor = _descriptor()
    fields: dict[str, Any] = {
        "partition_digest": descriptor.partition_digest,
        "representation_version": PIN_V2.representation_version,
        "pin": PIN_V2,
        "state": RepresentationState.ACTIVE,
        "manifest_digest": manifest_digest(descriptor.partition_digest, PIN_V2, [descriptor]),
        "audit_ref": d("audit:rebuild-1"),
        "entries": ((descriptor.memory_version_ref, descriptor.store_ref),),
        "operation_id": "rebuild-1",
        "updated_at": format_utc_timestamp(NOW),
    }
    fields.update(changes)
    return RepresentationRecord(**fields)


RECORD_MUTATIONS = [
    ("extra-field", lambda m: {**m, "extra": 1}),
    ("pin-invalid", lambda m: {**m, "pin": {**m["pin"], "dimensions": 0}}),
    ("pin-not-mapping", lambda m: {**m, "pin": "pin"}),
    ("state-unknown", lambda m: {**m, "state": "RETIRED"}),
    ("entry-shape", lambda m: {**m, "entries": [["only-one"]]}),
    ("entries-unsorted", lambda m: {**m, "entries": [["z", "a"], ["a", "z"]]}),
    ("active-without-manifest", lambda m: {**m, "manifest_digest": None}),
    ("building-with-manifest", lambda m: {**m, "state": "BUILDING", "audit_ref": None}),
    ("active-without-audit-ref", lambda m: {**m, "audit_ref": None}),
    ("building-with-audit-ref", lambda m: {**m, "state": "BUILDING", "manifest_digest": None}),
    ("audit-ref-not-digest", lambda m: {**m, "audit_ref": "audit:1"}),
    ("manifest-not-digest", lambda m: {**m, "manifest_digest": "abc"}),
    ("version-not-pin", lambda m: {**m, "representation_version": PIN_V1.representation_version}),
    ("operation-empty", lambda m: {**m, "operation_id": ""}),
]


@pytest.mark.parametrize(("label", "mutate"), RECORD_MUTATIONS, ids=[c[0] for c in RECORD_MUTATIONS])
def test_representation_records_are_closed_and_canonical(label: str, mutate: Any) -> None:
    record = _record()
    assert RepresentationRecord.from_mapping(json.loads(canonical_bytes(record.to_mapping()))) == record
    assert_error(
        lambda: RepresentationRecord.from_mapping(mutate(json.loads(canonical_bytes(record.to_mapping())))),
        "INTERNAL_ERROR",
        "REPRESENTATION_RECORD_INVALID",
    )


def test_manifest_digest_depends_on_sources_and_pin_only() -> None:
    first = _descriptor()
    second = dataclasses.replace(first, memory_version_ref="urn:ocor:memory:unit-2:v1")
    digest = manifest_digest(first.partition_digest, PIN_V2, [first, second])
    assert digest == manifest_digest(first.partition_digest, PIN_V2, [second, first])
    assert digest != manifest_digest(first.partition_digest, PIN_V2, [first])
    assert digest != manifest_digest(d("other-partition"), PIN_V2, [first, second])
    assert digest != manifest_digest(first.partition_digest, dataclasses.replace(PIN_V2, tokenizer_digest=d("tok")), [first, second])


def test_an_index_entry_binds_only_its_descriptor_and_binary32_vector() -> None:
    descriptor = _descriptor()
    values = tuple(V2.embed("convoy route"))
    payload = descriptor.to_mapping()
    assert _entry_binds(IndexEntry(payload, values), descriptor)
    assert not _entry_binds(None, descriptor)
    assert not _entry_binds(IndexEntry({**payload, "purpose": "other"}, values), descriptor)
    assert not _entry_binds(IndexEntry(payload, "text"), descriptor)
    assert not _entry_binds(IndexEntry(payload, values[:-1]), descriptor)
    assert not _entry_binds(IndexEntry(payload, (True,) + values[1:]), descriptor)
    assert not _entry_binds(IndexEntry(payload, (math.inf,) + values[1:]), descriptor)
    assert not _entry_binds(IndexEntry(payload, (1e300,) + values[1:]), descriptor)
    assert not _entry_binds(IndexEntry(payload, tuple(reversed(values))), descriptor)


def test_parallel_layouts_never_share_a_native_layout_key() -> None:
    for pin in (PIN_V1, PIN_V2):
        layout = ParallelLayout.of(pin)
        assert layout.representation_version != pin.representation_version
        assert layout.embedding_dimensions == pin.dimensions
    assert ParallelLayout.of(PIN_V1) != ParallelLayout.of(PIN_V2)


def test_unit_rebuild_and_search_branch_logic() -> None:
    world = unit_world()
    records = populate(world)
    receipt = world.rebuild(records[0])
    assert [ref for ref, _ in receipt.entries] == sorted(r.item.version_ref for r in records)
    assert world.representations.record(MemoryPartition.for_item(records[0].item).digest, PIN_V2.representation_version).state is RepresentationState.ACTIVE
    found = world.search_v2("supply route")
    assert refs(found)[0] in {"urn:ocor:memory:conv-1:v1", "urn:ocor:memory:conv-2:v1"}
    assert world.coordinator.metrics()[("rebuild", "OK")] == 1


def test_operation_id_and_limit_are_validated() -> None:
    world = unit_world()
    record = world.admit("unit-1", "convoy route")
    ref = MemoryPartition.for_item(record.item).ref
    for operation in ("", " op", None):
        assert_error(
            lambda operation=operation: world.coordinator.rebuild(ref, PROFILE_V2, binding=binding(), operation_id=operation),  # type: ignore[arg-type]
            "MEMORY_SCHEMA_INVALID",
            "OPERATION_ID_INVALID",
        )
    world.rebuild(record)
    vector = world.coordinator.embed_query(PROFILE_V2, "convoy")
    partition = MemoryPartition.for_item(record.item)
    for limit in (0, True, "1"):
        assert_error(
            lambda limit=limit: world.coordinator.vector_candidates(partition, PROFILE_V2, vector, limit=limit),  # type: ignore[arg-type]
            "MEMORY_SCHEMA_INVALID",
            "QUERY_INVALID",
        )
    assert_error(lambda: world.coordinator.vector_candidates(partition, PROFILE_V2, "abc", limit=1), "MEMORY_SCHEMA_INVALID", "QUERY_INVALID")  # type: ignore[arg-type]
    assert_error(lambda: world.coordinator.vector_candidates(partition, PROFILE_V2, vector[:-1], limit=1), "MEMORY_SCHEMA_INVALID", "EMBEDDING_DIMENSION_MISMATCH")
    assert len(world.coordinator.vector_candidates(partition, PROFILE_V2, vector, limit=1)) == 1


def test_metrics_use_a_bounded_label_set() -> None:
    world = unit_world()
    record = world.admit("unit-1", "convoy route")
    world.rebuild(record)
    assert_error(lambda: world.coordinator.rebuild("urn:ocor:memory-partition:none", PROFILE_V2, binding=None, operation_id="x"), "AUTHENTICATION_REQUIRED", "BINDING_MISSING")
    assert_error(lambda: world.coordinator.rebuild("urn:ocor:memory-partition:none", PROFILE_V2, binding=binding(), operation_id="x"), "POLICY_DENIED", "PARTITION_NOT_AUTHORIZED")
    labels = set(world.coordinator.metrics())
    assert labels <= {(op, outcome) for op in ("rebuild", "invalidate", "vector_candidates") for outcome in ("OK", "AUTHENTICATION_REQUIRED", "POLICY_DENIED")}
    assert all(len(label) == 2 and "urn:" not in "".join(label) for label in labels)


def test_invalidation_requires_an_active_representation_of_the_same_pin() -> None:
    world = unit_world()
    record = world.admit("unit-1", "convoy route")
    assert_error(lambda: world.invalidate(record), "REPRESENTATION_NOT_READY", "REPRESENTATION_ABSENT")
    world.rebuild(record)
    partition = MemoryPartition.for_item(record.item)
    active = world.representations.record(partition.digest, PIN_V2.representation_version)
    world.representations.records[(partition.digest, PIN_V2.representation_version)] = dataclasses.replace(
        active, state=RepresentationState.BUILDING, manifest_digest=None
    )
    assert_error(lambda: world.invalidate(record), "REPRESENTATION_NOT_READY", "REPRESENTATION_REBUILDING")
    world.representations.records[(partition.digest, PIN_V2.representation_version)] = active
    store_ref = active.entries[0][1]
    kept = world.representations.items.pop(store_ref)
    assert_error(lambda: world.invalidate(record), "INTERNAL_ERROR", "DESCRIPTOR_MISSING")
    world.representations.items[store_ref] = kept
    original = world.parallel.inner.entries
    world.parallel.inner.entries = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("index down"))
    assert_error(lambda: world.invalidate(record), "REPRESENTATION_NOT_READY", "INVALIDATION_INCOMPLETE")
    world.parallel.inner.entries = original
    receipt = world.invalidate(record)
    assert receipt.invalidated == () and receipt.manifest_digest == active.manifest_digest


def test_unacknowledged_index_or_descriptor_writes_leave_the_representation_building() -> None:
    world = unit_world()
    record = world.admit("unit-1", "convoy route")
    original_upsert = world.parallel.inner.upsert
    world.parallel.inner.upsert = lambda *a, **k: None  # acknowledges without writing
    assert_error(lambda: world.rebuild(record), "REPRESENTATION_NOT_READY", "PROJECTION_UNVERIFIED")
    world.parallel.inner.upsert = original_upsert
    original_put = world.representations.put_descriptor
    world.representations.put_descriptor = lambda descriptor: None  # type: ignore[method-assign]
    assert_error(lambda: world.rebuild(record, op="rebuild-2"), "REPRESENTATION_NOT_READY", "DESCRIPTOR_UNVERIFIED")
    partition = MemoryPartition.for_item(record.item)
    assert world.representations.record(partition.digest, PIN_V2.representation_version).state is RepresentationState.BUILDING
    world.representations.put_descriptor = original_put  # type: ignore[method-assign]
    assert world.rebuild(record, op="rebuild-3").entries


def test_foreign_or_stale_descriptors_never_occupy_a_candidate_slot() -> None:
    world = unit_world()
    records = populate(world)
    receipt = world.rebuild(records[0])
    partition = MemoryPartition.for_item(records[0].item)
    other = world.admit("other-1", "supply route", ctx=context(compartments=("bravo",)))
    other_partition = MemoryPartition.for_item(other.item)
    layout = ParallelLayout.of(PIN_V2)
    text = "supply route"
    query = world.coordinator.embed_query(PROFILE_V2, text)
    baseline = world.coordinator.vector_candidates(partition, PROFILE_V2, query, limit=10)
    foreign = EmbeddingDescriptor.build(other.item, other.item_digest, other_partition, PIN_V2, V2.embed(text))
    outsider = dataclasses.replace(
        EmbeddingDescriptor.build(records[0].item, records[0].item_digest, partition, PIN_V2, V2.embed(text)),
        memory_version_ref="urn:ocor:memory:ghost:v1",
    )
    for descriptor in (foreign, outsider):
        world.parallel.inner.upsert(partition, layout, descriptor.store_ref, descriptor.to_mapping(), V2.embed(text))
    # A well-formed descriptor of a current version that is not in the manifest
    # (a shadow embedding) is unbound: skipped, never ranked.
    shadow = EmbeddingDescriptor.build(records[1].item, records[1].item_digest, partition, PIN_V2, V2.embed(text))
    assert shadow.store_ref not in {store_ref for _, store_ref in receipt.entries}
    world.parallel.inner.upsert(partition, layout, shadow.store_ref, shadow.to_mapping(), V2.embed(text))
    hits = world.coordinator.vector_candidates(partition, PROFILE_V2, query, limit=10)
    assert hits == baseline and len(hits) >= 2
    assert {hit.store_ref for hit in hits} <= {store_ref for _, store_ref in receipt.entries}
    assert {hit.memory_version_ref for hit in hits} <= {r.item.version_ref for r in records}
    assert all(hit.representation_version == PIN_V2.representation_version for hit in hits)


def test_a_rebuild_of_an_active_representation_blocks_retrieval_until_it_completes() -> None:
    world = unit_world()
    record = world.admit("unit-1", "convoy route")
    world.rebuild(record)
    assert len(world.search_v2("convoy route").hits) == 1
    world.admit("unit-2", "convoy route north")
    original = world.parallel.inner.upsert
    world.parallel.inner.upsert = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("index down"))
    assert_error(lambda: world.rebuild(record, op="rebuild-2"), "REPRESENTATION_NOT_READY", "REBUILD_INCOMPLETE")
    partition = MemoryPartition.for_item(record.item)
    assert world.representations.record(partition.digest, PIN_V2.representation_version).state is RepresentationState.BUILDING
    assert_error(lambda: world.search_v2("convoy route"), "REPRESENTATION_NOT_READY", "REPRESENTATION_REBUILDING")
    world.parallel.inner.upsert = original
    assert len(world.rebuild(record, op="rebuild-3").entries) == 2
    assert len(world.search_v2("convoy route").hits) == 2


def test_an_unbound_backlog_beyond_the_scan_bound_fails_closed() -> None:
    from ocor_runtime.memory.stores import StoreLimits

    world = unit_world()
    record = world.admit("unit-1", "convoy route")
    world.coordinator = world.build(limits=StoreLimits(page_size=2, max_scanned_hits=4))
    world.rebuild(record)
    partition = MemoryPartition.for_item(record.item)
    vector = world.coordinator.embed_query(PROFILE_V2, "convoy route")
    for index in range(6):
        world.parallel.inner.upsert(partition, ParallelLayout.of(PIN_V2), f"urn:ocor:stray:{index}", {"stray": index}, [2.0 * v for v in vector])
    assert_error(
        lambda: world.coordinator.vector_candidates(partition, PROFILE_V2, vector, limit=1),
        "REPRESENTATION_NOT_READY",
        "UNBOUND_BACKLOG",
    )
    world.rebuild(record, op="rebuild-sweep")
    assert len(world.coordinator.vector_candidates(partition, PROFILE_V2, vector, limit=1)) == 1


def test_markings_outside_the_lattice_and_invalid_decisions_fail_closed() -> None:
    world = unit_world()
    record = world.admit("unit-1", "convoy route")
    assert_error(lambda: world.rebuild(record, ctx=context(marking=d("marking:UNKNOWN"))), "POLICY_DENIED", "PARTITION_NOT_AUTHORIZED")

    class NoDecision(RepresentationGrant):
        def authorize_representation(self, partition: MemoryPartition, pin: EmbeddingModelPin, ctx: GovernedContext) -> MemoryPolicyDecision:
            return {"permitted": True}  # type: ignore[return-value]

    class Refusal(RepresentationGrant):
        def authorize_representation(self, partition: MemoryPartition, pin: EmbeddingModelPin, ctx: GovernedContext) -> MemoryPolicyDecision:
            raise MemoryEmbeddingError("AUTHORITY_DENIED", "SCOPE_NOT_DELEGATED", "scope owner not delegated")

    world.coordinator = world.build(policy=NoDecision())
    assert_error(lambda: world.rebuild(record), "CONTROL_PLANE_UNAVAILABLE", "POLICY_DECISION_INVALID")
    world.coordinator = world.build(policy=Refusal())
    assert_error(lambda: world.rebuild(record), "AUTHORITY_DENIED", "SCOPE_NOT_DELEGATED")
    partition = MemoryPartition.for_item(record.item)
    assert world.representations.record(partition.digest, PIN_V2.representation_version) is None


def test_unit_every_refusal_writes_a_denial_event() -> None:
    world = unit_world()
    record = world.admit("unit-1", "convoy route")
    partition = MemoryPartition.for_item(record.item)
    vector = world.coordinator.embed_query(PROFILE_V2, "convoy route")
    assert_denied(world, INVALIDATE, lambda: world.invalidate(record), "REPRESENTATION_NOT_READY", "REPRESENTATION_ABSENT")
    assert_denied(world, INVALIDATE, lambda: world.coordinator.invalidate(partition.ref, PROFILE_V2, binding=None, operation_id="x"), "AUTHENTICATION_REQUIRED", "BINDING_MISSING")
    assert_denied(world, REBUILD, lambda: world.rebuild(record, op=" padded"), "MEMORY_SCHEMA_INVALID", "OPERATION_ID_INVALID")
    assert_denied(world, SEARCH, lambda: world.coordinator.vector_candidates(partition, PROFILE_V2, vector[:-1], limit=1), "MEMORY_SCHEMA_INVALID", "EMBEDDING_DIMENSION_MISMATCH")
    world.rebuild(record)
    active = world.representations.record(partition.digest, PIN_V2.representation_version)
    key = (partition.digest, PIN_V2.representation_version)
    world.representations.records[key] = dataclasses.replace(active, state=RepresentationState.BUILDING, manifest_digest=None, audit_ref=None)
    assert_denied(world, INVALIDATE, lambda: world.invalidate(record), "REPRESENTATION_NOT_READY", "REPRESENTATION_REBUILDING")
    assert_denied(world, SEARCH, lambda: world.coordinator.vector_candidates(partition, PROFILE_V2, vector, limit=1), "REPRESENTATION_NOT_READY", "REPRESENTATION_REBUILDING")
    world.representations.records[key] = dataclasses.replace(active, pin=dataclasses.replace(PIN_V2, tokenizer_digest=d("tokenizer:other")))
    assert_denied(world, INVALIDATE, lambda: world.invalidate(record), "REPRESENTATION_NOT_READY", "REPRESENTATION_VERSION_MIXED")
    assert_denied(world, SEARCH, lambda: world.coordinator.vector_candidates(partition, PROFILE_V2, vector, limit=1), "REPRESENTATION_NOT_READY", "REPRESENTATION_VERSION_MIXED")
    world.representations.records[key] = active
    late = world.admit("unit-2", "convoy route north")
    assert_denied(world, SEARCH, lambda: world.coordinator.vector_candidates(partition, PROFILE_V2, vector, limit=1), "REPRESENTATION_NOT_READY", "REPRESENTATION_INCOMPLETE")
    world.rebuild(late, op="rebuild-2")
    store_ref = dict(world.representations.record(*key).entries)[record.item.version_ref]
    descriptor = world.representations.items[store_ref]
    world.representations.items[store_ref] = dataclasses.replace(descriptor, embedding_digest=d("tampered"))
    assert_denied(world, SEARCH, lambda: world.coordinator.vector_candidates(partition, PROFILE_V2, vector, limit=2), "REPRESENTATION_NOT_READY", "PROJECTION_DRIFT")
    event = world.rep_audit.events[-1]
    assert (event["partition_ref"], event["representation_version"]) == (partition.ref, PIN_V2.representation_version)
    # An unaudited denial still fails closed.
    world.rep_audit.fail = True
    assert_error(lambda: world.coordinator.vector_candidates(partition, PROFILE_V2, vector, limit=2), "CONTROL_PLANE_UNAVAILABLE", "AUDIT_UNAVAILABLE")
    world.rep_audit.fail = False
    world.rebuild(record, op="rebuild-repair")
    assert len(world.coordinator.vector_candidates(partition, PROFILE_V2, vector, limit=2)) == 2
    assert [e["operation_id"] for e in successes(world, REBUILD)] == ["rebuild-1", "rebuild-2", "rebuild-repair"]


def interloper_after_building(world: World, record: AdmittedMemoryVersion) -> dict[str, Any]:
    """Replace the BUILDING record by a concurrent operation right after it is written."""

    partition = MemoryPartition.for_item(record.item)
    inner = world.parallel.inner
    original = inner.upsert
    seen: dict[str, Any] = {}

    def upsert(*args: Any, **kwargs: Any) -> None:
        if "interloper" not in seen:
            building = world.representations.record(partition.digest, PIN_V2.representation_version)
            assert building is not None and building.state is RepresentationState.BUILDING
            interloper = dataclasses.replace(building, operation_id="interloper")
            world.representations.put_record(interloper, expected_digest=building.digest)
            seen["interloper"] = interloper
        original(*args, **kwargs)

    inner.upsert = upsert
    seen["restore"] = lambda: setattr(inner, "upsert", original)
    return seen


def check_lost_compare_and_set(world: World, records: Sequence[AdmittedMemoryVersion]) -> None:
    partition = MemoryPartition.for_item(records[0].item)
    seen = interloper_after_building(world, records[0])
    assert_denied(world, REBUILD, lambda: world.rebuild(records[0]), "MEMORY_IDEMPOTENCY_CONFLICT", "REPRESENTATION_RECORD_CONFLICT")
    seen["restore"]()
    assert successes(world, REBUILD) == []
    record = world.representations.record(partition.digest, PIN_V2.representation_version)
    assert record == seen["interloper"] and record.state is RepresentationState.BUILDING and record.manifest_digest is None
    assert_error(lambda: world.search_v2("supply route"), "REPRESENTATION_NOT_READY", "REPRESENTATION_REBUILDING")
    receipt = world.rebuild(records[0], op="rebuild-2")
    assert [(e["operation_id"], e["audit_ref"]) for e in successes(world, REBUILD)] == [("rebuild-2", receipt.audit_ref)]
    final = world.representations.record(partition.digest, PIN_V2.representation_version)
    assert final.state is RepresentationState.ACTIVE and final.operation_id == "rebuild-2" and final.manifest_digest == receipt.manifest_digest
    # The same race on invalidation leaves the ACTIVE interloper and no success receipt.
    active = world.representations.record(partition.digest, PIN_V2.representation_version)
    inner = world.parallel.inner
    original = inner.entries

    def entries(*args: Any, **kwargs: Any) -> Any:
        current = world.representations.record(partition.digest, PIN_V2.representation_version)
        if current == active:
            world.representations.put_record(dataclasses.replace(active, operation_id="interloper-2"), expected_digest=active.digest)
        return original(*args, **kwargs)

    inner.entries = entries
    assert_denied(world, INVALIDATE, lambda: world.invalidate(records[0]), "MEMORY_IDEMPOTENCY_CONFLICT", "REPRESENTATION_RECORD_CONFLICT")
    inner.entries = original
    assert successes(world, INVALIDATE) == []
    assert world.representations.record(partition.digest, PIN_V2.representation_version).operation_id == "interloper-2"


def test_unit_a_lost_compare_and_set_leaves_no_success_receipt() -> None:
    world = unit_world()
    check_lost_compare_and_set(world, populate(world))


def check_validity_window(world: World) -> None:
    keep = world.admit("keep", "lighthouse beacon signal keep")
    world.admit("elapsed", "lighthouse beacon signal elapsed", valid_until=NOW + timedelta(seconds=30))
    world.admit("future", "lighthouse beacon signal future", valid_from=NOW + timedelta(hours=1))
    receipt = world.rebuild(keep)
    # Descriptors exist for every current version: the window is evaluated per query.
    assert [ref.split(":")[3] for ref, _ in receipt.entries] == ["elapsed", "future", "keep"]
    world.clock.advance(timedelta(minutes=2))
    partition = MemoryPartition.for_item(keep.item)
    vector = world.coordinator.embed_query(PROFILE_V2, "lighthouse beacon signal")

    def names(**kwargs: Any) -> list[str]:
        hits = world.coordinator.vector_candidates(partition, PROFILE_V2, vector, limit=10, **kwargs)
        return sorted(hit.memory_version_ref.split(":")[3] for hit in hits)

    assert names() == ["keep"]
    assert names(valid_at=NOW) == ["elapsed", "keep"]  # historic instant: the elapsed version was valid
    assert refs(world.search_v2("lighthouse beacon signal")) == ["urn:ocor:memory:keep:v1"]
    # The search service hands its valid_at to the representation lookup: the
    # version valid at that historic instant is found, the not-yet-valid one is not.
    historic = world.search_v2("lighthouse beacon signal", valid_at=format_utc_timestamp(NOW))
    assert sorted(refs(historic)) == ["urn:ocor:memory:elapsed:v1", "urn:ocor:memory:keep:v1"]
    assert denials(world, SEARCH) == []
    assert_denied(world, SEARCH, lambda: names(valid_at="2026-01-01T00:00:00Z"), "MEMORY_SCHEMA_INVALID", "QUERY_INVALID")
    world.clock.advance(timedelta(hours=1))
    # The future version enters its window without any rebuild: the representation stays complete.
    assert names() == ["future", "keep"]
    assert sorted(refs(world.search_v2("lighthouse beacon signal"))) == ["urn:ocor:memory:future:v1", "urn:ocor:memory:keep:v1"]
    # At the historic instant the future version was not yet valid.
    assert sorted(refs(world.search_v2("lighthouse beacon signal", valid_at=format_utc_timestamp(NOW)))) == ["urn:ocor:memory:elapsed:v1", "urn:ocor:memory:keep:v1"]


def test_unit_versions_outside_their_validity_window_never_occupy_a_candidate_slot() -> None:
    check_validity_window(unit_world())


# --------------------------------------------------------------------------
# Real backends (qualifying): PostgreSQL, Qdrant and OpenBao
# --------------------------------------------------------------------------


class OpenBaoHarness(base.OpenBaoHarness):
    PREFIX = "ocor-test-0053-openbao-"


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

    def world(self, *, schema: str | None = None, models: Sequence[Any] | None = None) -> World:
        if schema is None:
            schema = f"ocor_t0053_{uuid.uuid4().hex[:12]}"
            self.schemas.append(schema)
        postgres = base.PostgresStores(self.dsn, schema)
        return World(
            metadata=postgres,
            content=base.PostgresContentStore(postgres),
            lexical=base.PostgresLexicalIndex(postgres),
            vector=t52.CompactQdrantVectorIndex(self.qdrant.endpoint, schema),
            cipher=base.OpenBaoTransitCipher(self.bao),
            representations=PostgresRepresentationStore(self.dsn, schema),
            parallel=t52.CompactQdrantVectorIndex(self.qdrant.endpoint, schema),
            models=models,
        )

    def fresh(self, world: World, *, models: Sequence[Any] | None = None) -> World:
        """New adapter instances and connections over the same backends, ledger and audit store."""

        clone = self.world(schema=world.metadata.schema, models=models)
        clone.ledger = world.ledger
        clone.clock = world.clock
        clone.rep_audit = world.rep_audit
        clone.coordinator = clone.build()
        return clone


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


def source_snapshot(world: World) -> dict[str, Any]:
    """Every byte of source memory: metadata, content, lexical tables and native vectors."""

    schema = world.metadata.schema
    snapshot: dict[str, Any] = {}

    def rows(conn: psycopg.Connection[Any], table: str) -> list[tuple[Any, ...]]:
        found = conn.execute(f'SELECT * FROM "{schema}"."{table}" ORDER BY 1, 2').fetchall()
        return [tuple(bytes(c) if isinstance(c, memoryview) else c for c in row) for row in found]

    with world.metadata.connect() as conn:
        for table in ("partitions", "versions", "pointers", "heads", "content", "lexical_layouts"):
            snapshot[table] = rows(conn, table)
        for (name,) in conn.execute(f'SELECT table_name FROM "{schema}".lexical_layouts ORDER BY 1').fetchall():
            snapshot[f"lexical:{name}"] = rows(conn, name)
    native = world.vector.inner
    for partition in world.metadata.partitions():
        for version in sorted({PROFILE_V1.representation_version, PROFILE_V2.representation_version}):
            entries = []
            for hit in native.entries(partition, version):
                entry = native.read_back(partition, version, hit.store_ref)
                entries.append((hit.store_ref, json.dumps(dict(entry.payload), sort_keys=True), entry.body))
            snapshot[f"vector:{partition.digest}:{version}"] = sorted(entries)
    return snapshot


def parallel_entries(world: World, record: AdmittedMemoryVersion, pin: EmbeddingModelPin = PIN_V2) -> dict[str, Any]:
    partition = MemoryPartition.for_item(record.item)
    layout = ParallelLayout.of(pin).representation_version
    index = world.parallel.inner
    out = {}
    for hit in index.entries(partition, layout):
        entry = index.read_back(partition, layout, hit.store_ref)
        out[hit.store_ref] = (dict(entry.payload), stored_vector_digest(entry.body))
    return out


def test_qualifying_backends_are_real_and_pinned(backends: Backends) -> None:
    assert base.QDRANT_IMAGE.endswith(base.LOCKED_IMAGES["qdrant"].split("@", 1)[1])
    assert base._docker("inspect", backends.qdrant.container, "--format", "{{.Config.Image}}") == base.QDRANT_IMAGE
    assert base._docker("inspect", backends.bao.container, "--format", "{{.Config.Image}}") == base.LOCKED_IMAGES["openbao"]
    with psycopg.connect(backends.dsn) as conn:
        row = conn.execute("SHOW server_version").fetchone()
    assert row is not None and str(row[0]).startswith("16.")
    world = backends.world()
    assert isinstance(world.parallel.inner, base.QdrantVectorIndex) and isinstance(world.vector.inner, base.QdrantVectorIndex)
    assert isinstance(world.representations, PostgresRepresentationStore)
    assert isinstance(world.cipher, base.OpenBaoTransitCipher) and not isinstance(world.metadata, base.MemMetadata)


def test_model_upgrade_builds_a_parallel_representation_bound_to_every_pin(backends: Backends) -> None:
    world = backends.world()
    records = populate(world)
    before_v1 = world.search_v1("convoy moving along the northern supply route")
    receipt = world.rebuild(records[0])
    partition = MemoryPartition.for_item(records[0].item)
    assert receipt.partition_ref == partition.ref and receipt.representation_version == PIN_V2.representation_version
    assert receipt.pin_digest == PIN_V2.digest and receipt.invalidated == ()
    assert [ref for ref, _ in receipt.entries] == sorted(r.item.version_ref for r in records)
    record = world.representations.record(partition.digest, PIN_V2.representation_version)
    assert record is not None and record.state is RepresentationState.ACTIVE and record.manifest_digest == receipt.manifest_digest
    stored = parallel_entries(world, records[0])
    assert set(stored) == {store_ref for _, store_ref in receipt.entries}
    by_ref = {r.item.version_ref: r for r in records}
    for store_ref, (payload, binary32) in stored.items():
        descriptor = EmbeddingDescriptor.from_mapping(payload)
        source = by_ref[descriptor.memory_version_ref]
        text = dict(CORPUS)[source.item.memory_item_id]
        assert descriptor == world.representations.descriptor(store_ref)
        assert (descriptor.item_digest, descriptor.content_digest) == (source.item_digest, source.item.content_digest)
        assert descriptor.pin == PIN_V2 and descriptor.partition_digest == partition.digest
        assert (descriptor.purpose, descriptor.classification_marking_ref) == (source.item.purpose, source.item.classification_marking_ref)
        assert descriptor.embedding_digest == vector_digest(V2.embed(text)) and binary32 == descriptor.stored_vector_digest
    # The upgraded representation is searched only under its own pin.
    upgraded = world.search_v2("supply route")
    assert set(refs(upgraded)[:2]) == {"urn:ocor:memory:conv-1:v1", "urn:ocor:memory:conv-2:v1"}
    assert upgraded.receipt["representation_versions"] == {"VECTOR": PIN_V2.representation_version}
    assert "vector" not in json.dumps(upgraded.to_mapping()).replace("vector_digest", "").replace("\"vector\":", "")
    # The native v1 representation keeps answering exactly as before the upgrade.
    assert world.search_v1("convoy moving along the northern supply route").to_mapping() == before_v1.to_mapping()
    audit = world.rep_audit.events[-1]
    assert audit["action"] == "rebuildEmbeddingRepresentation" and audit["manifest_digest"] == receipt.manifest_digest
    assert (audit["operation_id"], audit["causation_id"], audit["correlation_id"]) == ("rebuild-1", "rebuild-1", CALLER.correlation_id)
    assert audit["pin"] == PIN_V2.to_mapping() and audit["embedded_count"] == 3 and audit["audit_ref"] == receipt.audit_ref


def test_rebuild_never_changes_immutable_memory_or_native_projections(backends: Backends) -> None:
    world = backends.world()
    records = populate(world)
    before = source_snapshot(world)
    digests = [world.metadata.get(r.item.memory_item_id, 1).staged.item_digest for r in records]
    world.vector.calls.clear()
    world.lexical.calls.clear()
    world.rebuild(records[0])
    world.rebuild(records[0], op="rebuild-2")
    world.invalidate(records[0])
    after = source_snapshot(world)
    assert after == before
    assert [world.metadata.get(r.item.memory_item_id, 1).staged.item_digest for r in records] == digests
    assert all(world.metadata.head(r.item.memory_item_id) == 1 for r in records)
    assert all(call[0] != "upsert" and call[0] != "remove" for call in world.vector.calls + world.lexical.calls)


def test_rebuild_is_deterministic_across_runs_adapters_and_fresh_stores(backends: Backends) -> None:
    world = backends.world()
    records = populate(world)
    first = world.rebuild(records[0])
    stored = parallel_entries(world, records[0])
    second = world.rebuild(records[0], op="rebuild-2")
    assert (second.manifest_digest, second.entries) == (first.manifest_digest, first.entries)
    assert parallel_entries(world, records[0]) == stored
    clone = backends.fresh(world)
    third = clone.rebuild(records[0], op="rebuild-3")
    assert (third.manifest_digest, third.entries) == (first.manifest_digest, first.entries)
    other = backends.world()
    reversed_records = populate(other, tuple(reversed(CORPUS)))
    fourth = other.rebuild(reversed_records[0], op="rebuild-elsewhere")
    assert (fourth.manifest_digest, fourth.entries) == (first.manifest_digest, first.entries)
    assert parallel_entries(other, reversed_records[0]) == stored
    response = clone.search_v2("radar contact eastern ridge")
    assert refs(response)[0] == "urn:ocor:memory:conv-3:v1"
    assert response.to_mapping()["hits"] == other.search_v2("radar contact eastern ridge").to_mapping()["hits"]


def test_an_interrupted_rebuild_fails_retrieval_closed_then_resumes_to_the_same_manifest(backends: Backends) -> None:
    clean = backends.world()
    expected = clean.rebuild(populate(clean)[0], op="clean")
    world = backends.world()
    records = populate(world)
    inner = world.parallel.inner
    original = inner.upsert
    writes = {"n": 0}

    def crash_after_first(*args: Any, **kwargs: Any) -> None:
        writes["n"] += 1
        if writes["n"] > 1:
            raise ConnectionError("qdrant unavailable")
        original(*args, **kwargs)

    inner.upsert = crash_after_first
    assert_error(lambda: world.rebuild(records[0]), "REPRESENTATION_NOT_READY", "REBUILD_INCOMPLETE")
    partition = MemoryPartition.for_item(records[0].item)
    record = world.representations.record(partition.digest, PIN_V2.representation_version)
    assert record is not None and record.state is RepresentationState.BUILDING and record.manifest_digest is None
    assert len(parallel_entries(world, records[0])) == 1
    assert_error(lambda: world.search_v2("supply route"), "REPRESENTATION_NOT_READY", "REPRESENTATION_REBUILDING")
    assert_error(lambda: world.search_v2("supply route", mode=RetrievalMode.HYBRID), "REPRESENTATION_NOT_READY", "REPRESENTATION_REBUILDING")
    assert len(world.search_v1("supply route").hits) == 3  # the native representation is unaffected
    assert successes(world, REBUILD) == []
    assert denials(world, REBUILD) == [("REPRESENTATION_NOT_READY", "REBUILD_INCOMPLETE")]
    assert denials(world, SEARCH) == [("REPRESENTATION_NOT_READY", "REPRESENTATION_REBUILDING")] * 2
    inner.upsert = original
    resumed = world.rebuild(records[0], op="rebuild-resume")
    assert (resumed.manifest_digest, resumed.entries) == (expected.manifest_digest, expected.entries)
    assert len(world.search_v2("supply route").hits) == 3


def test_an_unaudited_rebuild_never_becomes_active(backends: Backends) -> None:
    world = backends.world()
    records = populate(world)
    world.rep_audit.fail = True
    assert_error(lambda: world.rebuild(records[0]), "CONTROL_PLANE_UNAVAILABLE", "AUDIT_UNAVAILABLE")
    record = world.representations.record(MemoryPartition.for_item(records[0].item).digest, PIN_V2.representation_version)
    assert record is not None and record.state is RepresentationState.BUILDING and record.audit_ref is None
    # Even the denial of the search cannot be audited: it still fails closed.
    assert_error(lambda: world.search_v2("supply route"), "CONTROL_PLANE_UNAVAILABLE", "AUDIT_UNAVAILABLE")
    world.rep_audit.fail = False
    assert world.rep_audit.events == []  # nothing could be recorded, nothing became ACTIVE
    assert_denied(world, SEARCH, lambda: world.search_v2("supply route"), "REPRESENTATION_NOT_READY", "REPRESENTATION_REBUILDING")
    world.rebuild(records[0], op="rebuild-2")
    assert len(world.search_v2("supply route").hits) == 3
    assert [e["operation_id"] for e in successes(world, REBUILD)] == ["rebuild-2"]


def test_unpinned_models_and_dimensions_fail_rebuild_and_retrieval(backends: Backends) -> None:
    world = backends.world()
    records = populate(world)
    world.rebuild(records[0])
    vector = world.coordinator.embed_query(PROFILE_V2, "supply route")
    for changes in (
        {"embedding_model_digest": d("embedding-model:feature-hash-16:unpinned")},
        {"embedding_dimensions": 16, "embedding_model_ref": "embedding-model:feature-hash-16:other"},
        {"embedding_normalization_profile": "none"},
    ):
        model = {**MODEL_V2, **changes}
        body = request(RetrievalMode.VECTOR, query_vector=vector, model=model)
        assert_error(lambda body=body: world.service().search(body, binding=binding()), "UNSUPPORTED_CAPABILITY", "EMBEDDING_MODEL_UNPINNED")
        profile = VectorProfile(**model)  # type: ignore[arg-type]
        assert_error(lambda profile=profile: world.rebuild(records[0], profile, op="unpinned"), "UNSUPPORTED_CAPABILITY", "EMBEDDING_MODEL_UNPINNED")
    wrong_dimensions = {**MODEL_V2, "embedding_dimensions": 32}
    body = request(RetrievalMode.VECTOR, query_vector=[1.0] + [0.0] * 31, model=wrong_dimensions)
    assert_error(lambda: world.service().search(body, binding=binding()), "UNSUPPORTED_CAPABILITY", "EMBEDDING_MODEL_UNPINNED")
    partition = MemoryPartition.for_item(records[0].item)
    assert_error(
        lambda: world.coordinator.vector_candidates(partition, PROFILE_V2, vector + (0.0,), limit=3),
        "MEMORY_SCHEMA_INVALID",
        "EMBEDDING_DIMENSION_MISMATCH",
    )
    # A boundary without the v1 pin refuses even the native representation.
    only_v2 = backends.fresh(world, models=(FeatureHashingModel(),))
    assert_error(lambda: only_v2.search_v1("supply route"), "UNSUPPORTED_CAPABILITY", "EMBEDDING_MODEL_UNPINNED")
    assert world.representations.record(partition.digest, PIN_V2.representation_version).operation_id == "rebuild-1"


def test_mixed_representation_versions_fail_retrieval(backends: Backends) -> None:
    world = backends.world()
    records = populate(world)
    world.rebuild(records[0])
    partition = MemoryPartition.for_item(records[0].item)
    # (1) a current version embedded only natively (v1) after the v2 rebuild
    late = world.admit("late", "supply route reopened after repairs")
    assert_error(lambda: world.search_v2("supply route"), "REPRESENTATION_NOT_READY", "REPRESENTATION_INCOMPLETE")
    receipt = world.rebuild(late, op="rebuild-incremental")
    assert "urn:ocor:memory:late:v1" in dict(receipt.entries)
    assert "urn:ocor:memory:late:v1" in refs(world.search_v2("supply route reopened"))
    # (2) a representation built with another pin for the same profile
    retokenized = FeatureHashingModel()
    retokenized.pin = dataclasses.replace(retokenized.pin, tokenizer_digest=d("tokenizer:other"))
    other_pin = backends.fresh(world, models=(FixtureHashModel(), retokenized))
    assert_error(lambda: other_pin.search_v2("supply route"), "REPRESENTATION_NOT_READY", "REPRESENTATION_VERSION_MIXED")
    assert_error(lambda: other_pin.invalidate(records[0]), "REPRESENTATION_NOT_READY", "REPRESENTATION_VERSION_MIXED")
    # (3) an entry of another representation version inside the v2 layout
    text = "supply route"
    foreign = dataclasses.replace(
        EmbeddingDescriptor.build(records[0].item, records[0].item_digest, partition, PIN_V2, V2.embed(text)),
        representation_version=PIN_V1.representation_version,
    )
    world.parallel.inner.upsert(partition, ParallelLayout.of(PIN_V2), foreign.store_ref, foreign.to_mapping(), V2.embed(text))
    assert_error(lambda: world.search_v2(text), "REPRESENTATION_NOT_READY", "REPRESENTATION_VERSION_MIXED")
    world.rebuild(records[0], op="rebuild-sweep")
    assert foreign.store_ref not in parallel_entries(world, records[0])
    assert len(world.search_v2(text).hits) == 4


def test_revocation_expiry_reclassification_and_deletion_invalidate_before_materialisation(backends: Backends) -> None:
    world = backends.world()
    corpus = [(name, f"harbour patrol sighting {name}") for name in ("keep", "revoke", "expire", "reclass", "delete")]
    records = {item_id: world.admit(item_id, text, expires_at=NOW + timedelta(minutes=5) if item_id == "expire" else None) for item_id, text in corpus}
    first = world.rebuild(records["keep"])
    assert len(first.entries) == 5 and len(world.search_v2("harbour patrol sighting").hits) == 5
    world.transition(records["revoke"], "REVOKED", "harbour patrol sighting revoke")
    world.transition(records["delete"], "DELETION_PENDING", "harbour patrol sighting delete", deletion_epoch=1)
    world.admit("reclass", "harbour patrol sighting reclass", version=2, ctx=context(marking=M_SECRET))
    world.clock.advance(timedelta(minutes=6))
    # Before any invalidation run, no stale representation reaches any output.
    after = world.search_v2("harbour patrol sighting", include_explanation=True)
    assert refs(after) == ["urn:ocor:memory:keep:v1"] and len(after.receipt["hits"]) == 1  # type: ignore[arg-type]
    assert all(name not in json.dumps(after.to_mapping()) for name in ("revoke", "expire", "reclass", "delete"))
    partition = MemoryPartition.for_item(records["keep"].item)
    vector = world.coordinator.embed_query(PROFILE_V2, "harbour patrol sighting")
    candidates = world.coordinator.vector_candidates(partition, PROFILE_V2, vector, limit=10)
    assert [hit.memory_version_ref for hit in candidates] == ["urn:ocor:memory:keep:v1"]
    receipt = world.invalidate(records["keep"])
    assert receipt.invalidated == tuple(sorted(f"urn:ocor:memory:{name}:v1" for name in ("revoke", "expire", "reclass", "delete")))
    assert [ref for ref, _ in receipt.entries] == ["urn:ocor:memory:keep:v1"]
    assert len(parallel_entries(world, records["keep"])) == 1
    assert len(world.representations.descriptors(MemoryPartition.for_item(records["keep"].item).digest, PIN_V2.representation_version)) == 1
    assert world.rep_audit.events[-1]["action"] == "invalidateEmbeddingRepresentation"
    assert refs(world.search_v2("harbour patrol sighting")) == ["urn:ocor:memory:keep:v1"]
    # The reclassified version lives in its own partition and is never mixed in.
    secret = context(compartments=("alpha", "bravo"), marking=M_SECRET)
    # The SECRET partition has no v2 representation yet: only the RESTRICTED one answers.
    assert refs(world.search_v2("harbour patrol sighting", ctx=secret)) == ["urn:ocor:memory:keep:v1"]
    assert "urn:ocor:memory:reclass:v2" in refs(world.search_v1("harbour patrol sighting reclass", ctx=secret))
    rebuilt = world.rebuild(world.ledger.get("reclass", 2), ctx=secret, op="rebuild-secret")
    assert [ref for ref, _ in rebuilt.entries] == ["urn:ocor:memory:reclass:v2"]
    assert sorted(refs(world.search_v2("harbour patrol sighting", ctx=secret))) == ["urn:ocor:memory:keep:v1", "urn:ocor:memory:reclass:v2"]


def test_rebuild_requires_an_authorized_gcs_and_a_live_policy_decision(backends: Backends) -> None:
    world = backends.world()
    records = populate(world)
    partition = MemoryPartition.for_item(records[0].item)

    def nothing_written() -> None:
        assert world.representations.record(partition.digest, PIN_V2.representation_version) is None
        assert parallel_entries(world, records[0]) == {}
        assert successes(world, REBUILD) == []

    assert_denied(
        world,
        REBUILD,
        lambda: world.coordinator.rebuild(partition.ref, PROFILE_V2, binding=None, operation_id="op"),
        "AUTHENTICATION_REQUIRED",
        "BINDING_MISSING",
    )
    unauthenticated = world.rep_audit.events[-1]
    assert unauthenticated["correlation_id"] is None and unauthenticated["partition_ref"] == partition.ref
    for ctx in (
        context(compartments=("bravo",)),
        context(marking=base.M_UNCLASSIFIED),
        context(tenant="tenant-b"),
        context(organization="org-b"),
        context(domain="domain-intel"),
        context(purpose="training"),
        dataclasses.replace(CALLER, policy_bundle_digest=d("policy-bundle:memory:2")),
        dataclasses.replace(CALLER, ontology_release_digest=d("ontology-release:2")),
    ):
        error = assert_denied(world, REBUILD, lambda ctx=ctx: world.rebuild(records[0], ctx=ctx), "POLICY_DENIED", "PARTITION_NOT_AUTHORIZED")
        assert error.correlation_id == ctx.correlation_id
        event = world.rep_audit.events[-1]
        assert (event["correlation_id"], event["governed_context_digest"]) == (ctx.correlation_id, ctx.digest())
        assert (event["operation_id"], event["causation_id"], event["partition_ref"]) == ("rebuild-1", "rebuild-1", partition.ref)
        assert event["representation_version"] == PIN_V2.representation_version
    assert_denied(
        world,
        REBUILD,
        lambda: world.coordinator.rebuild("urn:ocor:memory-partition:" + "0" * 64, PROFILE_V2, binding=binding(), operation_id="op"),
        "POLICY_DENIED",
        "PARTITION_NOT_AUTHORIZED",
    )
    assert world.rep_policy.calls == []  # refused on the partition tuple before policy
    nothing_written()
    world.rep_policy.permitted = False
    assert_denied(world, REBUILD, lambda: world.rebuild(records[0]), "POLICY_DENIED", "REPRESENTATION_DENIED")
    world.rep_policy.permitted, world.rep_policy.fail = True, True
    assert_denied(world, REBUILD, lambda: world.rebuild(records[0]), "CONTROL_PLANE_UNAVAILABLE", "POLICY_UNAVAILABLE")
    world.rep_policy.fail, world.rep_policy.bundle = False, d("policy-bundle:stale")
    assert_denied(world, REBUILD, lambda: world.rebuild(records[0]), "STALE_POLICY", "POLICY_BUNDLE_MISMATCH")
    nothing_written()
    assert denials(world, REBUILD) == (
        [("AUTHENTICATION_REQUIRED", "BINDING_MISSING")]
        + [("POLICY_DENIED", "PARTITION_NOT_AUTHORIZED")] * 9
        + [("POLICY_DENIED", "REPRESENTATION_DENIED"), ("CONTROL_PLANE_UNAVAILABLE", "POLICY_UNAVAILABLE"), ("STALE_POLICY", "POLICY_BUNDLE_MISMATCH")]
    )
    # The denial of an unavailable audit sink still fails closed, without effect.
    world.rep_policy.permitted, world.rep_audit.fail = False, True
    assert_error(lambda: world.rebuild(records[0]), "CONTROL_PLANE_UNAVAILABLE", "AUDIT_UNAVAILABLE").correlation_id == CALLER.correlation_id
    world.rep_policy.permitted, world.rep_audit.fail = True, False
    nothing_written()
    world.rep_policy.bundle = None
    receipt = world.rebuild(records[0])
    assert len(receipt.entries) == 3
    assert [e["audit_ref"] for e in successes(world, REBUILD)] == [receipt.audit_ref]


def test_parallel_representations_never_cross_compartments(backends: Backends) -> None:
    world = backends.world()
    alpha = populate(world, ctx=context(compartments=("alpha",)))
    bravo = populate(world, [("brv-1", "supply route survey bravo")], ctx=context(compartments=("bravo",)))
    alpha_receipt = world.rebuild(alpha[0])
    bravo_receipt = world.rebuild(bravo[0], op="rebuild-bravo")
    alpha_partition, bravo_partition = (MemoryPartition.for_item(r[0].item) for r in (alpha, bravo))
    layout = ParallelLayout.of(PIN_V2).representation_version
    names = {world.parallel.inner.collection(p, layout) for p in (alpha_partition, bravo_partition)}
    assert len(names) == 2 and not set(alpha_receipt.entries) & set(bravo_receipt.entries)
    alpha_only = context(compartments=("alpha",))
    world.parallel.calls.clear()
    response = world.search_v2("supply route survey", ctx=alpha_only)
    assert response.hits and all(hit.memory_item_id.startswith("conv-") for hit in response.hits)
    touched = {call[1] for call in world.parallel.calls}
    assert touched == {alpha_partition.digest}
    both = world.search_v2("supply route survey bravo", ctx=CALLER)
    assert refs(both)[0] == "urn:ocor:memory:brv-1:v1"
    assert_error(lambda: world.rebuild(bravo[0], ctx=alpha_only, op="cross"), "POLICY_DENIED", "PARTITION_NOT_AUTHORIZED")


def test_tampered_descriptors_or_vectors_fail_retrieval_closed(backends: Backends) -> None:
    world = backends.world()
    records = populate(world)
    receipt = world.rebuild(records[0])
    partition = MemoryPartition.for_item(records[0].item)
    store_ref = dict(receipt.entries)["urn:ocor:memory:conv-1:v1"]
    # (1) the vector persisted in Qdrant is replaced under the same descriptor
    descriptor = world.representations.descriptor(store_ref)
    world.parallel.inner.upsert(partition, ParallelLayout.of(PIN_V2), store_ref, descriptor.to_mapping(), V2.embed("unrelated decoy text"))
    assert_error(lambda: world.search_v2("convoy moving along the northern supply route"), "REPRESENTATION_NOT_READY", "PROJECTION_DRIFT")
    world.rebuild(records[0], op="rebuild-repair")
    assert refs(world.search_v2("convoy moving along the northern supply route"))[0] == "urn:ocor:memory:conv-1:v1"
    # (2) the registered descriptor row is altered
    with world.representations.connect() as conn:
        tampered = {**descriptor.to_mapping(), "embedding_digest": d("tampered")}
        conn.execute(
            f'UPDATE "{world.representations.schema}".embedding_descriptors SET body = %s WHERE store_ref = %s',
            (canonical_bytes(tampered).decode(), store_ref),
        )
    assert_error(lambda: world.search_v2("supply route"), "REPRESENTATION_NOT_READY", "PROJECTION_DRIFT")
    # (3) a stray, non-descriptor point never occupies a result slot
    world.rebuild(records[0], op="rebuild-repair-2")
    world.parallel.inner.upsert(partition, ParallelLayout.of(PIN_V2), "urn:ocor:stray", {"note": "not a descriptor"}, V2.embed("supply route"))
    assert len(world.search_v2("supply route").hits) == 3


def test_concurrent_rebuilds_serialise_through_the_record_and_converge(backends: Backends) -> None:
    clean = backends.world()
    expected = clean.rebuild(populate(clean)[0], op="clean")
    world = backends.world()
    records = populate(world)
    outcomes: list[Any] = []

    def run(index: int) -> None:
        worker = backends.fresh(world)
        try:
            outcomes.append(worker.rebuild(records[0], op=f"rebuild-{index}"))
        except MemoryAdmissionError as exc:
            outcomes.append(exc)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert len(outcomes) == 3
    won = [o for o in outcomes if isinstance(o, RepresentationReceipt)]
    lost = [o for o in outcomes if not isinstance(o, RepresentationReceipt)]
    assert won and all((o.reason_code, o.detail_code) == ("MEMORY_IDEMPOTENCY_CONFLICT", "REPRESENTATION_RECORD_CONFLICT") for o in lost)
    assert {o.manifest_digest for o in won} == {expected.manifest_digest}
    if world.representations.record(MemoryPartition.for_item(records[0].item).digest, PIN_V2.representation_version).state is not RepresentationState.ACTIVE:
        world.rebuild(records[0], op="rebuild-settle")
    final = world.representations.record(MemoryPartition.for_item(records[0].item).digest, PIN_V2.representation_version)
    assert final.state is RepresentationState.ACTIVE and final.manifest_digest == expected.manifest_digest
    assert len(world.search_v2("supply route").hits) == 3
    stale = dataclasses.replace(final, operation_id="stale")
    assert_error(lambda: world.representations.put_record(stale, expected_digest=d("not-current")), "MEMORY_IDEMPOTENCY_CONFLICT", "REPRESENTATION_RECORD_CONFLICT")
    assert_error(lambda: world.representations.put_record(stale, expected_digest=None), "MEMORY_IDEMPOTENCY_CONFLICT", "REPRESENTATION_RECORD_CONFLICT")


def test_hybrid_retrieval_uses_the_parallel_vector_factor_with_its_pin(backends: Backends) -> None:
    world = backends.world()
    records = populate(world)
    world.rebuild(records[0])
    response = world.search_v2("radar contact eastern ridge", mode=RetrievalMode.HYBRID)
    assert refs(response)[0] == "urn:ocor:memory:conv-3:v1"
    assert response.receipt["representation_versions"]["VECTOR"] == PIN_V2.representation_version  # type: ignore[index]
    top = response.hits[0].score_factors
    cosine = math.fsum(a * b for a, b in zip(V2.embed("radar contact eastern ridge"), V2.embed(CORPUS[2][1]), strict=True))
    assert abs(top["vector"] - cosine) < 1e-6 and top["lexical"] == 1.0


def test_retrieval_of_a_rebuilt_representation_is_durable_across_fresh_adapters(backends: Backends) -> None:
    world = backends.world()
    records = populate(world)
    world.rebuild(records[0])
    first = world.search_v2("supply route")
    clone = backends.fresh(world)
    assert clone.search_v2("supply route").to_mapping() == first.to_mapping()


def test_unit_doubles_are_not_used_by_qualifying_worlds(backends: Backends) -> None:
    world = backends.world()
    assert not isinstance(world.representations, MemRepresentations)
    assert not isinstance(world.parallel.inner, base.MemIndex) and not isinstance(world.vector.inner, base.MemIndex)
    assert isinstance(world.lexical.inner, base.PostgresLexicalIndex)
    assert isinstance(world.registry.resolve(PROFILE_V2)[0], FeatureHashingModel)


def test_a_lost_compare_and_set_leaves_no_success_receipt_on_real_backends(backends: Backends) -> None:
    world = backends.world()
    check_lost_compare_and_set(world, populate(world))


def test_versions_outside_their_validity_window_never_occupy_a_candidate_slot(backends: Backends) -> None:
    check_validity_window(backends.world())


def test_an_elapsed_corpus_beyond_the_candidate_pool_still_returns_the_valid_version(backends: Backends) -> None:
    world = backends.world()
    keep = world.admit("keep", "lighthouse beacon signal")
    for index in range(140):
        world.admit(f"elapsed-{index:03d}", f"lighthouse beacon signal {index}", valid_until=NOW + timedelta(seconds=30))
    receipt = world.rebuild(keep)
    assert len(receipt.entries) == 141
    world.clock.advance(timedelta(minutes=2))
    partition = MemoryPartition.for_item(keep.item)
    vector = world.coordinator.embed_query(PROFILE_V2, "lighthouse beacon signal 7")
    hits = world.coordinator.vector_candidates(partition, PROFILE_V2, vector, limit=128)
    assert [hit.memory_version_ref for hit in hits] == ["urn:ocor:memory:keep:v1"]
    assert refs(world.search_v2("lighthouse beacon signal 7")) == ["urn:ocor:memory:keep:v1"]
    assert denials(world, SEARCH) == []


def test_every_refusal_writes_a_denial_event_on_real_backends(backends: Backends) -> None:
    world = backends.world()
    records = populate(world)
    partition = MemoryPartition.for_item(records[0].item)
    vector = world.coordinator.embed_query(PROFILE_V2, "supply route")
    assert_denied(world, INVALIDATE, lambda: world.invalidate(records[0]), "REPRESENTATION_NOT_READY", "REPRESENTATION_ABSENT")
    world.rebuild(records[0])
    late = world.admit("late", "supply route reopened")
    assert_denied(world, SEARCH, lambda: world.coordinator.vector_candidates(partition, PROFILE_V2, vector, limit=3), "REPRESENTATION_NOT_READY", "REPRESENTATION_INCOMPLETE")
    world.rebuild(late, op="rebuild-2")
    store_ref = dict(world.representations.record(partition.digest, PIN_V2.representation_version).entries)[records[0].item.version_ref]
    descriptor = world.representations.descriptor(store_ref)
    world.parallel.inner.upsert(partition, ParallelLayout.of(PIN_V2), store_ref, descriptor.to_mapping(), V2.embed("unrelated decoy text"))
    assert_denied(world, SEARCH, lambda: world.coordinator.vector_candidates(partition, PROFILE_V2, vector, limit=4), "REPRESENTATION_NOT_READY", "PROJECTION_DRIFT")
    world.rebuild(records[0], op="rebuild-3")
    other_pin = backends.fresh(world, models=(FixtureHashModel(), _retokenized()))
    other_pin.rep_audit = world.rep_audit
    other_pin.coordinator = other_pin.build()
    assert_denied(other_pin, INVALIDATE, lambda: other_pin.invalidate(records[0]), "REPRESENTATION_NOT_READY", "REPRESENTATION_VERSION_MIXED")
    assert_denied(other_pin, SEARCH, lambda: other_pin.coordinator.vector_candidates(partition, PROFILE_V2, vector, limit=4), "REPRESENTATION_NOT_READY", "REPRESENTATION_VERSION_MIXED")
    assert [e["operation_id"] for e in successes(world, REBUILD)] == ["rebuild-1", "rebuild-2", "rebuild-3"]


def _retokenized() -> FeatureHashingModel:
    model = FeatureHashingModel()
    model.pin = dataclasses.replace(model.pin, tokenizer_digest=d("tokenizer:other"))
    return model


# --------------------------------------------------------------------------
# Unaudited activations, caller correlation of search denials (repair 2)
# --------------------------------------------------------------------------


def strand_unaudited_active(world: World, record: AdmittedMemoryVersion) -> RepresentationRecord:
    """The success receipt cannot be written and the compensating withdraw fails too."""

    partition = MemoryPartition.for_item(record.item)
    store = world.representations
    original = store.put_record

    def put_record(candidate: RepresentationRecord, *, expected_digest: str | None) -> None:
        current = store.record(candidate.partition_digest, candidate.representation_version)
        if current is not None and current.state is RepresentationState.ACTIVE and candidate.state is RepresentationState.BUILDING:
            raise ConnectionError("representation store unavailable")
        original(candidate, expected_digest=expected_digest)

    world.rep_audit.accept = lambda event: str(event["action"]).endswith(".denied")
    store.put_record = put_record
    try:
        assert_error(lambda: world.rebuild(record), "CONTROL_PLANE_UNAVAILABLE", "AUDIT_UNAVAILABLE")
    finally:
        del store.put_record
        world.rep_audit.accept = None
    stranded = store.record(partition.digest, PIN_V2.representation_version)
    assert stranded is not None and stranded.state is RepresentationState.ACTIVE and stranded.audit_ref is not None
    assert successes(world, REBUILD) == [] and not world.rep_audit.contains(stranded.audit_ref)
    assert world.coordinator.metrics()[("withdraw", "INCOMPLETE")] == 1
    return stranded


def check_unaudited_activation_never_serves(world: World, fresh: Any = None) -> None:
    records = populate(world)
    partition = MemoryPartition.for_item(records[0].item)
    vector = world.coordinator.embed_query(PROFILE_V2, "supply route")
    stranded = strand_unaudited_active(world, records[0])
    # Left ACTIVE in the store, but without a success receipt it never serves.
    assert_denied(world, SEARCH, lambda: world.search_v2("supply route"), "REPRESENTATION_NOT_READY", "REPRESENTATION_UNAUDITED")
    assert_denied(world, SEARCH, lambda: world.coordinator.vector_candidates(partition, PROFILE_V2, vector, limit=3), "REPRESENTATION_NOT_READY", "REPRESENTATION_UNAUDITED")
    assert_denied(world, INVALIDATE, lambda: world.invalidate(records[0]), "REPRESENTATION_NOT_READY", "REPRESENTATION_UNAUDITED")
    if fresh is not None:
        # Durable: a new coordinator over the same stores refuses it as well.
        other = fresh(world)
        assert_denied(other, SEARCH, lambda: other.search_v2("supply route"), "REPRESENTATION_NOT_READY", "REPRESENTATION_UNAUDITED")
    # An unavailable receipt lookup fails closed.
    world.rep_audit.lookup_fails = True
    assert_denied(world, SEARCH, lambda: world.coordinator.vector_candidates(partition, PROFILE_V2, vector, limit=3), "CONTROL_PLANE_UNAVAILABLE", "AUDIT_UNAVAILABLE")
    world.rep_audit.lookup_fails = False
    assert successes(world, REBUILD) == []
    # A rebuild with a writable audit store recovers: one receipt, ACTIVE, served.
    receipt = world.rebuild(records[0], op="rebuild-2")
    final = world.representations.record(partition.digest, PIN_V2.representation_version)
    assert final is not None and final.state is RepresentationState.ACTIVE and final.audit_ref == receipt.audit_ref != stranded.audit_ref
    assert [(e["operation_id"], e["audit_ref"]) for e in successes(world, REBUILD)] == [("rebuild-2", receipt.audit_ref)]
    served = refs(world.search_v2("supply route"))
    assert served and set(served) <= {r.item.version_ref for r in records}
    world.rep_audit.lookup_fails = True
    assert_denied(world, SEARCH, lambda: world.search_v2("supply route"), "CONTROL_PLANE_UNAVAILABLE", "AUDIT_UNAVAILABLE")
    world.rep_audit.lookup_fails = False


def test_unit_an_unaudited_activation_never_serves_even_if_the_withdraw_fails() -> None:
    check_unaudited_activation_never_serves(unit_world())


def test_unit_an_active_record_without_audit_ref_never_serves_nor_looks_up() -> None:
    world = unit_world()
    records = populate(world)
    world.rebuild(records[0])
    partition = MemoryPartition.for_item(records[0].item)
    key = (partition.digest, PIN_V2.representation_version)
    # Only an in-process store can hold it: the record parser rejects it.
    world.representations.records[key] = dataclasses.replace(world.representations.records[key], audit_ref=None)
    world.rep_audit.lookup_fails = True  # a lookup would fail AUDIT_UNAVAILABLE instead
    vector = world.coordinator.embed_query(PROFILE_V2, "supply route")
    assert_denied(world, SEARCH, lambda: world.coordinator.vector_candidates(partition, PROFILE_V2, vector, limit=3), "REPRESENTATION_NOT_READY", "REPRESENTATION_UNAUDITED")


def test_unit_a_withdraw_lost_to_a_newer_operation_leaves_that_operation_s_record() -> None:
    world = unit_world()
    records = populate(world)
    partition = MemoryPartition.for_item(records[0].item)
    key = (partition.digest, PIN_V2.representation_version)

    def accept(event: Any) -> bool:
        if str(event["action"]).endswith(".denied"):
            return True
        # A newer operation takes the record over before the receipt is refused.
        current = world.representations.records[key]
        world.representations.put_record(dataclasses.replace(current, state=RepresentationState.BUILDING, manifest_digest=None, audit_ref=None, operation_id="newer"), expected_digest=current.digest)
        return False

    world.rep_audit.accept = accept
    assert_error(lambda: world.rebuild(records[0]), "CONTROL_PLANE_UNAVAILABLE", "AUDIT_UNAVAILABLE")
    world.rep_audit.accept = None
    record = world.representations.records[key]
    assert (record.operation_id, record.state) == ("newer", RepresentationState.BUILDING)
    assert successes(world, REBUILD) == [] and world.coordinator.metrics()[("withdraw", "SUPERSEDED")] == 1
    assert_denied(world, SEARCH, lambda: world.search_v2("supply route"), "REPRESENTATION_NOT_READY", "REPRESENTATION_REBUILDING")


def test_unit_a_transiently_failing_withdraw_is_retried_within_its_bound() -> None:
    world = unit_world()
    records = populate(world)
    partition = MemoryPartition.for_item(records[0].item)
    store = world.representations
    original = store.put_record
    failures: list[str] = []

    def put_record(candidate: RepresentationRecord, *, expected_digest: str | None) -> None:
        current = store.record(candidate.partition_digest, candidate.representation_version)
        if current is not None and current.state is RepresentationState.ACTIVE and candidate.state is RepresentationState.BUILDING and not failures:
            failures.append(candidate.operation_id)
            raise ConnectionError("transient")
        original(candidate, expected_digest=expected_digest)

    store.put_record = put_record  # type: ignore[method-assign]
    world.rep_audit.accept = lambda event: str(event["action"]).endswith(".denied")
    assert_error(lambda: world.rebuild(records[0]), "CONTROL_PLANE_UNAVAILABLE", "AUDIT_UNAVAILABLE")
    world.rep_audit.accept = None
    del store.put_record
    record = store.record(partition.digest, PIN_V2.representation_version)
    assert failures == ["rebuild-1"] and record.state is RepresentationState.BUILDING and record.audit_ref is None
    assert ("withdraw", "INCOMPLETE") not in world.coordinator.metrics()
    assert_denied(world, SEARCH, lambda: world.search_v2("supply route"), "REPRESENTATION_NOT_READY", "REPRESENTATION_REBUILDING")


def check_search_denials_carry_the_caller(world: World) -> None:
    records = populate(world)
    partition = MemoryPartition.for_item(records[0].item)
    vector = world.coordinator.embed_query(PROFILE_V2, "supply route")
    world.rebuild(records[0])
    world.admit("late", "supply route reopened")
    error = assert_denied(world, SEARCH, lambda: world.search_v2("supply route", operation_id="search-77"), "REPRESENTATION_NOT_READY", "REPRESENTATION_INCOMPLETE")
    event = world.rep_audit.events[-1]
    assert error.correlation_id == CALLER.correlation_id
    assert (event["correlation_id"], event["operation_id"], event["causation_id"], event["governed_context_digest"]) == (CALLER.correlation_id, "search-77", "search-77", CALLER.digest())
    # A port call outside any search carries no caller: nothing is invented.
    assert_denied(world, SEARCH, lambda: world.coordinator.vector_candidates(partition, PROFILE_V2, vector, limit=3), "REPRESENTATION_NOT_READY", "REPRESENTATION_INCOMPLETE")
    event = world.rep_audit.events[-1]
    assert (event["correlation_id"], event["operation_id"], event["causation_id"], event["governed_context_digest"]) == (None, None, None, None)
    # Without a binding the search fails closed before any representation lookup.
    before = list(world.rep_audit.events)
    body = request(RetrievalMode.VECTOR, text="supply route", query_vector=vector, model=MODEL_V2)
    assert_error(lambda: world.service().search(body, binding=None), "AUTHENTICATION_REQUIRED", "BINDING_MISSING")
    assert world.rep_audit.events == before
    # The scope of one search service never reaches another coordinator.
    other = unit_world()
    other_records = populate(other)
    other.rebuild(other_records[0])
    other.admit("late", "supply route reopened")
    other_partition = MemoryPartition.for_item(other_records[0].item)
    seen: list[str | None] = []
    real = world.coordinator.vector_candidates

    def nested(*args: Any, **kwargs: Any) -> Any:
        with pytest.raises(MemoryAdmissionError):
            other.coordinator.vector_candidates(other_partition, PROFILE_V2, vector, limit=3)
        seen.append(other.rep_audit.events[-1]["correlation_id"])
        return real(*args, **kwargs)

    world.coordinator.vector_candidates = nested  # type: ignore[method-assign]
    with pytest.raises(MemoryAdmissionError):
        world.search_v2("supply route")
    del world.coordinator.vector_candidates
    assert seen and set(seen) == {None}


def test_unit_search_denials_carry_the_caller_correlation() -> None:
    check_search_denials_carry_the_caller(unit_world())


def test_an_unaudited_activation_never_serves_on_real_backends(backends: Backends) -> None:
    check_unaudited_activation_never_serves(backends.world(), backends.fresh)


def test_search_denials_carry_the_caller_correlation_on_real_backends(backends: Backends) -> None:
    check_search_denials_carry_the_caller(backends.world())
