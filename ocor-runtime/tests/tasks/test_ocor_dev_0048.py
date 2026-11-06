"""OCOR-DEV-0048: real control-plane boundary providers (WS-11).

Least privilege (OPA), workload identity and mTLS trust (SPIFFE/SPIRE), policy
bundles (OPA), delegation (Keycloak) and secret isolation (OpenBao) are
enforced by the real services in the ``ocor-bootstrap`` stack -- never mocks.
Every positive case drives a live backend; every negative case proves a
fail-closed rejection for the right reason; every fault-injection case proves
an unreachable or stale control stops answering as a denial, not a permit.

The SPIKE counterpart (OCOR-DEV-0021) proved bounded-timeout latency and
failure semantics for the control-plane *probe*; this task proves the same
semantics on the *provider* boundary itself, reusing the sealed ports
(OCOR-DEV-0014) and the sealed fault-injection helpers (WS-12) unmodified.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

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
    verify_delegation_signature,
    verify_signed_delegation,
    workload_key_thumbprint,
)
from ocor_runtime.security.ports import (
    AuthenticatedPrincipal,
    ControlName,
    ControlStatus,
    IdentityRequest,
    PolicyEffect,
    PolicyRequest,
    SecretRequest,
    SecurityControlError,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
SCRIPTS_DIR = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

_SPEC = importlib.util.spec_from_file_location(
    "fault_inject_test_environment_0048", SCRIPTS_DIR / "fault_inject_test_environment.py"
)
assert _SPEC is not None and _SPEC.loader is not None
fault_inject = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = fault_inject
_SPEC.loader.exec_module(fault_inject)

KC = "http://127.0.0.1:8080"
OPA = "http://127.0.0.1:8181"
OB = "http://127.0.0.1:8200"
REALM = "ocor"
CLIENT_ID = "ocor-control-plane"
USERNAME = "analyst-1"
USER_PWD = "analyst-pass-123"
POLICY_ID = "ocor-control-plane"
SPIRE_AGENT_CONTAINER = "ocor-bootstrap-spire-agent-1"
SPIRE_SOCKET = "/run/spire/sockets/agent.sock"
EXPECTED_SPIFFE_ID = "spiffe://ocor.test/ocor/control-plane"

def _rego(principal_id: str) -> str:
    return (
        "package ocor.control_plane\n\n"
        "default allow := false\n\n"
        "allow if {\n"
        f'    input.principal_id == "{principal_id}"\n'
        '    input.action == "read"\n'
        '    input.resource == "urn:ocor:target:site-1"\n'
        "}\n"
    )

SERVICE_URLS = {
    "OPA": "http://127.0.0.1:8181/health",
    "Keycloak": "http://127.0.0.1:8080/realms/master/.well-known/openid-configuration",
    "OpenBao": "http://127.0.0.1:8200/v1/sys/health",
}

# Test-only policy-bundle signer (RSA-2048).  This key pair exists solely to
# prove the provider verifies a detached signature against a pinned public key;
# it is not a production credential and no private material is used elsewhere.
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


_WORKLOAD_KEY_THUMBPRINT: str | None = None


def _sign_bundle(
    rego_source: str,
    *,
    policy_id: str = POLICY_ID,
    signer: str = _SIGNER,
    not_before: datetime | None = None,
    expires_at: datetime | None = None,
) -> SignedPolicyBundle:
    not_before = not_before or _now() - timedelta(minutes=5)
    expires_at = expires_at or _now() + timedelta(hours=1)
    unsigned = SignedPolicyBundle(
        policy_id=policy_id,
        rego_source=rego_source,
        signer=signer,
        not_before=not_before,
        expires_at=expires_at,
        signature="",
    )
    signature = base64.b64encode(
        _rsa_sign(unsigned.signing_payload(), _SIGNER_N, _SIGNER_D)
    ).decode()
    return replace(unsigned, signature=signature)


def _install_policy(
    provider: OpaPolicyDecisionProvider, rego_source: str
) -> str:
    return provider.install_policy(_sign_bundle(rego_source))


def _env_file() -> Path | None:
    if os.environ.get("OCOR_BOOTSTRAP_ENV"):
        candidate = Path(os.environ["OCOR_BOOTSTRAP_ENV"])
        if candidate.exists():
            return candidate
    for candidate in (
        Path.home() / ".ocor-bootstrap-secrets" / "ocor-bootstrap.env",
        REPOSITORY_ROOT / ".ocor" / "bootstrap.env",
    ):
        if candidate.exists():
            return candidate
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".ocor" / "bootstrap.env"
        if candidate.exists():
            return candidate
    return None


def _load_env() -> dict[str, str]:
    path = _env_file()
    if path is None:
        pytest.skip(
            "ocor-bootstrap env file not found; real credentials are mandatory qualifying evidence"
        )
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            env[key] = value
    return env


def _http(method: str, url: str, *, headers: dict[str, str] | None = None, body: str | None = None):
    import urllib.error
    import urllib.request

    data = body.encode() if isinstance(body, str) else body
    req = urllib.request.Request(url, method=method, data=data)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def _now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# mTLS reverse proxy: a real TLS-terminating front that requires and verifies
# the caller's workload SVID and forwards plaintext to the local backend.  It
# exists solely to prove the providers carry the SVID on the transport, not
# merely fetch it in a separate (unused) probe.
# --------------------------------------------------------------------------- #


def _fetch_svid_json() -> dict[str, object]:
    completed = subprocess.run(
        [
            "docker",
            "exec",
            SPIRE_AGENT_CONTAINER,
            "/opt/spire/bin/spire-agent",
            "api",
            "fetch",
            "x509",
            "-socketPath",
            SPIRE_SOCKET,
            "-output",
            "json",
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip("spire-agent api fetch x509 failed; a real SVID is mandatory")
    svids = json.loads(completed.stdout.decode()).get("svids") or []
    assert svids, "no SVID returned by spire-agent"
    return svids[0]


def _server_tls_material() -> dict[str, str]:
    svid = _fetch_svid_json()
    chain = _split_der_chain(_b64_decode(str(svid["x509_svid"])))
    key_der = _b64_decode(str(svid["x509_svid_key"]))
    bundle_der = _b64_decode(str(svid["bundle"]))
    return {
        "cert_pem": "".join(_der_to_pem(der, "CERTIFICATE") for der in chain),
        "key_pem": _der_to_pem(key_der, "PRIVATE KEY"),
        "ca_pem": _der_to_pem(bundle_der, "CERTIFICATE"),
    }


def _read_http_head_and_body(sock: socket.socket) -> tuple[bytes, bytes]:
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(65536)
        if not chunk:
            break
        buf += chunk
    head, _, body = buf.partition(b"\r\n\r\n")
    content_length = 0
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            content_length = int(line.split(b":", 1)[1].strip())
    while len(body) < content_length:
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
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _set_header(head: bytes, name: bytes, value: bytes) -> bytes:
    lines = head.split(b"\r\n")
    lowered = name.lower()
    updated = False
    for i, line in enumerate(lines):
        if b":" in line and line.split(b":", 1)[0].strip().lower() == lowered:
            lines[i] = name + b": " + value
            updated = True
    if not updated:
        lines.append(name + b": " + value)
    return b"\r\n".join(lines)


class _MtlsReverseProxy:
    """TLS-terminating loopback proxy with mandatory, verified client auth."""

    def __init__(
        self,
        backend_host: str,
        backend_port: int,
        server_cert_pem: str,
        server_key_pem: str,
        client_ca_pem: str,
    ) -> None:
        self.response_delay = 0.0
        self.delayed_method: bytes | None = None
        self.delayed_path: bytes | None = None
        # One-shot hooks run around the next policy evaluation POST: the real
        # request and response still cross the real backend unmodified.
        self.before_eval: object = None
        self.after_eval: object = None
        self._backend = (backend_host, backend_port)
        self._server_cert_pem = server_cert_pem
        self._server_key_pem = server_key_pem
        self._client_ca_pem = client_ca_pem
        self._lsock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._port = 0
        self._td: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> "_MtlsReverseProxy":
        self._td = tempfile.TemporaryDirectory()
        cert_path = os.path.join(self._td.name, "server.pem")
        key_path = os.path.join(self._td.name, "server.key")
        with open(cert_path, "w") as handle:
            handle.write(self._server_cert_pem)
        with open(key_path, "w") as handle:
            handle.write(self._server_key_pem)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=cert_path, keyfile=key_path)
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_verify_locations(cadata=self._client_ca_pem)
        self._context = context
        self._lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._lsock.bind(("127.0.0.1", 0))
        self._lsock.listen(16)
        self._port = int(self._lsock.getsockname()[1])
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self

    def _serve(self) -> None:
        assert self._lsock is not None
        while not self._stop.is_set():
            try:
                self._lsock.settimeout(0.5)
                conn, _ = self._lsock.accept()
            except (socket.timeout, OSError):
                continue
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        try:
            tls = self._context.wrap_socket(conn, server_side=True)
        except (ssl.SSLError, OSError):
            conn.close()
            return
        try:
            head, body = _read_http_head_and_body(tls)
            if not head:
                return
            head = _set_header(head, b"Connection", b"close")
            is_eval = head.startswith(b"POST /v1/data/ocor/control_plane/allow")
            before, after = (self.before_eval, self.after_eval) if is_eval else (None, None)
            if is_eval:
                self.before_eval = self.after_eval = None
            if callable(before):
                before()
            backend = socket.create_connection(self._backend, timeout=10)
            try:
                backend.sendall(head + b"\r\n\r\n" + body)
                backend.settimeout(30)
                response = _read_until_eof(backend)
            finally:
                backend.close()
            if callable(after):
                after()
            if (self.response_delay
                    and (self.delayed_method is None or head.startswith(self.delayed_method+b" "))
                    and (self.delayed_path is None or head.split(b" ")[1] == self.delayed_path)):
                time.sleep(self.response_delay)
            tls.sendall(response)
        except (ssl.SSLError, OSError):
            pass
        finally:
            tls.close()

    @property
    def url(self) -> str:
        return f"https://127.0.0.1:{self._port}"

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._lsock is not None:
            try:
                self._lsock.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._td is not None:
            self._td.cleanup()


# --------------------------------------------------------------------------- #
# mTLS fixtures: a session-scoped client context carrying the real workload
# SVID plus three TLS-terminating reverse proxies that require and verify the
# caller's certificate before forwarding to the plaintext local backend.
# --------------------------------------------------------------------------- #


def _tls_handshake(url: str, context: ssl.SSLContext) -> dict[str, object]:
    host = "127.0.0.1"
    port = int(url.rsplit(":", 1)[1])
    with socket.create_connection((host, port), timeout=10) as raw:
        with context.wrap_socket(raw, server_hostname=host) as tls:
            tls.do_handshake()
            return tls.getpeercert() or {}


@pytest.fixture(scope="session")
def mtls(live_stack: None) -> dict[str, object]:
    if not fault_inject.container_healthy(SPIRE_AGENT_CONTAINER):
        pytest.skip("SPIRE agent container is unavailable; real mTLS is mandatory")
    provider = SpireWorkloadIdentityProvider(
        agent_container=SPIRE_AGENT_CONTAINER,
        socket_path=SPIRE_SOCKET,
        expected_spiffe_id=EXPECTED_SPIFFE_ID,
    )
    client_context = provider.mtls_context()
    global _WORKLOAD_KEY_THUMBPRINT
    _WORKLOAD_KEY_THUMBPRINT = workload_key_thumbprint(client_context)
    material = _server_tls_material()
    proxies: list[_MtlsReverseProxy] = []
    for backend_port in (8181, 8080, 8200):
        proxy = _MtlsReverseProxy(
            "127.0.0.1",
            backend_port,
            material["cert_pem"],
            material["key_pem"],
            material["ca_pem"],
        )
        proxy.__enter__()
        proxies.append(proxy)
    try:
        yield {
            "ssl_context": client_context,
            "proxies": proxies,
            "opa": proxies[0].url,
            "keycloak": proxies[1].url,
            "openbao": proxies[2].url,
        }
    finally:
        for proxy in proxies:
            proxy.__exit__(None, None, None)







@pytest.fixture(scope="session")
def env() -> dict[str, str]:
    return _load_env()


@pytest.fixture(scope="session")
def live_stack(env: dict[str, str]) -> None:
    for label, url in SERVICE_URLS.items():
        if not fault_inject.http_reachable(url, timeout=5.0):
            pytest.skip(f"{label} is unreachable; real services are mandatory qualifying evidence")


@pytest.fixture(scope="session")
def admin_token(live_stack: None, env: dict[str, str]) -> str:
    import json
    import urllib.parse

    status, body = _http(
        "POST",
        f"{KC}/realms/master/protocol/openid-connect/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=(
            "client_id=admin-cli"
            f"&username=ocor-admin&password={urllib.parse.quote(env['OCOR_LOCAL_KEYCLOAK_PASSWORD'])}"
            "&grant_type=password"
        ),
    )
    assert status == 200, f"Keycloak admin token: HTTP {status} {body}"
    return json.loads(body)["access_token"]


@pytest.fixture(scope="session")
def principals(admin_token: str) -> None:
    import json

    headers = {"Authorization": f"Bearer {admin_token}"}
    status, body = _http(
        "GET", f"{KC}/admin/realms/{REALM}/clients?clientId={CLIENT_ID}", headers=headers
    )
    assert status == 200, f"client lookup: HTTP {status} {body}"
    clients = json.loads(body)
    if not clients:
        payload = json.dumps(
            {
                "clientId": CLIENT_ID,
                "enabled": True,
                "publicClient": True,
                "directAccessGrantsEnabled": True,
                "standardFlowEnabled": False,
                "protocol": "openid-connect",
                "redirectUris": ["http://127.0.0.1:8080/*"],
            }
        )
        status, body = _http(
            "POST",
            f"{KC}/admin/realms/{REALM}/clients",
            headers={**headers, "Content-Type": "application/json"},
            body=payload,
        )
        assert status in (200, 201), f"create client: HTTP {status} {body}"

    status, body = _http(
        "GET", f"{KC}/admin/realms/{REALM}/users?username={USERNAME}", headers=headers
    )
    assert status == 200, f"user lookup: HTTP {status} {body}"
    users = json.loads(body)
    if not users:
        payload = json.dumps(
            {
                "username": USERNAME,
                "enabled": True,
                "firstName": "Analyst",
                "lastName": "One",
                "email": f"{USERNAME}@ocor.test",
                "emailVerified": True,
            }
        )
        status, body = _http(
            "POST",
            f"{KC}/admin/realms/{REALM}/users",
            headers={**headers, "Content-Type": "application/json"},
            body=payload,
        )
        assert status in (200, 201), f"create user: HTTP {status} {body}"
        status, body = _http(
            "GET", f"{KC}/admin/realms/{REALM}/users?username={USERNAME}", headers=headers
        )
        users = json.loads(body)
    uid = users[0]["id"]
    if not users[0].get("email"):
        # The Keycloak 26 default user profile requires an email: without it a
        # freshly provisioned realm answers "Account is not fully set up".
        status, body = _http(
            "PUT",
            f"{KC}/admin/realms/{REALM}/users/{uid}",
            headers={**headers, "Content-Type": "application/json"},
            body=json.dumps({**users[0], "email": f"{USERNAME}@ocor.test", "emailVerified": True}),
        )
        assert status == 204, f"set synthetic email: HTTP {status} {body}"
    payload = json.dumps({"type": "password", "value": USER_PWD, "temporary": False})
    status, body = _http(
        "PUT",
        f"{KC}/admin/realms/{REALM}/users/{uid}/reset-password",
        headers={**headers, "Content-Type": "application/json"},
        body=payload,
    )
    assert status == 204, f"reset password: HTTP {status} {body}"


@pytest.fixture
def principal(principals: None, mtls: dict[str, object]) -> AuthenticatedPrincipal:
    provider = KeycloakIdentityProvider(
        str(mtls["keycloak"]),
        REALM,
        CLIENT_ID,
        password_resolver=lambda u: USER_PWD if u == USERNAME else "",
        ssl_context=mtls["ssl_context"],
    )
    return provider.authenticate(
        IdentityRequest(f"urn:ocor:credential-ref:{USERNAME}", "account", str(uuid.uuid4()))
    )


@pytest.fixture
def opa(
    principal: AuthenticatedPrincipal, mtls: dict[str, object]
) -> tuple[OpaPolicyDecisionProvider, str]:
    provider = OpaPolicyDecisionProvider(
        str(mtls["opa"]), POLICY_ID, signer_public_key=(_SIGNER_N, _SIGNER_E), ssl_context=mtls["ssl_context"]
    )
    digest = _install_policy(provider, _rego(principal.principal_id))
    return provider, digest


def _gcs(principal: AuthenticatedPrincipal, policy_digest: str) -> GovernedContext:
    return GovernedContext(
        tenant_id="tenant-a",
        organization_id="org-a",
        domain_id="domain-a",
        compartments=("compartment-a",),
        classification_marking_ref="urn:sha256:" + "0" * 64,
        purpose="read-site-1",
        effective_principal_id=principal.principal_id,
        actor_chain=(principal.principal_id,),
        ontology_release_digest="urn:sha256:" + "1" * 64,
        policy_bundle_digest=policy_digest,
        correlation_id=str(uuid.uuid4()),
    )


def _policy_request(
    principal: AuthenticatedPrincipal, policy_digest: str, action: str = "read"
) -> PolicyRequest:
    gcs = _gcs(principal, policy_digest)
    return PolicyRequest(
        principal=principal,
        action=action,
        resource="urn:ocor:target:site-1",
        governed_context=gcs,
        governed_context_digest=gcs.digest(),
        at=_now(),
    )


# --------------------------------------------------------------------------- #
# Unit: pure fail-closed parsing helpers (no live backend, no mock)
# --------------------------------------------------------------------------- #


def test_sha256_urn_and_b64_decode_are_deterministic():
    from ocor_runtime.security.control_plane import _b64_decode, _b64url_decode, _sha256_urn

    payload = b"ocor"
    digest = _sha256_urn(payload)
    assert digest == "urn:sha256:" + hashlib.sha256(payload).hexdigest()
    assert _sha256_urn(payload) == digest

    import base64

    assert _b64_decode(base64.b64encode(payload).decode()) == payload
    assert _b64url_decode(base64.urlsafe_b64encode(payload).decode()) == payload


def test_split_der_chain_and_tlv_parse_synthetic_concatenation():
    from ocor_runtime.security.control_plane import _split_der_chain, _tlv

    # a SEQUENCE of 3 content bytes parses to (tag=0x30, len=3, start=2, end=5)
    assert _tlv(b"\x30\x03\x01\x02\x03", 0) == (0x30, 3, 2, 5)
    # two concatenated single-byte certs split into exactly two entries
    assert _split_der_chain(b"\x30\x01\x00" + b"\x30\x01\x00") == [b"\x30\x01\x00", b"\x30\x01\x00"]
    # an empty blob yields no certs; the provider's own len(chain) < 2 fence rejects it
    assert _split_der_chain(b"") == []


# --------------------------------------------------------------------------- #
# Keycloak: delegation chain and least-privilege identity, fail-closed
# --------------------------------------------------------------------------- #


def test_authenticate_real_keycloak_principal(principal: AuthenticatedPrincipal):
    # principal_id is the immutable Keycloak subject (sub), never the username
    assert principal.principal_id != USERNAME
    assert principal.principal_id == principal.actor_chain[-1]
    assert principal.assurance_level in ("LEVEL_1", "LEVEL_2")
    assert principal.session_id


def test_wrong_password_fails_closed(principals: None, mtls: dict[str, object]):
    provider = KeycloakIdentityProvider(
        str(mtls["keycloak"]),
        REALM,
        CLIENT_ID,
        password_resolver=lambda u: "wrong",
        ssl_context=mtls["ssl_context"],
    )
    with pytest.raises(SecurityControlError) as excinfo:
        provider.authenticate(
            IdentityRequest(f"urn:ocor:credential-ref:{USERNAME}", "account", str(uuid.uuid4()))
        )
    assert excinfo.value.reason_code == "IDENTITY_REJECTED"


def test_wrong_audience_fails_closed(principals: None, mtls: dict[str, object]):
    provider = KeycloakIdentityProvider(
        str(mtls["keycloak"]),
        REALM,
        CLIENT_ID,
        password_resolver=lambda u: USER_PWD,
        ssl_context=mtls["ssl_context"],
    )
    with pytest.raises(SecurityControlError) as excinfo:
        provider.authenticate(
            IdentityRequest(
                f"urn:ocor:credential-ref:{USERNAME}", "urn:ocor:audience:gateway", str(uuid.uuid4())
            )
        )
    assert excinfo.value.reason_code == "IDENTITY_REJECTED"


# --------------------------------------------------------------------------- #
# OPA: least privilege, signed policy bundle, stale-bundle fence
# --------------------------------------------------------------------------- #


def test_policy_install_persists_and_returns_content_digest(
    principal: AuthenticatedPrincipal, opa: tuple[OpaPolicyDecisionProvider, str]
):
    provider, digest = opa
    source = _rego(principal.principal_id)
    assert digest == "urn:sha256:" + hashlib.sha256(source.encode()).hexdigest()
    assert provider._fetch_policy_source() == source


def test_policy_permit_for_matching_governed_input(
    principal: AuthenticatedPrincipal, opa: tuple[OpaPolicyDecisionProvider, str]
):
    provider, digest = opa
    request = _policy_request(principal, digest, action="read")
    decision = provider.evaluate(request)
    assert decision.effect is PolicyEffect.PERMIT
    decision.verify(request, at=_now())


def test_policy_deny_for_non_matching_action(
    principal: AuthenticatedPrincipal, opa: tuple[OpaPolicyDecisionProvider, str]
):
    provider, digest = opa
    decision = provider.evaluate(_policy_request(principal, digest, action="delete"))
    assert decision.effect is PolicyEffect.DENY


def test_policy_receives_all_governed_attributes(
    principal: AuthenticatedPrincipal, mtls: dict[str, object]
):
    provider = OpaPolicyDecisionProvider(
        str(mtls["opa"]),
        POLICY_ID,
        signer_public_key=(_SIGNER_N, _SIGNER_E),
        ssl_context=mtls["ssl_context"],
    )
    rego = (
        "package ocor.control_plane\n\n"
        "default allow := false\n\n"
        "allow if {\n"
        '    input.tenant_id == "tenant-a"\n'
        '    input.organization_id == "org-a"\n'
        '    input.domain_id == "domain-a"\n'
        '    input.compartments == ["compartment-a"]\n'
        '    input.classification_marking_ref == "urn:sha256:' + "0" * 64 + '"\n'
        "    input.effective_principal_id == input.principal_id\n"
        "    input.actor_chain[_] == input.principal_id\n"
        '    input.action == "read"\n'
        '    input.resource == "urn:ocor:target:site-1"\n'
        "}\n"
    )
    digest = _install_policy(provider, rego)
    request = _policy_request(principal, digest, action="read")
    decision = provider.evaluate(request)
    assert decision.effect is PolicyEffect.PERMIT


def test_policy_denies_when_tenant_is_not_forwarded(
    principal: AuthenticatedPrincipal, mtls: dict[str, object]
):
    provider = OpaPolicyDecisionProvider(
        str(mtls["opa"]),
        POLICY_ID,
        signer_public_key=(_SIGNER_N, _SIGNER_E),
        ssl_context=mtls["ssl_context"],
    )
    rego = (
        "package ocor.control_plane\n\n"
        "default allow := false\n\n"
        "allow if {\n"
        '    input.tenant_id == "tenant-b"\n'
        '    input.action == "read"\n'
        "}\n"
    )
    digest = _install_policy(provider, rego)
    # The governed context is tenant-a; if tenant_id were silently omitted the
    # comparison would be undefined, but it must be forwarded and denied here.
    request = _policy_request(principal, digest, action="read")
    decision = provider.evaluate(request)
    assert decision.effect is PolicyEffect.DENY


def test_stale_bundle_fails_closed(
    principal: AuthenticatedPrincipal, opa: tuple[OpaPolicyDecisionProvider, str]
):
    provider, digest = opa
    _http(
        "PUT",
        f"{OPA}/v1/policies/{POLICY_ID}",
        headers={"Content-Type": "text/plain"},
        body=_rego(principal.principal_id) + "# drift\n",
    )
    with pytest.raises(SecurityControlError) as excinfo:
        provider.evaluate(_policy_request(principal, digest, action="read"))
    assert excinfo.value.reason_code == "STALE_BUNDLE"


def test_installed_bundle_expiry_fails_closed_at_decision_time(
    principal: AuthenticatedPrincipal, mtls: dict[str, object]
):
    # A bundle installed while still valid must not keep authorising after its
    # validity window closes: the freshness fence re-checks ``expires_at`` on
    # every decision, so a permit cannot outlive the bundle that granted it.
    provider = OpaPolicyDecisionProvider(
        str(mtls["opa"]),
        POLICY_ID,
        signer_public_key=(_SIGNER_N, _SIGNER_E),
        ssl_context=mtls["ssl_context"],
    )
    digest = provider.install_policy(
        _sign_bundle(_rego(principal.principal_id), expires_at=_now() + timedelta(seconds=2))
    )
    request = _policy_request(principal, digest, action="read")
    assert provider.evaluate(request).effect is PolicyEffect.PERMIT
    time.sleep(3.0)
    with pytest.raises(SecurityControlError) as excinfo:
        provider.evaluate(_policy_request(principal, digest, action="read"))
    assert excinfo.value.reason_code == "POLICY_BUNDLE_WINDOW_INVALID"


def test_unsigned_module_cannot_extend_governed_package(
    principal: AuthenticatedPrincipal, mtls: dict[str, object]
):
    # A module dropped into the governed OPA package without a signed bundle
    # must not silently extend the decision.  The freshness fence lists every
    # evaluated module and rejects any unsolicited member of the governed
    # package before the (now widened) policy is ever consulted.
    provider = OpaPolicyDecisionProvider(
        str(mtls["opa"]),
        POLICY_ID,
        signer_public_key=(_SIGNER_N, _SIGNER_E),
        ssl_context=mtls["ssl_context"],
    )
    digest = _install_policy(provider, _rego(principal.principal_id))
    request = _policy_request(principal, digest, action="erase")
    # Positive control: the signed bundle alone denies the erase action.
    assert provider.evaluate(request).effect is PolicyEffect.DENY

    extra_id = "unsigned-extension"
    unsigned = 'package ocor.control_plane\n\nallow if { input.action == "erase" }\n'
    status, _ = _http(
        "PUT",
        f"{OPA}/v1/policies/{extra_id}",
        headers={"Content-Type": "text/plain"},
        body=unsigned,
    )
    assert status == 200
    try:
        with pytest.raises(SecurityControlError) as excinfo:
            provider.evaluate(request)
        assert excinfo.value.reason_code == "STALE_BUNDLE"
    finally:
        _http("DELETE", f"{OPA}/v1/policies/{extra_id}")


# --------------------------------------------------------------------------- #
# SPIFFE/SPIRE: workload identity and mTLS trust verification
# --------------------------------------------------------------------------- #


@pytest.fixture
def spire(env: dict[str, str]) -> SpireWorkloadIdentityProvider:
    if not fault_inject.container_healthy(SPIRE_AGENT_CONTAINER):
        pytest.skip("SPIRE agent container is unavailable; a real workload identity is mandatory")
    return SpireWorkloadIdentityProvider(
        agent_container=SPIRE_AGENT_CONTAINER,
        socket_path=SPIRE_SOCKET,
        expected_spiffe_id=EXPECTED_SPIFFE_ID,
    )


def test_workload_identity_is_fetched_and_verified(spire: SpireWorkloadIdentityProvider):
    identity = spire.current()
    assert identity.spiffe_id == EXPECTED_SPIFFE_ID
    assert identity.attested is True
    assert identity.svid_ref.startswith("urn:sha256:")
    identity.require_valid(at=_now())


def test_unexpected_spiffe_id_fails_closed(env: dict[str, str]):
    if not fault_inject.container_healthy(SPIRE_AGENT_CONTAINER):
        pytest.skip("SPIRE agent container is unavailable; a real workload identity is mandatory")
    provider = SpireWorkloadIdentityProvider(
        agent_container=SPIRE_AGENT_CONTAINER,
        socket_path=SPIRE_SOCKET,
        expected_spiffe_id="spiffe://ocor.test/ocor/wrong",
    )
    with pytest.raises(SecurityControlError) as excinfo:
        provider.current()
    assert excinfo.value.reason_code == "WORKLOAD_IDENTITY_UNAVAILABLE"




# --------------------------------------------------------------------------- #
# mTLS transport: the providers present their workload SVID on the wire and
# verify the peer against the trust bundle; without either, they fail closed.
# --------------------------------------------------------------------------- #


def test_provider_requires_mtls_context():
    # Constructing a provider without a mutual-TLS context is an outright
    # refusal, not a silent downgrade to plaintext HTTP.
    with pytest.raises(SecurityControlError) as excinfo:
        OpaPolicyDecisionProvider(OPA, POLICY_ID, signer_public_key=(_SIGNER_N, _SIGNER_E))
    assert excinfo.value.reason_code == "MTLS_REQUIRED"


def test_opa_provider_rejects_plaintext_base_url():
    # An authenticated policy flow must never perform credentialed I/O over
    # plaintext HTTP: an http:// base URL is rejected at the I/O boundary,
    # before any socket is opened, even with a mutual-TLS-capable context.
    provider = OpaPolicyDecisionProvider(
        OPA,
        POLICY_ID,
        signer_public_key=(_SIGNER_N, _SIGNER_E),
        ssl_context=ssl.create_default_context(),
    )
    with pytest.raises(SecurityControlError) as excinfo:
        _install_policy(provider, _rego("urn:ocor:principal:plaintext-opa"))
    assert excinfo.value.reason_code == "MTLS_REQUIRED"
    assert "HTTPS" in str(excinfo.value)


def test_keycloak_provider_rejects_plaintext_base_url():
    provider = KeycloakIdentityProvider(
        KC,
        REALM,
        CLIENT_ID,
        password_resolver=lambda u: "x",
        ssl_context=ssl.create_default_context(),
    )
    with pytest.raises(SecurityControlError) as excinfo:
        provider.authenticate(
            IdentityRequest(f"urn:ocor:credential-ref:{USERNAME}", "account", str(uuid.uuid4()))
        )
    assert excinfo.value.reason_code == "MTLS_REQUIRED"
    assert "HTTPS" in str(excinfo.value)


def test_openbao_provider_rejects_plaintext_base_url():
    provider = OpenBaoSecretProvider(
        OB, "token", mount="ocor", ssl_context=ssl.create_default_context()
    )
    request = SecretRequest(
        secret_ref="urn:ocor:secret-ref:plaintext-openbao",
        principal_id="plaintext-openbao",
        purpose="read-site-1",
        governed_context_digest=f"urn:sha256:{'0' * 64}",
        requested_at=_now(),
    )
    # A correctly bound principal reaches the transport check, which must
    # refuse plaintext before any socket is opened.
    principal = AuthenticatedPrincipal(
        principal_id="plaintext-openbao",
        session_id="plaintext-session",
        actor_chain=("plaintext-openbao",),
        assurance_level="LEVEL_2",
        authenticated_at=_now() - timedelta(minutes=1),
        expires_at=_now() + timedelta(minutes=5),
        status=ControlStatus.available(
            ControlName.IDENTITY, observed_at=_now(), source_digest="urn:sha256:" + "2" * 64
        ),
    )
    with pytest.raises(SecurityControlError) as excinfo:
        provider.lease(request, principal=principal)
    assert excinfo.value.reason_code == "MTLS_REQUIRED"
    assert "HTTPS" in str(excinfo.value)


def test_mtls_transport_presents_and_verifies_workload_svid(mtls: dict[str, object]):
    # A successful handshake here means the provider-side context both presented
    # a client SVID that the proxy accepted and verified the proxy's SVID chain
    # against the SPIRE trust bundle (the context requires CERT_REQUIRED).
    peer = _tls_handshake(str(mtls["opa"]), mtls["ssl_context"])
    assert peer, "mutual-TLS handshake completed but no peer certificate was parsed"


def test_mtls_server_rejects_absent_client_certificate(mtls: dict[str, object]):
    # The reverse proxy requires and verifies a client certificate: a peer that
    # presents none is rejected, proving the "mutual" half of mTLS is enforced
    # by the server side, not merely claimed by the client.  With TLS 1.3 the
    # client may see its own Finished before the server's rejection lands, so
    # we drive a full request and require either a transport error or the
    # absence of any well-formed HTTP response.
    no_cert = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    no_cert.check_hostname = False
    no_cert.verify_mode = ssl.CERT_NONE
    host = "127.0.0.1"
    port = int(str(mtls["opa"]).rsplit(":", 1)[1])
    rejected = False
    with socket.create_connection((host, port), timeout=10) as raw:
        with no_cert.wrap_socket(raw, server_hostname=host) as tls:
            try:
                tls.do_handshake()
                tls.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
                data = tls.recv(4096)
            except (ssl.SSLError, OSError):
                rejected = True
            else:
                rejected = not data.startswith(b"HTTP/")
    assert rejected, "server accepted an anonymous peer without a client certificate"



# --------------------------------------------------------------------------- #
# OpenBao: secret isolation, opaque handle, fail-closed
# --------------------------------------------------------------------------- #


def _seed_secret(
    env: dict[str, str], principal_id: str, secret_name: str, data: dict[str, str]
) -> None:
    status, body = _http(
        "POST",
        f"{OB}/v1/ocor/data/{principal_id}/{secret_name}",
        headers={
            "X-Vault-Token": env["OCOR_LOCAL_OPENBAO_TOKEN"],
            "Content-Type": "application/json",
        },
        body=json.dumps({"data": data}),
    )
    assert status in (200, 204), f"seed secret: HTTP {status} {body}"


def test_secret_lease_returns_opaque_handle(
    principal: AuthenticatedPrincipal,
    env: dict[str, str],
    opa: tuple[OpaPolicyDecisionProvider, str],
    mtls: dict[str, object],
):
    _, policy_digest = opa
    _seed_secret(
        env, principal.principal_id, "control-plane-db",
        {"dsn": "postgres://ocor:secret@control-plane-db/ocor"},
    )
    provider = OpenBaoSecretProvider(
        str(mtls["openbao"]), env["OCOR_LOCAL_OPENBAO_TOKEN"], mount="ocor", ssl_context=mtls["ssl_context"]
    )
    gcs = _gcs(principal, policy_digest)
    request = SecretRequest(
        secret_ref="urn:ocor:secret-ref:control-plane-db",
        principal_id=principal.principal_id,
        purpose="read-site-1",
        governed_context_digest=gcs.digest(),
        requested_at=_now(),
    )
    lease = provider.lease(request, principal=principal)
    assert lease.handle_ref.startswith("urn:ocor:secret-handle:")
    assert lease.secret_ref == request.secret_ref
    lease.verify(request, at=_now())


def test_wrong_openbao_token_fails_closed(
    principal: AuthenticatedPrincipal,
    opa: tuple[OpaPolicyDecisionProvider, str],
    mtls: dict[str, object],
):
    _, policy_digest = opa
    provider = OpenBaoSecretProvider(
        str(mtls["openbao"]), "wrong-token", mount="ocor", ssl_context=mtls["ssl_context"]
    )
    gcs = _gcs(principal, policy_digest)
    request = SecretRequest(
        secret_ref="urn:ocor:secret-ref:control-plane-db",
        principal_id=principal.principal_id,
        purpose="read-site-1",
        governed_context_digest=gcs.digest(),
        requested_at=_now(),
    )
    with pytest.raises(SecurityControlError) as excinfo:
        provider.lease(request, principal=principal)
    assert excinfo.value.reason_code == "SECRETS_UNAVAILABLE"


def test_secret_ref_cannot_escape_principal_scope(
    principal: AuthenticatedPrincipal,
    env: dict[str, str],
    opa: tuple[OpaPolicyDecisionProvider, str],
    mtls: dict[str, object],
):
    # A secret reference is interpolated into an OpenBao kv-v2 path; a crafted
    # reference carrying a path segment must be rejected outright rather than
    # resolved outside the principal's scope.
    _, policy_digest = opa
    provider = OpenBaoSecretProvider(
        str(mtls["openbao"]), env["OCOR_LOCAL_OPENBAO_TOKEN"], mount="ocor", ssl_context=mtls["ssl_context"]
    )
    gcs = _gcs(principal, policy_digest)
    request = SecretRequest(
        secret_ref="urn:ocor:secret-ref:../victim/isolation-fixture",
        principal_id=principal.principal_id,
        purpose="read-site-1",
        governed_context_digest=gcs.digest(),
        requested_at=_now(),
    )
    with pytest.raises(SecurityControlError) as excinfo:
        provider.lease(request, principal=principal)
    assert excinfo.value.reason_code == "SECRET_REFERENCE_INVALID"


# --------------------------------------------------------------------------- #
# Fault injection: a paused control plane stops answering as a denial
# --------------------------------------------------------------------------- #


def test_paused_opa_fails_closed_within_bounded_timeout(
    principal: AuthenticatedPrincipal, mtls: dict[str, object]
):
    provider = OpaPolicyDecisionProvider(
        str(mtls["opa"]),
        POLICY_ID,
        signer_public_key=(_SIGNER_N, _SIGNER_E),
        timeout_seconds=2.0,
        ssl_context=mtls["ssl_context"],
    )
    digest = _install_policy(provider, _rego(principal.principal_id))
    request = _policy_request(principal, digest, action="read")
    provider.evaluate(request)

    pause = fault_inject.run(
        fault_inject.fault_command("opa", "pause"), cwd=REPOSITORY_ROOT, timeout=30
    )
    assert pause.returncode == 0, pause.stderr
    try:
        detected = fault_inject._poll(
            lambda: not fault_inject.http_reachable(SERVICE_URLS["OPA"], timeout=1.0), timeout=10.0
        )
        assert detected, "OPA was never observed unreachable after pause"
        start = time.monotonic()
        with pytest.raises(SecurityControlError) as excinfo:
            provider.evaluate(request)
        elapsed = time.monotonic() - start
        assert excinfo.value.reason_code in ("SERVICE_UNAVAILABLE", "POLICY_UNAVAILABLE")
        assert elapsed <= 2.0 + 1.0, f"fail-closed took {elapsed:.2f}s, exceeding its bound"
        # the denial is correlated to the exact request that caused it
        assert request.governed_context.correlation_id in str(excinfo.value)
    finally:
        unpause = fault_inject.run(
            fault_inject.fault_command("opa", "unpause"), cwd=REPOSITORY_ROOT, timeout=30
        )
        assert unpause.returncode == 0, unpause.stderr
        recovered = fault_inject._poll(
            lambda: fault_inject.http_reachable(SERVICE_URLS["OPA"], timeout=2.0), timeout=15.0
        )
        assert recovered, "OPA did not recover within the bounded window after unpause"

    provider.evaluate(_policy_request(principal, digest, action="read"))


def test_paused_keycloak_fails_closed_with_correlation(mtls: dict[str, object]):
    # An unreachable identity provider is a denial correlated to the exact
    # request, not a silent permit nor a bare timeout without context.
    provider = KeycloakIdentityProvider(
        str(mtls["keycloak"]),
        REALM,
        CLIENT_ID,
        password_resolver=lambda u: USER_PWD,
        timeout_seconds=0.5,
        ssl_context=mtls["ssl_context"],
    )
    correlation_id = str(uuid.uuid4())
    request = IdentityRequest(f"urn:ocor:credential-ref:{USERNAME}", "account", correlation_id)

    pause = fault_inject.run(
        fault_inject.fault_command("keycloak", "pause"), cwd=REPOSITORY_ROOT, timeout=30
    )
    assert pause.returncode == 0, pause.stderr
    try:
        detected = fault_inject._poll(
            lambda: not fault_inject.http_reachable(SERVICE_URLS["Keycloak"], timeout=1.0),
            timeout=10.0,
        )
        assert detected, "Keycloak was never observed unreachable after pause"
        with pytest.raises(SecurityControlError) as excinfo:
            provider.authenticate(request)
        assert excinfo.value.reason_code == "SERVICE_UNAVAILABLE"
        assert correlation_id in str(excinfo.value)
    finally:
        unpause = fault_inject.run(
            fault_inject.fault_command("keycloak", "unpause"), cwd=REPOSITORY_ROOT, timeout=30
        )
        assert unpause.returncode == 0, unpause.stderr
        recovered = fault_inject._poll(
            lambda: fault_inject.http_reachable(SERVICE_URLS["Keycloak"], timeout=2.0),
            timeout=15.0,
        )
        assert recovered, "Keycloak did not recover within the bounded window after unpause"


# --------------------------------------------------------------------------- #
# Bundle integrity: digest pin, signature, validity window, non-boolean result
# --------------------------------------------------------------------------- #


def test_policy_pin_mismatch_fails_closed(
    principal: AuthenticatedPrincipal, opa: tuple[OpaPolicyDecisionProvider, str]
):
    provider, _ = opa
    wrong_digest = "urn:sha256:" + "f" * 64
    request = _policy_request(principal, wrong_digest, action="read")
    with pytest.raises(SecurityControlError) as excinfo:
        provider.evaluate(request)
    assert excinfo.value.reason_code == "STALE_BUNDLE"


def test_unsigned_bundle_fails_closed(mtls: dict[str, object]):
    provider = OpaPolicyDecisionProvider(
        str(mtls["opa"]),
        POLICY_ID,
        signer_public_key=(_SIGNER_N, _SIGNER_E),
        ssl_context=mtls["ssl_context"],
    )
    unsigned = SignedPolicyBundle(
        policy_id=POLICY_ID,
        rego_source=_rego("placeholder"),
        signer=_SIGNER,
        not_before=_now() - timedelta(minutes=5),
        expires_at=_now() + timedelta(hours=1),
        signature="",
    )
    with pytest.raises(SecurityControlError) as excinfo:
        provider.install_policy(unsigned)
    assert excinfo.value.reason_code == "POLICY_BUNDLE_SIGNATURE_INVALID"


def test_forged_bundle_signature_fails_closed(mtls: dict[str, object]):
    provider = OpaPolicyDecisionProvider(
        str(mtls["opa"]),
        POLICY_ID,
        signer_public_key=(_SIGNER_N, _SIGNER_E),
        ssl_context=mtls["ssl_context"],
    )
    valid = _sign_bundle(_rego("placeholder"))
    tampered = replace(valid, rego_source=_rego("placeholder") + "# tampered\n")
    with pytest.raises(SecurityControlError) as excinfo:
        provider.install_policy(tampered)
    assert excinfo.value.reason_code == "POLICY_BUNDLE_SIGNATURE_INVALID"


def test_expired_bundle_fails_closed(mtls: dict[str, object]):
    provider = OpaPolicyDecisionProvider(
        str(mtls["opa"]),
        POLICY_ID,
        signer_public_key=(_SIGNER_N, _SIGNER_E),
        ssl_context=mtls["ssl_context"],
    )
    bundle = _sign_bundle(
        _rego("placeholder"),
        not_before=_now() - timedelta(minutes=10),
        expires_at=_now() - timedelta(minutes=1),
    )
    with pytest.raises(SecurityControlError) as excinfo:
        provider.install_policy(bundle)
    assert excinfo.value.reason_code == "POLICY_BUNDLE_WINDOW_INVALID"


def test_non_boolean_policy_result_fails_closed(
    principal: AuthenticatedPrincipal, opa: tuple[OpaPolicyDecisionProvider, str]
):
    provider, _ = opa
    digest = provider.install_policy(
        _sign_bundle('package ocor.control_plane\n\nallow := {"permit": true}\n')
    )
    request = _policy_request(principal, digest, action="read")
    with pytest.raises(SecurityControlError) as excinfo:
        provider.evaluate(request)
    assert excinfo.value.reason_code == "POLICY_DECISION_INVALID"


# --------------------------------------------------------------------------- #
# Delegation binding: a forged actor chain never elevates privilege
# --------------------------------------------------------------------------- #


def test_forged_delegation_chain_fails_closed(
    principal: AuthenticatedPrincipal, opa: tuple[OpaPolicyDecisionProvider, str]
):
    provider, digest = opa
    gcs = GovernedContext(
        tenant_id="tenant-a",
        organization_id="org-a",
        domain_id="domain-a",
        compartments=("compartment-a",),
        classification_marking_ref="urn:sha256:" + "0" * 64,
        purpose="read-site-1",
        effective_principal_id=principal.principal_id,
        actor_chain=("forged-delegator",),
        ontology_release_digest="urn:sha256:" + "1" * 64,
        policy_bundle_digest=digest,
        correlation_id=str(uuid.uuid4()),
    )
    request = PolicyRequest(
        principal=principal,
        action="read",
        resource="urn:ocor:target:site-1",
        governed_context=gcs,
        governed_context_digest=gcs.digest(),
        at=_now(),
    )
    with pytest.raises(SecurityControlError) as excinfo:
        provider.evaluate(request)
    assert excinfo.value.reason_code == "IDENTITY_BINDING_MISMATCH"


_CAPABILITY = CapabilityInvocation(
    capability_id="urn:ocor:capability:read-site",
    capability_version="1.0.0",
    effect_class=OperationClass.R0_READ,
    risk_class=RiskClass.R0_READ,
)


def _policy_digest(principal_id: str) -> str:
    return "urn:sha256:" + hashlib.sha256(_rego(principal_id).encode()).hexdigest()


def _sign_grant(unsigned: SignedDelegation) -> SignedDelegation:
    signature = base64.b64encode(
        _rsa_sign(unsigned.signing_payload(), _SIGNER_N, _SIGNER_D)
    ).decode("ascii")
    return replace(unsigned, signature=signature)


def _sign_delegation(
    *,
    delegatee_id: str,
    delegator_id: str = "delegator-1",
    delegation_id: str = "urn:ocor:delegation:test",
    resource_scope: str = "urn:ocor:target:site-1",
    permitted_purposes: tuple[str, ...] = ("read-site-1",),
    not_before: datetime | None = None,
    expires_at: datetime | None = None,
    policy_bundle_digest: str | None = None,
    confirmation_key_thumbprint: str | None = None,
    **overrides: object,
) -> SignedDelegation:
    """Sign a complete ADD v1.3 §5.2 DelegationGrant with the test authority.

    By default the grant covers exactly the governed context built by
    ``_delegated_policy_request``, is bound to the bundle ``_rego(delegatee)``
    and is confirmed to the SPIRE workload key of the session mTLS context.
    """
    fields: dict[str, object] = {
        "grant_id": delegation_id,
        "grantor_principal": delegator_id,
        "grantee_principal": delegatee_id,
        "capability_id": _CAPABILITY.capability_id,
        "capability_version": _CAPABILITY.capability_version,
        "resource_scope": resource_scope,
        "tenant_id": "tenant-a",
        "organization_id": "org-a",
        "domains": ("domain-a",),
        "compartments": ("compartment-a",),
        "permitted_purposes": permitted_purposes,
        "effect_ceiling": OperationClass.R0_READ,
        "risk_ceiling": RiskClass.R0_READ,
        "not_before": not_before or _now() - timedelta(minutes=5),
        "expires_at": expires_at or _now() + timedelta(hours=1),
        "max_chain_depth": 1,
        "policy_bundle_digest": policy_bundle_digest or _policy_digest(delegatee_id),
        "nonce": uuid.uuid4().hex,
        "confirmation_key_thumbprint": confirmation_key_thumbprint or _WORKLOAD_KEY_THUMBPRINT,
    }
    fields.update(overrides)
    return _sign_grant(SignedDelegation(**fields))  # type: ignore[arg-type]


def _sign_revocation(delegation_id: str) -> SignedDelegationRevocation:
    unsigned = SignedDelegationRevocation(
        delegation_id=delegation_id,
        revoked_at=_now(),
        signature="",
    )
    signature = base64.b64encode(
        _rsa_sign(unsigned.signing_payload(), _SIGNER_N, _SIGNER_D)
    ).decode("ascii")
    return replace(unsigned, signature=signature)


def _delegated_policy_request(
    principal: AuthenticatedPrincipal,
    policy_digest: str,
    delegation: SignedDelegation | tuple[SignedDelegation, ...],
    **gcs_overrides: object,
) -> PolicyRequest:
    grants = delegation if isinstance(delegation, tuple) else (delegation,)
    fields: dict[str, object] = {
        "tenant_id": "tenant-a",
        "organization_id": "org-a",
        "domain_id": "domain-a",
        "compartments": ("compartment-a",),
        "classification_marking_ref": "urn:sha256:" + "0" * 64,
        "purpose": "read-site-1",
        "effective_principal_id": principal.principal_id,
        "actor_chain": (grants[0].grantor_principal,)
        + tuple(grant.grantee_principal for grant in grants),
        "ontology_release_digest": "urn:sha256:" + "1" * 64,
        "policy_bundle_digest": policy_digest,
        "correlation_id": str(uuid.uuid4()),
    }
    fields.update(gcs_overrides)
    gcs = GovernedContext(**fields)  # type: ignore[arg-type]
    return PolicyRequest(
        principal=principal,
        action="read",
        resource="urn:ocor:target:site-1",
        governed_context=gcs,
        governed_context_digest=gcs.digest(),
        at=_now(),
    )


# --------------------------------------------------------------------------- #
# Signed delegation: real crypto, bounded scope, revocation and window fences
# --------------------------------------------------------------------------- #


def test_valid_signed_delegation_grants_within_bounds(principal: AuthenticatedPrincipal):
    delegation = _sign_delegation(delegatee_id=principal.principal_id)
    verify_signed_delegation(
        delegation,
        (_SIGNER_N, _SIGNER_E),
        resource_scope="urn:ocor:target:site-1",
        purpose="read-site-1",
        delegator_id="delegator-1",
        delegatee_id=principal.principal_id,
        at=_now(),
    )


def test_delegation_over_scope_fails_closed(principal: AuthenticatedPrincipal):
    delegation = _sign_delegation(delegatee_id=principal.principal_id)
    with pytest.raises(SecurityControlError) as excinfo:
        verify_signed_delegation(
            delegation,
            (_SIGNER_N, _SIGNER_E),
            resource_scope="urn:ocor:target:other-site",
            purpose="read-site-1",
            delegator_id="delegator-1",
            delegatee_id=principal.principal_id,
            at=_now(),
        )
    assert excinfo.value.reason_code == "DELEGATION_SCOPE_MISMATCH"


def test_delegation_purpose_mismatch_fails_closed(principal: AuthenticatedPrincipal):
    delegation = _sign_delegation(delegatee_id=principal.principal_id)
    with pytest.raises(SecurityControlError) as excinfo:
        verify_signed_delegation(
            delegation,
            (_SIGNER_N, _SIGNER_E),
            resource_scope="urn:ocor:target:site-1",
            purpose="write-site-1",
            delegator_id="delegator-1",
            delegatee_id=principal.principal_id,
            at=_now(),
        )
    assert excinfo.value.reason_code == "DELEGATION_PURPOSE_MISMATCH"


def test_delegation_binding_mismatch_fails_closed(principal: AuthenticatedPrincipal):
    delegation = _sign_delegation(delegatee_id=principal.principal_id)
    with pytest.raises(SecurityControlError) as excinfo:
        verify_signed_delegation(
            delegation,
            (_SIGNER_N, _SIGNER_E),
            resource_scope="urn:ocor:target:site-1",
            purpose="read-site-1",
            delegator_id="delegator-1",
            delegatee_id="someone-else",
            at=_now(),
        )
    assert excinfo.value.reason_code == "DELEGATION_BINDING_MISMATCH"


def test_altered_delegation_fails_closed(principal: AuthenticatedPrincipal):
    delegation = _sign_delegation(delegatee_id=principal.principal_id)
    tampered = replace(delegation, resource_scope="urn:ocor:target:other-site")
    with pytest.raises(SecurityControlError) as excinfo:
        verify_signed_delegation(
            tampered,
            (_SIGNER_N, _SIGNER_E),
            resource_scope="urn:ocor:target:other-site",
            purpose="read-site-1",
            delegator_id="delegator-1",
            delegatee_id=principal.principal_id,
            at=_now(),
        )
    assert excinfo.value.reason_code == "DELEGATION_SIGNATURE_INVALID"


def test_revoked_delegation_fails_closed(principal: AuthenticatedPrincipal):
    delegation = _sign_delegation(delegatee_id=principal.principal_id)
    with pytest.raises(SecurityControlError) as excinfo:
        verify_signed_delegation(
            delegation,
            (_SIGNER_N, _SIGNER_E),
            resource_scope="urn:ocor:target:site-1",
            purpose="read-site-1",
            delegator_id="delegator-1",
            delegatee_id=principal.principal_id,
            at=_now(),
            revoked=True,
        )
    assert excinfo.value.reason_code == "DELEGATION_REVOKED"


def test_expired_delegation_fails_closed(principal: AuthenticatedPrincipal):
    delegation = _sign_delegation(
        delegatee_id=principal.principal_id,
        not_before=_now() - timedelta(minutes=10),
        expires_at=_now() - timedelta(minutes=1),
    )
    with pytest.raises(SecurityControlError) as excinfo:
        verify_signed_delegation(
            delegation,
            (_SIGNER_N, _SIGNER_E),
            resource_scope="urn:ocor:target:site-1",
            purpose="read-site-1",
            delegator_id="delegator-1",
            delegatee_id=principal.principal_id,
            at=_now(),
        )
    assert excinfo.value.reason_code == "DELEGATION_EXPIRED"


# --------------------------------------------------------------------------- #
# VF-001: canonical UTC time -- offset-equivalence is preserved, but an
# offset-only reinterpretation of the signed wall clock must never extend a
# window that the authority did not grant.
# --------------------------------------------------------------------------- #


def test_offset_equivalent_bundle_signing_is_stable(mtls: dict[str, object]):
    provider = OpaPolicyDecisionProvider(
        str(mtls["opa"]),
        POLICY_ID,
        signer_public_key=(_SIGNER_N, _SIGNER_E),
        ssl_context=mtls["ssl_context"],
    )
    rego = _rego("offset-equivalent")
    bundle = _sign_bundle(rego)
    # Same instant, different offset: the canonical UTC payload is unchanged,
    # so the detached signature still verifies and the bundle is accepted.
    equivalent = replace(
        bundle,
        expires_at=bundle.expires_at.astimezone(timezone(timedelta(hours=2))),
    )
    digest = provider.install_policy(equivalent)
    assert digest == "urn:sha256:" + hashlib.sha256(rego.encode()).hexdigest()


def test_offset_shifted_bundle_rejected(mtls: dict[str, object]):
    provider = OpaPolicyDecisionProvider(
        str(mtls["opa"]),
        POLICY_ID,
        signer_public_key=(_SIGNER_N, _SIGNER_E),
        ssl_context=mtls["ssl_context"],
    )
    expired = _sign_bundle(
        _rego("offset-shifted"),
        not_before=_now() - timedelta(minutes=10),
        expires_at=_now() - timedelta(minutes=5),
    )
    # Reinterpret the *wall clock* under a -02:00 offset while keeping payload
    # and signature byte-for-byte unchanged: the instant silently moves two
    # hours into the future.  Canonical UTC signing must reject this because
    # the signature no longer covers the re-canonicalised payload.
    shifted = replace(
        expired,
        expires_at=expired.expires_at.replace(tzinfo=timezone(timedelta(hours=-2))),
    )
    with pytest.raises(SecurityControlError) as excinfo:
        provider.install_policy(shifted)
    assert excinfo.value.reason_code == "POLICY_BUNDLE_SIGNATURE_INVALID"


# --------------------------------------------------------------------------- #
# VF-002: the signed delegation grant and its revocation state are consumed at
# the policy boundary (``OpaPolicyDecisionProvider.evaluate``) on real OPA, with
# a valid delegated request and fail-closed negatives on the same operation.
# --------------------------------------------------------------------------- #


@pytest.fixture
def opa_delegated(
    principal: AuthenticatedPrincipal, mtls: dict[str, object]
) -> tuple[OpaPolicyDecisionProvider, str]:
    provider = OpaPolicyDecisionProvider(
        str(mtls["opa"]),
        POLICY_ID,
        signer_public_key=(_SIGNER_N, _SIGNER_E),
        delegation_signer_public_key=(_SIGNER_N, _SIGNER_E),
        ssl_context=mtls["ssl_context"],
    )
    digest = _install_policy(provider, _rego(principal.principal_id))
    return provider, digest


def test_valid_delegated_request_on_real_backends(
    principal: AuthenticatedPrincipal, opa_delegated: tuple[OpaPolicyDecisionProvider, str]
):
    provider, digest = opa_delegated
    delegation = _sign_delegation(delegatee_id=principal.principal_id)
    request = _delegated_policy_request(principal, digest, delegation)
    decision = provider.evaluate(request, delegation=delegation, capability=_CAPABILITY)
    assert decision.effect is PolicyEffect.PERMIT
    decision.verify(request, at=_now())


def test_delegated_request_without_grant_fails_closed(
    principal: AuthenticatedPrincipal, opa_delegated: tuple[OpaPolicyDecisionProvider, str]
):
    provider, digest = opa_delegated
    delegation = _sign_delegation(delegatee_id=principal.principal_id)
    request = _delegated_policy_request(principal, digest, delegation)
    with pytest.raises(SecurityControlError) as excinfo:
        provider.evaluate(request)
    assert excinfo.value.reason_code == "IDENTITY_BINDING_MISMATCH"


def test_delegated_request_expired_fails_closed(
    principal: AuthenticatedPrincipal, opa_delegated: tuple[OpaPolicyDecisionProvider, str]
):
    provider, digest = opa_delegated
    delegation = _sign_delegation(
        delegatee_id=principal.principal_id,
        not_before=_now() - timedelta(minutes=10),
        expires_at=_now() - timedelta(minutes=1),
    )
    request = _delegated_policy_request(principal, digest, delegation)
    with pytest.raises(SecurityControlError) as excinfo:
        provider.evaluate(request, delegation=delegation, capability=_CAPABILITY)
    assert excinfo.value.reason_code == "DELEGATION_EXPIRED"


def test_delegated_request_revoked_fails_closed(
    principal: AuthenticatedPrincipal, mtls: dict[str, object]
):
    provider = OpaPolicyDecisionProvider(
        str(mtls["opa"]),
        POLICY_ID,
        signer_public_key=(_SIGNER_N, _SIGNER_E),
        delegation_signer_public_key=(_SIGNER_N, _SIGNER_E),
        delegation_revocations=(_sign_revocation("urn:ocor:delegation:test"),),
        ssl_context=mtls["ssl_context"],
    )
    digest = _install_policy(provider, _rego(principal.principal_id))
    delegation = _sign_delegation(delegatee_id=principal.principal_id)
    request = _delegated_policy_request(principal, digest, delegation)
    with pytest.raises(SecurityControlError) as excinfo:
        provider.evaluate(request, delegation=delegation, capability=_CAPABILITY)
    assert excinfo.value.reason_code == "DELEGATION_REVOKED"


def test_delegated_request_out_of_scope_fails_closed(
    principal: AuthenticatedPrincipal, opa_delegated: tuple[OpaPolicyDecisionProvider, str]
):
    provider, digest = opa_delegated
    delegation = _sign_delegation(
        delegatee_id=principal.principal_id,
        resource_scope="urn:ocor:target:other-site",
    )
    request = _delegated_policy_request(principal, digest, delegation)
    with pytest.raises(SecurityControlError) as excinfo:
        provider.evaluate(request, delegation=delegation, capability=_CAPABILITY)
    assert excinfo.value.reason_code == "DELEGATION_SCOPE_MISMATCH"


def test_delegated_request_out_of_purpose_fails_closed(
    principal: AuthenticatedPrincipal, opa_delegated: tuple[OpaPolicyDecisionProvider, str]
):
    provider, digest = opa_delegated
    delegation = _sign_delegation(
        delegatee_id=principal.principal_id,
        permitted_purposes=("write-site-1",),
    )
    request = _delegated_policy_request(principal, digest, delegation)
    with pytest.raises(SecurityControlError) as excinfo:
        provider.evaluate(request, delegation=delegation, capability=_CAPABILITY)
    assert excinfo.value.reason_code == "DELEGATION_PURPOSE_MISMATCH"


def test_delegated_request_altered_chain_fails_closed(
    principal: AuthenticatedPrincipal, opa_delegated: tuple[OpaPolicyDecisionProvider, str]
):
    provider, digest = opa_delegated
    delegation = _sign_delegation(delegatee_id=principal.principal_id)
    gcs = GovernedContext(
        tenant_id="tenant-a",
        organization_id="org-a",
        domain_id="domain-a",
        compartments=("compartment-a",),
        classification_marking_ref="urn:sha256:" + "0" * 64,
        purpose="read-site-1",
        effective_principal_id=principal.principal_id,
        actor_chain=("attacker-delegator", principal.principal_id),
        ontology_release_digest="urn:sha256:" + "1" * 64,
        policy_bundle_digest=digest,
        correlation_id=str(uuid.uuid4()),
    )
    request = PolicyRequest(
        principal=principal,
        action="read",
        resource="urn:ocor:target:site-1",
        governed_context=gcs,
        governed_context_digest=gcs.digest(),
        at=_now(),
    )
    with pytest.raises(SecurityControlError) as excinfo:
        provider.evaluate(request, delegation=delegation, capability=_CAPABILITY)
    assert excinfo.value.reason_code == "DELEGATION_BINDING_MISMATCH"


# --------------------------------------------------------------------------- #
# Secret isolation: an absent reference is an outright denial, never a write
# --------------------------------------------------------------------------- #


def test_absent_secret_ref_fails_closed_without_overwrite(
    principal: AuthenticatedPrincipal,
    env: dict[str, str],
    opa: tuple[OpaPolicyDecisionProvider, str],
    mtls: dict[str, object],
):
    _, policy_digest = opa
    provider = OpenBaoSecretProvider(
        str(mtls["openbao"]), env["OCOR_LOCAL_OPENBAO_TOKEN"], mount="ocor", ssl_context=mtls["ssl_context"]
    )
    gcs = _gcs(principal, policy_digest)
    request = SecretRequest(
        secret_ref="urn:ocor:secret-ref:absent-secret",
        principal_id=principal.principal_id,
        purpose="read-site-1",
        governed_context_digest=gcs.digest(),
        requested_at=_now(),
    )
    with pytest.raises(SecurityControlError) as excinfo:
        provider.lease(request, principal=principal)
    assert excinfo.value.reason_code == "SECRET_REFERENCE_UNRESOLVED"
    # no-overwrite: the lease attempt must not have provisioned the secret
    status, _ = _http(
        "GET",
        f"{OB}/v1/ocor/data/{principal.principal_id}/absent-secret",
        headers={"X-Vault-Token": env["OCOR_LOCAL_OPENBAO_TOKEN"]},
    )
    assert status == 404


# --------------------------------------------------------------------------- #
# Peer identity: a valid SVID from the same trust domain but a *different*
# service must be rejected by the client context, not merely chain-verified.
# --------------------------------------------------------------------------- #

SPIRE_SERVER_CONTAINER = "ocor-bootstrap-spire-server-1"
SPIRE_SERVER_SOCKET = "/run/spire/sockets/server.sock"


def _spire_server_json(command: list[str]) -> dict[str, object]:
    completed = subprocess.run(
        [
            "docker",
            "exec",
            SPIRE_SERVER_CONTAINER,
            "/opt/spire/bin/spire-server",
            *command,
            "-socketPath",
            SPIRE_SERVER_SOCKET,
            "-output",
            "json",
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode()
    return json.loads(completed.stdout.decode())


def _register_other_service_svid(*, ttl_seconds: int = 120) -> tuple[str, str, str, str]:
    """Register a temporary second workload SVID and return (cert_pem, key_pem,
    ca_pem, entry_id) plus poll the agent until that SVID is delivered."""
    entries = _spire_server_json(["entry", "show"]).get("entries", [])
    control = next(
        (e for e in entries if e.get("spiffe_id", {}).get("path") == "/ocor/control-plane"),
        None,
    )
    assert control is not None, "control-plane SPIRE entry is missing"
    parent = control["parent_id"]
    parent_id = f"spiffe://{parent['trust_domain']}{parent['path']}"
    other_id = f"spiffe://ocor.test/ocor/verifier-other-service-{uuid.uuid4().hex[:16]}"

    created = _spire_server_json(
        ["entry", "create", "-parentID", parent_id, "-spiffeID", other_id,
         "-selector", "unix:uid:0", "-x509SVIDTTL", str(ttl_seconds)]
    )
    entry_list = created.get("entries") or [
        item.get("entry", {})
        for item in created.get("results", [])
        if item.get("status", {}).get("code") in (0, None)
    ] or ([created] if created.get("id") else [])
    assert len(entry_list) == 1 and entry_list[0].get("id"), "no SPIRE entry id returned"
    entry_id = str(entry_list[0]["id"])

    svid: dict[str, object] | None = None
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        fetch = subprocess.run(
            [
                "docker", "exec", SPIRE_AGENT_CONTAINER, "/opt/spire/bin/spire-agent",
                "api", "fetch", "x509", "-socketPath", SPIRE_SOCKET, "-output", "json",
            ],
            capture_output=True, timeout=30, check=False,
        )
        if fetch.returncode == 0:
            for item in json.loads(fetch.stdout.decode()).get("svids", []):
                if item.get("spiffe_id") == other_id:
                    svid = item
                    break
        if svid is not None:
            break
        time.sleep(0.5)
    assert svid is not None, "second SVID was not delivered within the bound"
    chain = _split_der_chain(_b64_decode(str(svid["x509_svid"])))
    cert_pem = "".join(_der_to_pem(der, "CERTIFICATE") for der in chain)
    key_pem = _der_to_pem(_b64_decode(str(svid["x509_svid_key"])), "PRIVATE KEY")
    ca_pem = _der_to_pem(_b64_decode(str(svid["bundle"])), "CERTIFICATE")
    return cert_pem, key_pem, ca_pem, entry_id


def _delete_spire_entry(entry_id: str) -> None:
    subprocess.run(
        [
            "docker", "exec", SPIRE_SERVER_CONTAINER, "/opt/spire/bin/spire-server",
            "entry", "delete", "-socketPath", SPIRE_SERVER_SOCKET, "-entryID", entry_id,
        ],
        capture_output=True, timeout=30, check=False,
    )
    # Let the agent converge so the temporary identity cannot leak into a later
    # fetch in the same or a subsequent run.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        fetch = subprocess.run(
            [
                "docker", "exec", SPIRE_AGENT_CONTAINER, "/opt/spire/bin/spire-agent",
                "api", "fetch", "x509", "-socketPath", SPIRE_SOCKET, "-output", "json",
            ],
            capture_output=True, timeout=30, check=False,
        )
        if fetch.returncode != 0:
            break
        ids = [
            str(i.get("spiffe_id"))
            for i in json.loads(fetch.stdout.decode()).get("svids", [])
        ]
        if not any(i.startswith("spiffe://ocor.test/ocor/verifier-other-service-") for i in ids):
            break
        time.sleep(0.5)


def test_client_rejects_peer_with_different_spiffe_id(mtls: dict[str, object]):
    # A peer that presents a *valid* SVID from the same SPIRE trust domain but
    # belonging to a different service is rejected before any request byte is
    # written: chain verification is not service authentication.
    if not fault_inject.container_healthy(SPIRE_AGENT_CONTAINER):
        pytest.skip("SPIRE agent container is unavailable; real peer identity is mandatory")
    cert_pem, key_pem, ca_pem, entry_id = _register_other_service_svid()
    try:
        with _MtlsReverseProxy("127.0.0.1", 8181, cert_pem, key_pem, ca_pem) as proxy:
            with pytest.raises(ssl.SSLError):
                _tls_handshake(proxy.url, mtls["ssl_context"])
    finally:
        _delete_spire_entry(entry_id)

# REPAIR-4: trusted boundary time and intersected authority lifetimes.
def _wait_past(instant: datetime) -> None:
    remaining = (instant - _now()).total_seconds()
    assert remaining < 20, 'bounded real-time test'
    if remaining > 0:
        time.sleep(remaining + 0.05)


@pytest.mark.parametrize('offset', [-3600, 3600])
def test_repair4_policy_time_is_boundary_time(principal, opa, offset):
    provider, digest = opa
    request = replace(_policy_request(principal, digest),
                      at=min(principal.expires_at-timedelta(microseconds=1),
                             _now()+timedelta(seconds=offset))
                      if offset > 0 else principal.authenticated_at)
    before = _now()
    decision = provider.evaluate(request)
    after = _now()
    assert before <= decision.evaluated_at <= after
    assert decision.status.observed_at == decision.evaluated_at
    decision.verify(request, at=after)
    assert decision.valid_until <= principal.expires_at


def test_repair4_queued_delegation_expires(principal, opa_delegated):
    provider, digest = opa_delegated
    grant = _sign_delegation(delegatee_id=principal.principal_id,
                            expires_at=_now() + timedelta(seconds=3))
    request = _delegated_policy_request(principal, digest, grant)
    assert provider.evaluate(request, delegation=grant, capability=_CAPABILITY).effect is PolicyEffect.PERMIT
    _wait_past(grant.expires_at)
    with pytest.raises(SecurityControlError) as err:
        provider.evaluate(request, delegation=grant, capability=_CAPABILITY)
    assert err.value.reason_code == 'DELEGATION_EXPIRED'


@pytest.mark.parametrize('authority', ['delegation', 'bundle', 'principal'])
def test_repair4_decision_capped_at_canonical_authority(principal, mtls, authority):
    expiry = _now() + timedelta(seconds=4, microseconds=700000)
    provider = OpaPolicyDecisionProvider(
        str(mtls['opa']), POLICY_ID, signer_public_key=(_SIGNER_N, _SIGNER_E),
        delegation_signer_public_key=(_SIGNER_N, _SIGNER_E), ssl_context=mtls['ssl_context'])
    bundle = _sign_bundle(_rego(principal.principal_id),
                          expires_at=expiry if authority == 'bundle' else None)
    digest = provider.install_policy(bundle)
    # Real Keycloak authentication supplies this identity; restricting its
    # window cannot add authority. Tests still traverse real OPA and mTLS.
    if authority == 'principal':
        principal = replace(principal, expires_at=expiry)
    grant = _sign_delegation(delegatee_id=principal.principal_id,
                            expires_at=expiry if authority == 'delegation' else None)
    request = _delegated_policy_request(principal, digest, grant)
    decision = provider.evaluate(request, delegation=grant, capability=_CAPABILITY)
    limit = expiry if authority == 'principal' else expiry.replace(microsecond=0)
    assert decision.effect is PolicyEffect.PERMIT
    decision.verify(request, at=_now())
    assert decision.valid_until <= limit
    _wait_past(limit)
    with pytest.raises(SecurityControlError) as err:
        decision.verify(request, at=_now())
    assert err.value.reason_code == 'POLICY_DECISION_EXPIRED'


def test_repair4_queued_principal_expired(principal, opa):
    provider, digest = opa
    principal = replace(principal, expires_at=_now()+timedelta(seconds=2))
    request = _policy_request(principal, digest)
    assert provider.evaluate(request).effect is PolicyEffect.PERMIT
    _wait_past(principal.expires_at)
    with pytest.raises(SecurityControlError) as err:
        provider.evaluate(request)
    assert err.value.reason_code == 'IDENTITY_EXPIRED'


def test_repair4_future_request_cannot_activate_delegation(principal, opa_delegated):
    provider, digest = opa_delegated
    grant = _sign_delegation(delegatee_id=principal.principal_id,
                            not_before=_now()+timedelta(seconds=30))
    request = replace(_delegated_policy_request(principal, digest, grant), at=grant.not_before)
    with pytest.raises(SecurityControlError) as err:
        provider.evaluate(request, delegation=grant, capability=_CAPABILITY)
    assert err.value.reason_code == 'DELEGATION_EXPIRED'


def test_repair4_helper_cannot_replay_old_time(principal):
    grant = _sign_delegation(delegatee_id=principal.principal_id,
                            expires_at=_now()-timedelta(seconds=2))
    with pytest.raises(SecurityControlError) as err:
        verify_signed_delegation(grant, (_SIGNER_N, _SIGNER_E),
            resource_scope='urn:ocor:target:site-1', purpose='read-site-1',
            delegator_id=grant.grantor_principal, delegatee_id=principal.principal_id,
            at=grant.not_before)
    assert err.value.reason_code == 'DELEGATION_EXPIRED'


@pytest.mark.parametrize('offset', [-86400, 86400])
def test_repair4_secret_lease_uses_boundary_time(principal, env, mtls, offset):
    name = 'repair4-time-'+uuid.uuid4().hex
    _seed_secret(env, principal.principal_id, name, {'value': 'disposable'})
    provider = OpenBaoSecretProvider(str(mtls['openbao']), env['OCOR_LOCAL_OPENBAO_TOKEN'],
                                    ssl_context=mtls['ssl_context'])
    request = SecretRequest('urn:ocor:secret-ref:'+name, principal.principal_id,
                            'read-site-1', 'urn:sha256:'+'1'*64,
                            _now()+timedelta(seconds=offset))
    before = _now()
    lease = provider.lease(request, principal=principal)
    after = _now()
    assert before <= lease.issued_at <= after
    assert lease.status.observed_at == lease.issued_at
    assert lease.expires_at <= after+timedelta(seconds=300)
    lease.verify(request, at=after)


@pytest.fixture
def repair4_short_svid():
    from ocor_runtime.security.control_plane import _parse_certificate
    cert, key, ca, entry_id = _register_other_service_svid(ttl_seconds=12)
    try:
        leaf = _parse_certificate(ssl.PEM_cert_to_DER_cert(cert.split('-----END CERTIFICATE-----')[0]+'-----END CERTIFICATE-----'))
        identity = leaf['uri_sans'][0]
        provider = SpireWorkloadIdentityProvider(agent_container=SPIRE_AGENT_CONTAINER,
                  socket_path=SPIRE_SOCKET, expected_spiffe_id=identity)
        proxies = [_MtlsReverseProxy('127.0.0.1', port, cert, key, ca)
                   for port in (8181, 8080, 8200)]
        try:
            for proxy in proxies:
                proxy.__enter__()
            yield provider, [proxy.url for proxy in proxies], datetime.fromtimestamp(leaf['not_after'], UTC)
        finally:
            for proxy in proxies:
                proxy.__exit__(None, None, None)
    finally:
        _spire_server_json(['entry', 'delete', '-entryID', entry_id])


def test_repair4_svid_bounds_policy_and_rejects_expired_context(principal, repair4_short_svid):
    spire, urls, expiry = repair4_short_svid
    identity = spire.current()
    assert identity.expires_at <= expiry
    context = spire.mtls_context()
    provider = OpaPolicyDecisionProvider(urls[0], POLICY_ID,
                signer_public_key=(_SIGNER_N, _SIGNER_E), ssl_context=context)
    digest = _install_policy(provider, _rego(principal.principal_id))
    request = _policy_request(principal, digest)
    decision = provider.evaluate(request)
    assert decision.effect is PolicyEffect.PERMIT
    assert decision.valid_until <= expiry
    _wait_past(expiry)
    with pytest.raises(SecurityControlError) as err:
        provider.evaluate(request)
    assert err.value.reason_code == 'WORKLOAD_IDENTITY_EXPIRED'


@pytest.fixture
def repair4_keycloak_client(env, principals, mtls, request):
    claim = request.param
    client_id = 'repair4-'+uuid.uuid4().hex
    payload = {'clientId': client_id, 'enabled': True, 'publicClient': True,
               'directAccessGrantsEnabled': True, 'protocol': 'openid-connect',
               'attributes': {'access.token.lifespan': '3' if claim == 'exp' else '300'}}
    if claim in ('nbf', 'iat'):
        payload['protocolMappers'] = [{'name': 'future-'+claim, 'protocol': 'openid-connect',
            'protocolMapper': 'oidc-hardcoded-claim-mapper', 'config': {
                'claim.name': claim, 'claim.value': str(int(_now().timestamp())+30),
                'jsonType.label': 'long', 'access.token.claim': 'true'}}]
    import urllib.parse
    status, body = _http('POST', KC+'/realms/master/protocol/openid-connect/token',
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        body=urllib.parse.urlencode({'client_id': 'admin-cli', 'username': 'ocor-admin',
              'password': env['OCOR_LOCAL_KEYCLOAK_PASSWORD'], 'grant_type': 'password'}))
    assert status == 200
    admin_token = json.loads(body)['access_token']
    headers = {'Authorization': 'Bearer '+admin_token, 'Content-Type': 'application/json'}
    status, body = _http('POST', f'{KC}/admin/realms/{REALM}/clients', headers=headers, body=json.dumps(payload))
    assert status == 201, body
    status, body = _http('GET', f'{KC}/admin/realms/{REALM}/clients?clientId={client_id}', headers=headers)
    assert status == 200
    uid = json.loads(body)[0]['id']
    try:
        yield KeycloakIdentityProvider(str(mtls['keycloak']), REALM, client_id,
              password_resolver=lambda _: USER_PWD, ssl_context=mtls['ssl_context'])
    finally:
        assert _http('DELETE', f'{KC}/admin/realms/{REALM}/clients/{uid}', headers=headers)[0] == 204


@pytest.mark.parametrize('repair4_keycloak_client', ['nbf'], indirect=True)
def test_repair4_real_signed_future_token_rejected(repair4_keycloak_client):
    with pytest.raises(SecurityControlError) as err:
        repair4_keycloak_client.authenticate(IdentityRequest(
            'urn:ocor:credential-ref:'+USERNAME, 'account', str(uuid.uuid4())))
    assert err.value.reason_code == 'IDENTITY_REJECTED'


@pytest.mark.parametrize('repair4_keycloak_client', ['exp'], indirect=True)
def test_repair4_real_token_expiry_revalidated_at_policy(repair4_keycloak_client, mtls):
    principal = repair4_keycloak_client.authenticate(IdentityRequest(
            'urn:ocor:credential-ref:'+USERNAME, 'account', str(uuid.uuid4())))
    provider = OpaPolicyDecisionProvider(str(mtls['opa']), POLICY_ID,
              signer_public_key=(_SIGNER_N, _SIGNER_E), ssl_context=mtls['ssl_context'])
    digest = _install_policy(provider, _rego(principal.principal_id))
    request = _policy_request(principal, digest)
    decision = provider.evaluate(request)
    assert decision.effect is PolicyEffect.PERMIT
    assert decision.valid_until <= principal.expires_at
    _wait_past(principal.expires_at)
    with pytest.raises(SecurityControlError) as err:
        provider.evaluate(request)
    assert err.value.reason_code == 'IDENTITY_EXPIRED'


def test_repair4_openbao_token_bounds_lease(principal, env, mtls):
    root_headers = {'X-Vault-Token': env['OCOR_LOCAL_OPENBAO_TOKEN'], 'Content-Type': 'application/json'}
    status, body = _http('POST', OB+'/v1/auth/token/create', headers=root_headers,
                         body=json.dumps({'ttl': '5s', 'policies': ['root'], 'renewable': False}))
    assert status == 200
    token = json.loads(body)['auth']['client_token']
    status, body = _http('GET', OB+'/v1/auth/token/lookup-self', headers={'X-Vault-Token': token})
    assert status == 200
    expiry = datetime.fromisoformat(json.loads(body)['data']['expire_time'].replace('Z', '+00:00'))
    name = 'repair4-token-'+uuid.uuid4().hex
    _seed_secret(env, principal.principal_id, name, {'value': 'disposable'})
    provider = OpenBaoSecretProvider(str(mtls['openbao']), token, ssl_context=mtls['ssl_context'])
    request = SecretRequest('urn:ocor:secret-ref:'+name, principal.principal_id,
                            'read-site-1', 'urn:sha256:'+'1'*64, _now())
    lease = provider.lease(request, principal=principal)
    assert lease.expires_at <= expiry
    lease.verify(request, at=_now())
    _wait_past(expiry)
    with pytest.raises(SecurityControlError) as err:
        lease.verify(request, at=_now())
    assert err.value.reason_code == 'SECRET_LEASE_EXPIRED'
    with pytest.raises(SecurityControlError) as err:
        provider.lease(request, principal=principal)
    assert err.value.reason_code == 'SECRETS_UNAVAILABLE'


@pytest.mark.parametrize('authority,reason', [
    ('delegation', 'DELEGATION_EXPIRED'), ('principal', 'IDENTITY_EXPIRED'),
    ('bundle', 'POLICY_BUNDLE_WINDOW_INVALID'),
])
def test_repair4_expiry_during_real_opa_response(principal, mtls, authority, reason):
    provider = OpaPolicyDecisionProvider(str(mtls['opa']), POLICY_ID,
        signer_public_key=(_SIGNER_N, _SIGNER_E),
        delegation_signer_public_key=(_SIGNER_N, _SIGNER_E), ssl_context=mtls['ssl_context'])
    expiry = _now()+timedelta(seconds=2)
    digest = provider.install_policy(_sign_bundle(_rego(principal.principal_id),
                                     expires_at=expiry if authority == 'bundle' else None))
    if authority == 'principal':
        principal = replace(principal, expires_at=expiry)
    grant = _sign_delegation(delegatee_id=principal.principal_id,
                            expires_at=expiry if authority == 'delegation' else None)
    request = _delegated_policy_request(principal, digest, grant)
    assert provider.evaluate(request, delegation=grant, capability=_CAPABILITY).effect is PolicyEffect.PERMIT
    proxy = mtls['proxies'][0]
    proxy.response_delay = 2.1
    proxy.delayed_method = b'POST'
    try:
        with pytest.raises(SecurityControlError) as err:
            provider.evaluate(request, delegation=grant, capability=_CAPABILITY)
        assert err.value.reason_code == reason
    finally:
        proxy.response_delay = 0.0
        proxy.delayed_method = None
        proxy.delayed_path = None


def test_repair4_bundle_expiry_during_real_install(principal, mtls):
    provider = OpaPolicyDecisionProvider(str(mtls['opa']), POLICY_ID,
        signer_public_key=(_SIGNER_N, _SIGNER_E), ssl_context=mtls['ssl_context'])
    proxy = mtls['proxies'][0]
    proxy.response_delay = 1.1
    try:
        with pytest.raises(SecurityControlError) as err:
            provider.install_policy(_sign_bundle(_rego(principal.principal_id),
                                    expires_at=_now()+timedelta(seconds=2)))
        assert err.value.reason_code == 'POLICY_BUNDLE_WINDOW_INVALID'
    finally:
        proxy.response_delay = 0.0
        proxy.delayed_method = None
        proxy.delayed_path = None


def test_repair4_openbao_scheduled_deletion_bounds_lease(principal, env, mtls):
    name = 'repair4-deletion-'+uuid.uuid4().hex
    headers = {'X-Vault-Token': env['OCOR_LOCAL_OPENBAO_TOKEN'], 'Content-Type': 'application/json'}
    status, _ = _http('POST', f'{OB}/v1/ocor/metadata/{principal.principal_id}/{name}',
        headers=headers, body=json.dumps({'delete_version_after': '4s'}))
    assert status in (200, 204)
    _seed_secret(env, principal.principal_id, name, {'value': 'disposable'})
    status, body = _http('GET', f'{OB}/v1/ocor/data/{principal.principal_id}/{name}', headers=headers)
    assert status == 200
    expiry = datetime.fromisoformat(json.loads(body)['data']['metadata']['deletion_time'].replace('Z','+00:00'))
    provider = OpenBaoSecretProvider(str(mtls['openbao']), env['OCOR_LOCAL_OPENBAO_TOKEN'],
                                    ssl_context=mtls['ssl_context'])
    request = SecretRequest('urn:ocor:secret-ref:'+name, principal.principal_id,
                            'read-site-1', 'urn:sha256:'+'1'*64, _now())
    lease = provider.lease(request, principal=principal)
    lease.verify(request, at=_now())
    assert lease.expires_at <= expiry
    _wait_past(expiry)
    with pytest.raises(SecurityControlError) as err:
        lease.verify(request, at=_now())
    assert err.value.reason_code == 'SECRET_LEASE_EXPIRED'
    with pytest.raises(SecurityControlError) as err:
        provider.lease(request, principal=principal)
    assert err.value.reason_code == 'SECRET_REFERENCE_UNRESOLVED'


@pytest.mark.parametrize('repair4_keycloak_client', ['iat'], indirect=True)
def test_repair4_keycloak_issued_at_is_server_controlled(repair4_keycloak_client):
    # Keycloak 26.6.3 explicitly forbids overriding iat with a claim mapper.
    # Characterize that real issuer, never claim a future-iat fixture exists.
    before = _now()
    principal = repair4_keycloak_client.authenticate(IdentityRequest(
        'urn:ocor:credential-ref:'+USERNAME, 'account', str(uuid.uuid4())))
    assert before.replace(microsecond=0) <= principal.authenticated_at <= _now()


def test_repair4_svid_bounds_identity_and_secret(principals, env, repair4_short_svid):
    spire, urls, expiry = repair4_short_svid
    context = spire.mtls_context()
    provider = KeycloakIdentityProvider(urls[1], REALM, CLIENT_ID,
                        password_resolver=lambda _: USER_PWD, ssl_context=context)
    principal = provider.authenticate(IdentityRequest('urn:ocor:credential-ref:'+USERNAME,
                                        'account', str(uuid.uuid4())))
    assert principal.expires_at <= expiry
    name = 'repair4-svid-'+uuid.uuid4().hex
    _seed_secret(env, principal.principal_id, name, {'value': 'disposable'})
    secrets = OpenBaoSecretProvider(urls[2], env['OCOR_LOCAL_OPENBAO_TOKEN'], ssl_context=context)
    request = SecretRequest('urn:ocor:secret-ref:'+name, principal.principal_id,
                           'read-site-1', 'urn:sha256:'+'1'*64, _now())
    lease = secrets.lease(request, principal=principal)
    assert lease.expires_at <= expiry
    lease.verify(request, at=_now())
    _wait_past(expiry)
    for operation in [lambda: secrets.lease(request, principal=principal), lambda: provider.authenticate(
        IdentityRequest('urn:ocor:credential-ref:'+USERNAME, 'account', str(uuid.uuid4())))]:
        with pytest.raises(SecurityControlError) as err:
            operation()
        assert err.value.reason_code == 'WORKLOAD_IDENTITY_EXPIRED'


@pytest.mark.parametrize('repair4_keycloak_client', ['exp'], indirect=True)
def test_repair4_token_expiry_during_real_authentication(repair4_keycloak_client, mtls):
    proxy = mtls['proxies'][1]
    # All responses cross the real backend; delay the signed token response
    # so its 3s lifetime is consumed before verification at the boundary.
    proxy.response_delay = 3.1
    proxy.delayed_method = b'POST'
    try:
        with pytest.raises(SecurityControlError) as err:
            repair4_keycloak_client.authenticate(IdentityRequest(
                'urn:ocor:credential-ref:'+USERNAME, 'account', str(uuid.uuid4())))
        assert err.value.reason_code == 'IDENTITY_REJECTED'
    finally:
        proxy.response_delay = 0.0
        proxy.delayed_method = None
        proxy.delayed_path = None


@pytest.mark.parametrize('authority,reason', [('token', 'SECRETS_UNAVAILABLE'),
                                            ('deletion', 'SECRET_LEASE_EXPIRED')])
def test_repair4_expiry_during_real_secret_read(principal, env, mtls, authority, reason):
    headers = {'X-Vault-Token': env['OCOR_LOCAL_OPENBAO_TOKEN'], 'Content-Type': 'application/json'}
    token = env['OCOR_LOCAL_OPENBAO_TOKEN']
    name = 'repair4-race-'+uuid.uuid4().hex
    path = f'/v1/ocor/data/{principal.principal_id}/{name}'
    if authority == 'token':
        status, body = _http('POST', OB+'/v1/auth/token/create', headers=headers,
                body=json.dumps({'ttl': '3s', 'policies': ['root'], 'renewable': False}))
        assert status == 200
        token = json.loads(body)['auth']['client_token']
    else:
        status, _ = _http('POST', f'{OB}/v1/ocor/metadata/{principal.principal_id}/{name}',
                         headers=headers, body=json.dumps({'delete_version_after': '3s'}))
        assert status in (200, 204)
    _seed_secret(env, principal.principal_id, name, {'value': 'disposable'})
    provider = OpenBaoSecretProvider(str(mtls['openbao']), token, ssl_context=mtls['ssl_context'])
    request = SecretRequest('urn:ocor:secret-ref:'+name, principal.principal_id,
                           'read-site-1', 'urn:sha256:'+'1'*64, _now())
    provider.lease(request, principal=principal).verify(request, at=_now())
    proxy = mtls['proxies'][2]
    proxy.response_delay = 3.1
    proxy.delayed_path = path.encode()
    try:
        with pytest.raises(SecurityControlError) as err:
            provider.lease(request, principal=principal)
        assert err.value.reason_code == reason
    finally:
        proxy.response_delay = 0.0
        proxy.delayed_path = None


def test_repair4_utc_equivalent_delegation_has_same_deadline(principal, opa_delegated):
    provider, digest = opa_delegated
    grant = _sign_delegation(delegatee_id=principal.principal_id,
                             expires_at=_now()+timedelta(seconds=20, microseconds=900000))
    shifted = replace(grant, expires_at=grant.expires_at.astimezone(timezone(timedelta(hours=2))))
    request = _delegated_policy_request(principal, digest, shifted)
    decision = provider.evaluate(request, delegation=shifted, capability=_CAPABILITY)
    assert decision.effect is PolicyEffect.PERMIT
    assert decision.valid_until == grant.expires_at.replace(microsecond=0)
    reinterpreted = replace(grant, expires_at=grant.expires_at.replace(tzinfo=timezone(timedelta(hours=-2))))
    with pytest.raises(SecurityControlError) as err:
        provider.evaluate(request, delegation=reinterpreted, capability=_CAPABILITY)
    assert err.value.reason_code == 'DELEGATION_SIGNATURE_INVALID'


# =========================================================================== #
# REPAIR-5 (decision OCOR-DEV-0048-REPAIR-5-CLAUDE; implementer Claude Code,
# verifier Codex).  VF-001: the signed DelegationGrant carries and enforces
# every ADD v1.3 §5.2 constraint.  VF-002: the OPA evaluation and the emitted
# PolicyDecision are bound atomically to the verified bundle snapshot.  Every
# case drives the real OPA, SPIRE/mTLS, Keycloak or OpenBao boundary.
# =========================================================================== #

from ocor_runtime.kernel.governed_context import GovernedContextError  # noqa: E402

_DESIGN_GRANT_FIELDS = {
    "grant_id", "grantor_principal", "grantee_principal", "capability_id",
    "capability_version", "resource_scope", "tenant_id", "domains", "compartments",
    "permitted_purposes", "effect_ceiling", "risk_ceiling", "not_before", "expires_at",
    "max_chain_depth", "redelegation_allowed", "parent_grant_digest",
    "policy_bundle_digest", "nonce", "confirmation_key_thumbprint",
}


def _expect(reason: str, operation) -> SecurityControlError:
    with pytest.raises(SecurityControlError) as excinfo:
        operation()
    assert excinfo.value.reason_code == reason, str(excinfo.value)
    return excinfo.value


def test_repair5_grant_signs_every_design_field(principal: AuthenticatedPrincipal):
    grant = _sign_delegation(delegatee_id=principal.principal_id)
    payload = json.loads(grant.signing_payload())
    # signature_ref is the detached signature itself; organization_id is the
    # ADD §1.4 binding the design record leaves implicit.
    assert set(payload) == _DESIGN_GRANT_FIELDS | {"organization_id"}
    assert verify_delegation_signature(grant, (_SIGNER_N, _SIGNER_E)) == grant.digest()
    assert grant.digest().startswith("urn:sha256:")
    # ADD §5.2 rule 1: redelegation is off unless the authority signs it on.
    assert grant.redelegation_allowed is False and payload["redelegation_allowed"] is False
    assert grant.parent_grant_digest is None


@pytest.mark.parametrize("field,value", [
    ("grant_id", "urn:ocor:delegation:other"),
    ("grantor_principal", "delegator-2"),
    ("grantee_principal", "someone-else"),
    ("capability_id", "urn:ocor:capability:erase-site"),
    ("capability_version", "2.0.0"),
    ("resource_scope", "urn:ocor:target:other-site"),
    ("tenant_id", "tenant-b"),
    ("organization_id", "org-b"),
    ("domains", ("domain-a", "domain-b")),
    ("compartments", ("compartment-a", "compartment-b")),
    ("permitted_purposes", ("read-site-1", "write-site-1")),
    ("effect_ceiling", OperationClass.R3_HIGH_IMPACT),
    ("risk_ceiling", RiskClass.R3_HIGH_IMPACT),
    ("not_before", datetime(2026, 1, 1, tzinfo=UTC)),
    ("expires_at", datetime(2030, 1, 1, tzinfo=UTC)),
    ("max_chain_depth", 5),
    ("redelegation_allowed", True),
    ("parent_grant_digest", "urn:sha256:" + "a" * 64),
    ("policy_bundle_digest", "urn:sha256:" + "b" * 64),
    ("nonce", "f" * 32),
    ("confirmation_key_thumbprint", "urn:sha256:" + "c" * 64),
])
def test_repair5_altering_any_grant_field_breaks_signature(
    principal: AuthenticatedPrincipal, opa_delegated: tuple[OpaPolicyDecisionProvider, str],
    field: str, value: object,
):
    provider, digest = opa_delegated
    grant = _sign_delegation(delegatee_id=principal.principal_id)
    request = _delegated_policy_request(principal, digest, grant)
    assert provider.evaluate(request, delegation=grant, capability=_CAPABILITY).effect is (
        PolicyEffect.PERMIT)
    tampered = replace(grant, **{field: value})
    _expect("DELEGATION_SIGNATURE_INVALID",
            lambda: provider.evaluate(request, delegation=tampered, capability=_CAPABILITY))


@pytest.mark.parametrize("field,value", [
    ("grant_id", ""), ("grantor_principal", ""), ("grantee_principal", "delegator-1"),
    ("capability_id", ""), ("capability_version", ""), ("resource_scope", ""),
    ("tenant_id", ""), ("organization_id", ""), ("domains", ()), ("compartments", ()),
    ("permitted_purposes", ()), ("domains", ("domain-a", "domain-a")),
    ("compartments", "compartment-a"), ("effect_ceiling", 7), ("effect_ceiling", True),
    ("risk_ceiling", "R0_INFORMATIONAL"), ("max_chain_depth", 0), ("max_chain_depth", True),
    ("redelegation_allowed", "no"), ("parent_grant_digest", "sha256:abc"),
    ("policy_bundle_digest", ""), ("nonce", "short"), ("confirmation_key_thumbprint", ""),
    ("not_before", datetime(2026, 1, 1)), ("expires_at", datetime(2026, 1, 1, tzinfo=UTC)),
])
def test_repair5_incomplete_grant_is_rejected(
    principal: AuthenticatedPrincipal, opa_delegated: tuple[OpaPolicyDecisionProvider, str],
    field: str, value: object,
):
    provider, digest = opa_delegated
    grant = _sign_delegation(delegatee_id=principal.principal_id)
    request = _delegated_policy_request(principal, digest, grant)
    assert provider.evaluate(request, delegation=grant, capability=_CAPABILITY).effect is (
        PolicyEffect.PERMIT)
    incomplete = replace(grant, **{field: value})
    # The authority cannot sign it, and the boundary refuses it as presented.
    _expect("DELEGATION_INVALID", incomplete.signing_payload)
    _expect("DELEGATION_INVALID",
            lambda: provider.evaluate(request, delegation=incomplete, capability=_CAPABILITY))


@pytest.mark.parametrize("field,value", [
    ("tenant_id", "tenant-b"), ("organization_id", "org-b"), ("domain_id", "domain-b"),
    ("compartments", ("compartment-b",)), ("compartments", ("compartment-a", "compartment-b")),
])
def test_repair5_signed_grant_bounds_governed_scope(
    principal: AuthenticatedPrincipal, opa_delegated: tuple[OpaPolicyDecisionProvider, str],
    field: str, value: object,
):
    # VF-001 (cycle 4) counterexample: the same signed grant replayed into a
    # foreign tenant, organization, domain or compartment set.
    provider, digest = opa_delegated
    grant = _sign_delegation(delegatee_id=principal.principal_id)
    request = _delegated_policy_request(principal, digest, grant)
    assert provider.evaluate(request, delegation=grant, capability=_CAPABILITY).effect is (
        PolicyEffect.PERMIT)
    replay = _delegated_policy_request(principal, digest, grant, **{field: value})
    _expect("DELEGATION_SCOPE_MISMATCH",
            lambda: provider.evaluate(replay, delegation=grant, capability=_CAPABILITY))


def test_repair5_grant_scope_is_an_intersection(
    principal: AuthenticatedPrincipal, opa_delegated: tuple[OpaPolicyDecisionProvider, str],
):
    provider, digest = opa_delegated
    grant = _sign_delegation(
        delegatee_id=principal.principal_id,
        domains=("domain-a", "domain-b"),
        compartments=("compartment-a", "compartment-b"),
    )
    for domain, compartments in (("domain-b", ("compartment-a",)),
                                 ("domain-a", ("compartment-a", "compartment-b"))):
        request = _delegated_policy_request(
            principal, digest, grant, domain_id=domain, compartments=compartments
        )
        decision = provider.evaluate(request, delegation=grant, capability=_CAPABILITY)
        assert decision.effect is PolicyEffect.PERMIT
        decision.verify(request, at=_now())
    outside = _delegated_policy_request(principal, digest, grant, domain_id="domain-c")
    _expect("DELEGATION_SCOPE_MISMATCH",
            lambda: provider.evaluate(outside, delegation=grant, capability=_CAPABILITY))


@pytest.mark.parametrize("capability,reason", [
    (replace(_CAPABILITY, capability_id="urn:ocor:capability:erase-site"),
     "DELEGATION_CAPABILITY_MISMATCH"),
    (replace(_CAPABILITY, capability_version="2.0.0"), "DELEGATION_CAPABILITY_MISMATCH"),
    (replace(_CAPABILITY, effect_class=OperationClass.R2_CONTROLLED), "DELEGATION_CEILING_EXCEEDED"),
    (replace(_CAPABILITY, risk_class=RiskClass.R2_CONTROLLED), "DELEGATION_CEILING_EXCEEDED"),
    (None, "DELEGATION_INVALID"),
])
def test_repair5_capability_must_fit_grant_ceilings(
    principal: AuthenticatedPrincipal, opa_delegated: tuple[OpaPolicyDecisionProvider, str],
    capability: CapabilityInvocation | None, reason: str,
):
    provider, digest = opa_delegated
    grant = _sign_delegation(
        delegatee_id=principal.principal_id,
        effect_ceiling=OperationClass.R1_ANALYZE,
        risk_ceiling=RiskClass.R1_ANALYZE,
    )
    request = _delegated_policy_request(principal, digest, grant)
    for within in (_CAPABILITY, replace(_CAPABILITY, effect_class=OperationClass.R1_ANALYZE,
                                        risk_class=RiskClass.R1_ANALYZE)):
        assert provider.evaluate(request, delegation=grant, capability=within).effect is (
            PolicyEffect.PERMIT)
    _expect(reason, lambda: provider.evaluate(request, delegation=grant, capability=capability))


def test_repair5_capability_invocation_is_strictly_typed():
    for field, value in (("effect_class", True), ("effect_class", 9), ("risk_class", "R1_LOW"),
                         ("capability_id", ""), ("capability_version", "")):
        _expect("CAPABILITY_INVOCATION_INVALID",
                lambda: replace(_CAPABILITY, **{field: value}))


def test_repair5_grant_is_bound_to_the_verified_policy_bundle(
    principal: AuthenticatedPrincipal, opa_delegated: tuple[OpaPolicyDecisionProvider, str],
):
    provider, digest = opa_delegated
    foreign = _sign_delegation(delegatee_id=principal.principal_id,
                               policy_bundle_digest="urn:sha256:" + "9" * 64)
    request = _delegated_policy_request(principal, digest, foreign)
    _expect("DELEGATION_POLICY_BINDING_MISMATCH",
            lambda: provider.evaluate(request, delegation=foreign, capability=_CAPABILITY))
    grant = _sign_delegation(delegatee_id=principal.principal_id)
    request = _delegated_policy_request(principal, digest, grant)
    assert provider.evaluate(request, delegation=grant, capability=_CAPABILITY).effect is (
        PolicyEffect.PERMIT)
    # A newly verified bundle revision does not inherit grants of the old one.
    revised = _install_policy(provider, _rego(principal.principal_id) + "# revision 2\n")
    request = _delegated_policy_request(principal, revised, grant)
    _expect("DELEGATION_POLICY_BINDING_MISMATCH",
            lambda: provider.evaluate(request, delegation=grant, capability=_CAPABILITY))


def test_repair5_grant_is_confirmed_to_the_presenting_workload_key(
    principal: AuthenticatedPrincipal, opa_delegated: tuple[OpaPolicyDecisionProvider, str],
):
    provider, digest = opa_delegated
    grant = _sign_delegation(delegatee_id=principal.principal_id,
                             confirmation_key_thumbprint="urn:sha256:" + "c" * 64)
    request = _delegated_policy_request(principal, digest, grant)
    _expect("DELEGATION_KEY_BINDING_MISMATCH",
            lambda: provider.evaluate(request, delegation=grant, capability=_CAPABILITY))


def test_repair5_grant_cannot_be_transferred_to_another_workload(
    principal: AuthenticatedPrincipal, repair4_short_svid,
):
    # A real second SPIRE workload presents its own SVID on mTLS: a grant
    # confirmed to the control-plane key is useless to it, and vice versa.
    spire, urls, _ = repair4_short_svid
    other = spire.mtls_context()
    assert workload_key_thumbprint(other) != _WORKLOAD_KEY_THUMBPRINT
    provider = OpaPolicyDecisionProvider(
        urls[0], POLICY_ID, signer_public_key=(_SIGNER_N, _SIGNER_E),
        delegation_signer_public_key=(_SIGNER_N, _SIGNER_E), ssl_context=other)
    digest = _install_policy(provider, _rego(principal.principal_id))
    stolen = _sign_delegation(delegatee_id=principal.principal_id)
    request = _delegated_policy_request(principal, digest, stolen)
    _expect("DELEGATION_KEY_BINDING_MISMATCH",
            lambda: provider.evaluate(request, delegation=stolen, capability=_CAPABILITY))
    own = _sign_delegation(delegatee_id=principal.principal_id,
                           confirmation_key_thumbprint=workload_key_thumbprint(other))
    request = _delegated_policy_request(principal, digest, own)
    assert provider.evaluate(request, delegation=own, capability=_CAPABILITY).effect is (
        PolicyEffect.PERMIT)


def test_repair5_grant_nonce_cannot_be_reused_by_another_grant(
    principal: AuthenticatedPrincipal, opa_delegated: tuple[OpaPolicyDecisionProvider, str],
):
    provider, digest = opa_delegated
    grant = _sign_delegation(delegatee_id=principal.principal_id)
    request = _delegated_policy_request(principal, digest, grant)
    for _ in range(2):  # the same standing grant may be presented again
        assert provider.evaluate(request, delegation=grant, capability=_CAPABILITY).effect is (
            PolicyEffect.PERMIT)
    twin = _sign_delegation(delegatee_id=principal.principal_id, nonce=grant.nonce,
                            permitted_purposes=("read-site-1", "audit-site-1"))
    _expect("DELEGATION_REPLAY",
            lambda: provider.evaluate(request, delegation=twin, capability=_CAPABILITY))


def _grant_chain(
    principal: AuthenticatedPrincipal, digest: str, *,
    root: dict[str, object] | None = None, child: dict[str, object] | None = None,
) -> tuple[SignedDelegation, SignedDelegation]:
    root_fields: dict[str, object] = {
        "delegatee_id": "intermediary-1", "delegation_id": "urn:ocor:delegation:root",
        "policy_bundle_digest": digest, "redelegation_allowed": True, "max_chain_depth": 2,
        "domains": ("domain-a", "domain-b"), "compartments": ("compartment-a", "compartment-b"),
        "permitted_purposes": ("read-site-1", "audit-site-1"),
        "effect_ceiling": OperationClass.R1_ANALYZE, "risk_ceiling": RiskClass.R1_ANALYZE,
    }
    root_fields.update(root or {})
    root_grant = _sign_delegation(**root_fields)  # type: ignore[arg-type]
    child_fields: dict[str, object] = {
        "delegatee_id": principal.principal_id, "delegator_id": "intermediary-1",
        "delegation_id": "urn:ocor:delegation:child", "policy_bundle_digest": digest,
        "parent_grant_digest": root_grant.digest(),
        "expires_at": _now() + timedelta(minutes=30),
    }
    child_fields.update(child or {})
    return root_grant, _sign_delegation(**child_fields)  # type: ignore[arg-type]


def test_repair5_two_hop_chain_on_real_backends(
    principal: AuthenticatedPrincipal, opa_delegated: tuple[OpaPolicyDecisionProvider, str],
):
    provider, digest = opa_delegated
    chain = _grant_chain(principal, digest)
    request = _delegated_policy_request(principal, digest, chain)
    assert request.governed_context.actor_chain == ("delegator-1", "intermediary-1",
                                                    principal.principal_id)
    decision = provider.evaluate(request, delegation=chain, capability=_CAPABILITY)
    assert decision.effect is PolicyEffect.PERMIT
    assert decision.valid_until <= _canonical(chain[1].expires_at)
    decision.verify(request, at=_now())


def _canonical(instant: datetime) -> datetime:
    return instant.astimezone(UTC).replace(microsecond=0)


@pytest.mark.parametrize("root,child,reason", [
    ({"redelegation_allowed": False}, {}, "DELEGATION_REDELEGATION_FORBIDDEN"),
    ({}, {"parent_grant_digest": "urn:sha256:" + "d" * 64}, "DELEGATION_CHAIN_INVALID"),
    ({"parent_grant_digest": "urn:sha256:" + "d" * 64}, {}, "DELEGATION_CHAIN_INVALID"),
    ({}, {"domains": ("domain-a", "domain-c")}, "DELEGATION_AMPLIFICATION"),
    ({}, {"compartments": ("compartment-a", "compartment-c")}, "DELEGATION_AMPLIFICATION"),
    ({}, {"permitted_purposes": ("read-site-1", "write-site-1")}, "DELEGATION_AMPLIFICATION"),
    ({}, {"effect_ceiling": OperationClass.R2_CONTROLLED}, "DELEGATION_AMPLIFICATION"),
    ({}, {"risk_ceiling": RiskClass.R2_CONTROLLED}, "DELEGATION_AMPLIFICATION"),
    ({}, {"expires_at": _now() + timedelta(hours=3)}, "DELEGATION_AMPLIFICATION"),
    ({}, {"max_chain_depth": 2}, "DELEGATION_AMPLIFICATION"),
    ({"max_chain_depth": 1, "redelegation_allowed": True}, {}, "DELEGATION_CHAIN_TOO_DEEP"),
])
def test_repair5_chain_cannot_amplify_or_exceed_its_limits(
    principal: AuthenticatedPrincipal, opa_delegated: tuple[OpaPolicyDecisionProvider, str],
    root: dict[str, object], child: dict[str, object], reason: str,
):
    provider, digest = opa_delegated
    chain = _grant_chain(principal, digest, root=root, child=child)
    request = _delegated_policy_request(principal, digest, chain)
    _expect(reason, lambda: provider.evaluate(request, delegation=chain, capability=_CAPABILITY))


def test_repair5_chain_links_every_actor_and_rejects_cycles(
    principal: AuthenticatedPrincipal, opa_delegated: tuple[OpaPolicyDecisionProvider, str],
):
    provider, digest = opa_delegated
    root_grant, child_grant = _grant_chain(principal, digest)
    swapped = (child_grant, root_grant)
    request = _delegated_policy_request(principal, digest, (root_grant, child_grant))
    _expect("DELEGATION_BINDING_MISMATCH",
            lambda: provider.evaluate(request, delegation=swapped, capability=_CAPABILITY))
    _expect("DELEGATION_BINDING_MISMATCH",
            lambda: provider.evaluate(request, delegation=child_grant, capability=_CAPABILITY))
    # A cyclic actor chain cannot even be expressed as a governed context.
    with pytest.raises(GovernedContextError):
        _delegated_policy_request(
            principal, digest, root_grant,
            actor_chain=(principal.principal_id, "intermediary-1", principal.principal_id))


def test_repair5_revoking_any_chain_link_denies(
    principal: AuthenticatedPrincipal, opa_delegated: tuple[OpaPolicyDecisionProvider, str],
):
    provider, digest = opa_delegated
    chain = _grant_chain(principal, digest)
    request = _delegated_policy_request(principal, digest, chain)
    assert provider.evaluate(request, delegation=chain, capability=_CAPABILITY).effect is (
        PolicyEffect.PERMIT)
    provider.apply_revocation(_sign_revocation(chain[0].grant_id))
    _expect("DELEGATION_REVOKED",
            lambda: provider.evaluate(request, delegation=chain, capability=_CAPABILITY))


def test_repair5_runtime_revocation_applies_to_new_calls(
    principal: AuthenticatedPrincipal, opa_delegated: tuple[OpaPolicyDecisionProvider, str],
):
    provider, digest = opa_delegated
    grant = _sign_delegation(delegatee_id=principal.principal_id)
    request = _delegated_policy_request(principal, digest, grant)
    assert provider.evaluate(request, delegation=grant, capability=_CAPABILITY).effect is (
        PolicyEffect.PERMIT)
    forged = replace(_sign_revocation("urn:ocor:delegation:unrelated"),
                     delegation_id=grant.grant_id)
    _expect("DELEGATION_REVOCATION_INVALID", lambda: provider.apply_revocation(forged))
    assert provider.evaluate(request, delegation=grant, capability=_CAPABILITY).effect is (
        PolicyEffect.PERMIT)
    provider.apply_revocation(_sign_revocation(grant.grant_id))
    _expect("DELEGATION_REVOKED",
            lambda: provider.evaluate(request, delegation=grant, capability=_CAPABILITY))


def test_repair5_revocation_while_policy_is_evaluating(
    principal: AuthenticatedPrincipal, mtls: dict[str, object],
):
    provider = OpaPolicyDecisionProvider(
        str(mtls["opa"]), POLICY_ID, signer_public_key=(_SIGNER_N, _SIGNER_E),
        delegation_signer_public_key=(_SIGNER_N, _SIGNER_E), ssl_context=mtls["ssl_context"])
    digest = _install_policy(provider, _rego(principal.principal_id))
    grant = _sign_delegation(delegatee_id=principal.principal_id)
    request = _delegated_policy_request(principal, digest, grant)
    assert provider.evaluate(request, delegation=grant, capability=_CAPABILITY).effect is (
        PolicyEffect.PERMIT)
    proxy = mtls["proxies"][0]
    applied: list[bool] = []

    def revoke() -> None:
        provider.apply_revocation(_sign_revocation(grant.grant_id))
        applied.append(True)

    proxy.before_eval = revoke
    try:
        _expect("DELEGATION_REVOKED",
                lambda: provider.evaluate(request, delegation=grant, capability=_CAPABILITY))
        assert applied
    finally:
        proxy.before_eval = proxy.after_eval = None


_UNSIGNED_ERASE = 'package ocor.control_plane\n\nallow if { input.action == "erase" }\n'


def _opa_put(module_id: str, source: str) -> None:
    status, body = _http("PUT", f"{OPA}/v1/policies/{module_id}",
                         headers={"Content-Type": "text/plain"}, body=source)
    assert status == 200, body


def _opa_delete(module_id: str) -> None:
    _http("DELETE", f"{OPA}/v1/policies/{module_id}")


@pytest.mark.parametrize("removed_before_response", [False, True])
def test_repair5_module_injected_after_freshness_check_is_stale(
    principal: AuthenticatedPrincipal, mtls: dict[str, object], removed_before_response: bool,
):
    # VF-002 (cycle 4) counterexample: an unsigned module enters the governed
    # package after the freshness check and before the real evaluation.  When
    # it is also removed before the response returns, no later listing can
    # see it: only the evaluation's own provenance can.
    provider = OpaPolicyDecisionProvider(
        str(mtls["opa"]), POLICY_ID, signer_public_key=(_SIGNER_N, _SIGNER_E),
        ssl_context=mtls["ssl_context"])
    digest = _install_policy(provider, _rego(principal.principal_id))
    request = _policy_request(principal, digest, action="erase")
    assert provider.evaluate(request).effect is PolicyEffect.DENY
    module = "repair5-race-" + uuid.uuid4().hex
    events: list[str] = []
    proxy = mtls["proxies"][0]
    proxy.before_eval = lambda: (_opa_put(module, _UNSIGNED_ERASE), events.append("injected"))
    if removed_before_response:
        proxy.after_eval = lambda: (_opa_delete(module), events.append("removed"))
    try:
        error = _expect("STALE_BUNDLE", lambda: provider.evaluate(request))
        assert events == (["injected", "removed"] if removed_before_response else ["injected"])
        assert request.governed_context.correlation_id in str(error)
        if removed_before_response:
            assert "evaluated rule is not part of the verified policy bundle" in str(error)
    finally:
        proxy.before_eval = proxy.after_eval = None
        _opa_delete(module)
    assert provider.evaluate(_policy_request(principal, digest, action="erase")).effect is (
        PolicyEffect.DENY)


def test_repair5_signed_module_swapped_during_evaluation_is_stale(
    principal: AuthenticatedPrincipal, mtls: dict[str, object],
):
    provider = OpaPolicyDecisionProvider(
        str(mtls["opa"]), POLICY_ID, signer_public_key=(_SIGNER_N, _SIGNER_E),
        ssl_context=mtls["ssl_context"])
    source = _rego(principal.principal_id)
    digest = _install_policy(provider, source)
    request = _policy_request(principal, digest, action="erase")
    assert provider.evaluate(request).effect is PolicyEffect.DENY
    widened = source + '\nallow if { input.action == "erase" }\n'
    proxy = mtls["proxies"][0]
    proxy.before_eval = lambda: _opa_put(POLICY_ID, widened)
    proxy.after_eval = lambda: _opa_put(POLICY_ID, source)
    try:
        error = _expect("STALE_BUNDLE", lambda: provider.evaluate(request))
        assert "evaluated rule is not part of the verified policy bundle" in str(error)
    finally:
        proxy.before_eval = proxy.after_eval = None
        _opa_put(POLICY_ID, source)
    assert provider.evaluate(_policy_request(principal, digest, action="erase")).effect is (
        PolicyEffect.DENY)


def test_repair5_enclosing_package_rule_head_is_stale(
    principal: AuthenticatedPrincipal, mtls: dict[str, object],
):
    provider = OpaPolicyDecisionProvider(
        str(mtls["opa"]), POLICY_ID, signer_public_key=(_SIGNER_N, _SIGNER_E),
        ssl_context=mtls["ssl_context"])
    digest = _install_policy(provider, _rego(principal.principal_id))
    request = _policy_request(principal, digest, action="erase")
    assert provider.evaluate(request).effect is PolicyEffect.DENY
    module = "repair5-enclosing-" + uuid.uuid4().hex
    _opa_put(module, 'package ocor\n\ncontrol_plane.allow if { input.action == "erase" }\n')
    try:
        _expect("STALE_BUNDLE", lambda: provider.evaluate(request))
    finally:
        _opa_delete(module)
    assert provider.evaluate(request).effect is PolicyEffect.DENY


@pytest.mark.parametrize("dependency", [
    "data.ocor.extra.flag == true",
    "data.ocor.control_plane.flag == true",
    "data.ocor.bootstrap.allow == false",
])
def test_repair5_bundle_depending_on_unsigned_data_is_rejected(
    principal: AuthenticatedPrincipal, mtls: dict[str, object], dependency: str,
):
    provider = OpaPolicyDecisionProvider(
        str(mtls["opa"]), POLICY_ID, signer_public_key=(_SIGNER_N, _SIGNER_E),
        ssl_context=mtls["ssl_context"])
    rego = (
        "package ocor.control_plane\n\ndefault allow := false\n\n"
        f"allow if {{\n    input.action == \"read\"\n    {dependency}\n}}\n"
    )
    _expect("POLICY_BUNDLE_INVALID", lambda: provider.install_policy(_sign_bundle(rego)))


def test_repair5_self_contained_bundle_with_local_rules_is_accepted(
    principal: AuthenticatedPrincipal, mtls: dict[str, object],
):
    provider = OpaPolicyDecisionProvider(
        str(mtls["opa"]), POLICY_ID, signer_public_key=(_SIGNER_N, _SIGNER_E),
        ssl_context=mtls["ssl_context"])
    rego = (
        "package ocor.control_plane\n\ndefault allow := false\n\n"
        'reader if input.action == "read"\n\n'
        "allow if {\n    reader\n"
        f'    input.principal_id == "{principal.principal_id}"\n'
        '    input.resource == "urn:ocor:target:site-1"\n}\n'
    )
    digest = provider.install_policy(_sign_bundle(rego))
    assert provider.evaluate(_policy_request(principal, digest, action="read")).effect is (
        PolicyEffect.PERMIT)
    assert provider.evaluate(_policy_request(principal, digest, action="erase")).effect is (
        PolicyEffect.DENY)


def test_repair5_policy_receives_release_pin_capability_and_grants(
    principal: AuthenticatedPrincipal, mtls: dict[str, object],
):
    provider = OpaPolicyDecisionProvider(
        str(mtls["opa"]), POLICY_ID, signer_public_key=(_SIGNER_N, _SIGNER_E),
        delegation_signer_public_key=(_SIGNER_N, _SIGNER_E), ssl_context=mtls["ssl_context"])
    rego = (
        "package ocor.control_plane\n\ndefault allow := false\n\n"
        "allow if {\n"
        f'    input.ontology_release_digest == "urn:sha256:{"1" * 64}"\n'
        "    input.policy_bundle_digest != \"\"\n"
        "    input.correlation_id != \"\"\n"
        '    input.capability.capability_id == "urn:ocor:capability:read-site"\n'
        '    input.capability.effect_class == "R0_READ"\n'
        '    input.delegation_grant_ids == ["urn:ocor:delegation:test"]\n'
        "}\n"
    )
    digest = provider.install_policy(_sign_bundle(rego))
    grant = _sign_delegation(delegatee_id=principal.principal_id, policy_bundle_digest=digest)
    request = _delegated_policy_request(principal, digest, grant)
    assert provider.evaluate(request, delegation=grant, capability=_CAPABILITY).effect is (
        PolicyEffect.PERMIT)
    other_release = _delegated_policy_request(
        principal, digest, grant, ontology_release_digest="urn:sha256:" + "2" * 64)
    assert provider.evaluate(other_release, delegation=grant, capability=_CAPABILITY).effect is (
        PolicyEffect.DENY)


def test_repair5_boundary_recomputes_governed_context_digest(
    principal: AuthenticatedPrincipal, opa: tuple[OpaPolicyDecisionProvider, str],
):
    provider, digest = opa
    request = _policy_request(principal, digest)
    assert provider.evaluate(request).effect is PolicyEffect.PERMIT
    forged = replace(request)
    object.__setattr__(forged, "governed_context_digest", "urn:sha256:" + "e" * 64)
    _expect("GOVERNED_CONTEXT_MISMATCH", lambda: provider.evaluate(forged))


def test_repair5_secret_lease_is_bound_to_the_authenticated_principal(
    principal: AuthenticatedPrincipal, env: dict[str, str], mtls: dict[str, object],
):
    name = "repair5-isolation-" + uuid.uuid4().hex
    victim = "repair5-victim-" + uuid.uuid4().hex
    _seed_secret(env, principal.principal_id, name, {"value": "own"})
    _seed_secret(env, victim, name, {"value": "victim"})
    provider = OpenBaoSecretProvider(str(mtls["openbao"]), env["OCOR_LOCAL_OPENBAO_TOKEN"],
                                     ssl_context=mtls["ssl_context"])
    own = SecretRequest("urn:ocor:secret-ref:" + name, principal.principal_id,
                        "read-site-1", "urn:sha256:" + "1" * 64, _now())
    short = replace(principal, expires_at=_now() + timedelta(seconds=30))
    lease = provider.lease(own, principal=short)
    assert lease.expires_at <= short.expires_at
    lease.verify(own, at=_now())
    foreign = SecretRequest("urn:ocor:secret-ref:" + name, victim,
                            "read-site-1", "urn:sha256:" + "1" * 64, _now())
    _expect("SECRET_BINDING_MISMATCH", lambda: provider.lease(foreign, principal=principal))
    _expect("SECRET_BINDING_MISMATCH", lambda: provider.lease(own))
    expired = replace(principal, expires_at=_now() + timedelta(seconds=1))
    _wait_past(expired.expires_at)
    _expect("IDENTITY_EXPIRED", lambda: provider.lease(own, principal=expired))


# --------------------------------------------------------------------------- #
# REPAIR-6: a signed OIDC ``act`` claim authenticates actors, never a grant
# --------------------------------------------------------------------------- #


def _keycloak_admin_headers(env: dict[str, str]) -> dict[str, str]:
    import urllib.parse
    status, body = _http("POST", KC + "/realms/master/protocol/openid-connect/token",
                         headers={"Content-Type": "application/x-www-form-urlencoded"},
                         body=urllib.parse.urlencode({
                             "client_id": "admin-cli", "username": "ocor-admin",
                             "password": env["OCOR_LOCAL_KEYCLOAK_PASSWORD"],
                             "grant_type": "password"}))
    assert status == 200, body
    return {"Authorization": "Bearer " + json.loads(body)["access_token"],
            "Content-Type": "application/json"}


def _analyst_subject(headers: dict[str, str]) -> str:
    status, body = _http("GET", f"{KC}/admin/realms/{REALM}/users?username={USERNAME}",
                         headers=headers)
    assert status == 200, body
    return str(json.loads(body)[0]["id"])


@pytest.fixture
def repair6_act(env, principals, mtls, request):
    """A real Keycloak client whose access tokens carry a signed ``act`` claim.

    ``request.param`` is ``(claim_value, json_type)``; ``{sub}`` in the value
    is replaced by the analyst's own subject.  Keycloak signs the token, so
    the claim reaches the provider exactly as an RFC 8693 actor claim would.
    """
    value, json_type = request.param
    headers = _keycloak_admin_headers(env)
    value = value.replace("{sub}", _analyst_subject(headers))
    client_id = "repair6-" + uuid.uuid4().hex
    payload = {"clientId": client_id, "enabled": True, "publicClient": True,
               "directAccessGrantsEnabled": True, "protocol": "openid-connect",
               "protocolMappers": [{
                   "name": "repair6-act", "protocol": "openid-connect",
                   "protocolMapper": "oidc-hardcoded-claim-mapper",
                   "config": {"claim.name": "act", "claim.value": value,
                              "jsonType.label": json_type, "access.token.claim": "true"}}]}
    status, body = _http("POST", f"{KC}/admin/realms/{REALM}/clients", headers=headers,
                         body=json.dumps(payload))
    assert status == 201, body
    status, body = _http("GET", f"{KC}/admin/realms/{REALM}/clients?clientId={client_id}",
                         headers=headers)
    assert status == 200, body
    uid = json.loads(body)[0]["id"]
    try:
        yield KeycloakIdentityProvider(str(mtls["keycloak"]), REALM, client_id,
                                       password_resolver=lambda _: USER_PWD,
                                       ssl_context=mtls["ssl_context"])
    finally:
        headers = _keycloak_admin_headers(env)
        assert _http("DELETE", f"{KC}/admin/realms/{REALM}/clients/{uid}",
                     headers=headers)[0] == 204


def _authenticate(provider: KeycloakIdentityProvider) -> AuthenticatedPrincipal:
    return provider.authenticate(IdentityRequest(
        "urn:ocor:credential-ref:" + USERNAME, "account", str(uuid.uuid4())))


_ACT_DELEGATOR = ('{"sub": "delegator-1"}', "JSON")
_ACT_INTERMEDIARY = ('{"sub": "intermediary-1"}', "JSON")
_ACT_NESTED = ('{"sub": "intermediary-1", "act": {"sub": "delegator-1"}}', "JSON")


def _delegated_opa(mtls: dict[str, object], principal_id: str) -> tuple[
        OpaPolicyDecisionProvider, str]:
    provider = OpaPolicyDecisionProvider(
        str(mtls["opa"]), POLICY_ID, signer_public_key=(_SIGNER_N, _SIGNER_E),
        delegation_signer_public_key=(_SIGNER_N, _SIGNER_E), ssl_context=mtls["ssl_context"])
    return provider, _install_policy(provider, _rego(principal_id))


@pytest.mark.parametrize("repair6_act,expected", [
    (_ACT_DELEGATOR, ("delegator-1",)),
    (_ACT_NESTED, ("delegator-1", "intermediary-1")),
], indirect=["repair6_act"])
def test_repair6_signed_act_claim_authenticates_the_actor_chain(repair6_act, expected):
    principal = _authenticate(repair6_act)
    assert principal.actor_chain == expected + (principal.principal_id,)


@pytest.mark.parametrize("repair6_act", [
    ('"delegator-1"', "String"),
    ('{"client_id": "delegator-1"}', "JSON"),
    ('{"sub": ""}', "JSON"),
    ('{"sub": 7}', "JSON"),
    ('{"sub": "{sub}"}', "JSON"),
    ('{"sub": "delegator-1", "act": {"sub": "delegator-1"}}', "JSON"),
    ('{"sub": "delegator-1", "act": "intermediary-1"}', "JSON"),
], indirect=True)
def test_repair6_malformed_act_claim_is_rejected(repair6_act):
    # The reason must be the signed actor claim itself, never a transport or
    # grant failure that would also surface as IDENTITY_REJECTED.
    error = _expect("IDENTITY_REJECTED", lambda: _authenticate(repair6_act))
    assert "actor claim" in str(error), str(error)


@pytest.mark.parametrize("repair6_act", [_ACT_DELEGATOR], indirect=True)
def test_repair6_act_claim_does_not_replace_the_grant(repair6_act, mtls):
    principal = _authenticate(repair6_act)
    provider, digest = _delegated_opa(mtls, principal.principal_id)
    grant = _sign_delegation(delegatee_id=principal.principal_id)
    request = _delegated_policy_request(principal, digest, grant)
    assert request.governed_context.actor_chain == principal.actor_chain
    # Positive: the authenticated actors plus the complete signed grant.
    decision = provider.evaluate(request, delegation=grant, capability=_CAPABILITY)
    assert decision.effect is PolicyEffect.PERMIT
    decision.verify(request, at=_now())
    # Negative: the same signed act claim without the grant, with or without
    # a declared capability, and with the authenticated actor omitted.
    _expect("DELEGATION_REQUIRED", lambda: provider.evaluate(request))
    _expect("DELEGATION_REQUIRED", lambda: provider.evaluate(request, capability=_CAPABILITY))
    _expect("DELEGATION_REQUIRED", lambda: provider.evaluate(_policy_request(principal, digest)))
    _expect("DELEGATION_INVALID", lambda: provider.evaluate(request, delegation=()))
    _expect("DELEGATION_INVALID", lambda: provider.evaluate(request, delegation=grant))
    # Revocation: presenting the revoked grant and omitting it are both denied.
    provider.apply_revocation(_sign_revocation(grant.grant_id))
    _expect("DELEGATION_REVOKED",
            lambda: provider.evaluate(request, delegation=grant, capability=_CAPABILITY))
    _expect("DELEGATION_REQUIRED", lambda: provider.evaluate(request))


@pytest.mark.parametrize("overrides,reason", [
    ({"not_before": _now() - timedelta(minutes=10), "expires_at": _now() - timedelta(minutes=1)},
     "DELEGATION_EXPIRED"),
    ({"not_before": _now() + timedelta(minutes=10), "expires_at": _now() + timedelta(hours=1)},
     "DELEGATION_EXPIRED"),
    ({"resource_scope": "urn:ocor:target:other-site"}, "DELEGATION_SCOPE_MISMATCH"),
    ({"permitted_purposes": ("write-site-1",)}, "DELEGATION_PURPOSE_MISMATCH"),
    ({"capability_id": "urn:ocor:capability:other"}, "DELEGATION_CAPABILITY_MISMATCH"),
    ({"effect_ceiling": OperationClass.R0_READ, "risk_ceiling": RiskClass.R0_READ,
      "_capability": OperationClass.R1_ANALYZE}, "DELEGATION_CEILING_EXCEEDED"),
    ({"delegator_id": "delegator-2"}, "IDENTITY_BINDING_MISMATCH"),
    ({"confirmation_key_thumbprint": "urn:sha256:" + "a" * 64},
     "DELEGATION_KEY_BINDING_MISMATCH"),
])
@pytest.mark.parametrize("repair6_act", [_ACT_DELEGATOR], indirect=True)
def test_repair6_act_principal_grant_is_fully_verified(repair6_act, mtls, overrides, reason):
    principal = _authenticate(repair6_act)
    provider, digest = _delegated_opa(mtls, principal.principal_id)
    fields = dict(overrides)
    effect = fields.pop("_capability", None)
    capability = _CAPABILITY if effect is None else replace(_CAPABILITY, effect_class=effect)
    grant = _sign_delegation(delegatee_id=principal.principal_id, **fields)  # type: ignore[arg-type]
    request = _delegated_policy_request(principal, digest, grant)
    _expect(reason, lambda: provider.evaluate(request, delegation=grant, capability=capability))


@pytest.mark.parametrize("repair6_act,expected", [
    (_ACT_INTERMEDIARY, None),
    (_ACT_NESTED, None),
    (_ACT_DELEGATOR, "IDENTITY_BINDING_MISMATCH"),
], indirect=["repair6_act"])
def test_repair6_authenticated_actors_are_the_exact_chain_tail(repair6_act, mtls, expected):
    principal = _authenticate(repair6_act)
    provider, digest = _delegated_opa(mtls, principal.principal_id)
    chain = _grant_chain(principal, digest)
    request = _delegated_policy_request(principal, digest, chain)
    assert request.governed_context.actor_chain == (
        "delegator-1", "intermediary-1", principal.principal_id)
    if expected is None:
        decision = provider.evaluate(request, delegation=chain, capability=_CAPABILITY)
        assert decision.effect is PolicyEffect.PERMIT
    else:
        _expect(expected,
                lambda: provider.evaluate(request, delegation=chain, capability=_CAPABILITY))
    # Dropping the root grant can never shorten the authenticated chain.
    child = _sign_delegation(delegatee_id=principal.principal_id, delegator_id="intermediary-1",
                             policy_bundle_digest=digest)
    short = _delegated_policy_request(principal, digest, child)
    reason = "IDENTITY_BINDING_MISMATCH" if len(principal.actor_chain) > 2 or (
        principal.actor_chain[0] != "intermediary-1") else None
    if reason is None:
        assert provider.evaluate(short, delegation=child, capability=_CAPABILITY).effect is (
            PolicyEffect.PERMIT)
    else:
        _expect(reason, lambda: provider.evaluate(short, delegation=child, capability=_CAPABILITY))
    _expect("DELEGATION_REQUIRED", lambda: provider.evaluate(request))


def test_repair6_non_delegated_principal_needs_exactly_its_own_chain(
    principal: AuthenticatedPrincipal, opa: tuple[OpaPolicyDecisionProvider, str],
):
    provider, digest = opa
    assert principal.actor_chain == (principal.principal_id,)
    assert provider.evaluate(_policy_request(principal, digest)).effect is PolicyEffect.PERMIT
    for chain in (("delegator-1", principal.principal_id), (principal.principal_id, "x-1"),
                  ("delegator-1",)):
        gcs = replace(_gcs(principal, digest), actor_chain=chain)
        request = PolicyRequest(principal=principal, action="read",
                                resource="urn:ocor:target:site-1", governed_context=gcs,
                                governed_context_digest=gcs.digest(), at=_now())
        _expect("IDENTITY_BINDING_MISMATCH", lambda: provider.evaluate(request))


@pytest.mark.parametrize("repair6_act", [_ACT_DELEGATOR], indirect=True)
def test_repair6_delegated_session_cannot_lease_a_secret_without_a_grant(
    repair6_act, principal: AuthenticatedPrincipal, env: dict[str, str], mtls: dict[str, object],
):
    delegated = _authenticate(repair6_act)
    assert delegated.principal_id == principal.principal_id
    name = "repair6-lease-" + uuid.uuid4().hex
    _seed_secret(env, principal.principal_id, name, {"value": "own"})
    provider = OpenBaoSecretProvider(str(mtls["openbao"]), env["OCOR_LOCAL_OPENBAO_TOKEN"],
                                     ssl_context=mtls["ssl_context"])
    request = SecretRequest("urn:ocor:secret-ref:" + name, principal.principal_id,
                            "read-site-1", "urn:sha256:" + "1" * 64, _now())
    provider.lease(request, principal=principal).verify(request, at=_now())
    _expect("DELEGATION_REQUIRED", lambda: provider.lease(request, principal=delegated))


# --------------------------------------------------------------------------- #
# REPAIR-6 path audit: every remaining authentication, evaluation and SVID
# branch is exercised with real Keycloak, OPA and SPIRE material.
# --------------------------------------------------------------------------- #


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_json(segment: str) -> dict[str, object]:
    return json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))


def _control_plane_keycloak(mtls: dict[str, object], client_id: str = CLIENT_ID):
    return KeycloakIdentityProvider(str(mtls["keycloak"]), REALM, client_id,
                                    password_resolver=lambda _: USER_PWD,
                                    ssl_context=mtls["ssl_context"])


def test_repair6_access_token_verification_branches(principals, mtls):
    provider = _control_plane_keycloak(mtls)
    configuration = provider._oidc_configuration()
    issuer = str(configuration["issuer"])
    jwks = provider._jwks(provider._secure_endpoint(str(configuration["jwks_uri"])))
    token = provider._password_grant(
        provider._secure_endpoint(str(configuration["token_endpoint"])), USERNAME, USER_PWD)
    claims = provider._verify_access_token(token, jwks, issuer, "account")
    assert isinstance(claims["sub"], str) and "act" not in claims
    header, payload, signature = token.split(".")
    head, body = _b64url_json(header), _b64url_json(payload)
    forged = {
        "malformed JWT": header + "." + payload,
        "unsupported JWT algorithm": _b64url(json.dumps({**head, "alg": "none"}).encode())
        + "." + payload + "." + signature,
        "unknown signing key": _b64url(json.dumps({**head, "kid": "forged-kid"}).encode())
        + "." + payload + "." + signature,
        # An actor claim cannot be added to a signed token after issuance.
        "JWT signature check failed": header + "."
        + _b64url(json.dumps({**body, "act": {"sub": "delegator-1"}}).encode())
        + "." + signature,
    }
    for message, value in forged.items():
        error = _expect("IDENTITY_REJECTED",
                        lambda value=value: provider._verify_access_token(
                            value, jwks, issuer, "account"))
        assert message in str(error), str(error)
    error = _expect("IDENTITY_REJECTED",
                    lambda: provider._verify_access_token(token, jwks, issuer + "-x", "account"))
    assert "issuer mismatch" in str(error)
    error = _expect("IDENTITY_REJECTED",
                    lambda: provider._verify_access_token(token, jwks, issuer, "other-audience"))
    assert "audience mismatch" in str(error)


def test_repair6_credential_reference_branches(principals, mtls):
    provider = _control_plane_keycloak(mtls)
    principal = provider.authenticate(IdentityRequest(
        "urn:ocor:credential-ref:" + USERNAME, "account", str(uuid.uuid4())))
    assert principal.actor_chain == (principal.principal_id,)
    empty = IdentityRequest("urn:ocor:credential-ref:", "account", str(uuid.uuid4()))
    error = _expect("IDENTITY_REJECTED", lambda: provider.authenticate(empty))
    assert "empty credential reference" in str(error)
    foreign = IdentityRequest("urn:ocor:credential-ref:" + USERNAME, "account",
                              str(uuid.uuid4()))
    object.__setattr__(foreign, "credential_ref", "urn:other:" + USERNAME)
    error = _expect("IDENTITY_REJECTED", lambda: provider.authenticate(foreign))
    assert "unknown credential reference" in str(error)


@pytest.fixture
def repair6_subjectless_client(env, principals, mtls):
    """A real client whose tokens carry the audience but no ``sub`` claim."""
    headers = _keycloak_admin_headers(env)
    client_id = "repair6-nosub-" + uuid.uuid4().hex
    payload = {"clientId": client_id, "enabled": True, "publicClient": True,
               "directAccessGrantsEnabled": True, "protocol": "openid-connect",
               "protocolMappers": [{
                   "name": "repair6-audience", "protocol": "openid-connect",
                   "protocolMapper": "oidc-audience-mapper",
                   "config": {"included.custom.audience": "account",
                              "access.token.claim": "true"}}]}
    status, body = _http("POST", f"{KC}/admin/realms/{REALM}/clients", headers=headers,
                         body=json.dumps(payload))
    assert status == 201, body
    status, body = _http("GET", f"{KC}/admin/realms/{REALM}/clients?clientId={client_id}",
                         headers=headers)
    uid = json.loads(body)[0]["id"]
    try:
        status, body = _http("GET", f"{KC}/admin/realms/{REALM}/clients/{uid}/default-client-scopes",
                             headers=headers)
        assert status == 200, body
        for scope in json.loads(body):
            assert _http("DELETE", f"{KC}/admin/realms/{REALM}/clients/{uid}/"
                         f"default-client-scopes/{scope['id']}", headers=headers)[0] == 204
        yield _control_plane_keycloak(mtls, client_id)
    finally:
        assert _http("DELETE", f"{KC}/admin/realms/{REALM}/clients/{uid}",
                     headers=_keycloak_admin_headers(env))[0] == 204


def test_repair6_token_without_subject_is_rejected(repair6_subjectless_client, mtls):
    provider = repair6_subjectless_client
    configuration = provider._oidc_configuration()
    token = provider._password_grant(
        provider._secure_endpoint(str(configuration["token_endpoint"])), USERNAME, USER_PWD)
    jwks = provider._jwks(provider._secure_endpoint(str(configuration["jwks_uri"])))
    claims = provider._verify_access_token(token, jwks, str(configuration["issuer"]), "account")
    assert "sub" not in claims  # the real token verifies: only the subject is missing
    error = _expect("IDENTITY_REJECTED", lambda: _authenticate(provider))
    assert "missing subject claim" in str(error)
    assert _authenticate(_control_plane_keycloak(mtls)).principal_id


def test_repair6_forged_svid_chain_is_rejected(env):
    from ocor_runtime.security.control_plane import (
        _parse_certificate,
        _verify_certificate_signature,
    )
    provider = SpireWorkloadIdentityProvider(
        agent_container=SPIRE_AGENT_CONTAINER, socket_path=SPIRE_SOCKET,
        expected_spiffe_id=EXPECTED_SPIFFE_ID)
    assert provider.current().spiffe_id == EXPECTED_SPIFFE_ID
    svid = provider._fetch_svid()
    chain = _split_der_chain(_b64_decode(str(svid["x509_svid"])))
    certificates = [_parse_certificate(der) for der in chain + [_b64_decode(str(svid["bundle"]))]]
    for child, issuer in zip(certificates, certificates[1:]):
        _verify_certificate_signature(child, issuer)
    leaf, intermediate, root = certificates[0], certificates[1], certificates[-1]
    tampered_tbs = bytearray(leaf["tbs_der"])  # type: ignore[arg-type]
    tampered_tbs[-1] ^= 0x01
    for forged, issuer in (
        ({**leaf, "tbs_der": bytes(tampered_tbs)}, intermediate),
        ({**leaf, "sigalg_oid": b"\x2a\x03"}, intermediate),
        (leaf, root),
        (intermediate, leaf),
    ):
        _expect("SVID_CHAIN_INVALID",
                lambda forged=forged, issuer=issuer: _verify_certificate_signature(forged, issuer))


def test_repair6_boundary_rechecks_the_principal_binding(
    principal: AuthenticatedPrincipal, opa: tuple[OpaPolicyDecisionProvider, str],
):
    provider, digest = opa
    request = _policy_request(principal, digest)
    assert provider.evaluate(request).effect is PolicyEffect.PERMIT
    other = replace(request.governed_context, effective_principal_id="someone-else",
                    actor_chain=("someone-else",))
    forged = replace(request)
    object.__setattr__(forged, "governed_context", other)
    object.__setattr__(forged, "governed_context_digest", other.digest())
    _expect("PRINCIPAL_BINDING_MISMATCH", lambda: provider.evaluate(forged))


_CONFLICTING_REGO = (
    "package ocor.control_plane\n\n"
    'allow := true if { input.action == "read" }\n\n'
    'allow := false if { input.resource == "urn:ocor:target:site-1" }\n'
)


def test_repair6_policy_evaluation_error_fails_closed(
    principal: AuthenticatedPrincipal, mtls: dict[str, object],
):
    provider = OpaPolicyDecisionProvider(str(mtls["opa"]), POLICY_ID,
                                         signer_public_key=(_SIGNER_N, _SIGNER_E),
                                         ssl_context=mtls["ssl_context"])
    digest = _install_policy(provider, _CONFLICTING_REGO)
    gcs = _gcs(principal, digest)

    def request(action: str, resource: str) -> PolicyRequest:
        return PolicyRequest(principal=principal, action=action, resource=resource,
                             governed_context=gcs, governed_context_digest=gcs.digest(),
                             at=_now())

    assert provider.evaluate(request("read", "urn:ocor:target:site-2")).effect is (
        PolicyEffect.PERMIT)
    assert provider.evaluate(request("write", "urn:ocor:target:site-1")).effect is (
        PolicyEffect.DENY)
    # Both complete-rule definitions apply: real OPA answers an evaluation
    # error, which is a denial and never a permit.
    error = _expect("POLICY_UNAVAILABLE",
                    lambda: provider.evaluate(request("read", "urn:ocor:target:site-1")))
    assert "policy eval HTTP 500" in str(error)


def test_repair7_policy_evaluation_error_keeps_correlation(
    principal: AuthenticatedPrincipal, mtls: dict[str, object],
):
    # VF-001 (repair cycle 7): the non-200 branch of evaluate() must keep the
    # request correlation in the denial diagnostic (LLD v1.1 §5.3).  This is a
    # separate positive/negative case on the real OPA boundary so the already
    # accepted cycle-6 test bodies remain byte-for-byte unchanged.
    provider = OpaPolicyDecisionProvider(str(mtls["opa"]), POLICY_ID,
                                         signer_public_key=(_SIGNER_N, _SIGNER_E),
                                         ssl_context=mtls["ssl_context"])
    digest = _install_policy(provider, _CONFLICTING_REGO)
    gcs = _gcs(principal, digest)

    def request(action: str, resource: str) -> PolicyRequest:
        return PolicyRequest(principal=principal, action=action, resource=resource,
                             governed_context=gcs, governed_context_digest=gcs.digest(),
                             at=_now())

    # Positive control: the non-conflicting rule still yields a permit.
    assert provider.evaluate(request("read", "urn:ocor:target:site-2")).effect is (
        PolicyEffect.PERMIT)
    # Negative control: a conflicting complete rule yields a denial, never a permit.
    assert provider.evaluate(request("write", "urn:ocor:target:site-1")).effect is (
        PolicyEffect.DENY)
    # Both complete-rule definitions apply: real OPA answers HTTP 500, which is a
    # denial whose diagnostic preserves the request correlation.
    error = _expect("POLICY_UNAVAILABLE",
                    lambda: provider.evaluate(request("read", "urn:ocor:target:site-1")))
    assert "policy eval HTTP 500" in str(error)
    assert gcs.correlation_id in str(error)
