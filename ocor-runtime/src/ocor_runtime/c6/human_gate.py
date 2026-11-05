"""C6 -- Human Gate decision approval with dual control.

Supplies the real quorum/separation-of-duties/signature/scope/TTL
logic the Human Gate transitions OCOR-DEV-0042's sealed
``ocor_runtime.c6.fsm`` table declares (``ACT-T06``/``ACT-T07``/
``ACT-T08``/``ACT-T09a``/``ACT-T09b``, "Human Gate richiesto" /
"approvato" / "non approvato") actually need. ``HumanGateCoordinator``
produces the unsigned ``Approval`` disposition of OCOR-DEV-0030 (defined
here and re-exported by ``ocor_runtime.c6.engine``); since NCR-C6-001 the
engine no longer admits it: it admits only the ``ApprovalSet`` of
``ApprovalGate``.

``HumanGateCoordinator`` re-reads identity attributes at every validation
and uses its boundary-owned ``TrustedClock``. Request timestamps and
``GateSignature.role`` do not confer authority. The optional ``at``
argument is retained for source compatibility only and never decides
validity. Signature content digests are not cryptographic authentication;
the registry provisioning boundary remains the open REM-0031 risk.

``HumanGateCoordinator`` and its caller-supplied ``ApprovalPolicy`` are retained for their
current consumers. The action path uses ``ApprovalGate`` and ``DecisionGate`` (NCR-C6-001,
NCR-C6-008): the approval requirement is derived from the risk class
(``approval_requirement``, ADD v1.3 :3298-3307, :3338), never supplied by the caller; every
Approval is an Ed25519 signature of a human approver bound to proposal digest, revision,
ontology release and expiry, no approver equals the proposer, and the ``ApprovalSet`` is
signed by the gate and for ``R3_HIGH_IMPACT`` expires ten minutes after the second signature,
without renewal (ADD v1.3 :3334). ``G-DECISION`` admits only a Decision ``ACCEPT`` signed by
the competent Authority, unexpired and bounded to effect, target, parameters and validity
window (ADD v1.3 :2849-2850, LLD v1.1 :254). A replayed Approval, ApprovalSet or Decision is
rejected (NFR-005).
"""

from __future__ import annotations

import base64
import binascii
import re
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

from ..c1.signing import Ed25519SigningKey, ed25519_verify
from ..c2_identity import IdentityRecord, IdentityRegistry
from ..c3_store import require_aware
from ..errors import OCORError
from ..kernel.canonical import canonical_digest
from ..kernel.governance import RiskClass, TrustedClock
from . import records


class HumanGateError(OCORError):
    """A Human Gate resolution or revalidation was refused.
    ``reason_code`` identifies why (QUORUM_NOT_MET,
    MISSING_REQUIRED_ROLE), mirroring the reason-code pattern already
    established by the other retained C1-C8 components this session.
    Deliberately generic: it never discloses which individual
    signature was excluded (expired, scope-mismatched, unresolved,
    excluded, or shadowed by separation of duties), the same
    anti-disclosure posture OCOR-DEV-0034's marking gate already
    established."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


@dataclass(frozen=True, slots=True)
class Approval:
    """The unsigned Human Gate disposition of OCOR-DEV-0030 (``ACT-T08``/``ACT-T09a``/``ACT-T09b``)
    that ``HumanGateCoordinator`` produces for its retained consumers. It carries no signature
    bound to proposal digest, revision, release and expiry, so ``G-APPROVAL`` of the action path
    does not admit it (ADD v1.3 :2849, NCR-C6-001)."""

    action_id: str
    approver: str
    approved: bool
    approved_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.approved_at, field="approved_at")
        if not self.approver:
            raise ValueError("an Approval requires an approver")


@dataclass(frozen=True, slots=True)
class ApprovalPolicy:
    """The dual-control policy a risk-bearing action's Human Gate must
    satisfy: at least ``minimum_signatories`` distinct real humans
    total, with every one of ``required_roles`` covered by its own
    distinct human -- no single human ever credited toward two
    different required roles (separation of duties) -- and the
    action's own proposer (and any other explicitly excluded
    principal) never counted at all."""

    required_roles: frozenset[str]
    minimum_signatories: int
    ttl: timedelta
    excluded_principal_id: str | None = None

    def __post_init__(self) -> None:
        if self.minimum_signatories < 1:
            raise ValueError("minimum_signatories must be at least one")
        if self.ttl <= timedelta(0):
            raise ValueError("ttl must be a positive duration")


@dataclass(frozen=True, slots=True)
class GateSignature:
    """One real signatory's act of signing, bound to the exact action,
    role and scope it was given for. ``integrity_digest`` is a
    content-addressed binding of every semantic field via the shared,
    sealed RFC 8785 kernel canonicalizer -- an honest, tamper-evident
    commitment, not a real asymmetric cryptographic signature (no PKI
    exists in this delivery's scope, the same honesty already
    established by OCOR-DEV-0028's unsigned ``signature_envelope_ref``
    placeholder)."""

    action_id: str
    principal_id: str
    role: str
    scope: str
    signed_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.signed_at, field="signed_at")
        if not self.action_id:
            raise ValueError("a GateSignature requires an action_id")
        if not self.principal_id:
            raise ValueError("a GateSignature requires a principal_id")
        if not self.role:
            raise ValueError("a GateSignature requires a role")
        if not self.scope:
            raise ValueError("a GateSignature requires a scope")

    @property
    def integrity_digest(self) -> str:
        return canonical_digest(
            {
                "action_id": self.action_id,
                "principal_id": self.principal_id,
                "role": self.role,
                "scope": self.scope,
                "signed_at": self.signed_at.isoformat(),
            }
        )


_ROLE_TOKEN = re.compile(r"[A-Z][A-Z0-9_]*(?::\S+)?")


def _active_human_roles(record: IdentityRecord | None) -> frozenset[str] | None:
    """Q1 PoC interpretation, read only from the registry's scalar attributes.

    None means unusable; an empty role set is distinct and may satisfy a
    reset quorum, for which ADD 5.4 names no specific approver roles.
    """
    if record is None:
        return None
    attributes = record.attributes
    if attributes.get("principal_kind") != "HUMAN" or attributes.get("status") != "ACTIVE":
        return None
    raw = attributes.get("roles")
    if not isinstance(raw, str):
        return None
    tokens = raw.split(" ") if raw else []
    if tokens != sorted(set(tokens)) or any(_ROLE_TOKEN.fullmatch(token) is None for token in tokens):
        return None
    return frozenset(tokens)


class HumanGateCoordinator:
    def __init__(self, *, identities: IdentityRegistry, clock: TrustedClock) -> None:
        self._identities = identities
        self._clock = clock

    def validate(
        self,
        *,
        action_id: str,
        proposer_id: str,
        policy: ApprovalPolicy,
        signatures: Iterable[GateSignature],
        scope: str,
        at: datetime | None = None,
        control_check: Callable[[], None] | None = None,
    ) -> Approval:
        signature_set = tuple(signatures)
        instant = require_aware(self._clock.now(), field="trusted clock")
        excluded = {proposer_id}
        if policy.excluded_principal_id:
            excluded.add(policy.excluded_principal_id)

        valid_principals: set[str] = set()
        role_candidates: dict[str, set[str]] = {role: set() for role in policy.required_roles}

        for signature in signature_set:
            principal = signature.principal_id
            if signature.action_id != action_id:
                continue
            if principal in excluded:
                continue
            roles = _active_human_roles(self._identities.get(principal))
            if roles is None or signature.role not in roles:
                continue
            if signature.scope != scope:
                continue
            if not timedelta(0) <= instant - signature.signed_at < policy.ttl:
                continue

            valid_principals.add(principal)

            if signature.role in policy.required_roles:
                role_candidates[signature.role].add(principal)

        if len(valid_principals) < policy.minimum_signatories:
            raise HumanGateError(
                "QUORUM_NOT_MET",
                f"{len(valid_principals)} distinct valid signatory(ies), {policy.minimum_signatories} required",
            )
        # A distinct human per required role, independent of signature order.
        # A first-fit assignment can falsely reject a valid quorum when one
        # human holds both roles and another can cover only one of them.
        role_by_principal: dict[str, str] = {}

        def assign(role: str, visited: set[str]) -> bool:
            for principal in sorted(role_candidates[role]):
                if principal in visited:
                    continue
                visited.add(principal)
                previous = role_by_principal.get(principal)
                if previous is None or assign(previous, visited):
                    role_by_principal[principal] = role
                    return True
            return False

        for role in sorted(policy.required_roles):
            assign(role, set())
        missing_roles = policy.required_roles - set(role_by_principal.values())
        if missing_roles:
            raise HumanGateError("MISSING_REQUIRED_ROLE", f"no distinct valid signatory for: {sorted(missing_roles)}")

        if control_check is not None:
            control_check()
            # Policy I/O may advance time or change identity authority. Only
            # the final fresh validation may publish an Approval. The frozen
            # tuple also supports single-pass signature iterators safely.
            return self.validate(
                action_id=action_id, proposer_id=proposer_id, policy=policy,
                signatures=signature_set, scope=scope,
            )

        approver = ",".join(sorted(valid_principals))
        return Approval(action_id=action_id, approver=approver, approved=True, approved_at=instant)


DOMAIN_APPROVER = "DOMAIN_APPROVER"
NATIONAL_APPROVER = "NATIONAL_APPROVER"
R3_APPROVAL_SET_VALIDITY = timedelta(minutes=10)


class ApprovalGateError(OCORError):
    """``G-APPROVAL`` or ``G-DECISION`` refused. ``reason_code`` is one of
    NO_MUTATION_ADMITTED, SIGNATURE_INVALID, SCOPE_MISMATCH, SELF_APPROVAL,
    APPROVER_NOT_AUTHORIZED, APPROVAL_EXPIRED, APPROVAL_REPLAYED, QUORUM_NOT_MET,
    APPROVAL_SET_INVALID, GATE_PACKAGE_DIGEST_MISMATCH, DECISION_SIGNATURE_INVALID,
    DECISION_NOT_COMPETENT, DECISION_REJECTED, DECISION_SCOPE_MISMATCH, DECISION_EXPIRED,
    DECISION_REPLAYED."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


@dataclass(frozen=True, slots=True)
class ApprovalRequirement:
    """The approval obligation of a risk class (ADD v1.3 :3298-3307, :3338)."""

    risk_class: RiskClass
    mutation_admitted: bool
    quorum: int
    required_roles: frozenset[str]
    set_validity_after_last_signature: timedelta | None


def gate_disposition(risk_class: object, *, canonical_target: bool) -> str:
    """The Human Gate disposition of ``CONTROL_CHECK`` (LLD v1.1 :267-268): ``REQUIRED`` when
    the risk class requires an Approval (``ACT-T06``); ``NOT_REQUIRED`` only when the gate is not
    required and the target is not canonical (``ACT-T07``). A class that admits no mutation on a
    canonical target, or no valid risk classification, denies the request (ADD v1.3 :3298-3303)."""

    requirement = approval_requirement(risk_class)
    if requirement.mutation_admitted:
        return "REQUIRED"
    if canonical_target is not False:
        raise ApprovalGateError(
            "NO_MUTATION_ADMITTED", f"{requirement.risk_class.name} admits no mutation of a canonical target"
        )
    return "NOT_REQUIRED"


def approval_requirement(risk_class: object) -> ApprovalRequirement:
    """Derive the approval obligation from the risk class; without a valid risk class the
    mutative request is denied (ADD v1.3 :3298)."""

    if isinstance(risk_class, bool) or not isinstance(risk_class, int):
        raise ApprovalGateError("NO_MUTATION_ADMITTED", "no valid risk classification")
    try:
        risk = RiskClass(risk_class)
    except ValueError as error:
        raise ApprovalGateError("NO_MUTATION_ADMITTED", "no valid risk classification") from error
    if risk is RiskClass.R3_HIGH_IMPACT:
        return ApprovalRequirement(risk, True, 2, frozenset({DOMAIN_APPROVER, NATIONAL_APPROVER}), R3_APPROVAL_SET_VALIDITY)
    if risk is RiskClass.R2_CONTROLLED:
        return ApprovalRequirement(risk, True, 1, frozenset(), None)
    return ApprovalRequirement(risk, False, 0, frozenset(), None)


@runtime_checkable
class SignerKeyring(Protocol):
    """Public Ed25519 keys of the principals that may sign (approvers, Authorities, the gate)."""

    def public_key(self, principal_id: str, keyid: str) -> bytes | None: ...


class InMemorySignerKeyring:
    def __init__(self) -> None:
        self._keys: dict[tuple[str, str], bytes] = {}
        self._lock = threading.Lock()

    def register(self, principal_id: str, keyid: str, public_key: bytes) -> None:
        if not principal_id or not keyid or not isinstance(public_key, bytes) or len(public_key) != 32:
            raise ValueError("a principal, a keyid and a 32-byte Ed25519 public key are required")
        with self._lock:
            known = self._keys.setdefault((principal_id, keyid), public_key)
        if known != public_key:
            raise ValueError("the key of a principal and keyid is immutable")

    def public_key(self, principal_id: str, keyid: str) -> bytes | None:
        with self._lock:
            return self._keys.get((principal_id, keyid))


@runtime_checkable
class ActiveReleasePort(Protocol):
    def active_release_digest(self) -> str: ...


@runtime_checkable
class ReplayLedger(Protocol):
    """Single use of Approvals, ApprovalSets and Decisions: ``claim`` records every key
    atomically when none was claimed before and returns the keys already claimed."""

    def claim(self, keys: tuple[str, ...]) -> tuple[str, ...]: ...


class InMemoryReplayLedger:
    def __init__(self) -> None:
        self._claimed: set[str] = set()
        self._lock = threading.Lock()

    def claim(self, keys: tuple[str, ...]) -> tuple[str, ...]:
        with self._lock:
            already = tuple(key for key in keys if key in self._claimed)
            if not already:
                self._claimed.update(keys)
            return already


def signature_valid(keyring: SignerKeyring, principal_id: str, record: records.SignedRecord) -> bool:
    """Whether ``record`` carries a valid Ed25519 signature of ``principal_id`` under its keyid."""

    public_key = keyring.public_key(principal_id, record.keyid)
    if not isinstance(public_key, bytes) or len(public_key) != 32:
        return False
    try:
        raw = base64.b64decode(record.signature, validate=True)
    except (binascii.Error, ValueError):
        return False
    return ed25519_verify(public_key, record.signed_bytes(), raw)


def _sign(key: Ed25519SigningKey, unsigned: records.SignedRecord) -> str:
    return base64.b64encode(key.sign(unsigned.signed_bytes())).decode("ascii")


def signed_with[R: records.SignedRecord](key: Ed25519SigningKey, unsigned: R) -> R:
    """``unsigned`` with the Ed25519 signature of ``key`` over its signed bytes."""

    return replace(unsigned, signature=_sign(key, unsigned))  # type: ignore[type-var]


_PLACEHOLDER_SIGNATURE = records.PLACEHOLDER_SIGNATURE


def sign_approval(
    key: Ed25519SigningKey,
    *,
    keyid: str,
    approval_id: str,
    proposal: records.ActionProposal,
    release_digest: str,
    approver_id: str,
    role: str,
    signed_at: datetime,
    expires_at: datetime,
) -> records.Approval:
    """The approver's signature of an Approval bound to proposal digest, revision, release and expiry."""

    unsigned = records.Approval(
        approval_id=approval_id,
        action_instance_id=proposal.action_instance_id,
        proposal_digest=proposal.digest(),
        revision=proposal.expected_revision,
        release_digest=release_digest,
        approver_id=approver_id,
        role=role,
        keyid=keyid,
        signed_at=signed_at,
        expires_at=expires_at,
        signature=_PLACEHOLDER_SIGNATURE,
    )
    return _replace_signature(unsigned, _sign(key, unsigned))


def sign_decision(
    key: Ed25519SigningKey,
    *,
    keyid: str,
    decision_id: str,
    authority_id: str,
    proposal: records.ActionProposal,
    gate_package_digest: str,
    outcome: str,
    rationale: str,
    valid_from: datetime,
    valid_until: datetime,
    decided_at: datetime,
) -> records.Decision:
    """The Authority's signature of a Decision bounded to the proposal's effect, target and parameters."""

    unsigned = records.Decision(
        decision_id=decision_id,
        action_instance_id=proposal.action_instance_id,
        gate_package_digest=gate_package_digest,
        outcome=outcome,
        rationale=rationale,
        effect_class=proposal.effect_class,
        target_ref=proposal.target_ref,
        parameters_digest=proposal.parameters_digest,
        valid_from=valid_from,
        valid_until=valid_until,
        authority_id=authority_id,
        keyid=keyid,
        decided_at=decided_at,
        signature=_PLACEHOLDER_SIGNATURE,
    )
    return _replace_signature(unsigned, _sign(key, unsigned))


def _replace_signature[R: (records.Approval, records.ApprovalSet, records.Decision)](record: R, signature: str) -> R:
    return replace(record, signature=signature)


class ApprovalGate:
    """``G-APPROVAL`` of the action path: quorum, SoD, signatures, scope and TTL derived from
    the risk class of the proposal. The admitted quorum becomes an ApprovalSet signed by the
    gate; each Approval enters one ApprovalSet only."""

    def __init__(
        self,
        *,
        identities: IdentityRegistry,
        approvers: SignerKeyring,
        releases: ActiveReleasePort,
        clock: TrustedClock,
        signing_key: Ed25519SigningKey,
        gate_id: str,
        keyid: str,
        ledger: ReplayLedger | None = None,
    ) -> None:
        if not isinstance(identities, IdentityRegistry):
            raise TypeError("identities must be the IdentityRegistry")
        if not isinstance(approvers, SignerKeyring):
            raise TypeError("approvers must implement SignerKeyring")
        if not isinstance(releases, ActiveReleasePort):
            raise TypeError("releases must implement ActiveReleasePort")
        if not callable(getattr(clock, "now", None)):
            raise TypeError("clock must implement TrustedClock")
        if not isinstance(signing_key, Ed25519SigningKey):
            raise TypeError("signing_key must be the gate's Ed25519 signing key")
        if not gate_id or not keyid:
            raise ValueError("gate_id and keyid are required")
        self._identities = identities
        self._approvers = approvers
        self._releases = releases
        self._clock = clock
        self._key = signing_key
        self.gate_id = gate_id
        self._keyid = keyid
        self._ledger: ReplayLedger = ledger if ledger is not None else InMemoryReplayLedger()

    @property
    def public_key(self) -> bytes:
        return self._key.public_key

    def _now(self) -> datetime:
        return require_aware(self._clock.now(), field="trusted clock")

    def _check(self, approval: object, proposal: records.ActionProposal, requirement: ApprovalRequirement,
               release: str, now: datetime) -> records.Approval:
        if not isinstance(approval, records.Approval):
            raise ApprovalGateError("SIGNATURE_INVALID", "an Approval is a signed Approval record")
        if not signature_valid(self._approvers, approval.approver_id, approval):
            raise ApprovalGateError("SIGNATURE_INVALID", "the Approval signature does not verify")
        if (
            approval.action_instance_id != proposal.action_instance_id
            or approval.proposal_digest != proposal.digest()
            or approval.revision != proposal.expected_revision
            or approval.release_digest != release
        ):
            raise ApprovalGateError("SCOPE_MISMATCH", "the Approval is bound to another proposal, revision or release")
        if approval.approver_id == proposal.proposer_id:
            raise ApprovalGateError("SELF_APPROVAL", "an approver coincides with the proposer")
        roles = _active_human_roles(self._identities.get(approval.approver_id))
        if roles is None or approval.role not in roles or (
            requirement.required_roles and approval.role not in requirement.required_roles
        ):
            raise ApprovalGateError("APPROVER_NOT_AUTHORIZED", "the approver is not an active human holding the role")
        if not approval.signed_at <= now < approval.expires_at:
            raise ApprovalGateError("APPROVAL_EXPIRED", "the Approval is expired or not yet valid")
        return approval

    def assemble(
        self, proposal: records.ActionProposal, approvals: Iterable[records.Approval], *, approval_set_id: str
    ) -> records.ApprovalSet:
        if not isinstance(proposal, records.ActionProposal):
            raise ApprovalGateError("SCOPE_MISMATCH", "a G-APPROVAL evaluates an ActionProposal")
        requirement = approval_requirement(proposal.risk_class)
        if not requirement.mutation_admitted:
            raise ApprovalGateError("NO_MUTATION_ADMITTED", f"{proposal.risk_class.name} admits no mutation")
        presented = tuple(approvals)
        now = self._now()
        release = self._releases.active_release_digest()
        admitted = tuple(self._check(item, proposal, requirement, release, now) for item in presented)
        principals = {item.approver_id for item in admitted}
        roles = {item.role for item in admitted}
        if (
            len(admitted) != requirement.quorum
            or len(principals) != requirement.quorum
            or not requirement.required_roles <= roles
        ):
            raise ApprovalGateError("QUORUM_NOT_MET", "the quorum of distinct approvers and roles is not met")
        completed_at = max(item.signed_at for item in admitted)
        expires_at = min(item.expires_at for item in admitted)
        if requirement.set_validity_after_last_signature is not None:
            expires_at = min(expires_at, completed_at + requirement.set_validity_after_last_signature)
        if now >= expires_at:
            raise ApprovalGateError("APPROVAL_EXPIRED", "the ApprovalSet would already be expired")
        unsigned = records.ApprovalSet(
            approval_set_id=approval_set_id,
            action_instance_id=proposal.action_instance_id,
            proposal_digest=proposal.digest(),
            risk_class=proposal.risk_class,
            approval_digests=tuple(item.digest() for item in admitted),
            approver_ids=tuple(sorted(principals)),
            completed_at=completed_at,
            expires_at=expires_at,
            keyid=self._keyid,
            signature=_PLACEHOLDER_SIGNATURE,
        )
        if self._ledger.claim(tuple(f"approval:{item.approval_id}" for item in admitted)):
            raise ApprovalGateError("APPROVAL_REPLAYED", "an Approval was already used in an ApprovalSet")
        return _replace_signature(unsigned, _sign(self._key, unsigned))

    def verify_set(self, approval_set: object, proposal: records.ActionProposal) -> records.ApprovalSet:
        if not isinstance(approval_set, records.ApprovalSet) or approval_set.keyid != self._keyid:
            raise ApprovalGateError("APPROVAL_SET_INVALID", "an ApprovalSet signed by this gate is required")
        public_key = self._key.public_key
        try:
            raw = base64.b64decode(approval_set.signature, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ApprovalGateError("APPROVAL_SET_INVALID", "the ApprovalSet signature does not verify") from error
        if not ed25519_verify(public_key, approval_set.signed_bytes(), raw):
            raise ApprovalGateError("APPROVAL_SET_INVALID", "the ApprovalSet signature does not verify")
        if (
            approval_set.action_instance_id != proposal.action_instance_id
            or approval_set.proposal_digest != proposal.digest()
            or approval_set.risk_class != proposal.risk_class
        ):
            raise ApprovalGateError("APPROVAL_SET_INVALID", "the ApprovalSet is bound to another proposal")
        if not approval_set.completed_at <= self._now() < approval_set.expires_at:
            raise ApprovalGateError("APPROVAL_EXPIRED", "the ApprovalSet is expired")
        return approval_set


class DecisionGate:
    """``G-DECISION`` of the action path: only a Decision ``ACCEPT`` signed by the competent
    Authority, unexpired, bounded to the proposal's effect, target and parameters and to the
    approved validity window, on the GatePackage whose digest the gate recomputes."""

    def __init__(
        self,
        *,
        authorities: SignerKeyring,
        approval_gate: ApprovalGate,
        clock: TrustedClock,
        ledger: ReplayLedger | None = None,
    ) -> None:
        if not isinstance(authorities, SignerKeyring):
            raise TypeError("authorities must implement SignerKeyring")
        if not isinstance(approval_gate, ApprovalGate):
            raise TypeError("approval_gate must be the ApprovalGate")
        if not callable(getattr(clock, "now", None)):
            raise TypeError("clock must implement TrustedClock")
        self._authorities = authorities
        self._approval_gate = approval_gate
        self._clock = clock
        self._ledger: ReplayLedger = ledger if ledger is not None else InMemoryReplayLedger()

    def _verify(
        self,
        decision: object,
        *,
        proposal: records.ActionProposal,
        package: records.GatePackage,
        package_digest: str,
        approval_set: records.ApprovalSet,
    ) -> tuple[records.Decision, records.ApprovalSet]:
        if not isinstance(proposal, records.ActionProposal):
            raise ApprovalGateError("DECISION_SCOPE_MISMATCH", "a G-DECISION evaluates an ActionProposal")
        if not approval_requirement(proposal.risk_class).mutation_admitted:
            raise ApprovalGateError("NO_MUTATION_ADMITTED", f"{proposal.risk_class.name} admits no mutation")
        try:
            digest = records.verify_gate_package(package, package_digest)
        except records.C6RecordError as error:
            raise ApprovalGateError("GATE_PACKAGE_DIGEST_MISMATCH", str(error)) from error
        if package.proposal_digest != proposal.digest() or package.action_instance_id != proposal.action_instance_id:
            raise ApprovalGateError("GATE_PACKAGE_DIGEST_MISMATCH", "the GatePackage freezes another proposal")
        admitted_set = self._approval_gate.verify_set(approval_set, proposal)
        if package.approval_set_digest != admitted_set.digest():
            raise ApprovalGateError("APPROVAL_SET_INVALID", "the GatePackage freezes another ApprovalSet")
        if not isinstance(decision, records.Decision):
            raise ApprovalGateError("DECISION_SIGNATURE_INVALID", "a G-DECISION admits only a signed Decision")
        if not signature_valid(self._authorities, decision.authority_id, decision):
            raise ApprovalGateError("DECISION_SIGNATURE_INVALID", "the Decision signature does not verify")
        if decision.authority_id != package.authority_ref:
            raise ApprovalGateError("DECISION_NOT_COMPETENT", "the Decision is not signed by the competent Authority")
        if decision.outcome != "ACCEPT":
            raise ApprovalGateError("DECISION_REJECTED", f"the Authority did not accept the action: {decision.rationale}")
        if (
            decision.gate_package_digest != digest
            or decision.action_instance_id != proposal.action_instance_id
            or decision.effect_class != proposal.effect_class
            or decision.target_ref != proposal.target_ref
            or decision.parameters_digest != proposal.parameters_digest
            or decision.valid_from < package.valid_from
            or decision.valid_until > min(package.valid_until, admitted_set.expires_at)
        ):
            raise ApprovalGateError("DECISION_SCOPE_MISMATCH", "the Decision exceeds the approved effect, target, parameters or window")
        now = require_aware(self._clock.now(), field="trusted clock")
        if not decision.valid_from <= now < decision.valid_until:
            raise ApprovalGateError("DECISION_EXPIRED", "the Decision is expired or not yet valid")
        return decision, admitted_set

    def admit(
        self,
        decision: object,
        *,
        proposal: records.ActionProposal,
        package: records.GatePackage,
        package_digest: str,
        approval_set: records.ApprovalSet,
    ) -> records.Decision:
        admitted, admitted_set = self._verify(
            decision, proposal=proposal, package=package, package_digest=package_digest, approval_set=approval_set
        )
        already = self._ledger.claim((f"decision:{admitted.decision_id}", f"approval-set:{admitted_set.approval_set_id}"))
        if f"decision:{admitted.decision_id}" in already:
            raise ApprovalGateError("DECISION_REPLAYED", "the Decision was already admitted")
        if already:
            raise ApprovalGateError("APPROVAL_REPLAYED", "the ApprovalSet was already used by another Decision")
        return admitted

    def reverify(
        self,
        decision: object,
        *,
        proposal: records.ActionProposal,
        package: records.GatePackage,
        package_digest: str,
        approval_set: records.ApprovalSet,
    ) -> records.Decision:
        """Every check of ``admit`` except the single-use claim, for the retry of the action
        instance the Decision was already admitted for: the Decision, its ApprovalSet and its
        GatePackage must still verify and be unexpired (ADD v1.3 :3334, expiry re-runs the gate)."""

        verified, _ = self._verify(
            decision, proposal=proposal, package=package, package_digest=package_digest, approval_set=approval_set
        )
        return verified
