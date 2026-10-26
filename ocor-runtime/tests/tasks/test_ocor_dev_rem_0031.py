"""OCOR-DEV-REM-0031: authenticated and authorised IdentityRegistry provisioning
boundary (PO decision REM-0024-IDENTITY-REGISTRY-WRITER-AUTHORITY of 2026-10-14).

A record enters the registry through ``IdentityProvisioningBoundary`` only if
its writer is authenticated by real Keycloak and authorised by real OPA with a
signed, self-contained bundle. The boundary is distinct from break-glass
grant/authorize and from approval signatures. It denies, for the right reason:

* a hostile first writer (authenticated but not a provisioning authority);
* an unauthenticated writer;
* self-attribution (the record names the writer itself);
* a writer that is itself a registered principal (requester or approver);
* any update of an existing record or of an already bound identifier;
* an unavailable or unverifiable authority (identity or policy), fail-closed.

Every negative case also proves the registry is unchanged. Real backends come
from the sealed OCOR-DEV-0048 mTLS fixtures, imported unmodified; stub ports
are used only for local failure handling (non-PERMIT effects, drifted
decisions, races), never as qualifying backend evidence. The identity-record
schema and the reserved Q1 attribute convention are unchanged.
"""

from __future__ import annotations

import importlib.util
import json
import secrets
import subprocess
import sys
import time
import urllib.parse
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from ocor_runtime.c2.provisioning import (
    PROVISIONING_ACTION,
    PROVISIONING_RESOURCE_PREFIX,
    IdentityProvisioningBoundary,
    IdentityProvisioningDenied,
    ProvisioningReceipt,
    provisioning_policy_rego,
    provisioning_resource,
)
from ocor_runtime.c2_identity import (
    PRIVILEGED_RECORD_REASON_CODE,
    RESERVED_PRINCIPAL_ATTRIBUTES,
    IdentityRecord,
    IdentityRegistrationDenied,
    IdentityRegistry,
    ResolutionStatus,
    identify_or_abstain,
)
from ocor_runtime.c6.human_gate import ApprovalPolicy, GateSignature, HumanGateCoordinator, HumanGateError
from ocor_runtime.errors import IdentityConflictError
from ocor_runtime.kernel.governance import InMemoryTrustedClock
from ocor_runtime.kernel.governed_context import GovernedContext
from ocor_runtime.security.control_plane import (
    KeycloakIdentityProvider,
    OpaPolicyDecisionProvider,
    SpireWorkloadIdentityProvider,
)
from ocor_runtime.security.ports import (
    AuthenticatedPrincipal,
    ControlName,
    ControlStatus,
    IdentityRequest,
    PolicyDecision,
    PolicyEffect,
    PolicyRequest,
    SecurityControlError,
)

_M0048_PATH = Path(__file__).resolve().parent / "test_ocor_dev_0048.py"
_SPEC = importlib.util.spec_from_file_location("ocor_dev_0048_fixtures_for_rem0031", _M0048_PATH)
assert _SPEC is not None and _SPEC.loader is not None
m0048 = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = m0048
_SPEC.loader.exec_module(m0048)

# Real-backend fixtures and helpers of the sealed OCOR-DEV-0048 module, reused unmodified.
env = m0048.env
live_stack = m0048.live_stack
admin_token = m0048.admin_token
principals = m0048.principals

fault_inject = m0048.fault_inject
REPOSITORY_ROOT = m0048.REPOSITORY_ROOT
SERVICE_URLS = m0048.SERVICE_URLS
KC = m0048.KC
REALM = m0048.REALM
CLIENT_ID = m0048.CLIENT_ID
POLICY_ID = m0048.POLICY_ID
HOSTILE_USERNAME = m0048.USERNAME
HOSTILE_PASSWORD = m0048.USER_PWD
AUDIENCE = "account"

PROVISIONER_USERNAME = "registry-provisioner-rem0031"
# Generated per session, never persisted: a disposable local credential.
_PROVISIONER_PASSWORD = secrets.token_urlsafe(24)

NEW_HUMAN = "urn:ocor:human:rem0031-new-approver"


def _q1(*roles: str, kind: str = "HUMAN", status: str = "ACTIVE") -> dict[str, object]:
    return {"principal_kind": kind, "status": status, "roles": " ".join(sorted(roles))}


def _record(canonical_id: str = NEW_HUMAN, *aliases: str, **attributes: object) -> IdentityRecord:
    return IdentityRecord(
        canonical_id=canonical_id,
        aliases=frozenset(aliases),
        attributes=attributes or _q1("SECURITY_DUTY_OFFICER"),
    )


def _snapshot(registry: IdentityRegistry) -> tuple[tuple[IdentityRecord, ...], dict[str, tuple[str, ...]]]:
    records = registry.all_records()
    identifiers = {
        identifier: registry.candidates(identifier)
        for record in records
        for identifier in (record.canonical_id, *record.aliases)
    }
    return records, identifiers


# --------------------------------------------------------------------------- #
# Real backend fixtures: a provisioning-authority user in real Keycloak and a
# signed provisioning bundle installed in real OPA over mTLS.
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def provisioner_user(admin_token: str, principals: None) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    status, body = m0048._http(
        "GET",
        f"{KC}/admin/realms/{REALM}/users?username={urllib.parse.quote(PROVISIONER_USERNAME)}&exact=true",
        headers=headers,
    )
    assert status == 200, f"user lookup: HTTP {status} {body}"
    users = json.loads(body)
    if not users:
        status, body = m0048._http(
            "POST",
            f"{KC}/admin/realms/{REALM}/users",
            headers={**headers, "Content-Type": "application/json"},
            body=json.dumps({
                "username": PROVISIONER_USERNAME,
                "enabled": True,
                "firstName": "Registry",
                "lastName": "Provisioner",
                "email": f"{PROVISIONER_USERNAME}@ocor.test",
                "emailVerified": True,
            }),
        )
        assert status in (200, 201), f"create user: HTTP {status} {body}"
        status, body = m0048._http(
            "GET",
            f"{KC}/admin/realms/{REALM}/users?username={urllib.parse.quote(PROVISIONER_USERNAME)}&exact=true",
            headers=headers,
        )
        users = json.loads(body)
    uid = users[0]["id"]
    status, body = m0048._http(
        "PUT",
        f"{KC}/admin/realms/{REALM}/users/{uid}/reset-password",
        headers={**headers, "Content-Type": "application/json"},
        body=json.dumps({"type": "password", "value": _PROVISIONER_PASSWORD, "temporary": False}),
    )
    assert status == 204, f"reset password: HTTP {status} {body}"


def _control_plane_server_material() -> dict[str, str]:
    """Server-side TLS material of the control-plane SVID, selected by SPIFFE ID.

    The agent may still deliver a temporary SVID of another service registered
    by an earlier test (OCOR-DEV-0048 peer-identity cases); the first SVID is
    therefore never assumed to be the control-plane one.
    """
    deadline = time.monotonic() + 30
    while True:
        completed = subprocess.run(
            ["docker", "exec", m0048.SPIRE_AGENT_CONTAINER, "/opt/spire/bin/spire-agent",
             "api", "fetch", "x509", "-socketPath", m0048.SPIRE_SOCKET, "-output", "json"],
            capture_output=True, timeout=30, check=False,
        )
        assert completed.returncode == 0, completed.stderr.decode()
        svids = json.loads(completed.stdout.decode()).get("svids") or []
        svid = next((item for item in svids if item.get("spiffe_id") == m0048.EXPECTED_SPIFFE_ID), None)
        if svid is not None:
            break
        assert time.monotonic() < deadline, "control-plane SVID was not delivered within the bound"
        time.sleep(0.5)
    chain = m0048._split_der_chain(m0048._b64_decode(str(svid["x509_svid"])))
    return {
        "cert_pem": "".join(m0048._der_to_pem(der, "CERTIFICATE") for der in chain),
        "key_pem": m0048._der_to_pem(m0048._b64_decode(str(svid["x509_svid_key"])), "PRIVATE KEY"),
        "ca_pem": m0048._der_to_pem(m0048._b64_decode(str(svid["bundle"])), "CERTIFICATE"),
    }


@pytest.fixture(scope="session")
def mtls(live_stack: None):
    # Same construction as the sealed OCOR-DEV-0048 fixture (real SVID client
    # context, TLS-terminating proxies with mandatory verified client auth in
    # front of OPA and Keycloak), with the server SVID selected by SPIFFE ID.
    if not fault_inject.container_healthy(m0048.SPIRE_AGENT_CONTAINER):
        pytest.fail("SPIRE agent container is unavailable; real mTLS is mandatory")
    client_context = SpireWorkloadIdentityProvider(
        agent_container=m0048.SPIRE_AGENT_CONTAINER,
        socket_path=m0048.SPIRE_SOCKET,
        expected_spiffe_id=m0048.EXPECTED_SPIFFE_ID,
    ).mtls_context()
    material = _control_plane_server_material()
    proxies = []
    for backend_port in (8181, 8080):
        proxy = m0048._MtlsReverseProxy(
            "127.0.0.1", backend_port, material["cert_pem"], material["key_pem"], material["ca_pem"]
        )
        proxy.__enter__()
        proxies.append(proxy)
    try:
        yield {"ssl_context": client_context, "opa": proxies[0].url, "keycloak": proxies[1].url}
    finally:
        for proxy in proxies:
            proxy.__exit__(None, None, None)


def _password(username: str) -> str:
    if username == PROVISIONER_USERNAME:
        return _PROVISIONER_PASSWORD
    if username == HOSTILE_USERNAME:
        return HOSTILE_PASSWORD
    return ""


def _keycloak(mtls: dict[str, object], *, url: str | None = None, timeout: float = 5.0,
              resolver=_password) -> KeycloakIdentityProvider:
    return KeycloakIdentityProvider(
        url or str(mtls["keycloak"]),
        REALM,
        CLIENT_ID,
        password_resolver=resolver,
        timeout_seconds=timeout,
        ssl_context=mtls["ssl_context"],
    )


def _credential(username: str) -> str:
    return f"urn:ocor:credential-ref:{username}"


def _authenticate(provider: KeycloakIdentityProvider, username: str) -> AuthenticatedPrincipal:
    return provider.authenticate(IdentityRequest(_credential(username), AUDIENCE, str(uuid.uuid4())))


@pytest.fixture(scope="session")
def identities(provisioner_user: None, mtls: dict[str, object]) -> dict[str, str]:
    provider = _keycloak(mtls)
    return {
        "provisioner": _authenticate(provider, PROVISIONER_USERNAME).principal_id,
        "hostile": _authenticate(provider, HOSTILE_USERNAME).principal_id,
    }


def _opa(mtls: dict[str, object], *, timeout: float = 5.0) -> OpaPolicyDecisionProvider:
    return OpaPolicyDecisionProvider(
        str(mtls["opa"]),
        POLICY_ID,
        signer_public_key=(m0048._SIGNER_N, m0048._SIGNER_E),
        timeout_seconds=timeout,
        ssl_context=mtls["ssl_context"],
    )


@pytest.fixture
def opa(identities: dict[str, str], mtls: dict[str, object]) -> tuple[OpaPolicyDecisionProvider, str]:
    provider = _opa(mtls)
    digest = provider.install_policy(
        m0048._sign_bundle(provisioning_policy_rego([identities["provisioner"]]))
    )
    return provider, digest


def _gcs(principal_id: str, policy_digest: str, *, correlation_id: str | None = None) -> GovernedContext:
    return GovernedContext(
        tenant_id="tenant-a",
        organization_id="org-a",
        domain_id="domain-a",
        compartments=("compartment-a",),
        classification_marking_ref="urn:sha256:" + "0" * 64,
        purpose="identity-provisioning",
        effective_principal_id=principal_id,
        actor_chain=(principal_id,),
        ontology_release_digest="urn:sha256:" + "1" * 64,
        policy_bundle_digest=policy_digest,
        correlation_id=correlation_id or str(uuid.uuid4()),
    )


@pytest.fixture
def world(opa, identities, mtls):
    provider, digest = opa
    registry = IdentityRegistry()
    boundary = IdentityProvisioningBoundary(
        registry, identity=_keycloak(mtls), policy=provider, audience=AUDIENCE
    )
    return registry, boundary, digest, identities


def _reseed(boundary, *records):
    """A registry seeded at composition with the same real authority ports:
    after construction, records with Q1 attributes enter only through the boundary."""
    registry = IdentityRegistry(records)
    return registry, IdentityProvisioningBoundary(
        registry, identity=boundary._identity, policy=boundary._policy, audience=boundary._audience
    )


def _provision(boundary, record, username, principal_id, digest, **gcs_kwargs):
    return boundary.provision(
        record,
        credential_ref=_credential(username),
        governed_context=_gcs(principal_id, digest, **gcs_kwargs),
    )


def _denied(boundary, registry, record, username, principal_id, digest, reason, **gcs_kwargs):
    before = _snapshot(registry)
    with pytest.raises(IdentityProvisioningDenied) as excinfo:
        _provision(boundary, record, username, principal_id, digest, **gcs_kwargs)
    assert excinfo.value.reason_code == reason, (excinfo.value.reason_code, str(excinfo.value))
    assert _snapshot(registry) == before, "a denied provisioning changed the registry"
    return excinfo.value


# --------------------------------------------------------------------------- #
# Positive: authorised creation on real Keycloak + OPA
# --------------------------------------------------------------------------- #


def test_authorised_writer_creates_new_q1_record_on_real_backends(world):
    registry, boundary, digest, ids = world
    correlation_id = str(uuid.uuid4())
    record = _record(NEW_HUMAN, "rem0031-approver-alias")

    receipt = _provision(
        boundary, record, PROVISIONER_USERNAME, ids["provisioner"], digest,
        correlation_id=correlation_id,
    )

    assert isinstance(receipt, ProvisioningReceipt)
    assert receipt.record == record
    assert receipt.writer_principal_id == ids["provisioner"]
    assert receipt.policy_bundle_digest == digest
    assert receipt.correlation_id == correlation_id
    assert receipt.decision_id.startswith("urn:sha256:")
    assert registry.get(NEW_HUMAN) == record
    assert dict(registry.get(NEW_HUMAN).attributes) == _q1("SECURITY_DUTY_OFFICER")
    outcome = registry.resolve("rem0031-approver-alias")
    assert outcome.status is ResolutionStatus.IDENTIFIED and outcome.canonical_id == NEW_HUMAN


def test_authorised_writer_may_provision_after_composition_seeding(world):
    # Seeding records of other principals does not make the authority one of them.
    registry, boundary, digest, ids = world
    registry, boundary = _reseed(boundary, _record("urn:ocor:human:rem0031-seeded-requester", **_q1()))
    receipt = _provision(boundary, _record(), PROVISIONER_USERNAME, ids["provisioner"], digest)
    assert receipt.record.canonical_id == NEW_HUMAN
    assert len(registry.all_records()) == 2


# --------------------------------------------------------------------------- #
# Hostile first writer and unauthenticated writer
# --------------------------------------------------------------------------- #


def test_hostile_first_writer_is_denied_by_real_policy(world):
    registry, boundary, digest, ids = world
    error = _denied(
        boundary, registry, _record(), HOSTILE_USERNAME, ids["hostile"], digest,
        "PROVISIONING_POLICY_DENIED",
    )
    assert registry.get(NEW_HUMAN) is None
    assert error.correlation_id is not None


def test_unauthenticated_writer_is_denied_by_real_keycloak(opa, identities, mtls):
    provider, digest = opa
    registry = IdentityRegistry()
    boundary = IdentityProvisioningBoundary(
        registry,
        identity=_keycloak(mtls, resolver=lambda _user: "wrong-password"),
        policy=provider,
        audience=AUDIENCE,
    )
    error = _denied(
        boundary, registry, _record(), PROVISIONER_USERNAME, identities["provisioner"], digest,
        "PROVISIONING_WRITER_UNAUTHENTICATED",
    )
    assert error.cause_reason_code == "IDENTITY_REJECTED"


def test_unknown_credential_reference_is_denied_before_any_backend(world):
    registry, boundary, digest, ids = world
    before = _snapshot(registry)
    with pytest.raises(IdentityProvisioningDenied) as excinfo:
        boundary.provision(
            _record(), credential_ref="analyst-1", governed_context=_gcs(ids["provisioner"], digest)
        )
    assert excinfo.value.reason_code == "PROVISIONING_REQUEST_INVALID"
    assert _snapshot(registry) == before


def test_governed_context_bound_to_another_principal_is_denied(world):
    registry, boundary, digest, ids = world
    error = _denied(
        boundary, registry, _record(), PROVISIONER_USERNAME, ids["hostile"], digest,
        "PROVISIONING_AUTHORITY_REJECTED",
    )
    assert error.cause_reason_code == "PRINCIPAL_BINDING_MISMATCH"


# --------------------------------------------------------------------------- #
# Self-attribution
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("placement", ["canonical", "alias", "alias_case_folded"])
def test_self_attribution_is_denied(world, placement):
    registry, boundary, digest, ids = world
    me = ids["provisioner"]
    record = {
        "canonical": _record(me),
        "alias": _record(NEW_HUMAN, me),
        "alias_case_folded": _record(NEW_HUMAN, f"  {me.upper()} "),
    }[placement]
    _denied(
        boundary, registry, record, PROVISIONER_USERNAME, me, digest,
        "PROVISIONING_SELF_ATTRIBUTION",
    )


def test_real_policy_independently_denies_self_attribution(opa, identities, mtls):
    # Defence in depth: the signed policy itself refuses a resource naming the writer.
    provider, digest = opa
    writer = _authenticate(_keycloak(mtls), PROVISIONER_USERNAME)
    gcs = _gcs(writer.principal_id, digest)

    def decide(resource: str) -> PolicyEffect:
        return provider.evaluate(PolicyRequest(
            principal=writer, action=PROVISIONING_ACTION, resource=resource,
            governed_context=gcs, governed_context_digest=gcs.digest(), at=datetime.now(UTC),
        )).effect

    assert decide(provisioning_resource(NEW_HUMAN)) is PolicyEffect.PERMIT
    assert decide(provisioning_resource(writer.principal_id)) is PolicyEffect.DENY
    assert decide("urn:ocor:target:site-1") is PolicyEffect.DENY


# --------------------------------------------------------------------------- #
# Writer registered as a principal (requester or approver)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "seed",
    [
        pytest.param({"roles": (), "alias": False}, id="requester"),
        pytest.param({"roles": ("SECURITY_DUTY_OFFICER",), "alias": False}, id="approver"),
        pytest.param({"roles": ("DOMAIN_OWNER:ops",), "alias": True}, id="approver_by_alias"),
    ],
)
def test_writer_registered_as_requester_or_approver_is_denied(world, seed):
    registry, boundary, digest, ids = world
    me = ids["provisioner"]
    if seed["alias"]:
        registry, boundary = _reseed(boundary, _record("urn:ocor:human:rem0031-owner", me, **_q1(*seed["roles"])))
    else:
        registry, boundary = _reseed(boundary, _record(me, **_q1(*seed["roles"])))
    _denied(
        boundary, registry, _record(), PROVISIONER_USERNAME, me, digest,
        "PROVISIONING_WRITER_IS_REGISTERED_PRINCIPAL",
    )
    assert registry.get(NEW_HUMAN) is None


# --------------------------------------------------------------------------- #
# Update denied
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("variant", ["promotion", "identical_replay", "bound_alias"])
def test_update_of_existing_record_or_identifier_is_denied(world, variant):
    registry, boundary, digest, ids = world
    requester = _record("urn:ocor:human:rem0031-requester", "rem0031-requester-alias", **_q1())
    registry, boundary = _reseed(boundary, requester)
    record = {
        "promotion": _record(requester.canonical_id, **_q1("SECURITY_DUTY_OFFICER")),
        "identical_replay": requester,
        "bound_alias": _record(NEW_HUMAN, "REM0031-Requester-Alias"),
    }[variant]
    _denied(
        boundary, registry, record, PROVISIONER_USERNAME, ids["provisioner"], digest,
        "PROVISIONING_UPDATE_DENIED",
    )
    assert registry.get(requester.canonical_id) == requester


def test_second_provisioning_of_a_created_record_is_denied(world):
    registry, boundary, digest, ids = world
    created = _provision(boundary, _record(), PROVISIONER_USERNAME, ids["provisioner"], digest).record
    _denied(
        boundary, registry, _record(NEW_HUMAN, **_q1("DOMAIN_OWNER:ops")), PROVISIONER_USERNAME,
        ids["provisioner"], digest, "PROVISIONING_UPDATE_DENIED",
    )
    assert registry.get(NEW_HUMAN) == created


# --------------------------------------------------------------------------- #
# Unavailable or unverifiable authority: fail-closed on real backends
# --------------------------------------------------------------------------- #


def _pause(service: str):
    result = fault_inject.run(fault_inject.fault_command(service, "pause"), cwd=REPOSITORY_ROOT, timeout=30)
    assert result.returncode == 0, result.stderr


def _unpause(service: str, label: str):
    result = fault_inject.run(fault_inject.fault_command(service, "unpause"), cwd=REPOSITORY_ROOT, timeout=30)
    assert result.returncode == 0, result.stderr
    assert fault_inject._poll(
        lambda: fault_inject.http_reachable(SERVICE_URLS[label], timeout=2.0), timeout=15.0
    ), f"{label} did not recover after unpause"


def test_paused_opa_fails_closed_and_recovers(identities, mtls):
    provider = _opa(mtls, timeout=2.0)
    digest = provider.install_policy(
        m0048._sign_bundle(provisioning_policy_rego([identities["provisioner"]]))
    )
    registry = IdentityRegistry()
    boundary = IdentityProvisioningBoundary(
        registry, identity=_keycloak(mtls), policy=provider, audience=AUDIENCE
    )
    _pause("opa")
    try:
        assert fault_inject._poll(
            lambda: not fault_inject.http_reachable(SERVICE_URLS["OPA"], timeout=1.0), timeout=10.0
        ), "OPA was never observed unreachable after pause"
        error = _denied(
            boundary, registry, _record(), PROVISIONER_USERNAME, identities["provisioner"], digest,
            "PROVISIONING_AUTHORITY_UNAVAILABLE",
        )
        assert error.cause_reason_code in ("SERVICE_UNAVAILABLE", "POLICY_UNAVAILABLE")
    finally:
        _unpause("opa", "OPA")
    _provision(boundary, _record(), PROVISIONER_USERNAME, identities["provisioner"], digest)
    assert registry.get(NEW_HUMAN) is not None


def test_paused_keycloak_fails_closed_and_recovers(opa, identities, mtls):
    provider, digest = opa
    registry = IdentityRegistry()
    boundary = IdentityProvisioningBoundary(
        registry, identity=_keycloak(mtls, timeout=0.5), policy=provider, audience=AUDIENCE
    )
    _pause("keycloak")
    try:
        assert fault_inject._poll(
            lambda: not fault_inject.http_reachable(SERVICE_URLS["Keycloak"], timeout=1.0),
            timeout=10.0,
        ), "Keycloak was never observed unreachable after pause"
        error = _denied(
            boundary, registry, _record(), PROVISIONER_USERNAME, identities["provisioner"], digest,
            "PROVISIONING_AUTHORITY_UNAVAILABLE",
        )
        assert error.cause_reason_code == "SERVICE_UNAVAILABLE"
    finally:
        _unpause("keycloak", "Keycloak")
    recovered = IdentityProvisioningBoundary(
        registry, identity=_keycloak(mtls), policy=provider, audience=AUDIENCE
    )
    _provision(recovered, _record(), PROVISIONER_USERNAME, identities["provisioner"], digest)
    assert registry.get(NEW_HUMAN) is not None


def test_policy_without_installed_signed_bundle_fails_closed(identities, mtls):
    registry = IdentityRegistry()
    boundary = IdentityProvisioningBoundary(
        registry, identity=_keycloak(mtls), policy=_opa(mtls), audience=AUDIENCE
    )
    error = _denied(
        boundary, registry, _record(), PROVISIONER_USERNAME, identities["provisioner"],
        "urn:sha256:" + "e" * 64, "PROVISIONING_AUTHORITY_UNAVAILABLE",
    )
    assert error.cause_reason_code == "POLICY_UNAVAILABLE"


def test_governed_pin_to_another_bundle_fails_closed(world):
    registry, boundary, _digest, ids = world
    error = _denied(
        boundary, registry, _record(), PROVISIONER_USERNAME, ids["provisioner"],
        "urn:sha256:" + "f" * 64, "PROVISIONING_AUTHORITY_UNAVAILABLE",
    )
    assert error.cause_reason_code == "STALE_BUNDLE"


def test_unreachable_identity_endpoint_fails_closed(opa, identities, mtls):
    provider, digest = opa
    registry = IdentityRegistry()
    boundary = IdentityProvisioningBoundary(
        registry,
        identity=_keycloak(mtls, url="https://127.0.0.1:9", timeout=1.0),
        policy=provider,
        audience=AUDIENCE,
    )
    error = _denied(
        boundary, registry, _record(), PROVISIONER_USERNAME, identities["provisioner"], digest,
        "PROVISIONING_AUTHORITY_UNAVAILABLE",
    )
    assert error.cause_reason_code == "SERVICE_UNAVAILABLE"


# --------------------------------------------------------------------------- #
# Local failure handling (stub ports; non-qualifying for backend behaviour)
# --------------------------------------------------------------------------- #

_LOCAL_DIGEST = "urn:sha256:" + "a" * 64
_WRITER = "urn:ocor:workload:rem0031-local-provisioner"


class _LocalIdentity:
    def __init__(self, principal_id: str = _WRITER, error: Exception | None = None) -> None:
        self.principal_id = principal_id
        self.error = error
        self.calls = 0

    def authenticate(self, request: IdentityRequest) -> AuthenticatedPrincipal:
        self.calls += 1
        if self.error is not None:
            raise self.error
        now = datetime.now(UTC)
        return AuthenticatedPrincipal(
            principal_id=self.principal_id,
            session_id="local-session",
            actor_chain=(self.principal_id,),
            assurance_level="LEVEL_2",
            authenticated_at=now - timedelta(seconds=1),
            expires_at=now + timedelta(minutes=5),
            status=ControlStatus.available(ControlName.IDENTITY, observed_at=now, source_digest=_LOCAL_DIGEST),
        )


@dataclass
class _LocalPolicy:
    effect: PolicyEffect = PolicyEffect.PERMIT
    obligations: tuple[str, ...] = ()
    error: Exception | None = None
    drift_resource: bool = False
    during: object = None
    calls: int = 0

    def evaluate(self, request: PolicyRequest) -> PolicyDecision:
        self.calls += 1
        if callable(self.during):
            self.during()
        if self.error is not None:
            raise self.error
        now = datetime.now(UTC)
        bound = replace(request, resource="urn:ocor:target:other") if self.drift_resource else request
        return PolicyDecision.from_request(
            replace(bound, at=now),
            effect=self.effect,
            decision_id="urn:sha256:" + "b" * 64,
            valid_until=now + timedelta(minutes=1),
            obligations=self.obligations,
            status=ControlStatus.available(
                ControlName.POLICY, observed_at=now,
                source_digest=request.governed_context.policy_bundle_digest,
            ),
        )


def _local(policy: _LocalPolicy, identity: _LocalIdentity | None = None, seed: tuple[IdentityRecord, ...] = ()):
    registry = IdentityRegistry(seed)
    boundary = IdentityProvisioningBoundary(
        registry, identity=identity or _LocalIdentity(), policy=policy, audience=AUDIENCE
    )
    return registry, boundary


def _local_denied(registry, boundary, reason, record=None):
    return _denied(boundary, registry, record or _record(), "local", _WRITER, _LOCAL_DIGEST, reason)


def test_local_permit_creates_record():
    registry, boundary = _local(_LocalPolicy())
    receipt = _provision(boundary, _record(), "local", _WRITER, _LOCAL_DIGEST)
    assert registry.get(NEW_HUMAN) == receipt.record


@pytest.mark.parametrize(
    "effect,obligations",
    [
        (PolicyEffect.DENY, ()),
        (PolicyEffect.REQUIRE_APPROVAL, ("dual-control",)),
        (PolicyEffect.PERMIT_WITH_CONSTRAINTS, ("audit",)),
        (PolicyEffect.OBLIGATE, ("notify",)),
    ],
)
def test_every_non_permit_effect_is_a_denial(effect, obligations):
    registry, boundary = _local(_LocalPolicy(effect=effect, obligations=obligations))
    _local_denied(registry, boundary, "PROVISIONING_POLICY_DENIED")


def test_decision_bound_to_another_resource_is_rejected():
    registry, boundary = _local(_LocalPolicy(drift_resource=True))
    error = _local_denied(registry, boundary, "PROVISIONING_AUTHORITY_REJECTED")
    assert error.cause_reason_code == "POLICY_BINDING_MISMATCH"


@pytest.mark.parametrize(
    "error,reason,cause",
    [
        (SecurityControlError("POLICY_UNAVAILABLE", "x"), "PROVISIONING_AUTHORITY_UNAVAILABLE", "POLICY_UNAVAILABLE"),
        (SecurityControlError("POLICY_DECISION_INVALID", "x"), "PROVISIONING_AUTHORITY_REJECTED", "POLICY_DECISION_INVALID"),
        (OSError("connection reset"), "PROVISIONING_AUTHORITY_UNAVAILABLE", None),
        (ValueError("malformed"), "PROVISIONING_AUTHORITY_UNAVAILABLE", None),
    ],
)
def test_policy_failures_fail_closed(error, reason, cause):
    registry, boundary = _local(_LocalPolicy(error=error))
    assert _local_denied(registry, boundary, reason).cause_reason_code == cause


@pytest.mark.parametrize(
    "error,reason,cause",
    [
        (SecurityControlError("IDENTITY_UNAVAILABLE", "x"), "PROVISIONING_AUTHORITY_UNAVAILABLE", "IDENTITY_UNAVAILABLE"),
        (SecurityControlError("IDENTITY_REJECTED", "x"), "PROVISIONING_WRITER_UNAUTHENTICATED", "IDENTITY_REJECTED"),
        (SecurityControlError("ANONYMOUS_IDENTITY_FORBIDDEN", "x"), "PROVISIONING_WRITER_UNAUTHENTICATED", "ANONYMOUS_IDENTITY_FORBIDDEN"),
        (TimeoutError("timed out"), "PROVISIONING_AUTHORITY_UNAVAILABLE", None),
    ],
)
def test_identity_failures_fail_closed_without_consulting_policy(error, reason, cause):
    policy = _LocalPolicy()
    registry, boundary = _local(policy, _LocalIdentity(error=error))
    assert _local_denied(registry, boundary, reason).cause_reason_code == cause
    assert policy.calls == 0


def test_boundary_checks_precede_policy_consultation():
    policy = _LocalPolicy()
    registry, boundary = _local(policy, seed=(_record(_WRITER, **_q1(kind="WORKLOAD")),))
    _local_denied(registry, boundary, "PROVISIONING_WRITER_IS_REGISTERED_PRINCIPAL")
    _local_denied(registry, boundary, "PROVISIONING_SELF_ATTRIBUTION", _record(NEW_HUMAN, _WRITER))
    assert policy.calls == 0


def test_record_created_concurrently_during_policy_is_not_overwritten():
    racing = _record(NEW_HUMAN, **_q1())
    holder: dict[str, IdentityRegistry] = {}
    # A concurrent provisioning admitted through the boundary's reserved write path.
    policy = _LocalPolicy(during=lambda: holder["registry"]._admit_provisioned(racing))
    registry, boundary = _local(policy)
    holder["registry"] = registry
    with pytest.raises(IdentityProvisioningDenied) as excinfo:
        _provision(boundary, _record(), "local", _WRITER, _LOCAL_DIGEST)
    assert excinfo.value.reason_code == "PROVISIONING_UPDATE_DENIED"
    assert registry.get(NEW_HUMAN) == racing


def test_writer_registered_concurrently_during_policy_is_denied():
    holder: dict[str, IdentityRegistry] = {}
    policy = _LocalPolicy(
        during=lambda: holder["registry"]._admit_provisioned(_record(_WRITER, **_q1("SECURITY_DUTY_OFFICER")))
    )
    registry, boundary = _local(policy)
    holder["registry"] = registry
    with pytest.raises(IdentityProvisioningDenied) as excinfo:
        _provision(boundary, _record(), "local", _WRITER, _LOCAL_DIGEST)
    assert excinfo.value.reason_code == "PROVISIONING_WRITER_IS_REGISTERED_PRINCIPAL"
    assert registry.get(NEW_HUMAN) is None


def test_non_record_input_is_rejected():
    registry, boundary = _local(_LocalPolicy())
    with pytest.raises(IdentityProvisioningDenied) as excinfo:
        boundary.provision(
            {"canonical_id": NEW_HUMAN},  # type: ignore[arg-type]
            credential_ref=_credential("local"),
            governed_context=_gcs(_WRITER, _LOCAL_DIGEST),
        )
    assert excinfo.value.reason_code == "PROVISIONING_REQUEST_INVALID"
    assert registry.all_records() == ()


# --------------------------------------------------------------------------- #
# Signed provisioning policy source
# --------------------------------------------------------------------------- #


def test_provisioning_policy_is_governed_and_self_contained():
    source = provisioning_policy_rego(["b-authority", "a-authority"])
    assert source.startswith("package ocor.control_plane\n")
    assert "default allow := false" in source
    assert f'"{PROVISIONING_ACTION}"' in source
    assert f'"{PROVISIONING_RESOURCE_PREFIX}"' in source
    assert source.index('"a-authority"') < source.index('"b-authority"')
    assert "data." not in source
    assert provisioning_policy_rego(["a-authority", "b-authority"]) == source


@pytest.mark.parametrize(
    "authorities",
    [[], [""], ['a"} allow if { true'], ["a\nb"], ["a\\b"], [None]],
)
def test_provisioning_policy_rejects_unsafe_authorities(authorities):
    with pytest.raises(ValueError):
        provisioning_policy_rego(authorities)


def test_provisioning_resource_is_namespaced():
    assert provisioning_resource(NEW_HUMAN) == PROVISIONING_RESOURCE_PREFIX + NEW_HUMAN
    with pytest.raises(ValueError):
        provisioning_resource("")


@pytest.mark.parametrize(
    "violation",
    [None, "action", "resource", "self_resource", "authority", "effective_principal",
     "actor_chain", "delegation", "capability"],
)
def test_signed_policy_clauses_on_real_opa(opa, identities, violation):
    # Each clause of the signed rule is exercised directly on the installed
    # bundle: the baseline permits, every single violation denies.
    _provider, _digest = opa
    writer = identities["provisioner"]
    policy_input: dict[str, object] = {
        "action": PROVISIONING_ACTION,
        "resource": provisioning_resource(NEW_HUMAN),
        "principal_id": writer,
        "effective_principal_id": writer,
        "actor_chain": [writer],
        "delegation_grant_ids": [],
        "capability": None,
    }
    if violation is not None:
        policy_input.update({
            "action": {"action": "identity.update"},
            "resource": {"resource": "urn:ocor:target:site-1"},
            "self_resource": {"resource": provisioning_resource(writer)},
            "authority": {"principal_id": identities["hostile"],
                          "effective_principal_id": identities["hostile"],
                          "actor_chain": [identities["hostile"]]},
            "effective_principal": {"effective_principal_id": identities["hostile"]},
            "actor_chain": {"actor_chain": [identities["hostile"], writer]},
            "delegation": {"delegation_grant_ids": ["urn:ocor:grant:x"]},
            "capability": {"capability": {"capability_id": "x"}},
        }[violation])
    status, body = m0048._http(
        "POST",
        f"{m0048.OPA}/v1/data/ocor/control_plane/allow",
        headers={"Content-Type": "application/json"},
        body=json.dumps({"input": policy_input}),
    )
    assert status == 200, body
    assert json.loads(body).get("result") is (violation is None)


# --------------------------------------------------------------------------- #
# register() closed by default for reserved Q1 attributes (PO decision
# REM-0031-REGISTRY-CONSUMER-SCOPE, option 1): immutability first, then every
# new record carrying principal_kind, status or roles is refused; such records
# enter only by composition seeding or through the provisioning boundary.
# --------------------------------------------------------------------------- #

_APPROVER = "urn:ocor:human:rem0031-hostile-approver"
_GATE_NOW = datetime(2026, 10, 26, 9, tzinfo=UTC)


def _register_denied(registry: IdentityRegistry, record: IdentityRecord) -> IdentityRegistrationDenied:
    before = _snapshot(registry)
    with pytest.raises(IdentityRegistrationDenied) as excinfo:
        registry.register(record)
    assert excinfo.value.reason_code == PRIVILEGED_RECORD_REASON_CODE
    assert _snapshot(registry) == before, "a refused registration changed the registry"
    assert registry.get(record.canonical_id) is None or registry.get(record.canonical_id) != record
    return excinfo.value


def test_reserved_q1_attribute_names_are_the_approved_convention():
    assert RESERVED_PRINCIPAL_ATTRIBUTES == frozenset({"principal_kind", "status", "roles"})
    assert PRIVILEGED_RECORD_REASON_CODE == "IDENTITY_PRIVILEGED_RECORD_REQUIRES_PROVISIONING"
    assert issubclass(IdentityRegistrationDenied, PermissionError)
    assert not issubclass(IdentityRegistrationDenied, IdentityConflictError)


def test_hostile_first_writer_directly_on_register_is_denied():
    # The first writer of a new identity can no longer self-assign an approver role.
    registry = IdentityRegistry()
    _register_denied(registry, _record(_APPROVER, "hostile-alias", **_q1("SECURITY_DUTY_OFFICER")))
    assert registry.all_records() == ()
    assert registry.candidates("hostile-alias") == ()
    assert registry.resolve(_APPROVER).status is ResolutionStatus.ABSTAIN


def test_hostile_first_writer_cannot_reach_a_human_gate_quorum():
    seeded = _record("urn:ocor:human:rem0031-real-approver", **_q1("COMPLIANCE"))
    registry = IdentityRegistry([seeded])
    _register_denied(registry, _record(_APPROVER, **_q1("RISK_OWNER")))
    signatures = [
        GateSignature(action_id="action", principal_id=seeded.canonical_id, role="COMPLIANCE", scope="scope", signed_at=_GATE_NOW),
        GateSignature(action_id="action", principal_id=_APPROVER, role="RISK_OWNER", scope="scope", signed_at=_GATE_NOW),
    ]
    gate = HumanGateCoordinator(identities=registry, clock=InMemoryTrustedClock(_GATE_NOW))
    with pytest.raises(HumanGateError):
        gate.validate(
            action_id="action", proposer_id="urn:ocor:human:rem0031-proposer",
            policy=ApprovalPolicy(frozenset({"COMPLIANCE", "RISK_OWNER"}), 2, timedelta(minutes=10)),
            signatures=signatures, scope="scope",
        )


@pytest.mark.parametrize(
    "attributes",
    [
        pytest.param({"principal_kind": "HUMAN"}, id="principal_kind_only"),
        pytest.param({"status": "ACTIVE"}, id="status_only"),
        pytest.param({"roles": "SECURITY_DUTY_OFFICER"}, id="roles_only"),
        pytest.param({"roles": ""}, id="empty_roles"),
        pytest.param({"principal_kind": "WORKLOAD", "status": "ACTIVE", "roles": ""}, id="workload"),
        pytest.param({"principal_kind": "HUMAN", "status": "SUSPENDED", "roles": "", "display": "x"}, id="with_other_keys"),
        pytest.param({"principal_kind": None}, id="null_value"),
    ],
)
def test_register_refuses_every_new_record_with_any_reserved_key(attributes):
    _register_denied(IdentityRegistry(), _record(_APPROVER, **attributes))


def test_register_still_admits_new_records_without_reserved_keys():
    registry = IdentityRegistry()
    plain = IdentityRecord(canonical_id="urn:ocor:asset:rem0031-plain", aliases=frozenset({"Plain"}),
                           attributes={"display_name": "Plain", "Status": "case differs", "role": "not reserved"})
    assert registry.register(plain) == plain
    assert registry.register(IdentityRecord(canonical_id="urn:ocor:asset:bare")).attributes == {}
    assert registry.resolve("plain").canonical_id == plain.canonical_id


def test_immutability_conflict_is_checked_before_the_reserved_key_refusal():
    requester = _record("urn:ocor:human:rem0031-requester", **_q1())
    registry = IdentityRegistry([requester])
    with pytest.raises(IdentityConflictError):
        registry.register(_record(requester.canonical_id, **_q1("SECURITY_DUTY_OFFICER")))
    plain = IdentityRecord(canonical_id="urn:ocor:asset:rem0031-plain")
    registry.register(plain)
    with pytest.raises(IdentityConflictError):
        registry.register(_record(plain.canonical_id, **_q1("SECURITY_DUTY_OFFICER")))
    assert registry.get(requester.canonical_id) == requester
    assert registry.get(plain.canonical_id) == plain


def test_identical_replay_of_a_seeded_record_adds_nothing():
    requester = _record("urn:ocor:human:rem0031-requester", **_q1())
    registry = IdentityRegistry([requester])
    before = _snapshot(registry)
    assert registry.register(requester) is registry.get(requester.canonical_id)
    assert _snapshot(registry) == before


def test_composition_seeding_admits_q1_records_with_immutability():
    a = _record("urn:ocor:human:rem0031-a", "alias-a", **_q1("COMPLIANCE"))
    b = _record("urn:ocor:human:rem0031-b", **_q1())
    registry = IdentityRegistry(iter([a, b, a]))
    assert registry.all_records() == (a, b)
    assert registry.resolve("ALIAS-A").canonical_id == a.canonical_id
    with pytest.raises(IdentityConflictError):
        IdentityRegistry([a, _record(a.canonical_id, **_q1("RISK_OWNER"))])
    assert identify_or_abstain([a, b], "alias-a").canonical_id == a.canonical_id


def test_no_public_registry_method_admits_q1_records_after_construction():
    public = {name for name in vars(IdentityRegistry) if not name.startswith("_")}
    assert public == {"register", "get", "add_alias", "candidates", "resolve", "all_records"}
    registry = IdentityRegistry()
    with pytest.raises(KeyError):
        registry.add_alias(_APPROVER, "hostile-alias")
    _register_denied(registry, _record(_APPROVER, **_q1("SECURITY_DUTY_OFFICER")))
    assert registry.all_records() == ()


def test_boundary_is_the_only_runtime_writer_of_q1_records():
    registry, boundary = _local(_LocalPolicy())
    _register_denied(registry, _record())
    receipt = _provision(boundary, _record(), "local", _WRITER, _LOCAL_DIGEST)
    assert registry.get(NEW_HUMAN) == receipt.record
    assert dict(receipt.record.attributes) == _q1("SECURITY_DUTY_OFFICER")
