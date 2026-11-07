"""Test support of OCOR-DEV-REM-0054 (NCP-U08, NCR-C6-010): the emergency stop of ADD v1.3
§5.4-§5.5 (:3343, :3351) and LLD v1.1 §4.3 (:328) and the break-glass delegation of ADD v1.3
:3347 and LLD v1.1 §4.2 (:324).

* The stop is activated by an authorised Safety Officer, increments a signed ``stop_epoch`` kept
  in a durable ``StopEpochPort`` and is read through that port; the reset needs dual control and
  the verification of the incident and of the recovery.
* The break-glass grant is a Delegation signed by the break-glass authority with a typed reason.

The keys are test keys derived from fixed labels; they exist only to prove the signatures.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from ocor_runtime.c1.signing import Ed25519SigningKey
from ocor_runtime.c2_identity import IdentityRecord
from ocor_runtime.c6.human_gate import InMemorySignerKeyring
from ocor_runtime.c6.safety import (
    BreakGlassAlertSink,
    BreakGlassAuditSink,
    BreakGlassController,
    EmergencyStopController,
    InMemoryStopEpochStore,
    PrincipalDirectory,
    RecoveryVerification,
    StopEpochPort,
    StopEpochReader,
)
from ocor_runtime.kernel.governance import TrustedClock

SAFETY_OFFICER = "urn:ocor:human:safety-officer"
INCIDENT = "urn:ocor:incident:42"
RECOVERY_EVIDENCE = "urn:sha256:" + hashlib.sha256(b"recovery verified for urn:ocor:incident:42").hexdigest()

CONTROL_PLANE = "urn:ocor:emergency-control-plane"
CONTROL_PLANE_KEYID = "emergency-control-plane-key-1"
BREAK_GLASS_AUTHORITY = "urn:ocor:break-glass-authority"
BREAK_GLASS_KEYID = "break-glass-authority-key-1"


def signing_key(label: str) -> Ed25519SigningKey:
    return Ed25519SigningKey.from_seed(hashlib.sha256(label.encode("utf-8")).digest())


CONTROL_PLANE_KEY = signing_key("ocor emergency control plane")
BREAK_GLASS_KEY = signing_key("ocor break-glass authority")


def keyring() -> InMemorySignerKeyring:
    ring = InMemorySignerKeyring()
    ring.register(CONTROL_PLANE, CONTROL_PLANE_KEYID, CONTROL_PLANE_KEY.public_key)
    ring.register(BREAK_GLASS_AUTHORITY, BREAK_GLASS_KEYID, BREAK_GLASS_KEY.public_key)
    return ring


def safety_officer_record(*, roles: str = "SAFETY_OFFICER", kind: str = "HUMAN", status: str = "ACTIVE") -> IdentityRecord:
    return IdentityRecord(
        canonical_id=SAFETY_OFFICER, attributes={"principal_kind": kind, "status": status, "roles": roles}
    )


class WithSafetyOfficer:
    """A read-only principal directory that resolves the Safety Officer and delegates every other
    principal to the directory of the test."""

    def __init__(self, directory: PrincipalDirectory | None = None, *, officer: IdentityRecord | None = None) -> None:
        self._directory = directory
        self._officer = safety_officer_record() if officer is None else officer

    def get(self, canonical_id: str) -> IdentityRecord | None:
        if canonical_id == SAFETY_OFFICER:
            return self._officer
        return None if self._directory is None else self._directory.get(canonical_id)


def stop_controller(
    directory: PrincipalDirectory | None = None, *, epochs: StopEpochPort | None = None
) -> EmergencyStopController:
    """The Emergency Control Plane over a durable stop-epoch port (in memory unless given)."""

    return EmergencyStopController(
        epochs=InMemoryStopEpochStore() if epochs is None else epochs,
        identities=WithSafetyOfficer(directory),
        signing_key=CONTROL_PLANE_KEY,
        issuer_id=CONTROL_PLANE,
        keyid=CONTROL_PLANE_KEYID,
        keyring=keyring(),
    )


def stop_reader(epochs: StopEpochPort) -> StopEpochReader:
    """A reader of the signed stop epoch on the same port, as G-DISPATCH and the C8 tool runtime
    hold it: it shares no object with the controller that activates the stop."""

    return StopEpochReader(epochs=epochs, keyring=keyring(), issuer_id=CONTROL_PLANE)


def activate(stop: EmergencyStopController, *, reason: str, at: datetime, incident_ref: str = INCIDENT):  # type: ignore[no-untyped-def]
    return stop.activate(activator=SAFETY_OFFICER, reason=reason, incident_ref=incident_ref, at=at)


def recovery(approvers: tuple[str, ...], *, incident_ref: str = INCIDENT, evidence: str = RECOVERY_EVIDENCE) -> RecoveryVerification:
    return RecoveryVerification(incident_ref=incident_ref, verified_by=approvers[0], evidence_digest=evidence)


def break_glass_controller(
    *,
    identities: PrincipalDirectory,
    stop: EmergencyStopController | StopEpochReader,
    clock: TrustedClock,
    audit: BreakGlassAuditSink,
    alerts: BreakGlassAlertSink,
) -> BreakGlassController:
    return BreakGlassController(
        identities=identities,
        stop=stop,
        clock=clock,
        audit=audit,
        alerts=alerts,
        signing_key=BREAK_GLASS_KEY,
        issuer_id=BREAK_GLASS_AUTHORITY,
        keyid=BREAK_GLASS_KEYID,
    )
