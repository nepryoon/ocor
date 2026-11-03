"""The ``canonical-state-committed`` event that C3 writes in the outbox of a commit.

OCOR-DEV-REM-0050 (NCP-U04, NCR-C3-003). The payload is fixed in the commit
transaction, so the relay publishes exactly what was committed (ADD v1.3 §6.2 step 3,
``OCOR_ADD_v1.3_APPROVED_BASELINE.md`` :3432). It carries the isolation boundary --
tenant, domain, compartments, classification and purpose -- (Register FR-068 :192) and
the correlation of the governed path: event ID (the outbox event ID), Decision,
Authority and action instance, actor chain, correlation and causation (Register FR-075
:207); the release and GovernedContext digest let every projector verify release and
GCS (LLD v1.1 §2.4 :148).

OCOR-DEV-REM-0051 (NCP-U06, NCR-C5-001): the payload also carries the complete
``GovernedContext`` of the commit, so the relay can build a ``canonical-ingestion-envelope:1.2``
that realises it integrally (ADD v1.3 :845) and every projector can verify the commit
context digest. ``CANONICAL_STATE_COMMITTED_SCHEMA`` is the content-addressed JSON Schema
2020-12 of the payload, against which C5 validates it a second time (ADD v1.3 :529).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .ports import C3Error, GovernedCanonicalCommitCommand, _thaw

CANONICAL_STATE_COMMITTED = "canonical-state-committed"
EVENT_VERSION = "1"
CANONICAL_STATE_COMMITTED_EVENT_TYPE = "urn:ocor:event-type:canonical-state-committed"
CANONICAL_STATE_COMMITTED_SCHEMA_ID = "urn:ocor:schema:canonical-state-committed"
CANONICAL_STATE_COMMITTED_SCHEMA_VERSION = "1.0.0"

_TEXT: dict[str, Any] = {"type": "string", "minLength": 1}
_DIGEST: dict[str, Any] = {"type": "string", "pattern": "^urn:sha256:[0-9a-f]{64}$"}
_TEXT_SET: dict[str, Any] = {"type": "array", "minItems": 1, "uniqueItems": True, "items": _TEXT}
_GOVERNED_CONTEXT: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "tenant_id", "organization_id", "domain_id", "compartments", "classification_marking_ref", "purpose",
        "effective_principal_id", "actor_chain", "ontology_release_digest", "policy_bundle_digest", "correlation_id",
    ],
    "properties": {
        "tenant_id": _TEXT,
        "organization_id": _TEXT,
        "domain_id": _TEXT,
        "compartments": _TEXT_SET,
        "classification_marking_ref": _DIGEST,
        "purpose": _TEXT,
        "effective_principal_id": _TEXT,
        "actor_chain": _TEXT_SET,
        "ontology_release_digest": _DIGEST,
        "policy_bundle_digest": _DIGEST,
        "correlation_id": _TEXT,
    },
}
CANONICAL_STATE_COMMITTED_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": CANONICAL_STATE_COMMITTED_SCHEMA_ID,
    "title": "OCOR C3 canonical-state-committed event payload",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "event_type", "commit_id", "command_id", "action_instance_id", "tenant_id", "aggregate_type", "aggregate_ref",
        "from_revision", "to_revision", "state", "state_digest", "decision_ref", "authority_ref", "evidence_refs",
        "gate_package_digest", "governed_context_digest", "ontology_release_digest", "boundary", "actor_chain",
        "correlation_id", "causation_id", "branch", "governed_context",
    ],
    "properties": {
        "event_type": {"const": CANONICAL_STATE_COMMITTED},
        "commit_id": _TEXT,
        "command_id": _TEXT,
        "action_instance_id": _TEXT,
        "tenant_id": _TEXT,
        "aggregate_type": _TEXT,
        "aggregate_ref": _TEXT,
        "from_revision": {"type": "integer", "minimum": 0},
        "to_revision": {"type": "integer", "minimum": 1},
        "state": {"type": "object"},
        "state_digest": _DIGEST,
        "decision_ref": _TEXT,
        "authority_ref": _TEXT,
        "evidence_refs": {"type": "array", "items": _TEXT},
        "gate_package_digest": _DIGEST,
        "governed_context_digest": _DIGEST,
        "ontology_release_digest": _DIGEST,
        "boundary": {
            "type": "object",
            "additionalProperties": False,
            "required": ["tenant_id", "domain_id", "compartments", "classification_marking_ref", "purpose"],
            "properties": {
                "tenant_id": _TEXT,
                "domain_id": _TEXT,
                "compartments": _TEXT_SET,
                "classification_marking_ref": _DIGEST,
                "purpose": _TEXT,
            },
        },
        "actor_chain": _TEXT_SET,
        "correlation_id": _TEXT,
        "causation_id": _TEXT,
        "branch": {"const": "main"},
        "governed_context": _GOVERNED_CONTEXT,
    },
}


def canonical_event_payload(
    command: GovernedCanonicalCommitCommand,
    *,
    commit_id: str,
    from_revision: int,
    to_revision: int,
    state: Mapping[str, Any],
    state_digest: str,
) -> dict[str, Any]:
    context = command.governed_context
    return {
        "event_type": CANONICAL_STATE_COMMITTED,
        "commit_id": commit_id,
        "command_id": command.command_id,
        "action_instance_id": command.action_instance_id,
        "tenant_id": context.tenant_id,
        "aggregate_type": command.aggregate_type,
        "aggregate_ref": command.aggregate_ref,
        "from_revision": from_revision,
        "to_revision": to_revision,
        "state": _thaw(state),
        "state_digest": state_digest,
        "decision_ref": command.decision_ref,
        "authority_ref": command.authority_ref,
        "evidence_refs": list(command.evidence_refs),
        "gate_package_digest": command.gate_package_digest,
        "governed_context_digest": command.governed_context_digest,
        "ontology_release_digest": context.ontology_release_digest,
        "boundary": {
            "tenant_id": context.tenant_id,
            "domain_id": context.domain_id,
            "compartments": list(context.compartments),
            "classification_marking_ref": context.classification_marking_ref,
            "purpose": context.purpose,
        },
        "actor_chain": list(context.actor_chain),
        "correlation_id": context.correlation_id,
        "causation_id": command.action_instance_id,
        "branch": command.branch,
        "governed_context": context.to_mapping(),
    }


DELIVERY_OUTCOMES = frozenset({"ACKNOWLEDGED", "FAILED"})


@dataclass(frozen=True, slots=True)
class DeliveryAttempt:
    """An operational delivery record of one outbox entry, separate from the immutable
    entry itself (ADD v1.3 §2.3 :293)."""

    event_id: str
    attempt_no: int
    outcome: str
    writer_epoch: int | None
    recorded_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id:
            raise C3Error("COMMIT_CONTRACT_INVALID", "event_id is required")
        if isinstance(self.attempt_no, bool) or not isinstance(self.attempt_no, int) or self.attempt_no <= 0:
            raise C3Error("COMMIT_CONTRACT_INVALID", "attempt_no must be positive")
        if self.outcome not in DELIVERY_OUTCOMES:
            raise C3Error("COMMIT_CONTRACT_INVALID", f"unknown delivery outcome {self.outcome!r}")
        if self.outcome == "ACKNOWLEDGED" and (
            isinstance(self.writer_epoch, bool) or not isinstance(self.writer_epoch, int) or self.writer_epoch <= 0
        ):
            raise C3Error("COMMIT_CONTRACT_INVALID", "an acknowledgement carries the writer epoch")
        if not isinstance(self.recorded_at, datetime) or self.recorded_at.utcoffset() is None:
            raise C3Error("COMMIT_CONTRACT_INVALID", "recorded_at must be timezone-aware")
