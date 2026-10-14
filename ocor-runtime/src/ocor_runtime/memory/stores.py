"""C8 governed memory -- metadata, content, lexical and vector stores.

Implements the ``MemoryMetadataStore``, ``MemoryContentStore``,
``MemoryLexicalIndexPort`` and ``MemoryVectorIndexPort`` slice of the
``GovernedMemoryService`` (ADD v1.3 Part II §§2.5-2.8, 2.13; LLD v1.1
§§2.8.1-2.8.4; change-control §7):

* Every admitted version is stored under one ``MemoryPartition``: the full
  isolation tuple (tenant, organization, domain, compartments, marking,
  purpose, policy bundle, ontology release, memory scope and the scope owner
  bindings).  Content objects, lexical entries and vector entries live only in
  the physical partition derived from that digest; nothing is shared across
  partitions, so there is no cross-compartment dedupe, ANN graph or index.
* Each representation (``STRUCTURED``, ``FULL_TEXT``, ``VECTOR``) has a
  ``RepresentationPointer`` binding item/version, item digest, content digest,
  representation version and digest, partition, marking, policy bundle, scope
  and deletion epoch.  The index entry carries exactly that pointer, so every
  projection is rebuildable from metadata plus content and every hit can be
  checked against the metadata authority.  Pointer references are opaque URNs:
  backend identifiers never cross the ports.
* ``MemoryStoreCoordinator.commit`` stages metadata and pointers as
  ``PENDING``, writes the encrypted content-addressed payload and each
  projection, re-reads every write instead of trusting an acknowledgement --
  the pointer and the indexed body (the searched document, the ranked vector at
  the binary32 precision the vector index persists) must both bind -- and
  only then flips the version and all its pointers to ``COMMITTED`` in a single
  metadata transaction that also advances the item's versioned head pointer.
  A version that is ``PENDING`` -- partial store visibility -- is never
  materialised (``REPRESENTATION_NOT_READY``), and an index hit whose pointer is
  not a committed metadata pointer -- an unbound representation -- never
  reaches a result, a rank slot or a count.
* ``MemoryStoreCoordinator.reconcile`` rolls complete pending versions forward,
  retracts the projections and content of incomplete ones, and removes every
  unbound index entry and unreferenced content object (fail closed).
* Version 2 index and metadata ports (OCOR-DEV-REM-0020) store the version's
  ``index_attributes`` beside each entry and evaluate an
  ``EligibilityPredicate`` inside the backend query; a commit retires the
  projections of the item's predecessor, so only the head is searchable
  (LLD v1.1 §2.8.4).  A lookup made inside an ``eligibility_scope`` on an index
  that cannot evaluate the predicate fails closed.

The module is backend-free (``OCOR_LANGUAGE_POLICY.md`` row 8): stores, indexes
and the content cipher are ports.  Policy evaluation and the derivation of the
caller's authorized partition belong to retrieval (OCOR-DEV-0052); memory
metadata is authority for memory metadata only, never for canonical state.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import struct
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from ..kernel.canonical import canonical_digest, format_utc_timestamp, parse_utc_timestamp
from ..kernel.governance import TrustedClock
from .model import (
    DIGEST,
    SCOPE_BINDINGS,
    AdmittedMemoryVersion,
    GovernedMemoryItem,
    MemoryAdmissionError,
    MemoryScope,
    MemoryVersionLedger,
    RepresentationKind,
    memory_version_ref,
)

PARTITION_PREFIX = "urn:ocor:memory-partition:"
REPRESENTATION_PREFIX = "urn:ocor:memory-representation:"
CONTENT_OBJECT_PREFIX = "urn:ocor:memory-content-object:"
VECTOR_ENCODING = b"ocor-memory-vector:f64be:"
STORED_VECTOR_ENCODING = b"ocor-memory-vector:f32be:"
# Fresh seals tried before short plaintext found inside the ciphertext is
# treated as a non-encrypting cipher rather than a coincidence.
SEAL_ATTEMPTS = 32


class MemoryStoreError(MemoryAdmissionError):
    """Fail-closed store refusal carrying the closed memory Problem vocabulary."""


class MemoryStoreCorrupted(MemoryStoreError):
    """Persisted memory metadata, content or pointers failed verification."""

    def __init__(self, detail_code: str, message: str) -> None:
        super().__init__("INTERNAL_ERROR", detail_code, message)


def _hex(digest: str) -> str:
    return digest.removeprefix("urn:sha256:")


def _sha256(data: bytes) -> str:
    return "urn:sha256:" + hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# Partitions and representation profiles
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MemoryPartition:
    """The full isolation tuple of ADD v1.3 Part II §2.6 for one stored item.

    ``scope_bindings`` are the owner bindings of the item's scope (the schema
    ``allOf`` bindings: run, task, agent, team, project or federation policy),
    so two items share a partition only if every isolation attribute matches.
    """

    tenant_id: str
    organization_id: str
    domain_id: str
    compartments: tuple[str, ...]
    classification_marking_ref: str
    purpose: str
    policy_bundle_digest: str
    ontology_release_digest: str
    memory_scope: MemoryScope
    scope_bindings: tuple[tuple[str, str], ...]

    @classmethod
    def for_item(cls, item: GovernedMemoryItem) -> MemoryPartition:
        bindings: list[tuple[str, str]] = []
        for name in SCOPE_BINDINGS[item.memory_scope]:
            value = getattr(item, name)
            if not isinstance(value, str) or not value:
                raise MemoryStoreError(
                    "MEMORY_SCHEMA_INVALID",
                    "SCOPE_BINDING_MISSING",
                    f"{item.memory_scope.value} partition requires {name}",
                )
            bindings.append((name, value))
        return cls(
            tenant_id=item.tenant_id,
            organization_id=item.organization_id,
            domain_id=item.domain_id,
            compartments=tuple(sorted(item.compartments)),
            classification_marking_ref=item.classification_marking_ref,
            purpose=item.purpose,
            policy_bundle_digest=item.policy_bundle_digest,
            ontology_release_digest=item.ontology_release_digest,
            memory_scope=item.memory_scope,
            scope_bindings=tuple(bindings),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "tenant_id": self.tenant_id,
            "organization_id": self.organization_id,
            "domain_id": self.domain_id,
            "compartments": list(self.compartments),
            "classification_marking_ref": self.classification_marking_ref,
            "purpose": self.purpose,
            "policy_bundle_digest": self.policy_bundle_digest,
            "ontology_release_digest": self.ontology_release_digest,
            "memory_scope": self.memory_scope.value,
            "scope_bindings": [[name, value] for name, value in self.scope_bindings],
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> MemoryPartition:
        expected = {
            "tenant_id",
            "organization_id",
            "domain_id",
            "compartments",
            "classification_marking_ref",
            "purpose",
            "policy_bundle_digest",
            "ontology_release_digest",
            "memory_scope",
            "scope_bindings",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise MemoryStoreCorrupted("PARTITION_INVALID", "partition is not a closed record")
        raw_compartments = value["compartments"]
        raw_bindings = value["scope_bindings"]
        if not isinstance(raw_compartments, list) or not isinstance(raw_bindings, list):
            raise MemoryStoreCorrupted("PARTITION_INVALID", "partition members have invalid types")
        compartments: list[str] = []
        for compartment in raw_compartments:
            if not isinstance(compartment, str) or not compartment:
                raise MemoryStoreCorrupted("PARTITION_INVALID", "partition compartment is invalid")
            compartments.append(compartment)
        bindings: list[tuple[str, str]] = []
        for binding in raw_bindings:
            if (
                not isinstance(binding, list)
                or len(binding) != 2
                or not all(isinstance(part, str) and part for part in binding)
            ):
                raise MemoryStoreCorrupted("PARTITION_INVALID", "partition binding is invalid")
            bindings.append((str(binding[0]), str(binding[1])))
        strings: dict[str, str] = {}
        for name in expected - {"compartments", "scope_bindings", "memory_scope"}:
            raw = value[name]
            if not isinstance(raw, str) or not raw:
                raise MemoryStoreCorrupted("PARTITION_INVALID", f"partition {name} is invalid")
            strings[name] = raw
        try:
            scope = MemoryScope(str(value["memory_scope"]))
        except ValueError as exc:
            raise MemoryStoreCorrupted("PARTITION_INVALID", "partition scope is invalid") from exc
        partition = cls(
            tenant_id=strings["tenant_id"],
            organization_id=strings["organization_id"],
            domain_id=strings["domain_id"],
            compartments=tuple(compartments),
            classification_marking_ref=strings["classification_marking_ref"],
            purpose=strings["purpose"],
            policy_bundle_digest=strings["policy_bundle_digest"],
            ontology_release_digest=strings["ontology_release_digest"],
            memory_scope=scope,
            scope_bindings=tuple(bindings),
        )
        if list(partition.compartments) != sorted(partition.compartments):
            raise MemoryStoreCorrupted("PARTITION_INVALID", "partition is not canonical")
        return partition

    @property
    def digest(self) -> str:
        return canonical_digest(self.to_mapping())

    @property
    def ref(self) -> str:
        return PARTITION_PREFIX + _hex(self.digest)


@dataclass(frozen=True, slots=True)
class LexicalProfile:
    """Versioned full-text analyzer profile; a new version is a new representation."""

    profile_ref: str = "urn:ocor:memory-lexical:simple"
    version: int = 1
    text_search_configuration: str = "simple"

    @property
    def representation_version(self) -> str:
        return canonical_digest(
            {
                "representation_kind": RepresentationKind.FULL_TEXT.value,
                "profile_ref": self.profile_ref,
                "version": self.version,
                "text_search_configuration": self.text_search_configuration,
            }
        )


@dataclass(frozen=True, slots=True)
class VectorProfile:
    """Embedding representation version bound to the item's model pins (§2.8)."""

    embedding_model_ref: str
    embedding_model_digest: str
    embedding_dimensions: int
    embedding_normalization_profile: str

    @classmethod
    def for_item(cls, item: GovernedMemoryItem) -> VectorProfile:
        if (
            item.embedding_model_ref is None
            or item.embedding_model_digest is None
            or item.embedding_dimensions is None
            or item.embedding_normalization_profile is None
        ):
            raise MemoryStoreError(
                "MEMORY_SCHEMA_INVALID",
                "EMBEDDING_BINDING_MISSING",
                "VECTOR representation requires the embedding model binding",
            )
        return cls(
            embedding_model_ref=item.embedding_model_ref,
            embedding_model_digest=item.embedding_model_digest,
            embedding_dimensions=item.embedding_dimensions,
            embedding_normalization_profile=item.embedding_normalization_profile,
        )

    @property
    def representation_version(self) -> str:
        return canonical_digest(
            {
                "representation_kind": RepresentationKind.VECTOR.value,
                "embedding_model_ref": self.embedding_model_ref,
                "embedding_model_digest": self.embedding_model_digest,
                "embedding_dimensions": self.embedding_dimensions,
                "embedding_normalization_profile": self.embedding_normalization_profile,
            }
        )


def structured_representation_version(item: GovernedMemoryItem) -> str:
    return canonical_digest(
        {
            "representation_kind": RepresentationKind.STRUCTURED.value,
            "content_schema_ref": item.content_schema_ref,
        }
    )


def vector_digest(values: Sequence[float]) -> str:
    """Canonical digest of an embedding: IEEE-754 binary64 big-endian values."""

    return _sha256(VECTOR_ENCODING + struct.pack(f">{len(values)}d", *values))


def stored_vector_digest(values: Sequence[float]) -> str:
    """Digest of the vector as a vector index persists it: IEEE-754 binary32 big-endian.

    Vector indexes store binary32 components, so the projection is bound at that
    precision; the binary64 embedding itself is bound by ``embedding_digest``.
    """

    try:
        packed = struct.pack(f">{len(values)}f", *values)
    except (OverflowError, struct.error) as exc:
        raise MemoryStoreError(
            "MEMORY_SCHEMA_INVALID",
            "EMBEDDING_INVALID",
            "embedding is not representable at the vector index precision",
        ) from exc
    return _sha256(STORED_VECTOR_ENCODING + packed)


def lexical_representation_digest(representation_version: str, document: str) -> str:
    return canonical_digest(
        {
            "representation_version": representation_version,
            "document_digest": _sha256(document.encode()),
        }
    )


def vector_representation_digest(
    representation_version: str, embedding_digest: str, values: Sequence[float]
) -> str:
    return canonical_digest(
        {
            "representation_version": representation_version,
            "embedding_digest": embedding_digest,
            "stored_vector_digest": stored_vector_digest(values),
        }
    )


def lexical_document(payload: bytes) -> str:
    """The full-text document is the strict UTF-8 payload, so it is rebuildable."""

    try:
        document = bytes(payload).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MemoryStoreError(
            "MEMORY_SCHEMA_INVALID",
            "LEXICAL_DOCUMENT_INVALID",
            "FULL_TEXT representation requires a UTF-8 payload",
        ) from exc
    if "\x00" in document or not document.strip():
        raise MemoryStoreError(
            "MEMORY_SCHEMA_INVALID",
            "LEXICAL_DOCUMENT_INVALID",
            "FULL_TEXT representation requires a non-empty document without NUL",
        )
    return document


def validate_embedding(item: GovernedMemoryItem, vector: Sequence[float]) -> tuple[float, ...]:
    """The supplied embedding must be exactly the one the item digests."""

    profile = VectorProfile.for_item(item)
    if isinstance(vector, (str, bytes)) or not isinstance(vector, Sequence):
        raise MemoryStoreError(
            "MEMORY_SCHEMA_INVALID", "EMBEDDING_INVALID", "embedding must be a sequence"
        )
    values: list[float] = []
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MemoryStoreError(
                "MEMORY_SCHEMA_INVALID", "EMBEDDING_INVALID", "embedding values must be numbers"
            )
        if not math.isfinite(value):
            raise MemoryStoreError(
                "MEMORY_SCHEMA_INVALID", "EMBEDDING_INVALID", "embedding values must be finite"
            )
        values.append(float(value))
    if len(values) != profile.embedding_dimensions:
        raise MemoryStoreError(
            "MEMORY_SCHEMA_INVALID",
            "EMBEDDING_DIMENSION_MISMATCH",
            "embedding length differs from embedding_dimensions",
        )
    if not any(values):
        raise MemoryStoreError(
            "MEMORY_SCHEMA_INVALID", "EMBEDDING_INVALID", "embedding must not be the zero vector"
        )
    stored_vector_digest(values)
    if not any(struct.unpack(f">{len(values)}f", struct.pack(f">{len(values)}f", *values))):
        raise MemoryStoreError(
            "MEMORY_SCHEMA_INVALID",
            "EMBEDDING_INVALID",
            "embedding vanishes at the vector index precision",
        )
    if item.embedding_digest is None or not hmac.compare_digest(
        vector_digest(values), item.embedding_digest
    ):
        raise MemoryStoreError(
            "MEMORY_SCHEMA_INVALID",
            "EMBEDDING_DIGEST_MISMATCH",
            "embedding_digest does not bind the supplied embedding",
        )
    return tuple(values)


# --------------------------------------------------------------------------
# Versioned representation pointers
# --------------------------------------------------------------------------

POINTER_FIELDS = frozenset(
    {
        "memory_version_ref",
        "item_digest",
        "content_digest",
        "representation_kind",
        "representation_version",
        "representation_digest",
        "partition_digest",
        "classification_marking_ref",
        "policy_bundle_digest",
        "memory_scope",
        "deletion_epoch",
    }
)


@dataclass(frozen=True, slots=True)
class RepresentationPointer:
    """The binding carried by metadata and by every index entry (change-control §7)."""

    memory_version_ref: str
    item_digest: str
    content_digest: str
    representation_kind: RepresentationKind
    representation_version: str
    representation_digest: str
    partition_digest: str
    classification_marking_ref: str
    policy_bundle_digest: str
    memory_scope: MemoryScope
    deletion_epoch: int

    def to_mapping(self) -> dict[str, object]:
        return {
            "memory_version_ref": self.memory_version_ref,
            "item_digest": self.item_digest,
            "content_digest": self.content_digest,
            "representation_kind": self.representation_kind.value,
            "representation_version": self.representation_version,
            "representation_digest": self.representation_digest,
            "partition_digest": self.partition_digest,
            "classification_marking_ref": self.classification_marking_ref,
            "policy_bundle_digest": self.policy_bundle_digest,
            "memory_scope": self.memory_scope.value,
            "deletion_epoch": self.deletion_epoch,
        }

    @classmethod
    def from_mapping(cls, value: object) -> RepresentationPointer:
        """Parse a stored pointer strictly; anything else is not a pointer."""

        if not isinstance(value, Mapping) or set(value) != POINTER_FIELDS:
            raise MemoryStoreCorrupted("POINTER_INVALID", "pointer is not a closed record")
        epoch = value["deletion_epoch"]
        if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
            raise MemoryStoreCorrupted("POINTER_INVALID", "pointer deletion_epoch is invalid")
        strings: dict[str, str] = {}
        for name in POINTER_FIELDS - {"deletion_epoch"}:
            raw = value[name]
            if not isinstance(raw, str) or not raw:
                raise MemoryStoreCorrupted("POINTER_INVALID", f"pointer {name} is invalid")
            strings[name] = raw
        for name in (
            "item_digest",
            "content_digest",
            "representation_version",
            "representation_digest",
            "partition_digest",
            "classification_marking_ref",
            "policy_bundle_digest",
        ):
            if DIGEST.fullmatch(strings[name]) is None:
                raise MemoryStoreCorrupted("POINTER_INVALID", f"pointer {name} is not a digest")
        try:
            kind = RepresentationKind(strings["representation_kind"])
            scope = MemoryScope(strings["memory_scope"])
        except ValueError as exc:
            raise MemoryStoreCorrupted("POINTER_INVALID", "pointer enum is invalid") from exc
        return cls(
            memory_version_ref=strings["memory_version_ref"],
            item_digest=strings["item_digest"],
            content_digest=strings["content_digest"],
            representation_kind=kind,
            representation_version=strings["representation_version"],
            representation_digest=strings["representation_digest"],
            partition_digest=strings["partition_digest"],
            classification_marking_ref=strings["classification_marking_ref"],
            policy_bundle_digest=strings["policy_bundle_digest"],
            memory_scope=scope,
            deletion_epoch=epoch,
        )

    @property
    def digest(self) -> str:
        return canonical_digest(self.to_mapping())

    @property
    def store_ref(self) -> str:
        return REPRESENTATION_PREFIX + _hex(self.digest)


def stage_conflict(version_ref: str) -> MemoryStoreError:
    """Raised by metadata stores when a slot already holds a different stage."""

    return MemoryStoreError(
        "MEMORY_IDEMPOTENCY_CONFLICT",
        "STAGE_CONFLICT",
        f"{version_ref} is already staged with different metadata or pointers",
    )


def predecessor_not_committed(version_ref: str) -> MemoryStoreError:
    """Raised by metadata stores when the head pointer is not exactly ``n - 1``."""

    return MemoryStoreError(
        "REPRESENTATION_NOT_READY",
        "PREDECESSOR_NOT_COMMITTED",
        f"{version_ref} requires its predecessor version to be committed first",
    )


def content_object_ref(partition: MemoryPartition, content_digest: str) -> str:
    """Content address scoped to the partition: no cross-partition dedupe."""

    return CONTENT_OBJECT_PREFIX + _hex(
        canonical_digest({"partition_digest": partition.digest, "content_digest": content_digest})
    )


# --------------------------------------------------------------------------
# Ports
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SealedContent:
    """Ciphertext plus the opaque logical key reference that sealed it."""

    key_ref: str
    ciphertext: bytes


class ContentCipher(Protocol):
    """Authenticated encryption bound to ``context`` (partition and content address)."""

    def seal(self, *, context: Mapping[str, str], plaintext: bytes) -> SealedContent:
        """Encrypt ``plaintext`` so it opens only under the identical context."""

    def open(self, *, context: Mapping[str, str], sealed: SealedContent) -> bytes:
        """Decrypt, raising on any context, key or ciphertext mismatch."""


class MemoryContentStore(Protocol):
    """Encrypted, content-addressed payload store (no canonical-state authority)."""

    def put(self, object_ref: str, partition_digest: str, sealed: SealedContent) -> None:
        """Store once; an existing object is never overwritten."""

    def get(self, object_ref: str) -> SealedContent | None:
        """Return the sealed object, or ``None``."""

    def delete(self, object_ref: str) -> None:
        """Remove the object (reconciliation of unreferenced content)."""

    def refs(self, partition_digest: str) -> tuple[str, ...]:
        """Every object ref stored in one partition."""


class VersionState(StrEnum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"


@dataclass(frozen=True, slots=True)
class StagedVersion:
    """Metadata of one version plus its pointers, as written before projections."""

    memory_item_id: str
    memory_version: int
    item: Mapping[str, object]
    item_digest: str
    audit_ref: str
    partition: MemoryPartition
    content_object_ref: str
    pointers: tuple[RepresentationPointer, ...]
    staged_at: str

    @property
    def memory_version_ref(self) -> str:
        return memory_version_ref(self.memory_item_id, self.memory_version)

    def body(self) -> dict[str, object]:
        """The idempotency-relevant body (everything except the staging time)."""

        return {
            "memory_item_id": self.memory_item_id,
            "memory_version": self.memory_version,
            "item": dict(self.item),
            "item_digest": self.item_digest,
            "audit_ref": self.audit_ref,
            "partition": self.partition.to_mapping(),
            "content_object_ref": self.content_object_ref,
            "pointers": [pointer.to_mapping() for pointer in self.pointers],
        }

    @property
    def stage_digest(self) -> str:
        return canonical_digest(self.body())

    @classmethod
    def from_body(cls, body: Mapping[str, object], staged_at: str) -> StagedVersion:
        """Rebuild a persisted stage strictly; adapters never trust stored bytes."""

        expected = {
            "memory_item_id",
            "memory_version",
            "item",
            "item_digest",
            "audit_ref",
            "partition",
            "content_object_ref",
            "pointers",
        }
        if not isinstance(body, Mapping) or set(body) != expected:
            raise MemoryStoreCorrupted("METADATA_INVALID", "stage is not a closed record")
        item = body["item"]
        partition = body["partition"]
        pointers = body["pointers"]
        version = body["memory_version"]
        strings = {
            name: body[name]
            for name in ("memory_item_id", "item_digest", "audit_ref", "content_object_ref")
        }
        if (
            not isinstance(item, Mapping)
            or not isinstance(partition, Mapping)
            or not isinstance(pointers, list)
            or isinstance(version, bool)
            or not isinstance(version, int)
            or not all(isinstance(value, str) and value for value in strings.values())
            or not isinstance(staged_at, str)
        ):
            raise MemoryStoreCorrupted("METADATA_INVALID", "stage members have invalid types")
        staged = cls(
            memory_item_id=str(strings["memory_item_id"]),
            memory_version=version,
            item=MappingProxyType(dict(item)),
            item_digest=str(strings["item_digest"]),
            audit_ref=str(strings["audit_ref"]),
            partition=MemoryPartition.from_mapping(partition),
            content_object_ref=str(strings["content_object_ref"]),
            pointers=tuple(RepresentationPointer.from_mapping(p) for p in pointers),
            staged_at=staged_at,
        )
        staged.verify()
        return staged

    def verify(self) -> GovernedMemoryItem:
        """Re-validate the stored item and every binding derived from it."""

        try:
            item = GovernedMemoryItem.from_mapping(self.item)
        except MemoryAdmissionError as exc:
            raise MemoryStoreCorrupted("METADATA_INVALID", f"stored item invalid: {exc}") from exc
        if not hmac.compare_digest(item.digest(), self.item_digest):
            raise MemoryStoreCorrupted("METADATA_DIGEST_MISMATCH", "item digest mismatch")
        if (item.memory_item_id, item.memory_version) != (
            self.memory_item_id,
            self.memory_version,
        ):
            raise MemoryStoreCorrupted("METADATA_INVALID", "stored version slot mismatch")
        if MemoryPartition.for_item(item) != self.partition:
            raise MemoryStoreCorrupted("METADATA_INVALID", "stored partition mismatch")
        if content_object_ref(self.partition, item.content_digest) != self.content_object_ref:
            raise MemoryStoreCorrupted("METADATA_INVALID", "stored content ref mismatch")
        kinds = sorted(pointer.representation_kind.value for pointer in self.pointers)
        if kinds != sorted(kind.value for kind in item.representation_kinds):
            raise MemoryStoreCorrupted("METADATA_INVALID", "stored pointers mismatch")
        for pointer in self.pointers:
            if (
                pointer.memory_version_ref != item.version_ref
                or pointer.item_digest != self.item_digest
                or pointer.content_digest != item.content_digest
                or pointer.partition_digest != self.partition.digest
            ):
                raise MemoryStoreCorrupted("METADATA_INVALID", "stored pointer binding mismatch")
        return item


@dataclass(frozen=True, slots=True)
class StoredVersion:
    staged: StagedVersion
    state: VersionState
    committed_at: str | None


class MemoryMetadataStore(Protocol):
    """Authority for memory metadata only: versions, pointers and head pointers."""

    def stage(self, staged: StagedVersion) -> StoredVersion:
        """Atomically insert the version and its pointers as ``PENDING``.

        An existing version with the same stage digest is returned unchanged;
        any other occupant of the slot raises ``MEMORY_IDEMPOTENCY_CONFLICT``.
        """

    def get(self, memory_item_id: str, memory_version: int) -> StoredVersion | None:
        """Return one exact version, whatever its state."""

    def commit(
        self, memory_item_id: str, memory_version: int, *, stage_digest: str, committed_at: str
    ) -> StoredVersion:
        """Atomically flip version and pointers to ``COMMITTED`` and advance the head.

        Refuses unless the slot holds ``stage_digest`` and, for a version
        ``n > 1``, the head pointer is exactly ``n - 1``.
        """

    def head(self, memory_item_id: str) -> int:
        """Highest committed version, or 0."""

    def pointer(self, store_ref: str) -> tuple[RepresentationPointer, VersionState] | None:
        """The pointer registered under ``store_ref`` and its version state."""

    def versions_in(self, partition_digest: str) -> tuple[StoredVersion, ...]:
        """Every staged or committed version of one partition."""

    def partitions(self) -> tuple[MemoryPartition, ...]:
        """Every partition that has ever received a staged version."""


@dataclass(frozen=True, slots=True)
class IndexHit:
    """One raw index answer: the opaque ref, the stored pointer payload, a score."""

    store_ref: str
    payload: Mapping[str, object]
    score: float


@dataclass(frozen=True, slots=True)
class IndexEntry:
    """One stored entry read back from the backend: pointer payload and indexed body.

    ``body`` is the document the lexical index searches or the vector the
    vector index ranks, exactly as persisted; ``None`` when the backend cannot
    return it consistently.
    """

    payload: Mapping[str, object]
    body: str | tuple[float, ...] | None


class MemoryLexicalIndexPort(Protocol):
    """Policy-partitioned full-text projection (rebuildable)."""

    def upsert(
        self,
        partition: MemoryPartition,
        profile: LexicalProfile,
        store_ref: str,
        payload: Mapping[str, object],
        document: str,
    ) -> None:
        """Write one entry into the physical partition of ``partition``/``profile``."""

    def search(
        self,
        partition: MemoryPartition,
        representation_version: str,
        query: str,
        *,
        limit: int,
        offset: int,
    ) -> Sequence[IndexHit]:
        """Ranked page of the partition only; deterministic order."""

    def get(
        self, partition: MemoryPartition, representation_version: str, store_ref: str
    ) -> Mapping[str, object] | None:
        """The stored payload of one entry, read from the backend."""

    def read_back(
        self, partition: MemoryPartition, representation_version: str, store_ref: str
    ) -> IndexEntry | None:
        """The stored payload and the indexed body of one entry, read from the backend."""

    def entries(
        self, partition: MemoryPartition, representation_version: str
    ) -> Sequence[IndexHit]:
        """Every entry of the physical partition (reconciliation)."""

    def remove(
        self, partition: MemoryPartition, representation_version: str, store_ref: str
    ) -> None:
        """Delete one entry."""


class MemoryVectorIndexPort(Protocol):
    """Policy-partitioned, representation-versioned embedding projection."""

    def upsert(
        self,
        partition: MemoryPartition,
        profile: VectorProfile,
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
        """Ranked page of the partition only; deterministic order."""

    def get(
        self, partition: MemoryPartition, representation_version: str, store_ref: str
    ) -> Mapping[str, object] | None:
        """The stored payload of one entry, read from the backend."""

    def read_back(
        self, partition: MemoryPartition, representation_version: str, store_ref: str
    ) -> IndexEntry | None:
        """The stored payload and the indexed body of one entry, read from the backend."""

    def entries(
        self, partition: MemoryPartition, representation_version: str
    ) -> Sequence[IndexHit]:
        """Every entry of the physical partition (reconciliation)."""

    def remove(
        self, partition: MemoryPartition, representation_version: str, store_ref: str
    ) -> None:
        """Delete one entry."""


# --------------------------------------------------------------------------
# Eligibility attributes and predicates (index port version 2, OCOR-DEV-REM-0020)
# --------------------------------------------------------------------------

INDEX_ATTRIBUTES_VERSION = "urn:ocor:memory-index-attributes:1"
# "No upper bound" for valid_until/expires_at; below 2**53 so that every
# backend compares it exactly as an integer or as a double.
UNBOUNDED_US = 9_000_000_000_000_000
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _micros(instant: datetime) -> int:
    if not isinstance(instant, datetime) or instant.utcoffset() is None:
        raise MemoryStoreError(
            "MEMORY_SCHEMA_INVALID", "QUERY_INVALID", "instant must be an aware timestamp"
        )
    return (instant - _EPOCH) // timedelta(microseconds=1)


def index_attributes(item: GovernedMemoryItem) -> dict[str, object]:
    """Eligibility attributes of one version, stored beside its index entries.

    Everything but ``superseded`` is immutable for a version (every semantic
    change is a new version); ``superseded`` becomes true when a later
    version of the item commits, so a searchable projection is only ever the
    item's head.  The attributes never replace the pointer: hits are still
    bound to committed metadata and re-validated before materialisation.
    """

    return {
        "memory_item_id": item.memory_item_id,
        "memory_version": item.memory_version,
        "memory_kind": item.memory_kind.value,
        "memory_scope": item.memory_scope.value,
        "source_kind": item.source_kind.value,
        "content_schema_ref": item.content_schema_ref,
        "confidence": float(item.confidence),
        "taint_labels": sorted(item.taint_labels),
        "lifecycle_status": item.lifecycle_status.value,
        "deleted": item.deletion_epoch is not None,
        "valid_from_us": _micros(item.valid_from),
        "valid_until_us": UNBOUNDED_US if item.valid_until is None else _micros(item.valid_until),
        "expires_at_us": UNBOUNDED_US if item.expires_at is None else _micros(item.expires_at),
        "superseded": False,
    }


@dataclass(frozen=True, slots=True)
class EligibilityPredicate:
    """The eligibility predicates a search pushes into every index query.

    A version matches when it is the item's head (not ``superseded``),
    ``ACTIVE``, not deleted, of a requested kind and scope, valid at
    ``valid_at``, unexpired at ``now`` and accepted by the structured filters.
    ``accepts`` is the reference semantics every adapter must reproduce.
    """

    memory_kinds: frozenset[str]
    memory_scopes: frozenset[str]
    valid_at: datetime
    now: datetime
    source_kinds: frozenset[str] | None = None
    content_schema_refs: frozenset[str] | None = None
    min_confidence: float | None = None
    exclude_taint_labels: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.memory_kinds or not self.memory_scopes:
            raise MemoryStoreError(
                "MEMORY_SCHEMA_INVALID", "QUERY_INVALID", "kinds and scopes must not be empty"
            )
        _micros(self.valid_at)
        _micros(self.now)

    @property
    def valid_at_us(self) -> int:
        return _micros(self.valid_at)

    @property
    def now_us(self) -> int:
        return _micros(self.now)

    def accepts(self, attributes: Mapping[str, object]) -> bool:
        try:
            if (
                attributes["superseded"] is not False
                or attributes["deleted"] is not False
                or attributes["lifecycle_status"] != "ACTIVE"
                or attributes["memory_kind"] not in self.memory_kinds
                or attributes["memory_scope"] not in self.memory_scopes
            ):
                return False
            valid_from, valid_until, expires_at = (
                attributes["valid_from_us"],
                attributes["valid_until_us"],
                attributes["expires_at_us"],
            )
            if not all(isinstance(v, int) for v in (valid_from, valid_until, expires_at)):
                return False
            assert isinstance(valid_from, int) and isinstance(valid_until, int)
            assert isinstance(expires_at, int)
            if not valid_from <= self.valid_at_us < valid_until or expires_at <= self.now_us:
                return False
            if self.source_kinds is not None and attributes["source_kind"] not in self.source_kinds:
                return False
            if (
                self.content_schema_refs is not None
                and attributes["content_schema_ref"] not in self.content_schema_refs
            ):
                return False
            confidence = attributes["confidence"]
            if self.min_confidence is not None and (
                not isinstance(confidence, (int, float)) or confidence < self.min_confidence
            ):
                return False
            labels = attributes["taint_labels"]
            if not isinstance(labels, list):
                return False
            return not self.exclude_taint_labels & set(labels)
        except KeyError:
            return False  # an entry without the attribute record is never eligible

    def to_mapping(self) -> dict[str, object]:
        return {
            "attributes_version": INDEX_ATTRIBUTES_VERSION,
            "memory_kinds": sorted(self.memory_kinds),
            "memory_scopes": sorted(self.memory_scopes),
            "valid_at": format_utc_timestamp(self.valid_at),
            "now": format_utc_timestamp(self.now),
            "source_kinds": None if self.source_kinds is None else sorted(self.source_kinds),
            "content_schema_refs": None
            if self.content_schema_refs is None
            else sorted(self.content_schema_refs),
            "min_confidence": self.min_confidence,
            "exclude_taint_labels": sorted(self.exclude_taint_labels),
        }


@runtime_checkable
class EligibilityIndexPort(Protocol):
    """Version 2 of the lexical and vector index ports.

    ``upsert`` additionally takes ``attributes=index_attributes(item)``, stored
    beside (never inside) the pointer payload: ``get``, ``read_back`` and
    ``entries`` keep returning the pointer payload only.
    """

    def search_eligible(
        self,
        partition: MemoryPartition,
        representation_version: str,
        query: str | Sequence[float],
        *,
        where: EligibilityPredicate,
        limit: int,
        offset: int,
    ) -> Sequence[IndexHit]:
        """Ranked page of the partition restricted by ``where`` inside the backend query."""

    def score_entries(
        self,
        partition: MemoryPartition,
        representation_version: str,
        query: str | Sequence[float],
        store_refs: Sequence[str],
    ) -> Mapping[str, float]:
        """The backend's own score of ``query`` for exactly these entries (0 when unmatched)."""

    def retire(
        self,
        partition: MemoryPartition,
        representation_version: str,
        memory_item_id: str,
        below_version: int,
    ) -> None:
        """Mark every entry of the item older than ``below_version`` as ``superseded``."""


@runtime_checkable
class EligibilityMetadataStore(Protocol):
    """Version 2 of the metadata store: eligibility predicates inside the query."""

    def eligible_versions(
        self, partition_digest: str, where: EligibilityPredicate
    ) -> tuple[StoredVersion, ...]:
        """Committed head versions of the partition whose item matches ``where``."""


_ELIGIBILITY: ContextVar[EligibilityPredicate | None] = ContextVar(
    "ocor_memory_eligibility_predicate", default=None
)


@contextmanager
def eligibility_scope(predicate: EligibilityPredicate) -> Iterator[None]:
    """Push ``predicate`` into every candidate lookup made inside the block.

    Lookups keep their signature (subclasses such as the embedding lifecycle
    coordinator override them); a lookup that runs inside a scope must search
    a version 2 index or fail closed.
    """

    if not isinstance(predicate, EligibilityPredicate):
        raise MemoryStoreError(
            "MEMORY_SCHEMA_INVALID", "QUERY_INVALID", "eligibility predicate is invalid"
        )
    token = _ELIGIBILITY.set(predicate)
    try:
        yield
    finally:
        _ELIGIBILITY.reset(token)


# --------------------------------------------------------------------------
# Coordinator
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StoreLimits:
    """Boundary configuration of the store coordinator."""

    lexical_profile: LexicalProfile = field(default_factory=LexicalProfile)
    page_size: int = 16
    max_scanned_hits: int = 256
    reconcile_grace: timedelta = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class StoreCommitReceipt:
    memory_version_ref: str
    item_digest: str
    partition_ref: str
    content_object_ref: str
    representations: tuple[tuple[str, str, str], ...]
    state: str
    head_version: int
    audit_ref: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "memory_version_ref": self.memory_version_ref,
            "item_digest": self.item_digest,
            "audit_ref": self.audit_ref,
            "partition_ref": self.partition_ref,
            "content_object_ref": self.content_object_ref,
            "representations": [list(entry) for entry in self.representations],
            "state": self.state,
            "head_version": self.head_version,
        }


@dataclass(frozen=True, slots=True)
class MaterializedVersion:
    item: GovernedMemoryItem
    payload: bytes
    pointers: tuple[RepresentationPointer, ...]
    partition_ref: str


@dataclass(frozen=True, slots=True)
class BoundHit:
    """A candidate whose index entry is a committed metadata pointer."""

    memory_version_ref: str
    item_digest: str
    content_digest: str
    store_ref: str
    representation_kind: str
    representation_version: str
    classification_marking_ref: str
    score: float


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    completed: tuple[str, ...]
    retracted: tuple[str, ...]
    deferred: tuple[str, ...]
    unbound_removed: tuple[str, ...]
    content_removed: tuple[str, ...]

    def to_mapping(self) -> dict[str, object]:
        return {
            "completed": list(self.completed),
            "retracted": list(self.retracted),
            "deferred": list(self.deferred),
            "unbound_removed": list(self.unbound_removed),
            "content_removed": list(self.content_removed),
        }


class _Outcome(StrEnum):
    COMPLETED = "COMPLETED"
    RETRACTED = "RETRACTED"
    DEFERRED = "DEFERRED"


def _persisted_vector(body: object, dimensions: int | None) -> tuple[float, ...] | None:
    if isinstance(body, (str, bytes)) or not isinstance(body, Sequence):
        return None
    if dimensions is None or len(body) != dimensions:
        return None
    values: list[float] = []
    for value in body:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(value):
            return None
        values.append(float(value))
    return tuple(values)


def _not_visible() -> MemoryStoreError:
    # Absent and out-of-partition versions are indistinguishable (no existence leak).
    return MemoryStoreError(
        "MEMORY_VERSION_NOT_FOUND", "VERSION_NOT_VISIBLE", "memory version is not visible"
    )


def _not_ready(detail: str, message: str) -> MemoryStoreError:
    return MemoryStoreError("REPRESENTATION_NOT_READY", detail, message)


def _eligible_index(index: object) -> EligibilityIndexPort:
    # A predicate that cannot be pushed into the backend query fails closed.
    if not isinstance(index, EligibilityIndexPort):
        raise _not_ready(
            "INDEX_PREDICATES_UNSUPPORTED", "the index cannot evaluate eligibility predicates"
        )
    return index


class MemoryStoreCoordinator:
    """Commits admitted versions across the four stores with one visibility switch."""

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
        limits: StoreLimits | None = None,
    ) -> None:
        self._ledger = ledger
        self._metadata = metadata
        self._content = content
        self._cipher = cipher
        self._lexical = lexical
        self._vector = vector
        self._clock = clock
        self._limits = limits if limits is not None else StoreLimits()
        if self._limits.page_size < 1 or self._limits.max_scanned_hits < 1:
            raise ValueError("store limits must be positive")

    # -- commit -----------------------------------------------------------

    def commit(
        self,
        record: AdmittedMemoryVersion,
        *,
        payload: bytes,
        embedding: Sequence[float] | None = None,
    ) -> StoreCommitReceipt:
        """Store one admitted version; it becomes visible only when complete."""

        try:
            return self._commit(record, payload, embedding)
        except MemoryAdmissionError as exc:
            # Correlate every refusal with the admission that produced the record.
            if exc.correlation_id is None and isinstance(record, AdmittedMemoryVersion):
                correlation = record.audit_event.get("correlation_id")
                exc.correlation_id = correlation if isinstance(correlation, str) else None
            raise

    def _commit(
        self,
        record: AdmittedMemoryVersion,
        payload: bytes,
        embedding: Sequence[float] | None,
    ) -> StoreCommitReceipt:
        staged, document, vector = self._prepare(record, payload, embedding)
        stored = self._metadata.stage(staged)
        if stored.staged.stage_digest != staged.stage_digest:
            raise MemoryStoreCorrupted("METADATA_INVALID", "metadata returned another stage")
        if stored.state is VersionState.COMMITTED:
            self._verify_committed(stored)
            # A replayed commit also repairs a retirement lost after the switch.
            self._retire_predecessors(stored.staged)
            return self._receipt(stored)
        partition = staged.partition
        item = record.item
        try:
            self._write_content(staged, item.content_digest, payload)
            for pointer in staged.pointers:
                self._write_projection(partition, item, pointer, document, vector)
        except MemoryStoreError:
            raise
        except Exception as exc:  # noqa: BLE001 -- every backend failure fails closed
            raise _not_ready(
                "STORE_COMMIT_INCOMPLETE",
                f"{staged.memory_version_ref} stays PENDING: {type(exc).__name__}",
            ) from exc
        try:
            committed = self._metadata.commit(
                staged.memory_item_id,
                staged.memory_version,
                stage_digest=staged.stage_digest,
                committed_at=format_utc_timestamp(self._clock.now()),
            )
        except MemoryStoreError:
            raise
        except Exception as exc:  # noqa: BLE001 -- a lost metadata commit fails closed
            raise _not_ready(
                "STORE_COMMIT_INCOMPLETE",
                f"{staged.memory_version_ref} stays PENDING: {type(exc).__name__}",
            ) from exc
        if committed.state is not VersionState.COMMITTED:
            raise MemoryStoreCorrupted("METADATA_INVALID", "metadata commit was not applied")
        self._retire_predecessors(committed.staged)
        return self._receipt(committed)

    def _retire_predecessors(self, staged: StagedVersion) -> None:
        """Make the previous version's projections unsearchable (LLD v1.1 §2.8.4).

        Runs after the visibility switch, so a failure leaves the predecessor
        searchable but never served: every hit is still bound to the head and
        re-validated.  The commit then fails closed and a replay retries it.
        """

        if staged.memory_version < 2:
            return
        layouts: set[tuple[MemoryPartition, RepresentationKind, str]] = set()
        for stored in (
            self._metadata.get(staged.memory_item_id, staged.memory_version - 1),
            StoredVersion(staged, VersionState.COMMITTED, None),
        ):
            if stored is None:
                continue
            for pointer in stored.staged.pointers:
                if pointer.representation_kind is not RepresentationKind.STRUCTURED:
                    layouts.add(
                        (
                            stored.staged.partition,
                            pointer.representation_kind,
                            pointer.representation_version,
                        )
                    )
        try:
            for partition, kind, version in sorted(
                layouts, key=lambda layout: (layout[0].digest, layout[1].value, layout[2])
            ):
                index = self._index(kind)
                if isinstance(index, EligibilityIndexPort):
                    index.retire(partition, version, staged.memory_item_id, staged.memory_version)
        except Exception as exc:  # noqa: BLE001 -- a lost retirement fails closed
            raise _not_ready(
                "PREDECESSOR_NOT_RETIRED",
                f"{staged.memory_version_ref} committed; predecessor projections not retired: "
                f"{type(exc).__name__}",
            ) from exc

    def _prepare(
        self,
        record: AdmittedMemoryVersion,
        payload: bytes,
        embedding: Sequence[float] | None,
    ) -> tuple[StagedVersion, str | None, tuple[float, ...] | None]:
        if not isinstance(record, AdmittedMemoryVersion):
            raise MemoryStoreError(
                "MEMORY_SCHEMA_INVALID", "RECORD_INVALID", "commit requires an admitted version"
            )
        try:
            record.verify()
        except MemoryAdmissionError as exc:
            raise MemoryStoreError(
                "MEMORY_SCHEMA_INVALID", "RECORD_INVALID", "admitted version does not verify"
            ) from exc
        item = record.item
        admitted = self._ledger.get(item.memory_item_id, item.memory_version)
        if (
            admitted is None
            or not hmac.compare_digest(admitted.item_digest, record.item_digest)
            or not hmac.compare_digest(admitted.receipt.audit_ref, record.receipt.audit_ref)
        ):
            raise MemoryStoreError(
                "MEMORY_VERSION_NOT_FOUND",
                "VERSION_NOT_ADMITTED",
                "only versions recorded by the admission ledger are stored",
            )
        if not isinstance(payload, (bytes, bytearray)) or not hmac.compare_digest(
            _sha256(bytes(payload)), item.content_digest
        ):
            raise MemoryStoreError(
                "MEMORY_SCHEMA_INVALID",
                "CONTENT_DIGEST_MISMATCH",
                "content_digest does not bind payload",
            )
        kinds = set(item.representation_kinds)
        document = (
            lexical_document(bytes(payload)) if RepresentationKind.FULL_TEXT in kinds else None
        )
        vector: tuple[float, ...] | None = None
        if RepresentationKind.VECTOR in kinds:
            if embedding is None:
                raise MemoryStoreError(
                    "MEMORY_SCHEMA_INVALID",
                    "EMBEDDING_MISSING",
                    "VECTOR representation requires its embedding",
                )
            vector = validate_embedding(item, embedding)
        elif embedding is not None:
            raise MemoryStoreError(
                "MEMORY_SCHEMA_INVALID",
                "UNBOUND_REPRESENTATION",
                "embedding supplied for an item without VECTOR representation",
            )
        partition = MemoryPartition.for_item(item)
        pointers = tuple(
            self._pointer(item, record.item_digest, partition, kind, document, vector)
            for kind in sorted(kinds, key=lambda k: k.value)
        )
        staged = StagedVersion(
            memory_item_id=item.memory_item_id,
            memory_version=item.memory_version,
            item=MappingProxyType(item.to_mapping()),
            item_digest=record.item_digest,
            audit_ref=record.receipt.audit_ref,
            partition=partition,
            content_object_ref=content_object_ref(partition, item.content_digest),
            pointers=pointers,
            staged_at=format_utc_timestamp(self._clock.now()),
        )
        return staged, document, vector

    def _pointer(
        self,
        item: GovernedMemoryItem,
        item_digest: str,
        partition: MemoryPartition,
        kind: RepresentationKind,
        document: str | None,
        vector: tuple[float, ...] | None,
    ) -> RepresentationPointer:
        if kind is RepresentationKind.FULL_TEXT:
            assert document is not None
            version = self._limits.lexical_profile.representation_version
            representation = lexical_representation_digest(version, document)
        elif kind is RepresentationKind.VECTOR:
            assert item.embedding_digest is not None and vector is not None
            version = VectorProfile.for_item(item).representation_version
            representation = vector_representation_digest(version, item.embedding_digest, vector)
        else:
            version = structured_representation_version(item)
            representation = item_digest
        return RepresentationPointer(
            memory_version_ref=item.version_ref,
            item_digest=item_digest,
            content_digest=item.content_digest,
            representation_kind=kind,
            representation_version=version,
            representation_digest=representation,
            partition_digest=partition.digest,
            classification_marking_ref=item.classification_marking_ref,
            policy_bundle_digest=item.policy_bundle_digest,
            memory_scope=item.memory_scope,
            deletion_epoch=item.deletion_epoch if item.deletion_epoch is not None else 0,
        )

    @staticmethod
    def _cipher_context(staged: StagedVersion, content_digest: str) -> dict[str, str]:
        return {
            "content_object_ref": staged.content_object_ref,
            "partition_digest": staged.partition.digest,
            "content_digest": content_digest,
        }

    def _write_content(self, staged: StagedVersion, content_digest: str, payload: bytes) -> None:
        context = self._cipher_context(staged, content_digest)
        if self._content.get(staged.content_object_ref) is None:
            sealed = self._seal(context, bytes(payload))
            self._content.put(staged.content_object_ref, staged.partition.digest, sealed)
        self._read_content(staged, content_digest)

    def _seal(self, context: Mapping[str, str], plaintext: bytes) -> SealedContent:
        """Seal before any write; refuse output that is not context-bound ciphertext.

        Plaintext found verbatim inside the ciphertext, at any length, is
        refused.  Short plaintext can occur by chance in genuine ciphertext,
        so a fresh seal is tried up to ``SEAL_ATTEMPTS`` times; a cipher that
        keeps the plaintext (or an empty payload, contained in everything)
        fails closed.  The object must also refuse to open under another
        content address, which a pass-through cipher cannot do.
        """

        for _ in range(SEAL_ATTEMPTS):
            sealed = self._cipher.seal(context=context, plaintext=plaintext)
            if plaintext not in bytes(sealed.ciphertext):
                break
        else:
            raise MemoryStoreCorrupted(
                "CONTENT_NOT_ENCRYPTED", "cipher output contains the plaintext"
            )
        foreign = dict(context)
        foreign["content_digest"] = canonical_digest(
            {"foreign_context_of": context["content_digest"]}
        )
        try:
            self._cipher.open(context=foreign, sealed=sealed)
        except Exception:  # noqa: BLE001 -- refusing the foreign context is the expected outcome
            return sealed
        raise MemoryStoreCorrupted(
            "CONTENT_NOT_ENCRYPTED", "sealed content opens outside its context"
        )

    def _read_content(self, staged: StagedVersion, content_digest: str) -> bytes:
        sealed = self._content.get(staged.content_object_ref)
        if sealed is None:
            raise _not_ready("CONTENT_UNAVAILABLE", "content object is not readable")
        try:
            plaintext = self._cipher.open(
                context=self._cipher_context(staged, content_digest), sealed=sealed
            )
        except Exception as exc:  # noqa: BLE001 -- any decrypt failure is corruption
            raise MemoryStoreCorrupted("CONTENT_UNSEALABLE", "content does not open") from exc
        if not hmac.compare_digest(_sha256(plaintext), content_digest):
            raise MemoryStoreCorrupted("CONTENT_DIGEST_MISMATCH", "content does not bind digest")
        return plaintext

    def _write_projection(
        self,
        partition: MemoryPartition,
        item: GovernedMemoryItem,
        pointer: RepresentationPointer,
        document: str | None,
        vector: tuple[float, ...] | None,
    ) -> None:
        payload = pointer.to_mapping()
        if pointer.representation_kind is RepresentationKind.FULL_TEXT:
            assert document is not None
            if isinstance(self._lexical, EligibilityIndexPort):
                self._lexical.upsert(
                    partition,
                    self._limits.lexical_profile,
                    pointer.store_ref,
                    payload,
                    document,
                    attributes=index_attributes(item),  # type: ignore[call-arg]
                )
            else:
                self._lexical.upsert(
                    partition, self._limits.lexical_profile, pointer.store_ref, payload, document
                )
        elif pointer.representation_kind is RepresentationKind.VECTOR:
            assert vector is not None
            profile = VectorProfile.for_item(item)
            if isinstance(self._vector, EligibilityIndexPort):
                self._vector.upsert(
                    partition,
                    profile,
                    pointer.store_ref,
                    payload,
                    vector,
                    attributes=index_attributes(item),  # type: ignore[call-arg]
                )
            else:
                self._vector.upsert(partition, profile, pointer.store_ref, payload, vector)
        else:
            return  # STRUCTURED is the metadata record itself.
        if not self._projection_bound(partition, item, pointer):
            raise _not_ready("PROJECTION_UNVERIFIED", "projection read-back does not match")

    def _index(self, kind: RepresentationKind) -> MemoryLexicalIndexPort | MemoryVectorIndexPort:
        return self._lexical if kind is RepresentationKind.FULL_TEXT else self._vector

    def _projection_bound(
        self,
        partition: MemoryPartition,
        item: GovernedMemoryItem,
        pointer: RepresentationPointer,
    ) -> bool:
        """Read the entry back: its pointer and its indexed body must both bind.

        The body -- the searched document or the ranked vector -- is re-read
        from the backend and digested; an acknowledged write whose body differs
        from the representation digest of the pointer is not bound.
        """

        if pointer.representation_kind is RepresentationKind.STRUCTURED:
            return True
        stored = self._index(pointer.representation_kind).read_back(
            partition, pointer.representation_version, pointer.store_ref
        )
        if stored is None or dict(stored.payload) != pointer.to_mapping():
            return False
        body = stored.body
        if pointer.representation_kind is RepresentationKind.FULL_TEXT:
            if not isinstance(body, str):
                return False
            actual = lexical_representation_digest(pointer.representation_version, body)
        else:
            values = _persisted_vector(body, item.embedding_dimensions)
            if values is None or item.embedding_digest is None:
                return False
            try:
                actual = vector_representation_digest(
                    pointer.representation_version, item.embedding_digest, values
                )
            except MemoryStoreError:
                return False
        return hmac.compare_digest(actual, pointer.representation_digest)

    def _receipt(self, stored: StoredVersion) -> StoreCommitReceipt:
        staged = stored.staged
        return StoreCommitReceipt(
            memory_version_ref=staged.memory_version_ref,
            item_digest=staged.item_digest,
            partition_ref=staged.partition.ref,
            content_object_ref=staged.content_object_ref,
            representations=tuple(
                (p.representation_kind.value, p.representation_version, p.store_ref)
                for p in staged.pointers
            ),
            state=stored.state.value,
            head_version=self._metadata.head(staged.memory_item_id),
            audit_ref=staged.audit_ref,
        )

    def _verify_committed(self, stored: StoredVersion) -> GovernedMemoryItem:
        item = stored.staged.verify()
        for pointer in stored.staged.pointers:
            registered = self._metadata.pointer(pointer.store_ref)
            if registered is None or registered != (pointer, VersionState.COMMITTED):
                raise MemoryStoreCorrupted("POINTER_UNBOUND", "committed pointer is not registered")
        return item

    # -- reads ------------------------------------------------------------

    def read_version(
        self, partition: MemoryPartition, memory_item_id: str, memory_version: int
    ) -> MaterializedVersion:
        """Materialise one exact committed version of the authorized partition."""

        stored = self._metadata.get(memory_item_id, memory_version)
        if stored is None or stored.staged.partition.digest != partition.digest:
            raise _not_visible()
        if stored.state is not VersionState.COMMITTED:
            raise _not_ready("VERSION_NOT_COMMITTED", "memory version is partially stored")
        item = self._verify_committed(stored)
        for pointer in stored.staged.pointers:
            if not self._projection_bound(partition, item, pointer):
                raise _not_ready("PROJECTION_DRIFT", "a committed projection does not bind")
        payload = self._read_content(stored.staged, item.content_digest)
        return MaterializedVersion(
            item=item,
            payload=payload,
            pointers=stored.staged.pointers,
            partition_ref=partition.ref,
        )

    def read_latest(self, partition: MemoryPartition, memory_item_id: str) -> MaterializedVersion:
        """Follow the versioned head pointer to the latest committed version."""

        head = self._metadata.head(memory_item_id)
        if head < 1:
            raise _not_visible()
        return self.read_version(partition, memory_item_id, head)

    def lexical_candidates(
        self, partition: MemoryPartition, query: str, *, limit: int
    ) -> tuple[BoundHit, ...]:
        if not isinstance(query, str) or not query.strip():
            raise MemoryStoreError("MEMORY_SCHEMA_INVALID", "QUERY_INVALID", "query is empty")
        version = self._limits.lexical_profile.representation_version
        where = _ELIGIBILITY.get()
        index = self._lexical

        def page(offset: int) -> Sequence[IndexHit]:
            if where is not None:
                return _eligible_index(index).search_eligible(
                    partition, version, query, where=where,
                    limit=self._limits.page_size, offset=offset,
                )
            return index.search(
                partition, version, query, limit=self._limits.page_size, offset=offset
            )

        return self._bound_candidates(
            partition, RepresentationKind.FULL_TEXT, version, page, limit
        )

    def vector_candidates(
        self,
        partition: MemoryPartition,
        profile: VectorProfile,
        vector: Sequence[float],
        *,
        limit: int,
    ) -> tuple[BoundHit, ...]:
        try:
            values = [float(v) for v in vector if not isinstance(v, bool)]
        except (TypeError, ValueError) as exc:
            raise MemoryStoreError(
                "MEMORY_SCHEMA_INVALID", "QUERY_INVALID", "query vector must be numeric"
            ) from exc
        if len(values) != profile.embedding_dimensions or not all(map(math.isfinite, values)):
            raise MemoryStoreError(
                "MEMORY_SCHEMA_INVALID", "QUERY_INVALID", "query vector does not fit the profile"
            )
        version = profile.representation_version
        where = _ELIGIBILITY.get()
        index = self._vector

        def page(offset: int) -> Sequence[IndexHit]:
            if where is not None:
                return _eligible_index(index).search_eligible(
                    partition, version, values, where=where,
                    limit=self._limits.page_size, offset=offset,
                )
            return index.search(
                partition, version, values, limit=self._limits.page_size, offset=offset
            )

        return self._bound_candidates(partition, RepresentationKind.VECTOR, version, page, limit)

    def lexical_scores(
        self, partition: MemoryPartition, query: str, pointers: Sequence[RepresentationPointer]
    ) -> dict[str, float]:
        """The lexical index's own score of ``query`` for committed pointers of the partition."""

        if not isinstance(query, str) or not query.strip():
            raise MemoryStoreError("MEMORY_SCHEMA_INVALID", "QUERY_INVALID", "query is empty")
        version = self._limits.lexical_profile.representation_version
        return self._scores(
            partition, RepresentationKind.FULL_TEXT, version, self._lexical, query, pointers
        )

    def vector_scores(
        self,
        partition: MemoryPartition,
        profile: VectorProfile,
        vector: Sequence[float],
        pointers: Sequence[RepresentationPointer],
    ) -> dict[str, float]:
        """The vector index's own similarity of ``vector`` for committed pointers of the partition."""

        values = [float(v) for v in vector]
        if len(values) != profile.embedding_dimensions or not all(map(math.isfinite, values)):
            raise MemoryStoreError(
                "MEMORY_SCHEMA_INVALID", "QUERY_INVALID", "query vector does not fit the profile"
            )
        return self._scores(
            partition,
            RepresentationKind.VECTOR,
            profile.representation_version,
            self._vector,
            values,
            pointers,
        )

    def _scores(
        self,
        partition: MemoryPartition,
        kind: RepresentationKind,
        representation_version: str,
        index: MemoryLexicalIndexPort | MemoryVectorIndexPort,
        query: str | Sequence[float],
        pointers: Sequence[RepresentationPointer],
    ) -> dict[str, float]:
        refs: list[str] = []
        for pointer in pointers:
            registered = self._metadata.pointer(pointer.store_ref)
            if (
                pointer.partition_digest != partition.digest
                or pointer.representation_kind is not kind
                or pointer.representation_version != representation_version
                or registered is None
                or registered != (pointer, VersionState.COMMITTED)
            ):
                raise _not_ready("POINTER_UNBOUND", "a scored pointer is not committed here")
            refs.append(pointer.store_ref)
        if not refs:
            return {}
        scores = _eligible_index(index).score_entries(
            partition, representation_version, query, sorted(set(refs))
        )
        result: dict[str, float] = {}
        for ref in refs:
            score = scores.get(ref)
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise _not_ready("PROJECTION_DRIFT", "a committed projection has no score")
            if not math.isfinite(score):
                raise _not_ready("PROJECTION_DRIFT", "a committed projection score is invalid")
            result[ref] = float(score)
        return result

    def _bound_candidates(
        self,
        partition: MemoryPartition,
        kind: RepresentationKind,
        representation_version: str,
        page: Callable[[int], Sequence[IndexHit]],
        limit: int,
    ) -> tuple[BoundHit, ...]:
        """Only committed pointers occupy result slots; unbound hits are skipped.

        Pages are read until ``limit`` bound hits are found or the partition
        is exhausted, so unbound entries never displace a bound candidate.  A
        backlog of unbound entries beyond ``max_scanned_hits`` fails closed
        instead of silently returning a shorter result.
        """

        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise MemoryStoreError("MEMORY_SCHEMA_INVALID", "QUERY_INVALID", "limit must be >= 1")
        results: list[BoundHit] = []
        seen: set[str] = set()
        offset = 0
        while len(results) < limit:
            if offset >= self._limits.max_scanned_hits:
                raise _not_ready("UNBOUND_BACKLOG", "index requires reconciliation")
            hits = page(offset)
            for hit in hits:
                if hit.store_ref in seen:
                    continue
                seen.add(hit.store_ref)
                pointer = self._bound_pointer(partition, kind, representation_version, hit)
                if pointer is None:
                    continue
                results.append(
                    BoundHit(
                        memory_version_ref=pointer.memory_version_ref,
                        item_digest=pointer.item_digest,
                        content_digest=pointer.content_digest,
                        store_ref=pointer.store_ref,
                        representation_kind=pointer.representation_kind.value,
                        representation_version=pointer.representation_version,
                        classification_marking_ref=pointer.classification_marking_ref,
                        score=float(hit.score),
                    )
                )
                if len(results) == limit:
                    break
            if len(hits) < self._limits.page_size:
                break
            offset += len(hits)
        return tuple(results)

    def _bound_pointer(
        self,
        partition: MemoryPartition,
        kind: RepresentationKind,
        representation_version: str,
        hit: IndexHit,
    ) -> RepresentationPointer | None:
        try:
            pointer = RepresentationPointer.from_mapping(dict(hit.payload))
        except MemoryStoreError:
            return None
        if (
            pointer.store_ref != hit.store_ref
            or pointer.partition_digest != partition.digest
            or pointer.representation_kind is not kind
            or pointer.representation_version != representation_version
        ):
            return None
        registered = self._metadata.pointer(pointer.store_ref)
        if registered is None or registered != (pointer, VersionState.COMMITTED):
            return None
        return pointer

    def committed_count(self, partition: MemoryPartition) -> int:
        """Count of committed versions in the partition (pending ones never count)."""

        return sum(
            1
            for stored in self._metadata.versions_in(partition.digest)
            if stored.state is VersionState.COMMITTED
        )

    # -- reconciliation ---------------------------------------------------

    def reconcile(self) -> ReconciliationReport:
        """Roll complete pending versions forward and retract every partial or unbound one."""

        completed: list[str] = []
        retracted: list[str] = []
        deferred: list[str] = []
        unbound: list[str] = []
        removed_content: list[str] = []
        cutoff = self._clock.now() - self._limits.reconcile_grace
        for partition in self._metadata.partitions():
            versions = sorted(
                self._metadata.versions_in(partition.digest),
                key=lambda s: (s.staged.memory_item_id, s.staged.memory_version),
            )
            in_flight: set[str] = set()
            for stored in versions:
                if stored.state is VersionState.COMMITTED:
                    continue
                staged = stored.staged
                if parse_utc_timestamp(staged.staged_at) > cutoff:
                    in_flight.add(staged.memory_version_ref)
                    deferred.append(staged.memory_version_ref)
                    continue
                outcome = self._reconcile_pending(partition, staged)
                if outcome is _Outcome.COMPLETED:
                    completed.append(staged.memory_version_ref)
                elif outcome is _Outcome.RETRACTED:
                    retracted.append(staged.memory_version_ref)
                else:
                    # Complete but waiting for its predecessor: keep its projections.
                    deferred.append(staged.memory_version_ref)
                    in_flight.add(staged.memory_version_ref)
            refreshed = self._metadata.versions_in(partition.digest)
            unbound.extend(self._sweep_indexes(partition, refreshed, in_flight))
            removed_content.extend(self._sweep_content(partition, refreshed, in_flight))
        return ReconciliationReport(
            completed=tuple(completed),
            retracted=tuple(retracted),
            deferred=tuple(deferred),
            unbound_removed=tuple(unbound),
            content_removed=tuple(removed_content),
        )

    def _reconcile_pending(self, partition: MemoryPartition, staged: StagedVersion) -> _Outcome:
        item = staged.verify()
        try:
            self._read_content(staged, item.content_digest)
            complete = all(self._projection_bound(partition, item, p) for p in staged.pointers)
        except MemoryStoreError:
            complete = False
        if complete:
            head = self._metadata.head(staged.memory_item_id)
            if staged.memory_version != head + 1:
                return _Outcome.DEFERRED
            self._metadata.commit(
                staged.memory_item_id,
                staged.memory_version,
                stage_digest=staged.stage_digest,
                committed_at=format_utc_timestamp(self._clock.now()),
            )
            self._retire_predecessors(staged)
            return _Outcome.COMPLETED
        # Not protected as in flight: the index and content sweeps that follow
        # remove every projection and content object this version left behind.
        return _Outcome.RETRACTED

    def _sweep_indexes(
        self,
        partition: MemoryPartition,
        versions: Sequence[StoredVersion],
        in_flight: set[str],
    ) -> list[str]:
        committed: dict[str, RepresentationPointer] = {}
        protected: dict[str, RepresentationPointer] = {}
        layouts: set[tuple[RepresentationKind, str]] = {
            (RepresentationKind.FULL_TEXT, self._limits.lexical_profile.representation_version)
        }
        for stored in versions:
            for pointer in stored.staged.pointers:
                if pointer.representation_kind is not RepresentationKind.STRUCTURED:
                    layouts.add((pointer.representation_kind, pointer.representation_version))
                if stored.state is VersionState.COMMITTED:
                    committed[pointer.store_ref] = pointer
                elif stored.staged.memory_version_ref in in_flight:
                    protected[pointer.store_ref] = pointer
        removed: list[str] = []
        for kind, version in sorted(layouts, key=lambda layout: (layout[0].value, layout[1])):
            index = self._index(kind)
            for hit in index.entries(partition, version):
                expected = committed.get(hit.store_ref) or protected.get(hit.store_ref)
                if expected is not None and dict(hit.payload) == expected.to_mapping():
                    continue
                index.remove(partition, version, hit.store_ref)
                removed.append(hit.store_ref)
        return removed

    def _sweep_content(
        self,
        partition: MemoryPartition,
        versions: Sequence[StoredVersion],
        in_flight: set[str],
    ) -> list[str]:
        keep = {
            stored.staged.content_object_ref
            for stored in versions
            if stored.state is VersionState.COMMITTED
            or stored.staged.memory_version_ref in in_flight
        }
        removed: list[str] = []
        for ref in self._content.refs(partition.digest):
            if ref not in keep:
                self._content.delete(ref)
                removed.append(ref)
        return removed


__all__ = [
    "BoundHit",
    "ContentCipher",
    "EligibilityIndexPort",
    "EligibilityMetadataStore",
    "EligibilityPredicate",
    "INDEX_ATTRIBUTES_VERSION",
    "IndexEntry",
    "IndexHit",
    "LexicalProfile",
    "MaterializedVersion",
    "MemoryContentStore",
    "MemoryLexicalIndexPort",
    "MemoryMetadataStore",
    "MemoryPartition",
    "MemoryStoreCoordinator",
    "MemoryStoreCorrupted",
    "MemoryStoreError",
    "MemoryVectorIndexPort",
    "ReconciliationReport",
    "RepresentationPointer",
    "SealedContent",
    "StagedVersion",
    "StoreCommitReceipt",
    "StoreLimits",
    "StoredVersion",
    "VectorProfile",
    "VersionState",
    "content_object_ref",
    "eligibility_scope",
    "index_attributes",
    "lexical_document",
    "lexical_representation_digest",
    "predecessor_not_committed",
    "stage_conflict",
    "stored_vector_digest",
    "structured_representation_version",
    "validate_embedding",
    "vector_digest",
    "vector_representation_digest",
]
