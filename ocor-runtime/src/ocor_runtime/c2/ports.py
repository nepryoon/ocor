"""Typed named-query, consistency and watermark ports for C2.

Every failure is a ``C2Error`` whose reason code belongs to the closed Problem enum of
the Named Query Gateway contract (``ocor-named-query-gateway.openapi.yaml`` :452-466);
``STALE_CONTEXT``, ``PROJECTION_NOT_READY`` and ``RELEASE_MISMATCH`` always carry the
served context (:472-479, ADD v1.3 :1362). The internal digest form is
``urn:sha256:<hex>`` (LLD v1.1 :37); the transport adapter converts the wire form.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

from ..kernel.canonical import (
    IdentifierError,
    validate_correlation_id,
    verify_canonical_digest,
)
from ..kernel.governed_context import GovernedContext, GovernedContextError
from .problem import SERVED_REQUIRED

if TYPE_CHECKING:
    from ..security.ports import AuthenticatedPrincipal

DIGEST = re.compile(r"urn:sha256:[0-9a-f]{64}")
NAMED_CONTRACT = re.compile(r"urn:ocor:contract:named-query:[A-Za-z0-9._~-]+")
URN = re.compile(r"urn:ocor:[A-Za-z0-9._~:/-]+")
DEFERRED_ELEMENT = re.compile(r"(ELM|CAP|FR)-[0-9]{3}")
FORBIDDEN_QUERY_FIELDS = frozenset({"query", "query_text", "sparql", "sql", "typeql", "woql"})


class C2Error(ValueError):
    """A typed fail-closed C2 failure, convertible to the contract Problem."""

    def __init__(
        self,
        reason_code: str,
        message: str,
        *,
        served: ServedContext | None = None,
        deferred_element: str | None = None,
    ) -> None:
        # The C2 runtime emits only the closed enum (verified by an AST scan). Sealed spike
        # adapters behind ProjectionReadPort may still raise their own codes: the gateway
        # maps every code outside PROBLEM_REASON_CODES to POLICY_DENIED before the wire.
        if not isinstance(reason_code, str) or not reason_code:
            raise ValueError("a reason code is required")
        if reason_code in SERVED_REQUIRED and served is None:
            raise ValueError(f"{reason_code} requires the served context")
        if reason_code == "CAPABILITY_DEFERRED" and (
            not isinstance(deferred_element, str) or DEFERRED_ELEMENT.fullmatch(deferred_element) is None
        ):
            raise ValueError("CAPABILITY_DEFERRED requires the deferred element")
        self.reason_code = reason_code
        self.detail = message
        self.served = served
        self.deferred_element = deferred_element
        super().__init__(f"{reason_code}: {message}")


def _required(field: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise C2Error("SCHEMA_VIOLATION", f"{field} is required")
    return value


def _digest(field: str, value: object) -> str:
    result = _required(field, value)
    if DIGEST.fullmatch(result) is None:
        raise C2Error("SCHEMA_VIOLATION", f"{field} must be a SHA-256 URN")
    return result


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(child) for child in value)
    return copy.deepcopy(value)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw(child) for child in value]
    return copy.deepcopy(value)


class ConsistencyMode(StrEnum):
    BEST_AVAILABLE = "BEST_AVAILABLE"
    AT_LEAST_COMMIT = "AT_LEAST_COMMIT"
    EXACT_AT_COMMIT = "EXACT_AT_COMMIT"


@dataclass(frozen=True, slots=True)
class ServedContext:
    """What was actually served (NFR-024, Register :180). The gateway adds the result
    marking join, the provenance reference and the redaction count (contract :254-273)."""

    branch: str
    ontology_release_digest: str
    canonical_commit: str
    projection_watermark: str
    staleness_ms: int
    governed_context_digest: str
    policy_bundle_digest: str
    result_marking_ref: str | None = None
    provenance_ref: str | None = None
    redaction_count: int = 0

    def __post_init__(self) -> None:
        for field in ("branch", "canonical_commit", "projection_watermark"):
            _required(field, getattr(self, field))
        for field in (
            "ontology_release_digest",
            "governed_context_digest",
            "policy_bundle_digest",
        ):
            _digest(field, getattr(self, field))
        for field in ("result_marking_ref", "provenance_ref"):
            if getattr(self, field) is not None:
                _digest(field, getattr(self, field))
        for field in ("staleness_ms", "redaction_count"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise C2Error("SCHEMA_VIOLATION", f"{field} must be non-negative")


@runtime_checkable
class CommitOrderingPort(Protocol):
    """Branch/commit ordering (FR-057 dependency, Register :179): the position of a
    canonical commit on a branch, or ``None`` when the commit is not (yet) known there."""

    def position(self, branch: str, commit: str) -> int | None: ...


def commit_reached(ordering: CommitOrderingPort | None, branch: str, observed: str, required: str) -> bool:
    """``observed >= required`` on ``branch``; equality needs no ordering, anything
    else is decided only by a known order (fail-closed when either is unknown)."""

    if observed == required:
        return True
    if ordering is None:
        return False
    required_position = ordering.position(branch, required)
    observed_position = ordering.position(branch, observed)
    if required_position is None or observed_position is None:
        return False
    return observed_position >= required_position


@dataclass(frozen=True, slots=True)
class ConsistencyRequirement:
    mode: ConsistencyMode
    required_commit: str | None = None
    wait_timeout_ms: int = 0

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "mode", ConsistencyMode(self.mode))
        except ValueError as exc:
            raise C2Error("SCHEMA_VIOLATION", f"unknown consistency mode: {self.mode}") from exc
        if isinstance(self.wait_timeout_ms, bool) or not isinstance(self.wait_timeout_ms, int) or not 0 <= self.wait_timeout_ms <= 30000:
            raise C2Error("SCHEMA_VIOLATION", "wait_timeout_ms is outside 0..30000")
        if self.required_commit is not None and (
            not isinstance(self.required_commit, str) or not 1 <= len(self.required_commit) <= 256
        ):
            raise C2Error("SCHEMA_VIOLATION", "required_commit must be 1..256 characters")
        # contract :135-141: required_commit is mandatory for the strong modes only and
        # allowed otherwise (NCR-C2-009); BEST_AVAILABLE serves the latest compatible
        # watermark and declares its staleness (LLD v1.1 :126).
        requires_commit = self.mode in {
            ConsistencyMode.AT_LEAST_COMMIT,
            ConsistencyMode.EXACT_AT_COMMIT,
        }
        if requires_commit and self.required_commit is None:
            raise C2Error("SCHEMA_VIOLATION", "required_commit is mandatory for strong consistency")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ConsistencyRequirement:
        allowed = {"mode", "required_commit", "wait_timeout_ms"}
        if set(value) - allowed:
            raise C2Error("SCHEMA_VIOLATION", "additional consistency property")
        try:
            return cls(
                mode=value["mode"],  # type: ignore[arg-type]
                required_commit=value.get("required_commit"),  # type: ignore[arg-type]
                wait_timeout_ms=value.get("wait_timeout_ms", 0),  # type: ignore[arg-type]
            )
        except KeyError as exc:
            raise C2Error("SCHEMA_VIOLATION", "mode is required") from exc

    def to_mapping(self) -> dict[str, object]:
        result: dict[str, object] = {"mode": self.mode.value, "wait_timeout_ms": self.wait_timeout_ms}
        if self.required_commit is not None:
            result["required_commit"] = self.required_commit
        return result

    def verify_served(self, served: ServedContext, ordering: CommitOrderingPort | None = None) -> ServedContext:
        """FR-057 (Register :179), ADD v1.3 :1361, LLD v1.1 :126 and :369: AT_LEAST_COMMIT(Cn)
        may serve Cm >= Cn and declares Cm; EXACT_AT_COMMIT(Cn) serves exactly Cn or answers
        PROJECTION_NOT_READY with the served context, never a downgrade."""

        if self.mode is ConsistencyMode.BEST_AVAILABLE:
            return served
        required = self.required_commit
        assert required is not None  # guaranteed by __post_init__ for the strong modes
        if self.mode is ConsistencyMode.AT_LEAST_COMMIT:
            if commit_reached(ordering, served.branch, served.projection_watermark, required) and commit_reached(
                ordering, served.branch, served.canonical_commit, required
            ):
                return served
            raise C2Error(
                "PROJECTION_NOT_READY", "served watermark does not yet reach the requested commit", served=served
            )
        if served.projection_watermark != required or served.canonical_commit != required:
            raise C2Error("PROJECTION_NOT_READY", "served commit is not exactly the requested commit", served=served)
        return served


@dataclass(frozen=True, slots=True)
class NamedQueryRequest:
    """The admitted named query. Besides the call and the GCS it carries the branch,
    logic version and scenario of the contract ``QueryContext`` (:142-184) into the planned
    read (LLD v1.1 :124, :126); ``branch`` defaults to ``main``."""

    request_id: str
    contract_id: str
    contract_version: str
    contract_digest: str
    parameters: Mapping[str, Any]
    governed_context: GovernedContext
    governed_context_digest: str
    consistency: ConsistencyRequirement
    branch: str = "main"
    logic_version: str | None = None
    scenario_id: str | None = None

    optional_fields: ClassVar[tuple[str, ...]] = ("branch", "logic_version", "scenario_id")
    fields: ClassVar[tuple[str, ...]] = (
        "request_id",
        "contract_id",
        "contract_version",
        "contract_digest",
        "parameters",
        "governed_context",
        "governed_context_digest",
        "consistency",
    )

    def __post_init__(self) -> None:
        try:
            validate_correlation_id(self.request_id)
        except IdentifierError as exc:
            raise C2Error("SCHEMA_VIOLATION", f"request_id is invalid: {exc}") from exc
        if not isinstance(self.contract_id, str) or NAMED_CONTRACT.fullmatch(self.contract_id) is None:
            raise C2Error("SCHEMA_VIOLATION", "only named query contract IDs are accepted")
        _required("contract_version", self.contract_version)
        _digest("contract_digest", self.contract_digest)
        _digest("governed_context_digest", self.governed_context_digest)
        # contract :180-184: branch 1..256, logic_version 1..128, scenario_id a UUID
        if not isinstance(self.branch, str) or not 1 <= len(self.branch) <= 256:
            raise C2Error("SCHEMA_VIOLATION", "branch must be 1..256 characters")
        if self.logic_version is not None and (
            not isinstance(self.logic_version, str) or not 1 <= len(self.logic_version) <= 128
        ):
            raise C2Error("SCHEMA_VIOLATION", "logic_version must be 1..128 characters")
        if self.scenario_id is not None:
            try:
                validate_correlation_id(self.scenario_id)
            except (IdentifierError, TypeError) as exc:
                raise C2Error("SCHEMA_VIOLATION", "scenario_id is invalid") from exc
        # ADD v1.3 :380 (Query surface): an absent or mismatching GCS field is DENY.
        if not self.governed_context.purpose:
            raise C2Error("POLICY_DENIED", "purpose is required before routing")
        try:
            verify_canonical_digest(
                self.governed_context.to_mapping(), self.governed_context_digest
            )
        except Exception as exc:
            raise C2Error("POLICY_DENIED", "GCS digest mismatch") from exc
        if not isinstance(self.parameters, Mapping):
            raise C2Error("SCHEMA_VIOLATION", "parameters must be an object")
        forbidden = FORBIDDEN_QUERY_FIELDS & {str(key).lower() for key in self.parameters}
        if forbidden:
            raise C2Error("SCHEMA_VIOLATION", "parameters contain arbitrary query text")
        object.__setattr__(self, "parameters", _freeze(self.parameters))

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> NamedQueryRequest:
        present = set(value)
        additional = present - set(cls.fields) - set(cls.optional_fields)
        missing = set(cls.fields) - present
        if additional:
            raise C2Error("SCHEMA_VIOLATION", f"additional query fields: {sorted(additional)}")
        if missing:
            raise C2Error("SCHEMA_VIOLATION", f"missing query fields: {sorted(missing)}")
        context_value = value["governed_context"]
        if not isinstance(context_value, Mapping):
            raise C2Error("SCHEMA_VIOLATION", "governed_context must be an object")
        try:
            context = GovernedContext.from_mapping(context_value)
        except GovernedContextError as exc:
            # ADD v1.3 :380: an incomplete or mismatching GCS on the Query surface is DENY.
            raise C2Error("POLICY_DENIED", str(exc)) from exc
        consistency_value = value["consistency"]
        if not isinstance(consistency_value, Mapping):
            raise C2Error("SCHEMA_VIOLATION", "consistency must be an object")
        return cls(
            request_id=value["request_id"],  # type: ignore[arg-type]
            contract_id=value["contract_id"],  # type: ignore[arg-type]
            contract_version=value["contract_version"],  # type: ignore[arg-type]
            contract_digest=value["contract_digest"],  # type: ignore[arg-type]
            parameters=value["parameters"],  # type: ignore[arg-type]
            governed_context=context,
            governed_context_digest=value["governed_context_digest"],  # type: ignore[arg-type]
            consistency=ConsistencyRequirement.from_mapping(consistency_value),
            branch=value.get("branch", "main"),  # type: ignore[arg-type]
            logic_version=value.get("logic_version"),  # type: ignore[arg-type]
            scenario_id=value.get("scenario_id"),  # type: ignore[arg-type]
        )

    @property
    def isolation_key(self) -> tuple[object, ...]:
        return self.governed_context.isolation_key()

    def to_mapping(self) -> dict[str, object]:
        result: dict[str, object] = {
            "request_id": self.request_id,
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "contract_digest": self.contract_digest,
            "parameters": _thaw(self.parameters),
            "governed_context": self.governed_context.to_mapping(),
            "governed_context_digest": self.governed_context_digest,
            "consistency": self.consistency.to_mapping(),
            "branch": self.branch,
        }
        if self.logic_version is not None:
            result["logic_version"] = self.logic_version
        if self.scenario_id is not None:
            result["scenario_id"] = self.scenario_id
        return result

    def verify_served(self, served: ServedContext, ordering: CommitOrderingPort | None = None) -> ServedContext:
        context = self.governed_context
        if (
            served.governed_context_digest != self.governed_context_digest
            or served.policy_bundle_digest != context.policy_bundle_digest
            or served.ontology_release_digest != context.ontology_release_digest
        ):
            raise C2Error("STALE_CONTEXT", "served context drifted from request bindings", served=served)
        return self.consistency.verify_served(served, ordering)


@dataclass(frozen=True, slots=True)
class NamedQueryResponse:
    request_id: str
    result_ref: str
    result_digest: str
    served: ServedContext

    def __post_init__(self) -> None:
        validate_correlation_id(self.request_id)
        _required("result_ref", self.result_ref)
        _digest("result_digest", self.result_digest)


@dataclass(frozen=True, slots=True)
class Watermark:
    projection_id: str
    branch: str
    ontology_release_digest: str
    canonical_commit: str
    observed_at: datetime

    def __post_init__(self) -> None:
        for field in ("projection_id", "branch", "canonical_commit"):
            _required(field, getattr(self, field))
        _digest("ontology_release_digest", self.ontology_release_digest)
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise C2Error("SCHEMA_VIOLATION", "observed_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class QueryContext:
    """The contract ``QueryContext`` (:142-184) in the internal digest form.

    ``principal_id`` and ``actor_chain`` are deliberately absent: they derive from the
    transport security context (contract :145-149; ADD v1.3 :380; LLD v1.1 :41).
    """

    request_id: str
    correlation_id: str
    tenant_id: str
    organization_id: str
    domain_id: str
    compartments: tuple[str, ...]
    purpose: str
    classification_marking_ref: str
    ontology_release_digest: str
    policy_bundle_digest: str
    governed_context_digest: str
    logic_version: str
    branch: str
    consistency: ConsistencyRequirement
    scenario_id: str | None = None

    def __post_init__(self) -> None:
        for field in ("request_id", "correlation_id"):
            try:
                validate_correlation_id(getattr(self, field))
            except (IdentifierError, TypeError) as exc:
                raise C2Error("SCHEMA_VIOLATION", f"{field} is invalid") from exc
        for field in ("logic_version", "branch"):
            _required(field, getattr(self, field))
        for field in ("ontology_release_digest", "policy_bundle_digest", "governed_context_digest"):
            _digest(field, getattr(self, field))
        if not isinstance(self.consistency, ConsistencyRequirement):
            raise C2Error("SCHEMA_VIOLATION", "consistency is required")
        if self.scenario_id is not None:
            try:
                validate_correlation_id(self.scenario_id)
            except (IdentifierError, TypeError) as exc:
                raise C2Error("SCHEMA_VIOLATION", "scenario_id is invalid") from exc
        object.__setattr__(self, "compartments", tuple(self.compartments))

    def governed_context(self, *, principal_id: str, actor_chain: tuple[str, ...]) -> GovernedContext:
        """The canonical eleven-field GCS bound to the transport principal; the body digest
        is recomputed on it and a mismatch is DENY (ADD v1.3 :380; LLD v1.1 :38)."""

        try:
            context = GovernedContext.from_mapping({
                "tenant_id": self.tenant_id,
                "organization_id": self.organization_id,
                "domain_id": self.domain_id,
                "compartments": list(self.compartments),
                "classification_marking_ref": self.classification_marking_ref,
                "purpose": self.purpose,
                "effective_principal_id": principal_id,
                "actor_chain": list(actor_chain),
                "ontology_release_digest": self.ontology_release_digest,
                "policy_bundle_digest": self.policy_bundle_digest,
                "correlation_id": self.correlation_id,
            })
        except GovernedContextError as exc:
            raise C2Error("POLICY_DENIED", "the governed context is incomplete") from exc
        if context.digest() != self.governed_context_digest:
            raise C2Error("POLICY_DENIED", "governed_context_digest does not bind the transport principal")
        return context


@dataclass(frozen=True, slots=True)
class ContractCall:
    """The contract ``ContractCall`` (:185-195): ``parameters`` are validated against the
    closed schema selected by contract id and digest (ADD v1.3 :1361)."""

    contract_id: str
    contract_version: str
    contract_digest: str
    parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.contract_id, str) or URN.fullmatch(self.contract_id) is None:
            raise C2Error("SCHEMA_VIOLATION", "contract_id is not a contract URN")
        if not isinstance(self.contract_version, str):
            raise C2Error("SCHEMA_VIOLATION", "contract_version must be a string")
        _digest("contract_digest", self.contract_digest)
        if not isinstance(self.parameters, Mapping):
            raise C2Error("SCHEMA_VIOLATION", "parameters must be an object")
        object.__setattr__(self, "parameters", _freeze(self.parameters))


@dataclass(frozen=True, slots=True)
class NamedQueryCall:
    """A query body without principal: the context and the named contract call."""

    context: QueryContext
    call: ContractCall


@dataclass(frozen=True, slots=True)
class TransportBoundQuery:
    """A query bound to the principal authenticated by the transport (mTLS/workload
    identity and verified token, ADD v1.3 :1361), never by the body."""

    principal: AuthenticatedPrincipal
    query: NamedQueryCall


@runtime_checkable
class NamedQueryPort(Protocol):
    def execute(self, request: NamedQueryRequest) -> NamedQueryResponse: ...


@runtime_checkable
class ProjectionReadPort(Protocol):
    def read(self, request: NamedQueryRequest) -> NamedQueryResponse: ...


@runtime_checkable
class PolicyDecisionPort(Protocol):
    def decide(self, request: NamedQueryRequest) -> str: ...


@runtime_checkable
class AuthorityResolutionPort(Protocol):
    def resolve(self, request: NamedQueryRequest) -> str: ...


@runtime_checkable
class EvidenceReadPort(Protocol):
    """LLD v1.1 :113. The read is bound to the transport principal and admitted like a
    named query (LLD v1.1 :117-120), never to a body-borne request."""

    def get(self, evidence_ref: str, query: TransportBoundQuery) -> Mapping[str, object]: ...


@runtime_checkable
class WatermarkPort(Protocol):
    def current(self, projection_id: str, branch: str) -> Watermark: ...
