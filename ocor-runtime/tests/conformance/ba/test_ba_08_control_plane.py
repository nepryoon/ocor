"""OCOR-DEV-0060 BA-08: security control plane -- policy timeout, revocation, lease expiry, stop drill.

BA: ``BA-08`` of ADD v1.3 Part I section 2.6 (row "OPA, Keycloak,
SPIFFE/SPIRE, OpenBao", required property "Decisione di policy entro
``policy_authority_timeout``; revoca propagata e scadenza locale del
``CapabilityLease`` come meccanismi indipendenti per il target ``≤10 s``";
conformance test "Chaos/safety drill con misura dell'ultimo command accettato
dopo lo stop") and the ``BA-08`` row of LLD v1.1 section 7.1
("OPA/Keycloak/SPIFFE/OpenBao applicano identity, delegation, policy, lease,
stop e secret isolation"). ``policy_authority_timeout`` is ``PT3S`` (ADD v1.3
configuration table); the containment target is ``NFR-047`` (10 s).

Real components (``infra/services.lock.json``, digest-pinned, running in the
``ocor-bootstrap`` stack): OPA 1.20.1, Keycloak 26.7.2, SPIFFE/SPIRE 1.15.3
(agent ``ocor-bootstrap-spire-agent-1``) and OpenBao 2.6.2. Sealed adapters
reused unmodified: ``ocor_runtime.security.control_plane``
(``KeycloakIdentityProvider``, ``SpireWorkloadIdentityProvider``,
``OpaPolicyDecisionProvider`` with signed bundle, signed delegation chain and
signed revocation, ``OpenBaoSecretProvider``), the ports of
``ocor_runtime.security.ports``, ``ocor_runtime.c6_capabilities``
(``CapabilityAuthority``/``CapabilityLease``, bound to the stop epoch) and
``ocor_runtime.c6.safety.EmergencyStopController`` (OCOR-DEV-0044). Every
control-plane call travels over real mutual TLS carrying the live SPIRE SVID
(loopback TLS-terminating proxies copied from the sealed OCOR-DEV-0048 test).

The command boundary exercised by the drills is a test-side composition of
those sealed controls -- no runtime code composes OPA with the lease ledger:
a command is accepted only if the local ``CapabilityLease`` (bound to the
emergency-stop epoch) authorizes it, the real OPA decision over the signed
delegation chain PERMITs it and is valid, and the lease authorizes it again
when the use is consumed. The two drills measure the instant of the last
accepted command after the stop: once with the revocation push delivered
(stop epoch + signed delegation revocation), and once with the push
unavailable (OPA paused, decision timeout fails closed), where only the
lease's local expiry -- anchored below the workload certificate's lifetime --
stops acceptance. The measured values are recorded as junit properties.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from ocor_runtime.c6.safety import EmergencyStopController, StopStatus
from ocor_runtime.c6_capabilities import CapabilityAuthority, CapabilityLease, StopEpochDenied
from ocor_runtime.errors import AuthorizationError
from ocor_runtime.kernel.governance import RiskClass
from ocor_runtime.kernel.governed_context import GovernedContext
from ocor_runtime.security.control_plane import (
    CapabilityInvocation,
    KeycloakIdentityProvider,
    OpaPolicyDecisionProvider,
    OpenBaoSecretProvider,
    OperationClass,
    SignedDelegation,
    SignedDelegationRevocation,
    SignedPolicyBundle,
    SpireWorkloadIdentityProvider,
    _b64_decode,
    _der_to_pem,
    _rsa_sign,
    _split_der_chain,
    workload_key_thumbprint,
)
from ocor_runtime.security.ports import (
    AuthenticatedPrincipal,
    IdentityRequest,
    PolicyDecision,
    PolicyEffect,
    PolicyRequest,
    SecretRequest,
    SecurityControlError,
    WorkloadIdentity,
)

BA_CASE = {
    "ba_id": "BA-08",
    "component": "OPA + Keycloak + SPIFFE/SPIRE + OpenBao security control plane",
    "component_version": "opa 1.20.1; keycloak 26.7.2; spire-agent 1.15.3; spire-server 1.15.3; openbao 2.6.2",
    "backend_services": ["opa", "keycloak", "spire-agent", "spire-server", "openbao"],
    "add_v1_3_part_i_2_6": {
        "required_property": "Decisione di policy entro `policy_authority_timeout`; revoca propagata e scadenza "
        "locale del `CapabilityLease` come meccanismi indipendenti per il target `≤10 s`",
        "conformance_test": "Chaos/safety drill con misura dell'ultimo command accettato dopo lo stop",
    },
    "lld_v1_1_7_1_oracle": "OPA/Keycloak/SPIFFE/OpenBao applicano identity, delegation, policy, lease, stop e "
    "secret isolation",
    "requirement_ids": ["NFR-047", "FR-128", "NFR-079"],
    "requirement_binding": {
        "NFR-047": "The stop drills measure the last command accepted after the stop and assert that no new "
        "command is accepted beyond 10 s, both with the revocation push and with only the local lease expiry.",
        "FR-128": "Every command's actor chain, purpose and signed delegation grant are verified by the real "
        "policy boundary, and a revoked grant is refused there independently of the lease.",
        "NFR-079": "Failure injection on the policy engine (OPA paused) yields a fail-closed refusal within "
        "policy_authority_timeout, never a permit, without disabling identity, lease or stop controls.",
    },
    "positive_tests": [
        "test_ba_08_positive_identity_delegation_and_policy_decision_within_policy_authority_timeout",
        "test_ba_08_positive_stop_drill_last_command_accepted_within_10_s_of_the_stop",
    ],
    "negative_tests": [
        "test_ba_08_negative_revocation_push_alone_refuses_while_the_lease_is_still_valid",
        "test_ba_08_negative_stop_epoch_alone_fences_the_lease_while_policy_still_permits",
        "test_ba_08_negative_secret_isolation_refuses_a_foreign_principal_and_path_escape",
    ],
    "fault_tests": [
        "test_ba_08_fault_policy_timeout_fails_closed_and_local_lease_expiry_alone_stops_commands",
    ],
}

KC = "http://127.0.0.1:8080"
OPA = "http://127.0.0.1:8181"
OB = "http://127.0.0.1:8200"
REALM = "ocor"
CLIENT_ID = "ocor-control-plane"
USERNAME = "analyst-1"
USER_PWD = "analyst-pass-123"
POLICY_ID = "ocor-control-plane"
OPA_CONTAINER = "ocor-bootstrap-opa-1"
SPIRE_AGENT_CONTAINER = "ocor-bootstrap-spire-agent-1"
SPIRE_SOCKET = "/run/spire/sockets/agent.sock"
EXPECTED_SPIFFE_ID = "spiffe://ocor.test/ocor/control-plane"
RESOURCE = "urn:ocor:target:site-1"
PURPOSE = "read-site-1"
COMMAND_CAPABILITY = "command:dispatch"
DELEGATOR = "delegator-1"

POLICY_AUTHORITY_TIMEOUT_S = 3.0  # ADD v1.3 configuration: policy_authority_timeout = PT3S
CONTAINMENT_TARGET_S = 10.0  # NFR-047 / BA-08 target
OBSERVATION_WINDOW_S = CONTAINMENT_TARGET_S + 0.75

SERVICE_URLS = {
    "OPA": f"{OPA}/health",
    "Keycloak": f"{KC}/realms/master/.well-known/openid-configuration",
    "OpenBao": f"{OB}/v1/sys/health",
}

# Test-only policy/delegation signer (RSA-2048), copied from the sealed
# OCOR-DEV-0048 test: it exists solely so the providers verify detached
# signatures against a pinned public key; it is not a production credential.
_SIGNER = "ocor-policy-signer-test"
_SIGNER_N = int(
    "00e1a86107dff3770af8b36aeed51e5f2c82aafc616fb3a365634f1ddcfdb1038"
    "e238da4600fa9f8b15223a1f4e9d63d60250ed5b323603d77a6659315e71ef71"
    "ae6982059fe31e6e98c8c12757863f7bcf2b8a83cd8ce0828f8e1b7a5e8128fc"
    "6a9779db09380fa5436ca701047def3fcec1416c36212bcf3d58b1af38678181"
    "d5ef740b6b4f0fbca559d4fd3be16aa3d39039e41cd918e4aad55c7c6785661a"
    "acd857fde6dec923ded1591e904d89024c4457e01984288e6cceb6b6cdafaaece"
    "ee2f568c245606e2ada66fa54ff4ca638729d1665d9e3a2c833be120f7a10a57"
    "df84e2dd099e49131291f0945c39ecc6c99be590655bb26460c8bd7d64c20717",
    16,
)
_SIGNER_E = 65537
_SIGNER_D = int(
    "0467d4a92232af26cc2f388dbc2471283dced7c991343922f01ae9d2d8331e06"
    "26e48b8a8293c772b2cf5648a14e18f9a90f8e958641c9416e42ba69e98ebdb5"
    "4d3e381779b280b71b92da83679bd008e4d63d169f06fabace0d1e18439d2528"
    "74438d1516f4242f03b8d512444cf28784166a515b3751701341b97f7aa71a95"
    "62d34fed0cc6d40a97eccc5dfb036d581bb72711fd1dd5f13ce69ce482f40231"
    "d3bd23a7da2d985862a2e7d33a01d3a261d9fccd2315290736ca7f46a7b61186"
    "6a39d6a8aa36ba26dbc7ae26a20942bb82d72a47dc877d9a1c17fa3665413c16"
    "b29d1f08cb29ba9050d41e4a66cb7e14d1f3f67da8707fce47ef20e7c65c8761",
    16,
)

_CAPABILITY = CapabilityInvocation(
    capability_id="urn:ocor:capability:read-site",
    capability_version="1.0.0",
    effect_class=OperationClass.R0_READ,
    risk_class=RiskClass.R0_INFORMATIONAL,
)

RecordProperty = Callable[[str, object], None]


def _now() -> datetime:
    return datetime.now(UTC)


def _rego(principal_id: str) -> str:
    # Identical to the sealed OCOR-DEV-0048 bundle, so both suites converge on one module.
    return (
        "package ocor.control_plane\n\n"
        "default allow := false\n\n"
        "allow if {\n"
        f'    input.principal_id == "{principal_id}"\n'
        '    input.action == "read"\n'
        '    input.resource == "urn:ocor:target:site-1"\n'
        "}\n"
    )


def _sign(payload: bytes) -> str:
    return base64.b64encode(_rsa_sign(payload, _SIGNER_N, _SIGNER_D)).decode("ascii")


def _sign_bundle(rego_source: str) -> SignedPolicyBundle:
    unsigned = SignedPolicyBundle(
        policy_id=POLICY_ID,
        rego_source=rego_source,
        signer=_SIGNER,
        not_before=_now() - timedelta(minutes=5),
        expires_at=_now() + timedelta(hours=1),
        signature="",
    )
    return replace(unsigned, signature=_sign(unsigned.signing_payload()))


def _sign_grant(*, grantee: str, policy_digest: str, key_thumbprint: str) -> SignedDelegation:
    unsigned = SignedDelegation(
        grant_id=f"urn:ocor:delegation:ba08:{uuid.uuid4()}",
        grantor_principal=DELEGATOR,
        grantee_principal=grantee,
        capability_id=_CAPABILITY.capability_id,
        capability_version=_CAPABILITY.capability_version,
        resource_scope=RESOURCE,
        tenant_id="tenant-a",
        organization_id="org-a",
        domains=("domain-a",),
        compartments=("compartment-a",),
        permitted_purposes=(PURPOSE,),
        effect_ceiling=OperationClass.R0_READ,
        risk_ceiling=RiskClass.R0_INFORMATIONAL,
        not_before=_now() - timedelta(minutes=5),
        expires_at=_now() + timedelta(hours=1),
        max_chain_depth=1,
        policy_bundle_digest=policy_digest,
        nonce=uuid.uuid4().hex,
        confirmation_key_thumbprint=key_thumbprint,
    )
    return replace(unsigned, signature=_sign(unsigned.signing_payload()))


def _sign_revocation(grant_id: str) -> SignedDelegationRevocation:
    unsigned = SignedDelegationRevocation(delegation_id=grant_id, revoked_at=_now(), signature="")
    return replace(unsigned, signature=_sign(unsigned.signing_payload()))


def _gcs(principal: AuthenticatedPrincipal, policy_digest: str, actor_chain: tuple[str, ...]) -> GovernedContext:
    return GovernedContext(
        tenant_id="tenant-a",
        organization_id="org-a",
        domain_id="domain-a",
        compartments=("compartment-a",),
        classification_marking_ref="urn:sha256:" + "0" * 64,
        purpose=PURPOSE,
        effective_principal_id=principal.principal_id,
        actor_chain=actor_chain,
        ontology_release_digest="urn:sha256:" + "1" * 64,
        policy_bundle_digest=policy_digest,
        correlation_id=str(uuid.uuid4()),
    )


def _request(
    principal: AuthenticatedPrincipal, policy_digest: str, *, delegated: bool, action: str = "read"
) -> PolicyRequest:
    chain = (DELEGATOR, principal.principal_id) if delegated else (principal.principal_id,)
    gcs = _gcs(principal, policy_digest, chain)
    return PolicyRequest(
        principal=principal,
        action=action,
        resource=RESOURCE,
        governed_context=gcs,
        governed_context_digest=gcs.digest(),
        at=_now(),
    )


# --------------------------------------------------------------------------- #
# Environment and plain local HTTP (setup/read-back only, never a BA decision)
# --------------------------------------------------------------------------- #


def _env_file() -> Path | None:
    configured = os.environ.get("OCOR_BOOTSTRAP_ENV")
    if configured and Path(configured).exists():
        return Path(configured)
    repository = Path(__file__).resolve().parents[4]
    for candidate in (
        Path.home() / ".ocor-bootstrap-secrets" / "ocor-bootstrap.env",
        repository / ".ocor" / "bootstrap.env",
    ):
        if candidate.exists():
            return candidate
    return None


def _http(
    method: str, url: str, *, headers: dict[str, str] | None = None, body: str | None = None
) -> tuple[int, str]:
    request = urllib.request.Request(url, method=method, data=None if body is None else body.encode())
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=10.0) as response:
            return int(response.status), response.read().decode()
    except urllib.error.HTTPError as error:
        return int(error.code), error.read().decode()


def _reachable(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True
    except (OSError, urllib.error.URLError):
        return False


def _poll(predicate: Callable[[], bool], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.25)
    return predicate()


def _container_state(container: str) -> dict[str, Any]:
    result = subprocess.run(
        ["docker", "inspect", container, "--format", "{{json .State}}"],
        text=True, capture_output=True, timeout=15, check=False,
    )
    if result.returncode:
        return {"Status": "absent", "Running": False}
    state: dict[str, Any] = json.loads(result.stdout)
    return state


def _docker(*args: str) -> None:
    result = subprocess.run(["docker", *args], text=True, capture_output=True, timeout=60, check=False)
    assert result.returncode == 0, f"docker {args[0]} failed: {result.stderr.strip()}"


# --------------------------------------------------------------------------- #
# mTLS: loopback TLS-terminating proxies that require and verify the caller's
# SPIRE SVID before forwarding to the local backend (copied from OCOR-DEV-0048).
# --------------------------------------------------------------------------- #


def _fetch_svid_json() -> dict[str, Any]:
    completed = subprocess.run(
        [
            "docker", "exec", SPIRE_AGENT_CONTAINER, "/opt/spire/bin/spire-agent", "api", "fetch", "x509",
            "-socketPath", SPIRE_SOCKET, "-output", "json",
        ],
        capture_output=True, timeout=30, check=False,
    )
    if completed.returncode != 0:
        state = _container_state(SPIRE_AGENT_CONTAINER)
        pytest.fail(
            "spire-agent api fetch x509 failed; a real SVID is mandatory for BA-08 "
            f"(agent state={state.get('Status')}, OOMKilled={state.get('OOMKilled')}, "
            f"exit={state.get('ExitCode')})"
        )
    svids = json.loads(completed.stdout.decode()).get("svids") or []
    assert svids, "no SVID returned by spire-agent"
    svid: dict[str, Any] = svids[0]
    return svid


def _read_http(sock: ssl.SSLSocket | socket.socket) -> tuple[bytes, bytes]:
    buffer = b""
    while b"\r\n\r\n" not in buffer:
        chunk = sock.recv(65536)
        if not chunk:
            break
        buffer += chunk
    head, _, body = buffer.partition(b"\r\n\r\n")
    length = 0
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1].strip())
    while len(body) < length:
        chunk = sock.recv(65536)
        if not chunk:
            break
        body += chunk
    return head, body


def _read_until_eof(sock: socket.socket) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _force_connection_close(head: bytes) -> bytes:
    lines = [line for line in head.split(b"\r\n") if not line.lower().startswith(b"connection:")]
    return b"\r\n".join([*lines, b"Connection: close"])


class _MtlsProxy:
    """TLS-terminating loopback proxy with mandatory, verified client auth."""

    def __init__(self, backend_port: int, cert_pem: str, key_pem: str, ca_pem: str) -> None:
        self._backend = ("127.0.0.1", backend_port)
        self._tmp = tempfile.TemporaryDirectory()
        cert_path = os.path.join(self._tmp.name, "server.pem")
        key_path = os.path.join(self._tmp.name, "server.key")
        Path(cert_path).write_text(cert_pem)
        Path(key_path).write_text(key_pem)
        os.chmod(key_path, 0o600)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=cert_path, keyfile=key_path)
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_verify_locations(cadata=ca_pem)
        self._context = context
        self._stop = threading.Event()
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(32)
        self._listener.settimeout(0.5)
        self.url = f"https://127.0.0.1:{int(self._listener.getsockname()[1])}"
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                connection, _ = self._listener.accept()
            except (TimeoutError, OSError):
                continue
            threading.Thread(target=self._handle, args=(connection,), daemon=True).start()

    def _handle(self, connection: socket.socket) -> None:
        try:
            tls = self._context.wrap_socket(connection, server_side=True)
        except (ssl.SSLError, OSError):
            connection.close()
            return
        try:
            head, body = _read_http(tls)
            if not head:
                return
            backend = socket.create_connection(self._backend, timeout=10)
            try:
                backend.sendall(_force_connection_close(head) + b"\r\n\r\n" + body)
                backend.settimeout(30)
                response = _read_until_eof(backend)
            finally:
                backend.close()
            tls.sendall(response)
        except (ssl.SSLError, OSError):
            # the caller already timed out or the backend is paused: the
            # connection is dropped, which the caller observes as a failure.
            return
        finally:
            tls.close()

    def close(self) -> None:
        self._stop.set()
        self._listener.close()
        self._thread.join(timeout=5)
        self._tmp.cleanup()


@dataclass(frozen=True)
class _Mtls:
    context: ssl.SSLContext
    key_thumbprint: str
    workload: WorkloadIdentity
    opa: str
    keycloak: str
    openbao: str


# --------------------------------------------------------------------------- #
# Fixtures (real backends; an unavailable backend fails the case)
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def env() -> dict[str, str]:
    path = _env_file()
    if path is None:
        pytest.fail("ocor-bootstrap env file not found; real control-plane credentials are mandatory for BA-08")
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            values[key] = value
    for key in ("OCOR_LOCAL_KEYCLOAK_PASSWORD", "OCOR_LOCAL_OPENBAO_TOKEN"):
        if not values.get(key):
            pytest.fail(f"{key} is missing from the ocor-bootstrap env file")
    return values


@pytest.fixture(scope="module")
def live_stack(env: dict[str, str]) -> None:
    for label, url in SERVICE_URLS.items():
        if not _reachable(url, timeout=5.0):
            pytest.fail(f"{label} is unreachable; the real control plane is mandatory qualifying evidence for BA-08")
    state = _container_state(SPIRE_AGENT_CONTAINER)
    if not state.get("Running"):
        pytest.fail(
            f"SPIRE agent container is not running (state={state.get('Status')}, "
            f"OOMKilled={state.get('OOMKilled')}, exit={state.get('ExitCode')}); real SPIFFE mTLS is mandatory"
        )


@pytest.fixture(scope="module")
def mtls(live_stack: None) -> Iterator[_Mtls]:
    spire = SpireWorkloadIdentityProvider(
        agent_container=SPIRE_AGENT_CONTAINER, socket_path=SPIRE_SOCKET, expected_spiffe_id=EXPECTED_SPIFFE_ID
    )
    try:
        workload = spire.current()
        context = spire.mtls_context()
    except SecurityControlError as error:
        state = _container_state(SPIRE_AGENT_CONTAINER)
        pytest.fail(f"real SPIRE workload identity unavailable: {error} (agent state={state.get('Status')})")
    svid = _fetch_svid_json()
    chain = _split_der_chain(_b64_decode(str(svid["x509_svid"])))
    cert_pem = "".join(_der_to_pem(der, "CERTIFICATE") for der in chain)
    key_pem = _der_to_pem(_b64_decode(str(svid["x509_svid_key"])), "PRIVATE KEY")
    ca_pem = _der_to_pem(_b64_decode(str(svid["bundle"])), "CERTIFICATE")
    proxies = [_MtlsProxy(port, cert_pem, key_pem, ca_pem) for port in (8181, 8080, 8200)]
    try:
        yield _Mtls(
            context=context,
            key_thumbprint=workload_key_thumbprint(context),
            workload=workload,
            opa=proxies[0].url,
            keycloak=proxies[1].url,
            openbao=proxies[2].url,
        )
    finally:
        for proxy in proxies:
            proxy.close()


@pytest.fixture(scope="module")
def principals(live_stack: None, env: dict[str, str]) -> None:
    status, body = _http(
        "POST",
        f"{KC}/realms/master/protocol/openid-connect/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=(
            "client_id=admin-cli&username=ocor-admin"
            f"&password={urllib.parse.quote(env['OCOR_LOCAL_KEYCLOAK_PASSWORD'])}&grant_type=password"
        ),
    )
    assert status == 200, f"Keycloak admin token: HTTP {status}"
    headers = {"Authorization": f"Bearer {json.loads(body)['access_token']}"}
    json_headers = {**headers, "Content-Type": "application/json"}
    status, body = _http("GET", f"{KC}/admin/realms/{REALM}/clients?clientId={CLIENT_ID}", headers=headers)
    assert status == 200, f"client lookup: HTTP {status}"
    if not json.loads(body):
        client = {
            "clientId": CLIENT_ID, "enabled": True, "publicClient": True, "directAccessGrantsEnabled": True,
            "standardFlowEnabled": False, "protocol": "openid-connect", "redirectUris": [f"{KC}/*"],
        }
        status, _ = _http("POST", f"{KC}/admin/realms/{REALM}/clients", headers=json_headers, body=json.dumps(client))
        assert status in (200, 201), f"create client: HTTP {status}"
    status, body = _http("GET", f"{KC}/admin/realms/{REALM}/users?username={USERNAME}", headers=headers)
    assert status == 200, f"user lookup: HTTP {status}"
    users = json.loads(body)
    if not users:
        user = {
            "username": USERNAME, "enabled": True, "firstName": "Analyst", "lastName": "One",
            "email": f"{USERNAME}@ocor.test", "emailVerified": True,
        }
        status, _ = _http("POST", f"{KC}/admin/realms/{REALM}/users", headers=json_headers, body=json.dumps(user))
        assert status in (200, 201), f"create user: HTTP {status}"
        status, body = _http("GET", f"{KC}/admin/realms/{REALM}/users?username={USERNAME}", headers=headers)
        users = json.loads(body)
    uid = users[0]["id"]
    if not users[0].get("email"):
        updated = {**users[0], "email": f"{USERNAME}@ocor.test", "emailVerified": True}
        status, _ = _http("PUT", f"{KC}/admin/realms/{REALM}/users/{uid}", headers=json_headers, body=json.dumps(updated))
        assert status == 204, f"set synthetic email: HTTP {status}"
    credential = json.dumps({"type": "password", "value": USER_PWD, "temporary": False})
    status, _ = _http(
        "PUT", f"{KC}/admin/realms/{REALM}/users/{uid}/reset-password", headers=json_headers, body=credential
    )
    assert status == 204, f"reset password: HTTP {status}"


@pytest.fixture
def principal(principals: None, mtls: _Mtls) -> AuthenticatedPrincipal:
    provider = KeycloakIdentityProvider(
        mtls.keycloak, REALM, CLIENT_ID,
        password_resolver=lambda user: USER_PWD if user == USERNAME else "",
        ssl_context=mtls.context,
    )
    return provider.authenticate(IdentityRequest(f"urn:ocor:credential-ref:{USERNAME}", "account", str(uuid.uuid4())))


@pytest.fixture
def opa(principal: AuthenticatedPrincipal, mtls: _Mtls) -> tuple[OpaPolicyDecisionProvider, str]:
    provider = OpaPolicyDecisionProvider(
        mtls.opa,
        POLICY_ID,
        signer_public_key=(_SIGNER_N, _SIGNER_E),
        delegation_signer_public_key=(_SIGNER_N, _SIGNER_E),
        timeout_seconds=POLICY_AUTHORITY_TIMEOUT_S,
        ssl_context=mtls.context,
    )
    digest = provider.install_policy(_sign_bundle(_rego(principal.principal_id)))
    return provider, digest


# --------------------------------------------------------------------------- #
# The command boundary under test (composition of sealed controls)
# --------------------------------------------------------------------------- #


@dataclass
class _Attempt:
    started: datetime
    finished: datetime
    accepted: bool
    reason: str


class _CommandBoundary:
    """A command is accepted only if the stop-bound lease authorizes it, the
    real OPA decision over the signed delegation chain PERMITs it and is
    valid, and the lease authorizes it again when its use is consumed."""

    def __init__(
        self,
        *,
        authority: CapabilityAuthority,
        lease: CapabilityLease,
        opa: OpaPolicyDecisionProvider,
        principal: AuthenticatedPrincipal,
        policy_digest: str,
        grant: SignedDelegation,
    ) -> None:
        self.authority = authority
        self.lease = lease
        self.opa = opa
        self.principal = principal
        self.policy_digest = policy_digest
        self.grant = grant

    def _lease_check(self, *, consume: bool) -> None:
        self.authority.authorize(
            self.lease, COMMAND_CAPABILITY, RESOURCE, at=_now(), subject=self.principal.principal_id, consume=consume
        )

    def decide(self) -> tuple[PolicyRequest, PolicyDecision]:
        request = _request(self.principal, self.policy_digest, delegated=True)
        decision = self.opa.evaluate(request, delegation=self.grant, capability=_CAPABILITY)
        return request, decision

    def _accept(self, request: PolicyRequest, decision: PolicyDecision) -> None:
        if decision.effect is not PolicyEffect.PERMIT:
            raise SecurityControlError("POLICY_DENIED", "policy decision is not a permit")
        decision.verify(request, at=_now())
        self._lease_check(consume=True)

    def submit(self) -> None:
        """Online path: a fresh real OPA decision for every command."""
        self._lease_check(consume=False)
        request, decision = self.decide()
        self._accept(request, decision)

    def submit_with_held_decision(self, request: PolicyRequest, decision: PolicyDecision) -> None:
        """Degraded path while the policy plane is unreachable: only a decision
        obtained earlier and still inside its ``valid_until`` is usable."""
        self._lease_check(consume=False)
        self._accept(request, decision)


def _attempt(action: Callable[[], None]) -> _Attempt:
    started = _now()
    try:
        action()
    except StopEpochDenied as error:
        return _Attempt(started, _now(), False, f"StopEpochDenied: {error}")
    except AuthorizationError as error:
        return _Attempt(started, _now(), False, f"AuthorizationError: {error}")
    except SecurityControlError as error:
        return _Attempt(started, _now(), False, f"SecurityControlError:{error.reason_code}")
    return _Attempt(started, _now(), True, "ACCEPTED")


def _boundary(
    principal: AuthenticatedPrincipal,
    opa: tuple[OpaPolicyDecisionProvider, str],
    mtls: _Mtls,
    *,
    ttl: timedelta,
    stop: EmergencyStopController,
) -> _CommandBoundary:
    provider, digest = opa
    authority = CapabilityAuthority("ba-08-capability-authority", stop=stop)
    issued = _now()
    # Local expiry anchored to the workload certificate: never beyond the SVID.
    expires_at = min(issued + ttl, mtls.workload.expires_at)
    lease = authority.issue(
        subject=principal.principal_id,
        capabilities=[COMMAND_CAPABILITY],
        resources=[RESOURCE],
        issued_at=issued,
        expires_at=expires_at,
    )
    grant = _sign_grant(grantee=principal.principal_id, policy_digest=digest, key_thumbprint=mtls.key_thumbprint)
    return _CommandBoundary(
        authority=authority, lease=lease, opa=provider, principal=principal, policy_digest=digest, grant=grant
    )


# --------------------------------------------------------------------------- #
# BA-08 cases
# --------------------------------------------------------------------------- #


def test_ba_08_positive_identity_delegation_and_policy_decision_within_policy_authority_timeout(
    principal: AuthenticatedPrincipal,
    opa: tuple[OpaPolicyDecisionProvider, str],
    mtls: _Mtls,
    record_property: RecordProperty,
) -> None:
    provider, digest = opa
    # Identity: SPIFFE workload identity attested by SPIRE, principal by Keycloak.
    assert mtls.workload.spiffe_id == EXPECTED_SPIFFE_ID and mtls.workload.attested
    assert mtls.workload.expires_at > _now()
    principal.require_valid(at=_now())
    assert principal.actor_chain == (principal.principal_id,)

    # Policy: the signed bundle is what the real OPA server holds.
    status, body = _http("GET", f"{OPA}/v1/policies/{POLICY_ID}")
    assert status == 200
    raw = json.loads(body)["result"]["raw"]
    assert "urn:sha256:" + hashlib.sha256(raw.encode()).hexdigest() == digest

    grant = _sign_grant(grantee=principal.principal_id, policy_digest=digest, key_thumbprint=mtls.key_thumbprint)
    latencies: list[float] = []
    for _ in range(5):
        request = _request(principal, digest, delegated=True)
        started = time.monotonic()
        decision = provider.evaluate(request, delegation=grant, capability=_CAPABILITY)
        latencies.append(time.monotonic() - started)
        assert decision.effect is PolicyEffect.PERMIT
        decision.verify(request, at=_now())
        assert decision.policy_bundle_digest == digest

    # The same real policy denies an action it does not grant, also in time.
    denied_request = _request(principal, digest, delegated=False, action="write")
    started = time.monotonic()
    denied = provider.evaluate(denied_request)
    latencies.append(time.monotonic() - started)
    assert denied.effect is PolicyEffect.DENY

    record_property("ba08_policy_decision_latencies_s", [round(value, 4) for value in latencies])
    assert max(latencies) <= POLICY_AUTHORITY_TIMEOUT_S, f"policy decision exceeded PT3S: {latencies}"


def test_ba_08_positive_stop_drill_last_command_accepted_within_10_s_of_the_stop(
    principal: AuthenticatedPrincipal,
    opa: tuple[OpaPolicyDecisionProvider, str],
    mtls: _Mtls,
    record_property: RecordProperty,
) -> None:
    stop = EmergencyStopController()
    # The lease would stay valid for an hour: only the pushed stop and revocation can end acceptance.
    boundary = _boundary(principal, opa, mtls, ttl=timedelta(hours=1), stop=stop)
    attempts: list[_Attempt] = []
    errors: list[BaseException] = []
    stop_at: list[datetime] = []
    finished = threading.Event()

    def command_stream() -> None:
        try:
            while not stop_at or _now() < stop_at[0] + timedelta(seconds=OBSERVATION_WINDOW_S):
                attempts.append(_attempt(boundary.submit))
                time.sleep(0.02)
        except BaseException as error:  # noqa: BLE001 -- surfaced to the test thread below
            errors.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=command_stream, daemon=True)
    worker.start()
    try:
        assert _poll(lambda: sum(item.accepted for item in attempts) >= 3, timeout=30), "no command accepted before stop"
    finally:
        # Revocation push: emergency stop on the local epoch and the signed
        # revocation of the delegation grant at the policy boundary.
        instant = _now()
        stop.activate(reason="ba-08 safety drill", at=instant)
        boundary.opa.apply_revocation(_sign_revocation(boundary.grant.grant_id))
        stop_at.append(instant)
    assert finished.wait(OBSERVATION_WINDOW_S + 30), "command stream did not finish"
    worker.join(5)
    assert errors == []

    stopped = stop_at[0]
    accepted = [item for item in attempts if item.accepted]
    after = [item for item in attempts if item.started >= stopped]
    last_accepted_after_stop_s = max((item.finished - stopped).total_seconds() for item in accepted)
    record_property("ba08_push_last_accepted_after_stop_s", round(last_accepted_after_stop_s, 4))
    record_property("ba08_push_attempts_after_stop", len(after))

    assert len(accepted) >= 3
    assert last_accepted_after_stop_s <= CONTAINMENT_TARGET_S
    assert after and not any(item.accepted for item in after), "a new command was accepted after the stop"
    assert max(item.started for item in after) >= stopped + timedelta(seconds=CONTAINMENT_TARGET_S)
    assert all(item.reason.startswith("StopEpochDenied") for item in after), {item.reason for item in after}
    assert boundary.authority.usage(boundary.lease.lease_id) == len(accepted)

    # Independent second mechanism: the revocation reached the policy boundary too.
    with pytest.raises(SecurityControlError) as excinfo:
        boundary.decide()
    assert excinfo.value.reason_code == "DELEGATION_REVOKED"
    assert stop.status is StopStatus.STOPPING


def test_ba_08_negative_revocation_push_alone_refuses_while_the_lease_is_still_valid(
    principal: AuthenticatedPrincipal, opa: tuple[OpaPolicyDecisionProvider, str], mtls: _Mtls
) -> None:
    stop = EmergencyStopController()
    boundary = _boundary(principal, opa, mtls, ttl=timedelta(hours=1), stop=stop)
    assert _attempt(boundary.submit).accepted  # positive control
    assert boundary.authority.usage(boundary.lease.lease_id) == 1

    boundary.opa.apply_revocation(_sign_revocation(boundary.grant.grant_id))
    refused = _attempt(boundary.submit)
    assert not refused.accepted
    assert refused.reason == "SecurityControlError:DELEGATION_REVOKED"

    # The lease mechanism is untouched: it still authorizes, nothing was consumed.
    boundary.authority.authorize(
        boundary.lease, COMMAND_CAPABILITY, RESOURCE, at=_now(), subject=principal.principal_id
    )
    assert boundary.authority.usage(boundary.lease.lease_id) == 1
    assert stop.status is StopStatus.NORMAL


def test_ba_08_negative_stop_epoch_alone_fences_the_lease_while_policy_still_permits(
    principal: AuthenticatedPrincipal, opa: tuple[OpaPolicyDecisionProvider, str], mtls: _Mtls
) -> None:
    stop = EmergencyStopController()
    boundary = _boundary(principal, opa, mtls, ttl=timedelta(hours=1), stop=stop)
    assert _attempt(boundary.submit).accepted  # positive control
    assert boundary.authority.usage(boundary.lease.lease_id) == 1

    stop.activate(reason="ba-08 stop without revocation push", at=_now())
    refused = _attempt(boundary.submit)
    assert not refused.accepted
    assert refused.reason.startswith("StopEpochDenied"), refused.reason

    # The policy mechanism is untouched: the real OPA decision still permits.
    request, decision = boundary.decide()
    assert decision.effect is PolicyEffect.PERMIT
    decision.verify(request, at=_now())
    assert boundary.authority.usage(boundary.lease.lease_id) == 1


def test_ba_08_negative_secret_isolation_refuses_a_foreign_principal_and_path_escape(
    principal: AuthenticatedPrincipal,
    opa: tuple[OpaPolicyDecisionProvider, str],
    mtls: _Mtls,
    env: dict[str, str],
) -> None:
    _, digest = opa
    token = env["OCOR_LOCAL_OPENBAO_TOKEN"]
    secret_name = f"ba08-{uuid.uuid4().hex[:12]}"
    data_url = f"{OB}/v1/ocor/data/{principal.principal_id}/{secret_name}"
    headers = {"X-Vault-Token": token, "Content-Type": "application/json"}
    provider = OpenBaoSecretProvider(mtls.openbao, token, mount="ocor", ssl_context=mtls.context)
    gcs_digest = _gcs(principal, digest, (principal.principal_id,)).digest()
    material = uuid.uuid4().hex
    try:
        # Mount and seed through the sealed provider's own mount check first.
        bootstrap = SecretRequest(
            secret_ref=f"urn:ocor:secret-ref:{secret_name}-absent",
            principal_id=principal.principal_id,
            purpose=PURPOSE,
            governed_context_digest=gcs_digest,
            requested_at=_now(),
        )
        with pytest.raises(SecurityControlError) as absent:
            provider.lease(bootstrap, principal=principal)
        assert absent.value.reason_code == "SECRET_REFERENCE_UNRESOLVED"
        status, _ = _http("POST", data_url, headers=headers, body=json.dumps({"data": {"value": material}}))
        assert status in (200, 204), f"seed secret: HTTP {status}"

        # Positive control: the principal's own secret yields only an opaque handle.
        own = replace(bootstrap, secret_ref=f"urn:ocor:secret-ref:{secret_name}", requested_at=_now())
        lease = provider.lease(own, principal=principal)
        assert lease.handle_ref.startswith("urn:ocor:secret-handle:")
        assert material not in repr(lease)
        lease.verify(own, at=_now())

        foreign = replace(own, principal_id="urn-ocor-principal-other", requested_at=_now())
        with pytest.raises(SecurityControlError) as excinfo:
            provider.lease(foreign, principal=principal)
        assert excinfo.value.reason_code == "SECRET_BINDING_MISMATCH"

        escape = replace(own, secret_ref=f"urn:ocor:secret-ref:../{secret_name}", requested_at=_now())
        with pytest.raises(SecurityControlError) as escaped:
            provider.lease(escape, principal=principal)
        assert escaped.value.reason_code == "SECRET_REFERENCE_INVALID"

        # No state changed on the server: still exactly one version, same content.
        status, body = _http("GET", data_url, headers=headers)
        assert status == 200
        stored = json.loads(body)["data"]
        assert stored["data"] == {"value": material} and stored["metadata"]["version"] == 1
    finally:
        metadata_url = f"{OB}/v1/ocor/metadata/{principal.principal_id}/{secret_name}"
        status, _ = _http("DELETE", metadata_url, headers=headers)
        assert status in (200, 204), f"secret cleanup: HTTP {status}"
        status, _ = _http("GET", data_url, headers=headers)
        assert status == 404, "the BA-08 secret was left behind"


def test_ba_08_fault_policy_timeout_fails_closed_and_local_lease_expiry_alone_stops_commands(
    principal: AuthenticatedPrincipal,
    opa: tuple[OpaPolicyDecisionProvider, str],
    mtls: _Mtls,
    record_property: RecordProperty,
) -> None:
    stop = EmergencyStopController()
    boundary = _boundary(principal, opa, mtls, ttl=timedelta(seconds=9), stop=stop)
    lease_expiry = boundary.lease.expires_at
    assert lease_expiry <= mtls.workload.expires_at

    # Admission while the control plane is up: a real decision, held locally.
    started = time.monotonic()
    held_request, held_decision = boundary.decide()
    assert time.monotonic() - started <= POLICY_AUTHORITY_TIMEOUT_S
    assert held_decision.effect is PolicyEffect.PERMIT
    assert held_decision.valid_until > lease_expiry, "the decision, not the lease, would bound this drill"

    _docker("pause", OPA_CONTAINER)
    try:
        assert _poll(lambda: not _reachable(SERVICE_URLS["OPA"], timeout=1.0), timeout=10.0), "OPA never paused"
        # Fault: the policy authority times out -> fail closed, never a permit.
        timed = time.monotonic()
        refused = _attempt(boundary.submit)
        elapsed = time.monotonic() - timed
        assert not refused.accepted
        assert refused.reason in ("SecurityControlError:SERVICE_UNAVAILABLE", "SecurityControlError:POLICY_UNAVAILABLE")
        assert elapsed <= POLICY_AUTHORITY_TIMEOUT_S + 1.0, f"fail-closed took {elapsed:.2f}s"

        # The stop is declared now, but its push cannot reach this boundary
        # (control plane down): the local epoch and the grant stay untouched.
        stopped = _now()
        assert stop.status is StopStatus.NORMAL
        assert stopped < lease_expiry <= stopped + timedelta(seconds=CONTAINMENT_TARGET_S)
        attempts: list[_Attempt] = []
        while _now() < stopped + timedelta(seconds=OBSERVATION_WINDOW_S):
            attempts.append(_attempt(lambda: boundary.submit_with_held_decision(held_request, held_decision)))
            time.sleep(0.02)
    finally:
        _docker("unpause", OPA_CONTAINER)
        assert _poll(lambda: _reachable(SERVICE_URLS["OPA"], timeout=2.0), timeout=20.0), "OPA did not recover"
        # Leave the shared stack as found: wait until Docker reports OPA healthy again.
        assert _poll(
            lambda: _container_state(OPA_CONTAINER).get("Health", {}).get("Status") == "healthy", timeout=90.0
        ), "OPA container did not return to healthy after unpause"

    accepted = [item for item in attempts if item.accepted]
    rejected = [item for item in attempts if not item.accepted]
    last_accepted_after_stop_s = max((item.finished - stopped).total_seconds() for item in accepted)
    record_property("ba08_expiry_last_accepted_after_stop_s", round(last_accepted_after_stop_s, 4))
    record_property("ba08_expiry_lease_ttl_after_stop_s", round((lease_expiry - stopped).total_seconds(), 4))

    # Without any push, acceptance continued until -- and only until -- local expiry.
    assert accepted and rejected
    assert last_accepted_after_stop_s <= CONTAINMENT_TARGET_S
    assert max(item.started for item in accepted) < lease_expiry
    first_refusal = min(item.started for item in rejected)
    assert not any(item.accepted and item.started > first_refusal for item in attempts)
    assert all(item.started >= lease_expiry - timedelta(milliseconds=50) for item in rejected)
    assert max(item.started for item in rejected) >= stopped + timedelta(seconds=CONTAINMENT_TARGET_S)
    assert all(
        item.reason == "AuthorizationError: capability lease is inactive or out of scope" for item in rejected
    ), {item.reason for item in rejected}

    # The control plane is back: a fresh decision permits, the expired lease still refuses.
    request, decision = boundary.decide()
    assert decision.effect is PolicyEffect.PERMIT
    assert not _attempt(boundary.submit).accepted
