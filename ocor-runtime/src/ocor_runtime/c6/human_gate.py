"""C6 -- Human Gate decision approval with dual control.

Supplies the real quorum/separation-of-duties/signature/scope/TTL
logic the Human Gate transitions OCOR-DEV-0042's sealed
``ocor_runtime.c6.fsm`` table declares (``ACT-T06``/``ACT-T07``/
``ACT-T08``/``ACT-T09a``/``ACT-T09b``, "Human Gate richiesto" /
"approvato" / "non approvato") actually need, and produces the exact
same sealed ``ocor_runtime.c6.engine.Approval`` record
(OCOR-DEV-0030, reused unmodified through its own public constructor)
``GovernedActionEngine.execute`` already accepts -- no change to
either sealed file.

``HumanGateCoordinator`` re-reads identity attributes at every validation
and uses its boundary-owned ``TrustedClock``. Request timestamps and
``GateSignature.role`` do not confer authority. The optional ``at``
argument is retained for source compatibility only and never decides
validity. Signature content digests are not cryptographic authentication;
the registry provisioning boundary remains the open REM-0031 risk.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..c2_identity import IdentityRecord, IdentityRegistry
from ..c3_store import require_aware
from ..errors import OCORError
from ..kernel.canonical import canonical_digest
from ..kernel.governance import TrustedClock
from .engine import Approval


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
