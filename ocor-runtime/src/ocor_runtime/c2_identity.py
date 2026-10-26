"""C2 — authoritative identity registry and Identify-or-Abstain resolver."""

from __future__ import annotations

import copy
import threading
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .errors import IdentityConflictError, OCORError

# Reserved Q1 attributes of identity-record v1.2 (PO decision
# REM-0024-BREAK-GLASS-PRINCIPAL-AUTHORITY): only composition seeding and the
# IdentityProvisioningBoundary may introduce a record that carries them
# (PO decision REM-0031-REGISTRY-CONSUMER-SCOPE, option 1).
RESERVED_PRINCIPAL_ATTRIBUTES = frozenset({"principal_kind", "status", "roles"})
PRIVILEGED_RECORD_REASON_CODE = "IDENTITY_PRIVILEGED_RECORD_REQUIRES_PROVISIONING"


class IdentityRegistrationDenied(OCORError, PermissionError):
    """A new record with reserved Q1 attributes reached the open write path."""

    reason_code = PRIVILEGED_RECORD_REASON_CODE


def normalize_identifier(value: str) -> str:
    """Normalize aliases without introducing fuzzy or lossy matching."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("identity identifier must be a non-empty string")
    return unicodedata.normalize("NFKC", value).strip().casefold()


@dataclass(frozen=True, slots=True)
class IdentityRecord:
    canonical_id: str
    aliases: frozenset[str] = field(default_factory=frozenset)
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_id, str) or not self.canonical_id.strip():
            raise ValueError("canonical_id must be a non-empty string")
        object.__setattr__(self, "aliases", frozenset(self.aliases))
        object.__setattr__(
            self,
            "attributes",
            MappingProxyType(copy.deepcopy(dict(self.attributes))),
        )


class ResolutionStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    ABSTAIN = "ABSTAIN"


@dataclass(frozen=True, slots=True)
class ResolutionOutcome:
    status: ResolutionStatus
    canonical_id: str | None
    confidence: float
    reason: str
    candidates: tuple[str, ...] = ()

    @property
    def identified(self) -> bool:
        return self.status is ResolutionStatus.IDENTIFIED


class IdentityRegistry:
    """Thread-safe registry with immutable canonical records.

    Alias collisions are retained as evidence of ambiguity.  The resolver then
    abstains unless authoritative evidence selects one candidate with sufficient
    confidence and margin.

    Records carrying reserved Q1 attributes enter only as ``records`` seeded at
    construction, before the registry is shared, or later through
    ``IdentityProvisioningBoundary``; ``register`` refuses every new one.
    """

    def __init__(self, records: Iterable[IdentityRecord] = ()) -> None:
        self._records: dict[str, IdentityRecord] = {}
        self._aliases: dict[str, set[str]] = {}
        self._lock = threading.RLock()
        for record in records:
            self._store(record)

    def register(self, record: IdentityRecord) -> IdentityRecord:
        with self._lock:
            # Immutability first: a different record under a known identity
            # is still an IdentityConflictError, an identical one a no-op.
            if self._records.get(record.canonical_id) is None and (
                RESERVED_PRINCIPAL_ATTRIBUTES & set(record.attributes)
            ):
                raise IdentityRegistrationDenied(
                    f"{PRIVILEGED_RECORD_REASON_CODE}: new identity {record.canonical_id!r} "
                    "carries reserved principal attributes"
                )
            return self._store(record)

    def _admit_provisioned(self, record: IdentityRecord) -> IdentityRecord:
        """Write path reserved to IdentityProvisioningBoundary, which has
        authenticated and authorised the writer and holds the lock."""

        with self._lock:
            return self._store(record)

    def _store(self, record: IdentityRecord) -> IdentityRecord:
        with self._lock:
            existing = self._records.get(record.canonical_id)
            if existing is not None:
                if existing != record:
                    raise IdentityConflictError(
                        f"canonical identity {record.canonical_id!r} is immutable"
                    )
                return existing

            stable = IdentityRecord(
                canonical_id=record.canonical_id,
                aliases=frozenset(record.aliases),
                attributes=record.attributes,
            )
            self._records[stable.canonical_id] = stable
            identifiers = set(stable.aliases) | {stable.canonical_id}
            for identifier in identifiers:
                self._aliases.setdefault(normalize_identifier(identifier), set()).add(
                    stable.canonical_id
                )
            return stable

    def get(self, canonical_id: str) -> IdentityRecord | None:
        with self._lock:
            return self._records.get(canonical_id)

    def add_alias(self, canonical_id: str, alias: str) -> None:
        """Add evidence without rewriting the immutable identity record."""

        normalized = normalize_identifier(alias)
        with self._lock:
            if canonical_id not in self._records:
                raise KeyError(canonical_id)
            self._aliases.setdefault(normalized, set()).add(canonical_id)

    def candidates(self, identifier: str) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._aliases.get(normalize_identifier(identifier), ())))

    def resolve(
        self,
        identifier: str,
        *,
        evidence: Mapping[str, float] | None = None,
        minimum_confidence: float = 0.80,
        minimum_margin: float = 0.10,
    ) -> ResolutionOutcome:
        if not (0.0 <= minimum_confidence <= 1.0):
            raise ValueError("minimum_confidence must be between zero and one")
        if not (0.0 <= minimum_margin <= 1.0):
            raise ValueError("minimum_margin must be between zero and one")

        candidates = self.candidates(identifier)
        if not candidates:
            return ResolutionOutcome(
                ResolutionStatus.ABSTAIN,
                None,
                0.0,
                "no authoritative identity candidate",
            )

        if evidence is None:
            scores = {candidate: 1.0 for candidate in candidates}
        else:
            unknown = set(evidence) - set(candidates)
            if unknown:
                return ResolutionOutcome(
                    ResolutionStatus.ABSTAIN,
                    None,
                    0.0,
                    "evidence names a non-candidate identity",
                    candidates,
                )
            scores = {candidate: float(evidence.get(candidate, 0.0)) for candidate in candidates}
            if any(score < 0.0 or score > 1.0 for score in scores.values()):
                raise ValueError("identity evidence scores must be between zero and one")

        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        winner, confidence = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = confidence - runner_up
        if confidence < minimum_confidence:
            return ResolutionOutcome(
                ResolutionStatus.ABSTAIN,
                None,
                confidence,
                "best candidate is below the confidence threshold",
                candidates,
            )
        if len(ranked) > 1 and margin < minimum_margin:
            return ResolutionOutcome(
                ResolutionStatus.ABSTAIN,
                None,
                confidence,
                "candidate evidence is ambiguous",
                candidates,
            )
        return ResolutionOutcome(
            ResolutionStatus.IDENTIFIED,
            winner,
            confidence,
            "authoritative identity resolved",
            candidates,
        )

    def all_records(self) -> tuple[IdentityRecord, ...]:
        with self._lock:
            return tuple(self._records[key] for key in sorted(self._records))


IdentityResolver = IdentityRegistry


def identify_or_abstain(
    records: Iterable[IdentityRecord], identifier: str
) -> ResolutionOutcome:
    return IdentityRegistry(records).resolve(identifier)

