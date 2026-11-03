"""C3 commit admission: the governed-path checks that precede every canonical commit.

OCOR-DEV-REM-0050 (NCP-U04, NCR-C3-001). Before the transaction C3 validates the C6
provenance, the Decision, the Authority, the Evidence and the bindings of the closed
command (LLD v1.1 §1.5, ``docs/OCOR_LLD_v1.1.md`` :97). ``CommitAdmission.admit`` accepts
a ``GovernedCanonicalCommitCommand`` only when (ADD v1.3
``OCOR_ADD_v1.3_APPROVED_BASELINE.md``):

- the frozen GatePackage named by ``gate_package_digest`` resolves, is produced and
  signed by C6, hashes to that digest and binds exactly the command's action instance,
  Decision, Authority, Evidence set, claim/source bindings, aggregate, expected revision,
  canonical delta, idempotency key, precondition and invariant IDs and GovernedContext
  (:342 rule 10, :2557);
- the Decision is a C6-signed ``ACCEPT`` with ``effect_class=CANONICAL_COMMIT``, not
  expired, for the same action instance and GatePackage (:342);
- the Authority is signed, inside its validity window, not revoked and coherent with the
  GatePackage, the tenant and the effective principal (:342, :3430);
- every Evidence ref resolves to a record whose retention has not expired;
- the mutation fence holds: no emergency stop, the stop epoch frozen in the GatePackage
  is still current, the ontology release of the GatePackage and of the GovernedContext is
  the active one (:3443; Register FR-138 :310).

Preconditions are evaluated on the current canonical state and invariants on the new
state inside the commit (``check_state``), so both see exactly the revision the commit
replaces (Register FR-062 :186). Precondition, invariant and GatePackage mismatches map
to ``PRECONDITION_FAILED``, ``INVARIANT_VIOLATION`` and ``GATE_PACKAGE_MISMATCH``
(ADD v1.3 :2569); an unresolvable, unsigned, expired or non-ACCEPT Decision is
``POLICY_DENIED``, an unusable Authority is ``AUTHORITY_MISSING``, an unresolvable
Evidence is ``CONTRACT_REJECTED``, a stop is ``EMERGENCY_STOP_ACTIVE`` and an inactive
release is ``RELEASE_MISMATCH`` (closed error set of ADD v1.3 :2329-2352). Nothing is
permissive by default: every port, key and binding registry is a required argument.

Governance records are DSSE-style signed: Ed25519 over the DSSE PAE of the RFC 8785
bytes of the payload, with the payload type naming the record kind.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from ..c1.signing import dsse_pae, ed25519_verify
from ..kernel.canonical import canonical_bytes, canonical_digest, parse_utc_timestamp
from ..kernel.governance import EvidenceRecord, TrustedClock
from .ports import C3Error, GovernedCanonicalCommitCommand, _freeze, _thaw

C6_PRODUCER = "urn:ocor:component:c6"
GATE_PACKAGE_PAYLOAD_TYPE = "application/vnd.ocor.c6.gate-package+json"
DECISION_PAYLOAD_TYPE = "application/vnd.ocor.c6.decision+json"
AUTHORITY_PAYLOAD_TYPE = "application/vnd.ocor.c6.authority+json"

GATE_PACKAGE_FIELDS = frozenset(
    {
        "record_type",
        "producer",
        "action_instance_id",
        "decision_ref",
        "authority_ref",
        "evidence_refs",
        "claim_source_bindings",
        "aggregate_type",
        "aggregate_ref",
        "expected_revision",
        "canonical_delta_digest",
        "idempotency_key",
        "precondition_bindings",
        "invariant_bindings",
        "governed_context_digest",
        "ontology_release_digest",
        "stop_epoch",
        "frozen_at",
    }
)
DECISION_FIELDS = frozenset(
    {
        "record_type",
        "producer",
        "decision_ref",
        "action_instance_id",
        "outcome",
        "effect_class",
        "gate_package_digest",
        "decided_at",
        "expires_at",
    }
)
AUTHORITY_FIELDS = frozenset(
    {
        "record_type",
        "producer",
        "authority_ref",
        "action_instance_id",
        "gate_package_digest",
        "tenant_id",
        "effective_principal_id",
        "not_before",
        "expires_at",
    }
)

Predicate = Callable[[Mapping[str, Any]], bool]


@dataclass(frozen=True, slots=True)
class SignedGovernanceRecord:
    """A governance record of the governed path with its detached signature."""

    payload_type: str
    payload: Mapping[str, Any]
    keyid: str
    signature: str

    def __post_init__(self) -> None:
        for name in ("payload_type", "keyid", "signature"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise C3Error("COMMIT_CONTRACT_INVALID", f"{name} is required")
        if not isinstance(self.payload, Mapping):
            raise C3Error("COMMIT_CONTRACT_INVALID", "payload must be an object")
        object.__setattr__(self, "payload", _freeze(self.payload))

    @property
    def digest(self) -> str:
        return canonical_digest(_thaw(self.payload))

    def signed_bytes(self) -> bytes:
        return dsse_pae(self.payload_type, canonical_bytes(_thaw(self.payload)))


def sign_governance_record(
    payload_type: str, payload: Mapping[str, Any], *, key: Any, keyid: str
) -> SignedGovernanceRecord:
    """Signs a record with an Ed25519 signing key (``ocor_runtime.c1.signing``)."""
    message = dsse_pae(payload_type, canonical_bytes(_thaw(payload)))
    return SignedGovernanceRecord(
        payload_type=payload_type,
        payload=payload,
        keyid=keyid,
        signature=base64.b64encode(key.sign(message)).decode("ascii"),
    )


def gate_package_payload(
    command_fields: Mapping[str, Any],
    *,
    ontology_release_digest: str,
    stop_epoch: int,
    frozen_at: str,
) -> dict[str, Any]:
    """The frozen GatePackage of a canonical commit, built by C6 from the fields the
    command will carry; its canonical digest is the command's ``gate_package_digest``."""
    return {
        "record_type": "GatePackage",
        "producer": C6_PRODUCER,
        "action_instance_id": command_fields["action_instance_id"],
        "decision_ref": command_fields["decision_ref"],
        "authority_ref": command_fields["authority_ref"],
        "evidence_refs": sorted(command_fields["evidence_refs"]),
        "claim_source_bindings": sorted(
            (dict(item) for item in command_fields["claim_source_bindings"]),
            key=lambda item: (item["claim_ref"], item["source_ref"], item["evidence_ref"]),
        ),
        "aggregate_type": command_fields["aggregate_type"],
        "aggregate_ref": command_fields["aggregate_ref"],
        "expected_revision": command_fields["expected_revision"],
        "canonical_delta_digest": canonical_digest(_thaw(command_fields["canonical_delta"])),
        "idempotency_key": command_fields["idempotency_key"],
        "precondition_bindings": sorted(command_fields["precondition_bindings"]),
        "invariant_bindings": sorted(command_fields["invariant_bindings"]),
        "governed_context_digest": command_fields["governed_context_digest"],
        "ontology_release_digest": ontology_release_digest,
        "stop_epoch": stop_epoch,
        "frozen_at": frozen_at,
    }


@runtime_checkable
class GovernedPathRecordPort(Protocol):
    """Read side of the C6 governance record store."""

    def gate_package(self, gate_package_digest: str) -> SignedGovernanceRecord | None: ...

    def decision(self, decision_ref: str) -> SignedGovernanceRecord | None: ...

    def authority(self, authority_ref: str) -> SignedGovernanceRecord | None: ...

    def authority_revoked(self, authority_ref: str) -> bool: ...

    def evidence(self, evidence_ref: str) -> EvidenceRecord | None: ...


@runtime_checkable
class MutationFencePort(Protocol):
    """Stop epoch and emergency stop (C6) and active ontology release (C1)."""

    def current_stop_epoch(self) -> int: ...

    def emergency_stop_active(self) -> bool: ...

    def active_release_digest(self) -> str: ...


@dataclass(frozen=True, slots=True)
class AdmittedCommit:
    """The admission verdict that the commit transaction re-checks on state."""

    command: GovernedCanonicalCommitCommand
    gate_package_digest: str
    decision_ref: str
    authority_ref: str
    ontology_release_digest: str
    stop_epoch: int


def _deny(reason: str, message: str) -> C3Error:
    return C3Error(reason, message)


def _instant(record: Mapping[str, Any], field: str, reason: str) -> datetime:
    value = record.get(field)
    if not isinstance(value, str):
        raise _deny(reason, f"{field} is not a UTC timestamp")
    try:
        return parse_utc_timestamp(value)
    except (TypeError, ValueError) as exc:
        raise _deny(reason, f"{field} is not a UTC timestamp") from exc


class CommitAdmission:
    """Fail-closed admission of a canonical commit command (NCR-C3-001)."""

    def __init__(
        self,
        *,
        records: GovernedPathRecordPort,
        fence: MutationFencePort,
        trusted_keys: Mapping[str, bytes],
        clock: TrustedClock,
        preconditions: Mapping[str, Predicate],
        invariants: Mapping[str, Predicate],
    ) -> None:
        if not isinstance(records, GovernedPathRecordPort):
            raise TypeError("records must implement GovernedPathRecordPort")
        if not isinstance(fence, MutationFencePort):
            raise TypeError("fence must implement MutationFencePort")
        keys = dict(trusted_keys)
        if not keys or any(not isinstance(k, str) or not isinstance(v, bytes) or len(v) != 32 for k, v in keys.items()):
            raise TypeError("trusted_keys must map key IDs to 32-byte Ed25519 public keys")
        if not callable(getattr(clock, "now", None)):
            raise TypeError("clock must implement TrustedClock")
        for name, registry in (("preconditions", preconditions), ("invariants", invariants)):
            if not isinstance(registry, Mapping) or any(not callable(item) for item in registry.values()):
                raise TypeError(f"{name} must map binding IDs to predicates")
        self._records = records
        self._fence = fence
        self._keys = keys
        self._clock = clock
        self._preconditions = dict(preconditions)
        self._invariants = dict(invariants)

    # --- signatures --------------------------------------------------------------------

    def _verified(
        self,
        record: object,
        payload_type: str,
        fields: frozenset[str],
        record_type: str,
        reason: str,
    ) -> Mapping[str, Any]:
        if not isinstance(record, SignedGovernanceRecord):
            raise _deny(reason, f"{record_type} does not resolve")
        if record.payload_type != payload_type:
            raise _deny(reason, f"{record_type} has payload type {record.payload_type!r}")
        key = self._keys.get(record.keyid)
        try:
            signature = base64.b64decode(record.signature, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise _deny(reason, f"{record_type} signature is not base64") from exc
        if key is None or not ed25519_verify(key, record.signed_bytes(), signature):
            raise _deny(reason, f"{record_type} signature is not verified by a trusted key")
        payload = record.payload
        if set(payload) != fields:
            raise _deny(reason, f"{record_type} is not a closed record")
        if payload.get("record_type") != record_type or payload.get("producer") != C6_PRODUCER:
            raise _deny(reason, f"{record_type} is not produced by C6")
        return payload

    # --- admission ---------------------------------------------------------------------

    def admit(self, command: GovernedCanonicalCommitCommand) -> AdmittedCommit:
        if not isinstance(command, GovernedCanonicalCommitCommand):
            raise _deny("COMMIT_CONTRACT_INVALID", "a GovernedCanonicalCommitCommand is required")
        now = self._clock.now()

        package_record = self._records.gate_package(command.gate_package_digest)
        package = self._verified(
            package_record, GATE_PACKAGE_PAYLOAD_TYPE, GATE_PACKAGE_FIELDS, "GatePackage", "GATE_PACKAGE_MISMATCH"
        )
        if canonical_digest(_thaw(package)) != command.gate_package_digest:
            raise _deny("GATE_PACKAGE_MISMATCH", "the GatePackage does not hash to gate_package_digest")
        expected = gate_package_payload(
            command.to_mapping(),
            ontology_release_digest=package["ontology_release_digest"],
            stop_epoch=package["stop_epoch"],
            frozen_at=package["frozen_at"],
        )
        drifted = sorted(name for name in GATE_PACKAGE_FIELDS if _thaw(package[name]) != expected[name])
        if drifted:
            raise _deny("GATE_PACKAGE_MISMATCH", f"the command differs from the frozen GatePackage: {drifted}")

        decision = self._verified(
            self._records.decision(command.decision_ref), DECISION_PAYLOAD_TYPE, DECISION_FIELDS, "Decision", "POLICY_DENIED"
        )
        if decision["decision_ref"] != command.decision_ref:
            raise _deny("POLICY_DENIED", "the Decision record names another decision")
        if decision["outcome"] != "ACCEPT" or decision["effect_class"] != "CANONICAL_COMMIT":
            raise _deny("POLICY_DENIED", "the Decision is not ACCEPT with effect_class CANONICAL_COMMIT")
        if not _instant(decision, "decided_at", "POLICY_DENIED") <= now < _instant(decision, "expires_at", "POLICY_DENIED"):
            raise _deny("POLICY_DENIED", "the Decision is not valid at commit time")
        if decision["action_instance_id"] != command.action_instance_id or decision["gate_package_digest"] != command.gate_package_digest:
            raise _deny("GATE_PACKAGE_MISMATCH", "the Decision is not bound to the frozen GatePackage")

        authority = self._verified(
            self._records.authority(command.authority_ref), AUTHORITY_PAYLOAD_TYPE, AUTHORITY_FIELDS, "Authority",
            "AUTHORITY_MISSING",
        )
        if authority["authority_ref"] != command.authority_ref:
            raise _deny("AUTHORITY_MISSING", "the Authority record names another authority")
        if self._records.authority_revoked(command.authority_ref) is not False:
            raise _deny("AUTHORITY_MISSING", "the Authority is revoked")
        if not _instant(authority, "not_before", "AUTHORITY_MISSING") <= now < _instant(authority, "expires_at", "AUTHORITY_MISSING"):
            raise _deny("AUTHORITY_MISSING", "the Authority is not valid at commit time")
        context = command.governed_context
        if (
            authority["action_instance_id"] != command.action_instance_id
            or authority["gate_package_digest"] != command.gate_package_digest
            or authority["tenant_id"] != context.tenant_id
            or authority["effective_principal_id"] != context.effective_principal_id
        ):
            raise _deny("GATE_PACKAGE_MISMATCH", "the Authority is not coherent with the frozen GatePackage")

        for evidence_ref in command.evidence_refs:
            evidence = self._records.evidence(evidence_ref)
            if not isinstance(evidence, EvidenceRecord) or evidence.evidence_id != evidence_ref:
                raise _deny("CONTRACT_REJECTED", f"evidence {evidence_ref!r} does not resolve")
            if evidence.retention_until <= now:
                raise _deny("CONTRACT_REJECTED", f"evidence {evidence_ref!r} is past its retention")

        if self._fence.emergency_stop_active() is not False:
            raise _deny("EMERGENCY_STOP_ACTIVE", "the emergency stop is active")
        stop_epoch = self._fence.current_stop_epoch()
        if isinstance(stop_epoch, bool) or not isinstance(stop_epoch, int) or stop_epoch != package["stop_epoch"]:
            raise _deny("EMERGENCY_STOP_ACTIVE", "the stop epoch changed since the GatePackage was frozen")
        active = self._fence.active_release_digest()
        if package["ontology_release_digest"] != active or context.ontology_release_digest != active:
            raise _deny("RELEASE_MISMATCH", "the ontology release of the command is not the active release")

        for binding in command.precondition_bindings:
            if binding not in self._preconditions:
                raise _deny("PRECONDITION_FAILED", f"precondition {binding!r} is not registered")
        for binding in command.invariant_bindings:
            if binding not in self._invariants:
                raise _deny("INVARIANT_VIOLATION", f"invariant {binding!r} is not registered")
        return AdmittedCommit(
            command=command,
            gate_package_digest=command.gate_package_digest,
            decision_ref=command.decision_ref,
            authority_ref=command.authority_ref,
            ontology_release_digest=active,
            stop_epoch=stop_epoch,
        )

    def check_state(
        self, admitted: AdmittedCommit, current_state: Mapping[str, Any], new_state: Mapping[str, Any]
    ) -> None:
        """Runs inside the commit, on the state the commit replaces and produces."""
        if not isinstance(admitted, AdmittedCommit):
            raise _deny("COMMIT_CONTRACT_INVALID", "an admitted commit is required")
        for binding in admitted.command.precondition_bindings:
            if self._evaluate(self._preconditions.get(binding), current_state) is not True:
                raise _deny("PRECONDITION_FAILED", f"precondition {binding!r} does not hold")
        for binding in admitted.command.invariant_bindings:
            if self._evaluate(self._invariants.get(binding), new_state) is not True:
                raise _deny("INVARIANT_VIOLATION", f"invariant {binding!r} does not hold on the new state")

    @staticmethod
    def _evaluate(predicate: Predicate | None, state: Mapping[str, Any]) -> bool:
        if predicate is None:
            return False
        try:
            return predicate(_freeze(dict(state))) is True
        except Exception:  # noqa: BLE001 -- a failing predicate is a failed binding, never a pass
            return False
