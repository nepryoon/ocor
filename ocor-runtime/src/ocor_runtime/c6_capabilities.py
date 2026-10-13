"""C6 — scoped, expiring and revocable capability leases."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Iterable, Protocol

from .c3_store import require_aware
from .errors import AuthorizationError, OCORError, TemporalGuardViolation


class StopEpochAuthority(Protocol):
    """The trusted emergency-stop epoch a lease is bound to (LLD v1.1
    sections 1.4 and 4.3), e.g. ``c6.safety.EmergencyStopController``."""

    @property
    def epoch(self) -> int: ...

    def guard_dispatch(self, *, fenced_epoch: int) -> None: ...


def _capability_matches(grant: str, requested: str) -> bool:
    if grant == "*" or grant == requested:
        return True
    return grant.endswith(":*") and requested.startswith(grant[:-1])


def _resource_matches(scope: str, resource: str) -> bool:
    if scope == "*" or scope == resource:
        return True
    return scope.endswith("/*") and resource.startswith(scope[:-1])


def _resource_scope_contains(parent: str, child: str) -> bool:
    if parent == "*" or parent == child:
        return True
    if parent.endswith("/*"):
        prefix = parent[:-1]
        if child.endswith("/*"):
            return child[:-1].startswith(prefix)
        return child.startswith(prefix)
    return False


@dataclass(frozen=True, slots=True)
class CapabilityLease:
    lease_id: str
    subject: str
    capabilities: frozenset[str]
    resources: frozenset[str]
    not_before: datetime
    expires_at: datetime
    issued_at: datetime
    issuer: str
    revoked_at: datetime | None = None
    parent_lease_id: str | None = None
    max_uses: int | None = None
    stop_epoch: int | None = None

    def __post_init__(self) -> None:
        if not self.lease_id or not self.subject or not self.issuer:
            raise ValueError("lease_id, subject and issuer are required")
        if not self.capabilities or not self.resources:
            raise ValueError("a capability lease requires capabilities and resources")
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        object.__setattr__(self, "resources", frozenset(self.resources))
        require_aware(self.not_before, field="not_before")
        require_aware(self.expires_at, field="expires_at")
        require_aware(self.issued_at, field="issued_at")
        if self.not_before >= self.expires_at:
            raise TemporalGuardViolation("lease not_before must precede expires_at")
        if self.issued_at > self.not_before:
            raise TemporalGuardViolation("lease cannot become active before it is issued")
        if self.revoked_at is not None:
            require_aware(self.revoked_at, field="revoked_at")
            if self.revoked_at < self.issued_at:
                raise TemporalGuardViolation("lease cannot be revoked before issuance")
        if self.max_uses is not None and self.max_uses <= 0:
            raise ValueError("max_uses must be positive")
        if self.stop_epoch is not None and (
            not isinstance(self.stop_epoch, int) or isinstance(self.stop_epoch, bool) or self.stop_epoch < 0
        ):
            raise ValueError("stop_epoch must be a non-negative integer")

    def is_active(self, at: datetime) -> bool:
        instant = require_aware(at, field="at")
        return (
            self.not_before <= instant < self.expires_at
            and (self.revoked_at is None or instant < self.revoked_at)
        )

    def allows(
        self,
        capability: str,
        resource: str,
        *,
        at: datetime,
        subject: str | None = None,
    ) -> bool:
        if subject is not None and subject != self.subject:
            return False
        if not self.is_active(at):
            return False
        return any(
            _capability_matches(grant, capability) for grant in self.capabilities
        ) and any(_resource_matches(scope, resource) for scope in self.resources)


class CapabilityAuthority:
    """Authoritative issuer and usage ledger for capability leases."""

    def __init__(
        self,
        issuer: str = "ocor-capability-authority",
        *,
        stop: StopEpochAuthority | None = None,
    ) -> None:
        if not issuer:
            raise ValueError("issuer must be non-empty")
        self.issuer = issuer
        self._leases: dict[str, CapabilityLease] = {}
        self._uses: dict[str, int] = {}
        self._lock = threading.RLock()
        self._stop = stop

    @property
    def stop_controller(self) -> StopEpochAuthority | None:
        with self._lock:
            return self._stop

    def bind_stop_controller(self, stop: StopEpochAuthority) -> None:
        """Bind every lease issued from now on to ``stop``'s epoch. An
        authority serves exactly one emergency-stop controller."""
        with self._lock:
            if self._stop is None:
                self._stop = stop
            elif self._stop is not stop:
                raise ValueError("capability authority is already bound to another emergency-stop controller")

    def _current_stop_epoch(self) -> int | None:
        stop = self.stop_controller
        if stop is None:
            return None
        epoch = stop.epoch
        try:
            stop.guard_dispatch(fenced_epoch=epoch)
        except OCORError as error:
            raise AuthorizationError(f"emergency stop is active, no capability lease is issued: {error}") from error
        return epoch

    def issue(
        self,
        *,
        subject: str,
        capabilities: Iterable[str],
        resources: Iterable[str],
        issued_at: datetime,
        not_before: datetime | None = None,
        expires_at: datetime | None = None,
        ttl: timedelta | None = None,
        lease_id: str | None = None,
        max_uses: int | None = None,
        parent: CapabilityLease | None = None,
    ) -> CapabilityLease:
        issued = require_aware(issued_at, field="issued_at")
        starts = require_aware(not_before or issued, field="not_before")
        if (expires_at is None) == (ttl is None):
            raise ValueError("provide exactly one of expires_at or ttl")
        ends = require_aware(expires_at or (starts + ttl), field="expires_at")  # type: ignore[operator]
        authoritative_parent: CapabilityLease | None = None
        if parent is not None:
            with self._lock:
                authoritative_parent = self._leases.get(parent.lease_id)
            if authoritative_parent is None:
                raise AuthorizationError("delegating parent lease is not authoritative")
            if not authoritative_parent.is_active(starts):
                raise AuthorizationError("delegating parent lease is inactive")
        stop_epoch = self._current_stop_epoch()
        lease = CapabilityLease(
            lease_id=lease_id or str(uuid.uuid4()),
            subject=subject,
            capabilities=frozenset(capabilities),
            resources=frozenset(resources),
            not_before=starts,
            expires_at=ends,
            issued_at=issued,
            issuer=self.issuer,
            parent_lease_id=authoritative_parent.lease_id if authoritative_parent else None,
            max_uses=max_uses,
            stop_epoch=stop_epoch,
        )
        if authoritative_parent is not None:
            self._validate_delegation(authoritative_parent, lease)
        with self._lock:
            if lease.lease_id in self._leases:
                raise ValueError(f"duplicate lease id: {lease.lease_id}")
            self._leases[lease.lease_id] = lease
            self._uses[lease.lease_id] = 0
        return lease

    @staticmethod
    def _validate_delegation(parent: CapabilityLease, child: CapabilityLease) -> None:
        if child.issued_at < parent.issued_at:
            raise AuthorizationError("delegated lease predates its parent")
        if parent.stop_epoch is not None and child.stop_epoch != parent.stop_epoch:
            raise AuthorizationError("delegating parent lease is bound to another emergency-stop epoch")
        if child.not_before < parent.not_before or child.expires_at > parent.expires_at:
            raise AuthorizationError("delegated lease exceeds its parent time window")
        if any(
            not any(_capability_matches(grant, requested) for grant in parent.capabilities)
            for requested in child.capabilities
        ):
            raise AuthorizationError("delegated lease escalates capabilities")
        if any(
            not any(_resource_scope_contains(scope, child_scope) for scope in parent.resources)
            for child_scope in child.resources
        ):
            raise AuthorizationError("delegated lease widens its resource scope")

    def get(self, lease_id: str) -> CapabilityLease | None:
        with self._lock:
            return self._leases.get(lease_id)

    def revoke(self, lease_id: str, *, at: datetime) -> CapabilityLease:
        instant = require_aware(at, field="at")
        with self._lock:
            lease = self._leases[lease_id]
            if lease.revoked_at is not None:
                return lease
            revoked = replace(lease, revoked_at=instant)
            self._leases[lease_id] = revoked
            return revoked

    def authorize(
        self,
        lease: CapabilityLease | str,
        capability: str,
        resource: str,
        *,
        at: datetime,
        subject: str | None = None,
        consume: bool = False,
    ) -> CapabilityLease:
        instant = require_aware(at, field="at")
        lease_id = lease if isinstance(lease, str) else lease.lease_id
        with self._lock:
            authoritative = self._leases.get(lease_id)
            if authoritative is None:
                raise AuthorizationError("capability lease is unknown to its authority")
            if not authoritative.allows(
                capability, resource, at=instant, subject=subject
            ):
                raise AuthorizationError("capability lease is inactive or out of scope")
            self._require_active_ancestry(authoritative, instant, seen=set())
            uses = self._uses[lease_id]
            if authoritative.max_uses is not None and uses >= authoritative.max_uses:
                raise AuthorizationError("capability lease usage limit is exhausted")
            if consume:
                self._uses[lease_id] = uses + 1
            return authoritative

    def _require_active_ancestry(
        self,
        lease: CapabilityLease,
        instant: datetime,
        *,
        seen: set[str],
    ) -> None:
        if lease.lease_id in seen:
            raise AuthorizationError("capability delegation cycle detected")
        seen.add(lease.lease_id)
        if lease.parent_lease_id is None:
            return
        parent = self._leases.get(lease.parent_lease_id)
        if parent is None or not parent.is_active(instant):
            raise AuthorizationError("parent capability lease is inactive")
        self._require_active_ancestry(parent, instant, seen=seen)

    def usage(self, lease_id: str) -> int:
        with self._lock:
            return self._uses[lease_id]


LeaseRegistry = CapabilityAuthority
