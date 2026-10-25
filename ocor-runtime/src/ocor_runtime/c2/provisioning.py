"""C2 — authenticated and authorised IdentityRegistry provisioning boundary.

OCOR-DEV-REM-0031 (PO decision REM-0024-IDENTITY-REGISTRY-WRITER-AUTHORITY,
2026-10-14).  A record is provisioned only for a writer authenticated by the
identity port and authorised by the policy port for ``identity.provision`` on
the record's namespaced resource.  The boundary is distinct from break-glass
grant/authorize and from approval signatures: it never consults them and they
never consult it.

Order of checks, every one fail-closed and leaving the registry unchanged:

1. structural request validation;
2. writer authentication (identity port);
3. self-attribution: no identifier of the record may name the writer or any
   actor of its authenticated chain;
4. the writer must not itself be a registered principal (requester, approver
   or any other record);
5. no update: neither the canonical identifier nor any alias may already be
   bound in the registry;
6. policy decision (policy port), bound to the exact request; only ``PERMIT``
   provisions, every other effect is a denial;
7. checks 4 and 5 are repeated under the registry lock immediately before the
   write, so a concurrent writer cannot be overwritten or slip in.

The identity-record schema and the reserved Q1 attribute convention
(``principal_kind``, ``status``, ``roles``) are unchanged: the boundary
stores the record exactly as given.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from ..c2_identity import IdentityRecord, IdentityRegistry, normalize_identifier
from ..errors import OCORError
from ..kernel.governed_context import GovernedContext
from ..security.ports import (
    AuthenticatedPrincipal,
    IdentityProviderPort,
    IdentityRequest,
    PolicyDecision,
    PolicyDecisionPort,
    PolicyEffect,
    PolicyRequest,
    SecurityControlError,
)

PROVISIONING_ACTION = "identity.provision"
PROVISIONING_RESOURCE_PREFIX = "urn:ocor:identity-provisioning:"

# Causes that mean the authority could not answer, as opposed to an answer
# that rejects the writer or the request.
_UNAVAILABLE_CAUSES = frozenset({
    "SERVICE_UNAVAILABLE",
    "IDENTITY_UNAVAILABLE",
    "POLICY_UNAVAILABLE",
    "STALE_BUNDLE",
    "POLICY_BUNDLE_WINDOW_INVALID",
    "WORKLOAD_IDENTITY_UNAVAILABLE",
    "WORKLOAD_IDENTITY_EXPIRED",
})
_AUTHORITY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/+-]*")


class IdentityProvisioningDenied(OCORError, PermissionError):
    """A provisioning request was refused; the registry is unchanged."""

    def __init__(
        self,
        reason_code: str,
        message: str,
        *,
        correlation_id: str | None = None,
        cause_reason_code: str | None = None,
    ) -> None:
        super().__init__(f"{reason_code}: correlation_id={correlation_id or 'none'} {message}")
        self.reason_code = reason_code
        self.correlation_id = correlation_id
        self.cause_reason_code = cause_reason_code


@dataclass(frozen=True, slots=True)
class ProvisioningReceipt:
    record: IdentityRecord
    writer_principal_id: str
    decision_id: str
    policy_bundle_digest: str
    governed_context_digest: str
    correlation_id: str
    provisioned_at: datetime


def provisioning_resource(canonical_id: str) -> str:
    if not isinstance(canonical_id, str) or not canonical_id.strip():
        raise ValueError("canonical_id must be a non-empty string")
    return PROVISIONING_RESOURCE_PREFIX + canonical_id


def provisioning_policy_rego(authorities: Iterable[str]) -> str:
    """Render the governed, self-contained provisioning rule set to be signed.

    Only the listed authority principals may provision, never on a resource
    naming themselves, never through delegation and never for another
    effective principal.  Authority identifiers are restricted to a safe
    character set so they cannot alter the policy source.
    """

    names = list(authorities)
    if not names:
        raise ValueError("at least one provisioning authority is required")
    for name in names:
        if not isinstance(name, str) or _AUTHORITY_ID.fullmatch(name) is None:
            raise ValueError(f"unsafe provisioning authority identifier {name!r}")
    literals = ", ".join(json.dumps(name) for name in sorted(set(names)))
    return (
        "package ocor.control_plane\n\n"
        "default allow := false\n\n"
        f"provisioning_authorities := {{{literals}}}\n\n"
        "allow if {\n"
        f"    input.action == {json.dumps(PROVISIONING_ACTION)}\n"
        f"    startswith(input.resource, {json.dumps(PROVISIONING_RESOURCE_PREFIX)})\n"
        f"    input.resource != concat(\"\", [{json.dumps(PROVISIONING_RESOURCE_PREFIX)}, "
        "input.principal_id])\n"
        "    provisioning_authorities[input.principal_id]\n"
        "    input.effective_principal_id == input.principal_id\n"
        "    input.actor_chain == [input.principal_id]\n"
        "    count(input.delegation_grant_ids) == 0\n"
        "    input.capability == null\n"
        "}\n"
    )


class IdentityProvisioningBoundary:
    """The only runtime path that admits a record on behalf of a writer."""

    def __init__(
        self,
        registry: IdentityRegistry,
        *,
        identity: IdentityProviderPort,
        policy: PolicyDecisionPort,
        audience: str,
    ) -> None:
        if not isinstance(registry, IdentityRegistry):
            raise TypeError("registry must be an IdentityRegistry")
        if not isinstance(audience, str) or not audience:
            raise ValueError("audience must be a non-empty string")
        self._registry = registry
        self._identity = identity
        self._policy = policy
        self._audience = audience

    def provision(
        self,
        record: IdentityRecord,
        *,
        credential_ref: str,
        governed_context: GovernedContext,
    ) -> ProvisioningReceipt:
        if not isinstance(governed_context, GovernedContext):
            raise IdentityProvisioningDenied(
                "PROVISIONING_REQUEST_INVALID", "a GovernedContext is required"
            )
        correlation_id = governed_context.correlation_id
        if not isinstance(record, IdentityRecord):
            raise IdentityProvisioningDenied(
                "PROVISIONING_REQUEST_INVALID",
                "only an IdentityRecord can be provisioned",
                correlation_id=correlation_id,
            )
        try:
            identifiers = {
                normalize_identifier(item) for item in (record.canonical_id, *record.aliases)
            }
        except ValueError as exc:
            raise IdentityProvisioningDenied(
                "PROVISIONING_REQUEST_INVALID",
                "record identifiers are invalid",
                correlation_id=correlation_id,
            ) from exc
        try:
            identity_request = IdentityRequest(credential_ref, self._audience, correlation_id)
        except SecurityControlError as exc:
            raise IdentityProvisioningDenied(
                "PROVISIONING_REQUEST_INVALID",
                "invalid credential reference",
                correlation_id=correlation_id,
                cause_reason_code=exc.reason_code,
            ) from exc

        writer = self._authenticate(identity_request, correlation_id)
        actors = {normalize_identifier(actor) for actor in (writer.principal_id, *writer.actor_chain)}
        if actors & identifiers:
            raise IdentityProvisioningDenied(
                "PROVISIONING_SELF_ATTRIBUTION",
                "the record names its own writer",
                correlation_id=correlation_id,
            )
        self._require_unregistered_writer(actors, correlation_id)
        self._require_new_identifiers(record, correlation_id)

        decision = self._decide(writer, record, governed_context, correlation_id)

        with self._registry._lock:
            self._require_unregistered_writer(actors, correlation_id)
            self._require_new_identifiers(record, correlation_id)
            stored = self._registry.register(record)
        return ProvisioningReceipt(
            record=stored,
            writer_principal_id=writer.principal_id,
            decision_id=decision.decision_id,
            policy_bundle_digest=decision.policy_bundle_digest,
            governed_context_digest=decision.governed_context_digest,
            correlation_id=correlation_id,
            provisioned_at=datetime.now(UTC),
        )

    def _authenticate(self, request: IdentityRequest, correlation_id: str) -> AuthenticatedPrincipal:
        try:
            principal = self._identity.authenticate(request)
            if not isinstance(principal, AuthenticatedPrincipal):
                raise SecurityControlError("IDENTITY_REJECTED", "identity port returned no principal")
            return principal.require_valid(at=datetime.now(UTC))
        except SecurityControlError as exc:
            reason = (
                "PROVISIONING_AUTHORITY_UNAVAILABLE"
                if exc.reason_code in _UNAVAILABLE_CAUSES
                else "PROVISIONING_WRITER_UNAUTHENTICATED"
            )
            raise IdentityProvisioningDenied(
                reason,
                "writer authentication failed",
                correlation_id=correlation_id,
                cause_reason_code=exc.reason_code,
            ) from exc
        except Exception as exc:  # any other failure is an unavailable authority
            raise IdentityProvisioningDenied(
                "PROVISIONING_AUTHORITY_UNAVAILABLE",
                f"identity authority failed: {type(exc).__name__}",
                correlation_id=correlation_id,
            ) from exc

    def _decide(
        self,
        writer: AuthenticatedPrincipal,
        record: IdentityRecord,
        governed_context: GovernedContext,
        correlation_id: str,
    ) -> PolicyDecision:
        try:
            request = PolicyRequest(
                principal=writer,
                action=PROVISIONING_ACTION,
                resource=provisioning_resource(record.canonical_id),
                governed_context=governed_context,
                governed_context_digest=governed_context.digest(),
                at=datetime.now(UTC),
            )
            decision = self._policy.evaluate(request)
            if not isinstance(decision, PolicyDecision):
                raise SecurityControlError("POLICY_DECISION_INVALID", "policy port returned no decision")
            decision.verify(request, at=datetime.now(UTC))
        except SecurityControlError as exc:
            reason = (
                "PROVISIONING_AUTHORITY_UNAVAILABLE"
                if exc.reason_code in _UNAVAILABLE_CAUSES
                else "PROVISIONING_AUTHORITY_REJECTED"
            )
            raise IdentityProvisioningDenied(
                reason,
                "provisioning policy did not produce a valid decision",
                correlation_id=correlation_id,
                cause_reason_code=exc.reason_code,
            ) from exc
        except Exception as exc:  # any other failure is an unavailable authority
            raise IdentityProvisioningDenied(
                "PROVISIONING_AUTHORITY_UNAVAILABLE",
                f"policy authority failed: {type(exc).__name__}",
                correlation_id=correlation_id,
            ) from exc
        if decision.effect is not PolicyEffect.PERMIT:
            raise IdentityProvisioningDenied(
                "PROVISIONING_POLICY_DENIED",
                f"policy effect {decision.effect.value}",
                correlation_id=correlation_id,
            )
        return decision

    def _require_unregistered_writer(self, actors: set[str], correlation_id: str) -> None:
        if any(self._registry.candidates(actor) for actor in actors):
            raise IdentityProvisioningDenied(
                "PROVISIONING_WRITER_IS_REGISTERED_PRINCIPAL",
                "a registered principal cannot provision identities",
                correlation_id=correlation_id,
            )

    def _require_new_identifiers(self, record: IdentityRecord, correlation_id: str) -> None:
        if self._registry.get(record.canonical_id) is not None or any(
            self._registry.candidates(item) for item in (record.canonical_id, *record.aliases)
        ):
            raise IdentityProvisioningDenied(
                "PROVISIONING_UPDATE_DENIED",
                "existing identities and bound identifiers cannot be provisioned again",
                correlation_id=correlation_id,
            )
