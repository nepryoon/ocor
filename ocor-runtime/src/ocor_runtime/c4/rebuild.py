"""C4 -- rebuild and drift reconciliation.

Implements LLD v1.1 section 2.4's ``ProjectionDriftDetector``: rebuilds
a projection fact from the canonical commit
(``ocor_runtime.c3.service.PostgresC3Service``, OCOR-DEV-0029, reused
unmodified through its own sealed public ``read`` method) and compares
its digest against what the live projection
(``ocor_runtime.c4.typedb_adapter.TypeDBProjectionAdapter``,
OCOR-DEV-0037, reused unmodified) currently serves -- through that
adapter's own sealed ``ProjectionReadPort.read`` method, never a
private/internal shortcut -- BEFORE ever overwriting it. A mismatch is
real drift: the divergent projection is quarantined rather than
silently repaired, and every subsequent read for that aggregate is
blocked (``PROJECTION_QUARANTINED``) until an explicit, successful
rebuild reconciles it: this task's own negative acceptance criterion,
made structural.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass

from ..c2.planner import served_from_watermark
from ..c2.ports import C2Error, ConsistencyMode, ConsistencyRequirement, NamedQueryRequest, NamedQueryResponse
from ..c3.service import PostgresC3Service
from ..c4.typedb_adapter import TypeDBProjectionAdapter
from ..kernel.governed_context import GovernedContext

_SYSTEM_DIGEST = "urn:sha256:" + "0" * 64


class DriftError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


@dataclass(frozen=True, slots=True)
class RebuildReport:
    aggregate_ref: str
    canonical_commit: str
    drift_detected: bool
    quarantined: bool


def _peek_request(aggregate_ref: str, release_digest: str) -> NamedQueryRequest:
    """A synthetic, deterministic system request used only to drive the
    sealed ``ProjectionReadPort.read`` for a BEST_AVAILABLE peek --
    never used to serve an end-user response. It is bound to the release the
    projection declares, which the projection serves (FR-148, Register :331)."""
    context = GovernedContext.from_mapping(
        {
            "tenant_id": "urn:ocor:tenant:system",
            "organization_id": "urn:ocor:org:system",
            "domain_id": "urn:ocor:domain:system",
            "compartments": ["urn:ocor:compartment:system"],
            "classification_marking_ref": _SYSTEM_DIGEST,
            "purpose": "c4-drift-reconciliation",
            "effective_principal_id": "urn:ocor:principal:c4-drift-detector",
            "actor_chain": ["urn:ocor:principal:c4-drift-detector"],
            "ontology_release_digest": release_digest,
            "policy_bundle_digest": _SYSTEM_DIGEST,
            "correlation_id": "018f2f95-01b2-7cc3-8d4e-000000000000",
        }
    )
    return NamedQueryRequest(
        request_id="018f2f95-01b2-7cc3-8d4e-000000000000",
        contract_id="urn:ocor:contract:named-query:c4-drift-reconciliation",
        contract_version="1.0.0",
        contract_digest=_SYSTEM_DIGEST,
        parameters={"fact_id": aggregate_ref},
        governed_context=context,
        governed_context_digest=context.digest(),
        consistency=ConsistencyRequirement(mode=ConsistencyMode.BEST_AVAILABLE),
    )


def _digest_of(value: str) -> str:
    return "urn:sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


class ProjectionDriftDetector:
    """Rebuilds a sample from the canonical log and reconciles it
    against the live projection; a divergent projection is quarantined
    rather than repaired, and quarantine blocks every subsequent read
    for that aggregate until a fresh rebuild reconciles cleanly."""

    def __init__(self, service: PostgresC3Service, projection: TypeDBProjectionAdapter) -> None:
        self._service = service
        self._projection = projection
        self._quarantined: set[str] = set()
        self._lock = threading.Lock()

    def is_quarantined(self, aggregate_ref: str) -> bool:
        with self._lock:
            return aggregate_ref in self._quarantined

    def _peek_served_payload_digest(self, aggregate_ref: str) -> str | None:
        try:
            response = self._projection.read(_peek_request(aggregate_ref, self._projection.release_digest))
        except C2Error as error:
            if error.reason_code == "POLICY_DENIED":
                return None
            if error.reason_code == "PROJECTION_NOT_READY":
                # an unreachable projection is the typed fail-closed PROJECTION_NOT_READY
                # (NCR-C4-003; contract :486-491; LLD v1.1 :346)
                raise DriftError("PROJECTION_NOT_READY", str(error)) from error
            raise DriftError("BACKEND_ERROR", str(error)) from error
        return response.result_digest

    def rebuild(self, *, tenant_id: str, aggregate_type: str, aggregate_ref: str) -> RebuildReport:
        canonical = self._service.read(tenant_id, aggregate_type, aggregate_ref)
        if canonical is None:
            raise DriftError("CANONICAL_NOT_FOUND", f"no canonical commit exists for {aggregate_ref!r}")
        expected_digest = canonical.state_digest
        expected_served_digest = _digest_of(expected_digest)

        served_digest = self._peek_served_payload_digest(aggregate_ref)
        if served_digest is not None and served_digest != expected_served_digest:
            with self._lock:
                self._quarantined.add(aggregate_ref)
            return RebuildReport(
                aggregate_ref=aggregate_ref,
                canonical_commit=canonical.commit_id,
                drift_detected=True,
                quarantined=True,
            )

        self._projection.apply_commit(fact_id=aggregate_ref, commit_id=canonical.commit_id, payload=expected_digest)
        with self._lock:
            self._quarantined.discard(aggregate_ref)
        return RebuildReport(
            aggregate_ref=aggregate_ref,
            canonical_commit=canonical.commit_id,
            drift_detected=False,
            quarantined=False,
        )

    def read_if_healthy(self, aggregate_ref: str, request: NamedQueryRequest) -> NamedQueryResponse:
        """The task's own negative acceptance criterion made
        executable: a quarantined, divergent projection is never
        served, regardless of what the request's own consistency mode
        would otherwise allow."""
        if self.is_quarantined(aggregate_ref):
            # a quarantined projection is not ready to serve (LLD v1.1 :350); the Problem
            # carries what the projection currently serves (contract :472-479).
            watermark = self._projection.current("urn:ocor:projection:c4-typedb", "main")
            raise C2Error(
                "PROJECTION_NOT_READY",
                f"{aggregate_ref!r} is quarantined pending reconciliation",
                served=served_from_watermark(watermark, request),
            )
        return self._projection.read(request)
