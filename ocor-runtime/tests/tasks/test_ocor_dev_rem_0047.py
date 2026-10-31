"""OCOR-DEV-REM-0047: NCP-U01, conformance of C1 (Ontology Compiler & IR Pipeline).

Unit NCP-U01 of the plan approved by NORMATIVE-CONFORMANCE-PLAN (2026-10-30). It
resolves the register entries NCR-C1-002, NCR-C1-003, NCR-C1-004, NCR-C1-005,
NCR-C1-006, NCR-C1-008, NCR-C1-009 and NCR-C1-010. Every case asserts the
behaviour prescribed by the normative element it cites (file and line):

- ADD v1.3 (ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md)
  :282 C1 operations ValidatePackage, Compile, SemanticDiff, PackageRelease,
  VerifyRelease; :415 YAML validated by a meta-schema; :417-431 OaC constructs;
  :433-440 deterministic normalisation (NFC, RFC 3339 UTC, canonical decimals,
  ordering, capability classification, fail-closed rejection); :441-462
  CanonicalIRCore; :464 ir_digest and Protobuf equivalence; :466-521 the
  signed-canonical-ir:1.0 DSSE envelope; :523 admission verifies trust root,
  revocation, DSSE PAE, digest, lock, compiler and artifact manifest.
- LLD v1.1 (docs/OCOR_LLD_v1.1.md) :39 set-like arrays sorted and duplicate-free
  before the digest; :103-107 C1 classes/ports, pipeline ending in signature and
  immutable release, generators and drift check; :16-18 precedence (IRB over ADD
  over LLD).
- Requirement Register v1.1 (ocor-runtime/docs/governance_dossier/registers/
  OCOR_Requirement_Register_v1.1_APPROVED.md): FR-024 (:114), FR-026 (:116),
  FR-027 (:117), FR-040 (:136), FR-041 (:137), FR-042 (:138), FR-043 (:139),
  FR-044 (:140), FR-045 (:141), FR-046 (:142), NFR-018, NFR-020 (:151),
  NFR-021 (:152), NFR-051 (:326).

Required backend: none (pure C1 compiler). Signing uses a key generated locally for
the test run; the Ed25519 signatures are checked against OpenSSL as an independent
oracle, the generated OpenAPI against openapi-spec-validator, the generated Protobuf
against grpc_tools.protoc and the IR Protobuf encoding against google.protobuf.
Implementer: Claude Code (Anthropic), reserve implementer of the OCOR loop.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib
import json
import re
import subprocess
import tempfile
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import jsonschema
import pytest
import yaml

from ocor_runtime.c1.ports import (
    C1Error,
    CompilerRequest,
    DependencyLockEntry,
    DiagnosticCode,
    SourceSyntax,
    SourceUnit,
)
from ocor_runtime.kernel.canonical import canonical_bytes, canonical_digest

ROOT = Path(__file__).resolve().parents[3]
ADD = ROOT / "ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
NOW = datetime(2026, 10, 31, 9, 0, 0, tzinfo=UTC)
ADAPTER_ROLES = ("jena", "terminusdb", "typedb")
TARGETS = ("asyncapi", "json-schema", "mcp-descriptor", "openapi", "protobuf", "sdk-python", "sdk-typescript")
CORE_KEYS = {
    "format",
    "release",
    "namespaces",
    "modules",
    "symbol_table",
    "types",
    "links",
    "constraints",
    "temporal_semantics",
    "derived_definitions",
    "named_contracts",
    "causal_manifests",
    "security_profiles",
    "capability_matrix",
    "artifact_plan",
}
RELEASE_KEYS = {"package_id", "semantic_version", "source_commit", "compiler_version", "lock_digest", "mapping_version"}
LOCK_DIGEST_A = "urn:sha256:" + "a" * 64
LOCK_DIGEST_B = "urn:sha256:" + "b" * 64
VALUE_FAMILIES = (
    "primitive",
    "container",
    "structured",
    "geospatial",
    "media",
    "timeseries",
    "quantity",
    "sensitive_reference",
    "enum",
    "object_reference",
)


def c1(name: str) -> ModuleType:
    """Import a conforming C1 module; a missing module is the divergence itself."""
    return importlib.import_module(f"ocor_runtime.c1.{name}")


# --------------------------------------------------------------------------- #
# A conforming OaC package (ADD v1.3 :417-431): package, namespace and module.
# --------------------------------------------------------------------------- #


def _properties() -> list[dict[str, Any]]:
    """One property per value-type family of FR-024 (Register v1.1 :114)."""
    return [
        {"property_id": "urn:ocor:property:vessel-name", "value_type_ref": "string", "cardinality": "ONE",
         "nullable": False, "constraint_refs": []},
        {"property_id": "urn:ocor:property:vessel-commissioned", "value_type_ref": "datetime", "cardinality": "ONE",
         "nullable": True, "default": "2026-10-31T10:00:00+02:00", "constraint_refs": []},
        {"property_id": "urn:ocor:property:vessel-draught", "value_type_ref": "decimal", "cardinality": "ONE",
         "nullable": True, "default": "1.50", "constraint_refs": []},
        {"property_id": "urn:ocor:property:vessel-crew", "value_type_ref": "list<string>", "cardinality": "ONE",
         "nullable": True, "constraint_refs": []},
        {"property_id": "urn:ocor:property:vessel-hull", "value_type_ref": "struct:urn:ocor:type:hull",
         "cardinality": "ONE", "nullable": True, "constraint_refs": []},
        {"property_id": "urn:ocor:property:vessel-position", "value_type_ref": "geo:point", "cardinality": "ONE",
         "nullable": True, "constraint_refs": []},
        {"property_id": "urn:ocor:property:vessel-photo", "value_type_ref": "media:image", "cardinality": "ONE",
         "nullable": True, "constraint_refs": []},
        {"property_id": "urn:ocor:property:vessel-speed-series", "value_type_ref": "timeseries<decimal>",
         "cardinality": "ONE", "nullable": True, "constraint_refs": []},
        {"property_id": "urn:ocor:property:vessel-tonnage", "value_type_ref": "quantity:tonne",
         "unit_ref": "urn:ocor:unit:tonne", "cardinality": "ONE", "nullable": True, "constraint_refs": []},
        {"property_id": "urn:ocor:property:vessel-owner-record", "value_type_ref":
         "sensitive_ref:urn:ocor:security-profile:restricted", "cardinality": "ONE", "nullable": True,
         "constraint_refs": []},
        {"property_id": "urn:ocor:property:vessel-status", "value_type_ref": "enum:urn:ocor:type:vessel-status",
         "cardinality": "ONE", "nullable": False, "constraint_refs": ["urn:ocor:constraint:status-known"]},
        {"property_id": "urn:ocor:property:vessel-port", "value_type_ref": "ref:urn:ocor:type:port",
         "cardinality": "ONE", "nullable": True, "constraint_refs": []},
    ]


def _definitions(*, interfaces: Sequence[str] = ("urn:ocor:type:asset", "urn:ocor:type:tracked")) -> list[dict[str, Any]]:
    temporal = {"mode": "BITEMPORAL", "valid_from_field": "valid_from", "valid_to_field": "valid_to",
                "system_from_field": "system_from", "system_to_field": "system_to", "precision": "MICROSECOND",
                "timezone_policy": "UTC"}
    return [
        {"construct": "TypeDefinition", "type_id": "urn:ocor:type:vessel", "kind": "OBJECT", "version": "1.0.0",
         "label": "Vessel café", "properties": _properties(), "keys": ["urn:ocor:property:vessel-name"],
         "interfaces": list(interfaces), "lifecycle_ref": "urn:ocor:lifecycle:asset",
         "temporal_annotation": temporal, "security_profile_ref": "urn:ocor:security-profile:restricted"},
        {"construct": "TypeDefinition", "type_id": "urn:ocor:type:asset", "kind": "INTERFACE", "version": "1.0.0",
         "properties": [], "keys": [], "interfaces": [], "security_profile_ref": "urn:ocor:security-profile:restricted"},
        {"construct": "TypeDefinition", "type_id": "urn:ocor:type:tracked", "kind": "INTERFACE", "version": "1.0.0",
         "properties": [], "keys": [], "interfaces": [], "security_profile_ref": "urn:ocor:security-profile:restricted"},
        {"construct": "TypeDefinition", "type_id": "urn:ocor:type:hull", "kind": "STRUCT", "version": "1.0.0",
         "properties": [{"property_id": "urn:ocor:property:hull-material", "value_type_ref": "string",
                         "cardinality": "ONE", "nullable": False, "constraint_refs": []}],
         "keys": [], "interfaces": [], "security_profile_ref": "urn:ocor:security-profile:restricted"},
        {"construct": "TypeDefinition", "type_id": "urn:ocor:type:vessel-status", "kind": "ENUM", "version": "1.0.0",
         "values": ["ACTIVE", "LAID_UP"], "properties": [], "keys": [], "interfaces": [],
         "security_profile_ref": "urn:ocor:security-profile:restricted"},
        {"construct": "TypeDefinition", "type_id": "urn:ocor:type:port", "kind": "OBJECT", "version": "1.0.0",
         "properties": [{"property_id": "urn:ocor:property:port-code", "value_type_ref": "string",
                         "cardinality": "ONE", "nullable": False, "constraint_refs": []}],
         "keys": ["urn:ocor:property:port-code"], "interfaces": [],
         "security_profile_ref": "urn:ocor:security-profile:restricted"},
        {"construct": "LinkDefinition", "link_id": "urn:ocor:link:berthing",
         "roles": [{"role": "vessel", "role_player_type_ref": "urn:ocor:type:vessel", "cardinality": "ONE"},
                   {"role": "port", "role_player_type_ref": "urn:ocor:type:port", "cardinality": "ONE"},
                   {"role": "pilot", "role_player_type_ref": "urn:ocor:type:port", "cardinality": "MANY"}],
         "properties": [], "temporal_annotation": temporal,
         "security_profile_ref": "urn:ocor:security-profile:restricted"},
        {"construct": "ConstraintDefinition", "constraint_id": "urn:ocor:constraint:status-known", "kind": "INVARIANT",
         "scope_ref": "urn:ocor:type:vessel", "typed_expression": {"op": "in", "field": "urn:ocor:property:vessel-status",
                                                                 "values": ["ACTIVE", "LAID_UP"]},
         "evaluation_phase": "COMMIT", "severity": "ERROR", "execution_owner": "urn:ocor:owner:c3",
         "validity": "ALWAYS", "repair_strategy": "REJECT"},
        {"construct": "DerivedDefinition", "derived_id": "urn:ocor:derived:active-vessels",
         "result_type_ref": "urn:ocor:type:vessel", "typed_ast": {"op": "filter", "on": "urn:ocor:type:vessel"},
         "execution_owner": "urn:ocor:owner:c4", "materialization_policy": "ON_READ",
         "dependency_refs": ["urn:ocor:type:vessel"]},
        {"construct": "ContractDefinition", "contract_id": "urn:ocor:contract:get-vessel", "kind": "NAMED_QUERY",
         "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
         "output_schema": {"type": "object", "properties": {"vessel": {"$ref": "urn:ocor:type:vessel"}}},
         "error_model": ["CONTRACT_NOT_FOUND", "POLICY_DENIED"], "effect_class": "READ_ONLY", "risk_class": "R0",
         "policy_refs": ["urn:ocor:policy:read-vessels"], "approval_refs": [], "version": "1.0.0"},
        {"construct": "ContractDefinition", "contract_id": "urn:ocor:contract:vessel-berthed", "kind": "EVENT",
         "input_schema": {"type": "object", "properties": {"vessel": {"type": "string"}}},
         "output_schema": {"type": "object"}, "error_model": [], "effect_class": "EVENT", "risk_class": "R0",
         "policy_refs": [], "approval_refs": [], "version": "1.0.0"},
        {"construct": "MarkingSchemeDefinition", "scheme_id": "urn:ocor:marking-scheme:fleet", "version": "1.0.0",
         "levels": ["UNCLASSIFIED", "RESTRICTED"], "top": "RESTRICTED", "bottom": "UNCLASSIFIED",
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
                 ("handling_instructions", "RESTRICTION", "UNION", "INTERSECTION"),
             )
         ],
         "unknown_value_behavior": "DENY", "incomparable_behavior": "DENY",
         "declassification_authority_ref": "urn:ocor:authority:declassification"},
        {"construct": "SecurityProfileDefinition", "security_profile_id": "urn:ocor:security-profile:restricted",
         "marking_scheme_ref": "urn:ocor:marking-scheme:fleet", "default_marking": "RESTRICTED"},
    ]


def _dispositions(*, unsupported: tuple[str, str] | None = None) -> list[dict[str, Any]]:
    capabilities = [f"value-family:{family}" for family in VALUE_FAMILIES] + [
        "construct:link:n-ary",
        "construct:constraint",
        "construct:derived",
        "construct:temporal:bitemporal",
    ]
    out = []
    for capability in capabilities:
        for role in ADAPTER_ROLES:
            disposition = "unsupported" if unsupported == (capability, role) else "exact"
            out.append({"construct": "CapabilityDisposition", "semantic_capability_id": capability,
                        "adapter_role": role, "disposition": disposition, "limitation": None,
                        "evidence_ref": "urn:ocor:evidence:fixture"})
    return out


def oac_documents(**overrides: Any) -> dict[str, dict[str, Any]]:
    package = {
        "construct": "OntologyPackage",
        "package_id": "urn:ocor:package:fleet",
        "version": overrides.get("version", "1.2.0"),
        "namespace_refs": ["urn:ocor:namespace:fleet"],
        "module_refs": ["urn:ocor:module:fleet-core"],
        "dependency_lock": [{"resource_id": "urn:ocor:module:shared-units", "version": "1.0.0",
                             "sha256": overrides.get("lock_digest", LOCK_DIGEST_A)}],
        "owner": "urn:ocor:owner:fleet-team",
        "classification_marking": "RESTRICTED",
        "release_profile": "poc",
        "adapter_roles": list(ADAPTER_ROLES),
        "artifact_targets": list(TARGETS),
    }
    namespace = {
        "construct": "Namespace",
        "namespace_id": "urn:ocor:namespace:fleet",
        "uri": "https://ocor.example/ns/fleet#",
        "prefix": "fleet",
        "ownership_boundary": "urn:ocor:owner:fleet-team",
        "default_marking": "RESTRICTED",
    }
    module = {
        "construct": "Module",
        "module_id": "urn:ocor:module:fleet-core",
        "version": "1.2.0",
        "namespace_ref": "urn:ocor:namespace:fleet",
        "imports": overrides.get("imports", ["urn:ocor:module:shared-units"]),
        "exports": ["urn:ocor:type:vessel", "urn:ocor:type:port"],
        "definitions": overrides.get("definitions", _definitions() + _dispositions()),
        "owner": "urn:ocor:owner:fleet-team",
        "steward": "urn:ocor:owner:fleet-steward",
        "reviewer": "urn:ocor:owner:fleet-reviewer",
        "status": "APPROVED",
        "review_date": "2026-10-31",
    }
    return {"package.yaml": package, "namespace.yaml": namespace, "module.yaml": module}


def oac_request(
    documents: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    semantic_version: str = "1.2.0",
    lock_digest: str = LOCK_DIGEST_A,
    dump: Callable[[Any], str] | None = None,
) -> CompilerRequest:
    docs = documents if documents is not None else oac_documents(version=semantic_version, lock_digest=lock_digest)
    render = dump or (lambda value: yaml.safe_dump(value, sort_keys=True, allow_unicode=True))
    ids = {"package.yaml": "urn:ocor:package:fleet", "namespace.yaml": "urn:ocor:namespace:fleet",
           "module.yaml": "urn:ocor:module:fleet-core"}
    sources = tuple(
        SourceUnit.create(
            resource_id=ids[path],
            version=str(document.get("version", "1.2.0")),
            syntax=SourceSyntax.YAML,
            content=render(document).encode("utf-8"),
            source_path=path,
            imports=("urn:ocor:module:shared-units",) if path == "module.yaml" else (),
        )
        for path, document in docs.items()
    )
    return CompilerRequest(
        package_id="urn:ocor:package:fleet",
        semantic_version=semantic_version,
        source_commit=COMMIT,
        compiler_version="1.0.0",
        mapping_version="1",
        release_profile="poc",
        sources=sources,
        dependency_lock=(DependencyLockEntry("urn:ocor:module:shared-units", "1.0.0", lock_digest),),
    )


def compiler(*, approved_exceptions: Sequence[tuple[str, str]] = ()) -> Any:
    return c1("ir").OacCompiler(approved_exceptions=approved_exceptions)


def _openssl_ed25519_seed(workdir: Path) -> tuple[bytes, Path]:
    """Generate an Ed25519 key with OpenSSL; return the raw 32-byte seed and the public PEM."""
    private = workdir / "ed25519.pem"
    public = workdir / "ed25519.pub.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)], check=True,
                   capture_output=True)
    subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)], check=True,
                   capture_output=True)
    der = subprocess.run(["openssl", "pkey", "-in", str(private), "-outform", "DER"], check=True,
                         capture_output=True).stdout
    assert der[:16] == bytes.fromhex("302e020100300506032b657004220420")
    return der[16:48], public


def _openssl_verify(public_pem: Path, message: bytes, signature: bytes, workdir: Path) -> bool:
    msg = workdir / "msg.bin"
    sig = workdir / "sig.bin"
    msg.write_bytes(message)
    sig.write_bytes(signature)
    result = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(public_pem), "-rawin",
                             "-in", str(msg), "-sigfile", str(sig)], capture_output=True)
    return result.returncode == 0


def _envelope_schema() -> Mapping[str, Any]:
    """The signed-canonical-ir:1.0 schema exactly as embedded in ADD v1.3 :466-521."""
    lines = ADD.read_text(encoding="utf-8").splitlines()
    anchor = next(i for i, line in enumerate(lines) if '"$id": "urn:ocor:schema:signed-canonical-ir:1.0"' in line)
    start = max(i for i in range(anchor) if lines[i].startswith("~~~"))  # the opening ~~~json fence
    end = next(i for i in range(anchor, len(lines)) if lines[i].startswith("~~~"))
    schema: Mapping[str, Any] = json.loads("\n".join(lines[start + 1 : end]))
    assert schema["$id"] == "urn:ocor:schema:signed-canonical-ir:1.0"
    return schema


class _Signing:
    def __init__(self, workdir: Path) -> None:
        signing = c1("signing")
        self.module = signing
        self.seed, self.public_pem = _openssl_ed25519_seed(workdir)
        self.key = signing.Ed25519SigningKey.from_seed(self.seed)
        self.keyid = "urn:ocor:key:c1-test"
        self.chain = "urn:sha256:" + hashlib.sha256(b"test-certificate-chain").hexdigest()
        self.signer = signing.DsseIrSigner(key=self.key, keyid=self.keyid, certificate_chain_ref=self.chain,
                                           clock=lambda: NOW)
        self.trust_root = signing.TrustRoot(
            keys={self.keyid: signing.TrustedKey(public_key=self.key.public_key, certificate_chain_ref=self.chain,
                                                 signing_profile=signing.ED25519_PROFILE)},
            revoked_keyids=frozenset(),
        )

    def admission(self, *, revoked: frozenset[str] = frozenset(), compilers: Sequence[str] = ("1.0.0",)) -> Any:
        root = self.module.TrustRoot(keys=self.trust_root.keys, revoked_keyids=revoked)
        return self.module.ReleaseAdmission(trust_root=root, accepted_compiler_versions=tuple(compilers))


def _package(signing: _Signing, request: CompilerRequest) -> Any:
    """Compile, generate the artefacts, attach the manifest and sign (PackageRelease)."""
    release = compiler().build(request)
    generator = c1("codegen").IrArtifactGenerator()
    files = generator.render(release)
    release = release.with_artifacts(generator.generate(release))
    return signing.module.ReleasePackage.create(
        signed=signing.signer.sign_release(release), dependency_lock=request.dependency_lock, artifacts=files
    )


def _rejected(call: Callable[[], object], *codes: DiagnosticCode) -> C1Error:
    with pytest.raises(C1Error) as caught:
        call()
    got = {item.code for item in caught.value.diagnostics}
    assert got & set(codes), (got, codes)
    return caught.value


# --------------------------------------------------------------------------- #
# NCR-C1-002 -- signed-canonical-ir:1.0 DSSE envelope and admission.
# --------------------------------------------------------------------------- #


def test_ncr_c1_002_conforms() -> None:
    """NCR-C1-002 (NFR-021, NFR-051): ADD v1.3 :466-521 envelope, :523 admission."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        signing = _Signing(workdir)
        request = oac_request()
        package = _package(signing, request)
        signed = package.signed
        envelope = signed.envelope

        # The envelope is exactly the ADD schema; the release references it by digest.
        jsonschema.Draft202012Validator(_envelope_schema()).validate(envelope)
        assert signed.release.signature_envelope_ref == canonical_digest(envelope)
        assert not signed.release.signature_envelope_ref.startswith("urn:ocor:unsigned:")
        payload = base64.b64decode(envelope["payload"], validate=True)
        assert payload == signed.release.canonical_bytes
        assert envelope["digest"] == "sha256:" + hashlib.sha256(payload).hexdigest()
        assert "urn:sha256:" + envelope["digest"].removeprefix("sha256:") == signed.release.ir_digest
        assert envelope["signingProfile"] == signing.module.ED25519_PROFILE
        assert envelope["signatures"][0]["signedAt"] == "2026-10-31T09:00:00Z"

        # DSSE PAE and the signature, checked with OpenSSL as an independent oracle.
        pae = signing.module.dsse_pae(envelope["payloadType"], payload)
        expected_pae = b"DSSEv1 %d %s %d %s" % (
            len(envelope["payloadType"]), envelope["payloadType"].encode(), len(payload), payload)
        assert pae == expected_pae
        signature = base64.b64decode(envelope["signatures"][0]["sig"], validate=True)
        assert _openssl_verify(signing.public_pem, pae, signature, workdir)
        assert not _openssl_verify(signing.public_pem, pae + b"x", signature, workdir)

        # RFC 8032 section 7.1 test vector 1 (empty message).
        rfc_key = signing.module.Ed25519SigningKey.from_seed(bytes.fromhex(
            "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"))
        assert rfc_key.public_key.hex() == "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
        assert rfc_key.sign(b"").hex() == (
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")

        # Admission (VerifyRelease) accepts the genuine package.
        receipt = signing.admission().verify(package)
        assert receipt.ir_digest == signed.release.ir_digest
        assert receipt.envelope_ref == signed.release.signature_envelope_ref

        def tampered(mutate: Callable[[dict[str, Any]], None]) -> Any:
            env = copy.deepcopy(dict(envelope))
            mutate(env)
            return signing.module.ReleasePackage.create(
                signed=signing.module.SignedRelease(release=signed.release, envelope=env),
                dependency_lock=package.dependency_lock, artifacts=package.artifacts)

        other_core = json.loads(payload)
        other_core["release"]["mapping_version"] = "2"
        forged_payload = canonical_bytes(other_core)
        cases: list[tuple[str, Callable[[], object], tuple[DiagnosticCode, ...]]] = [
            ("tampered payload", lambda: signing.admission().verify(tampered(
                lambda e: e.__setitem__("payload", base64.b64encode(forged_payload).decode()))),
             (DiagnosticCode.SIGNATURE_INVALID,)),
            ("invalid signature", lambda: signing.admission().verify(tampered(
                lambda e: e["signatures"][0].__setitem__("sig", base64.b64encode(b"\x00" * 64).decode()))),
             (DiagnosticCode.SIGNATURE_INVALID,)),
            ("inconsistent digest", lambda: signing.admission().verify(tampered(
                lambda e: e.__setitem__("digest", "sha256:" + "0" * 64))),
             (DiagnosticCode.SIGNATURE_INVALID,)),
            ("schema violation", lambda: signing.admission().verify(tampered(
                lambda e: e.__setitem__("canonicalization", "JCS-LIKE"))),
             (DiagnosticCode.SIGNATURE_INVALID,)),
            ("unknown key", lambda: signing.admission().verify(tampered(
                lambda e: e["signatures"][0].__setitem__("keyid", "urn:ocor:key:unknown"))),
             (DiagnosticCode.SIGNATURE_INVALID,)),
            ("chain mismatch", lambda: signing.admission().verify(tampered(
                lambda e: e["signatures"][0].__setitem__("certificateChainRef", "urn:sha256:" + "c" * 64))),
             (DiagnosticCode.SIGNATURE_INVALID,)),
            ("revoked key", lambda: signing.admission(revoked=frozenset({signing.keyid})).verify(package),
             (DiagnosticCode.SIGNATURE_INVALID,)),
            ("compiler not admitted", lambda: signing.admission(compilers=("0.9.0",)).verify(package),
             (DiagnosticCode.RELEASE_REJECTED,)),
            ("lock mismatch", lambda: signing.admission().verify(signing.module.ReleasePackage.create(
                signed=signed, artifacts=package.artifacts,
                dependency_lock=(DependencyLockEntry("urn:ocor:module:shared-units", "1.0.0", LOCK_DIGEST_B),))),
             (DiagnosticCode.LOCK_INVALID,)),
            ("missing artefact", lambda: signing.admission().verify(signing.module.ReleasePackage.create(
                signed=signed, dependency_lock=package.dependency_lock,
                artifacts={k: v for k, v in package.artifacts.items() if not k.endswith(":openapi")})),
             (DiagnosticCode.ARTIFACT_DRIFT,)),
            ("modified artefact", lambda: signing.admission().verify(signing.module.ReleasePackage.create(
                signed=signed, dependency_lock=package.dependency_lock,
                artifacts={k: (v + b"\n" if k.endswith(":openapi") else v) for k, v in package.artifacts.items()})),
             (DiagnosticCode.ARTIFACT_DRIFT,)),
        ]
        for name, call, codes in cases:
            try:
                _rejected(call, *codes)
            except AssertionError as error:  # pragma: no cover - diagnostic aid
                raise AssertionError(f"admission case {name!r}: {error}") from error

        # An unsigned candidate is never admitted.
        unsigned = compiler().build(request)
        assert unsigned.signature_envelope_ref.startswith("urn:ocor:unsigned:")
        _rejected(lambda: signing.admission().verify(signing.module.ReleasePackage.create(
            signed=signing.module.SignedRelease(release=unsigned, envelope={}),
            dependency_lock=package.dependency_lock, artifacts=package.artifacts)), DiagnosticCode.SIGNATURE_INVALID)


# --------------------------------------------------------------------------- #
# NCR-C1-003 -- CanonicalIRCore structure, lock digest, capability classification.
# --------------------------------------------------------------------------- #


def test_ncr_c1_003_conforms() -> None:
    """NCR-C1-003 (FR-040, FR-041, FR-042, NFR-018): ADD v1.3 :441-464 and :438-439."""
    release = compiler().build(oac_request())
    core = release.core
    assert set(core) == CORE_KEYS
    assert core["format"] == "ocor.cir/1.0"
    assert set(core["release"]) == RELEASE_KEYS
    assert core["release"]["lock_digest"] == canonical_digest(
        [{"resource_id": "urn:ocor:module:shared-units", "sha256": LOCK_DIGEST_A, "version": "1.0.0"}])
    for key in ("namespaces", "modules", "symbol_table", "security_profiles", "capability_matrix", "artifact_plan"):
        assert len(core[key]) >= 1, key
    assert release.ir_digest == canonical_digest(json.loads(release.canonical_bytes))

    # The lock enters ir_digest; the same lock resolves the same digest (FR-041).
    other_lock = compiler().build(oac_request(lock_digest=LOCK_DIGEST_B))
    assert other_lock.ir_digest != release.ir_digest
    assert compiler().build(oac_request()).ir_digest == release.ir_digest
    _rejected(lambda: compiler().build(oac_request(documents=oac_documents(lock_digest=LOCK_DIGEST_B))),
              DiagnosticCode.LOCK_INVALID)

    # Every symbol resolves; every (capability, adapter role) pair is classified (step 5).
    symbols = {entry["symbol_id"] for entry in core["symbol_table"]}
    assert {"urn:ocor:type:vessel", "urn:ocor:property:vessel-name", "urn:ocor:link:berthing",
            "urn:ocor:contract:get-vessel", "urn:ocor:namespace:fleet", "urn:ocor:module:fleet-core"} <= symbols
    pairs = {(entry["semantic_capability_id"], entry["adapter_role"]) for entry in core["capability_matrix"]}
    for family in VALUE_FAMILIES:
        for role in ADAPTER_ROLES:
            assert (f"value-family:{family}", role) in pairs
    assert {entry["artifact_kind"] for entry in core["artifact_plan"]} == set(TARGETS)

    # Step 6: an unapproved 'unsupported' disposition is rejected fail-closed;
    # an approved exception admits it and is recorded in the matrix.
    pair = ("value-family:geospatial", "jena")
    docs = oac_documents(definitions=_definitions() + _dispositions(unsupported=pair))
    _rejected(lambda: compiler().build(oac_request(documents=docs)), DiagnosticCode.UNSUPPORTED_CAPABILITY)
    excepted = compiler(approved_exceptions=(pair,)).build(oac_request(documents=docs))
    entry = next(e for e in excepted.core["capability_matrix"]
                 if (e["semantic_capability_id"], e["adapter_role"]) == pair)
    assert entry["disposition"] == "unsupported" and entry["approved_exception"] is True
    # A used capability without any disposition for an adapter role is unsupported.
    missing = [d for d in _dispositions() if (d.get("semantic_capability_id"), d.get("adapter_role")) != pair]
    _rejected(lambda: compiler().build(oac_request(documents=oac_documents(definitions=_definitions() + missing))),
              DiagnosticCode.UNSUPPORTED_CAPABILITY)

    # IR JSON and Protobuf are semantically equivalent and carry the same ir_digest (FR-040).
    ir = c1("ir")
    encoded = ir.encode_protobuf(release)
    digest, decoded = ir.decode_protobuf(encoded)
    assert digest == release.ir_digest and canonical_digest(decoded) == release.ir_digest
    from google.protobuf import struct_pb2

    envelope = struct_pb2.Struct()
    envelope.ParseFromString(encoded)
    assert envelope["ir_digest"] == release.ir_digest
    from google.protobuf.json_format import MessageToDict

    assert canonical_digest(_ints(MessageToDict(envelope)["core"])) == release.ir_digest
    assert ir.encode_protobuf(compiler().build(oac_request())) == encoded


def _ints(value: Any) -> Any:
    """google.protobuf.Value carries numbers as doubles; integral values return to int."""
    if isinstance(value, dict):
        return {k: _ints(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_ints(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


# --------------------------------------------------------------------------- #
# NCR-C1-004 -- OaC metamodel, meta-schema and normalisation.
# --------------------------------------------------------------------------- #


def test_ncr_c1_004_conforms() -> None:
    """NCR-C1-004 (FR-024, FR-026, FR-027, FR-042): ADD v1.3 :415, :417-431, :435."""
    oac = c1("oac")
    meta = oac.OAC_META_SCHEMA
    jsonschema.Draft202012Validator.check_schema(meta)
    for document in oac_documents().values():
        jsonschema.Draft202012Validator(meta).validate(document)

    release = compiler().build(oac_request())
    core = release.core
    # Every construct family of the metamodel is represented in the IR.
    assert {t["type_id"] for t in core["types"]} >= {"urn:ocor:type:vessel", "urn:ocor:type:hull",
                                                     "urn:ocor:type:vessel-status", "urn:ocor:type:asset"}
    assert {t["kind"] for t in core["types"]} >= {"OBJECT", "INTERFACE", "STRUCT", "ENUM"}
    berthing = next(link for link in core["links"] if link["link_id"] == "urn:ocor:link:berthing")
    assert len(berthing["roles"]) == 3  # n-ary, named roles, Link distinct from CausalEdge
    assert [c["constraint_id"] for c in core["constraints"]] == ["urn:ocor:constraint:status-known"]
    assert [d["derived_id"] for d in core["derived_definitions"]] == ["urn:ocor:derived:active-vessels"]
    assert {c["contract_id"] for c in core["named_contracts"]} == {"urn:ocor:contract:get-vessel",
                                                                    "urn:ocor:contract:vessel-berthed"}
    assert any(t["mode"] == "BITEMPORAL" for t in core["temporal_semantics"])
    assert core["security_profiles"][0]["security_profile_id"] == "urn:ocor:security-profile:restricted"
    # Every value-type family compiles to an unambiguous IR representation (FR-024).
    vessel = next(t for t in core["types"] if t["type_id"] == "urn:ocor:type:vessel")
    families = {p["value_type"]["family"] for p in vessel["properties"]}
    assert families == set(VALUE_FAMILIES)

    # Meta-schema violations are rejected with localised diagnostics.
    def broken(path: str, mutate: Callable[[dict[str, Any]], None]) -> CompilerRequest:
        docs = copy.deepcopy(oac_documents())
        mutate(docs[path])
        return oac_request(documents=docs)

    negatives = [
        ("package.yaml", lambda d: d.pop("owner")),
        ("namespace.yaml", lambda d: d.__setitem__("uri", "")),
        ("module.yaml", lambda d: d.__setitem__("definitions", [])),
        ("module.yaml", lambda d: d["definitions"][0].__setitem__("kind", "TABLE")),
        ("module.yaml", lambda d: d["definitions"][0]["temporal_annotation"].__setitem__("mode", "SOMETIMES")),
        ("module.yaml", lambda d: d["definitions"][0]["properties"][0].__setitem__("value_type_ref", "varchar(20)")),
        ("module.yaml", lambda d: d["definitions"][6].__setitem__("roles", d["definitions"][6]["roles"][:1])),
        ("module.yaml", lambda d: d["definitions"][7].__setitem__("kind", "TRIGGER")),
        ("module.yaml", lambda d: d["definitions"][9].__setitem__("kind", "STORED_PROCEDURE")),
        ("module.yaml", lambda d: d["definitions"][11].__setitem__("family_definitions",
                                                                   d["definitions"][11]["family_definitions"][:4])),
        ("module.yaml", lambda d: d["definitions"][11].__setitem__("unknown_value_behavior", "ALLOW")),
        ("module.yaml", lambda d: d["definitions"][12].__setitem__("construct", "Table")),
        ("module.yaml", lambda d: d.__setitem__("unexpected", True)),
    ]
    for index, (path, mutate) in enumerate(negatives):
        error = _rejected(lambda: compiler().build(broken(path, mutate)), DiagnosticCode.SOURCE_INVALID,
                          DiagnosticCode.TYPE_ERROR)
        assert any(d.path.startswith(path) for d in error.diagnostics), (index, error.diagnostics)

    # Two execution owners on one derived definition and a cyclic module import are rejected.
    def two_owners(d: dict[str, Any]) -> None:
        d["definitions"][8]["execution_owner"] = ["urn:ocor:owner:c3", "urn:ocor:owner:c4"]

    _rejected(lambda: compiler().build(broken("module.yaml", two_owners)), DiagnosticCode.MULTIPLE_EXECUTION_OWNERS,
              DiagnosticCode.TYPE_ERROR)
    _rejected(lambda: compiler().build(broken("module.yaml", lambda d: d["definitions"][0]["properties"][9]
                                              .__setitem__("value_type_ref", "ref:urn:ocor:type:absent"))),
              DiagnosticCode.UNRESOLVED_REFERENCE)

    # Normalisation step 2: NFC, RFC 3339 UTC timestamps and canonical decimals.
    nfd = copy.deepcopy(oac_documents())
    nfd["module.yaml"]["definitions"][0]["label"] = unicodedata.normalize("NFD", "Vessel café")
    assert nfd["module.yaml"]["definitions"][0]["label"] != "Vessel café"
    assert compiler().build(oac_request(documents=nfd)).ir_digest == release.ir_digest
    utc = copy.deepcopy(oac_documents())
    utc["module.yaml"]["definitions"][0]["properties"][1]["default"] = "2026-10-31T08:00:00Z"
    utc["module.yaml"]["definitions"][0]["properties"][2]["default"] = "1.5"
    assert compiler().build(oac_request(documents=utc)).ir_digest == release.ir_digest
    # JSON and YAML sources of the same package compile to the same IR.
    as_json = compiler().build(oac_request(dump=lambda value: json.dumps(value, ensure_ascii=False)))
    assert as_json.ir_digest == release.ir_digest


# --------------------------------------------------------------------------- #
# NCR-C1-005 -- generated targets from the same IR, identifiers and drift check.
# --------------------------------------------------------------------------- #


def test_ncr_c1_005_conforms() -> None:
    """NCR-C1-005 (FR-043, FR-044, NFR-020): LLD v1.1 :107, Register :139-140, :151."""
    release = compiler().build(oac_request())
    generator = c1("codegen").IrArtifactGenerator()
    files = generator.render(release)
    manifest = generator.generate(release)
    package_id = "urn:ocor:package:fleet"
    assert set(files) == {f"{package_id}:{target}" for target in TARGETS}
    assert {entry.artifact_id for entry in manifest} == set(files)
    for entry in manifest:
        assert entry.digest == "urn:sha256:" + hashlib.sha256(files[entry.artifact_id]).hexdigest()
    # Deterministic, bit-for-bit (NFR-051).
    assert generator.render(compiler().build(oac_request())) == files

    identifiers = {
        "ontologyRelease": f"{package_id}@1.2.0",
        "irDigest": release.ir_digest,
        "compilerVersion": "1.0.0",
        "mappingVersion": "1",
    }
    for artifact_id, content in files.items():
        text = content.decode("utf-8")
        for name, value in identifiers.items():
            assert name in text and value in text, (artifact_id, name)
        # No backend dialect or internal identifier leaks into a generated contract (FR-044).
        assert re.search(r"\b(TypeQL|typeql|WOQL|woql|SPARQL|sparql|SELECT\s+\?)", text) is None, artifact_id

    json_schema = json.loads(files[f"{package_id}:json-schema"])
    jsonschema.Draft202012Validator.check_schema(json_schema)
    assert "urn:ocor:type:vessel" in json.dumps(json_schema)
    from openapi_spec_validator import validate as validate_openapi

    openapi = json.loads(files[f"{package_id}:openapi"])
    validate_openapi(openapi)
    assert any("get-vessel" in path for path in openapi["paths"])
    asyncapi = json.loads(files[f"{package_id}:asyncapi"])
    assert asyncapi["asyncapi"].startswith("3.") and asyncapi["channels"]
    mcp = json.loads(files[f"{package_id}:mcp-descriptor"])
    assert {tool["name"] for tool in mcp["tools"]} >= {"get-vessel"}
    compile(files[f"{package_id}:sdk-python"].decode(), "sdk.py", "exec")
    assert "export " in files[f"{package_id}:sdk-typescript"].decode()
    with tempfile.TemporaryDirectory() as tmp:
        proto = Path(tmp) / "fleet.proto"
        proto.write_bytes(files[f"{package_id}:protobuf"])
        from grpc_tools import protoc

        assert protoc.main(["protoc", f"-I{tmp}", f"--python_out={tmp}", str(proto)]) == 0

    # Drift between a generated artefact and the IR blocks the release.
    generator.check_drift(release, files)
    _rejected(lambda: generator.check_drift(release, {**files, f"{package_id}:openapi": b"{}"}),
              DiagnosticCode.ARTIFACT_DRIFT)
    _rejected(lambda: generator.check_drift(release, {k: v for k, v in files.items() if not k.endswith(":asyncapi")}),
              DiagnosticCode.ARTIFACT_DRIFT)
    _rejected(lambda: generator.check_drift(release, {**files, f"{package_id}:extra": b"x"}),
              DiagnosticCode.ARTIFACT_DRIFT)


# --------------------------------------------------------------------------- #
# NCR-C1-006 -- FR-045 change classes, plans, dual control and new major.
# --------------------------------------------------------------------------- #


def _vessel(documents: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = documents["module.yaml"]["definitions"][0]
    return result


def test_ncr_c1_006_conforms() -> None:
    """NCR-C1-006 (FR-045, FR-046): Register v1.1 :141, LLD v1.1 :107 under :16-18."""
    migration = c1("migration")
    classes = migration.ChangeClass
    assert {item.value for item in classes} == {"compatible", "conditional", "breaking", "destructive",
                                                 "causal-breaking"}
    previous = compiler().build(oac_request())

    def candidate(version: str, mutate: Callable[[dict[str, dict[str, Any]]], None]) -> Any:
        docs = copy.deepcopy(oac_documents(version=version))
        mutate(docs)
        return compiler().build(oac_request(documents=docs, semantic_version=version))

    def add_optional(d: dict[str, dict[str, Any]]) -> None:
        _vessel(d)["properties"].append({"property_id": "urn:ocor:property:vessel-flag", "value_type_ref": "string",
                                         "cardinality": "ONE", "nullable": True, "constraint_refs": []})

    def add_required(d: dict[str, dict[str, Any]]) -> None:
        _vessel(d)["properties"].append({"property_id": "urn:ocor:property:vessel-imo", "value_type_ref": "string",
                                         "cardinality": "ONE", "nullable": False, "constraint_refs": []})

    def retype(d: dict[str, dict[str, Any]]) -> None:
        _vessel(d)["properties"][0]["value_type_ref"] = "integer"

    def remove(d: dict[str, dict[str, Any]]) -> None:
        _vessel(d)["properties"] = [p for p in _vessel(d)["properties"]
                                    if p["property_id"] != "urn:ocor:property:vessel-photo"]

    def causal(d: dict[str, dict[str, Any]]) -> None:
        d["module.yaml"]["definitions"].append(
            {"construct": "TypeDefinition", "type_id": "urn:ocor:type:delay-mechanism", "kind": "CAUSAL",
             "version": "1.0.0", "properties": [], "keys": [], "interfaces": [],
             "security_profile_ref": "urn:ocor:security-profile:restricted"})

    engine = migration.IrSemanticDiffEngine()
    planner = migration.IrMigrationPlanner()
    gate = migration.ReleaseChangeGate()
    expected = [
        ("1.3.0", add_optional, classes.COMPATIBLE),
        ("1.3.0", add_required, classes.CONDITIONAL),
        ("2.0.0", retype, classes.BREAKING),
        ("2.0.0", remove, classes.DESTRUCTIVE),
    ]
    causal_base = candidate("1.3.0", causal)
    for version, mutate, klass in expected:
        target = candidate(version, mutate)
        assert engine.classify(previous, target) is klass, (version, klass)
        plan = planner.plan(previous, target)
        assert plan["classification"] == klass.value
        assert set(plan) >= {"migration", "backfill", "alias", "deprecation", "dry_run", "recovery", "plan_digest"}
        body = {k: v for k, v in plan.items() if k != "plan_digest"}
        assert plan["plan_digest"] == canonical_digest(body)
    causal_change = candidate("2.0.0", lambda d: (causal(d), d["module.yaml"]["definitions"][-1]
                                                  .__setitem__("interfaces", ["urn:ocor:type:asset"])))
    assert engine.classify(causal_base, causal_change) is classes.CAUSAL_BREAKING
    assert engine.classify(previous, previous) is classes.COMPATIBLE
    assert engine.compare(previous, candidate("1.3.0", add_optional)).startswith("urn:sha256:")

    # Conditional needs a backfill plan.
    conditional = candidate("1.3.0", add_required)
    conditional_plan = planner.plan(previous, conditional)
    assert conditional_plan["backfill"]
    gate.admit(previous, conditional, plan=conditional_plan, approvals=())
    _rejected(lambda: gate.admit(previous, conditional, plan={**conditional_plan, "backfill": []}, approvals=()),
              DiagnosticCode.RELEASE_REJECTED)

    # Breaking needs migration plan, dual control and a new major (LLD v1.1 :107).
    breaking = candidate("2.0.0", retype)
    breaking_plan = planner.plan(previous, breaking)
    two = ("urn:ocor:principal:a", "urn:ocor:principal:b")
    gate.admit(previous, breaking, plan=breaking_plan, approvals=two)
    _rejected(lambda: gate.admit(previous, breaking, plan=None, approvals=two), DiagnosticCode.RELEASE_REJECTED)
    _rejected(lambda: gate.admit(previous, breaking, plan=breaking_plan, approvals=two[:1]),
              DiagnosticCode.RELEASE_REJECTED)
    _rejected(lambda: gate.admit(previous, breaking, plan=breaking_plan, approvals=(two[0], two[0])),
              DiagnosticCode.RELEASE_REJECTED)
    same_major = candidate("1.4.0", retype)
    _rejected(lambda: gate.admit(previous, same_major, plan=planner.plan(previous, same_major), approvals=two),
              DiagnosticCode.RELEASE_REJECTED)

    # A destructive change without backup/replay plan is rejected (FR-045 acceptance).
    destructive = candidate("2.0.0", remove)
    destructive_plan = planner.plan(previous, destructive)
    assert destructive_plan["recovery"]["backup_required"] is True
    _rejected(lambda: gate.admit(previous, destructive, plan=destructive_plan, approvals=two),
              DiagnosticCode.RELEASE_REJECTED)
    covered = planner.plan(previous, destructive, backup_ref="urn:ocor:backup:fleet-1.2.0",
                           replay_plan_ref="urn:ocor:replay:fleet-1.2.0")
    gate.admit(previous, destructive, plan=covered, approvals=two)
    # A plan that does not belong to the pair is rejected.
    _rejected(lambda: gate.admit(previous, destructive, plan=breaking_plan, approvals=two),
              DiagnosticCode.RELEASE_REJECTED)


# --------------------------------------------------------------------------- #
# NCR-C1-008 -- set-like arrays sorted and duplicate-free before the digest.
# --------------------------------------------------------------------------- #


def test_ncr_c1_008_conforms() -> None:
    """NCR-C1-008 (NFR-018): LLD v1.1 :39, ADD v1.3 :436."""
    # The frontend builder's set-like 'references' array (frontend.py:280).
    frontend = importlib.import_module("ocor_runtime.c1.frontend")

    def source(rid: str, refs: Sequence[str]) -> SourceUnit:
        body = {"id": rid, "fields": {"name": "x"}, "field_types": {"name": "string"}, "references": list(refs)}
        return SourceUnit.create(resource_id=rid, version="1", syntax=SourceSyntax.YAML,
                                 content=yaml.safe_dump(body, sort_keys=True).encode(), source_path=f"{rid}.yaml")

    def legacy(refs: Sequence[str]) -> CompilerRequest:
        return CompilerRequest(
            package_id="urn:ocor:package:refs", semantic_version="1.0.0", source_commit=COMMIT,
            compiler_version="1.0.0", mapping_version="1", release_profile="poc",
            sources=(source("urn:ocor:resource:a", refs), source("urn:ocor:resource:b", ()),
                     source("urn:ocor:resource:c", ())), dependency_lock=())

    # The IR array is sorted whatever the source order (the source bytes, and so their
    # content_digest, legitimately differ between the two sources).
    for order in (("urn:ocor:resource:c", "urn:ocor:resource:b"), ("urn:ocor:resource:b", "urn:ocor:resource:c")):
        built = frontend.FrontendCanonicalIrBuilder().build(legacy(order))
        assert tuple(built.core["resources"]["urn:ocor:resource:a"]["references"]) == (
            "urn:ocor:resource:b", "urn:ocor:resource:c")
    _rejected(lambda: frontend.FrontendCanonicalIrBuilder().build(
        legacy(("urn:ocor:resource:c", "urn:ocor:resource:b", "urn:ocor:resource:b"))),
        DiagnosticCode.DUPLICATE_RESOURCE)

    # The conforming compiler: set-like arrays of the IR.
    base = compiler().build(oac_request())
    swapped = oac_documents(definitions=_definitions(interfaces=("urn:ocor:type:tracked", "urn:ocor:type:asset"))
                            + _dispositions())
    assert compiler().build(oac_request(documents=swapped)).ir_digest == base.ir_digest
    vessel = next(t for t in base.core["types"] if t["type_id"] == "urn:ocor:type:vessel")
    assert list(vessel["interfaces"]) == sorted(vessel["interfaces"])
    duplicated = oac_documents(definitions=_definitions(interfaces=("urn:ocor:type:asset", "urn:ocor:type:asset"))
                               + _dispositions())
    _rejected(lambda: compiler().build(oac_request(documents=duplicated)), DiagnosticCode.DUPLICATE_RESOURCE)
    # Non-semantic collections are ordered by (kind, stable_resource_id, version).
    ids = [t["type_id"] for t in base.core["types"]]
    assert ids == sorted(ids)


# --------------------------------------------------------------------------- #
# NCR-C1-009 -- SemVer.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("version", ["not-semver", "1.0", "01.0.0", "1.0.0-", "v1.0.0", "1.0.0+", "1.2.3.4"])
def test_ncr_c1_009_conforms(version: str) -> None:
    """NCR-C1-009 (FR-040): ADD v1.3 :419, OntologyPackage version is SemVer."""
    _rejected(lambda: oac_request(semantic_version=version), DiagnosticCode.SOURCE_INVALID)
    # The OntologyPackage document's own version is SemVer too (meta-schema).
    docs = oac_documents(version=version)
    _rejected(lambda: compiler().build(oac_request(documents=docs)), DiagnosticCode.SOURCE_INVALID,
              DiagnosticCode.TYPE_ERROR)
    for valid in ("1.0.0", "2.1.3-rc.1+build.5", "0.0.1-alpha"):
        assert oac_request(semantic_version=valid).semantic_version == valid


# --------------------------------------------------------------------------- #
# NCR-C1-010 -- ReleasePublisher, ConformanceSuitePort and the C1 operations.
# --------------------------------------------------------------------------- #


def test_ncr_c1_010_conforms() -> None:
    """NCR-C1-010 (FR-024, NFR-020, FR-046): LLD v1.1 :103-107, ADD v1.3 :282."""
    ports = importlib.import_module("ocor_runtime.c1.ports")
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        signing = _Signing(workdir)
        publisher_module = c1("publisher")
        store = publisher_module.FileSystemReleaseStore(workdir / "releases")
        publisher = publisher_module.ImmutableReleasePublisher(admission=signing.admission(), store=store)
        suite = c1("conformance").IrConformanceSuite()
        assert isinstance(publisher, ports.ReleasePublisher)
        assert isinstance(suite, ports.ConformanceSuitePort)
        assert isinstance(signing.signer, ports.IrSigner)
        assert isinstance(compiler(), ports.CanonicalIrBuilder)
        assert isinstance(c1("codegen").IrArtifactGenerator(), ports.ArtifactGenerator)
        assert isinstance(c1("migration").IrSemanticDiffEngine(), ports.SemanticDiffEngine)
        assert isinstance(c1("migration").IrMigrationPlanner(), ports.MigrationPlanner)

        service = c1("service").OntologyCompilerService(
            compiler=compiler(), generator=c1("codegen").IrArtifactGenerator(), signer=signing.signer,
            admission=signing.admission(), publisher=publisher, conformance=suite,
            diff_engine=c1("migration").IrSemanticDiffEngine(), planner=c1("migration").IrMigrationPlanner(),
            gate=c1("migration").ReleaseChangeGate())

        # ValidatePackage
        assert service.validate_package(oac_request()) == ()
        broken = copy.deepcopy(oac_documents())
        broken["package.yaml"].pop("owner")
        diagnostics = service.validate_package(oac_request(documents=broken))
        assert diagnostics and diagnostics[0].path.startswith("package.yaml")
        # Compile
        release = service.compile(oac_request())
        report = suite.run(release)
        assert report["status"] == "PASS" and report["ir_digest"] == release.ir_digest
        assert {check["check"] for check in report["checks"]} >= {"core_structure", "symbol_resolution",
                                                                  "set_ordering", "nfc", "capability_coverage"}
        # PackageRelease: compile -> generate -> sign -> admit -> publish, immutable.
        ref = service.package_release(oac_request())
        assert ref == service.package_release(oac_request())  # idempotent for identical content
        stored = publisher.read(ref)
        assert stored.signed.release.ir_digest == release.ir_digest
        receipt = service.verify_release(ref)
        assert receipt.ir_digest == release.ir_digest
        # The same package version with different content is rejected (immutable release).
        changed = oac_request(lock_digest=LOCK_DIGEST_B)
        _rejected(lambda: service.package_release(changed), DiagnosticCode.RELEASE_REJECTED)
        # A stored release whose bytes are altered is rejected on read.
        for path in (workdir / "releases").rglob("*.json"):
            path.write_bytes(path.read_bytes().replace(b"fleet", b"fleat", 1))
            break
        _rejected(lambda: service.verify_release(ref), DiagnosticCode.SIGNATURE_INVALID,
                  DiagnosticCode.ARTIFACT_DRIFT, DiagnosticCode.RELEASE_REJECTED)
        # SemanticDiff
        diff = service.semantic_diff(release, release)
        assert diff["classification"] == "compatible"
        # The publisher never stores an unsigned candidate.
        unsigned = signing.module.ReleasePackage.create(
            signed=signing.module.SignedRelease(release=release, envelope={}),
            dependency_lock=oac_request().dependency_lock, artifacts={})
        _rejected(lambda: publisher.publish(unsigned), DiagnosticCode.SIGNATURE_INVALID)
        # A conformance failure is reported, never silently passed.
        failing = suite.run(_flat_release())
        assert failing["status"] == "FAIL"


def _flat_release() -> Any:
    frontend = importlib.import_module("ocor_runtime.c1.compiler")
    source = SourceUnit.create(resource_id="urn:ocor:resource:a", version="1", syntax=SourceSyntax.YAML,
                               content=b"id: urn:ocor:resource:a\nfields: {}\n", source_path="a.yaml")
    request = CompilerRequest(package_id="urn:ocor:package:flat", semantic_version="1.0.0", source_commit=COMMIT,
                              compiler_version="1.0.0", mapping_version="1", release_profile="poc",
                              sources=(source,), dependency_lock=())
    return frontend.RetainedCanonicalIrBuilder().build(request)


# --------------------------------------------------------------------------- #
# Parsing paths of the conforming pipeline fail closed with a typed C1Error.
# --------------------------------------------------------------------------- #


def test_ncr_c1_parsing_paths_fail_closed() -> None:
    """Every parser of the pipeline rejects malformed or tampered input with C1Error."""
    oac = c1("oac")
    ir = c1("ir")
    parser = oac.YamlOacParser()

    def unit(content: bytes, syntax: SourceSyntax = SourceSyntax.YAML) -> SourceUnit:
        return SourceUnit.create(resource_id="urn:ocor:package:fleet", version="1.2.0", syntax=syntax,
                                 content=content, source_path="package.yaml")

    # OaC sources: duplicate keys, binary floats, non-mappings, syntax errors.
    _rejected(lambda: parser.parse(unit(b"a: 1\na: 2\n")), DiagnosticCode.SOURCE_INVALID)
    _rejected(lambda: parser.parse(unit(b"a: 1.5\n")), DiagnosticCode.TYPE_ERROR)
    _rejected(lambda: parser.parse(unit(b"- a\n- b\n")), DiagnosticCode.TYPE_ERROR)
    _rejected(lambda: parser.parse(unit(b"a: [1,\n")), DiagnosticCode.SOURCE_INVALID)
    _rejected(lambda: parser.parse(unit(b'{"a": 1, "a": 2}', SourceSyntax.JSON)), DiagnosticCode.SOURCE_INVALID)
    _rejected(lambda: parser.parse(unit(b"a: 2026-10-31T10:00:00\n")), DiagnosticCode.TYPE_ERROR)
    for bad in ("1e3", "01.5", "1.", " 1.5"):
        _rejected(lambda bad=bad: oac.canonical_decimal(bad, "d"), DiagnosticCode.TYPE_ERROR)
    for bad in ("2026-10-31T10:00:00", "2026-13-31T10:00:00Z", "yesterday"):
        _rejected(lambda bad=bad: oac.canonical_timestamp(bad, "t"), DiagnosticCode.TYPE_ERROR)
    for bad in ("list<varchar>", "map<integer,string>", "geo:sphere", "quantity:", "ref:not-a-urn"):
        _rejected(lambda bad=bad: oac.parse_value_type(bad, "v"), DiagnosticCode.TYPE_ERROR)

    # IR Protobuf form: truncated, tampered and foreign encodings.
    release = compiler().build(oac_request())
    encoded = ir.encode_protobuf(release)
    _rejected(lambda: ir.decode_protobuf(encoded[:-3]), DiagnosticCode.SOURCE_INVALID)
    tampered = encoded.replace(b"urn:ocor:type:vessel", b"urn:ocor:type:vassel", 1)
    _rejected(lambda: ir.decode_protobuf(tampered), DiagnosticCode.SIGNATURE_INVALID)
    _rejected(lambda: ir.decode_protobuf(b"\x0f"), DiagnosticCode.SOURCE_INVALID)
    _rejected(lambda: ir.parse_core(b'{"b":1, "a":2}'), DiagnosticCode.SOURCE_INVALID)
    _rejected(lambda: ir.parse_core(b"not json"), DiagnosticCode.SOURCE_INVALID)

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        signing = _Signing(workdir)
        package = _package(signing, oac_request())
        # Envelope: non-base64 payload and signature are signature failures.
        for mutate in (lambda e: e.__setitem__("payload", "%%%"),
                       lambda e: e["signatures"][0].__setitem__("sig", "%%%")):
            env = copy.deepcopy(dict(package.signed.envelope))
            mutate(env)
            forged = signing.module.ReleasePackage.create(
                signed=signing.module.SignedRelease(release=package.signed.release, envelope=env),
                dependency_lock=package.dependency_lock, artifacts=package.artifacts)
            _rejected(lambda forged=forged: signing.admission().verify(forged), DiagnosticCode.SIGNATURE_INVALID)
        # Stored release records: unknown reference, malformed and non-canonical records.
        publisher_module = c1("publisher")
        store = publisher_module.FileSystemReleaseStore(workdir / "releases")
        publisher = publisher_module.ImmutableReleasePublisher(admission=signing.admission(), store=store)
        _rejected(lambda: publisher.read("urn:sha256:" + "0" * 64), DiagnosticCode.RELEASE_REJECTED)
        _rejected(lambda: publisher.read("not-a-ref"), DiagnosticCode.RELEASE_REJECTED)
        for record in (b"not json", b'{"format":"other"}', canonical_bytes({"format": "ocor.c1.release-record/1.0"})):
            ref = store.put(record)
            _rejected(lambda ref=ref: publisher.read(ref), DiagnosticCode.RELEASE_REJECTED)
        ref = publisher.publish(package)
        assert publisher.verify(ref).ir_digest == package.signed.release.ir_digest
