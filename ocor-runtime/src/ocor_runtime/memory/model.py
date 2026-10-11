"""C8 governed memory -- closed GovernedMemoryItem admission and immutable versions.

Implements the ``MemoryAdmissionPort`` slice of the ``GovernedMemoryService``
(ADD v1.3 Part II §§2.2-2.5, 2.12; LLD v1.1 §§2.8.1-2.8.2):

* ``GovernedMemoryItem`` is the closed record of
  ``reports/contracts/governed-memory-item.schema.json``: undeclared fields,
  aliases and type coercion are rejected, and every conditional branch of the
  schema (scope bindings, ``VECTOR`` representation, instruction eligibility,
  legal hold, deletion epoch) is enforced.
* ``CAPABILITY_MATRIX`` declares every one of the 8 x 7 kind/scope
  combinations explicitly; an undeclared or unsupported combination fails with
  ``UNSUPPORTED_CAPABILITY``.
* ``MemoryAdmissionService.admit`` follows the normative admission order: the
  GCS is rebuilt from the authenticated binding and its digest recalculated,
  the closed schema, content class and digests are validated, prohibited
  payloads (hidden reasoning, secrets, credentials, raw tokens, unbounded raw
  conversation) are refused, source/evidence/provenance are resolved under the
  same GCS, the conservative marking and the required taint are computed,
  scope/retention/policy are checked against the trusted boundary clock, and
  only then are metadata, content ref, lifecycle event and audit written as one
  atomic ledger record.
* Versions are immutable: version ``n > 1`` must supersede exactly version
  ``n - 1`` of the same item, may never reuse an occupied version slot with
  different bytes, and inherits (never sheds) the taint of every lineage source.

Every rejection happens before the ledger is called.  Persistence goes through
the ``MemoryVersionLedger`` port; this module ships an in-process reference
ledger and a hash-chained, append-only journal ledger that survives process
restarts (cross-run persistence) without any backend client, so the module
stays backend-free as required by ``OCOR_LANGUAGE_POLICY.md`` row 8.  Policy,
Authority and reference resolution are ports: memory never creates Authority,
Approval, Decision, CapabilityLease or canonical state.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import os
import re
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import BinaryIO, Protocol, TypeVar

from ..c4_marking import MarkingSchemeDefinition
from ..errors import CanonicalizationError, MarkingError, OCORError
from ..kernel.canonical import (
    TimestampError,
    canonical_bytes,
    canonical_digest,
    canonical_set,
    format_utc_timestamp,
    parse_i_json,
    parse_utc_timestamp,
)
from ..kernel.governance import EvidenceRecord, ProvenanceRecord, TrustedClock
from ..kernel.governed_context import (
    GovernedContext,
    GovernedContextCodec,
    GovernedContextError,
    VerifiedGovernedContextBinding,
)

DIGEST = re.compile(r"urn:sha256:[0-9a-f]{64}")
LANGUAGE = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*")
VERSION_REF = re.compile(r"urn:ocor:memory:(?P<item>.+):v(?P<version>[1-9][0-9]*)")
CONTENT_SCHEMA = re.compile(
    r"urn:ocor:memory-content:(?P<content_class>[a-z][a-z0-9-]*):(?P<version>[0-9]+\.[0-9]+)"
)


class MemoryKind(StrEnum):
    WORKING = "WORKING"
    EPISODIC = "EPISODIC"
    SEMANTIC = "SEMANTIC"
    PROCEDURAL = "PROCEDURAL"
    PREFERENCE = "PREFERENCE"
    REFLECTION = "REFLECTION"
    DISSENT = "DISSENT"
    TEAM_SHARED = "TEAM_SHARED"


class MemoryScope(StrEnum):
    RUN = "RUN"
    TASK = "TASK"
    AGENT = "AGENT"
    TEAM = "TEAM"
    PROJECT = "PROJECT"
    DOMAIN = "DOMAIN"
    FEDERATED = "FEDERATED"


class SourceKind(StrEnum):
    OBSERVATION = "OBSERVATION"
    EVIDENCE = "EVIDENCE"
    TOOL_RESULT = "TOOL_RESULT"
    HUMAN_INPUT = "HUMAN_INPUT"
    MODEL_OUTPUT = "MODEL_OUTPUT"
    DERIVED_SUMMARY = "DERIVED_SUMMARY"
    PROCEDURE = "PROCEDURE"
    PREFERENCE = "PREFERENCE"
    MEMORY_CONSOLIDATION = "MEMORY_CONSOLIDATION"


class RepresentationKind(StrEnum):
    STRUCTURED = "STRUCTURED"
    FULL_TEXT = "FULL_TEXT"
    VECTOR = "VECTOR"


class LifecycleStatus(StrEnum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    LEGAL_HOLD = "LEGAL_HOLD"
    DELETION_PENDING = "DELETION_PENDING"
    DELETION_INCOMPLETE = "DELETION_INCOMPLETE"
    DELETED = "DELETED"


PRIOR_LIFECYCLE_STATUSES = frozenset(
    {
        LifecycleStatus.ACTIVE,
        LifecycleStatus.QUARANTINED,
        LifecycleStatus.SUPERSEDED,
        LifecycleStatus.REVOKED,
        LifecycleStatus.EXPIRED,
    }
)
DELETION_STATUSES = frozenset(
    {
        LifecycleStatus.DELETION_PENDING,
        LifecycleStatus.DELETION_INCOMPLETE,
        LifecycleStatus.DELETED,
    }
)
# ADD v1.3 Part II §2.10: an item enters the lifecycle FSM at PROPOSED, or at
# its two admission targets; every later status is a lifecycle transition.
ADMISSION_STATUSES = frozenset(
    {LifecycleStatus.PROPOSED, LifecycleStatus.ACTIVE, LifecycleStatus.QUARANTINED}
)

REQUIRED_FIELDS = (
    "memory_item_id",
    "memory_version",
    "memory_kind",
    "memory_scope",
    "owner_principal_id",
    "tenant_id",
    "organization_id",
    "domain_id",
    "compartments",
    "classification_marking_ref",
    "purpose",
    "content_schema_ref",
    "content_ref",
    "content_digest",
    "source_kind",
    "source_ref",
    "source_digest",
    "evidence_refs",
    "provenance_refs",
    "derived_from_refs",
    "consolidates_refs",
    "created_at",
    "valid_from",
    "retention_policy_ref",
    "confidence",
    "policy_bundle_digest",
    "ontology_release_digest",
    "governed_context_digest",
    "instruction_eligible",
    "taint_labels",
    "representation_kinds",
    "lifecycle_status",
)
OPTIONAL_FIELDS = (
    "agent_run_id",
    "team_run_id",
    "task_id",
    "agent_id",
    "team_id",
    "project_id",
    "federation_policy_ref",
    "language",
    "supersedes_ref",
    "correction_of_ref",
    "valid_until",
    "expires_at",
    "legal_hold_ref",
    "uncertainty_ref",
    "instruction_approval_ref",
    "embedding_model_ref",
    "embedding_model_digest",
    "embedding_dimensions",
    "embedding_normalization_profile",
    "embedding_ref",
    "embedding_digest",
    "prior_lifecycle_status",
    "deletion_epoch",
)
MEMORY_ITEM_FIELDS = frozenset(REQUIRED_FIELDS + OPTIONAL_FIELDS)

# Schema allOf: scope -> mandatory binding fields.
SCOPE_BINDINGS: Mapping[MemoryScope, tuple[str, ...]] = MappingProxyType(
    {
        MemoryScope.RUN: ("agent_run_id",),
        MemoryScope.TASK: ("agent_run_id", "task_id"),
        MemoryScope.AGENT: ("agent_id",),
        MemoryScope.TEAM: ("team_id",),
        MemoryScope.PROJECT: ("project_id",),
        MemoryScope.DOMAIN: (),
        MemoryScope.FEDERATED: ("federation_policy_ref",),
    }
)
VECTOR_FIELDS = (
    "embedding_model_ref",
    "embedding_model_digest",
    "embedding_dimensions",
    "embedding_normalization_profile",
    "embedding_ref",
    "embedding_digest",
)

# The closed reason-code vocabulary of the governed-memory OpenAPI Problem.
PROBLEM_STATUS: Mapping[str, int] = MappingProxyType(
    {
        "AUTHENTICATION_REQUIRED": 401,
        "GOVERNED_CONTEXT_MISMATCH": 422,
        "POLICY_DENIED": 403,
        "AUTHORITY_DENIED": 403,
        "MEMORY_NOT_FOUND": 404,
        "MEMORY_VERSION_NOT_FOUND": 404,
        "MEMORY_SCHEMA_INVALID": 422,
        "MEMORY_IDEMPOTENCY_CONFLICT": 409,
        "MEMORY_TAINTED": 422,
        "REPRESENTATION_NOT_READY": 409,
        "UNSUPPORTED_CAPABILITY": 422,
        "LIFECYCLE_TRANSITION_INVALID": 409,
        "LEGAL_HOLD_ACTIVE": 409,
        "DELETION_INCOMPLETE": 409,
        "STALE_POLICY": 409,
        "STOP_EPOCH_MISMATCH": 409,
        "CONTROL_PLANE_UNAVAILABLE": 503,
        "INTERNAL_ERROR": 500,
    }
)
PROBLEM_REASON_CODES = frozenset(PROBLEM_STATUS)


def _matrix() -> Mapping[tuple[MemoryKind, MemoryScope], bool]:
    """Every kind/scope pair, declared explicitly (ADD v1.3 Part II §2.3).

    Kind defines semantics and scope ownership/visibility; they are
    independent, so the matrix is total.  The only unsupported pairs follow the
    taxonomy's minimum authority treatment (change-control §5): ``WORKING``
    memory is run/task-scoped, and ``TEAM_SHARED`` memory exists only where a
    team membership boundary (team or project) is the owner.
    """

    supported_scopes: Mapping[MemoryKind, frozenset[MemoryScope]] = {
        MemoryKind.WORKING: frozenset({MemoryScope.RUN, MemoryScope.TASK}),
        MemoryKind.TEAM_SHARED: frozenset({MemoryScope.TEAM, MemoryScope.PROJECT}),
    }
    return MappingProxyType(
        {
            (kind, scope): scope in supported_scopes.get(kind, frozenset(MemoryScope))
            for kind in MemoryKind
            for scope in MemoryScope
        }
    )


CAPABILITY_MATRIX = _matrix()

# Closed content-class registry.  Prohibited classes are refused by policy
# regardless of configuration (ADD v1.3 Part II §2.4).
PROHIBITED_CONTENT_CLASSES = frozenset(
    {
        "chain-of-thought",
        "scratchpad",
        "hidden-reasoning",
        "credential",
        "secret",
        "token",
        "raw-conversation",
    }
)
DEFAULT_CONTENT_SCHEMAS = frozenset(
    {
        "urn:ocor:memory-content:text:1.0",
        "urn:ocor:memory-content:structured:1.0",
        "urn:ocor:memory-content:episode:1.0",
        "urn:ocor:memory-content:plan:1.0",
        "urn:ocor:memory-content:summary:1.0",
        "urn:ocor:memory-content:procedure:1.0",
        "urn:ocor:memory-content:preference:1.0",
        "urn:ocor:memory-content:reflection:1.0",
        "urn:ocor:memory-content:dissent:1.0",
    }
)
# Payload markers of prohibited content inside an otherwise allowed class.
PROHIBITED_PAYLOAD_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("PRIVATE_KEY", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("CLOUD_ACCESS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("BEARER_TOKEN", re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+\S+")),
    (
        "JWT",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    ),
    (
        "CREDENTIAL_ASSIGNMENT",
        re.compile(r"(?i)\b(password|passwd|api[_-]?key|client[_-]?secret)\s*[:=]\s*\S+"),
    ),
    (
        "HIDDEN_REASONING",
        re.compile(r"(?i)<\s*/?\s*(thinking|scratchpad|chain[-_ ]of[-_ ]thought)\s*>"),
    ),
)

# Taint (ADD v1.3 Part II §2.12: all untrusted/model-generated content is
# tainted).  Every source kind maps to the label it must carry; REFLECTION is
# model-generated by definition (§2.9).
SOURCE_TAINT: Mapping[SourceKind, str] = MappingProxyType(
    {
        SourceKind.OBSERVATION: "EXTERNAL_DATA",
        SourceKind.EVIDENCE: "EXTERNAL_DATA",
        SourceKind.TOOL_RESULT: "TOOL_OUTPUT",
        SourceKind.HUMAN_INPUT: "HUMAN_SUPPLIED",
        SourceKind.MODEL_OUTPUT: "MODEL_GENERATED",
        SourceKind.DERIVED_SUMMARY: "DERIVED",
        SourceKind.PROCEDURE: "EXTERNAL_DATA",
        SourceKind.PREFERENCE: "HUMAN_SUPPLIED",
        SourceKind.MEMORY_CONSOLIDATION: "DERIVED",
    }
)
KIND_TAINT: Mapping[MemoryKind, frozenset[str]] = MappingProxyType(
    {MemoryKind.REFLECTION: frozenset({"MODEL_GENERATED"})}
)


class MemoryAdmissionError(OCORError):
    """Fail-closed admission refusal carrying a closed Problem reason code.

    ``detail_code`` refines the reason without widening the public enum; the
    message names fields only and never echoes payload content.
    """

    def __init__(
        self,
        reason_code: str,
        detail_code: str,
        message: str,
        *,
        correlation_id: str | None = None,
    ) -> None:
        if reason_code not in PROBLEM_REASON_CODES:
            raise ValueError(f"undeclared memory reason code: {reason_code}")
        self.reason_code = reason_code
        self.detail_code = detail_code
        self.correlation_id = correlation_id
        super().__init__(f"{reason_code}/{detail_code}: {message}")

    def to_problem(self) -> dict[str, object]:
        return {
            "type": f"urn:ocor:problem:memory:{self.reason_code.lower()}",
            "title": self.detail_code,
            "status": PROBLEM_STATUS[self.reason_code],
            "reason_code": self.reason_code,
            "correlation_id": self.correlation_id or "uncorrelated",
        }


def _schema_error(detail: str, message: str) -> MemoryAdmissionError:
    return MemoryAdmissionError("MEMORY_SCHEMA_INVALID", detail, message)


def memory_version_ref(memory_item_id: str, memory_version: int) -> str:
    """Return the stable, backend-free reference of one immutable version."""

    return f"urn:ocor:memory:{memory_item_id}:v{memory_version}"


def parse_memory_version_ref(ref: str) -> tuple[str, int]:
    match = VERSION_REF.fullmatch(ref) if isinstance(ref, str) else None
    if match is None:
        raise _schema_error("VERSION_REF_INVALID", "lineage reference is not a memory version ref")
    return match.group("item"), int(match.group("version"))


def require_supported(kind: MemoryKind, scope: MemoryScope) -> None:
    if not CAPABILITY_MATRIX.get((kind, scope), False):
        raise MemoryAdmissionError(
            "UNSUPPORTED_CAPABILITY",
            "KIND_SCOPE_UNSUPPORTED",
            f"{kind.value}/{scope.value} is not a supported memory capability",
        )


def _string(name: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise _schema_error("FIELD_INVALID", f"{name} must be a non-empty string")
    return value


def _digest(name: str, value: object) -> str:
    result = _string(name, value)
    if DIGEST.fullmatch(result) is None:
        raise _schema_error("FIELD_INVALID", f"{name} must be a canonical SHA-256 URN")
    return result


def _timestamp(name: str, value: object) -> datetime:
    try:
        return parse_utc_timestamp(_string(name, value))
    except TimestampError as exc:
        raise _schema_error("FIELD_INVALID", f"{name} must be a canonical UTC timestamp") from exc


def _integer(name: str, value: object, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise _schema_error("FIELD_INVALID", f"{name} must be an integer >= {minimum}")
    return value


E = TypeVar("E", bound=StrEnum)


def _enum(name: str, value: object, enum: type[E]) -> E:
    if not isinstance(value, str):
        raise _schema_error("FIELD_INVALID", f"{name} must be a declared enum value")
    try:
        return enum(value)
    except ValueError as exc:
        raise _schema_error("FIELD_INVALID", f"{name} must be a declared enum value") from exc


def _string_set(name: str, value: object, *, non_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise _schema_error("FIELD_INVALID", f"{name} must be an array")
    items = tuple(_string(name, item) for item in value)
    if non_empty and not items:
        raise _schema_error("FIELD_INVALID", f"{name} must not be empty")
    if len(set(items)) != len(items):
        raise _schema_error("FIELD_INVALID", f"{name} must not contain duplicates")
    try:
        return canonical_set(items)
    except CanonicalizationError as exc:  # defensive: duplicates are checked above
        raise _schema_error("FIELD_INVALID", f"{name}: {exc}") from exc


@dataclass(frozen=True, slots=True)
class GovernedMemoryItem:
    """The exact closed ``GovernedMemoryItem`` Full PoC profile record."""

    memory_item_id: str
    memory_version: int
    memory_kind: MemoryKind
    memory_scope: MemoryScope
    owner_principal_id: str
    tenant_id: str
    organization_id: str
    domain_id: str
    compartments: tuple[str, ...]
    classification_marking_ref: str
    purpose: str
    content_schema_ref: str
    content_ref: str
    content_digest: str
    source_kind: SourceKind
    source_ref: str
    source_digest: str
    evidence_refs: tuple[str, ...]
    provenance_refs: tuple[str, ...]
    derived_from_refs: tuple[str, ...]
    consolidates_refs: tuple[str, ...]
    created_at: datetime
    valid_from: datetime
    retention_policy_ref: str
    confidence: float
    policy_bundle_digest: str
    ontology_release_digest: str
    governed_context_digest: str
    instruction_eligible: bool
    taint_labels: tuple[str, ...]
    representation_kinds: tuple[RepresentationKind, ...]
    lifecycle_status: LifecycleStatus
    agent_run_id: str | None = None
    team_run_id: str | None = None
    task_id: str | None = None
    agent_id: str | None = None
    team_id: str | None = None
    project_id: str | None = None
    federation_policy_ref: str | None = None
    language: str | None = None
    supersedes_ref: str | None = None
    correction_of_ref: str | None = None
    valid_until: datetime | None = None
    expires_at: datetime | None = None
    legal_hold_ref: str | None = None
    uncertainty_ref: str | None = None
    instruction_approval_ref: str | None = None
    embedding_model_ref: str | None = None
    embedding_model_digest: str | None = None
    embedding_dimensions: int | None = None
    embedding_normalization_profile: str | None = None
    embedding_ref: str | None = None
    embedding_digest: str | None = None
    prior_lifecycle_status: LifecycleStatus | None = None
    deletion_epoch: int | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> GovernedMemoryItem:
        """Validate the closed JSON record without coercion or aliases."""

        if not isinstance(value, Mapping):
            raise _schema_error("NOT_AN_OBJECT", "GovernedMemoryItem must be an object")
        present = frozenset(value)
        additional = sorted(str(name) for name in present - MEMORY_ITEM_FIELDS)
        if additional:
            raise _schema_error(
                "ADDITIONAL_PROPERTY", f"undeclared fields: {', '.join(additional)}"
            )
        missing = sorted(set(REQUIRED_FIELDS) - present)
        if missing:
            raise _schema_error("REQUIRED_FIELD_MISSING", f"missing fields: {', '.join(missing)}")

        confidence = value["confidence"]
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
        ):
            raise _schema_error("FIELD_INVALID", "confidence must be a number in [0, 1]")
        instruction_eligible = value["instruction_eligible"]
        if not isinstance(instruction_eligible, bool):
            raise _schema_error("FIELD_INVALID", "instruction_eligible must be a boolean")
        representations = _string_set(
            "representation_kinds", value["representation_kinds"], non_empty=True
        )

        def optional(name: str, parse: Callable[[str, object], object]) -> object:
            return parse(name, value[name]) if name in value else None

        def plain(name: str, raw: object) -> object:
            return _string(name, raw)

        language = optional("language", plain)
        if language is not None and LANGUAGE.fullmatch(str(language)) is None:
            raise _schema_error("FIELD_INVALID", "language must be a BCP 47 tag")

        item = cls(
            memory_item_id=_string("memory_item_id", value["memory_item_id"]),
            memory_version=_integer("memory_version", value["memory_version"], 1),
            memory_kind=_enum("memory_kind", value["memory_kind"], MemoryKind),
            memory_scope=_enum("memory_scope", value["memory_scope"], MemoryScope),
            owner_principal_id=_string("owner_principal_id", value["owner_principal_id"]),
            tenant_id=_string("tenant_id", value["tenant_id"]),
            organization_id=_string("organization_id", value["organization_id"]),
            domain_id=_string("domain_id", value["domain_id"]),
            compartments=_string_set("compartments", value["compartments"], non_empty=True),
            classification_marking_ref=_digest(
                "classification_marking_ref", value["classification_marking_ref"]
            ),
            purpose=_string("purpose", value["purpose"]),
            content_schema_ref=_string("content_schema_ref", value["content_schema_ref"]),
            content_ref=_string("content_ref", value["content_ref"]),
            content_digest=_digest("content_digest", value["content_digest"]),
            source_kind=_enum("source_kind", value["source_kind"], SourceKind),
            source_ref=_string("source_ref", value["source_ref"]),
            source_digest=_digest("source_digest", value["source_digest"]),
            evidence_refs=_string_set("evidence_refs", value["evidence_refs"], non_empty=True),
            provenance_refs=_string_set(
                "provenance_refs", value["provenance_refs"], non_empty=True
            ),
            derived_from_refs=_string_set(
                "derived_from_refs", value["derived_from_refs"], non_empty=False
            ),
            consolidates_refs=_string_set(
                "consolidates_refs", value["consolidates_refs"], non_empty=False
            ),
            created_at=_timestamp("created_at", value["created_at"]),
            valid_from=_timestamp("valid_from", value["valid_from"]),
            retention_policy_ref=_string("retention_policy_ref", value["retention_policy_ref"]),
            confidence=confidence,
            policy_bundle_digest=_digest("policy_bundle_digest", value["policy_bundle_digest"]),
            ontology_release_digest=_digest(
                "ontology_release_digest", value["ontology_release_digest"]
            ),
            governed_context_digest=_digest(
                "governed_context_digest", value["governed_context_digest"]
            ),
            instruction_eligible=instruction_eligible,
            taint_labels=_string_set("taint_labels", value["taint_labels"], non_empty=True),
            representation_kinds=tuple(
                _enum("representation_kinds", kind, RepresentationKind)
                for kind in representations
            ),
            lifecycle_status=_enum("lifecycle_status", value["lifecycle_status"], LifecycleStatus),
            agent_run_id=optional("agent_run_id", plain),  # type: ignore[arg-type]
            team_run_id=optional("team_run_id", plain),  # type: ignore[arg-type]
            task_id=optional("task_id", plain),  # type: ignore[arg-type]
            agent_id=optional("agent_id", plain),  # type: ignore[arg-type]
            team_id=optional("team_id", plain),  # type: ignore[arg-type]
            project_id=optional("project_id", plain),  # type: ignore[arg-type]
            federation_policy_ref=optional("federation_policy_ref", plain),  # type: ignore[arg-type]
            language=language,  # type: ignore[arg-type]
            supersedes_ref=optional("supersedes_ref", plain),  # type: ignore[arg-type]
            correction_of_ref=optional("correction_of_ref", plain),  # type: ignore[arg-type]
            valid_until=optional("valid_until", _timestamp),  # type: ignore[arg-type]
            expires_at=optional("expires_at", _timestamp),  # type: ignore[arg-type]
            legal_hold_ref=optional("legal_hold_ref", plain),  # type: ignore[arg-type]
            uncertainty_ref=optional("uncertainty_ref", plain),  # type: ignore[arg-type]
            instruction_approval_ref=optional("instruction_approval_ref", plain),  # type: ignore[arg-type]
            embedding_model_ref=optional("embedding_model_ref", plain),  # type: ignore[arg-type]
            embedding_model_digest=optional("embedding_model_digest", _digest),  # type: ignore[arg-type]
            embedding_dimensions=optional(  # type: ignore[arg-type]
                "embedding_dimensions", lambda name, raw: _integer(name, raw, 1)
            ),
            embedding_normalization_profile=optional(  # type: ignore[arg-type]
                "embedding_normalization_profile", plain
            ),
            embedding_ref=optional("embedding_ref", plain),  # type: ignore[arg-type]
            embedding_digest=optional("embedding_digest", _digest),  # type: ignore[arg-type]
            prior_lifecycle_status=optional(  # type: ignore[arg-type]
                "prior_lifecycle_status",
                lambda name, raw: _enum(name, raw, LifecycleStatus),
            ),
            deletion_epoch=optional(  # type: ignore[arg-type]
                "deletion_epoch", lambda name, raw: _integer(name, raw, 0)
            ),
        )
        item._validate_conditionals()
        return item

    def _validate_conditionals(self) -> None:
        """The schema ``allOf`` branches, enforced exactly."""

        for name in SCOPE_BINDINGS[self.memory_scope]:
            if getattr(self, name) is None:
                raise _schema_error(
                    "SCOPE_BINDING_MISSING",
                    f"{self.memory_scope.value} scope requires {name}",
                )
        if RepresentationKind.VECTOR in self.representation_kinds:
            missing = [name for name in VECTOR_FIELDS if getattr(self, name) is None]
            if missing:
                raise _schema_error(
                    "EMBEDDING_BINDING_MISSING",
                    f"VECTOR representation requires {', '.join(missing)}",
                )
        if self.instruction_eligible and self.instruction_approval_ref is None:
            raise _schema_error(
                "INSTRUCTION_APPROVAL_MISSING",
                "instruction_eligible requires instruction_approval_ref",
            )
        if self.lifecycle_status is LifecycleStatus.LEGAL_HOLD and (
            self.legal_hold_ref is None or self.prior_lifecycle_status is None
        ):
            raise _schema_error(
                "LEGAL_HOLD_BINDING_MISSING",
                "LEGAL_HOLD requires legal_hold_ref and prior_lifecycle_status",
            )
        if (
            self.prior_lifecycle_status is not None
            and self.prior_lifecycle_status not in PRIOR_LIFECYCLE_STATUSES
        ):
            raise _schema_error("FIELD_INVALID", "prior_lifecycle_status is not declared")
        if self.lifecycle_status in DELETION_STATUSES and self.deletion_epoch is None:
            raise _schema_error(
                "DELETION_EPOCH_MISSING", "deletion statuses require deletion_epoch"
            )

    def to_mapping(self) -> dict[str, object]:
        """Return exactly the present boundary fields with JSON types."""

        result: dict[str, object] = {}
        for name in REQUIRED_FIELDS + OPTIONAL_FIELDS:
            raw = getattr(self, name)
            if raw is None:
                continue
            if isinstance(raw, datetime):
                result[name] = format_utc_timestamp(raw)
            elif isinstance(raw, StrEnum):
                result[name] = raw.value
            elif isinstance(raw, tuple):
                result[name] = [
                    element.value if isinstance(element, StrEnum) else element
                    for element in raw
                ]
            else:
                result[name] = raw
        return result

    def digest(self) -> str:
        return canonical_digest(self.to_mapping())

    @property
    def version_ref(self) -> str:
        return memory_version_ref(self.memory_item_id, self.memory_version)

    def lineage_refs(self) -> tuple[str, ...]:
        refs: list[str] = []
        for ref in (self.supersedes_ref, self.correction_of_ref):
            if ref is not None:
                refs.append(ref)
        refs.extend(self.derived_from_refs)
        refs.extend(self.consolidates_refs)
        return tuple(dict.fromkeys(refs))


@dataclass(frozen=True, slots=True)
class MemoryReceipt:
    """Opaque admission receipt (OpenAPI ``MemoryReceipt``)."""

    memory_item_id: str
    memory_version: int
    content_digest: str
    lifecycle_status: str
    governed_context_digest: str
    audit_ref: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "memory_item_id": self.memory_item_id,
            "memory_version": self.memory_version,
            "content_digest": self.content_digest,
            "lifecycle_status": self.lifecycle_status,
            "governed_context_digest": self.governed_context_digest,
            "audit_ref": self.audit_ref,
        }


IdempotencyKey = tuple[str, str, str, str, str]


def idempotency_key(item: GovernedMemoryItem, operation_id: str) -> IdempotencyKey:
    """LLD v1.1 §2.8.2: ``(tenant_id, memory_scope, source_digest, content_digest, operation_id)``."""

    return (
        item.tenant_id,
        item.memory_scope.value,
        item.source_digest,
        item.content_digest,
        operation_id,
    )


@dataclass(frozen=True, slots=True)
class AdmittedMemoryVersion:
    """One atomic ledger record: metadata, content ref, lifecycle event, audit."""

    item: GovernedMemoryItem
    item_digest: str
    idempotency_key: IdempotencyKey
    lifecycle_event: Mapping[str, object]
    audit_event: Mapping[str, object]
    receipt: MemoryReceipt

    def to_mapping(self) -> dict[str, object]:
        return {
            "item": self.item.to_mapping(),
            "item_digest": self.item_digest,
            "idempotency_key": list(self.idempotency_key),
            "lifecycle_event": dict(self.lifecycle_event),
            "audit_event": dict(self.audit_event),
            "receipt": self.receipt.to_mapping(),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> AdmittedMemoryVersion:
        """Rebuild a persisted record, re-verifying every bound digest."""

        expected = {
            "item",
            "item_digest",
            "idempotency_key",
            "lifecycle_event",
            "audit_event",
            "receipt",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise MemoryLedgerCorrupted("record is not a closed admitted-version record")
        raw_item = value["item"]
        lifecycle_event = value["lifecycle_event"]
        audit_event = value["audit_event"]
        raw_receipt = value["receipt"]
        key = value["idempotency_key"]
        if not (
            isinstance(raw_item, Mapping)
            and isinstance(lifecycle_event, Mapping)
            and isinstance(audit_event, Mapping)
            and isinstance(raw_receipt, Mapping)
            and isinstance(key, list)
            and len(key) == 5
            and all(isinstance(part, str) for part in key)
        ):
            raise MemoryLedgerCorrupted("record members have invalid types")
        try:
            item = GovernedMemoryItem.from_mapping(raw_item)
            receipt = MemoryReceipt(
                memory_item_id=str(raw_receipt["memory_item_id"]),
                memory_version=int(str(raw_receipt["memory_version"])),
                content_digest=str(raw_receipt["content_digest"]),
                lifecycle_status=str(raw_receipt["lifecycle_status"]),
                governed_context_digest=str(raw_receipt["governed_context_digest"]),
                audit_ref=str(raw_receipt["audit_ref"]),
            )
        except (MemoryAdmissionError, KeyError, ValueError) as exc:
            raise MemoryLedgerCorrupted(f"record does not re-validate: {exc}") from exc
        record = cls(
            item=item,
            item_digest=str(value["item_digest"]),
            idempotency_key=(key[0], key[1], key[2], key[3], key[4]),
            lifecycle_event=MappingProxyType(dict(lifecycle_event)),
            audit_event=MappingProxyType(dict(audit_event)),
            receipt=receipt,
        )
        record.verify()
        return record

    def verify(self) -> None:
        if not hmac.compare_digest(self.item.digest(), self.item_digest):
            raise MemoryLedgerCorrupted("item digest does not bind the persisted item")
        if not hmac.compare_digest(canonical_digest(dict(self.audit_event)), self.receipt.audit_ref):
            raise MemoryLedgerCorrupted("audit_ref does not bind the audit event")
        if self.audit_event.get("item_digest") != self.item_digest:
            raise MemoryLedgerCorrupted("audit event does not bind the item digest")
        if (
            self.receipt.memory_item_id != self.item.memory_item_id
            or self.receipt.memory_version != self.item.memory_version
            or self.receipt.content_digest != self.item.content_digest
            or self.receipt.lifecycle_status != self.item.lifecycle_status.value
            or self.receipt.governed_context_digest != self.item.governed_context_digest
        ):
            raise MemoryLedgerCorrupted("receipt does not bind the persisted item")


class MemoryLedgerCorrupted(MemoryAdmissionError):
    """Persisted memory metadata failed integrity verification (fail closed)."""

    def __init__(self, message: str) -> None:
        super().__init__("INTERNAL_ERROR", "MEMORY_LEDGER_CORRUPTED", message)


class MemoryVersionLedger(Protocol):
    """Append-only memory metadata authority port (never canonical state)."""

    def get(self, memory_item_id: str, memory_version: int) -> AdmittedMemoryVersion | None:
        """Return one exact immutable version."""

    def latest_version(self, memory_item_id: str) -> int:
        """Return the highest admitted version, or 0 when the item is unknown."""

    def by_idempotency_key(self, key: IdempotencyKey) -> AdmittedMemoryVersion | None:
        """Return the record admitted under an idempotency key."""

    def append(self, record: AdmittedMemoryVersion) -> None:
        """Atomically append, refusing any occupied slot, gap or reused key."""


def _occupancy_conflict(
    record: AdmittedMemoryVersion,
    latest: int,
    occupied: bool,
    key_taken: bool,
) -> MemoryAdmissionError | None:
    item = record.item
    if occupied or item.memory_version <= latest:
        return MemoryAdmissionError(
            "MEMORY_IDEMPOTENCY_CONFLICT",
            "IMMUTABLE_VERSION_OCCUPIED",
            f"{item.version_ref} is already admitted; versions are never overwritten",
        )
    if item.memory_version != latest + 1:
        return MemoryAdmissionError(
            "MEMORY_VERSION_NOT_FOUND",
            "VERSION_GAP",
            f"{item.version_ref} does not follow the latest admitted version {latest}",
        )
    if key_taken:
        return MemoryAdmissionError(
            "MEMORY_IDEMPOTENCY_CONFLICT",
            "IDEMPOTENCY_KEY_REUSED",
            "idempotency key is already bound to another admission",
        )
    return None


class InMemoryMemoryVersionLedger:
    """Thread-safe in-process reference ledger with append-only semantics."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._versions: dict[tuple[str, int], AdmittedMemoryVersion] = {}
        self._latest: dict[str, int] = {}
        self._keys: dict[IdempotencyKey, tuple[str, int]] = {}
        self._order: list[tuple[str, int]] = []

    def get(self, memory_item_id: str, memory_version: int) -> AdmittedMemoryVersion | None:
        with self._lock:
            return self._versions.get((memory_item_id, memory_version))

    def latest_version(self, memory_item_id: str) -> int:
        with self._lock:
            return self._latest.get(memory_item_id, 0)

    def by_idempotency_key(self, key: IdempotencyKey) -> AdmittedMemoryVersion | None:
        with self._lock:
            slot = self._keys.get(key)
            return None if slot is None else self._versions[slot]

    def append(self, record: AdmittedMemoryVersion) -> None:
        record.verify()
        slot = (record.item.memory_item_id, record.item.memory_version)
        with self._lock:
            conflict = _occupancy_conflict(
                record,
                self._latest.get(slot[0], 0),
                slot in self._versions,
                record.idempotency_key in self._keys,
            )
            if conflict is not None:
                raise conflict
            self._versions[slot] = record
            self._latest[slot[0]] = slot[1]
            self._keys[record.idempotency_key] = slot
            self._order.append(slot)

    def records(self) -> tuple[AdmittedMemoryVersion, ...]:
        with self._lock:
            return tuple(self._versions[slot] for slot in self._order)


GENESIS = "urn:sha256:" + "0" * 64


class JournalMemoryVersionLedger:
    """Durable, hash-chained, append-only JSON-lines memory version journal.

    Each line is ``{"seq", "prev", "record", "entry_digest"}`` in canonical
    bytes; ``entry_digest`` binds the previous entry, so any rewrite, removal,
    reordering or torn write of an acknowledged entry is detected when the
    journal is (re)opened and the ledger refuses to serve (fail closed).
    Appends take an exclusive ``flock`` and catch up with entries written by
    other processes before checking the slot, so concurrent runs cannot
    overwrite a version.  ``fsync`` precedes the acknowledgement.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._memory = InMemoryMemoryVersionLedger()
        self._offset = 0
        self._seq = 0
        self._head = GENESIS
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)
        with self._lock, self._path.open("rb") as handle:
            fcntl.flock(handle, fcntl.LOCK_SH)
            try:
                self._catch_up(handle)
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    @property
    def head(self) -> str:
        with self._lock:
            return self._head

    def _catch_up(self, handle: BinaryIO) -> None:
        handle.seek(self._offset)
        data = handle.read()
        if not data:
            return
        if not data.endswith(b"\n"):
            raise MemoryLedgerCorrupted("journal ends with a torn, unacknowledged write")
        for line in data.splitlines():
            self._apply(line)
            self._offset += len(line) + 1

    def _apply(self, line: bytes) -> None:
        try:
            entry = parse_i_json(line)
        except (CanonicalizationError, UnicodeError, ValueError) as exc:
            raise MemoryLedgerCorrupted(f"journal entry is not I-JSON: {exc}") from exc
        if not isinstance(entry, Mapping) or set(entry) != {
            "seq",
            "prev",
            "record",
            "entry_digest",
        }:
            raise MemoryLedgerCorrupted("journal entry is not a closed chain entry")
        if canonical_bytes(entry) != line:
            raise MemoryLedgerCorrupted("journal entry is not in canonical form")
        body = {"seq": entry["seq"], "prev": entry["prev"], "record": entry["record"]}
        if entry["seq"] != self._seq + 1 or entry["prev"] != self._head:
            raise MemoryLedgerCorrupted("journal chain is broken or reordered")
        if not hmac.compare_digest(canonical_digest(body), str(entry["entry_digest"])):
            raise MemoryLedgerCorrupted("journal entry digest mismatch")
        raw_record = entry["record"]
        if not isinstance(raw_record, Mapping):
            raise MemoryLedgerCorrupted("journal record is not an object")
        record = AdmittedMemoryVersion.from_mapping(raw_record)
        try:
            self._memory.append(record)
        except MemoryAdmissionError as exc:
            raise MemoryLedgerCorrupted(f"journal violates immutability: {exc}") from exc
        self._seq += 1
        self._head = str(entry["entry_digest"])

    def get(self, memory_item_id: str, memory_version: int) -> AdmittedMemoryVersion | None:
        with self._lock:
            return self._memory.get(memory_item_id, memory_version)

    def latest_version(self, memory_item_id: str) -> int:
        with self._lock:
            return self._memory.latest_version(memory_item_id)

    def by_idempotency_key(self, key: IdempotencyKey) -> AdmittedMemoryVersion | None:
        with self._lock:
            return self._memory.by_idempotency_key(key)

    def append(self, record: AdmittedMemoryVersion) -> None:
        record.verify()
        with self._lock, self._path.open("r+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                self._catch_up(handle)
                slot = (record.item.memory_item_id, record.item.memory_version)
                conflict = _occupancy_conflict(
                    record,
                    self._memory.latest_version(slot[0]),
                    self._memory.get(*slot) is not None,
                    self._memory.by_idempotency_key(record.idempotency_key) is not None,
                )
                if conflict is not None:
                    raise conflict
                body = {"seq": self._seq + 1, "prev": self._head, "record": record.to_mapping()}
                entry = dict(body, entry_digest=canonical_digest(body))
                line = canonical_bytes(entry) + b"\n"
                handle.seek(0, os.SEEK_END)
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
                self._apply(line[:-1])
                self._offset += len(line)
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


@dataclass(frozen=True, slots=True)
class InstructionApproval:
    """A separate approval making one exact procedural version instruction-eligible."""

    approval_ref: str
    memory_item_id: str
    approved_content_digest: str
    approver_principal_id: str
    tenant_id: str
    valid_until: datetime


@dataclass(frozen=True, slots=True)
class FederationPolicy:
    """An approved federation policy authorizing a tenant to own FEDERATED memory."""

    policy_ref: str
    tenant_ids: frozenset[str]
    purposes: frozenset[str]
    valid_until: datetime


class MemoryReferenceResolver(Protocol):
    """Resolve source, evidence, provenance and approvals under one GCS."""

    def source_digest(self, source_ref: str, context: GovernedContext) -> str | None:
        """Return the digest of a source authorized for this context."""

    def evidence(self, evidence_ref: str, context: GovernedContext) -> EvidenceRecord | None:
        """Return the evidence record authorized for this context."""

    def provenance(
        self, provenance_ref: str, context: GovernedContext
    ) -> ProvenanceRecord | None:
        """Return the provenance record authorized for this context."""

    def instruction_approval(
        self, approval_ref: str, context: GovernedContext
    ) -> InstructionApproval | None:
        """Return the instruction-eligibility approval record."""

    def federation_policy(
        self, policy_ref: str, context: GovernedContext
    ) -> FederationPolicy | None:
        """Return the approved federation policy."""


@dataclass(frozen=True, slots=True)
class MemoryPolicyDecision:
    permitted: bool
    decision_ref: str
    policy_bundle_digest: str
    reason: str = ""


class MemoryAdmissionPolicy(Protocol):
    """Policy/Authority port evaluated without treating content as instruction."""

    def authorize_admission(
        self, item: GovernedMemoryItem, context: GovernedContext
    ) -> MemoryPolicyDecision:
        """Return the live policy decision for this admission."""


class MarkingDominance(Protocol):
    def dominates(self, upper_ref: str, lower_ref: str) -> bool:
        """Return whether ``upper_ref`` is at least as restrictive as ``lower_ref``."""

    def join(self, refs: Iterable[str]) -> str:
        """Return the conservative join of marking refs."""


class LatticeMarkingResolver:
    """Marking dominance over a finite C4 lattice keyed by marking digests."""

    def __init__(self, scheme: MarkingSchemeDefinition, labels: Mapping[str, str]) -> None:
        self._scheme = scheme
        self._labels = MappingProxyType(dict(labels))
        self._refs = MappingProxyType({label: ref for ref, label in labels.items()})
        for ref, label in labels.items():
            _digest("classification_marking_ref", ref)
            scheme.leq(label, label)
        if len(self._refs) != len(self._labels):
            raise MarkingError("marking refs must map to distinct labels")

    def _label(self, ref: str) -> str:
        label = self._labels.get(ref)
        if label is None:
            raise MemoryAdmissionError(
                "POLICY_DENIED", "MARKING_UNKNOWN", "marking ref is not in the lattice"
            )
        return label

    def dominates(self, upper_ref: str, lower_ref: str) -> bool:
        return self._scheme.dominates(self._label(upper_ref), self._label(lower_ref))

    def join(self, refs: Iterable[str]) -> str:
        labels = [self._label(ref) for ref in refs]
        joined = self._scheme.join(*labels)
        ref = self._refs.get(joined)
        if ref is None:
            raise MemoryAdmissionError(
                "POLICY_DENIED", "MARKING_UNKNOWN", "marking join has no declared ref"
            )
        return ref


@dataclass(frozen=True, slots=True)
class AdmissionLimits:
    """Boundary configuration: retention horizons and admission clock skew."""

    retention_horizons: Mapping[str, timedelta]
    max_clock_skew: timedelta = timedelta(seconds=30)
    content_schemas: frozenset[str] = field(default=DEFAULT_CONTENT_SCHEMAS)


ENVELOPE_FIELDS = frozenset(
    {"operation_id", "governed_context", "governed_context_digest", "deadline", "candidate"}
)


def _envelope_string(name: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise _schema_error("ENVELOPE_INVALID", f"{name} must be a non-empty string")
    return value


class MemoryAdmissionService:
    """``MemoryAdmissionPort.admitMemory``: fail-closed, persistence-last admission."""

    def __init__(
        self,
        *,
        ledger: MemoryVersionLedger,
        resolver: MemoryReferenceResolver,
        policy: MemoryAdmissionPolicy,
        markings: MarkingDominance,
        clock: TrustedClock,
        limits: AdmissionLimits,
    ) -> None:
        self._ledger = ledger
        self._resolver = resolver
        self._policy = policy
        self._markings = markings
        self._clock = clock
        self._limits = limits

    def admit(
        self,
        request: Mapping[str, object],
        *,
        binding: VerifiedGovernedContextBinding | None,
        payload: bytes,
    ) -> MemoryReceipt:
        """Admit one candidate version, or raise before anything is persisted."""

        if not isinstance(binding, VerifiedGovernedContextBinding):
            raise MemoryAdmissionError(
                "AUTHENTICATION_REQUIRED",
                "BINDING_MISSING",
                "admission requires an authenticated governed-context binding",
            )
        correlation_id = binding.expected.correlation_id
        try:
            return self._admit(request, binding, payload)
        except MemoryAdmissionError as exc:
            if exc.correlation_id is None:
                exc.correlation_id = correlation_id
            raise

    def _admit(
        self,
        request: Mapping[str, object],
        binding: VerifiedGovernedContextBinding,
        payload: bytes,
    ) -> MemoryReceipt:
        now = self._clock.now()
        # 1. Closed envelope and the exact eleven-field GCS from the binding.
        if not isinstance(request, Mapping) or set(request) != ENVELOPE_FIELDS:
            raise _schema_error(
                "ENVELOPE_INVALID", "admission request is not the closed admission envelope"
            )
        operation_id = _envelope_string("operation_id", request["operation_id"])
        claimed_gcs_digest = _envelope_string(
            "governed_context_digest", request["governed_context_digest"]
        )
        try:
            deadline = parse_utc_timestamp(
                _envelope_string("deadline", request["deadline"])
            )
        except TimestampError as exc:
            raise _schema_error("ENVELOPE_INVALID", "deadline must be a UTC timestamp") from exc
        if deadline <= now:
            raise MemoryAdmissionError(
                "POLICY_DENIED", "DEADLINE_EXCEEDED", "admission deadline has passed"
            )
        raw_context = request["governed_context"]
        if not isinstance(raw_context, Mapping):
            raise MemoryAdmissionError(
                "GOVERNED_CONTEXT_MISMATCH", "GCS_INVALID", "governed_context must be an object"
            )
        try:
            context = GovernedContextCodec.from_openapi(raw_context, binding, claimed_gcs_digest)
        except GovernedContextError as exc:
            raise MemoryAdmissionError(
                "GOVERNED_CONTEXT_MISMATCH", exc.code, str(exc)
            ) from exc
        gcs_digest = context.digest()

        # 2. Closed schema, capability matrix and binding to the same GCS.
        raw_candidate = request["candidate"]
        if not isinstance(raw_candidate, Mapping):
            raise _schema_error("NOT_AN_OBJECT", "candidate must be an object")
        item = GovernedMemoryItem.from_mapping(raw_candidate)
        require_supported(item.memory_kind, item.memory_scope)
        self._bind_to_context(item, context, gcs_digest)

        # 3. Idempotency: same key and digest returns the original receipt.
        key = idempotency_key(item, operation_id)
        item_digest = item.digest()
        previous = self._ledger.by_idempotency_key(key)
        if previous is not None:
            if hmac.compare_digest(previous.item_digest, item_digest):
                # The item digest authenticates metadata, not the supplied bytes.
                # Replays must satisfy the same content boundary before receiving
                # an existing receipt (ADD Part II §2.4; LLD §2.8.2).
                self._validate_content(item, payload)
                return previous.receipt
            raise MemoryAdmissionError(
                "MEMORY_IDEMPOTENCY_CONFLICT",
                "IDEMPOTENCY_DIGEST_MISMATCH",
                "idempotency key was admitted with a different candidate digest",
            )

        # 4. Content class, payload digest and prohibited payloads.
        self._validate_content(item, payload)
        # 5. Temporal, retention and lifecycle admission rules (boundary clock).
        self._validate_temporal(item, now)
        self._validate_kind_rules(item)
        # 6. Immutable version slot and lineage.
        sources = self._validate_lineage(item, context)
        # 7. Source, evidence and provenance under the same GCS.
        evidence = self._resolve_references(item, context, now)
        # 8. Conservative marking and taint.
        self._validate_marking(item, context, evidence, sources)
        self._validate_taint(item, sources)
        # 9. Scope ownership and instruction eligibility.
        self._validate_scope_authority(item, context, now)
        self._validate_instruction_eligibility(item, context, now)
        # 10. Live policy and Authority (content is never treated as instruction).
        decision = self._evaluate_policy(item, context)

        lifecycle_event: dict[str, object] = {
            "event_type": "MEMORY_ADMITTED",
            "memory_version_ref": item.version_ref,
            "from_status": None,
            "to_status": item.lifecycle_status.value,
            "at": format_utc_timestamp(now),
        }
        audit_event: dict[str, object] = {
            "action": "admitMemory",
            "operation_id": operation_id,
            "memory_version_ref": item.version_ref,
            "item_digest": item_digest,
            "content_digest": item.content_digest,
            "governed_context_digest": gcs_digest,
            "binding_ref": binding.binding_ref,
            "policy_decision_ref": decision.decision_ref,
            "policy_bundle_digest": decision.policy_bundle_digest,
            "correlation_id": context.correlation_id,
            "lifecycle_event_digest": canonical_digest(lifecycle_event),
            "at": format_utc_timestamp(now),
        }
        receipt = MemoryReceipt(
            memory_item_id=item.memory_item_id,
            memory_version=item.memory_version,
            content_digest=item.content_digest,
            lifecycle_status=item.lifecycle_status.value,
            governed_context_digest=gcs_digest,
            audit_ref=canonical_digest(audit_event),
        )
        record = AdmittedMemoryVersion(
            item=item,
            item_digest=item_digest,
            idempotency_key=key,
            lifecycle_event=MappingProxyType(lifecycle_event),
            audit_event=MappingProxyType(audit_event),
            receipt=receipt,
        )
        # 11. Persistence last, as one atomic append.
        self._ledger.append(record)
        return receipt

    def _bind_to_context(
        self, item: GovernedMemoryItem, context: GovernedContext, gcs_digest: str
    ) -> None:
        bound = {
            "tenant_id": context.tenant_id,
            "organization_id": context.organization_id,
            "domain_id": context.domain_id,
            "compartments": context.compartments,
            "purpose": context.purpose,
            "policy_bundle_digest": context.policy_bundle_digest,
            "ontology_release_digest": context.ontology_release_digest,
            "governed_context_digest": gcs_digest,
            "owner_principal_id": context.effective_principal_id,
        }
        differing = sorted(name for name, value in bound.items() if getattr(item, name) != value)
        if differing:
            raise MemoryAdmissionError(
                "GOVERNED_CONTEXT_MISMATCH",
                "ITEM_NOT_BOUND_TO_GCS",
                f"candidate is not bound to the authenticated GCS: {', '.join(differing)}",
            )

    def _validate_content(self, item: GovernedMemoryItem, payload: bytes) -> None:
        match = CONTENT_SCHEMA.fullmatch(item.content_schema_ref)
        content_class = match.group("content_class") if match else None
        if content_class in PROHIBITED_CONTENT_CLASSES:
            raise MemoryAdmissionError(
                "POLICY_DENIED",
                "PROHIBITED_CONTENT_CLASS",
                "content class is a prohibited memory payload",
            )
        if item.content_schema_ref not in self._limits.content_schemas:
            raise _schema_error("CONTENT_SCHEMA_UNKNOWN", "content_schema_ref is not registered")
        if not isinstance(payload, (bytes, bytearray)):
            raise _schema_error("PAYLOAD_INVALID", "payload must be bytes")
        calculated = "urn:sha256:" + hashlib.sha256(payload).hexdigest()
        if not hmac.compare_digest(calculated, item.content_digest):
            raise _schema_error("CONTENT_DIGEST_MISMATCH", "content_digest does not bind payload")
        text = bytes(payload).decode("utf-8", errors="replace")
        for marker, pattern in PROHIBITED_PAYLOAD_PATTERNS:
            if pattern.search(text):
                raise MemoryAdmissionError(
                    "POLICY_DENIED",
                    f"PROHIBITED_PAYLOAD_{marker}",
                    "payload contains a prohibited content class",
                )

    def _validate_temporal(self, item: GovernedMemoryItem, now: datetime) -> None:
        skew = self._limits.max_clock_skew
        if not now - skew <= item.created_at <= now + skew:
            raise MemoryAdmissionError(
                "POLICY_DENIED",
                "CREATED_AT_OUTSIDE_BOUNDARY_WINDOW",
                "created_at is not within the boundary clock admission window",
            )
        if item.valid_until is not None and item.valid_until <= item.valid_from:
            raise _schema_error("VALIDITY_WINDOW_INVALID", "valid_until must follow valid_from")
        if item.valid_until is not None and item.valid_until <= now:
            raise MemoryAdmissionError(
                "POLICY_DENIED", "VALIDITY_ELAPSED", "valid_until has already elapsed"
            )
        horizon = self._limits.retention_horizons.get(item.retention_policy_ref)
        if horizon is None:
            raise MemoryAdmissionError(
                "POLICY_DENIED", "RETENTION_POLICY_UNKNOWN", "retention policy is not approved"
            )
        if item.expires_at is not None:
            if item.expires_at <= now:
                raise MemoryAdmissionError(
                    "POLICY_DENIED", "ALREADY_EXPIRED", "expires_at has already elapsed"
                )
            if item.expires_at > now + horizon:
                raise MemoryAdmissionError(
                    "POLICY_DENIED",
                    "RETENTION_HORIZON_EXCEEDED",
                    "expires_at exceeds the retention policy horizon",
                )
        elif item.memory_kind is MemoryKind.WORKING:
            raise MemoryAdmissionError(
                "POLICY_DENIED",
                "WORKING_MEMORY_TTL_REQUIRED",
                "WORKING memory requires a bounded expires_at",
            )

    def _validate_kind_rules(self, item: GovernedMemoryItem) -> None:
        if item.lifecycle_status not in ADMISSION_STATUSES or any(
            value is not None
            for value in (item.legal_hold_ref, item.prior_lifecycle_status, item.deletion_epoch)
        ):
            raise MemoryAdmissionError(
                "LIFECYCLE_TRANSITION_INVALID",
                "ADMISSION_STATUS_INVALID",
                "admission enters the lifecycle at PROPOSED, ACTIVE or QUARANTINED only",
            )
        if item.memory_kind is MemoryKind.SEMANTIC and not item.derived_from_refs:
            raise _schema_error(
                "SEMANTIC_DERIVATION_MISSING",
                "SEMANTIC memory requires evidence and derivation (derived_from_refs)",
            )
        if item.memory_kind is MemoryKind.TEAM_SHARED and item.team_id is None:
            raise _schema_error("TEAM_BINDING_MISSING", "TEAM_SHARED memory requires team_id")
        consolidation = item.source_kind is SourceKind.MEMORY_CONSOLIDATION
        if consolidation != bool(item.consolidates_refs):
            raise _schema_error(
                "CONSOLIDATION_LINEAGE_INVALID",
                "MEMORY_CONSOLIDATION source and consolidates_refs must appear together",
            )

    def _validate_lineage(
        self, item: GovernedMemoryItem, context: GovernedContext
    ) -> tuple[GovernedMemoryItem, ...]:
        latest = self._ledger.latest_version(item.memory_item_id)
        if item.memory_version <= latest:
            existing = self._ledger.get(item.memory_item_id, item.memory_version)
            if existing is not None and hmac.compare_digest(existing.item_digest, item.digest()):
                raise MemoryAdmissionError(
                    "MEMORY_IDEMPOTENCY_CONFLICT",
                    "VERSION_ALREADY_ADMITTED",
                    f"{item.version_ref} is already admitted under another operation",
                )
            raise MemoryAdmissionError(
                "MEMORY_IDEMPOTENCY_CONFLICT",
                "IMMUTABLE_VERSION_OCCUPIED",
                f"{item.version_ref} is already admitted; versions are never overwritten",
            )
        if item.memory_version > 1 and latest == 0:
            raise MemoryAdmissionError(
                "MEMORY_NOT_FOUND", "ITEM_UNKNOWN", "a new version requires an admitted item"
            )
        if item.memory_version != latest + 1:
            raise MemoryAdmissionError(
                "MEMORY_VERSION_NOT_FOUND",
                "VERSION_GAP",
                f"{item.version_ref} does not follow the latest admitted version {latest}",
            )
        if item.memory_version == 1:
            if item.supersedes_ref is not None or item.correction_of_ref is not None:
                raise _schema_error(
                    "LINEAGE_INVALID",
                    "a first version cannot supersede or correct; use derived_from_refs",
                )
        else:
            predecessor = memory_version_ref(item.memory_item_id, item.memory_version - 1)
            if item.supersedes_ref != predecessor:
                raise _schema_error(
                    "LINEAGE_INVALID",
                    f"version {item.memory_version} must supersede exactly {predecessor}",
                )
            if item.correction_of_ref is not None:
                corrected_item, corrected_version = parse_memory_version_ref(
                    item.correction_of_ref
                )
                if (
                    corrected_item != item.memory_item_id
                    or corrected_version >= item.memory_version
                ):
                    raise _schema_error(
                        "LINEAGE_INVALID",
                        "correction_of_ref must reference an earlier version of the same item",
                    )
        sources: list[GovernedMemoryItem] = []
        for ref in item.lineage_refs():
            source_item, source_version = parse_memory_version_ref(ref)
            if source_item == item.memory_item_id and source_version >= item.memory_version:
                raise _schema_error("LINEAGE_INVALID", "lineage cannot reference itself or later")
            source = self._ledger.get(source_item, source_version)
            if source is None:
                raise MemoryAdmissionError(
                    "MEMORY_VERSION_NOT_FOUND",
                    "LINEAGE_SOURCE_MISSING",
                    "a lineage reference does not resolve to an admitted version",
                )
            if source.item.tenant_id != context.tenant_id:
                raise MemoryAdmissionError(
                    "AUTHORITY_DENIED",
                    "CROSS_TENANT_LINEAGE",
                    "cross-tenant lineage is deny-by-default",
                )
            if not set(source.item.compartments) <= set(context.compartments):
                raise MemoryAdmissionError(
                    "AUTHORITY_DENIED",
                    "LINEAGE_COMPARTMENT_NOT_AUTHORIZED",
                    "a lineage source is outside the authorized compartments",
                )
            sources.append(source.item)
        if item.memory_version > 1:
            predecessor_item = sources[0]
            for name in (
                "tenant_id",
                "organization_id",
                "domain_id",
                "memory_kind",
                "memory_scope",
            ) + SCOPE_BINDINGS[item.memory_scope]:
                if getattr(predecessor_item, name) != getattr(item, name):
                    raise _schema_error(
                        "LINEAGE_IDENTITY_CHANGED",
                        f"{name} is immutable across versions of one item",
                    )
        return tuple(sources)

    def _resolve_references(
        self, item: GovernedMemoryItem, context: GovernedContext, now: datetime
    ) -> tuple[EvidenceRecord, ...]:
        try:
            source_digest = self._resolver.source_digest(item.source_ref, context)
            evidence = [self._resolver.evidence(ref, context) for ref in item.evidence_refs]
            provenance = [
                self._resolver.provenance(ref, context) for ref in item.provenance_refs
            ]
        except MemoryAdmissionError:
            raise
        except Exception as exc:
            raise MemoryAdmissionError(
                "CONTROL_PLANE_UNAVAILABLE",
                "REFERENCE_RESOLVER_UNAVAILABLE",
                "reference resolution failed closed",
            ) from exc
        if source_digest is None or not hmac.compare_digest(source_digest, item.source_digest):
            raise _schema_error(
                "SOURCE_UNRESOLVED", "source_ref does not resolve to source_digest under the GCS"
            )
        resolved: list[EvidenceRecord] = []
        for ref, record in zip(item.evidence_refs, evidence, strict=True):
            if record is None or record.evidence_id != ref:
                raise _schema_error("EVIDENCE_UNRESOLVED", "an evidence ref does not resolve")
            if record.retention_until <= now:
                raise MemoryAdmissionError(
                    "POLICY_DENIED", "EVIDENCE_RETENTION_ELAPSED", "evidence retention elapsed"
                )
            resolved.append(record)
        covered_evidence: set[str] = set()
        covers_source = False
        for ref, prov in zip(item.provenance_refs, provenance, strict=True):
            if prov is None or prov.provenance_id != ref:
                raise _schema_error(
                    "PROVENANCE_UNRESOLVED", "a provenance ref does not resolve"
                )
            covered_evidence.update(prov.evidence_refs)
            covers_source = covers_source or item.source_ref in prov.source_refs
        if not covers_source or not set(item.evidence_refs) <= covered_evidence:
            raise _schema_error(
                "PROVENANCE_INCOMPLETE",
                "provenance must cover the source and every evidence ref",
            )
        return tuple(resolved)

    def _validate_marking(
        self,
        item: GovernedMemoryItem,
        context: GovernedContext,
        evidence: Sequence[EvidenceRecord],
        sources: Sequence[GovernedMemoryItem],
    ) -> None:
        inputs = [record.marking_ref for record in evidence] + [
            source.classification_marking_ref for source in sources
        ]
        for marking in inputs:
            if not self._markings.dominates(context.classification_marking_ref, marking):
                raise MemoryAdmissionError(
                    "AUTHORITY_DENIED",
                    "INPUT_MARKING_EXCEEDS_CONTEXT",
                    "an input is marked above the authenticated context",
                )
        required = self._markings.join([context.classification_marking_ref, *inputs])
        if not self._markings.dominates(item.classification_marking_ref, required):
            raise MemoryAdmissionError(
                "POLICY_DENIED",
                "MARKING_DOWNGRADE",
                "item marking is below the conservative join of its context and inputs",
            )

    def _validate_taint(
        self, item: GovernedMemoryItem, sources: Sequence[GovernedMemoryItem]
    ) -> None:
        required = {SOURCE_TAINT[item.source_kind]}
        required |= KIND_TAINT.get(item.memory_kind, frozenset())
        for source in sources:
            required |= set(source.taint_labels)
        missing = sorted(required - set(item.taint_labels))
        if missing:
            raise MemoryAdmissionError(
                "MEMORY_TAINTED",
                "TAINT_LABEL_MISSING",
                f"taint cannot be dropped or laundered: missing {', '.join(missing)}",
            )

    def _validate_scope_authority(
        self, item: GovernedMemoryItem, context: GovernedContext, now: datetime
    ) -> None:
        if item.memory_scope is not MemoryScope.FEDERATED:
            if item.federation_policy_ref is not None:
                raise _schema_error(
                    "FEDERATION_BINDING_UNEXPECTED",
                    "federation_policy_ref is only valid for FEDERATED scope",
                )
            return
        assert item.federation_policy_ref is not None
        try:
            policy = self._resolver.federation_policy(item.federation_policy_ref, context)
        except Exception as exc:
            raise MemoryAdmissionError(
                "CONTROL_PLANE_UNAVAILABLE",
                "REFERENCE_RESOLVER_UNAVAILABLE",
                "federation policy resolution failed closed",
            ) from exc
        if (
            policy is None
            or policy.policy_ref != item.federation_policy_ref
            or context.tenant_id not in policy.tenant_ids
            or context.purpose not in policy.purposes
            or policy.valid_until <= now
        ):
            raise MemoryAdmissionError(
                "AUTHORITY_DENIED",
                "FEDERATION_POLICY_NOT_APPLICABLE",
                "FEDERATED scope requires an applicable approved federation policy",
            )

    def _validate_instruction_eligibility(
        self, item: GovernedMemoryItem, context: GovernedContext, now: datetime
    ) -> None:
        if not item.instruction_eligible:
            return
        if item.memory_kind is MemoryKind.REFLECTION or "MODEL_GENERATED" in item.taint_labels:
            raise MemoryAdmissionError(
                "MEMORY_TAINTED",
                "MODEL_GENERATED_INSTRUCTION",
                "model-generated content is never instruction-eligible at admission",
            )
        if item.memory_kind is not MemoryKind.PROCEDURAL:
            raise MemoryAdmissionError(
                "UNSUPPORTED_CAPABILITY",
                "INSTRUCTION_ELIGIBILITY_UNSUPPORTED",
                "only PROCEDURAL memory may become instruction-eligible",
            )
        assert item.instruction_approval_ref is not None
        try:
            approval = self._resolver.instruction_approval(item.instruction_approval_ref, context)
        except Exception as exc:
            raise MemoryAdmissionError(
                "CONTROL_PLANE_UNAVAILABLE",
                "REFERENCE_RESOLVER_UNAVAILABLE",
                "instruction approval resolution failed closed",
            ) from exc
        if (
            approval is None
            or approval.approval_ref != item.instruction_approval_ref
            or approval.memory_item_id != item.memory_item_id
            or approval.approved_content_digest != item.content_digest
            or approval.tenant_id != item.tenant_id
            or approval.approver_principal_id == item.owner_principal_id
            or approval.valid_until <= now
        ):
            raise MemoryAdmissionError(
                "AUTHORITY_DENIED",
                "INSTRUCTION_APPROVAL_INVALID",
                "instruction eligibility requires a separate, current, exact approval",
            )

    def _evaluate_policy(
        self, item: GovernedMemoryItem, context: GovernedContext
    ) -> MemoryPolicyDecision:
        try:
            decision = self._policy.authorize_admission(item, context)
        except MemoryAdmissionError:
            raise
        except Exception as exc:
            raise MemoryAdmissionError(
                "CONTROL_PLANE_UNAVAILABLE",
                "POLICY_UNAVAILABLE",
                "admission policy evaluation failed closed",
            ) from exc
        if not isinstance(decision, MemoryPolicyDecision):
            raise MemoryAdmissionError(
                "CONTROL_PLANE_UNAVAILABLE", "POLICY_DECISION_INVALID", "no policy decision"
            )
        if decision.policy_bundle_digest != context.policy_bundle_digest:
            raise MemoryAdmissionError(
                "STALE_POLICY",
                "POLICY_BUNDLE_MISMATCH",
                "policy decision was not evaluated against the context bundle",
            )
        if not decision.permitted:
            raise MemoryAdmissionError(
                "POLICY_DENIED", "ADMISSION_DENIED", "admission policy denied the candidate"
            )
        return decision
