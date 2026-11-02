"""OCOR-DEV-REM-0049 (NCP-U03): C2 Named Query Gateway conformance.

One test per register entry resolved by NCP-U03 of the approved plan
(``reports/development/NORMATIVE_CONFORMANCE_REGISTER.json`` ``plan_units.NCP-U03``,
NORMATIVE-CONFORMANCE-PLAN (2026-10-30)), plus the detailed cases of each entry.
The normative elements realised or verified are cited with file and line:

- ADD v1.3 = ``ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md``
- LLD v1.1 = ``docs/OCOR_LLD_v1.1.md``
- Register = ``ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md``
- Contract = ``ocor-runtime/docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml``

Oracles are independent of the implementation: the contract component schemas are
read from the contract file with PyYAML and checked with ``jsonschema``; Ed25519
audit signatures are verified with OpenSSL; the closed reason-code set is read from
the contract, never from the module under test. Backends are real: TypeDB
(projection, watermark, commit ordering), Fuseki (marking join) and PostgreSQL
(append-only audit, ``OCOR_LIVE_POSTGRES_DSN``); without them every case fails,
never skips. The context policy is an explicit test port of the sealed
``security.ports.PolicyDecisionPort`` (OPA in production, OCOR-DEV-0048).
"""

from __future__ import annotations

import ast
import base64
import dataclasses
import importlib
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import jsonschema
import pytest
import yaml

from ocor_runtime.c4.jena_adapter import JenaSHACLProjectionAdapter
from ocor_runtime.c4.typedb_adapter import TypeDBAdapterError, TypeDBProjectionAdapter
from ocor_runtime.c4_marking import MarkingEngine, MarkingSchemeDefinition, MarkingSet
from ocor_runtime.kernel.canonical import canonical_digest
from ocor_runtime.kernel.governed_context import GovernedContext
from ocor_runtime.security.ports import (
    AuthenticatedPrincipal,
    ControlName,
    ControlStatus,
    PolicyDecision,
    PolicyEffect,
    PolicyRequest,
)

RUNTIME_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = RUNTIME_ROOT.parent
SOURCE_ROOT = RUNTIME_ROOT / "src" / "ocor_runtime"
CONTRACT_PATH = RUNTIME_ROOT / "docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml"
ADD = RUNTIME_ROOT / "docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md"
LLD = REPOSITORY_ROOT / "docs/OCOR_LLD_v1.1.md"

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
RELEASE = "urn:sha256:" + "b" * 64
POLICY = "urn:sha256:" + "c" * 64
CONTRACT_DIGEST = "urn:sha256:" + "d" * 64
CONTRACT_ID = "urn:ocor:contract:named-query:fleet-object"
PRINCIPAL = "urn:ocor:principal:analyst-1"
TENANT = "urn:ocor:tenant:synthetic"
COMPARTMENT = "urn:ocor:compartment:alpha"
PURPOSE = "fleet-investigation"
SCHEME = MarkingSchemeDefinition("classification", levels=("UNCLASSIFIED", "SECRET", "TOP_SECRET"))
V1 = "urn:ocor:vessel:1"
V2 = "urn:ocor:vessel:2"
OPERATIONS = ("GetObject", "QueryObjectSet", "Search", "Traverse", "Explain", "GetProvenance")


# --------------------------------------------------------------------------- #
# Independent oracles
# --------------------------------------------------------------------------- #
def contract() -> dict[str, Any]:
    document: dict[str, Any] = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    return document


def contract_schema(name: str) -> dict[str, Any]:
    """A component schema of the gateway contract, resolvable with its own $refs."""
    document = contract()
    return {"$ref": f"#/components/schemas/{name}", "components": document["components"]}


def assert_contract_valid(name: str, instance: object) -> None:
    jsonschema.Draft202012Validator(
        contract_schema(name), format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
    ).validate(instance)


def problem_enum() -> tuple[str, ...]:
    return tuple(contract()["components"]["schemas"]["Problem"]["properties"]["reason_code"]["enum"])


def module(name: str) -> ModuleType:
    """Import a module of the runtime; a missing module is the divergence itself."""
    return importlib.import_module(f"ocor_runtime.{name}")


def internal(hex_char: str) -> str:
    return "urn:sha256:" + hex_char * 64


def wire(hex_char: str) -> str:
    return "sha256:" + hex_char * 64


# --------------------------------------------------------------------------- #
# Real backends
# --------------------------------------------------------------------------- #
def _dsn() -> str:
    dsn = os.environ.get("OCOR_LIVE_POSTGRES_DSN")
    if not dsn:
        pytest.fail("OCOR_LIVE_POSTGRES_DSN is mandatory qualifying evidence (real PostgreSQL audit)")
    return dsn


@pytest.fixture(scope="session")
def typedb_reachable() -> None:
    try:
        TypeDBProjectionAdapter().initialize()
    except (TypeDBAdapterError, OSError) as error:
        pytest.fail(f"a real, live TypeDB instance is mandatory qualifying evidence: {error}")


@pytest.fixture
def typedb(typedb_reachable: None) -> TypeDBProjectionAdapter:
    value = TypeDBProjectionAdapter()
    value.reset()
    return value


@pytest.fixture
def jena() -> JenaSHACLProjectionAdapter:
    value = JenaSHACLProjectionAdapter(MarkingEngine([SCHEME]))
    try:
        value.reset()
    except OSError as error:
        pytest.fail(f"a real, live Fuseki instance is mandatory qualifying evidence: {error}")
    return value


class AuditKeys:
    """An Ed25519 audit key generated by OpenSSL (the oracle) and its PEM public key."""

    def __init__(self, workdir: Path) -> None:
        private = workdir / "audit.pem"
        self.public_pem = workdir / "audit.pub.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)], check=True,
                       capture_output=True)
        subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(self.public_pem)],
                       check=True, capture_output=True)
        der = subprocess.run(["openssl", "pkey", "-in", str(private), "-outform", "DER"], check=True,
                             capture_output=True).stdout
        self.seed = der[-32:]
        self.workdir = workdir

    def openssl_verify(self, message: bytes, signature: bytes) -> bool:
        data = self.workdir / f"m-{uuid.uuid4().hex}"
        sig = self.workdir / f"s-{uuid.uuid4().hex}"
        data.write_bytes(message)
        sig.write_bytes(signature)
        result = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(self.public_pem),
                                 "-rawin", "-in", str(data), "-sigfile", str(sig)], capture_output=True)
        return result.returncode == 0


@pytest.fixture
def audit_keys() -> Iterator[AuditKeys]:
    with tempfile.TemporaryDirectory() as workdir:
        yield AuditKeys(Path(workdir))


@pytest.fixture
def audit_log(audit_keys: AuditKeys) -> Any:
    audit = module("audit")
    signing = module("c1.signing")
    signer = audit.AuditSigner(key=signing.Ed25519SigningKey.from_seed(audit_keys.seed),
                               keyid="urn:ocor:key:c2-audit-test")
    log = audit.PostgresAuditLog(_dsn(), schema=f"ocor_audit_rem0049_{uuid.uuid4().hex[:12]}", signer=signer)
    log.initialize()
    try:
        yield log
    finally:
        log.drop()


# --------------------------------------------------------------------------- #
# Gateway composition
# --------------------------------------------------------------------------- #
def principal(principal_id: str = PRINCIPAL) -> AuthenticatedPrincipal:
    """The verified transport principal (TRANSPORT origin, ADD v1.3 :380), as the
    identity provider port of OCOR-DEV-0048 returns it after mTLS/token verification."""
    return AuthenticatedPrincipal(
        principal_id=principal_id, session_id="urn:ocor:session:rem0049",
        actor_chain=("urn:ocor:actor:workstation", principal_id), assurance_level="aal2",
        authenticated_at=NOW - timedelta(minutes=5), expires_at=NOW + timedelta(days=3650),
        status=ControlStatus.available(ControlName.IDENTITY, observed_at=NOW, source_digest=internal("1")))


def governed_context(*, principal_id: str = PRINCIPAL, tenant: str = TENANT, compartment: str = COMPARTMENT,
                     purpose: str = PURPOSE, marking_ref: str = internal("a"), release: str = RELEASE
                     ) -> GovernedContext:
    return GovernedContext.from_mapping({
        "tenant_id": tenant, "organization_id": "urn:ocor:org:synthetic", "domain_id": "urn:ocor:domain:fleet",
        "compartments": [compartment], "classification_marking_ref": marking_ref, "purpose": purpose,
        "effective_principal_id": principal_id, "actor_chain": ["urn:ocor:actor:workstation", principal_id],
        "ontology_release_digest": release, "policy_bundle_digest": POLICY,
        "correlation_id": "018f2f95-01b2-7cc3-8d4e-123456789abc"})


def wire_context(mode: str = "BEST_AVAILABLE", required_commit: str | None = None, *, wait_timeout_ms: int = 0,
                 **changes: Any) -> dict[str, Any]:
    """A contract ``QueryContext`` (Contract :142-184) in wire form: no principal, no actor_chain."""
    gcs = governed_context(**{k: v for k, v in changes.items() if k in {
        "principal_id", "tenant", "compartment", "purpose", "marking_ref", "release"}})
    consistency: dict[str, Any] = {"mode": mode, "wait_timeout_ms": wait_timeout_ms}
    if required_commit is not None:
        consistency["required_commit"] = required_commit
    return {
        "request_id": "018f2f95-01b2-7cc3-8d4e-123456789abc",
        "correlation_id": "018f2f95-01b2-7cc3-8d4e-123456789abc",
        "tenant_id": gcs.tenant_id, "organization_id": gcs.organization_id, "domain_id": gcs.domain_id,
        "compartments": list(gcs.compartments), "purpose": gcs.purpose,
        "classification_marking_ref": gcs.classification_marking_ref,
        "ontology_release_digest": "sha256:" + gcs.ontology_release_digest.removeprefix("urn:sha256:"),
        "policy_bundle_digest": "sha256:" + gcs.policy_bundle_digest.removeprefix("urn:sha256:"),
        "governed_context_digest": "sha256:" + gcs.digest().removeprefix("urn:sha256:"),
        "logic_version": "1.0.0", "branch": "main", "consistency": consistency,
    }


def contract_call(contract_id: str = CONTRACT_ID, digest: str = wire("d"), **parameters: Any) -> dict[str, Any]:
    return {"contract_id": contract_id, "contract_version": "1.0.0", "contract_digest": digest,
            "parameters": dict(parameters)}


PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "properties": {"fleet": {"type": "string", "minLength": 1, "maxLength": 64}},
}


class ContextPolicy:
    """Explicit test port of ``security.ports.PolicyDecisionPort``: permits only the
    tenant, compartment and purpose of the fixture and records every request, so a
    test observes the policy context the gateway forwarded (FR-006, Register :49)."""

    def __init__(self) -> None:
        self.requests: list[PolicyRequest] = []

    def evaluate(self, request: PolicyRequest) -> PolicyDecision:
        self.requests.append(request)
        gcs = request.governed_context
        allowed = (gcs.tenant_id == TENANT and gcs.compartments == (COMPARTMENT,) and gcs.purpose == PURPOSE
                   and request.principal.principal_id == PRINCIPAL)
        return PolicyDecision.from_request(
            request, effect=PolicyEffect.PERMIT if allowed else PolicyEffect.DENY,
            decision_id=f"urn:ocor:decision:{uuid.uuid4()}", valid_until=request.at + timedelta(minutes=5),
            status=ControlStatus.available(ControlName.POLICY, observed_at=request.at, source_digest=POLICY))


class Gateway:
    """The C2 gateway composed with real TypeDB, Fuseki and PostgreSQL audit."""

    def __init__(self, typedb: TypeDBProjectionAdapter, jena: JenaSHACLProjectionAdapter, audit_log: Any,
                 *, clearance_level: str = "SECRET", marking_ref: str = internal("a"),
                 identity_lookups: list[str] | None = None, cost_budget: Any = None,
                 projection: Any = None) -> None:
        gateway = module("c2.gateway")
        identity = importlib.import_module("ocor_runtime.c2_identity")
        registry = identity.IdentityRegistry()
        registry.register(identity.IdentityRecord(canonical_id=PRINCIPAL, aliases=frozenset()))
        lookups = identity_lookups if identity_lookups is not None else []

        class CountingAuthority(gateway.IdentityBackedAuthority):  # type: ignore[misc,name-defined]
            def resolve(self, request: Any) -> str:
                lookups.append(request.governed_context.effective_principal_id)
                result: str = super().resolve(request)
                return result

        self.lookups = lookups
        self.context_policy = ContextPolicy()
        self.engine = MarkingEngine([SCHEME])
        self.catalog = gateway.NamedQueryCatalog(
            ontology_release_digest=RELEASE,
            queries={CONTRACT_ID: gateway.RegisteredNamedQuery(
                contract_id=CONTRACT_ID, versions=frozenset({"1.0.0"}), marking_scheme_id="classification",
                contract_digests={"1.0.0": CONTRACT_DIGEST}, parameters_schema=PARAMETERS_SCHEMA,
                **({} if cost_budget is None else {"cost_budget": cost_budget}))},
            provenance_contract_id=CONTRACT_ID)
        self.policy = gateway.RegistrationAndMarkingPolicy(
            registry=self.catalog.queries, marking_engine=self.engine, marking_port=jena,
            clearance_by_marking_ref={marking_ref: MarkingSet({"classification": clearance_level})})
        self.objects = module("c4.object_projection").TypeDBObjectProjection()
        self.objects.initialize()
        self.objects.reset()
        self.gateway = gateway.NamedQueryGateway(
            catalog=self.catalog, authority=CountingAuthority(registry), context_policy=self.context_policy,
            policy=self.policy, projection=typedb if projection is None else projection, objects=self.objects,
            audit=audit_log,
            commit_ordering=typedb, clock=lambda: NOW)
        self.http = module("c2.transport").NamedQueryHttpAdapter(self.gateway)

    def invoke(self, operation: str, body: Mapping[str, Any], who: str = PRINCIPAL) -> Any:
        return self.http.invoke(operation, body, principal(who))


def bound_query(who: str = PRINCIPAL) -> Any:
    """A generic named query bound to the transport principal (internal digest form)."""
    ports = module("c2.ports")
    gcs = governed_context()
    context = ports.QueryContext(
        request_id="018f2f95-01b2-7cc3-8d4e-123456789abc", correlation_id=gcs.correlation_id,
        tenant_id=gcs.tenant_id, organization_id=gcs.organization_id, domain_id=gcs.domain_id,
        compartments=gcs.compartments, purpose=gcs.purpose, classification_marking_ref=gcs.classification_marking_ref,
        ontology_release_digest=gcs.ontology_release_digest, policy_bundle_digest=gcs.policy_bundle_digest,
        governed_context_digest=gcs.digest(), logic_version="1.0.0", branch="main",
        consistency=ports.ConsistencyRequirement(ports.ConsistencyMode.BEST_AVAILABLE))
    call = ports.ContractCall(contract_id=CONTRACT_ID, contract_version="1.0.0", contract_digest=CONTRACT_DIGEST,
                              parameters={"fleet": "alpha"})
    return ports.TransportBoundQuery(principal=principal(who), query=ports.NamedQueryCall(context=context, call=call))


def get_object_body(context: dict[str, Any] | None = None, *, object_id: str = V1,
                    call: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"context": context or wire_context(),
            "object_ref": {"resource_type_id": "urn:ocor:type:vessel", "resource_id": object_id},
            "view_contract": call or contract_call()}


def load_fleet(fixture: Gateway, typedb: TypeDBProjectionAdapter) -> None:
    """Projected objects at canonical commits commit-1 and commit-2: V1 (SECRET) linked
    to V2 (TOP_SECRET, never published to the marking join, so redacted for a SECRET
    clearance)."""
    typedb.apply_commit(fact_id=V1, commit_id="commit-1", payload="v1")
    typedb.apply_commit(fact_id=V2, commit_id="commit-2", payload="v2")
    for object_id, level, links in ((V1, "SECRET", (V2,)), (V2, "TOP_SECRET", ())):
        fixture.objects.project(
            object_id=object_id, resource_type_id="urn:ocor:type:vessel", commit_id="commit-2",
            marking=MarkingSet({"classification": level}), values={"name": f"{object_id} alpha"},
            link_ids=links, provenance_ids=("source-1",), text=f"{object_id} alpha fleet")


# --------------------------------------------------------------------------- #
# NCR-C2-001 -- branch/commit ordering and bounded wait
# --------------------------------------------------------------------------- #
def test_ncr_c2_001_conforms(typedb: TypeDBProjectionAdapter) -> None:
    """FR-057 (Register :179): a projection beyond Cn serves at-least but not exact(Cn);
    LLD v1.1 :126: AT_LEAST_COMMIT(c,t) waits bounded until watermark >= c, then
    PROJECTION_NOT_READY; ADD v1.3 :1361: AT_LEAST_COMMIT(Cn) may serve Cm>Cn declaring Cm."""
    ports = module("c2.ports")
    planner_module = module("c2.planner")
    typedb.apply_commit(fact_id="f", commit_id="commit-1", payload="p1")
    typedb.apply_commit(fact_id="f", commit_id="commit-2", payload="p2")
    assert typedb.position("main", "commit-1") < typedb.position("main", "commit-2")
    assert typedb.position("main", "commit-9") is None

    class Permit:
        def decide(self, request: Any) -> str:
            return "PERMIT"

    planner = planner_module.ConsistencyPlanner(policy=Permit(), watermark_port=typedb, projection_id="p",
                                                branch="main", commit_ordering=typedb)
    gcs = governed_context()

    def request(mode: Any, commit: str, wait: int = 0) -> Any:
        return ports.NamedQueryRequest(
            request_id="018f2f95-01b2-7cc3-8d4e-123456789abc", contract_id=CONTRACT_ID, contract_version="1.0.0",
            contract_digest=CONTRACT_DIGEST, parameters={}, governed_context=gcs,
            governed_context_digest=gcs.digest(), consistency=ports.ConsistencyRequirement(mode, commit, wait))

    plan = planner.plan(request(ports.ConsistencyMode.AT_LEAST_COMMIT, "commit-1"))
    assert plan.observed_watermark.canonical_commit == "commit-2"  # serves Cm > Cn, declaring Cm
    with pytest.raises(ports.C2Error) as exact:
        planner.plan(request(ports.ConsistencyMode.EXACT_AT_COMMIT, "commit-1"))
    assert exact.value.reason_code == "PROJECTION_NOT_READY"
    assert exact.value.served is not None and exact.value.served.projection_watermark == "commit-2"

    started = time.monotonic()
    with pytest.raises(ports.C2Error) as behind:
        planner.plan(request(ports.ConsistencyMode.AT_LEAST_COMMIT, "commit-3", 400))
    elapsed = time.monotonic() - started
    assert behind.value.reason_code == "PROJECTION_NOT_READY"
    assert 0.4 <= elapsed < 5.0, elapsed  # bounded wait on wait_timeout_ms, not an immediate answer

    timer = threading.Timer(0.3, lambda: typedb.apply_commit(fact_id="f", commit_id="commit-3", payload="p3"))
    timer.start()
    try:
        caught_up = planner.plan(request(ports.ConsistencyMode.AT_LEAST_COMMIT, "commit-3", 5000))
    finally:
        timer.join()
    assert caught_up.observed_watermark.canonical_commit == "commit-3"

    served = ports.ServedContext("main", RELEASE, "commit-3", "commit-3", 0, gcs.digest(), POLICY)
    beyond = ports.ConsistencyRequirement(ports.ConsistencyMode.AT_LEAST_COMMIT, "commit-1")
    assert beyond.verify_served(served, ordering=typedb) == served
    with pytest.raises(ports.C2Error) as not_exact:
        ports.ConsistencyRequirement(ports.ConsistencyMode.EXACT_AT_COMMIT, "commit-1").verify_served(
            served, ordering=typedb)
    assert not_exact.value.reason_code == "PROJECTION_NOT_READY"


# --------------------------------------------------------------------------- #
# NCR-C2-002 -- transport-bound principal and full policy context
# --------------------------------------------------------------------------- #
def test_ncr_c2_002_conforms(typedb: TypeDBProjectionAdapter, jena: JenaSHACLProjectionAdapter,
                             audit_log: Any) -> None:
    """ADD v1.3 :380 (Query: no Principal in the body, TRANSPORT origin, DENY without lookup);
    LLD v1.1 :41 (principal and actor_chain derived from the authenticated identity);
    Contract :142-164 (QueryContext without principal_id/actor_chain); FR-006 (Register :49)."""
    fixture = Gateway(typedb, jena, audit_log)
    load_fleet(fixture, typedb)
    jena.publish(V1, {"label": V1, "classification": "SECRET", "provenanceRef": "urn:ocor:provenance:source-1"})
    for field, value in (("effective_principal_id", PRINCIPAL), ("actor_chain", [PRINCIPAL]),
                         ("principal_id", PRINCIPAL)):
        context = wire_context()
        context[field] = value
        reply = fixture.invoke("GetObject", get_object_body(context))
        assert reply.status == 400 and reply.body["reason_code"] == "SCHEMA_VIOLATION", field
        assert "object" not in reply.body

    reply = fixture.invoke("GetObject", get_object_body())
    assert reply.status == 200, reply.body
    forwarded = fixture.context_policy.requests[-1]
    assert forwarded.principal.principal_id == PRINCIPAL
    assert forwarded.governed_context.effective_principal_id == PRINCIPAL
    assert forwarded.governed_context.actor_chain == ("urn:ocor:actor:workstation", PRINCIPAL)
    assert forwarded.governed_context_digest == governed_context().digest()

    # a body digest computed for another principal never binds the transport principal
    reply = fixture.invoke("GetObject", get_object_body(wire_context(principal_id="urn:ocor:principal:other")))
    assert reply.status == 403 and reply.body["reason_code"] == "POLICY_DENIED"

    # tenant, compartment and purpose reach the decision and change its outcome
    for change in ({"tenant": "urn:ocor:tenant:other"}, {"compartment": "urn:ocor:compartment:z"},
                   {"purpose": "other-purpose"}):
        reply = fixture.invoke("GetObject", get_object_body(wire_context(**change)))
        assert reply.status == 403 and reply.body["reason_code"] == "POLICY_DENIED", change
        assert "object" not in reply.body


# --------------------------------------------------------------------------- #
# NCR-C2-003 -- unresolvable marking reference
# --------------------------------------------------------------------------- #
def test_ncr_c2_003_conforms(typedb: TypeDBProjectionAdapter, jena: JenaSHACLProjectionAdapter,
                             audit_log: Any) -> None:
    """ADD v1.3 :401: an unresolvable *_marking_ref produces DENY, never a permissive posture;
    ADD v1.3 :398 (every *_marking_ref is the digest of a marking object)."""
    gateway = module("c2.gateway")
    ports = module("c2.ports")
    fixture = Gateway(typedb, jena, audit_log, marking_ref=internal("a"))
    gcs = governed_context(marking_ref=internal("e"))
    request = ports.NamedQueryRequest(
        request_id="018f2f95-01b2-7cc3-8d4e-123456789abc", contract_id=CONTRACT_ID, contract_version="1.0.0",
        contract_digest=CONTRACT_DIGEST, parameters={}, governed_context=gcs, governed_context_digest=gcs.digest(),
        consistency=ports.ConsistencyRequirement(ports.ConsistencyMode.BEST_AVAILABLE))
    assert fixture.policy.decide(request) == gateway.DENY  # no resource_id: still resolved, still DENY
    load_fleet(fixture, typedb)
    reply = fixture.invoke("GetObject", get_object_body(wire_context(marking_ref=internal("e"))))
    assert reply.status == 403 and reply.body["reason_code"] == "POLICY_DENIED"
    assert "object" not in reply.body


# --------------------------------------------------------------------------- #
# NCR-C2-004 -- contract digest and active release
# --------------------------------------------------------------------------- #
def test_ncr_c2_004_conforms(typedb: TypeDBProjectionAdapter, jena: JenaSHACLProjectionAdapter,
                             audit_log: Any) -> None:
    """ADD v1.3 :1361: the Gateway rejects non-matching digest or release; Contract :452-466
    (CONTRACT_DIGEST_MISMATCH, RELEASE_MISMATCH); FR-046 (Register :142); FR-055 (Register :177).
    Both are decided before any projection read; RELEASE_MISMATCH carries served (ADD v1.3 :1362)."""
    fixture = Gateway(typedb, jena, audit_log)
    load_fleet(fixture, typedb)
    reads_before = fixture.objects.read_count
    reply = fixture.invoke("GetObject", get_object_body(call=contract_call(digest=wire("e"))))
    assert reply.status == 409 and reply.body["reason_code"] == "CONTRACT_DIGEST_MISMATCH"
    reply = fixture.invoke("GetObject", get_object_body(wire_context(release=internal("f"))))
    assert reply.status == 409 and reply.body["reason_code"] == "RELEASE_MISMATCH"
    assert_contract_valid("Problem", reply.body)
    assert reply.body["served"]["ontology_release"] == wire("b")  # the active release, never the request's
    assert fixture.objects.read_count == reads_before


def test_ncr_c2_004_catalog_is_built_from_an_admitted_c1_release() -> None:
    """The allow-list, contract digests and active release come from an admitted, signed C1
    release (NCP-U01 conforming pipeline): only NAMED_QUERY contracts are registered."""
    gateway = module("c2.gateway")
    with tempfile.TemporaryDirectory() as workdir:
        release = _named_query_release(Path(workdir))
        catalog = gateway.NamedQueryCatalog.from_release(release.package)
        assert set(catalog.queries) == {CONTRACT_ID}
        entry = catalog.queries[CONTRACT_ID]
        assert entry.contract_digests == {"1.0.0": release.contract_digest(CONTRACT_ID)}
        assert entry.parameters_schema == release.contracts[CONTRACT_ID]["input_schema"]
        assert catalog.ontology_release_digest == release.package.signed.release.ir_digest
        assert release.contracts["urn:ocor:contract:score"]["kind"] == "FUNCTION"  # never allow-listed


# --------------------------------------------------------------------------- #
# NCR-C2-005 -- denial audit through the single audit port
# --------------------------------------------------------------------------- #
def test_ncr_c2_005_conforms(typedb: TypeDBProjectionAdapter, jena: JenaSHACLProjectionAdapter,
                             audit_log: Any, audit_keys: AuditKeys) -> None:
    """FR-056 (Register :178): non allow-listed queries are denied and audited; NFR-034
    (Register :257); FR-134 (Register :302: actor, time, resource, reason, authority,
    correlation); ADD v1.3 :3143: append-only, hash-linked, signed audit records;
    ADD v1.3 :393: the GovernedContext is present in the Audit Record."""
    audit = module("audit")
    fixture = Gateway(typedb, jena, audit_log)
    load_fleet(fixture, typedb)
    denied = (
        get_object_body(call=contract_call(contract_id="urn:ocor:contract:named-query:not-registered")),
        get_object_body(wire_context(purpose="other-purpose")),
        get_object_body(call=contract_call(cypher="MATCH (n) RETURN n")),
    )
    for body in denied:
        assert fixture.invoke("GetObject", body).status in {400, 403, 404}
    records = audit_log.records()
    assert len(records) == len(denied)
    previous = audit.GENESIS_HASH
    for record in records:
        body = record.record
        for field in ("actor", "occurred_at", "resource", "reason_code", "authority_ref", "correlation_id",
                      "outcome", "event_type"):
            assert body[field], field
        assert body["event_type"] == "C2_QUERY_DENIED"
        assert record.previous_hash == previous
        assert record.record_hash == canonical_digest({"previous_hash": previous, "record": body})
        assert audit_keys.openssl_verify(audit.signing_payload(record), base64.b64decode(record.signature))
        previous = record.record_hash
    assert records[0].record["reason_code"] == "CONTRACT_NOT_FOUND"
    assert records[1].record["governed_context_digest"] == governed_context(purpose="other-purpose").digest()
    assert records[1].record["governed_context"]["effective_principal_id"] == PRINCIPAL
    assert audit.verify_audit_chain(records, {"urn:ocor:key:c2-audit-test": audit_keys_public(audit_keys)}) == 3
    psycopg = importlib.import_module("psycopg")
    for statement in (f"UPDATE {audit_log.schema}.audit_record SET signature = 'x'",
                      f"DELETE FROM {audit_log.schema}.audit_record", f"TRUNCATE {audit_log.schema}.audit_record"):
        with psycopg.connect(_dsn(), autocommit=True) as connection:
            with pytest.raises(psycopg.Error, match="append-only"):
                connection.execute(statement)
    assert len(audit_log.records()) == 3


def audit_keys_public(keys: AuditKeys) -> bytes:
    der = subprocess.run(["openssl", "pkey", "-pubin", "-in", str(keys.public_pem), "-outform", "DER"],
                         check=True, capture_output=True).stdout
    return der[-32:]


def test_ncr_c2_005_audit_unavailable_fails_closed(typedb: TypeDBProjectionAdapter,
                                                   jena: JenaSHACLProjectionAdapter, audit_keys: AuditKeys) -> None:
    """A denial that cannot be durably audited is never answered as a plain denial without
    record: the gateway answers CONTROL_PLANE_UNAVAILABLE (ADD v1.3 :174, :3143)."""
    audit = module("audit")
    signing = module("c1.signing")
    unreachable = audit.PostgresAuditLog(
        "postgresql://ocor:x@127.0.0.1:1/ocor", schema="ocor_audit_unreachable",
        signer=audit.AuditSigner(key=signing.Ed25519SigningKey.from_seed(audit_keys.seed), keyid="urn:ocor:key:x"))
    fixture = Gateway(typedb, jena, unreachable)
    reply = fixture.invoke("GetObject", get_object_body(
        call=contract_call(contract_id="urn:ocor:contract:named-query:not-registered")))
    assert reply.status == 503 and reply.body["reason_code"] == "CONTROL_PLANE_UNAVAILABLE"


# --------------------------------------------------------------------------- #
# NCR-C2-006 -- closed Problem model
# --------------------------------------------------------------------------- #
def _c2error_codes() -> set[str]:
    files = [*sorted((SOURCE_ROOT / "c2").glob("*.py")), SOURCE_ROOT / "c4/typedb_adapter.py",
             SOURCE_ROOT / "c4/rebuild.py", SOURCE_ROOT / "c4/object_projection.py"]
    codes: set[str] = set()
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "C2Error" and node.args:
                first = node.args[0]
                branches = [first.body, first.orelse] if isinstance(first, ast.IfExp) else [first]
                for branch in branches:
                    assert isinstance(branch, ast.Constant), f"{path}:{node.lineno} non-constant reason code"
                    codes.add(str(branch.value))
    return codes


def test_ncr_c2_006_conforms(typedb: TypeDBProjectionAdapter, jena: JenaSHACLProjectionAdapter,
                             audit_log: Any) -> None:
    """Contract :435-485 (closed Problem: reason_code enum, served for STALE_CONTEXT,
    PROJECTION_NOT_READY and RELEASE_MISMATCH, deferred_element for CAPABILITY_DEFERRED);
    ADD v1.3 :1362; ADD v1.3 :380 (DENY without lookup); NFR-024 (Register :180)."""
    ports = module("c2.ports")
    problem = module("c2.problem")
    enum = problem_enum()
    assert tuple(problem.PROBLEM_REASON_CODES) == enum
    assert _c2error_codes() <= set(enum), sorted(_c2error_codes() - set(enum))
    with pytest.raises(ValueError):
        ports.C2Error("PROJECTION_NOT_READY", "served is mandatory")
    with pytest.raises(ValueError):
        ports.C2Error("CAPABILITY_DEFERRED", "deferred_element is mandatory")
    gcs = governed_context()
    served = ports.ServedContext("main", RELEASE, "commit-1", "commit-1", 0, gcs.digest(), POLICY)
    for code in enum:
        extra: dict[str, Any] = {}
        if code in {"STALE_CONTEXT", "PROJECTION_NOT_READY", "RELEASE_MISMATCH"}:
            extra["served"] = served
        if code == "CAPABILITY_DEFERRED":
            extra["deferred_element"] = "ELM-011"
        document = problem.problem_document(ports.C2Error(code, "detail", **extra),
                                            correlation_id="018f2f95-01b2-7cc3-8d4e-123456789abc",
                                            result_marking_ref=internal("a"))
        assert_contract_valid("Problem", document)
        assert document["reason_code"] == code

    lookups: list[str] = []
    fixture = Gateway(typedb, jena, audit_log, identity_lookups=lookups)
    load_fleet(fixture, typedb)
    reply = fixture.invoke("GetObject", get_object_body(
        call=contract_call(contract_id="urn:ocor:contract:named-query:not-registered")))
    assert (reply.status, reply.body["reason_code"]) == (404, "CONTRACT_NOT_FOUND")
    assert reply.media_type == "application/problem+json"
    assert_contract_valid("Problem", reply.body)
    assert lookups == []  # DENY without identity lookup
    unknown = "urn:ocor:principal:never-registered"  # its own correct GCS digest, unknown identity
    reply = fixture.invoke("GetObject", get_object_body(wire_context(principal_id=unknown)), who=unknown)
    assert (reply.status, reply.body["reason_code"]) == (404, "CONTRACT_NOT_FOUND")

    # a code outside the closed enum raised behind a port never reaches the caller
    class LegacyCodeProjection:
        def read(self, request: Any) -> Any:
            raise ports.C2Error("RESULT_NOT_FOUND", "sealed spike adapter code")

    legacy = Gateway(typedb, jena, audit_log, projection=LegacyCodeProjection())
    with pytest.raises(ports.C2Error) as caught:
        legacy.gateway.execute(bound_query())
    assert caught.value.reason_code == "POLICY_DENIED"


def test_ncr_c2_006_backend_failure_is_a_typed_problem(typedb: TypeDBProjectionAdapter, audit_log: Any) -> None:
    """A marking backend failure is a typed fail-closed Problem (Contract :486-491;
    LLD v1.1 :346), CONTROL_PLANE_UNAVAILABLE (ADD v1.3 :174, :3141), never a raw OSError
    and never PERMIT."""
    class Unreachable(JenaSHACLProjectionAdapter):
        def exists_authorized(self, resource_id: str, clearance: MarkingSet) -> bool:
            raise ConnectionRefusedError("marking backend unreachable")

    fixture = Gateway(typedb, Unreachable(MarkingEngine([SCHEME])), audit_log)
    load_fleet(fixture, typedb)
    reply = fixture.invoke("GetObject", get_object_body())
    assert (reply.status, reply.body["reason_code"]) == (503, "CONTROL_PLANE_UNAVAILABLE")
    assert "object" not in reply.body


# --------------------------------------------------------------------------- #
# NCR-C2-007 -- closed request, closed parameters, cost budget, served disclosure
# --------------------------------------------------------------------------- #
def test_ncr_c2_007_conforms(typedb: TypeDBProjectionAdapter, jena: JenaSHACLProjectionAdapter,
                             audit_log: Any) -> None:
    """Contract :142-195 (QueryContext with branch, logic_version, scenario_id; parameters are the
    closed generated schema selected by contract_id and digest); Contract :254-273 (ServedContext
    with result_marking_ref, provenance_ref, redaction_count); LLD v1.1 :117-124 (allow-list of
    name/version/parameters, cost budget, marking join and post-filter); FR-007 (Register :58)."""
    ports = module("c2.ports")
    assert {"branch", "logic_version", "scenario_id"} <= {f.name for f in dataclasses.fields(ports.QueryContext)}
    fixture = Gateway(typedb, jena, audit_log)
    load_fleet(fixture, typedb)
    jena.publish(V1, {"label": V1, "classification": "SECRET", "provenanceRef": "urn:ocor:provenance:source-1"})
    for parameters in ({"cypher": "MATCH (n) RETURN n"}, {"fleet": 7}, {"fleet": "x" * 65}):
        reply = fixture.invoke("GetObject", get_object_body(call=contract_call(**parameters)))
        assert (reply.status, reply.body["reason_code"]) == (400, "SCHEMA_VIOLATION"), parameters
    body = {"context": wire_context(), "start": [{"resource_type_id": "urn:ocor:type:vessel",
                                                  "resource_id": f"vessel-{n}"} for n in range(1, 102)],
            "traversal_contract": contract_call()}
    reply = fixture.invoke("Traverse", body)
    assert (reply.status, reply.body["reason_code"]) == (400, "SCHEMA_VIOLATION")  # maxItems 100

    reply = fixture.invoke("Traverse", {"context": wire_context(), "start": [
        {"resource_type_id": "urn:ocor:type:vessel", "resource_id": V1}],
        "traversal_contract": contract_call()})
    assert reply.status == 200, reply.body
    assert_contract_valid("GraphResponse", reply.body)
    served = reply.body["served"]
    assert served["redaction_count"] == 1  # vessel-2 is TOP_SECRET for a SECRET clearance
    assert {node["node_ref"]["resource_id"] for node in reply.body["nodes"]} == {V1}
    assert re.fullmatch(r"urn:sha256:[0-9a-f]{64}", served["result_marking_ref"])
    assert re.fullmatch(r"urn:sha256:[0-9a-f]{64}", served["provenance_ref"])
    assert served["branch"] == "main" and served["served_commit"] == "commit-2"


def test_ncr_c2_007_cost_budget_is_enforced_before_the_read(typedb: TypeDBProjectionAdapter,
                                                            jena: JenaSHACLProjectionAdapter, audit_log: Any
                                                            ) -> None:
    """LLD v1.1 :120 (stima cost budget at step 2, before the query)."""
    gateway = module("c2.gateway")
    fixture = Gateway(typedb, jena, audit_log, cost_budget=gateway.CostBudget(max_items=5))
    load_fleet(fixture, typedb)
    reads = fixture.objects.read_count
    reply = fixture.invoke("QueryObjectSet", {"context": wire_context(), "object_set_contract": contract_call(),
                                              "page_size": 6})
    assert (reply.status, reply.body["reason_code"]) == (403, "POLICY_DENIED")
    assert fixture.objects.read_count == reads


# --------------------------------------------------------------------------- #
# NCR-C2-008 -- wire digest form (PO option 2)
# --------------------------------------------------------------------------- #
def test_ncr_c2_008_conforms(typedb: TypeDBProjectionAdapter, jena: JenaSHACLProjectionAdapter,
                             audit_log: Any) -> None:
    """NORMATIVE-CONFORMANCE-PLAN point 4, NCR-C2-008 option 2: the five digests stay in the
    contract form sha256:<hex> on the wire (Contract :118, :170-192), are converted bijectively
    to the internal urn:sha256:<hex> form (LLD v1.1 :37; governed-context.schema.json :43-48),
    governed_context_digest is computed on the internal form, and a malformed digest is
    rejected with SCHEMA_VIOLATION. NFR-022."""
    transport = module("c2.transport")
    for hex_char in "0af":
        assert transport.to_internal_digest(wire(hex_char)) == internal(hex_char)
        assert transport.to_wire_digest(internal(hex_char)) == wire(hex_char)
        assert transport.to_wire_digest(transport.to_internal_digest(wire(hex_char))) == wire(hex_char)
    ports = module("c2.ports")
    for malformed in (internal("a"), "sha256:" + "A" * 64, "sha256:" + "a" * 63, "", "md5:" + "a" * 32):
        with pytest.raises(ports.C2Error) as caught:
            transport.to_internal_digest(malformed)
        assert caught.value.reason_code == "SCHEMA_VIOLATION"
    fixture = Gateway(typedb, jena, audit_log)
    load_fleet(fixture, typedb)
    jena.publish(V1, {"label": V1, "classification": "SECRET", "provenanceRef": "urn:ocor:provenance:source-1"})
    reply = fixture.invoke("GetObject", get_object_body())
    assert reply.status == 200, reply.body
    assert_contract_valid("GetObjectResponse", reply.body)
    assert reply.body["served"]["ontology_release"] == wire("b")
    assert reply.body["object"]["object_schema"]["digest"].startswith("sha256:")
    for field in ("ontology_release_digest", "policy_bundle_digest", "governed_context_digest"):
        context = wire_context()
        context[field] = "urn:sha256:" + context[field].removeprefix("sha256:")
        reply = fixture.invoke("GetObject", get_object_body(context))
        assert (reply.status, reply.body["reason_code"]) == (400, "SCHEMA_VIOLATION"), field
    reply = fixture.invoke("GetObject", get_object_body(call=contract_call(digest=internal("d"))))
    assert (reply.status, reply.body["reason_code"]) == (400, "SCHEMA_VIOLATION")


# --------------------------------------------------------------------------- #
# NCR-C2-009 -- BEST_AVAILABLE with required_commit
# --------------------------------------------------------------------------- #
def test_ncr_c2_009_conforms() -> None:
    """Contract :126-141: required_commit is required only for the strong modes and is
    allowed otherwise; an invalid consistency object is a SCHEMA_VIOLATION (Contract :459)."""
    ports = module("c2.ports")
    value = {"mode": "BEST_AVAILABLE", "required_commit": "commit-1"}
    assert_contract_valid("Consistency", value)
    requirement = ports.ConsistencyRequirement.from_mapping(value)
    assert requirement.mode is ports.ConsistencyMode.BEST_AVAILABLE
    assert requirement.to_mapping()["required_commit"] == "commit-1"
    for invalid in ({"mode": "AT_LEAST_COMMIT"}, {"mode": "BEST_AVAILABLE", "wait_timeout_ms": 30001},
                    {"mode": "SOMETIMES"}, {"mode": "BEST_AVAILABLE", "extra": 1}):
        with pytest.raises(ports.C2Error) as caught:
            ports.ConsistencyRequirement.from_mapping(invalid)
        assert caught.value.reason_code == "SCHEMA_VIOLATION", invalid


# --------------------------------------------------------------------------- #
# NCR-C2-011 -- the six operations
# --------------------------------------------------------------------------- #
def test_ncr_c2_011_conforms(typedb: TypeDBProjectionAdapter, jena: JenaSHACLProjectionAdapter,
                             audit_log: Any) -> None:
    """Contract :8-98 (GetObject, QueryObjectSet, Search, Traverse, Explain, GetProvenance);
    ADD v1.3 :283; FR-055 (Register :177: every contract invocable without backend language);
    FR-007 (Register :58); LLD v1.1 :113 (EvidenceReadPort among the C2 ports)."""
    fixture = Gateway(typedb, jena, audit_log)
    load_fleet(fixture, typedb)
    jena.publish(V1, {"label": V1, "classification": "SECRET", "provenanceRef": "urn:ocor:provenance:source-1"})
    ref = {"resource_type_id": "urn:ocor:type:vessel", "resource_id": V1}
    bodies = {
        "GetObject": (get_object_body(), "GetObjectResponse"),
        "QueryObjectSet": ({"context": wire_context(), "object_set_contract": contract_call(), "page_size": 10},
                           "ObjectPageResponse"),
        "Search": ({"context": wire_context(), "search_contract": contract_call(), "text": "alpha",
                    "page_size": 10}, "SearchResponse"),
        "Traverse": ({"context": wire_context(), "start": [ref], "traversal_contract": contract_call()},
                     "GraphResponse"),
        "Explain": ({"context": wire_context(), "target": ref, "explanation_contract": contract_call()},
                    "GraphResponse"),
        "GetProvenance": ({"context": wire_context(), "target": ref, "direction": "UPSTREAM", "max_depth": 3},
                          "GraphResponse"),
    }
    assert set(bodies) == set(OPERATIONS)
    for operation, (body, response_schema) in bodies.items():
        assert_contract_valid(operation_request_schema(operation), body)
        reply = fixture.invoke(operation, body)
        assert reply.status == 200, (operation, reply.body)
        assert reply.media_type == "application/json"
        assert_contract_valid(response_schema, reply.body)
        assert reply.body["served"]["served_commit"] == "commit-2", operation
    page = fixture.invoke("QueryObjectSet", bodies["QueryObjectSet"][0]).body
    assert [item["object_ref"]["resource_id"] for item in page["items"]] == [V1]
    assert page["served"]["redaction_count"] == 1
    hits = fixture.invoke("Search", bodies["Search"][0]).body["hits"]
    assert [hit["score_semantics"] for hit in hits] == ["LEXICAL_RELEVANCE"]
    # NFR-006 (Register :50): a link to a withheld object is neither shown nor hinted at
    snapshot = fixture.invoke("GetObject", bodies["GetObject"][0]).body
    assert snapshot["object"]["link_refs"] == []
    assert snapshot["served"]["redaction_count"] == 1
    provenance = fixture.invoke("GetProvenance", bodies["GetProvenance"][0]).body
    evidence_nodes = [node for node in provenance["nodes"] if node["node_kind"] == "urn:ocor:type:evidence"]
    assert len(evidence_nodes) == 1 and provenance["edges"][0]["edge_type_id"] == "urn:ocor:edge:derived-from"
    without = fixture.invoke("GetProvenance", dict(bodies["GetProvenance"][0], include_evidence=False)).body
    assert [node["node_ref"]["resource_id"] for node in without["nodes"]] == [V1]
    # EvidenceReadPort (LLD v1.1 :113): evidence resolves only through an authorised object
    gateway = module("c2.gateway")
    ports = module("c2.ports")
    gcs = governed_context()
    request = ports.NamedQueryRequest(
        request_id="018f2f95-01b2-7cc3-8d4e-123456789abc", contract_id=CONTRACT_ID, contract_version="1.0.0",
        contract_digest=CONTRACT_DIGEST, parameters={}, governed_context=gcs, governed_context_digest=gcs.digest(),
        consistency=ports.ConsistencyRequirement(ports.ConsistencyMode.BEST_AVAILABLE))
    assert isinstance(fixture.gateway, ports.EvidenceReadPort)
    resolved = fixture.gateway.get(gateway.evidence_ref(V1, "source-1"), request)
    assert resolved["object_ref"] == V1 and resolved["evidence_ref"] == evidence_nodes[0]["node_ref"]["resource_id"]
    with pytest.raises(ports.C2Error) as hidden:
        fixture.gateway.get(gateway.evidence_ref(V2, "source-1"), request)
    assert hidden.value.reason_code == "POLICY_DENIED"
    unknown = fixture.invoke("Unknown", bodies["GetObject"][0])
    assert (unknown.status, unknown.body["reason_code"]) == (404, "CONTRACT_NOT_FOUND")


def operation_request_schema(operation: str) -> str:
    path = next(p for p in contract()["paths"].values() if p["post"]["operationId"] == operation)
    ref: str = path["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    return ref.rsplit("/", 1)[-1]


# --------------------------------------------------------------------------- #
# NCR-C2-012 -- exact-at-commit never downgrades
# --------------------------------------------------------------------------- #
def test_ncr_c2_012_conforms(typedb: TypeDBProjectionAdapter) -> None:
    """LLD v1.1 :369 (BA-03: exact-at-commit or PROJECTION_NOT_READY, never downgrade);
    ADD v1.3 :1363; Contract :452-466, :472-479 (served is mandatory); FR-057 (Register :179)."""
    ports = module("c2.ports")
    gcs = governed_context()
    typedb.apply_commit(fact_id="fact-1", commit_id="commit-1", payload="V1")
    request = ports.NamedQueryRequest(
        request_id="018f2f95-01b2-7cc3-8d4e-123456789abc", contract_id=CONTRACT_ID, contract_version="1.0.0",
        contract_digest=CONTRACT_DIGEST, parameters={"fact_id": "fact-1"}, governed_context=gcs,
        governed_context_digest=gcs.digest(),
        consistency=ports.ConsistencyRequirement(ports.ConsistencyMode.EXACT_AT_COMMIT, "commit-2"))
    with pytest.raises(ports.C2Error) as caught:
        typedb.read(request)
    assert caught.value.reason_code == "PROJECTION_NOT_READY"
    assert caught.value.served is not None
    assert caught.value.served.projection_watermark == "commit-1"
    problem = module("c2.problem").problem_document(caught.value, correlation_id=gcs.correlation_id,
                                                     result_marking_ref=internal("a"))
    assert_contract_valid("Problem", problem)
    assert problem["served"]["watermark"] == "commit-1"


# --------------------------------------------------------------------------- #
# Composition helper: an admitted C1 release with one NAMED_QUERY contract
# --------------------------------------------------------------------------- #
LOCK = "urn:sha256:" + "a" * 64
ROLES = ("jena", "terminusdb", "typedb")


class _NamedQueryRelease:
    """A release of the NCP-U01 conforming pipeline (OaC -> ocor.cir/1.0 -> DSSE -> admission ->
    immutable publisher), with one NAMED_QUERY contract and one FUNCTION contract."""

    def __init__(self, workdir: Path) -> None:
        c1_ports = module("c1.ports")
        ir = module("c1.ir")
        codegen = module("c1.codegen")
        publisher = module("c1.publisher")
        signing = module("c1.signing")
        key = signing.Ed25519SigningKey.from_seed(os.urandom(32))
        keyid = "urn:ocor:key:c2-release-test"
        chain = canonical_digest({"chain": "c2-release-test"})
        contracts = [
            {"construct": "ContractDefinition", "contract_id": CONTRACT_ID, "kind": "NAMED_QUERY",
             "input_schema": PARAMETERS_SCHEMA, "output_schema": {"type": "object"},
             "error_model": ["SCHEMA_VIOLATION"], "effect_class": "READ_ONLY", "risk_class": "R0",
             "policy_refs": ["urn:ocor:policy:fleet-queries"], "approval_refs": [], "version": "1.0.0"},
            {"construct": "ContractDefinition", "contract_id": "urn:ocor:contract:score", "kind": "FUNCTION",
             "input_schema": {"type": "object"}, "output_schema": {"type": "object"},
             "error_model": ["SCHEMA_VIOLATION"], "effect_class": "PURE", "risk_class": "R0",
             "policy_refs": ["urn:ocor:policy:fleet-queries"], "approval_refs": [], "version": "1.0.0"},
        ]
        marking = {"construct": "MarkingSchemeDefinition", "scheme_id": "urn:ocor:marking-scheme:fleet",
                   "version": "1.0.0", "levels": ["UNCLASSIFIED", "RESTRICTED"], "top": "RESTRICTED",
                   "bottom": "UNCLASSIFIED",
                   "dominance_relation": [["UNCLASSIFIED", "UNCLASSIFIED"], ["UNCLASSIFIED", "RESTRICTED"],
                                          ["RESTRICTED", "RESTRICTED"]],
                   "family_definitions": [
                       {"family": family, "vocabulary": ["A", "B"], "kind": kind, "join_operator": join,
                        "meet_operator": meet, "neutral_element": []}
                       for family, kind, join, meet in (
                           ("mandatory_markings", "RESTRICTION", "UNION", "INTERSECTION"),
                           ("caveats", "RESTRICTION", "UNION", "INTERSECTION"),
                           ("dissemination_controls", "RESTRICTION", "UNION", "INTERSECTION"),
                           ("permitted_purposes", "PERMISSION", "INTERSECTION", "UNION"),
                           ("handling_instructions", "RESTRICTION", "UNION", "INTERSECTION"))],
                   "unknown_value_behavior": "DENY", "incomparable_behavior": "DENY",
                   "declassification_authority_ref": "urn:ocor:authority:declassification"}
        definitions = [
            {"construct": "TypeDefinition", "type_id": "urn:ocor:type:vessel", "kind": "OBJECT", "version": "1.0.0",
             "properties": [{"property_id": "urn:ocor:property:vessel-name", "value_type_ref": "string",
                             "cardinality": "ONE", "nullable": False, "constraint_refs": []}],
             "keys": ["urn:ocor:property:vessel-name"], "interfaces": [],
             "security_profile_ref": "urn:ocor:security-profile:restricted"},
            *contracts, marking,
            {"construct": "SecurityProfileDefinition", "security_profile_id": "urn:ocor:security-profile:restricted",
             "marking_scheme_ref": "urn:ocor:marking-scheme:fleet", "default_marking": "RESTRICTED"},
            *({"construct": "CapabilityDisposition", "semantic_capability_id": "value-family:primitive",
               "adapter_role": role, "disposition": "exact", "limitation": None,
               "evidence_ref": "urn:ocor:evidence:fixture"} for role in ROLES),
        ]
        documents = {
            "package.yaml": {"construct": "OntologyPackage", "package_id": "urn:ocor:package:fleet",
                             "version": "1.0.0", "namespace_refs": ["urn:ocor:namespace:fleet"],
                             "module_refs": ["urn:ocor:module:fleet-core"],
                             "dependency_lock": [{"resource_id": "urn:ocor:module:shared-units",
                                                  "version": "1.0.0", "sha256": LOCK}],
                             "owner": "urn:ocor:owner:fleet-team", "classification_marking": "RESTRICTED",
                             "release_profile": "poc", "adapter_roles": list(ROLES),
                             "artifact_targets": ["json-schema", "openapi", "protobuf"]},
            "namespace.yaml": {"construct": "Namespace", "namespace_id": "urn:ocor:namespace:fleet",
                               "uri": "https://ocor.example/ns/fleet#", "prefix": "fleet",
                               "ownership_boundary": "urn:ocor:owner:fleet-team", "default_marking": "RESTRICTED"},
            "module.yaml": {"construct": "Module", "module_id": "urn:ocor:module:fleet-core", "version": "1.0.0",
                            "namespace_ref": "urn:ocor:namespace:fleet", "imports": ["urn:ocor:module:shared-units"],
                            "exports": ["urn:ocor:type:vessel"], "definitions": definitions,
                            "owner": "urn:ocor:owner:fleet-team", "steward": "urn:ocor:owner:fleet-steward",
                            "reviewer": "urn:ocor:owner:fleet-reviewer", "status": "APPROVED",
                            "review_date": "2026-11-02"},
        }
        ids = {"package.yaml": "urn:ocor:package:fleet", "namespace.yaml": "urn:ocor:namespace:fleet",
               "module.yaml": "urn:ocor:module:fleet-core"}
        lock = (c1_ports.DependencyLockEntry("urn:ocor:module:shared-units", "1.0.0", LOCK),)
        request = c1_ports.CompilerRequest(
            package_id="urn:ocor:package:fleet", semantic_version="1.0.0",
            source_commit="0123456789abcdef0123456789abcdef01234567", compiler_version="1.0.0",
            mapping_version="1", release_profile="poc", dependency_lock=lock,
            sources=tuple(c1_ports.SourceUnit.create(
                resource_id=ids[path], version="1.0.0", syntax=c1_ports.SourceSyntax.YAML,
                content=yaml.safe_dump(document, sort_keys=True).encode("utf-8"), source_path=path,
                imports=("urn:ocor:module:shared-units",) if path == "module.yaml" else ())
                for path, document in documents.items()))
        release = ir.OacCompiler().build(request)
        generator = codegen.IrArtifactGenerator()
        files = generator.render(release)
        release = release.with_artifacts(generator.generate(release))
        signer = signing.DsseIrSigner(key=key, keyid=keyid, certificate_chain_ref=chain)
        package = signing.ReleasePackage.create(signed=signer.sign_release(release), dependency_lock=lock,
                                                artifacts=files)
        trust = signing.TrustRoot(keys={keyid: signing.TrustedKey(
            public_key=key.public_key, certificate_chain_ref=chain, signing_profile=signing.ED25519_PROFILE)},
            revoked_keyids=frozenset())
        admission = signing.ReleaseAdmission(trust_root=trust, accepted_compiler_versions=("1.0.0",))
        store = publisher.ImmutableReleasePublisher(admission=admission,
                                                    store=publisher.FileSystemReleaseStore(workdir / "releases"))
        self.package = store.read(store.publish(package))
        self.contracts = {c["contract_id"]: _thaw(c) for c in self.package.signed.release.core["named_contracts"]}

    def contract_digest(self, contract_id: str) -> str:
        return canonical_digest(self.contracts[contract_id])


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _thaw(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_thaw(v) for v in value]
    return value


def _named_query_release(workdir: Path) -> _NamedQueryRelease:
    return _NamedQueryRelease(workdir)
