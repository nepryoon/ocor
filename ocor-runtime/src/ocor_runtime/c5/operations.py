"""C5 admission control: quotas per tenant and priority class (LLD v1.1 :165 and :338).

"Backpressure applica quote per tenant e priority class; audit/security non vengono
eliminati" (LLD v1.1 :165); "ResourceClass (``CONTROL``, ``INTERACTIVE``, ``BATCH``,
``AUDIT``) determina quota, priority e backpressure. C6/control/audit non condividono pool
esauribile con causal batch" (LLD v1.1 :338). Each ``(tenant, ResourceClass)`` has its own
in-flight pool, so saturating one class never starves another class or another tenant.
An ``AUDIT`` publish is never refused for backpressure: it is admitted even above its quota
and only counted. Admission runs after authentication, integrity, schema and policy
checks, which therefore never get disabled under saturation (Register :406, NFR-079).
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from enum import Enum


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
