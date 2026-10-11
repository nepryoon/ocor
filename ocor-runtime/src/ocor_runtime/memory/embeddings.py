"""C8 governed memory -- embedding lifecycle and deterministic representation rebuild.

Implements the embedding-lifecycle slice of the ``GovernedMemoryService``
(ADD v1.3 Part II §§2.6-2.8, 2.10; LLD v1.1 §§2.8.1, 2.8.4, 2.8.6, 7.2
``FGM-06``/``FGM-07``/``FGM-10``/``FGM-16``):

* An ``EmbeddingModelPin`` fixes model ref/version/digest, tokenizer
  ref/digest, dimensions and normalization profile.  Only pinned models are
  registered; a vector profile that does not resolve to exactly one pin --
  unknown model, other digest, other dimensions or normalization -- fails
  closed, at rebuild and at retrieval alike.
* Each embedding is described by an ``EmbeddingDescriptor`` binding the exact
  item/version, item and content digests, partition, purpose and marking to
  the full model pin, the representation version and the binary64 and stored
  binary32 vector digests.  The descriptor is the payload of its index entry,
  so every hit is checked against the descriptor authority.
* A model upgrade creates a *parallel* representation version: ``rebuild``
  re-embeds, under an authorized GCS and a live policy decision, every
  current ``ACTIVE`` vector-bearing version of one partition from its verified
  committed content.  The order is canonical, every embedding is computed twice
  and must be identical, every write is read back, and the result is a
  manifest whose digest depends only on the source versions and the pin, so a
  rebuild repeated on fresh stores yields the same manifest.  Source memory is
  only read: metadata, content, native projections and head pointers are never
  written.
* Parallel entries live in their own physical layout per partition and
  representation version (no cross-compartment ANN graph, centroid or cache)
  and outside the layouts of the store coordinator, whose reconciliation
  therefore never sees them.
* While a rebuild is in progress (``BUILDING``), when a current version lacks
  its descriptor, when the registered pin differs from the one the
  representation was built with, or when an entry of another representation
  version appears in the layout, vector retrieval of that version fails closed
  instead of mixing representation versions.  Revocation, expiry,
  reclassification, supersession or deletion of a version makes its
  descriptor ineligible at once: it never reaches a candidate slot, and
  ``invalidate`` (also part of every rebuild) removes it from the index and
  the manifest.  A version outside its validity window at the evaluated
  instant keeps its descriptor (it stays answerable for a historic
  ``valid_at``) but never occupies a candidate slot either.
* Every rebuild and invalidation writes an audit receipt (operation,
  causation and correlation ids, pin, manifest digest, counts) once the
  ``ACTIVE`` record is committed, so no lost compare-and-set leaves a success
  receipt.  The ``ACTIVE`` record names the ``audit_ref`` of that receipt and
  serves only while the audit store holds it: if the receipt cannot be
  written the record is put back to ``BUILDING`` (best effort, bounded), and
  even when that compensation fails too the record never serves.  Every
  refusal of rebuild, invalidation or vector candidate lookup writes a denial
  event (ADD v1.3 Part II: the audit store keeps access, denial and influence
  evidence); an unaudited denial still fails closed.  Inside a search of
  ``EmbeddingSearchService`` the lookup denial carries the caller's
  correlation, operation and governed-context digest and the lookup uses the
  search's ``valid_at``.  Raw vectors never leave the module.

The module is backend-free (``OCOR_LANGUAGE_POLICY.md`` row 8): the model, the
descriptor store, the index, policy and audit are ports.  Embeddings are
retrieval evidence only; they create no Authority, Approval, Decision,
CapabilityLease or canonical state.
"""

from __future__ import annotations

import hmac
import math
import struct
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

from ..kernel.canonical import (
    TimestampError,
    canonical_digest,
    format_utc_timestamp,
    parse_utc_timestamp,
)
from ..kernel.governance import TrustedClock
from ..kernel.governed_context import GovernedContext, VerifiedGovernedContextBinding
from .model import (
    DIGEST,
    GovernedMemoryItem,
    LifecycleStatus,
    MarkingDominance,
    MemoryAdmissionError,
    MemoryPolicyDecision,
    MemoryVersionLedger,
    RepresentationKind,
)
from .retrieval import MemorySearchResponse, MemorySearchService
from .stores import (
    BoundHit,
    ContentCipher,
    IndexEntry,
    IndexHit,
    MemoryContentStore,
    MemoryLexicalIndexPort,
    MemoryMetadataStore,
    MemoryPartition,
    MemoryStoreCoordinator,
    MemoryVectorIndexPort,
    StoredVersion,
    StoreLimits,
    VectorProfile,
    VersionState,
    lexical_document,
    stored_vector_digest,
    vector_digest,
)

EMBEDDING_PREFIX = "urn:ocor:memory-embedding:"
PARALLEL_LINEAGE = "PARALLEL_REBUILD"
MAX_EMBEDDING_DIMENSIONS = 4096
# Vector layouts rank by cosine similarity, so only unit vectors are indexed.
NORMALIZATION_PROFILES = frozenset({"l2-unit"})
UNIT_NORM_TOLERANCE = 1e-6
REBUILD_ACTION = "rebuildEmbeddingRepresentation"
INVALIDATE_ACTION = "invalidateEmbeddingRepresentation"
SEARCH_ACTION = "searchEmbeddingRepresentation"
# Compare-and-set attempts that put an unaudited ``ACTIVE`` record back to ``BUILDING``.
WITHDRAW_ATTEMPTS = 3


class MemoryEmbeddingError(MemoryAdmissionError):
    """Fail-closed embedding refusal carrying the closed memory Problem vocabulary."""


def _hex(digest: str) -> str:
    return digest.removeprefix("urn:sha256:")


def _not_ready(detail: str, message: str) -> MemoryEmbeddingError:
    return MemoryEmbeddingError("REPRESENTATION_NOT_READY", detail, message)


def _corrupted(detail: str, message: str) -> MemoryEmbeddingError:
    return MemoryEmbeddingError("INTERNAL_ERROR", detail, message)


# --------------------------------------------------------------------------
# Pinned embedding models
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EmbeddingModelPin:
    """Exact identity of one embedding model release and its tokenizer."""

    model_ref: str
    model_version: str
    model_digest: str
    tokenizer_ref: str
    tokenizer_digest: str
    dimensions: int
    normalization_profile: str

    def __post_init__(self) -> None:
        for name in ("model_ref", "model_version", "tokenizer_ref", "normalization_profile"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise MemoryEmbeddingError(
                    "MEMORY_SCHEMA_INVALID", "EMBEDDING_PIN_INVALID", f"pin {name} is invalid"
                )
        for name in ("model_digest", "tokenizer_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or DIGEST.fullmatch(value) is None:
                raise MemoryEmbeddingError(
                    "MEMORY_SCHEMA_INVALID", "EMBEDDING_PIN_INVALID", f"pin {name} is not a digest"
                )
        if (
            isinstance(self.dimensions, bool)
            or not isinstance(self.dimensions, int)
            or not 1 <= self.dimensions <= MAX_EMBEDDING_DIMENSIONS
        ):
            raise MemoryEmbeddingError(
                "MEMORY_SCHEMA_INVALID", "EMBEDDING_PIN_INVALID", "pin dimensions are out of range"
            )
        if self.normalization_profile not in NORMALIZATION_PROFILES:
            raise MemoryEmbeddingError(
                "UNSUPPORTED_CAPABILITY",
                "EMBEDDING_NORMALIZATION_UNSUPPORTED",
                "normalization profile is not supported by the vector layouts",
            )

    def to_mapping(self) -> dict[str, object]:
        return {
            "model_ref": self.model_ref,
            "model_version": self.model_version,
            "model_digest": self.model_digest,
            "tokenizer_ref": self.tokenizer_ref,
            "tokenizer_digest": self.tokenizer_digest,
            "dimensions": self.dimensions,
            "normalization_profile": self.normalization_profile,
        }

    @property
    def digest(self) -> str:
        return canonical_digest(self.to_mapping())

    @property
    def vector_profile(self) -> VectorProfile:
        """The retrieval-facing profile; its representation version names the pin."""

        return VectorProfile(
            embedding_model_ref=self.model_ref,
            embedding_model_digest=self.model_digest,
            embedding_dimensions=self.dimensions,
            embedding_normalization_profile=self.normalization_profile,
        )

    @property
    def representation_version(self) -> str:
        return self.vector_profile.representation_version


class EmbeddingModel(Protocol):
    """A deterministic embedding model behind its pin (the embedding worker port)."""

    @property
    def pin(self) -> EmbeddingModelPin:
        """The exact model release this instance serves."""

    def embed(self, text: str) -> Sequence[float]:
        """Embed ``text``; the same input must always give the same vector."""


class EmbeddingModelRegistry:
    """The pinned models a boundary may embed or search with; nothing else resolves."""

    def __init__(self, models: Iterable[EmbeddingModel]) -> None:
        resolved: dict[str, tuple[EmbeddingModel, EmbeddingModelPin]] = {}
        for model in models:
            pin = model.pin
            if not isinstance(pin, EmbeddingModelPin):
                raise ValueError("every registered model must expose an EmbeddingModelPin")
            version = pin.representation_version
            if version in resolved:
                raise ValueError("two registered models resolve to one representation version")
            resolved[version] = (model, pin)
        self._models = MappingProxyType(resolved)

    def resolve(self, profile: VectorProfile) -> tuple[EmbeddingModel, EmbeddingModelPin]:
        if not isinstance(profile, VectorProfile):
            raise MemoryEmbeddingError(
                "MEMORY_SCHEMA_INVALID", "VECTOR_PROFILE_INVALID", "vector profile is invalid"
            )
        entry = self._models.get(profile.representation_version)
        if entry is None:
            raise MemoryEmbeddingError(
                "UNSUPPORTED_CAPABILITY",
                "EMBEDDING_MODEL_UNPINNED",
                "no pinned embedding model matches the vector profile",
            )
        return entry

    def pins(self) -> tuple[EmbeddingModelPin, ...]:
        return tuple(pin for _, pin in self._models.values())


def _unit_vector(pin: EmbeddingModelPin, raw: object) -> tuple[float, ...]:
    """Validate one model output against its pin; anything else fails closed."""

    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise _not_ready("EMBEDDING_OUTPUT_INVALID", "embedding is not a sequence")
    values: list[float] = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _not_ready("EMBEDDING_OUTPUT_INVALID", "embedding values must be numbers")
        if not math.isfinite(value):
            raise _not_ready("EMBEDDING_OUTPUT_INVALID", "embedding values must be finite")
        values.append(float(value))
    if len(values) != pin.dimensions:
        raise MemoryEmbeddingError(
            "MEMORY_SCHEMA_INVALID",
            "EMBEDDING_DIMENSION_MISMATCH",
            "embedding length differs from the pinned dimensions",
        )
    stored_vector_digest(values)  # representable at the index precision
    if not any(struct.unpack(f">{len(values)}f", struct.pack(f">{len(values)}f", *values))):
        raise _not_ready("EMBEDDING_OUTPUT_INVALID", "embedding vanishes at index precision")
    if abs(math.sqrt(math.fsum(v * v for v in values)) - 1.0) > UNIT_NORM_TOLERANCE:
        raise _not_ready("EMBEDDING_OUTPUT_INVALID", "embedding is not l2-unit normalized")
    return tuple(values)


# --------------------------------------------------------------------------
# Embedding descriptors and parallel layouts
# --------------------------------------------------------------------------

DESCRIPTOR_STRINGS = (
    "memory_version_ref",
    "item_digest",
    "content_digest",
    "partition_digest",
    "purpose",
    "classification_marking_ref",
    "model_ref",
    "model_version",
    "model_digest",
    "tokenizer_ref",
    "tokenizer_digest",
    "normalization_profile",
    "representation_version",
    "embedding_digest",
    "stored_vector_digest",
)
DESCRIPTOR_DIGESTS = frozenset(
    {
        "item_digest",
        "content_digest",
        "partition_digest",
        "classification_marking_ref",
        "model_digest",
        "tokenizer_digest",
        "representation_version",
        "embedding_digest",
        "stored_vector_digest",
    }
)
DESCRIPTOR_FIELDS = frozenset(DESCRIPTOR_STRINGS) | {"dimensions"}


@dataclass(frozen=True, slots=True)
class EmbeddingDescriptor:
    """LLD v1.1 §2.8.4: one embedding bound to its exact source and model pin."""

    memory_version_ref: str
    item_digest: str
    content_digest: str
    partition_digest: str
    purpose: str
    classification_marking_ref: str
    model_ref: str
    model_version: str
    model_digest: str
    tokenizer_ref: str
    tokenizer_digest: str
    dimensions: int
    normalization_profile: str
    representation_version: str
    embedding_digest: str
    stored_vector_digest: str

    @classmethod
    def build(
        cls,
        item: GovernedMemoryItem,
        item_digest: str,
        partition: MemoryPartition,
        pin: EmbeddingModelPin,
        values: Sequence[float],
    ) -> EmbeddingDescriptor:
        return cls(
            memory_version_ref=item.version_ref,
            item_digest=item_digest,
            content_digest=item.content_digest,
            partition_digest=partition.digest,
            purpose=item.purpose,
            classification_marking_ref=item.classification_marking_ref,
            model_ref=pin.model_ref,
            model_version=pin.model_version,
            model_digest=pin.model_digest,
            tokenizer_ref=pin.tokenizer_ref,
            tokenizer_digest=pin.tokenizer_digest,
            dimensions=pin.dimensions,
            normalization_profile=pin.normalization_profile,
            representation_version=pin.representation_version,
            embedding_digest=vector_digest(values),
            stored_vector_digest=stored_vector_digest(values),
        )

    def to_mapping(self) -> dict[str, object]:
        mapping: dict[str, object] = {name: getattr(self, name) for name in DESCRIPTOR_STRINGS}
        mapping["dimensions"] = self.dimensions
        return mapping

    @classmethod
    def from_mapping(cls, value: object) -> EmbeddingDescriptor:
        """Parse a stored descriptor strictly; anything else is not a descriptor."""

        if not isinstance(value, Mapping) or set(value) != DESCRIPTOR_FIELDS:
            raise _corrupted("DESCRIPTOR_INVALID", "descriptor is not a closed record")
        strings: dict[str, str] = {}
        for name in DESCRIPTOR_STRINGS:
            raw = value[name]
            if not isinstance(raw, str) or not raw:
                raise _corrupted("DESCRIPTOR_INVALID", f"descriptor {name} is invalid")
            if name in DESCRIPTOR_DIGESTS and DIGEST.fullmatch(raw) is None:
                raise _corrupted("DESCRIPTOR_INVALID", f"descriptor {name} is not a digest")
            strings[name] = raw
        dimensions = value["dimensions"]
        if (
            isinstance(dimensions, bool)
            or not isinstance(dimensions, int)
            or not 1 <= dimensions <= MAX_EMBEDDING_DIMENSIONS
        ):
            raise _corrupted("DESCRIPTOR_INVALID", "descriptor dimensions are invalid")
        return cls(dimensions=dimensions, **strings)

    @property
    def pin(self) -> EmbeddingModelPin:
        return EmbeddingModelPin(
            model_ref=self.model_ref,
            model_version=self.model_version,
            model_digest=self.model_digest,
            tokenizer_ref=self.tokenizer_ref,
            tokenizer_digest=self.tokenizer_digest,
            dimensions=self.dimensions,
            normalization_profile=self.normalization_profile,
        )

    @property
    def digest(self) -> str:
        return canonical_digest(self.to_mapping())

    @property
    def store_ref(self) -> str:
        return EMBEDDING_PREFIX + _hex(self.digest)


@dataclass(frozen=True, slots=True)
class ParallelLayout:
    """Physical layout of one parallel representation version in one partition.

    ``representation_version`` here is the *layout key* handed to the index
    port: the digest of the parallel lineage and the semantic representation
    version.  It differs from every native layout key, so parallel entries
    never share a collection with the pointers the store coordinator owns.
    """

    representation_version: str
    embedding_dimensions: int

    @classmethod
    def of(cls, pin: EmbeddingModelPin) -> ParallelLayout:
        return cls(
            representation_version=canonical_digest(
                {
                    "representation_lineage": PARALLEL_LINEAGE,
                    "representation_version": pin.representation_version,
                }
            ),
            embedding_dimensions=pin.dimensions,
        )


class RepresentationIndexPort(Protocol):
    """Policy-partitioned vector projection addressed by parallel layout."""

    def upsert(
        self,
        partition: MemoryPartition,
        profile: ParallelLayout,
        store_ref: str,
        payload: Mapping[str, object],
        vector: Sequence[float],
    ) -> None:
        """Write one entry into the physical partition of ``partition``/``profile``."""

    def search(
        self,
        partition: MemoryPartition,
        representation_version: str,
        vector: Sequence[float],
        *,
        limit: int,
        offset: int,
    ) -> Sequence[IndexHit]:
        """Ranked page of the partition layout only; deterministic order."""

    def read_back(
        self, partition: MemoryPartition, representation_version: str, store_ref: str
    ) -> IndexEntry | None:
        """The stored payload and the indexed vector of one entry."""

    def entries(
        self, partition: MemoryPartition, representation_version: str
    ) -> Sequence[IndexHit]:
        """Every entry of the physical layout (reconciliation)."""

    def remove(
        self, partition: MemoryPartition, representation_version: str, store_ref: str
    ) -> None:
        """Delete one entry."""


# --------------------------------------------------------------------------
# Representation records (descriptor authority)
# --------------------------------------------------------------------------


class RepresentationState(StrEnum):
    BUILDING = "BUILDING"
    ACTIVE = "ACTIVE"


RECORD_FIELDS = frozenset(
    {
        "partition_digest",
        "representation_version",
        "pin",
        "state",
        "manifest_digest",
        "audit_ref",
        "entries",
        "operation_id",
        "updated_at",
    }
)


@dataclass(frozen=True, slots=True)
class RepresentationRecord:
    """State of one parallel representation version of one partition.

    ``entries`` maps each embedded ``memory_version_ref`` to its descriptor
    store ref, sorted; ``manifest_digest`` and ``audit_ref`` (the success
    receipt the record serves under) are set only when ``ACTIVE``.
    """

    partition_digest: str
    representation_version: str
    pin: EmbeddingModelPin
    state: RepresentationState
    manifest_digest: str | None
    audit_ref: str | None
    entries: tuple[tuple[str, str], ...]
    operation_id: str
    updated_at: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "partition_digest": self.partition_digest,
            "representation_version": self.representation_version,
            "pin": self.pin.to_mapping(),
            "state": self.state.value,
            "manifest_digest": self.manifest_digest,
            "audit_ref": self.audit_ref,
            "entries": [list(entry) for entry in self.entries],
            "operation_id": self.operation_id,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_mapping(cls, value: object) -> RepresentationRecord:
        if not isinstance(value, Mapping) or set(value) != RECORD_FIELDS:
            raise _corrupted("REPRESENTATION_RECORD_INVALID", "record is not a closed record")
        pin_raw, entries_raw = value["pin"], value["entries"]
        if not isinstance(pin_raw, Mapping) or not isinstance(entries_raw, list):
            raise _corrupted("REPRESENTATION_RECORD_INVALID", "record members have invalid types")
        try:
            pin = EmbeddingModelPin(**{str(k): v for k, v in pin_raw.items()})
            state = RepresentationState(str(value["state"]))
        except (TypeError, ValueError, MemoryAdmissionError) as exc:
            raise _corrupted("REPRESENTATION_RECORD_INVALID", "record pin or state invalid") from exc
        entries: list[tuple[str, str]] = []
        for entry in entries_raw:
            if (
                not isinstance(entry, list)
                or len(entry) != 2
                or not all(isinstance(part, str) and part for part in entry)
            ):
                raise _corrupted("REPRESENTATION_RECORD_INVALID", "record entry is invalid")
            entries.append((str(entry[0]), str(entry[1])))
        strings = {
            name: value[name]
            for name in ("partition_digest", "representation_version", "operation_id", "updated_at")
        }
        manifest, audit_ref = value["manifest_digest"], value["audit_ref"]
        if not all(isinstance(v, str) and v for v in strings.values()) or not all(
            digest is None or (isinstance(digest, str) and DIGEST.fullmatch(digest))
            for digest in (manifest, audit_ref)
        ):
            raise _corrupted("REPRESENTATION_RECORD_INVALID", "record strings are invalid")
        record = cls(
            partition_digest=str(strings["partition_digest"]),
            representation_version=str(strings["representation_version"]),
            pin=pin,
            state=state,
            manifest_digest=manifest if isinstance(manifest, str) else None,
            audit_ref=audit_ref if isinstance(audit_ref, str) else None,
            entries=tuple(entries),
            operation_id=str(strings["operation_id"]),
            updated_at=str(strings["updated_at"]),
        )
        if (
            list(record.entries) != sorted(record.entries)
            or record.pin.representation_version != record.representation_version
            or (record.state is RepresentationState.ACTIVE) != (record.manifest_digest is not None)
            or (record.state is RepresentationState.ACTIVE) != (record.audit_ref is not None)
        ):
            raise _corrupted("REPRESENTATION_RECORD_INVALID", "record is not canonical")
        return record

    @property
    def digest(self) -> str:
        return canonical_digest(self.to_mapping())


def manifest_digest(
    partition_digest: str, pin: EmbeddingModelPin, descriptors: Sequence[EmbeddingDescriptor]
) -> str:
    """Digest of a rebuild: only source versions, pin and descriptors, never time."""

    return canonical_digest(
        {
            "representation_lineage": PARALLEL_LINEAGE,
            "partition_digest": partition_digest,
            "representation_version": pin.representation_version,
            "pin_digest": pin.digest,
            "entries": [
                [descriptor.memory_version_ref, descriptor.store_ref]
                for descriptor in sorted(descriptors, key=lambda d: d.memory_version_ref)
            ],
        }
    )


class EmbeddingRepresentationStore(Protocol):
    """Authority for parallel representation records and descriptors only."""

    def record(
        self, partition_digest: str, representation_version: str
    ) -> RepresentationRecord | None:
        """The current record of one partition and representation version."""

    def put_record(self, record: RepresentationRecord, *, expected_digest: str | None) -> None:
        """Replace the record only if the current one has ``expected_digest``.

        ``None`` means no record may exist yet; any other occupant raises
        ``MEMORY_IDEMPOTENCY_CONFLICT`` (compare-and-set).
        """

    def put_descriptor(self, descriptor: EmbeddingDescriptor) -> None:
        """Store once under its content-addressed store ref."""

    def descriptor(self, store_ref: str) -> EmbeddingDescriptor | None:
        """One stored descriptor."""

    def descriptors(
        self, partition_digest: str, representation_version: str
    ) -> tuple[EmbeddingDescriptor, ...]:
        """Every stored descriptor of one partition and representation version."""

    def remove_descriptor(self, store_ref: str) -> None:
        """Delete one descriptor (invalidation)."""


def record_conflict() -> MemoryEmbeddingError:
    """Raised by representation stores when a compare-and-set loses."""

    return MemoryEmbeddingError(
        "MEMORY_IDEMPOTENCY_CONFLICT",
        "REPRESENTATION_RECORD_CONFLICT",
        "the representation record changed concurrently",
    )


# --------------------------------------------------------------------------
# Policy and audit ports, receipts
# --------------------------------------------------------------------------


class RepresentationPolicy(Protocol):
    """Live policy decision for generating a representation of one partition."""

    def authorize_representation(
        self, partition: MemoryPartition, pin: EmbeddingModelPin, context: GovernedContext
    ) -> MemoryPolicyDecision:
        """Decide whether ``context`` may embed ``partition`` with ``pin``."""


class RepresentationAuditSink(Protocol):
    def record(self, event: Mapping[str, object]) -> None:
        """Append one audit event; raising fails the operation closed."""

    def contains(self, audit_ref: str) -> bool:
        """Whether the event with ``audit_ref`` is held; raising fails closed."""


@dataclass(frozen=True, slots=True)
class RepresentationReceipt:
    action: str
    partition_ref: str
    representation_version: str
    pin_digest: str
    manifest_digest: str
    entries: tuple[tuple[str, str], ...]
    invalidated: tuple[str, ...]
    audit_ref: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "action": self.action,
            "partition_ref": self.partition_ref,
            "representation_version": self.representation_version,
            "pin_digest": self.pin_digest,
            "manifest_digest": self.manifest_digest,
            "entries": [list(entry) for entry in self.entries],
            "invalidated": list(self.invalidated),
            "audit_ref": self.audit_ref,
        }


# --------------------------------------------------------------------------
# Coordinator
# --------------------------------------------------------------------------


class EmbeddingLifecycleCoordinator(MemoryStoreCoordinator):
    """The store coordinator plus pinned, parallel, rebuildable vector representations.

    Native commits, reads and reconciliation are inherited unchanged.  Vector
    candidate lookup resolves the profile to a pin first and is served from the
    parallel layout whenever that partition has a parallel representation of
    the requested version.
    """

    def __init__(
        self,
        *,
        ledger: MemoryVersionLedger,
        metadata: MemoryMetadataStore,
        content: MemoryContentStore,
        cipher: ContentCipher,
        lexical: MemoryLexicalIndexPort,
        vector: MemoryVectorIndexPort,
        clock: TrustedClock,
        models: EmbeddingModelRegistry,
        representations: EmbeddingRepresentationStore,
        representation_index: RepresentationIndexPort,
        policy: RepresentationPolicy,
        markings: MarkingDominance,
        audit: RepresentationAuditSink,
        limits: StoreLimits | None = None,
    ) -> None:
        super().__init__(
            ledger=ledger,
            metadata=metadata,
            content=content,
            cipher=cipher,
            lexical=lexical,
            vector=vector,
            clock=clock,
            limits=limits,
        )
        self._models = models
        self._representations = representations
        self._representation_index = representation_index
        self._policy = policy
        self._markings = markings
        self._audit = audit
        # Bounded label set: (operation, "OK" or reason code).
        self._metrics: Counter[tuple[str, str]] = Counter()

    def metrics(self) -> Mapping[tuple[str, str], int]:
        return MappingProxyType(dict(self._metrics))

    # -- query embedding ---------------------------------------------------

    def embed_query(self, profile: VectorProfile, text: str) -> tuple[float, ...]:
        """Embed a query with exactly the pinned model of ``profile``."""

        model, pin = self._models.resolve(profile)
        if not isinstance(text, str) or not text.strip():
            raise MemoryEmbeddingError("MEMORY_SCHEMA_INVALID", "QUERY_INVALID", "query is empty")
        return self._embed(model, pin, text)

    # -- rebuild and invalidation -------------------------------------------

    def rebuild(
        self,
        partition_ref: str,
        profile: VectorProfile,
        *,
        binding: VerifiedGovernedContextBinding | None,
        operation_id: str,
    ) -> RepresentationReceipt:
        """Deterministically (re)build the parallel representation of one partition."""

        return self._observed(
            "rebuild",
            REBUILD_ACTION,
            binding,
            (partition_ref, profile, operation_id),
            lambda context: self._rebuild(partition_ref, profile, context, operation_id),
        )

    def invalidate(
        self,
        partition_ref: str,
        profile: VectorProfile,
        *,
        binding: VerifiedGovernedContextBinding | None,
        operation_id: str,
    ) -> RepresentationReceipt:
        """Remove descriptors of versions that are no longer current and ``ACTIVE``."""

        return self._observed(
            "invalidate",
            INVALIDATE_ACTION,
            binding,
            (partition_ref, profile, operation_id),
            lambda context: self._invalidate(partition_ref, profile, context, operation_id),
        )

    def _observed(
        self,
        operation: str,
        audit_action: str,
        binding: VerifiedGovernedContextBinding | None,
        request: tuple[str, VectorProfile, str],
        action: _Action,
    ) -> RepresentationReceipt:
        partition_ref, profile, operation_id = request
        if not isinstance(binding, VerifiedGovernedContextBinding):
            self._metrics[(operation, "AUTHENTICATION_REQUIRED")] += 1
            error = MemoryEmbeddingError(
                "AUTHENTICATION_REQUIRED",
                "BINDING_MISSING",
                "representation generation requires an authenticated governed-context binding",
            )
            self._record_denial(audit_action, error, partition_ref, profile, operation_id, None)
            raise error
        context = binding.expected
        try:
            receipt = action(context)
        except MemoryAdmissionError as exc:
            if exc.correlation_id is None:
                exc.correlation_id = context.correlation_id
            self._metrics[(operation, exc.reason_code)] += 1
            self._record_denial(audit_action, exc, partition_ref, profile, operation_id, context)
            raise
        self._metrics[(operation, "OK")] += 1
        return receipt

    def _record_denial(
        self,
        action: str,
        error: MemoryAdmissionError,
        partition_ref: object,
        profile: object,
        operation_id: object,
        context: GovernedContext | None,
    ) -> None:
        """Write the denial event of one refusal; an unaudited denial still fails closed."""

        operation = operation_id if isinstance(operation_id, str) else None
        event: dict[str, object] = {
            "action": action + ".denied",
            "operation_id": operation,
            "causation_id": operation,
            "correlation_id": None if context is None else context.correlation_id,
            "governed_context_digest": None if context is None else context.digest(),
            "partition_ref": partition_ref if isinstance(partition_ref, str) else None,
            "representation_version": (
                profile.representation_version if isinstance(profile, VectorProfile) else None
            ),
            "reason_code": error.reason_code,
            "detail_code": error.detail_code,
            "evaluated_at": format_utc_timestamp(self._clock.now()),
        }
        try:
            self._audit.record(MappingProxyType({**event, "audit_ref": canonical_digest(event)}))
        except Exception as exc:  # noqa: BLE001 -- an unaudited denial still fails closed
            unaudited = MemoryEmbeddingError(
                "CONTROL_PLANE_UNAVAILABLE",
                "AUDIT_UNAVAILABLE",
                "representation audit failed closed",
            )
            unaudited.correlation_id = error.correlation_id
            raise unaudited from exc

    def _authorized_partition(
        self, partition_ref: str, pin: EmbeddingModelPin, context: GovernedContext
    ) -> MemoryPartition:
        """Representation generation executes under an authorized GCS (ADD §2.8)."""

        partition = next(
            (p for p in self._metadata.partitions() if p.ref == partition_ref), None
        )
        # Absent and unauthorized partitions are indistinguishable.
        denied = MemoryEmbeddingError(
            "POLICY_DENIED", "PARTITION_NOT_AUTHORIZED", "partition is not authorized"
        )
        if partition is None:
            raise denied
        if (
            partition.tenant_id != context.tenant_id
            or partition.organization_id != context.organization_id
            or partition.domain_id != context.domain_id
            or partition.purpose != context.purpose
            or partition.policy_bundle_digest != context.policy_bundle_digest
            or partition.ontology_release_digest != context.ontology_release_digest
            or not set(partition.compartments) <= set(context.compartments)
        ):
            raise denied
        try:
            dominated = self._markings.dominates(
                context.classification_marking_ref, partition.classification_marking_ref
            )
        except MemoryAdmissionError:
            dominated = False
        if not dominated:
            raise denied
        try:
            decision = self._policy.authorize_representation(partition, pin, context)
        except MemoryAdmissionError:
            raise
        except Exception as exc:  # noqa: BLE001 -- unavailable policy fails closed
            raise MemoryEmbeddingError(
                "CONTROL_PLANE_UNAVAILABLE",
                "POLICY_UNAVAILABLE",
                "representation policy evaluation failed closed",
            ) from exc
        if not isinstance(decision, MemoryPolicyDecision):
            raise MemoryEmbeddingError(
                "CONTROL_PLANE_UNAVAILABLE", "POLICY_DECISION_INVALID", "no policy decision"
            )
        if decision.policy_bundle_digest != context.policy_bundle_digest:
            raise MemoryEmbeddingError(
                "STALE_POLICY",
                "POLICY_BUNDLE_MISMATCH",
                "representation decision was not evaluated against the context bundle",
            )
        if not decision.permitted:
            raise MemoryEmbeddingError(
                "POLICY_DENIED", "REPRESENTATION_DENIED", "representation policy denied"
            )
        return partition

    def _rebuild(
        self,
        partition_ref: str,
        profile: VectorProfile,
        context: GovernedContext,
        operation_id: str,
    ) -> RepresentationReceipt:
        _require_operation(operation_id)
        model, pin = self._models.resolve(profile)
        partition = self._authorized_partition(partition_ref, pin, context)
        layout = ParallelLayout.of(pin)
        current = self._representations.record(partition.digest, pin.representation_version)
        building = RepresentationRecord(
            partition_digest=partition.digest,
            representation_version=pin.representation_version,
            pin=pin,
            state=RepresentationState.BUILDING,
            manifest_digest=None,
            audit_ref=None,
            entries=() if current is None else current.entries,
            operation_id=operation_id,
            updated_at=format_utc_timestamp(self._clock.now()),
        )
        # From here on, retrieval of this version in this partition fails closed.
        self._representations.put_record(
            building, expected_digest=None if current is None else current.digest
        )
        descriptors: list[EmbeddingDescriptor] = []
        try:
            for stored, item in self._eligible(partition).values():
                descriptors.append(self._embed_version(partition, layout, model, pin, stored, item))
            invalidated = self._sweep(partition, layout, pin, descriptors)
        except MemoryAdmissionError:
            raise
        except Exception as exc:  # noqa: BLE001 -- every backend failure fails closed
            raise _not_ready(
                "REBUILD_INCOMPLETE",
                f"representation stays BUILDING: {type(exc).__name__}",
            ) from exc
        return self._activate(
            REBUILD_ACTION,
            partition,
            pin,
            building,
            descriptors,
            invalidated,
            operation_id,
            context,
        )

    def _invalidate(
        self,
        partition_ref: str,
        profile: VectorProfile,
        context: GovernedContext,
        operation_id: str,
    ) -> RepresentationReceipt:
        _require_operation(operation_id)
        _, pin = self._models.resolve(profile)
        partition = self._authorized_partition(partition_ref, pin, context)
        current = self._representations.record(partition.digest, pin.representation_version)
        if current is None:
            raise _not_ready("REPRESENTATION_ABSENT", "no parallel representation to invalidate")
        if current.state is not RepresentationState.ACTIVE:
            raise _not_ready("REPRESENTATION_REBUILDING", "representation is being rebuilt")
        if current.pin != pin:
            raise _not_ready("REPRESENTATION_VERSION_MIXED", "representation pin changed")
        self._require_receipt(current)
        eligible = self._eligible(partition)
        keep: list[EmbeddingDescriptor] = []
        for _, store_ref in current.entries:
            descriptor = self._representations.descriptor(store_ref)
            if descriptor is None:
                raise _corrupted("DESCRIPTOR_MISSING", "a manifest descriptor is missing")
            if _current(descriptor, eligible):
                keep.append(descriptor)
        try:
            invalidated = self._sweep(partition, ParallelLayout.of(pin), pin, keep)
        except MemoryAdmissionError:
            raise
        except Exception as exc:  # noqa: BLE001 -- every backend failure fails closed
            raise _not_ready(
                "INVALIDATION_INCOMPLETE", f"invalidation failed: {type(exc).__name__}"
            ) from exc
        return self._activate(
            INVALIDATE_ACTION,
            partition,
            pin,
            current,
            keep,
            invalidated,
            operation_id,
            context,
        )

    def _eligible(
        self, partition: MemoryPartition
    ) -> dict[str, tuple[StoredVersion, GovernedMemoryItem]]:
        """Current, ``ACTIVE``, unexpired, undeleted vector-bearing versions, canonically ordered."""

        now = self._clock.now()
        eligible: dict[str, tuple[StoredVersion, GovernedMemoryItem]] = {}
        versions = sorted(
            self._metadata.versions_in(partition.digest),
            key=lambda s: (s.staged.memory_item_id, s.staged.memory_version),
        )
        for stored in versions:
            if stored.state is not VersionState.COMMITTED:
                continue
            item = stored.staged.verify()
            if self._metadata.head(item.memory_item_id) != item.memory_version:
                continue
            if item.lifecycle_status is not LifecycleStatus.ACTIVE:
                continue
            if item.deletion_epoch is not None:
                continue
            if item.expires_at is not None and item.expires_at <= now:
                continue
            if RepresentationKind.VECTOR not in item.representation_kinds:
                continue
            eligible[item.version_ref] = (stored, item)
        return eligible

    def _embed(self, model: EmbeddingModel, pin: EmbeddingModelPin, text: str) -> tuple[float, ...]:
        try:
            first = model.embed(text)
            second = model.embed(text)
            served = model.pin
        except Exception as exc:  # noqa: BLE001 -- an unavailable model fails closed
            raise _not_ready(
                "EMBEDDING_WORKER_UNAVAILABLE", f"embedding failed: {type(exc).__name__}"
            ) from exc
        if served != pin:
            raise _corrupted("EMBEDDING_MODEL_DRIFT", "model no longer serves its pin")
        values = _unit_vector(pin, first)
        if _unit_vector(pin, second) != values:
            raise _not_ready("EMBEDDING_NONDETERMINISTIC", "model output is not deterministic")
        return values

    def _embed_version(
        self,
        partition: MemoryPartition,
        layout: ParallelLayout,
        model: EmbeddingModel,
        pin: EmbeddingModelPin,
        stored: StoredVersion,
        item: GovernedMemoryItem,
    ) -> EmbeddingDescriptor:
        staged = stored.staged
        # Verified committed content: digest, cipher context and projections bind.
        materialized = self.read_version(partition, staged.memory_item_id, staged.memory_version)
        values = self._embed(model, pin, lexical_document(materialized.payload))
        descriptor = EmbeddingDescriptor.build(item, staged.item_digest, partition, pin, values)
        self._representation_index.upsert(
            partition, layout, descriptor.store_ref, descriptor.to_mapping(), values
        )
        stored_entry = self._representation_index.read_back(
            partition, layout.representation_version, descriptor.store_ref
        )
        if not _entry_binds(stored_entry, descriptor):
            raise _not_ready("PROJECTION_UNVERIFIED", "representation read-back does not match")
        registered = self._representations.descriptor(descriptor.store_ref)
        if registered is not None and registered != descriptor:
            # Descriptors are derived from metadata, content and pin: a corrupted
            # row is replaced by the recomputed one, then re-verified.
            self._representations.remove_descriptor(descriptor.store_ref)
        self._representations.put_descriptor(descriptor)
        registered = self._representations.descriptor(descriptor.store_ref)
        if registered != descriptor:
            raise _not_ready("DESCRIPTOR_UNVERIFIED", "descriptor read-back does not match")
        return descriptor

    def _sweep(
        self,
        partition: MemoryPartition,
        layout: ParallelLayout,
        pin: EmbeddingModelPin,
        keep: Sequence[EmbeddingDescriptor],
    ) -> tuple[str, ...]:
        """Remove every descriptor and index entry outside ``keep``."""

        wanted = {descriptor.store_ref: descriptor for descriptor in keep}
        invalidated: set[str] = set()
        for descriptor in self._representations.descriptors(
            partition.digest, pin.representation_version
        ):
            if descriptor.store_ref not in wanted:
                self._representation_index.remove(
                    partition, layout.representation_version, descriptor.store_ref
                )
                self._representations.remove_descriptor(descriptor.store_ref)
                invalidated.add(descriptor.memory_version_ref)
        for hit in self._representation_index.entries(partition, layout.representation_version):
            expected = wanted.get(hit.store_ref)
            if expected is None or dict(hit.payload) != expected.to_mapping():
                self._representation_index.remove(
                    partition, layout.representation_version, hit.store_ref
                )
        return tuple(sorted(invalidated))

    def _activate(
        self,
        action: str,
        partition: MemoryPartition,
        pin: EmbeddingModelPin,
        previous: RepresentationRecord,
        descriptors: Sequence[EmbeddingDescriptor],
        invalidated: tuple[str, ...],
        operation_id: str,
        context: GovernedContext,
    ) -> RepresentationReceipt:
        entries = tuple(sorted((d.memory_version_ref, d.store_ref) for d in descriptors))
        digest = manifest_digest(partition.digest, pin, descriptors)
        now = format_utc_timestamp(self._clock.now())
        event: dict[str, object] = {
            "action": action,
            "operation_id": operation_id,
            "causation_id": operation_id,
            "correlation_id": context.correlation_id,
            "governed_context_digest": context.digest(),
            "partition_ref": partition.ref,
            "representation_version": pin.representation_version,
            "pin": pin.to_mapping(),
            "pin_digest": pin.digest,
            "manifest_digest": digest,
            "embedded_count": len(entries),
            "invalidated": list(invalidated),
            "classification_marking_ref": partition.classification_marking_ref,
            "evaluated_at": now,
        }
        audit_ref = canonical_digest(event)
        active = RepresentationRecord(
            partition_digest=partition.digest,
            representation_version=pin.representation_version,
            pin=pin,
            state=RepresentationState.ACTIVE,
            manifest_digest=digest,
            audit_ref=audit_ref,
            entries=entries,
            operation_id=operation_id,
            updated_at=now,
        )
        # The success receipt follows the committed compare-and-set: a lost CAS
        # raises here and leaves only the denial event of ``_observed``.  The
        # record serves only once the audit store holds ``audit_ref``.
        self._representations.put_record(active, expected_digest=previous.digest)
        try:
            self._audit.record(MappingProxyType({**event, "audit_ref": audit_ref}))
        except Exception as exc:  # noqa: BLE001 -- no audit, no activation
            self._withdraw(active)
            raise MemoryEmbeddingError(
                "CONTROL_PLANE_UNAVAILABLE",
                "AUDIT_UNAVAILABLE",
                "representation audit failed closed",
            ) from exc
        return RepresentationReceipt(
            action=action,
            partition_ref=partition.ref,
            representation_version=pin.representation_version,
            pin_digest=pin.digest,
            manifest_digest=digest,
            entries=entries,
            invalidated=invalidated,
            audit_ref=audit_ref,
        )

    def _withdraw(self, active: RepresentationRecord) -> None:
        """Put an unaudited ``ACTIVE`` record back to ``BUILDING``, bounded.

        Best effort only: an unaudited record never serves anyway, because its
        ``audit_ref`` is absent from the audit store (``_require_receipt``).
        """

        building = RepresentationRecord(
            partition_digest=active.partition_digest,
            representation_version=active.representation_version,
            pin=active.pin,
            state=RepresentationState.BUILDING,
            manifest_digest=None,
            audit_ref=None,
            entries=active.entries,
            operation_id=active.operation_id,
            updated_at=active.updated_at,
        )
        for _ in range(WITHDRAW_ATTEMPTS):
            try:
                self._representations.put_record(building, expected_digest=active.digest)
            except Exception:  # noqa: BLE001 -- re-read who owns the record now
                self._metrics[("withdraw", "RETRY")] += 1
            else:
                return
            try:
                current = self._representations.record(
                    active.partition_digest, active.representation_version
                )
            except Exception:  # noqa: BLE001 -- unknown owner: try again
                continue
            if current is None or current.digest != active.digest:
                self._metrics[("withdraw", "SUPERSEDED")] += 1
                return  # a newer operation owns the record
        self._metrics[("withdraw", "INCOMPLETE")] += 1

    def _require_receipt(self, record: RepresentationRecord) -> None:
        """An ``ACTIVE`` record serves only while its success receipt is held."""

        if record.audit_ref is None:
            raise _not_ready(
                "REPRESENTATION_UNAUDITED", "the representation has no success receipt"
            )
        try:
            held = self._audit.contains(record.audit_ref)
        except Exception as exc:  # noqa: BLE001 -- unknown receipt fails closed
            raise MemoryEmbeddingError(
                "CONTROL_PLANE_UNAVAILABLE",
                "AUDIT_UNAVAILABLE",
                "representation receipt lookup failed closed",
            ) from exc
        if held is not True:
            raise _not_ready(
                "REPRESENTATION_UNAUDITED", "the representation has no success receipt"
            )

    # -- retrieval ---------------------------------------------------------

    def vector_candidates(
        self,
        partition: MemoryPartition,
        profile: VectorProfile,
        vector: Sequence[float],
        *,
        limit: int,
        valid_at: datetime | None = None,
    ) -> tuple[BoundHit, ...]:
        """Only pinned profiles; one representation version per partition, never mixed.

        ``valid_at`` is the instant of the validity window; when omitted, the
        ``valid_at`` of the enclosing ``EmbeddingSearchService`` search, else
        the boundary time.  Versions outside it are skipped like ineligible ones.
        """

        scope = _SEARCH_SCOPE.get()
        if scope is not None and scope.coordinator is not self:
            scope = None  # another coordinator's search
        if valid_at is None and scope is not None:
            valid_at = scope.valid_at
        try:
            return self._vector_candidates(partition, profile, vector, limit, valid_at)
        except MemoryAdmissionError as exc:
            self._metrics[("vector_candidates", exc.reason_code)] += 1
            self._record_denial(
                SEARCH_ACTION,
                exc,
                partition.ref if isinstance(partition, MemoryPartition) else None,
                profile,
                None if scope is None else scope.operation_id,
                None if scope is None else scope.context,
            )
            raise

    def _vector_candidates(
        self,
        partition: MemoryPartition,
        profile: VectorProfile,
        vector: Sequence[float],
        limit: int,
        valid_at: datetime | None,
    ) -> tuple[BoundHit, ...]:
        _, pin = self._models.resolve(profile)
        if valid_at is not None and (
            not isinstance(valid_at, datetime) or valid_at.utcoffset() is None
        ):
            raise MemoryEmbeddingError(
                "MEMORY_SCHEMA_INVALID", "QUERY_INVALID", "valid_at must be an aware timestamp"
            )
        if isinstance(vector, (str, bytes)) or not isinstance(vector, Sequence):
            raise MemoryEmbeddingError(
                "MEMORY_SCHEMA_INVALID", "QUERY_INVALID", "query vector must be a sequence"
            )
        if len(vector) != pin.dimensions:
            raise MemoryEmbeddingError(
                "MEMORY_SCHEMA_INVALID",
                "EMBEDDING_DIMENSION_MISMATCH",
                "query vector length differs from the pinned dimensions",
            )
        record = self._representations.record(partition.digest, pin.representation_version)
        if record is None:
            return super().vector_candidates(partition, profile, vector, limit=limit)
        if record.state is not RepresentationState.ACTIVE:
            raise _not_ready("REPRESENTATION_REBUILDING", "representation is being rebuilt")
        if record.pin != pin:
            raise _not_ready(
                "REPRESENTATION_VERSION_MIXED", "representation was built with another pin"
            )
        self._require_receipt(record)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise MemoryEmbeddingError(
                "MEMORY_SCHEMA_INVALID", "QUERY_INVALID", "limit must be >= 1"
            )
        eligible = self._eligible(partition)
        manifest = dict(record.entries)
        for ref, (stored, _) in eligible.items():
            store_ref = manifest.get(ref)
            descriptor = None if store_ref is None else self._representations.descriptor(store_ref)
            if descriptor is None or not hmac.compare_digest(
                descriptor.item_digest, stored.staged.item_digest
            ):
                raise _not_ready(
                    "REPRESENTATION_INCOMPLETE",
                    "a current version has no descriptor in this representation version",
                )
            if descriptor.store_ref != store_ref:
                raise _not_ready("PROJECTION_DRIFT", "a registered descriptor does not bind")
        instant = self._clock.now() if valid_at is None else valid_at
        # Completeness is checked on every current version; only those valid at
        # ``instant`` may occupy a candidate slot.
        window = {
            ref: entry for ref, entry in eligible.items() if _valid_at(entry[1], instant)
        }
        layout = ParallelLayout.of(pin)
        members = frozenset(manifest.values())
        results: list[BoundHit] = []
        seen: set[str] = set()
        offset = 0
        page_size = self._limits.page_size
        while len(results) < limit:
            if offset >= self._limits.max_scanned_hits:
                raise _not_ready("UNBOUND_BACKLOG", "representation requires invalidation")
            hits = self._representation_index.search(
                partition, layout.representation_version, vector, limit=page_size, offset=offset
            )
            for hit in hits:
                if hit.store_ref in seen:
                    continue
                seen.add(hit.store_ref)
                bound = self._bound(partition, pin, members, window, hit)
                if bound is not None:
                    results.append(bound)
                    if len(results) == limit:
                        break
            if len(hits) < page_size:
                break
            offset += len(hits)
        return tuple(results)

    def _bound(
        self,
        partition: MemoryPartition,
        pin: EmbeddingModelPin,
        members: frozenset[str],
        eligible: Mapping[str, tuple[StoredVersion, GovernedMemoryItem]],
        hit: IndexHit,
    ) -> BoundHit | None:
        try:
            descriptor = EmbeddingDescriptor.from_mapping(dict(hit.payload))
        except MemoryAdmissionError:
            return None  # not a descriptor: unbound, never a candidate
        if descriptor.representation_version != pin.representation_version:
            raise _not_ready(
                "REPRESENTATION_VERSION_MIXED",
                "an entry of another representation version is in the layout",
            )
        if descriptor.store_ref != hit.store_ref or descriptor.store_ref not in members:
            return None  # not a manifest member of this layout: unbound
        if not _current(descriptor, eligible):
            return None  # revoked, expired, reclassified, superseded, deleted or out of window
        # A manifest member must still be exactly its registered descriptor and
        # its persisted vector; otherwise the ranking itself is untrustworthy.
        if self._representations.descriptor(descriptor.store_ref) != descriptor or not (
            _entry_binds(
                self._representation_index.read_back(
                    partition, ParallelLayout.of(pin).representation_version, hit.store_ref
                ),
                descriptor,
            )
        ):
            raise _not_ready("PROJECTION_DRIFT", "a parallel representation entry does not bind")
        return BoundHit(
            memory_version_ref=descriptor.memory_version_ref,
            item_digest=descriptor.item_digest,
            content_digest=descriptor.content_digest,
            store_ref=descriptor.store_ref,
            representation_kind=RepresentationKind.VECTOR.value,
            representation_version=descriptor.representation_version,
            classification_marking_ref=descriptor.classification_marking_ref,
            score=float(hit.score),
        )


# --------------------------------------------------------------------------
# Search service: caller scope of representation lookups
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _SearchScope:
    coordinator: object
    context: GovernedContext
    operation_id: str | None
    valid_at: datetime | None


_SEARCH_SCOPE: ContextVar[_SearchScope | None] = ContextVar(
    "ocor_memory_embedding_search_scope", default=None
)


class EmbeddingSearchService(MemorySearchService):
    """``MemorySearchService`` over an ``EmbeddingLifecycleCoordinator``.

    Behaviour and contract are those of the 0052 service; for the duration of
    one authenticated search the coordinator's vector lookups additionally
    know their caller: a lookup denial carries the binding's correlation, the
    request's ``operation_id`` and the governed-context digest, and the lookup
    evaluates the validity window at the request's ``valid_at``.  The scope
    holds raw request values; the service validates the request and rejects
    it before any lookup can read them.
    """

    def search(
        self,
        request: Mapping[str, object],
        *,
        binding: VerifiedGovernedContextBinding | None,
    ) -> MemorySearchResponse:
        if not isinstance(binding, VerifiedGovernedContextBinding) or not isinstance(
            request, Mapping
        ):
            return super().search(request, binding=binding)
        operation_id = request.get("operation_id")
        valid_at: datetime | None = None
        raw_valid_at = request.get("valid_at")
        if isinstance(raw_valid_at, str):
            try:
                valid_at = parse_utc_timestamp(raw_valid_at)
            except TimestampError:
                valid_at = None  # the service rejects it before any lookup
        token = _SEARCH_SCOPE.set(
            _SearchScope(
                coordinator=self._coordinator,
                context=binding.expected,
                operation_id=(
                    operation_id if isinstance(operation_id, str) and operation_id else None
                ),
                valid_at=valid_at,
            )
        )
        try:
            return super().search(request, binding=binding)
        finally:
            _SEARCH_SCOPE.reset(token)


class _Action(Protocol):
    def __call__(self, context: GovernedContext) -> RepresentationReceipt: ...


def _valid_at(item: GovernedMemoryItem, instant: datetime) -> bool:
    """The version's validity window contains ``instant`` (as in retrieval)."""

    return item.valid_from <= instant and (item.valid_until is None or instant < item.valid_until)


def _require_operation(operation_id: str) -> None:
    if not isinstance(operation_id, str) or not operation_id or operation_id != operation_id.strip():
        raise MemoryEmbeddingError(
            "MEMORY_SCHEMA_INVALID", "OPERATION_ID_INVALID", "operation_id is invalid"
        )


def _current(
    descriptor: EmbeddingDescriptor,
    eligible: Mapping[str, tuple[StoredVersion, GovernedMemoryItem]],
) -> bool:
    """The descriptor binds a version that is still current, eligible and unchanged."""

    entry = eligible.get(descriptor.memory_version_ref)
    if entry is None:
        return False
    stored, item = entry
    return (
        hmac.compare_digest(descriptor.item_digest, stored.staged.item_digest)
        and descriptor.content_digest == item.content_digest
        and descriptor.classification_marking_ref == item.classification_marking_ref
        and descriptor.purpose == item.purpose
        and descriptor.partition_digest == stored.staged.partition.digest
    )


def _entry_binds(entry: IndexEntry | None, descriptor: EmbeddingDescriptor) -> bool:
    """The persisted payload is the descriptor and the persisted vector its binary32 digest."""

    if entry is None or dict(entry.payload) != descriptor.to_mapping():
        return False
    body = entry.body
    if isinstance(body, (str, bytes)) or not isinstance(body, Sequence):
        return False
    if len(body) != descriptor.dimensions:
        return False
    values: list[float] = []
    for value in body:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        if not math.isfinite(value):
            return False
        values.append(float(value))
    try:
        actual = stored_vector_digest(values)
    except MemoryAdmissionError:
        return False
    return hmac.compare_digest(actual, descriptor.stored_vector_digest)


__all__ = [
    "EMBEDDING_PREFIX",
    "EmbeddingDescriptor",
    "EmbeddingLifecycleCoordinator",
    "EmbeddingModel",
    "EmbeddingModelPin",
    "EmbeddingModelRegistry",
    "EmbeddingRepresentationStore",
    "MemoryEmbeddingError",
    "ParallelLayout",
    "RepresentationAuditSink",
    "RepresentationIndexPort",
    "RepresentationPolicy",
    "RepresentationReceipt",
    "RepresentationRecord",
    "RepresentationState",
    "manifest_digest",
    "record_conflict",
]
