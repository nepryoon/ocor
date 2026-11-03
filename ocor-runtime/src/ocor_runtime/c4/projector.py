"""C4 projector of the C3 ``canonical-state-committed`` events.

OCOR-DEV-REM-0050 (NCP-U04, NCR-C3-003). Consumes the C3 events delivered by the C5
backbone in order per aggregate, verifies schema, ontology release and GovernedContext
digest before applying, applies each commit once, and advances the watermark in the same
TypeDB transaction as the fact (LLD v1.1 §2.4 :148; ADD v1.3 §6.2 steps 4-5 :3433-3434;
Register FR-064 :188). Deduplication is on (target, branch, commit_id) and is durable: it
reads the commit order the projection records with each applied commit. The projection
is never authoritative (ADD v1.3 §6.2 step 7).
"""

from __future__ import annotations

import threading
from typing import Any

from ..c5.backbone import CanonicalIngestionEnvelope
from ..kernel.canonical import canonical_bytes, canonical_digest, parse_i_json
from .typedb_adapter import TypeDBProjectionAdapter

CANONICAL_EVENT_SCHEMA = "urn:ocor:schema:canonical-ingestion-envelope:1"
CANONICAL_STATE_COMMITTED = "canonical-state-committed"
C3_PRODUCER = "urn:ocor:component:c3"
BRANCH = "main"


class ProjectorError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


class CanonicalStateProjector:
    """Applies canonical-state-committed events to the TypeDB projection."""

    def __init__(self, projection: TypeDBProjectionAdapter, *, release_digest: str) -> None:
        if not isinstance(projection, TypeDBProjectionAdapter):
            raise TypeError("a TypeDBProjectionAdapter is required")
        if not isinstance(release_digest, str) or not release_digest.startswith("urn:sha256:"):
            raise TypeError("release_digest must be a SHA-256 URN")
        self._projection = projection
        self._release = release_digest
        self._lock = threading.Lock()

    def _verified(self, envelope: CanonicalIngestionEnvelope) -> dict[str, Any]:
        if not isinstance(envelope, CanonicalIngestionEnvelope):
            raise ProjectorError("SCHEMA_VIOLATION", "a CanonicalIngestionEnvelope is required")
        payload = dict(envelope.payload)
        if (
            envelope.schema_ref != CANONICAL_EVENT_SCHEMA
            or envelope.event_type != CANONICAL_STATE_COMMITTED
            or envelope.producer_principal != C3_PRODUCER
            or payload.get("event_type") != CANONICAL_STATE_COMMITTED
            or payload.get("branch") != BRANCH
        ):
            raise ProjectorError("SCHEMA_VIOLATION", f"{envelope.event_id!r} is not a canonical-state-committed event")
        state = payload.get("state")
        revision = payload.get("to_revision")
        if (
            not isinstance(state, dict)
            or isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision != envelope.sequence
            or payload.get("commit_id") != envelope.source_ref
            or payload.get("aggregate_ref") != envelope.aggregate_ref
            or canonical_digest(state) != payload.get("state_digest")
        ):
            raise ProjectorError("SCHEMA_VIOLATION", f"{envelope.event_id!r} payload does not match its envelope")
        if payload.get("ontology_release_digest") != self._release:
            raise ProjectorError("RELEASE_MISMATCH", f"{envelope.event_id!r} is not of the projected release")
        if payload.get("governed_context_digest") != envelope.governed_context_digest:
            raise ProjectorError("GOVERNED_CONTEXT_MISMATCH", f"{envelope.event_id!r} GCS digest differs from its payload")
        return payload

    def _applied_revision(self, aggregate_ref: str) -> int:
        """The revision of the last commit applied for the aggregate, read back from the
        projected fact, so a restarted projector keeps the order (0 when none)."""
        found = self._projection._lookup_fact(aggregate_ref)  # noqa: SLF001 -- C4-internal read of its own fact
        if found is None:
            return 0
        try:
            fact = parse_i_json(found[1])
        except (TypeError, ValueError) as exc:
            raise ProjectorError("PROJECTION_DRIFT", f"projected fact of {aggregate_ref!r} is not canonical JSON") from exc
        revision = fact.get("revision") if isinstance(fact, dict) else None
        if isinstance(revision, bool) or not isinstance(revision, int) or revision <= 0:
            raise ProjectorError("PROJECTION_DRIFT", f"projected fact of {aggregate_ref!r} has no revision")
        return revision

    def apply(self, envelope: CanonicalIngestionEnvelope) -> bool:
        """Returns ``True`` when the commit was applied, ``False`` for a duplicate."""
        payload = self._verified(envelope)
        commit_id = payload["commit_id"]
        with self._lock:
            if self._projection.position(BRANCH, commit_id) is not None:
                return False
            applied = self._applied_revision(envelope.aggregate_ref)
            if payload["from_revision"] != applied:
                raise ProjectorError(
                    "OUT_OF_ORDER", f"{envelope.event_id!r} revision {envelope.sequence} does not follow revision {applied}"
                )
            fact = {"commit_id": commit_id, "revision": payload["to_revision"], "state": payload["state"]}
            self._projection.apply_commit(
                fact_id=envelope.aggregate_ref, commit_id=commit_id, payload=canonical_bytes(fact).decode("utf-8")
            )
            return True
