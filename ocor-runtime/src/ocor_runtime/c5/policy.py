"""C5 policy port: publish, per-delivery and replay/reprocess decisions.

ADD v1.3 :379-381 (ingestion, subscription, delivery and replay are policy enforcement
points of C5), LLD v1.1 :160-165 (``POLICY_DENIED`` -> audit and non-disclosing
quarantine; replay does not bypass policy). The port is vendor-neutral; OPA owns the
decisions in production. Anything but a ``PolicyDecision`` that allows is a denial.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason_code: str


@runtime_checkable
class C5Policy(Protocol):
    def authorize_publish(self, principal: str, envelope: Any) -> PolicyDecision: ...

    def authorize_delivery(self, principal: str, subscription_id: str, envelope: Any) -> PolicyDecision: ...

    def authorize_replay(self, principal: str, request: Any) -> PolicyDecision: ...


def permits(decision: object) -> bool:
    """Fail closed: only a well-formed allowing ``PolicyDecision`` permits."""
    return isinstance(decision, PolicyDecision) and decision.allowed is True
