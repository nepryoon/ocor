"""C4 projector of the C3 ``canonical-state-committed`` events.

OCOR-DEV-REM-0050 (NCP-U04, NCR-C3-003). Consumes the C3 events delivered by the C5
backbone in order per aggregate, verifies schema, ontology release and GovernedContext
digest before applying, applies each commit once, and advances the watermark in the same
TypeDB transaction as the fact (LLD v1.1 §2.4 :148; ADD v1.3 §6.2 steps 4-5 :3433-3434;
Register FR-064 :188). Deduplication is on (target, branch, commit_id) and is durable: it
reads the commit order the projection records with each applied commit. The projection
is never authoritative (ADD v1.3 §6.2 step 7).

OCOR-DEV-REM-0051 (NCP-U06, NCR-C5-001): the events arrive as admitted
``canonical-ingestion-envelope:1.2`` (ADD v1.3 :531-840). The projector reads the
aggregate identity and revision from ``aggregate``, the commit from the CDC transport
``source_transaction_id``, and verifies that the envelope realises its GovernedContext
(ADD v1.3 :845) as the commit context of the payload, with the relay's transport principal
as effective principal appended to the commit actor chain (ADD v1.3 :197 and :844).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Any

from ..c5.backbone import BackboneError, CanonicalIngestionEnvelope
from ..c5.envelope import thaw
from ..kernel.canonical import canonical_bytes, canonical_digest, parse_i_json
from ..kernel.governed_context import GovernedContext, GovernedContextError
from .typedb_adapter import TypeDBAdapterError, TypeDBProjectionAdapter

CANONICAL_STATE_COMMITTED = "canonical-state-committed"
CANONICAL_STATE_COMMITTED_EVENT_TYPE = "urn:ocor:event-type:canonical-state-committed"
C3_SOURCE = "urn:ocor:source:c3-canonical-state"
BRANCH = "main"
WORLD = "urn:ocor:world:main"


class ProjectorError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def _revision(value: object, minimum: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        return None
    return value


@contextmanager
def _projection(operation: str) -> Iterator[None]:
    """Projection failures leave the projector only as ``ProjectorError``: an unreachable
    TypeDB is ``BACKEND_UNAVAILABLE``, a refused query ``BACKEND_ERROR``; the server text
    is never echoed."""
    try:
        yield
    except TypeDBAdapterError as exc:
        raise ProjectorError("BACKEND_ERROR", f"{operation}: TypeDB refused the operation") from exc
    except OSError as exc:
        raise ProjectorError("BACKEND_UNAVAILABLE", f"{operation}: TypeDB is unavailable") from exc


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
        payload: dict[str, Any] = thaw(envelope.payload)
        if (
            envelope.event_type_id != CANONICAL_STATE_COMMITTED_EVENT_TYPE
            or envelope["source"]["source_id"] != C3_SOURCE
            or envelope["world_ref"] != WORLD
            or payload.get("event_type") != CANONICAL_STATE_COMMITTED
            or payload.get("branch") != BRANCH
        ):
            raise ProjectorError("SCHEMA_VIOLATION", f"{envelope.event_id!r} is not a canonical-state-committed event")
        state = payload.get("state")
        before = _revision(payload.get("from_revision"), 0)
        revision = _revision(payload.get("to_revision"), 1)
        try:
            state_digest = canonical_digest(state) if isinstance(state, dict) else None
        except (TypeError, ValueError) as exc:
            raise ProjectorError("SCHEMA_VIOLATION", f"{envelope.event_id!r} state is not I-JSON") from exc
        if (
            state_digest is None
            or before is None
            or revision is None
            or revision != before + 1
            or revision != envelope.aggregate.get("expected_revision")
            or payload.get("commit_id") != envelope["transport"].get("source_transaction_id")
            or payload.get("aggregate_ref") != envelope.aggregate["aggregate_id"]
            or state_digest != payload.get("state_digest")
        ):
            raise ProjectorError("SCHEMA_VIOLATION", f"{envelope.event_id!r} payload does not match its envelope")
        if payload.get("ontology_release_digest") != self._release:
            raise ProjectorError("RELEASE_MISMATCH", f"{envelope.event_id!r} is not of the projected release")
        if not self._context_verified(envelope, payload):
            raise ProjectorError("GOVERNED_CONTEXT_MISMATCH", f"{envelope.event_id!r} GCS differs from its payload")
        return payload

    @staticmethod
    def _context_verified(envelope: CanonicalIngestionEnvelope, payload: dict[str, Any]) -> bool:
        """The envelope realises its GovernedContext, which is the commit context of the payload
        with the transport principal as effective principal appended to the commit actor chain."""
        try:
            commit = GovernedContext.from_mapping(payload.get("governed_context"))  # type: ignore[arg-type]
            event = envelope.governed_context()
        except (GovernedContextError, BackboneError):
            return False
        chain = commit.actor_chain
        return (
            commit.digest() == payload.get("governed_context_digest")
            and event.actor_chain[: len(chain)] == chain
            and event.actor_chain[-1] == event.effective_principal_id
            and replace(commit, effective_principal_id=event.effective_principal_id, actor_chain=event.actor_chain) == event
        )

    def _applied_revision(self, aggregate_ref: str) -> int:
        """The revision of the last commit applied for the aggregate, read back from the
        projected fact, so a restarted projector keeps the order (0 when none)."""
        with _projection("lookup"):
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
            with _projection("position"):
                position = self._projection.position(BRANCH, commit_id)
            if position is not None:
                return False
            aggregate_ref = payload["aggregate_ref"]
            applied = self._applied_revision(aggregate_ref)
            if payload["from_revision"] != applied:
                raise ProjectorError(
                    "OUT_OF_ORDER", f"{envelope.event_id!r} revision {payload['to_revision']} does not follow revision {applied}"
                )
            fact = {"commit_id": commit_id, "revision": payload["to_revision"], "state": payload["state"]}
            with _projection("apply"):
                self._projection.apply_commit(
                    fact_id=aggregate_ref, commit_id=commit_id, payload=canonical_bytes(fact).decode("utf-8")
                )
            return True
