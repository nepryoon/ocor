"""C5 admission control: quotas per tenant and priority class (LLD v1.1 :165 and :338).

"Backpressure applica quote per tenant e priority class; audit/security non vengono
eliminati" (LLD v1.1 :165); "ResourceClass (``CONTROL``, ``INTERACTIVE``, ``BATCH``,
``AUDIT``) determina quota, priority e backpressure. C6/control/audit non condividono pool
esauribile con causal batch" (LLD v1.1 :338). Each ``(tenant, ResourceClass)`` has its own
in-flight pool, so saturating one class never starves another class or another tenant.
An ``AUDIT`` publish is never refused for backpressure: it is admitted even above its quota
and only counted. Admission runs after authentication, integrity, schema and policy
checks, which therefore never get disabled under saturation (Register :406, NFR-079).

``EventOperationsCoordinator`` is the operations surface of one backbone (ADD v1.3 :273 and
:286): publish under backpressure, the durable dead letters, the ``POISON`` operator gate and
the authorised reprocess of a dead letter (``ReprocessAuthorized``), which re-runs every
admission check of a fresh publish and never publishes a canonical effect twice (LLD v1.1
:161-165).
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from enum import Enum
from typing import TYPE_CHECKING

from .adapters.postgres import DeadLetter
from .envelope import BackboneError, SignedEnvelope

if TYPE_CHECKING:
    from .backbone import CanonicalEventBackbone, PublishReceipt

__all__ = ["AdmissionController", "DeadLetter", "EventOperationsCoordinator", "OperationsError", "ResourceClass"]


class OperationsError(BackboneError):
    """An operational refusal of C5 (backpressure, operator gate, replay authorisation),
    distinct from an envelope ``Violation``."""


class ResourceClass(str, Enum):
    CONTROL = "CONTROL"
    INTERACTIVE = "INTERACTIVE"
    BATCH = "BATCH"
    AUDIT = "AUDIT"


NEVER_DROPPED = frozenset({ResourceClass.AUDIT})
DEFAULT_QUOTAS: Mapping[ResourceClass, int] = {
    ResourceClass.CONTROL: 64,
    ResourceClass.INTERACTIVE: 32,
    ResourceClass.BATCH: 16,
    ResourceClass.AUDIT: 64,
}


class AdmissionController:
    """Bounded in-flight admission per ``(tenant, ResourceClass)``."""

    def __init__(self, quotas: Mapping[ResourceClass, int] | None = None) -> None:
        resolved = dict(DEFAULT_QUOTAS)
        for resource_class, limit in (quotas or {}).items():
            if not isinstance(resource_class, ResourceClass):
                raise ValueError("quotas are keyed by ResourceClass")
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
                raise ValueError("a quota is a positive integer")
            resolved[resource_class] = limit
        self._quotas = resolved
        self._in_flight: dict[tuple[str, ResourceClass], int] = {}
        self._lock = threading.Lock()

    def try_admit(self, tenant: str, resource_class: ResourceClass) -> bool:
        """Count one in-flight publish; ``False`` (refused) only for a droppable class at quota."""
        key = (tenant, resource_class)
        with self._lock:
            in_flight = self._in_flight.get(key, 0)
            if in_flight >= self._quotas[resource_class] and resource_class not in NEVER_DROPPED:
                return False
            self._in_flight[key] = in_flight + 1
            return True

    def release(self, tenant: str, resource_class: ResourceClass) -> None:
        key = (tenant, resource_class)
        with self._lock:
            remaining = self._in_flight.get(key, 0) - 1
            if remaining < 0:
                raise RuntimeError("admission released more than admitted")
            if remaining:
                self._in_flight[key] = remaining
            else:
                self._in_flight.pop(key, None)

    def in_flight(self, tenant: str, resource_class: ResourceClass) -> int:
        with self._lock:
            return self._in_flight.get((tenant, resource_class), 0)


class EventOperationsCoordinator:
    """The operations surface of one ``CanonicalEventBackbone`` for one producer channel.

    ``transport_principal`` is the authenticated transport principal of the channel (ADD v1.3
    :379); every publish and every reprocess goes through the backbone admission boundary
    with it, so no check is ever bypassed."""

    def __init__(self, backbone: CanonicalEventBackbone, *, transport_principal: str) -> None:
        from .backbone import CanonicalEventBackbone

        if not isinstance(backbone, CanonicalEventBackbone):
            raise TypeError("backbone must be a CanonicalEventBackbone")
        if not isinstance(transport_principal, str) or not transport_principal:
            raise ValueError("an authenticated transport principal is required")
        self._backbone = backbone
        self._principal = transport_principal

    def publish_with_backpressure(self, signed: SignedEnvelope, *, tenant: str) -> PublishReceipt:
        """Publish under the quota of ``(tenant, ResourceClass)``; ``tenant`` must be the tenant
        of the envelope: a discordant value is never corrected (ADD v1.3 :199)."""
        if not isinstance(signed, SignedEnvelope) or tenant != signed.envelope.tenant_id:
            raise OperationsError("GOVERNED_CONTEXT_MISMATCH", "the tenant does not match the envelope")
        return self._backbone.publish(signed, transport_principal=self._principal)

    @property
    def dead_letters(self) -> tuple[DeadLetter, ...]:
        return self._backbone.dead_letters()

    def is_poisoned(self, event_id: str) -> bool:
        """``True`` while a ``POISON`` quarantine of the event is not released by an operator."""
        return self._backbone.poison_held(event_id)

    def release_for_operator_replay(self, event_id: str, *, operator: str, authority_ref: str,
                                    reason: str = "operator release after diagnosis") -> None:
        """The operator gate (LLD v1.1 :163): release every open ``POISON`` quarantine of the event."""
        held = [record for record in self._backbone.poison_records(event_id) if not record.released]
        if not held:
            raise OperationsError("NOT_POISONED", "the event is not held in the poison quarantine")
        for record in held:
            self._backbone.release_quarantine(record.quarantine_id, operator=operator, authority_ref=authority_ref,
                                              reason=reason)

    def replay(self, dead_letter: DeadLetter, *, reason: str, requested_by: str, authority_ref: str) -> PublishReceipt:
        """Reprocess a dead letter (``ReprocessAuthorized``), preserving its event ID."""
        return self._backbone.reprocess_dead_letter(
            dead_letter, reason=reason, requested_by=requested_by, authority_ref=authority_ref,
            transport_principal=self._principal,
        )
