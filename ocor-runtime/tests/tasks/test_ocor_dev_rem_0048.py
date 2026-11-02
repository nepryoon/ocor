"""OCOR-DEV-REM-0048: NCP-U02, the Function & Model Registry ``ocor.registry.v1``.

Unit NCP-U02 of the plan approved by NORMATIVE-CONFORMANCE-PLAN (2026-10-30). It resolves
the register entry NCR-C1-001. Every case asserts the behaviour prescribed by the
normative element it cites (file and line):

- ``ocor-runtime/docs/governance_dossier/contracts/ocor_registry.proto`` :9-37 services
  ``FunctionRegistry`` and ``ModelRegistry``, enums ``EffectClass`` and
  ``ModelOutputKind``; :38-199 the messages.
- LLD v1.1 (docs/OCOR_LLD_v1.1.md) :29 the Registry contract is ``ocor_registry.proto``,
  package ``ocor.registry.v1``; :36 digests ``urn:sha256:<64 lowercase hex>``; :39
  set-like arrays sorted and duplicate-free; :40 a received digest is recalculated and a
  mismatch fails closed.
- ADD v1.3 (ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md)
  :1370 §3.4 Function & Model Registry: exact pins, no range and no ``latest``; a
  Function computes or proposes a mutation but never commits it; a Model output stays
  Prediction, Belief or Recommendation; and the admission constraints after the proto
  (``UNSPECIFIED`` invalid, ``MODEL_INFERENCE`` for models, ``PROPOSE_MUTATION`` returns
  only a typed Change Proposal, TypedValue schema and type URL equal to the pinned
  descriptor, unsigned/revoked/out-of-release artefacts fail closed, Principal from the
  transport binding, abstention outside the validity envelope, exactly one
  ``ModelResult`` disposition).
- Requirement Register v1.1 (ocor-runtime/docs/governance_dossier/registers/
  OCOR_Requirement_Register_v1.1_APPROVED.md): FR-058 (:181) a Function without the
  mandatory metadata is not published; NFR-025 (:182) sandbox, timeout and CPU, memory
  and output quotas, every overrun ends fail-safe and is audited; FR-059 (:183) a direct
  Function invocation produces no commit; FR-060 (:184) a Model output is reconstructible
  against pinned inputs and versions; FR-061 (:185) no implicit write of a prediction.

Required backend: PostgreSQL 16 of the ocor-bootstrap stack from
``OCOR_LIVE_POSTGRES_DSN`` (registry persistence); without it every case fails, never
skips. Each test uses its own disposable registry schema. C1 releases are compiled,
signed and published by the conforming C1 pipeline of NCP-U01 with a key generated for
the run; the proto parity case compiles ``ocor_registry.proto`` with grpc_tools.protoc
as an independent oracle.
Implementer: Claude Code (Anthropic), reserve implementer of the OCOR loop.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import importlib
import os
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from ocor_runtime.c1.ports import CompilerRequest, DependencyLockEntry, SourceSyntax, SourceUnit
from ocor_runtime.kernel.canonical import canonical_bytes, canonical_digest
from ocor_runtime.kernel.governed_context import GovernedContext, VerifiedGovernedContextBinding

ROOT = Path(__file__).resolve().parents[3]
PROTO = ROOT / "ocor-runtime/docs/governance_dossier/contracts/ocor_registry.proto"
PACKAGE = ROOT / "ocor-runtime/src/ocor_runtime/registry"
LOCK = "urn:sha256:" + "a" * 64
ROLES = ("jena", "terminusdb", "typedb")
TYPE_URL = "type.googleapis.com/ocor.fleet.v1.Score"
INPUT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["speed"],
                "properties": {"speed": {"type": "number"}}}
OUTPUT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["score"],
                 "properties": {"score": {"type": "number"}}}
PROPOSAL_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["change_proposal"],
                   "properties": {"change_proposal": {"type": "object"}}}
PROPOSAL_URL = "type.googleapis.com/ocor.fleet.v1.ChangeProposal"
CONTRACTS = {
    # contract_id: (kind, effect_class, input schema, output schema, risk class)
    "urn:ocor:contract:score": ("FUNCTION", "PURE", INPUT_SCHEMA, OUTPUT_SCHEMA, "R0"),
    "urn:ocor:contract:propose-speed": ("FUNCTION", "PROPOSE_MUTATION", INPUT_SCHEMA, PROPOSAL_SCHEMA, "R2"),
    "urn:ocor:contract:read-vessel": ("FUNCTION", "READ_CANONICAL", INPUT_SCHEMA, OUTPUT_SCHEMA, "R0"),
    "urn:ocor:contract:eta-model": ("MODEL_FUNCTION", "MODEL_INFERENCE", INPUT_SCHEMA, OUTPUT_SCHEMA, "R1"),
    "urn:ocor:contract:get-vessel": ("NAMED_QUERY", "READ_ONLY", INPUT_SCHEMA, OUTPUT_SCHEMA, "R0"),
}
SCORE_SOURCE = b"def invoke(value):\n    return {'score': value['speed'] * 2}\n"
PROPOSAL_SOURCE = (b"def invoke(value):\n    return {'change_proposal': {'op': 'set', 'field': 'speed',"
                   b" 'value': value['speed']}}\n")
MODEL_SOURCE = (b"def predict(value, mapping, deployment):\n"
                b"    return {'score': round(value[mapping['input']] * deployment['scale'] + deployment['bias'], 6)}\n")


def registry(name: str) -> ModuleType:
    """Import a module of the registry package; a missing module is the divergence itself."""
    return importlib.import_module(f"ocor_runtime.registry.{name}")


# --------------------------------------------------------------------------- #
# C1 release with the registry contracts (conforming pipeline of NCP-U01)
# --------------------------------------------------------------------------- #
def _contract(contract_id: str, version: str = "1.0.0") -> dict[str, Any]:
    kind, effect, input_schema, output_schema, risk = CONTRACTS[contract_id]
    return {"construct": "ContractDefinition", "contract_id": contract_id, "kind": kind,
            "input_schema": input_schema, "output_schema": output_schema, "error_model": ["SCHEMA_VIOLATION"],
            "effect_class": effect, "risk_class": risk, "policy_refs": ["urn:ocor:policy:fleet-functions"],
            "approval_refs": [], "version": version}


def _oac_request(semantic_version: str) -> CompilerRequest:
    marking = {"construct": "MarkingSchemeDefinition", "scheme_id": "urn:ocor:marking-scheme:fleet", "version": "1.0.0",
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
                       ("handling_instructions", "RESTRICTION", "UNION", "INTERSECTION"))],
               "unknown_value_behavior": "DENY", "incomparable_behavior": "DENY",
               "declassification_authority_ref": "urn:ocor:authority:declassification"}
    definitions = [
        {"construct": "TypeDefinition", "type_id": "urn:ocor:type:vessel", "kind": "OBJECT", "version": "1.0.0",
         "properties": [{"property_id": "urn:ocor:property:vessel-name", "value_type_ref": "string",
                         "cardinality": "ONE", "nullable": False, "constraint_refs": []}],
         "keys": ["urn:ocor:property:vessel-name"], "interfaces": [],
         "security_profile_ref": "urn:ocor:security-profile:restricted"},
        *(_contract(contract_id) for contract_id in sorted(CONTRACTS)),
        marking,
        {"construct": "SecurityProfileDefinition", "security_profile_id": "urn:ocor:security-profile:restricted",
         "marking_scheme_ref": "urn:ocor:marking-scheme:fleet", "default_marking": "RESTRICTED"},
        *({"construct": "CapabilityDisposition", "semantic_capability_id": "value-family:primitive",
           "adapter_role": role, "disposition": "exact", "limitation": None,
           "evidence_ref": "urn:ocor:evidence:fixture"} for role in ROLES),
    ]
    documents = {
        "package.yaml": {"construct": "OntologyPackage", "package_id": "urn:ocor:package:fleet",
                         "version": semantic_version, "namespace_refs": ["urn:ocor:namespace:fleet"],
                         "module_refs": ["urn:ocor:module:fleet-core"],
                         "dependency_lock": [{"resource_id": "urn:ocor:module:shared-units", "version": "1.0.0",
                                              "sha256": LOCK}],
                         "owner": "urn:ocor:owner:fleet-team", "classification_marking": "RESTRICTED",
                         "release_profile": "poc", "adapter_roles": list(ROLES),
                         "artifact_targets": ["json-schema", "openapi", "protobuf"]},
        "namespace.yaml": {"construct": "Namespace", "namespace_id": "urn:ocor:namespace:fleet",
                           "uri": "https://ocor.example/ns/fleet#", "prefix": "fleet",
                           "ownership_boundary": "urn:ocor:owner:fleet-team", "default_marking": "RESTRICTED"},
        "module.yaml": {"construct": "Module", "module_id": "urn:ocor:module:fleet-core", "version": semantic_version,
                        "namespace_ref": "urn:ocor:namespace:fleet", "imports": ["urn:ocor:module:shared-units"],
                        "exports": ["urn:ocor:type:vessel"], "definitions": definitions,
                        "owner": "urn:ocor:owner:fleet-team", "steward": "urn:ocor:owner:fleet-steward",
                        "reviewer": "urn:ocor:owner:fleet-reviewer", "status": "APPROVED",
                        "review_date": "2026-11-02"},
    }
    ids = {"package.yaml": "urn:ocor:package:fleet", "namespace.yaml": "urn:ocor:namespace:fleet",
           "module.yaml": "urn:ocor:module:fleet-core"}
    sources = tuple(
        SourceUnit.create(resource_id=ids[path], version=str(document.get("version", semantic_version)),
                          syntax=SourceSyntax.YAML,
                          content=yaml.safe_dump(document, sort_keys=True).encode("utf-8"), source_path=path,
                          imports=("urn:ocor:module:shared-units",) if path == "module.yaml" else ())
        for path, document in documents.items())
    return CompilerRequest(package_id="urn:ocor:package:fleet", semantic_version=semantic_version,
                           source_commit="0123456789abcdef0123456789abcdef01234567", compiler_version="1.0.0",
                           mapping_version="1", release_profile="poc", sources=sources,
                           dependency_lock=(DependencyLockEntry("urn:ocor:module:shared-units", "1.0.0", LOCK),))


class Keys:
    """A trusted Ed25519 key for C1 releases and registry statements, and an untrusted one."""

    def __init__(self) -> None:
        signing = importlib.import_module("ocor_runtime.c1.signing")
        self.signing = signing
        self.key = signing.Ed25519SigningKey.from_seed(os.urandom(32))
        self.rogue = signing.Ed25519SigningKey.from_seed(os.urandom(32))
        self.keyid = "urn:ocor:key:registry-test"
        self.chain = "urn:sha256:" + hashlib.sha256(b"registry-test-chain").hexdigest()

    def trust_root(self, *, revoked: frozenset[str] = frozenset()) -> Any:
        return self.signing.TrustRoot(
            keys={self.keyid: self.signing.TrustedKey(public_key=self.key.public_key,
                                                      certificate_chain_ref=self.chain,
                                                      signing_profile=self.signing.ED25519_PROFILE)},
            revoked_keyids=revoked)

    def sign(self, payload_type: str, statement: dict[str, Any], *, rogue: bool = False) -> bytes:
        result: bytes = registry("service").sign_statement(
            key=self.rogue if rogue else self.key, keyid=self.keyid, certificate_chain_ref=self.chain,
            payload_type=payload_type, statement=statement)
        return result


class Release:
    """A published, admitted C1 release and its publisher (``ReleaseCatalog``)."""

    def __init__(self, keys: Keys, workdir: Path, semantic_version: str = "1.0.0") -> None:
        ir = importlib.import_module("ocor_runtime.c1.ir")
        codegen = importlib.import_module("ocor_runtime.c1.codegen")
        publisher = importlib.import_module("ocor_runtime.c1.publisher")
        signing = keys.signing
        request = _oac_request(semantic_version)
        release = ir.OacCompiler().build(request)
        generator = codegen.IrArtifactGenerator()
        files = generator.render(release)
        release = release.with_artifacts(generator.generate(release))
        signer = signing.DsseIrSigner(key=keys.key, keyid=keys.keyid, certificate_chain_ref=keys.chain)
        package = signing.ReleasePackage.create(signed=signer.sign_release(release),
                                                dependency_lock=request.dependency_lock, artifacts=files)
        admission = signing.ReleaseAdmission(trust_root=keys.trust_root(), accepted_compiler_versions=("1.0.0",))
        self.publisher = publisher.ImmutableReleasePublisher(
            admission=admission, store=publisher.FileSystemReleaseStore(workdir / "releases"))
        self.ref: str = self.publisher.publish(package)
        self.ir_digest: str = package.signed.release.ir_digest
        self.contracts = {c["contract_id"]: dict(c) for c in package.signed.release.core["named_contracts"]}

    def contract_digest(self, contract_id: str) -> str:
        return canonical_digest(_thaw(self.contracts[contract_id]))


def _thaw(value: Any) -> Any:
    if isinstance(value, dict) or hasattr(value, "items"):
        return {str(k): _thaw(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_thaw(v) for v in value]
    return value


# --------------------------------------------------------------------------- #
# Registry fixture on the live PostgreSQL
# --------------------------------------------------------------------------- #
def _dsn() -> str:
    dsn = os.environ.get("OCOR_LIVE_POSTGRES_DSN")
    if not dsn:
        pytest.fail("OCOR_LIVE_POSTGRES_DSN is mandatory qualifying evidence (real PostgreSQL)")
    return dsn


class World:
    def __init__(self, workdir: Path) -> None:
        self.c = registry("contract")
        self.svc = registry("service")
        self.sandbox_module = registry("sandbox")
        self.store = registry("adapters.postgres").PostgresRegistryStore(
            _dsn(), schema="rem0048_" + uuid.uuid4().hex[:16])
        self.store.initialize()
        self.keys = Keys()
        self.release = Release(self.keys, workdir)
        self.functions = self.function_registry()
        self.models = self.model_registry()
        self.context, self.binding = self.governed(self.release.ir_digest)

    def function_registry(self, *, revoked: frozenset[str] = frozenset()) -> Any:
        return self.svc.FunctionRegistry(store=self.store, releases=self.release.publisher,
                                         trust_root=self.keys.trust_root(revoked=revoked),
                                         sandbox=self.sandbox_module.PythonSandbox())

    def model_registry(self, *, revoked: frozenset[str] = frozenset()) -> Any:
        return self.svc.ModelRegistry(store=self.store, releases=self.release.publisher,
                                      trust_root=self.keys.trust_root(revoked=revoked),
                                      sandbox=self.sandbox_module.PythonSandbox(), budget=self.budget())

    def budget(self, *, timeout: float = 20.0, cpu_millis: int = 5000, memory_bytes: int = 512 << 20,
               output_bytes: int = 4096) -> Any:
        return self.c.ResourceBudget(timeout=timedelta(seconds=timeout), cpu_millis=cpu_millis,
                                     memory_bytes=memory_bytes, output_bytes=output_bytes)

    def governed(self, release_digest: str, **changes: Any) -> tuple[Any, VerifiedGovernedContextBinding]:
        expected = GovernedContext(
            tenant_id="tenant-a", organization_id="org-a", domain_id="fleet", compartments=("alpha",),
            classification_marking_ref="urn:sha256:" + "c" * 64, purpose="planning",
            effective_principal_id="spiffe://ocor.local/agent/a", actor_chain=("spiffe://ocor.local/agent/a",),
            ontology_release_digest=release_digest, policy_bundle_digest="urn:sha256:" + "d" * 64,
            correlation_id="0b1a6a2e-4bb8-4c4e-9a59-7c2f0d3a1e01")
        binding = VerifiedGovernedContextBinding(binding_ref="urn:ocor:binding:test", expected=expected)
        context = self.c.InvocationContext(
            request_id="req-1", tenant_id=expected.tenant_id, domain_id=expected.domain_id,
            compartments=expected.compartments, purpose=expected.purpose,
            ontology_release_digest=expected.ontology_release_digest, logic_version="1.0.0", branch="main",
            scenario_id=None, correlation_id=expected.correlation_id, causation_id=None, delegation_ref=None,
            classification_marking_ref=expected.classification_marking_ref,
            organization_id=expected.organization_id, policy_bundle_digest=expected.policy_bundle_digest,
            governed_context_digest=expected.digest())
        return dataclasses.replace(context, **changes), binding

    # -- descriptors --------------------------------------------------------------------
    def schema_pin(self, schema: dict[str, Any], type_url: str = TYPE_URL, schema_id: str = "urn:ocor:schema:speed"
                   ) -> Any:
        return self.c.SchemaPin(schema_id=schema_id, semantic_version="1.0.0", schema_digest=canonical_digest(schema),
                                protobuf_type_url=type_url)

    def pin(self, contract_id: str, artifact_digest: str) -> Any:
        return self.c.VersionPin(resource_id=contract_id, semantic_version="1.0.0", artifact_digest=artifact_digest,
                                 contract_digest=self.release.contract_digest(contract_id))

    def artifact_signature(self, pin: Any, *, rogue: bool = False) -> str:
        statement = {"artifact_digest": pin.artifact_digest, "resource_id": pin.resource_id,
                     "semantic_version": pin.semantic_version}
        digest: str = self.store.put_artifact(self.keys.sign(self.svc.ARTIFACT_PAYLOAD_TYPE, statement, rogue=rogue))
        return digest

    def function(self, contract_id: str = "urn:ocor:contract:score", source: bytes = SCORE_SOURCE,
                 budget: Any = None, **changes: Any) -> Any:
        digest = self.store.put_artifact(source)
        pin = self.pin(contract_id, digest)
        output = PROPOSAL_SCHEMA if contract_id == "urn:ocor:contract:propose-speed" else OUTPUT_SCHEMA
        output_url = PROPOSAL_URL if contract_id == "urn:ocor:contract:propose-speed" else TYPE_URL
        descriptor = self.c.FunctionDescriptor(
            pin=pin, input_schema=self.schema_pin(INPUT_SCHEMA),
            output_schema=self.schema_pin(output, output_url, "urn:ocor:schema:output"), dependencies=(),
            effect_class=self.c.EffectClass[CONTRACTS[contract_id][1]], deterministic=True,
            execution_owner="urn:ocor:owner:fleet-team", budget=budget or self.budget(),
            policy_refs=("urn:ocor:policy:fleet-functions",), artifact_signature_ref=self.artifact_signature(pin),
            provenance_ref="urn:ocor:provenance:build-1")
        return dataclasses.replace(descriptor, **changes)

    def manifest(self, kind: str, descriptor: Any, *, release_ref: str | None = None, rogue: bool = False,
                 proposal: str = "urn:ocor:change-proposal:cp-1", **extra: Any) -> str:
        statement = {"kind": kind, "descriptor_digest": self.c.message_digest(descriptor),
                     "release_ref": release_ref or self.release.ref, "change_proposal_ref": proposal} | extra
        digest: str = self.store.put_artifact(self.keys.sign(self.svc.MANIFEST_PAYLOAD_TYPE, statement, rogue=rogue))
        return digest

    def publish_function(self, descriptor: Any, **manifest: Any) -> Any:
        request = self.c.PublishFunctionRequest(descriptor=descriptor,
                                                signed_manifest_ref=self.manifest("FUNCTION", descriptor, **manifest),
                                                change_proposal_ref="urn:ocor:change-proposal:cp-1")
        return self.functions.PublishFunction(request)

    def typed(self, value: Any, schema: dict[str, Any] = INPUT_SCHEMA, type_url: str = TYPE_URL) -> Any:
        return self.c.TypedValue(schema=self.schema_pin(schema, type_url),
                                 value=self.c.AnyValue(type_url=type_url, value=canonical_bytes(value)))

    def invoke(self, descriptor: Any, value: Any, *, key: str = "idem-1", context: Any = None,
               typed: Any = None) -> Any:
        request = self.c.InvokeFunctionRequest(function_pin=descriptor.pin, context=context or self.context,
                                               input=typed or self.typed(value), idempotency_key=key)
        return self.functions.InvokeFunction(request, binding=self.binding)

    # -- models ---------------------------------------------------------------------
    def model(self, *, envelope: dict[str, Any] | None = None, source: bytes = MODEL_SOURCE,
              deployment: dict[str, Any] | None = None, **changes: Any) -> Any:
        model_digest = self.store.put_artifact(source)
        deployment_digest = self.store.put_artifact(canonical_bytes(
            deployment or {"entrypoint": "predict", "scale": 1.5, "bias": 0.25}))
        mapping_digest = self.store.put_artifact(canonical_bytes({"input": "speed"}))
        envelope_digest = self.store.put_artifact(canonical_bytes(envelope or {
            "envelope_version": "1.0.0",
            "conditions": [{"condition_id": "speed-range", "field": "speed", "minimum": 0, "maximum": 40}]}))
        model_pin = self.pin("urn:ocor:contract:eta-model", model_digest)
        deployment_pin = self.c.VersionPin(resource_id="urn:ocor:deployment:eta", semantic_version="1.0.0",
                                           artifact_digest=deployment_digest,
                                           contract_digest=model_pin.contract_digest)
        mapping_pin = self.c.VersionPin(resource_id="urn:ocor:mapping:eta", semantic_version="1.0.0",
                                        artifact_digest=mapping_digest, contract_digest=model_pin.contract_digest)
        descriptor = self.c.ModelDescriptor(
            model_pin=model_pin, deployment_pin=deployment_pin, mapping_pin=mapping_pin,
            input_schema=self.schema_pin(INPUT_SCHEMA),
            output_schema=self.schema_pin(OUTPUT_SCHEMA, TYPE_URL, "urn:ocor:schema:output"),
            effect_class=self.c.EffectClass.MODEL_INFERENCE, validity_envelope_ref=envelope_digest,
            training_lineage_ref="urn:ocor:lineage:eta-train-1", owner_principal_ref="urn:ocor:owner:fleet-team",
            risk_class="R1", approval_status="APPROVED_BY_MODEL_BOARD",
            artifact_signature_ref=self.artifact_signature(model_pin))
        return dataclasses.replace(descriptor, **changes)

    def publish_model(self, descriptor: Any, output_kind: str | None = "PREDICTION", **manifest: Any) -> Any:
        extra = {} if output_kind is None else {"output_kind": output_kind}
        request = self.c.PublishModelRequest(
            descriptor=descriptor, signed_manifest_ref=self.manifest("MODEL", descriptor, **manifest, **extra),
            change_proposal_ref="urn:ocor:change-proposal:cp-1")
        return self.models.PublishModel(request)

    def invoke_model(self, descriptor: Any, value: Any, *, input_digest: str | None = None) -> Any:
        request = self.c.InvokeModelRequest(
            model_pin=descriptor.model_pin, deployment_pin=descriptor.deployment_pin,
            mapping_pin=descriptor.mapping_pin, context=self.context, input=self.typed(value),
            input_digest=input_digest or canonical_digest(value))
        return self.models.InvokeModel(request, binding=self.binding)

    def rejected(self, call: Callable[[], object], reason: str) -> Any:
        with pytest.raises(self.c.RegistryError) as caught:
            call()
        assert caught.value.reason_code == reason, caught.value
        return caught.value


@pytest.fixture
def world() -> Iterator[World]:
    with tempfile.TemporaryDirectory(prefix="rem0048-") as workdir:
        state = World(Path(workdir))
        try:
            yield state
        finally:
            state.store.drop()


def _decode(output: Any) -> Any:
    import json

    return json.loads(output.value.value)


# --------------------------------------------------------------------------- #
# NCR-C1-001: the registry exists and realises the contract end to end
# --------------------------------------------------------------------------- #
def test_ncr_c1_001_conforms(world: World) -> None:
    """proto :9-19 the six operations; ADD v1.3 :1370 exact pins; FR-058, FR-060 (Register :181, :184)."""
    descriptor = world.function()
    receipt = world.publish_function(descriptor)
    assert receipt.descriptor_digest == world.c.message_digest(descriptor)
    assert receipt.registry_commit.startswith("urn:sha256:") and receipt.audit_ref.startswith("urn:sha256:")
    resolved = world.functions.ResolveFunction(
        world.c.ResolveFunctionRequest(pin=descriptor.pin, context=world.context), binding=world.binding)
    assert resolved == descriptor
    result = world.invoke(descriptor, {"speed": 10})
    assert _decode(result.output) == {"score": 20}
    assert result.effect_class is world.c.EffectClass.PURE
    assert result.output.schema == descriptor.output_schema and result.output.value.type_url == TYPE_URL
    assert result.classification_marking_ref == world.context.classification_marking_ref
    assert result.result_digest.startswith("urn:sha256:") and result.provenance_ref.startswith("urn:sha256:")

    model = world.model()
    world.publish_model(model)
    resolved_model = world.models.ResolveModel(
        world.c.ResolveModelRequest(model_pin=model.model_pin, deployment_pin=model.deployment_pin,
                                    mapping_pin=model.mapping_pin, context=world.context), binding=world.binding)
    assert resolved_model == model
    outcome = world.invoke_model(model, {"speed": 10})
    assert outcome.output_kind is world.c.ModelOutputKind.PREDICTION
    assert outcome.abstention is None and _decode(outcome.output) == {"score": 15.25}
    assert outcome.validity == world.c.ValidityAssessment(True, "1.0.0", ())
    rebuilt = world.models.ReconstructModelInvocation(outcome.invocation_id)
    assert rebuilt == outcome


def test_contract_mirrors_ocor_registry_proto() -> None:
    """LLD v1.1 :29: the Registry contract is ocor_registry.proto, package ocor.registry.v1 (proto :1-199)."""
    contract = registry("contract")
    service = registry("service")
    from google.protobuf import descriptor_pb2
    import grpc_tools

    include = Path(grpc_tools.__file__).resolve().parent / "_proto"
    with tempfile.TemporaryDirectory() as directory:
        out = Path(directory) / "set.pb"
        subprocess.run([sys.executable, "-m", "grpc_tools.protoc", f"-I{PROTO.parent}", f"-I{include}",
                        f"--descriptor_set_out={out}", str(PROTO)], check=True, capture_output=True)
        file_set = descriptor_pb2.FileDescriptorSet.FromString(out.read_bytes())
    (proto,) = [f for f in file_set.file if f.name == "ocor_registry.proto"]
    assert proto.package == "ocor.registry.v1"
    for enum in proto.enum_type:
        python_enum = getattr(contract, enum.name)
        assert [(v.name, v.number) for v in enum.value] == [(m.name, m.value) for m in python_enum]
    names = {message.name for message in proto.message_type}
    assert names == {cls.__name__ for cls in contract.MESSAGES}
    for message in proto.message_type:
        cls = getattr(contract, message.name)
        ordered = [f.name for f in sorted(message.field, key=lambda f: f.number)]
        assert ordered == [f.name for f in dataclasses.fields(cls)], message.name
    for svc in proto.service:
        methods = [m.name for m in svc.method]
        assert all(callable(getattr(getattr(service, svc.name), m)) for m in methods), svc.name
    assert {s.name: [m.name for m in s.method] for s in proto.service} == {
        "FunctionRegistry": ["PublishFunction", "ResolveFunction", "InvokeFunction"],
        "ModelRegistry": ["PublishModel", "ResolveModel", "InvokeModel"]}


# --------------------------------------------------------------------------- #
# FR-058: mandatory Function metadata
# --------------------------------------------------------------------------- #
MISSING_METADATA = [
    ("pin", None),
    ("input_schema", None),
    ("output_schema", None),
    ("effect_class", "EFFECT_CLASS_UNSPECIFIED"),
    ("effect_class", "MODEL_INFERENCE"),
    ("deterministic", None),
    ("execution_owner", ""),
    ("budget", None),
    ("budget.timeout", timedelta(0)),
    ("budget.cpu_millis", 0),
    ("budget.memory_bytes", 0),
    ("budget.output_bytes", -1),
    ("policy_refs", ("urn:ocor:policy:b", "urn:ocor:policy:a")),
    ("artifact_signature_ref", ""),
    ("provenance_ref", ""),
    ("dependencies", None),
]


@pytest.mark.parametrize(("field", "value"), MISSING_METADATA, ids=[f"{f}={v!r}" for f, v in MISSING_METADATA])
def test_fr_058_function_without_mandatory_metadata_is_not_published(world: World, field: str, value: Any) -> None:
    """FR-058 (Register :181): firme input/output, dipendenze, versione, determinismo, classe d'effetto."""
    descriptor = world.function()
    if field == "effect_class":
        value = world.c.EffectClass[value]
    if field.startswith("budget."):
        descriptor = dataclasses.replace(descriptor, budget=dataclasses.replace(
            descriptor.budget, **{field.split(".")[1]: value}))
    else:
        descriptor = dataclasses.replace(descriptor, **{field: value})
    request = world.c.PublishFunctionRequest(descriptor=descriptor, signed_manifest_ref="urn:sha256:" + "e" * 64,
                                             change_proposal_ref="urn:ocor:change-proposal:cp-1")
    world.rejected(lambda: world.functions.PublishFunction(request), "SCHEMA_VIOLATION")
    assert world.store.entry_chain() == []


def test_fr_058_complete_function_with_published_dependency_is_published(world: World) -> None:
    """FR-058: the dependencies are exact pins of published Functions; an unpublished one is not admitted."""
    dependency = world.function()
    world.publish_function(dependency)
    dependent = world.function(source=SCORE_SOURCE + b"# v2\n", dependencies=(dependency.pin,))
    receipt = world.publish_function(dependent)
    assert receipt.descriptor_digest == world.c.message_digest(dependent)
    unknown = dataclasses.replace(dependency.pin, artifact_digest="urn:sha256:" + "9" * 64)
    orphan = world.function(source=SCORE_SOURCE + b"# v3\n", dependencies=(unknown,))
    world.rejected(lambda: world.publish_function(orphan), "CONTRACT_DIGEST_MISMATCH")
    chain = world.store.entry_chain()
    assert len(chain) == 2 and chain[1]["previous_commit"] == chain[0]["registry_commit"]


# --------------------------------------------------------------------------- #
# ADD v1.3 §3.4: exact pins, no range, no latest
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("version", ["^1.0.0", "1.x", "latest", ">=1.0.0", "1.0", "", "~1.0.0"])
def test_version_ranges_and_latest_are_rejected(world: World, version: str) -> None:
    """ADD v1.3 :1372: range di versione e risoluzione latest sono vietati nel runtime."""
    descriptor = world.function()
    world.publish_function(descriptor)
    pin = dataclasses.replace(descriptor.pin, semantic_version=version)
    world.rejected(lambda: world.functions.ResolveFunction(
        world.c.ResolveFunctionRequest(pin=pin, context=world.context), binding=world.binding), "SCHEMA_VIOLATION")
    world.rejected(lambda: world.invoke(dataclasses.replace(descriptor, pin=pin), {"speed": 1}), "SCHEMA_VIOLATION")


def test_resolution_is_exact_on_every_pin_field(world: World) -> None:
    """ADD v1.3 :1372 pin (resource_id, semantic_version, artifact_digest, contract_digest)."""
    descriptor = world.function()
    world.publish_function(descriptor)

    def resolve(pin: Any) -> Any:
        return world.functions.ResolveFunction(world.c.ResolveFunctionRequest(pin=pin, context=world.context),
                                               binding=world.binding)

    other = "urn:sha256:" + "7" * 64
    world.rejected(lambda: resolve(dataclasses.replace(descriptor.pin, artifact_digest=other)),
                   "CONTRACT_DIGEST_MISMATCH")
    world.rejected(lambda: resolve(dataclasses.replace(descriptor.pin, contract_digest=other)),
                   "CONTRACT_DIGEST_MISMATCH")
    world.rejected(lambda: resolve(dataclasses.replace(descriptor.pin, semantic_version="1.0.1")),
                   "CONTRACT_NOT_FOUND")
    world.rejected(lambda: resolve(dataclasses.replace(descriptor.pin, resource_id="urn:ocor:contract:other")),
                   "CONTRACT_NOT_FOUND")
    world.rejected(lambda: resolve(dataclasses.replace(descriptor.pin, artifact_digest="sha256:" + "7" * 64)),
                   "SCHEMA_VIOLATION")
    assert resolve(descriptor.pin) == descriptor


# --------------------------------------------------------------------------- #
# ADD v1.3 §3.4: unsigned, revoked or out-of-release artefacts fail closed
# --------------------------------------------------------------------------- #
def test_unsigned_or_out_of_release_publication_fails_closed(world: World) -> None:
    """ADD v1.3 §3.4: artifact, deployment o mapping non firmati, revocati o fuori release: fail-closed."""
    descriptor = world.function()
    world.rejected(lambda: world.publish_function(descriptor, rogue=True), "CONTRACT_REJECTED")
    forged = dataclasses.replace(descriptor, artifact_signature_ref=world.artifact_signature(descriptor.pin,
                                                                                            rogue=True))
    world.rejected(lambda: world.publish_function(forged), "CONTRACT_REJECTED")
    other_artifact = world.function(source=SCORE_SOURCE + b"# other\n")
    swapped = dataclasses.replace(descriptor, artifact_signature_ref=other_artifact.artifact_signature_ref)
    world.rejected(lambda: world.publish_function(swapped), "CONTRACT_REJECTED")
    world.rejected(lambda: world.publish_function(descriptor, proposal="urn:ocor:change-proposal:cp-2"),
                   "CONTRACT_REJECTED")
    world.rejected(lambda: world.publish_function(descriptor, release_ref="urn:sha256:" + "4" * 64),
                   "CONTRACT_REJECTED")
    outside = dataclasses.replace(descriptor, pin=dataclasses.replace(descriptor.pin,
                                                                      resource_id="urn:ocor:contract:absent"))
    outside = dataclasses.replace(outside, artifact_signature_ref=world.artifact_signature(outside.pin))
    world.rejected(lambda: world.publish_function(outside), "CONTRACT_REJECTED")
    query = world.function(contract_id="urn:ocor:contract:get-vessel", effect_class=world.c.EffectClass.PURE)
    world.rejected(lambda: world.publish_function(query), "CONTRACT_REJECTED")
    wrong_digest = dataclasses.replace(descriptor, pin=dataclasses.replace(
        descriptor.pin, contract_digest=world.release.contract_digest("urn:ocor:contract:propose-speed")))
    wrong_digest = dataclasses.replace(wrong_digest, artifact_signature_ref=world.artifact_signature(wrong_digest.pin))
    world.rejected(lambda: world.publish_function(wrong_digest), "CONTRACT_DIGEST_MISMATCH")
    wrong_effect = dataclasses.replace(descriptor, effect_class=world.c.EffectClass.READ_EXTERNAL)
    world.rejected(lambda: world.publish_function(wrong_effect), "CONTRACT_REJECTED")
    wrong_schema = dataclasses.replace(descriptor, input_schema=world.schema_pin(OUTPUT_SCHEMA))
    world.rejected(lambda: world.publish_function(wrong_schema), "CONTRACT_DIGEST_MISMATCH")
    wrong_policy = dataclasses.replace(descriptor, policy_refs=("urn:ocor:policy:other",))
    world.rejected(lambda: world.publish_function(wrong_policy), "CONTRACT_REJECTED")
    missing_artifact = dataclasses.replace(descriptor, pin=dataclasses.replace(
        descriptor.pin, artifact_digest="urn:sha256:" + hashlib.sha256(b"never stored").hexdigest()))
    missing_artifact = dataclasses.replace(missing_artifact,
                                           artifact_signature_ref=world.artifact_signature(missing_artifact.pin))
    world.rejected(lambda: world.publish_function(missing_artifact), "CONTRACT_REJECTED")
    assert world.store.entry_chain() == []
    assert world.publish_function(descriptor).descriptor_digest == world.c.message_digest(descriptor)


def test_revoked_artifact_or_key_fails_closed_after_publication(world: World) -> None:
    """ADD v1.3 §3.4: revocati -> fail-closed, on resolve and invoke, for Functions and Models."""
    descriptor = world.function()
    world.publish_function(descriptor)
    model = world.model()
    world.publish_model(model)
    assert world.invoke(descriptor, {"speed": 1}).output is not None
    revoked_registry = world.function_registry(revoked=frozenset({world.keys.keyid}))
    world.rejected(lambda: revoked_registry.ResolveFunction(
        world.c.ResolveFunctionRequest(pin=descriptor.pin, context=world.context), binding=world.binding),
        "CONTRACT_REJECTED")
    world.store.revoke(descriptor.pin.artifact_digest, reason="compromised build",
                       change_proposal_ref="urn:ocor:change-proposal:cp-9")
    world.rejected(lambda: world.invoke(descriptor, {"speed": 1}, key="idem-2"), "CONTRACT_REJECTED")
    world.rejected(lambda: world.functions.ResolveFunction(
        world.c.ResolveFunctionRequest(pin=descriptor.pin, context=world.context), binding=world.binding),
        "CONTRACT_REJECTED")
    world.store.revoke(model.mapping_pin.artifact_digest, reason="bad mapping",
                       change_proposal_ref="urn:ocor:change-proposal:cp-9")
    world.rejected(lambda: world.invoke_model(model, {"speed": 1}), "CONTRACT_REJECTED")
    assert {row["event"] for row in world.store.audit_chain()} >= {"ARTIFACT_REVOKED"}


def test_registry_tables_are_append_only(world: World) -> None:
    """Append-only, hash-linked registry and audit (ADD v1.3 §3.4 signing/lineage; NFR-025 audit)."""
    import psycopg

    world.publish_function(world.function())
    with psycopg.connect(_dsn()) as connection:
        for statement in (f"UPDATE {world.store.schema}.registry_entry SET record = '{{}}'::jsonb",
                          f"DELETE FROM {world.store.schema}.registry_audit"):
            with pytest.raises(psycopg.errors.RaiseException):
                connection.execute(statement)
            connection.rollback()
    audit = world.store.audit_chain()
    previous = "urn:sha256:" + "0" * 64
    for row in audit:
        assert row["previous_hash"] == previous
        assert row["audit_hash"] == canonical_digest({"previous_hash": previous, "event": row["event"],
                                                      "detail": row["detail"]})
        previous = row["audit_hash"]


# --------------------------------------------------------------------------- #
# InvocationContext against the verified binding; TypedValue against the pin
# --------------------------------------------------------------------------- #
def test_invocation_context_is_validated_against_the_binding(world: World) -> None:
    """ADD v1.3 §3.4 and :381: Principal from transport; the other GCS fields validated (DENY otherwise)."""
    descriptor = world.function()
    world.publish_function(descriptor)
    for change in ({"tenant_id": "tenant-b"}, {"compartments": ("alpha", "beta")}, {"purpose": "export"},
                   {"governed_context_digest": "urn:sha256:" + "1" * 64}, {"organization_id": "org-b"}):
        context = dataclasses.replace(world.context, **change)
        world.rejected(lambda c=context: world.invoke(descriptor, {"speed": 1}, context=c),
                       "GOVERNED_CONTEXT_MISMATCH")
    for change in ({"request_id": ""}, {"branch": ""}, {"logic_version": ""}, {"scenario_id": ""}):
        context = dataclasses.replace(world.context, **change)
        world.rejected(lambda c=context: world.invoke(descriptor, {"speed": 1}, context=c), "SCHEMA_VIOLATION")
    other_release = "urn:sha256:" + "5" * 64
    context, binding = world.governed(other_release)
    world.rejected(lambda: world.functions.InvokeFunction(
        world.c.InvokeFunctionRequest(function_pin=descriptor.pin, context=context,
                                      input=world.typed({"speed": 1}), idempotency_key="idem-r"),
        binding=binding), "RELEASE_MISMATCH")
    world.rejected(lambda: world.functions.InvokeFunction(
        world.c.InvokeFunctionRequest(function_pin=descriptor.pin, context=world.context,
                                      input=world.typed({"speed": 1}), idempotency_key="idem-r"),
        binding=None), "GOVERNED_CONTEXT_MISMATCH")


def test_typed_value_must_match_the_pinned_schema(world: World) -> None:
    """ADD v1.3 §3.4: TypedValue.schema.protobuf_type_url e digest coincidono con il descriptor pin-nato."""
    descriptor = world.function()
    world.publish_function(descriptor)
    good = world.typed({"speed": 3})
    cases = [
        world.typed({"speed": 3}, type_url="type.googleapis.com/ocor.fleet.v1.Other"),
        world.typed({"speed": 3}, schema=OUTPUT_SCHEMA),
        dataclasses.replace(good, value=world.c.AnyValue(type_url="type.googleapis.com/x.Y",
                                                         value=good.value.value)),
        dataclasses.replace(good, value=world.c.AnyValue(type_url=TYPE_URL, value=b"{not json")),
        dataclasses.replace(good, value=world.c.AnyValue(type_url=TYPE_URL, value=b'{"speed":"fast"}')),
        dataclasses.replace(good, value=world.c.AnyValue(type_url=TYPE_URL, value=b'{"speed":1,"x":2}')),
        dataclasses.replace(good, value=None),
        None,
    ]
    for index, typed in enumerate(cases):
        request = world.c.InvokeFunctionRequest(function_pin=descriptor.pin, context=world.context, input=typed,
                                                idempotency_key=f"idem-t{index}")
        world.rejected(lambda r=request: world.functions.InvokeFunction(r, binding=world.binding),
                       "SCHEMA_VIOLATION")
    bad_output = world.function(source=b"def invoke(value):\n    return {'score': 'high'}\n")
    world.publish_function(bad_output)
    world.rejected(lambda: world.invoke(bad_output, {"speed": 3}), "SCHEMA_VIOLATION")


# --------------------------------------------------------------------------- #
# NFR-025: sandbox, timeout and quotas; overruns fail-safe and audited
# --------------------------------------------------------------------------- #
OVERRUNS = [
    ("TIMEOUT", b"def invoke(value):\n    while True:\n        pass\n", {"timeout": 0.5, "cpu_millis": 60000}),
    ("CPU", b"def invoke(value):\n    while True:\n        pass\n", {"timeout": 30.0, "cpu_millis": 300}),
    ("MEMORY", b"def invoke(value):\n    return {'score': len(bytearray(1 << 31))}\n",
     {"memory_bytes": 256 << 20}),
    ("OUTPUT", b"def invoke(value):\n    return {'score': 1, 'pad': 'x' * 100000}\n", {"output_bytes": 256}),
    ("OUTPUT", b"def invoke(value):\n    return {'score': 1.5}\n", {"output_bytes": 8}),
]


@pytest.mark.parametrize(("kind", "source", "limits"), OVERRUNS, ids=[f"{k}-{i}" for i, (k, _, _) in
                                                                       enumerate(OVERRUNS)])
def test_nfr_025_every_overrun_ends_fail_safe_and_is_audited(world: World, kind: str, source: bytes,
                                                             limits: dict[str, Any]) -> None:
    """NFR-025 (Register :182): ogni superamento termina fail-safe e produce audit."""
    descriptor = world.function(source=source, budget=world.budget(**limits))
    world.publish_function(descriptor)
    error = world.rejected(lambda: world.invoke(descriptor, {"speed": 2}), "BUDGET_EXCEEDED")
    audit = {row["audit_hash"]: row for row in world.store.audit_chain()}
    record = audit[error.audit_ref]
    assert record["event"] == "SANDBOX_BUDGET_EXCEEDED" and record["detail"]["overrun"] == kind
    assert record["detail"]["pin"]["artifact_digest"] == descriptor.pin.artifact_digest
    assert world.store.find_invocation_by_key("FUNCTION", world.c.pin_key(descriptor.pin), "idem-1") is None


@pytest.mark.parametrize("source", [
    b"def invoke(value):\n    return {'score': len(open('/etc/hostname').read())}\n",
    b"import socket\ndef invoke(value):\n    return {'score': 1}\n",
    b"def invoke(value):\n    raise RuntimeError('boom')\n",
    b"def invoke(value):\n    import os\n    return {'score': os.getpid()}\n",
])
def test_nfr_025_sandbox_denies_files_sockets_and_imports(world: World, source: bytes) -> None:
    """NFR-025: the sandbox contains hostile code; a failure returns no output."""
    descriptor = world.function(source=source)
    world.publish_function(descriptor)
    world.rejected(lambda: world.invoke(descriptor, {"speed": 2}), "EXECUTION_FAILED")


def test_nfr_025_quotas_are_configurable_per_function(world: World) -> None:
    """NFR-025: the same artefact passes under a sufficient budget and is stopped under a smaller one."""
    source = b"def invoke(value):\n    total = 0\n    for i in range(2000000):\n        total += i\n    return {'score': 1}\n"
    ample = world.function(source=source, budget=world.budget(cpu_millis=20000))
    world.publish_function(ample)
    assert _decode(world.invoke(ample, {"speed": 1}).output) == {"score": 1}
    tight = world.function(source=source, budget=world.budget(cpu_millis=1))
    world.publish_function(tight)
    world.rejected(lambda: world.invoke(tight, {"speed": 1}), "BUDGET_EXCEEDED")


# --------------------------------------------------------------------------- #
# FR-059: computation separated from mutation
# --------------------------------------------------------------------------- #
def test_fr_059_function_invocation_never_commits(world: World) -> None:
    """FR-059 (Register :183); ADD v1.3 §3.4: PROPOSE_MUTATION returns only a typed Change Proposal."""
    descriptor = world.function(contract_id="urn:ocor:contract:propose-speed", source=PROPOSAL_SOURCE)
    world.publish_function(descriptor)
    result = world.invoke(descriptor, {"speed": 12})
    assert result.effect_class is world.c.EffectClass.PROPOSE_MUTATION
    assert result.output.value.type_url == PROPOSAL_URL
    assert _decode(result.output) == {"change_proposal": {"field": "speed", "op": "set", "value": 12}}
    assert result.served_commit == "" and result.watermark == ""
    imported = set()
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level:
                imported.add(("." * node.level) + (node.module or ""))
    assert all(name.split(".")[-1] in {"", "contract", "sandbox", "service", "postgres", "canonical",
                                       "governed_context", "ports", "signing"}
               or name in {"..kernel.canonical", "...kernel.canonical", "..c1.ports", "..c1.signing",
                           "..kernel.governed_context", "..contract"} for name in imported), imported
    assert not any(part in name for name in imported for part in ("c3", "c5", "c6", "c8", "memory"))
    reader = world.function(contract_id="urn:ocor:contract:read-vessel")
    world.publish_function(reader)
    world.rejected(lambda: world.invoke(reader, {"speed": 1}), "UNSUPPORTED_CAPABILITY")


# --------------------------------------------------------------------------- #
# FR-060 / FR-061: Model registry, lineage and dispositions
# --------------------------------------------------------------------------- #
def test_fr_060_model_output_is_reconstructible_from_pinned_inputs(world: World) -> None:
    """FR-060 (Register :184): output ricostruibile rispetto a input e versioni fissate."""
    model = world.model()
    world.publish_model(model)
    outcome = world.invoke_model(model, {"speed": 8})
    row = world.store.get_invocation(outcome.invocation_id)
    lineage = row["record"]["provenance"]
    assert lineage["model_pin"]["artifact_digest"] == model.model_pin.artifact_digest
    assert lineage["deployment_pin"]["artifact_digest"] == model.deployment_pin.artifact_digest
    assert lineage["mapping_pin"]["artifact_digest"] == model.mapping_pin.artifact_digest
    assert lineage["validity_envelope_ref"] == model.validity_envelope_ref
    assert lineage["input_digest"] == canonical_digest({"speed": 8})
    assert outcome.provenance_ref == canonical_digest(lineage)
    assert world.models.ReconstructModelInvocation(outcome.invocation_id) == outcome
    world.rejected(lambda: world.models.ReconstructModelInvocation("urn:uuid:" + str(uuid.uuid4())),
                   "CONTRACT_NOT_FOUND")
    world.rejected(lambda: world.invoke_model(model, {"speed": 8}, input_digest=canonical_digest({"speed": 9})),
                   "SCHEMA_VIOLATION")
    same_pins = world.invoke_model(model, {"speed": 8})
    assert same_pins.result_digest == outcome.result_digest and same_pins.invocation_id != outcome.invocation_id


def test_fr_060_unreproducible_model_fails_reconstruction(world: World) -> None:
    """FR-060: a model whose output is not a function of its pinned inputs is detected on replay."""
    source = (b"def predict(value, mapping, deployment):\n"
              b"    return {'score': float(id(object()) % 1000003)}\n")
    model = world.model(source=source)
    world.publish_model(model)
    outcome = world.invoke_model(model, {"speed": 5})
    world.rejected(lambda: world.models.ReconstructModelInvocation(outcome.invocation_id), "EXECUTION_FAILED")


def test_fr_061_model_outside_envelope_abstains_and_results_hold_one_disposition(world: World) -> None:
    """FR-061 (Register :185); ADD v1.3 §3.4: abstention outside the envelope, one disposition, output kind."""
    model = world.model()
    world.publish_model(model)
    outcome = world.invoke_model(model, {"speed": 99})
    assert outcome.output is None and outcome.abstention.reason_code == "OUTSIDE_VALIDITY_ENVELOPE"
    assert outcome.validity == world.c.ValidityAssessment(False, "1.0.0", ("speed-range",))
    assert world.models.ReconstructModelInvocation(outcome.invocation_id) == outcome
    inside = world.invoke_model(model, {"speed": 1})
    c = world.c
    for broken in (dataclasses.replace(inside, abstention=c.Abstention("X", "")),
                   dataclasses.replace(inside, output=None),
                   dataclasses.replace(inside, output_kind=c.ModelOutputKind.MODEL_OUTPUT_KIND_UNSPECIFIED),
                   dataclasses.replace(inside, validity=c.ValidityAssessment(False, "1.0.0", ("x",))),
                   dataclasses.replace(inside, validity=None)):
        world.rejected(lambda b=broken: c.admit_model_result(b), "SCHEMA_VIOLATION")
    assert c.admit_model_result(inside) is inside


def test_fr_061_model_publication_constraints(world: World) -> None:
    """ADD v1.3 §3.4: MODEL_INFERENCE only; a declared Prediction, Belief or Recommendation; signed pins."""
    model = world.model()
    world.rejected(lambda: world.publish_model(dataclasses.replace(model, effect_class=world.c.EffectClass.PURE)),
                   "SCHEMA_VIOLATION")
    world.rejected(lambda: world.publish_model(model, output_kind=None), "CONTRACT_REJECTED")
    world.rejected(lambda: world.publish_model(model, output_kind="CANONICAL_ASSERTION"), "CONTRACT_REJECTED")
    world.rejected(lambda: world.publish_model(model, rogue=True), "CONTRACT_REJECTED")
    world.rejected(lambda: world.publish_model(dataclasses.replace(model, risk_class="R3")), "CONTRACT_REJECTED")
    for bad in ({"envelope": {"envelope_version": "1.0.0", "conditions": [{"field": "speed"}]}},
                {"deployment": {"scale": 1}}):
        world.rejected(lambda b=bad: world.publish_model(world.model(**b)), "SCHEMA_VIOLATION")
    for name in ("model_pin", "deployment_pin", "mapping_pin", "input_schema", "output_schema"):
        world.rejected(lambda n=name: world.publish_model(dataclasses.replace(model, **{n: None})),
                       "SCHEMA_VIOLATION")
    for name in ("validity_envelope_ref", "training_lineage_ref", "owner_principal_ref", "approval_status"):
        world.rejected(lambda n=name: world.publish_model(dataclasses.replace(model, **{n: ""})),
                       "SCHEMA_VIOLATION")
    for kind in ("PREDICTION", "BELIEF", "RECOMMENDATION"):
        variant = world.model(deployment={"entrypoint": "predict", "scale": 1.5, "bias": 0.25, "k": kind})
        world.publish_model(variant, output_kind=kind)
        assert world.invoke_model(variant, {"speed": 2}).output_kind is world.c.ModelOutputKind[kind]


# --------------------------------------------------------------------------- #
# Idempotency, immutability and control-plane availability
# --------------------------------------------------------------------------- #
def test_publication_is_immutable_and_invocation_idempotent(world: World) -> None:
    """LLD v1.1 :40 recalculated digests; immutable pins; idempotency key (FR-062 pattern, ACT-T03)."""
    descriptor = world.function()
    first = world.publish_function(descriptor)
    assert world.publish_function(descriptor) == first
    changed = dataclasses.replace(descriptor, deterministic=False)
    world.rejected(lambda: world.publish_function(changed), "IDEMPOTENCY_CONFLICT")
    result = world.invoke(descriptor, {"speed": 4}, key="idem-x")
    assert world.invoke(descriptor, {"speed": 4}, key="idem-x") == result
    world.rejected(lambda: world.invoke(descriptor, {"speed": 5}, key="idem-x"), "IDEMPOTENCY_CONFLICT")
    world.rejected(lambda: world.invoke(descriptor, {"speed": 5}, key=""), "SCHEMA_VIOLATION")


def test_unreachable_store_is_control_plane_unavailable(world: World) -> None:
    """ADD v1.3 :174/:3141 pattern: an unavailable control plane fails closed, never falls back."""
    store = registry("adapters.postgres").PostgresRegistryStore(
        "postgresql://ocor:wrong@127.0.0.1:1/ocor", schema="rem0048_unreachable", connect_timeout=2)
    functions = world.svc.FunctionRegistry(store=store, releases=world.release.publisher,
                                           trust_root=world.keys.trust_root(),
                                           sandbox=world.sandbox_module.PythonSandbox())
    descriptor = world.function()
    world.rejected(lambda: functions.ResolveFunction(
        world.c.ResolveFunctionRequest(pin=descriptor.pin, context=world.context), binding=world.binding),
        "CONTROL_PLANE_UNAVAILABLE")


# --------------------------------------------------------------------------- #
# Input robustness of every parsing path (typed rejection, no coercion)
# --------------------------------------------------------------------------- #
def test_message_decoding_and_signature_parsing_fail_closed(world: World) -> None:
    """Every parsing path rejects tampered or ill-typed data with the typed error."""
    c = world.c
    budget = c.to_mapping(world.budget())
    for bad in (budget | {"extra": 1}, {k: v for k, v in budget.items() if k != "timeout"},
                budget | {"cpu_millis": "5000"}, budget | {"timeout": "5 s"}, budget | {"cpu_millis": True}, []):
        world.rejected(lambda b=bad: c.from_mapping(c.ResourceBudget, b), "SCHEMA_VIOLATION")
    typed = c.to_mapping(world.typed({"speed": 1}))
    world.rejected(lambda: c.from_mapping(c.TypedValue, typed | {"value": {"type_url": TYPE_URL, "value": "%%"}}),
                   "SCHEMA_VIOLATION")
    descriptor = c.to_mapping(world.function())
    world.rejected(lambda: c.from_mapping(c.FunctionDescriptor, descriptor | {"effect_class": "NOPE"}),
                   "SCHEMA_VIOLATION")
    world.rejected(lambda: c.from_mapping(c.FunctionDescriptor, descriptor | {"dependencies": {}}),
                   "SCHEMA_VIOLATION")
    verifier = world.svc.StatementVerifier(world.keys.trust_root())
    good = world.keys.sign(world.svc.MANIFEST_PAYLOAD_TYPE, {"kind": "FUNCTION"})
    import json

    envelope = json.loads(good)
    tampered = [
        b"not json",
        canonical_bytes(envelope | {"extra": 1}),
        canonical_bytes(envelope | {"payload": "%%%"}),
        canonical_bytes(envelope | {"signatures": []}),
        canonical_bytes(envelope | {"signatures": [{"keyid": world.keys.keyid}]}),
        canonical_bytes(envelope | {"payloadType": world.svc.ARTIFACT_PAYLOAD_TYPE}),
        canonical_bytes(envelope | {"payload": canonical_bytes({"kind": "MODEL"}).hex()}),
        canonical_bytes(envelope | {"signatures": [envelope["signatures"][0] | {"sig": "%%"}]}),
        canonical_bytes(envelope | {"signatures": [envelope["signatures"][0] | {"certificateChainRef": "x"}]}),
    ]
    for data in tampered:
        world.rejected(lambda d=data: verifier.verify(d, world.svc.MANIFEST_PAYLOAD_TYPE), "CONTRACT_REJECTED")
    assert verifier.verify(good, world.svc.MANIFEST_PAYLOAD_TYPE) == {"kind": "FUNCTION"}
    world.rejected(lambda: world.store.get_artifact("urn:sha256:" + "8" * 64), "CONTRACT_REJECTED")
    for request in (None, object(), c.PublishFunctionRequest(descriptor=None, signed_manifest_ref="",
                                                               change_proposal_ref="")):
        world.rejected(lambda r=request: world.functions.PublishFunction(r), "SCHEMA_VIOLATION")
