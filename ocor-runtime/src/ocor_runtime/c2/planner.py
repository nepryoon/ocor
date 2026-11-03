"""C2 -- policy-filtered planning: consistency and watermarks.

Implements the smallest contract-compliant slice of LLD v1.1 section
2.2's Unified Semantic Gateway algorithm step 3 ("valuta policy/
authority prima della query") combined with step 4's consistency
selection: a plan is computed entirely from the sealed
``PolicyDecisionPort`` (OCOR-DEV-0012/0034, reused unmodified) and
``WatermarkPort`` (OCOR-DEV-0012, reused unmodified) -- the real,
potentially expensive or disclosing backend data query
(``ProjectionReadPort.read``) is never issued to compute a plan. A
policy denial is decided before the watermark is ever consulted; a
watermark that does not satisfy the requested consistency yields
``PROJECTION_NOT_READY`` with the real, observable watermark that was
checked -- never a silent downgrade to ``BEST_AVAILABLE``, and never a
query against the actual backend data.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .ports import (
    C2Error,
    CommitOrderingPort,
    ConsistencyMode,
    NamedQueryRequest,
    PolicyDecisionPort,
    ServedContext,
    Watermark,
    WatermarkPort,
    commit_reached,
)

PERMIT = "PERMIT"
POLL_INTERVAL_S = 0.05


@dataclass(frozen=True, slots=True)
class ConsistencyPlan:
    """The outcome of planning: the requester's own required commit (or
    ``None`` for ``BEST_AVAILABLE``) alongside the real watermark that
    was consulted to produce it, so a caller can always show its work
    rather than trust a bare boolean."""

    required_commit: str | None
    observed_watermark: Watermark


def served_from_watermark(watermark: Watermark, request: NamedQueryRequest) -> ServedContext:
    """The served context of an observed watermark (NFR-024, Register :180)."""

    staleness = max(0, int((datetime.now(UTC) - watermark.observed_at).total_seconds() * 1000))
    return ServedContext(
        branch=watermark.branch,
        ontology_release_digest=watermark.ontology_release_digest,
        canonical_commit=watermark.canonical_commit,
        projection_watermark=watermark.canonical_commit,
        staleness_ms=staleness,
        governed_context_digest=request.governed_context_digest,
        policy_bundle_digest=request.governed_context.policy_bundle_digest,
    )


class ConsistencyPlanner:
    """Plans whether a policy-permitted request's requested consistency
    can be honored, using only the sealed ``PolicyDecisionPort`` and
    ``WatermarkPort`` -- never the actual projection data query. Policy
    is evaluated first: an unregistered or otherwise denied query never
    even reaches the watermark check, let alone the backend.

    Ordering and bounded wait (FR-057, Register :179; LLD v1.1 :126; ADD v1.3 :1361):
    ``AT_LEAST_COMMIT(c, t)`` is satisfied by any watermark at or beyond ``c`` on the
    branch (``commit_ordering``) and, while behind, polls the watermark for at most
    ``wait_timeout_ms`` before ``PROJECTION_NOT_READY``; ``EXACT_AT_COMMIT(c)`` waits
    the same bound for ``c`` to land and is never served by a later commit."""

    def __init__(
        self,
        *,
        policy: PolicyDecisionPort,
        watermark_port: WatermarkPort,
        projection_id: str,
        branch: str,
        commit_ordering: CommitOrderingPort | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._policy = policy
        self._watermark_port = watermark_port
        self._projection_id = projection_id
        self._branch = branch
        self._ordering = commit_ordering
        self._monotonic = monotonic
        self._sleep = sleep

    def _satisfied(self, mode: ConsistencyMode, observed: str, required: str) -> bool:
        if mode is ConsistencyMode.EXACT_AT_COMMIT:
            return observed == required
        return commit_reached(self._ordering, self._branch, observed, required)

    def _beyond(self, observed: str, required: str) -> bool:
        return observed != required and commit_reached(self._ordering, self._branch, observed, required)

    def plan(self, request: NamedQueryRequest) -> ConsistencyPlan:
        decision = self._policy.decide(request)
        if decision != PERMIT:
            raise C2Error("POLICY_DENIED", "named query is not a registered, authorized contract")

        observed = self._watermark_port.current(self._projection_id, self._branch)
        consistency = request.consistency
        if consistency.mode is ConsistencyMode.BEST_AVAILABLE:
            return ConsistencyPlan(required_commit=None, observed_watermark=observed)

        required_commit = consistency.required_commit
        assert required_commit is not None  # guaranteed by ConsistencyRequirement
        deadline = self._monotonic() + consistency.wait_timeout_ms / 1000
        while not self._satisfied(consistency.mode, observed.canonical_commit, required_commit):
            exact_overtaken = consistency.mode is ConsistencyMode.EXACT_AT_COMMIT and self._beyond(
                observed.canonical_commit, required_commit
            )
            remaining = deadline - self._monotonic()
            if exact_overtaken or remaining <= 0:
                raise C2Error(
                    "PROJECTION_NOT_READY",
                    f"watermark {observed.canonical_commit!r} does not satisfy required commit {required_commit!r}",
                    served=served_from_watermark(observed, request),
                )
            self._sleep(min(POLL_INTERVAL_S, remaining))
            observed = self._watermark_port.current(self._projection_id, self._branch)
        return ConsistencyPlan(required_commit=required_commit, observed_watermark=observed)
