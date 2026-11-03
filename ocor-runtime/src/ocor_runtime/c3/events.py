"""The ``canonical-state-committed`` event that C3 writes in the outbox of a commit.

OCOR-DEV-REM-0050 (NCP-U04, NCR-C3-003). The payload is fixed in the commit
transaction, so the relay publishes exactly what was committed (ADD v1.3 §6.2 step 3,
``OCOR_ADD_v1.3_APPROVED_BASELINE.md`` :3432). It carries the isolation boundary --
tenant, domain, compartments, classification and purpose -- (Register FR-068 :192) and
the correlation of the governed path: event ID (the outbox event ID), Decision,
Authority and action instance, actor chain, correlation and causation (Register FR-075
:207); the release and GovernedContext digest let every projector verify release and
GCS (LLD v1.1 §2.4 :148).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .ports import C3Error, GovernedCanonicalCommitCommand, _thaw

CANONICAL_STATE_COMMITTED = "canonical-state-committed"
EVENT_VERSION = "1"


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
