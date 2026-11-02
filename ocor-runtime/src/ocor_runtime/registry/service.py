"""``FunctionRegistry`` and ``ModelRegistry`` of ``ocor.registry.v1`` (ADD v1.3 §3.4).

Operations, as the services of ``ocor_registry.proto`` (:9-19): ``PublishFunction``,
``ResolveFunction``, ``InvokeFunction``, ``PublishModel``, ``ResolveModel`` and
``InvokeModel``; ``ReconstructModelInvocation`` replays a stored Model invocation against
its pinned inputs and versions (FR-060, Register v1.1 :184).

Admission (ADD v1.3 §3.4, the constraint list after the proto):
- exact pins only; range and ``latest`` are rejected (``contract.require_pin``);
- ``effect_class=UNSPECIFIED`` is invalid; a ``ModelDescriptor`` is ``MODEL_INFERENCE``;
- a ``PROPOSE_MUTATION`` Function returns only its typed Change Proposal as output: the
  registry has no port that writes canonical state, so an invocation never commits
  (FR-059) and a Model output stays a Prediction, Belief or Recommendation (FR-061);
- ``TypedValue.schema`` and ``protobuf_type_url`` equal the pinned descriptor schema;
- an artefact, deployment or mapping that is unsigned, revoked or outside its release
  fails closed: the descriptor is signed (DSSE manifest naming its digest), the artefact
  carries its own DSSE signature, both are re-verified on every resolve and invoke under
  the trust root (key revocation), registry revocations are checked, and the descriptor
  is bound to a named contract of an admitted C1 release (re-admitted on every use);
- the Principal and actor chain come from the verified transport binding, never from
  ``InvocationContext``; the other Governed Context fields are validated against it
  (``GovernedContextCodec.from_proto``), and the context release must be the bound one;
- a Model outside its validity envelope abstains, never returns output; a
  ``ModelResult`` holds exactly one disposition.

FR-058 (Register v1.1 :181): a Function without its mandatory metadata is not
published. NFR-025 (:182): Functions and Models run in the sandbox under the budget;
every overrun ends fail-safe and is audited.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Protocol

import jsonschema

from ..c1.ports import C1Error
from ..c1.signing import ED25519_PROFILE, Ed25519SigningKey, ReleasePackage, TrustRoot, dsse_pae, ed25519_verify
from ..kernel.canonical import canonical_bytes, canonical_digest, parse_i_json
from ..kernel.governed_context import (
    GovernedContext,
    GovernedContextCodec,
    GovernedContextError,
    VerifiedGovernedContextBinding,
)
from .contract import (
    Abstention,
    AnyValue,
    EffectClass,
    FunctionDescriptor,
    FunctionResult,
    InvocationContext,
    InvokeFunctionRequest,
    InvokeModelRequest,
    ModelDescriptor,
    ModelOutputKind,
    ModelResult,
    PublishFunctionRequest,
    PublishModelRequest,
    PublishReceipt,
    RegistryError,
    ResolveFunctionRequest,
    ResolveModelRequest,
    ResourceBudget,
    SchemaPin,
    TypedValue,
    ValidityAssessment,
    VersionPin,
    admit_function_descriptor,
    admit_model_descriptor,
    admit_model_result,
    from_mapping,
    json_mapping,
    message_digest,
    pin_key,
    require_budget,
    require_digest,
    require_pin,
    require_text,
    require_typed_value,
    require_urn,
    to_mapping,
    violation,
)
from .sandbox import SANDBOX_PROFILE, PythonSandbox, SandboxOverrun

MANIFEST_PAYLOAD_TYPE = "application/vnd.ocor.registry-manifest.v1+json"
ARTIFACT_PAYLOAD_TYPE = "application/vnd.ocor.registry-artifact.v1+json"
FUNCTION = "FUNCTION"
MODEL = "MODEL"
FUNCTION_ENTRYPOINT = "invoke"
READ_EFFECTS = frozenset({EffectClass.READ_CANONICAL, EffectClass.READ_PROJECTION, EffectClass.READ_EXTERNAL})
ENVELOPE_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["envelope_version", "conditions"],
    "properties": {
        "envelope_version": {"type": "string", "minLength": 1},
        "conditions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["condition_id", "field", "minimum", "maximum"],
                "properties": {
                    "condition_id": {"type": "string", "minLength": 1},
                    "field": {"type": "string", "minLength": 1},
                    "minimum": {"type": "number"},
                    "maximum": {"type": "number"},
                },
            },
        },
    },
}
DEPLOYMENT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["entrypoint"],
    "properties": {"entrypoint": {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$"}},
}


class RegistryStore(Protocol):
    def put_artifact(self, content: bytes) -> str: ...
    def get_artifact(self, digest: str) -> bytes: ...
    def append_audit(self, event: str, detail: Mapping[str, Any]) -> str: ...
    def append_entry(self, *, kind: str, entry_key: str, resource_id: str, semantic_version: str,
                     record: Mapping[str, Any], descriptor_digest: str,
                     audit_detail: Mapping[str, Any]) -> dict[str, Any]: ...
    def find_entry(self, kind: str, entry_key: str) -> dict[str, Any] | None: ...
    def has_version(self, kind: str, resource_id: str, semantic_version: str) -> bool: ...
    def revoked(self, digests: Iterable[str]) -> frozenset[str]: ...
    def record_invocation(self, *, invocation_id: str, kind: str, entry_key: str, idempotency_key: str | None,
                          request_digest: str, record: Mapping[str, Any]) -> dict[str, Any]: ...
    def find_invocation_by_key(self, kind: str, entry_key: str, idempotency_key: str) -> dict[str, Any] | None: ...
    def get_invocation(self, invocation_id: str) -> dict[str, Any] | None: ...


class ReleaseCatalog(Protocol):
    """The C1 release publisher: ``read`` returns a package only if admission accepts it again."""

    def read(self, ref: str) -> ReleasePackage: ...


# ------------------------------------------------------------------------------------
# DSSE statements: signed descriptor manifest and artefact signature
# ------------------------------------------------------------------------------------
def sign_statement(*, key: Ed25519SigningKey, keyid: str, certificate_chain_ref: str, payload_type: str,
                   statement: Mapping[str, Any]) -> bytes:
    """A DSSE envelope over the RFC 8785 bytes of ``statement`` (publisher tooling)."""
    payload = canonical_bytes(json_mapping(statement))
    signature = key.sign(dsse_pae(payload_type, payload))
    return canonical_bytes({
        "payloadType": payload_type,
        "payload": base64.b64encode(payload).decode("ascii"),
        "signingProfile": ED25519_PROFILE,
        "signatures": [{"keyid": keyid, "certificateChainRef": certificate_chain_ref,
                        "sig": base64.b64encode(signature).decode("ascii")}],
    })


class StatementVerifier:
    """Verifies a registry DSSE envelope under a trusted, unrevoked key; fail-closed."""

    def __init__(self, trust_root: TrustRoot) -> None:
        if not isinstance(trust_root, TrustRoot):
            raise TypeError("a TrustRoot is required")
        self._trust = trust_root

    def verify(self, envelope_bytes: bytes, payload_type: str) -> dict[str, Any]:
        def rejected(message: str) -> RegistryError:
            return RegistryError("CONTRACT_REJECTED", message)

        try:
            envelope = parse_i_json(envelope_bytes)
        except ValueError as exc:
            raise rejected("the signature envelope is not I-JSON") from exc
        if not isinstance(envelope, dict) or set(envelope) != {"payloadType", "payload", "signingProfile",
                                                                "signatures"}:
            raise rejected("the signature envelope is malformed")
        if envelope["payloadType"] != payload_type or envelope["signingProfile"] != ED25519_PROFILE:
            raise rejected("the signature envelope has the wrong payload type or signing profile")
        try:
            payload = base64.b64decode(envelope["payload"], validate=True)
            statement = parse_i_json(payload)
        except (binascii.Error, TypeError, ValueError) as exc:
            raise rejected("the signed payload is malformed") from exc
        signatures = envelope["signatures"]
        if not isinstance(statement, dict) or not isinstance(signatures, list) or not signatures:
            raise rejected("the signed payload is malformed")
        pae = dsse_pae(payload_type, payload)
        for item in signatures:
            if not isinstance(item, dict) or set(item) != {"keyid", "certificateChainRef", "sig"}:
                raise rejected("a signature entry is malformed")
            trusted = self._trust.keys.get(item["keyid"])
            if trusted is None or item["keyid"] in self._trust.revoked_keyids:
                continue
            if trusted.signing_profile != ED25519_PROFILE or not isinstance(item["certificateChainRef"], str):
                continue
            if not hmac.compare_digest(trusted.certificate_chain_ref, item["certificateChainRef"]):
                continue
            try:
                raw = base64.b64decode(item["sig"], validate=True)
            except (binascii.Error, TypeError, ValueError) as exc:
                raise rejected("a signature is not base64") from exc
            if ed25519_verify(trusted.public_key, pae, raw):
                return statement
        raise rejected("no signature verifies under a trusted, unrevoked key")


# ------------------------------------------------------------------------------------
# Shared registry core
# ------------------------------------------------------------------------------------
def _contract_entry(core: Mapping[str, Any], resource_id: str) -> dict[str, Any] | None:
    for contract in core.get("named_contracts", ()):
        if contract.get("contract_id") == resource_id:
            return dict(json_mapping(contract))
    return None


def _parse_json(raw: bytes, where: str) -> Any:
    try:
        return parse_i_json(raw)
    except ValueError as exc:
        raise violation(f"{where} is not I-JSON") from exc


def _validate(schema: Mapping[str, Any], value: Any, where: str) -> None:
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(value), key=lambda e: e.json_path)
    if errors:
        raise violation(f"{where} violates its pinned schema: {errors[0].message[:128]}")


class _RegistryCore:
    def __init__(self, *, store: RegistryStore, releases: ReleaseCatalog, trust_root: TrustRoot,
                 sandbox: PythonSandbox) -> None:
        self._store = store
        self._releases = releases
        self._verifier = StatementVerifier(trust_root)
        self._sandbox = sandbox

    # -- release binding ----------------------------------------------------------
    def _release(self, release_ref: str) -> ReleasePackage:
        require_digest(release_ref, "manifest.release_ref")
        try:
            return self._releases.read(release_ref)
        except C1Error as exc:
            raise RegistryError("CONTRACT_REJECTED", f"the release is not admitted: {exc}") from exc

    def _bind(self, release_ref: str, *, kind: str, pin: VersionPin, effect: EffectClass, input_schema: SchemaPin,
              output_schema: SchemaPin) -> tuple[str, dict[str, Any]]:
        """Bind a descriptor to a named contract of an admitted C1 release."""
        package = self._release(release_ref)
        contract = _contract_entry(package.signed.release.core, pin.resource_id)
        if contract is None:
            raise RegistryError("CONTRACT_REJECTED", f"{pin.resource_id} is outside the release")
        if contract.get("kind") != kind:
            raise RegistryError("CONTRACT_REJECTED", f"{pin.resource_id} is a {contract.get('kind')} contract")
        if contract.get("version") != pin.semantic_version:
            raise RegistryError("RELEASE_MISMATCH", "the pinned version is not the version of the release")
        if canonical_digest(contract) != pin.contract_digest:
            raise RegistryError("CONTRACT_DIGEST_MISMATCH", "contract_digest does not match the release contract")
        if contract.get("effect_class") != effect.name:
            raise RegistryError("CONTRACT_REJECTED", "the effect class differs from the release contract")
        for name, schema_pin in (("input_schema", input_schema), ("output_schema", output_schema)):
            if canonical_digest(contract[name]) != schema_pin.schema_digest:
                raise RegistryError("CONTRACT_DIGEST_MISMATCH", f"{name}.schema_digest does not match the release")
        return package.signed.release.ir_digest, contract

    # -- signatures and revocation ------------------------------------------------
    def _verify_artifact_signature(self, signature_ref: str, pin: VersionPin) -> None:
        statement = self._verifier.verify(self._store.get_artifact(signature_ref), ARTIFACT_PAYLOAD_TYPE)
        expected = {"artifact_digest": pin.artifact_digest, "resource_id": pin.resource_id,
                    "semantic_version": pin.semantic_version}
        if statement != expected:
            raise RegistryError("CONTRACT_REJECTED", "the artefact signature does not name the pinned artefact")

    def _verify_manifest(self, manifest_ref: str, *, kind: str, descriptor_digest: str,
                         change_proposal_ref: str) -> dict[str, Any]:
        statement = self._verifier.verify(self._store.get_artifact(manifest_ref), MANIFEST_PAYLOAD_TYPE)
        if (statement.get("kind") != kind or statement.get("descriptor_digest") != descriptor_digest
                or statement.get("change_proposal_ref") != change_proposal_ref):
            raise RegistryError("CONTRACT_REJECTED", "the signed manifest does not name this descriptor")
        return statement

    def _not_revoked(self, digests: Iterable[str]) -> None:
        revoked = self._store.revoked(digests)
        if revoked:
            raise RegistryError("CONTRACT_REJECTED", f"revoked: {sorted(revoked)[0]}")

    # -- context --------------------------------------------------------------------
    @staticmethod
    def _context(context: object, binding: VerifiedGovernedContextBinding) -> GovernedContext:
        if not isinstance(context, InvocationContext):
            raise violation("context is required")
        for name in ("request_id", "logic_version", "branch"):
            require_text(getattr(context, name), f"context.{name}")
        for name in ("scenario_id", "causation_id", "delegation_ref"):
            value = getattr(context, name)
            if value is not None:
                require_text(value, f"context.{name}")
        if not isinstance(context.compartments, tuple):
            raise violation("context.compartments must be a list")
        try:
            return GovernedContextCodec.from_proto(context, binding)
        except GovernedContextError as exc:
            raise RegistryError("GOVERNED_CONTEXT_MISMATCH", str(exc)) from exc

    @staticmethod
    def _same_release(context: InvocationContext, record: Mapping[str, Any]) -> None:
        if context.ontology_release_digest != record["release_ir_digest"]:
            raise RegistryError("RELEASE_MISMATCH", "the context release is not the release the entry is bound to")

    def _live(self, record: Mapping[str, Any], signed: Iterable[tuple[str, VersionPin]],
              digests: Iterable[str]) -> None:
        """Re-verify a stored entry: signatures, revocation and admission of its release."""
        for signature_ref, pin in signed:
            self._verify_artifact_signature(signature_ref, pin)
        self._verifier.verify(self._store.get_artifact(record["signed_manifest_ref"]), MANIFEST_PAYLOAD_TYPE)
        self._not_revoked(digests)
        if self._release(record["release_ref"]).signed.release.ir_digest != record["release_ir_digest"]:
            raise RegistryError("RELEASE_MISMATCH", "the bound release changed")

    def _entry(self, kind: str, key: str, pin: VersionPin) -> dict[str, Any]:
        entry = self._store.find_entry(kind, key)
        if entry is None:
            if self._store.has_version(kind, pin.resource_id, pin.semantic_version):
                raise RegistryError("CONTRACT_DIGEST_MISMATCH", "the pin does not match the published digests")
            raise RegistryError("CONTRACT_NOT_FOUND", f"{pin.resource_id}@{pin.semantic_version} is not published")
        return entry

    def _run(self, *, kind: str, pin: VersionPin, request_id: str, source_digest: str, entrypoint: str,
             arguments: list[Any], budget: ResourceBudget) -> Any:
        source = self._store.get_artifact(source_digest)
        try:
            return self._sandbox.run(source=source, artifact_digest=source_digest, entrypoint=entrypoint,
                                     arguments=arguments, budget=budget).output
        except SandboxOverrun as overrun:
            audit_ref = self._store.append_audit("SANDBOX_BUDGET_EXCEEDED", {
                "kind": kind, "overrun": overrun.kind, "detail": overrun.detail, "pin": to_mapping(pin),
                "request_id": request_id, "budget": to_mapping(budget), "sandbox_profile": SANDBOX_PROFILE})
            raise RegistryError("BUDGET_EXCEEDED", f"{overrun.kind}: terminated fail-safe",
                                audit_ref=audit_ref) from overrun


# ------------------------------------------------------------------------------------
# FunctionRegistry
# ------------------------------------------------------------------------------------
class FunctionRegistry(_RegistryCore):
    """``service FunctionRegistry`` (ocor_registry.proto :9-13)."""

    def PublishFunction(self, request: PublishFunctionRequest) -> PublishReceipt:  # noqa: N802 - proto RPC name
        if not isinstance(request, PublishFunctionRequest):
            raise violation("PublishFunctionRequest is required")
        descriptor = admit_function_descriptor(request.descriptor)
        manifest_ref = require_digest(request.signed_manifest_ref, "signed_manifest_ref")
        proposal = require_urn(request.change_proposal_ref, "change_proposal_ref")
        pin = descriptor.pin
        assert pin is not None and descriptor.input_schema is not None and descriptor.output_schema is not None
        descriptor_digest = message_digest(descriptor)
        manifest = self._verify_manifest(manifest_ref, kind=FUNCTION, descriptor_digest=descriptor_digest,
                                         change_proposal_ref=proposal)
        self._verify_artifact_signature(descriptor.artifact_signature_ref, pin)
        self._store.get_artifact(pin.artifact_digest)
        for dependency in descriptor.dependencies:
            self._entry(FUNCTION, pin_key(dependency), dependency)
        self._not_revoked([pin.artifact_digest, manifest_ref, descriptor.artifact_signature_ref,
                           *(d.artifact_digest for d in descriptor.dependencies)])
        release_ref = str(manifest.get("release_ref", ""))
        ir_digest, contract = self._bind(release_ref, kind=FUNCTION, pin=pin, effect=descriptor.effect_class,
                                         input_schema=descriptor.input_schema,
                                         output_schema=descriptor.output_schema)
        if tuple(contract.get("policy_refs", ())) != descriptor.policy_refs:
            raise RegistryError("CONTRACT_REJECTED", "policy_refs differ from the release contract")
        record = {"descriptor": to_mapping(descriptor), "release_ref": release_ref, "release_ir_digest": ir_digest,
                  "input_json_schema": contract["input_schema"], "output_json_schema": contract["output_schema"],
                  "signed_manifest_ref": manifest_ref, "change_proposal_ref": proposal}
        row = self._store.append_entry(
            kind=FUNCTION, entry_key=pin_key(pin), resource_id=pin.resource_id,
            semantic_version=pin.semantic_version, record=record, descriptor_digest=descriptor_digest,
            audit_detail={"pin": to_mapping(pin), "descriptor_digest": descriptor_digest,
                          "change_proposal_ref": proposal, "release_ir_digest": ir_digest})
        return _receipt(row)

    def _resolved(self, pin: VersionPin) -> tuple[FunctionDescriptor, dict[str, Any], dict[str, Any]]:
        entry = self._entry(FUNCTION, pin_key(pin), pin)
        record = entry["record"]
        descriptor = from_mapping(FunctionDescriptor, record["descriptor"], "descriptor")
        self._live(record, [(descriptor.artifact_signature_ref, pin)],
                   [pin.artifact_digest, record["signed_manifest_ref"], descriptor.artifact_signature_ref,
                    *(d.artifact_digest for d in descriptor.dependencies)])
        return descriptor, record, entry

    def ResolveFunction(self, request: ResolveFunctionRequest, *,  # noqa: N802 - proto RPC name
                        binding: VerifiedGovernedContextBinding) -> FunctionDescriptor:
        if not isinstance(request, ResolveFunctionRequest):
            raise violation("ResolveFunctionRequest is required")
        pin = require_pin(request.pin, "pin")
        self._context(request.context, binding)
        assert request.context is not None
        descriptor, record, _ = self._resolved(pin)
        self._same_release(request.context, record)
        return descriptor

    def InvokeFunction(self, request: InvokeFunctionRequest, *,  # noqa: N802 - proto RPC name
                       binding: VerifiedGovernedContextBinding) -> FunctionResult:
        if not isinstance(request, InvokeFunctionRequest):
            raise violation("InvokeFunctionRequest is required")
        pin = require_pin(request.function_pin, "function_pin")
        governed = self._context(request.context, binding)
        context = request.context
        assert context is not None
        key = require_text(request.idempotency_key, "idempotency_key")
        descriptor, record, entry = self._resolved(pin)
        self._same_release(context, record)
        if descriptor.effect_class in READ_EFFECTS:
            raise RegistryError("UNSUPPORTED_CAPABILITY",
                                "no governed read port is bound to the sandbox: the served commit cannot be disclosed")
        assert descriptor.input_schema is not None and descriptor.output_schema is not None
        assert descriptor.budget is not None
        typed = require_typed_value(request.input, descriptor.input_schema, "input")
        assert typed.value is not None
        value = _parse_json(typed.value.value, "input.value")
        _validate(record["input_json_schema"], value, "input")
        fingerprint = canonical_digest({"function_pin": to_mapping(pin), "input": to_mapping(typed),
                                        "governed_context_digest": context.governed_context_digest,
                                        "branch": context.branch, "scenario_id": context.scenario_id})
        replay = self._store.find_invocation_by_key(FUNCTION, pin_key(pin), key)
        if replay is not None:
            return _replayed(replay, fingerprint)
        output = self._run(kind=FUNCTION, pin=pin, request_id=context.request_id, source_digest=pin.artifact_digest,
                           entrypoint=FUNCTION_ENTRYPOINT, arguments=[value], budget=descriptor.budget)
        _validate(record["output_json_schema"], output, "output")
        typed_output = TypedValue(schema=descriptor.output_schema,
                                  value=AnyValue(descriptor.output_schema.protobuf_type_url, canonical_bytes(output)))
        provenance = {"function_pin": to_mapping(pin), "input_digest": canonical_digest(value),
                      "governed_context_digest": governed.digest(), "release_ir_digest": record["release_ir_digest"],
                      "registry_commit": entry["registry_commit"], "sandbox_profile": SANDBOX_PROFILE}
        provenance_ref = canonical_digest(provenance)
        result_body = {"output": to_mapping(typed_output), "effect_class": descriptor.effect_class.name,
                       "provenance_ref": provenance_ref,
                       "classification_marking_ref": context.classification_marking_ref,
                       "served_commit": "", "watermark": ""}
        result = FunctionResult(
            invocation_id=uuid.uuid4().urn, output=typed_output, effect_class=descriptor.effect_class,
            result_digest=canonical_digest(result_body), provenance_ref=provenance_ref,
            classification_marking_ref=context.classification_marking_ref, served_commit="", watermark="")
        stored = self._store.record_invocation(
            invocation_id=result.invocation_id, kind=FUNCTION, entry_key=pin_key(pin), idempotency_key=key,
            request_digest=fingerprint, record={"result": to_mapping(result), "provenance": provenance})
        return _replayed(stored, fingerprint)


def _receipt(row: Mapping[str, Any]) -> PublishReceipt:
    accepted: datetime = row["accepted_at"]
    return PublishReceipt(registry_commit=row["registry_commit"], descriptor_digest=row["descriptor_digest"],
                          accepted_at=accepted, audit_ref=row["audit_ref"])


def _replayed(row: Mapping[str, Any], fingerprint: str) -> FunctionResult:
    if row["request_digest"] != fingerprint:
        raise RegistryError("IDEMPOTENCY_CONFLICT", "the idempotency key was used for a different request")
    return from_mapping(FunctionResult, row["record"]["result"], "result")


# ------------------------------------------------------------------------------------
# ModelRegistry
# ------------------------------------------------------------------------------------
def _model_key(model: VersionPin, deployment: VersionPin, mapping: VersionPin) -> str:
    return "\x1e".join(pin_key(pin) for pin in (model, deployment, mapping))


def _assess(envelope: Mapping[str, Any], value: Any) -> ValidityAssessment:
    failed = []
    for condition in envelope["conditions"]:
        observed = value.get(condition["field"]) if isinstance(value, dict) else None
        inside = (isinstance(observed, int | float) and not isinstance(observed, bool)
                  and condition["minimum"] <= observed <= condition["maximum"])
        if not inside:
            failed.append(condition["condition_id"])
    return ValidityAssessment(inside_envelope=not failed, envelope_version=envelope["envelope_version"],
                              failed_conditions=tuple(sorted(set(failed))))


class ModelRegistry(_RegistryCore):
    """``service ModelRegistry`` (ocor_registry.proto :15-19)."""

    def __init__(self, *, store: RegistryStore, releases: ReleaseCatalog, trust_root: TrustRoot,
                 sandbox: PythonSandbox, budget: ResourceBudget) -> None:
        super().__init__(store=store, releases=releases, trust_root=trust_root, sandbox=sandbox)
        self._budget = require_budget(budget, "model budget")

    def _json_artifact(self, digest: str, schema: Mapping[str, Any], where: str) -> Any:
        value = _parse_json(self._store.get_artifact(digest), where)
        _validate(schema, value, where)
        return value

    def PublishModel(self, request: PublishModelRequest) -> PublishReceipt:  # noqa: N802 - proto RPC name
        if not isinstance(request, PublishModelRequest):
            raise violation("PublishModelRequest is required")
        descriptor = admit_model_descriptor(request.descriptor)
        manifest_ref = require_digest(request.signed_manifest_ref, "signed_manifest_ref")
        proposal = require_urn(request.change_proposal_ref, "change_proposal_ref")
        model, deployment, mapping = descriptor.model_pin, descriptor.deployment_pin, descriptor.mapping_pin
        assert model is not None and deployment is not None and mapping is not None
        assert descriptor.input_schema is not None and descriptor.output_schema is not None
        descriptor_digest = message_digest(descriptor)
        manifest = self._verify_manifest(manifest_ref, kind=MODEL, descriptor_digest=descriptor_digest,
                                         change_proposal_ref=proposal)
        output_kind = manifest.get("output_kind")
        if output_kind not in ("PREDICTION", "BELIEF", "RECOMMENDATION"):
            raise RegistryError("CONTRACT_REJECTED", "the manifest declares no Prediction, Belief or Recommendation")
        self._verify_artifact_signature(descriptor.artifact_signature_ref, model)
        self._store.get_artifact(model.artifact_digest)
        self._json_artifact(deployment.artifact_digest, DEPLOYMENT_SCHEMA, "deployment")
        self._json_artifact(mapping.artifact_digest, {"type": "object"}, "mapping")
        self._json_artifact(descriptor.validity_envelope_ref, ENVELOPE_SCHEMA, "validity envelope")
        self._not_revoked([model.artifact_digest, deployment.artifact_digest, mapping.artifact_digest,
                           descriptor.validity_envelope_ref, manifest_ref, descriptor.artifact_signature_ref])
        release_ref = str(manifest.get("release_ref", ""))
        ir_digest, contract = self._bind(release_ref, kind="MODEL_FUNCTION", pin=model,
                                         effect=descriptor.effect_class, input_schema=descriptor.input_schema,
                                         output_schema=descriptor.output_schema)
        if contract.get("risk_class") != descriptor.risk_class:
            raise RegistryError("CONTRACT_REJECTED", "risk_class differs from the release contract")
        record = {"descriptor": to_mapping(descriptor), "release_ref": release_ref, "release_ir_digest": ir_digest,
                  "input_json_schema": contract["input_schema"], "output_json_schema": contract["output_schema"],
                  "signed_manifest_ref": manifest_ref, "change_proposal_ref": proposal, "output_kind": output_kind}
        row = self._store.append_entry(
            kind=MODEL, entry_key=_model_key(model, deployment, mapping), resource_id=model.resource_id,
            semantic_version=model.semantic_version, record=record, descriptor_digest=descriptor_digest,
            audit_detail={"model_pin": to_mapping(model), "deployment_pin": to_mapping(deployment),
                          "mapping_pin": to_mapping(mapping), "descriptor_digest": descriptor_digest,
                          "change_proposal_ref": proposal, "release_ir_digest": ir_digest})
        return _receipt(row)

    def _resolved(self, model: VersionPin, deployment: VersionPin,
                  mapping: VersionPin) -> tuple[ModelDescriptor, dict[str, Any], dict[str, Any]]:
        entry = self._entry(MODEL, _model_key(model, deployment, mapping), model)
        record = entry["record"]
        descriptor = from_mapping(ModelDescriptor, record["descriptor"], "descriptor")
        self._live(record, [(descriptor.artifact_signature_ref, model)],
                   [model.artifact_digest, deployment.artifact_digest, mapping.artifact_digest,
                    descriptor.validity_envelope_ref, record["signed_manifest_ref"],
                    descriptor.artifact_signature_ref])
        return descriptor, record, entry

    def ResolveModel(self, request: ResolveModelRequest, *,  # noqa: N802 - proto RPC name
                     binding: VerifiedGovernedContextBinding) -> ModelDescriptor:
        if not isinstance(request, ResolveModelRequest):
            raise violation("ResolveModelRequest is required")
        pins = (require_pin(request.model_pin, "model_pin"), require_pin(request.deployment_pin, "deployment_pin"),
                require_pin(request.mapping_pin, "mapping_pin"))
        self._context(request.context, binding)
        assert request.context is not None
        descriptor, record, _ = self._resolved(*pins)
        self._same_release(request.context, record)
        return descriptor

    def _evaluate(self, *, descriptor: ModelDescriptor, record: Mapping[str, Any], entry: Mapping[str, Any],
                  value: Any, request_id: str, governed_context_digest: str,
                  classification_marking_ref: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """Envelope assessment and sandboxed inference; returns the result body and provenance."""
        model, deployment, mapping = descriptor.model_pin, descriptor.deployment_pin, descriptor.mapping_pin
        assert model is not None and deployment is not None and mapping is not None
        assert descriptor.output_schema is not None
        envelope = self._json_artifact(descriptor.validity_envelope_ref, ENVELOPE_SCHEMA, "validity envelope")
        validity = _assess(envelope, value)
        provenance = {"model_pin": to_mapping(model), "deployment_pin": to_mapping(deployment),
                      "mapping_pin": to_mapping(mapping), "input_digest": canonical_digest(value),
                      "governed_context_digest": governed_context_digest,
                      "release_ir_digest": record["release_ir_digest"], "registry_commit": entry["registry_commit"],
                      "validity_envelope_ref": descriptor.validity_envelope_ref,
                      "envelope_version": validity.envelope_version, "sandbox_profile": SANDBOX_PROFILE}
        provenance_ref = canonical_digest(provenance)
        output: TypedValue | None = None
        abstention: Abstention | None = None
        if validity.inside_envelope:
            deployment_doc = self._json_artifact(deployment.artifact_digest, DEPLOYMENT_SCHEMA, "deployment")
            mapping_doc = self._json_artifact(mapping.artifact_digest, {"type": "object"}, "mapping")
            produced = self._run(kind=MODEL, pin=model, request_id=request_id, source_digest=model.artifact_digest,
                                 entrypoint=deployment_doc["entrypoint"],
                                 arguments=[value, mapping_doc, deployment_doc], budget=self._budget)
            _validate(record["output_json_schema"], produced, "output")
            output = TypedValue(schema=descriptor.output_schema,
                                value=AnyValue(descriptor.output_schema.protobuf_type_url, canonical_bytes(produced)))
        else:
            abstention = Abstention(reason_code="OUTSIDE_VALIDITY_ENVELOPE", explanation_ref=canonical_digest(
                {"envelope_version": validity.envelope_version,
                 "failed_conditions": list(validity.failed_conditions)}))
        body = {"output_kind": record["output_kind"], "output": to_mapping(output),
                "abstention": to_mapping(abstention), "validity": to_mapping(validity), "uncertainty": None,
                "provenance_ref": provenance_ref, "classification_marking_ref": classification_marking_ref}
        return body, provenance

    def InvokeModel(self, request: InvokeModelRequest, *,  # noqa: N802 - proto RPC name
                    binding: VerifiedGovernedContextBinding) -> ModelResult:
        if not isinstance(request, InvokeModelRequest):
            raise violation("InvokeModelRequest is required")
        pins = (require_pin(request.model_pin, "model_pin"), require_pin(request.deployment_pin, "deployment_pin"),
                require_pin(request.mapping_pin, "mapping_pin"))
        governed = self._context(request.context, binding)
        context = request.context
        assert context is not None
        descriptor, record, entry = self._resolved(*pins)
        self._same_release(context, record)
        assert descriptor.input_schema is not None
        typed = require_typed_value(request.input, descriptor.input_schema, "input")
        assert typed.value is not None
        value = _parse_json(typed.value.value, "input.value")
        require_digest(request.input_digest, "input_digest")
        if not hmac.compare_digest(canonical_digest(value), request.input_digest):
            raise violation("input_digest does not match the recalculated digest of the input")
        _validate(record["input_json_schema"], value, "input")
        body, provenance = self._evaluate(descriptor=descriptor, record=record, entry=entry, value=value,
                                          request_id=context.request_id, governed_context_digest=governed.digest(),
                                          classification_marking_ref=context.classification_marking_ref)
        result = _model_result(uuid.uuid4().urn, body)
        self._store.record_invocation(
            invocation_id=result.invocation_id, kind=MODEL, entry_key=_model_key(*pins), idempotency_key=None,
            request_digest=message_digest(request),
            record={"request": to_mapping(request), "result": to_mapping(result), "provenance": provenance,
                    "result_body": body})
        return result

    def ReconstructModelInvocation(self, invocation_id: str) -> ModelResult:  # noqa: N802 - registry operation
        """FR-060: rebuild a stored output from its pinned input and versions; mismatch fails closed."""
        row = self._store.get_invocation(require_text(invocation_id, "invocation_id"))
        if row is None or row["kind"] != MODEL:
            raise RegistryError("CONTRACT_NOT_FOUND", "no Model invocation with this identifier")
        stored = row["record"]
        request = from_mapping(InvokeModelRequest, stored["request"], "request")
        assert request.model_pin and request.deployment_pin and request.mapping_pin and request.context
        assert request.input is not None and request.input.value is not None
        descriptor, record, entry = self._resolved(request.model_pin, request.deployment_pin, request.mapping_pin)
        value = _parse_json(request.input.value.value, "input.value")
        if canonical_digest(value) != request.input_digest:
            raise violation("the stored input does not match its input_digest")
        body, _ = self._evaluate(descriptor=descriptor, record=record, entry=entry, value=value,
                                 request_id=request.context.request_id,
                                 governed_context_digest=stored["provenance"]["governed_context_digest"],
                                 classification_marking_ref=request.context.classification_marking_ref)
        rebuilt = _model_result(row["invocation_id"], body)
        if rebuilt.result_digest != stored["result"]["result_digest"]:
            raise RegistryError("EXECUTION_FAILED", "the Model output is not reproducible from its pinned inputs")
        return rebuilt


def _model_result(invocation_id: str, body: Mapping[str, Any]) -> ModelResult:
    result = ModelResult(
        invocation_id=invocation_id, output_kind=ModelOutputKind[body["output_kind"]],
        output=from_mapping(TypedValue, body["output"], "output") if body["output"] is not None else None,
        abstention=from_mapping(Abstention, body["abstention"], "abstention") if body["abstention"] else None,
        validity=from_mapping(ValidityAssessment, body["validity"], "validity"), uncertainty=None,
        result_digest=canonical_digest(dict(body)), provenance_ref=body["provenance_ref"],
        classification_marking_ref=body["classification_marking_ref"])
    return admit_model_result(result)
