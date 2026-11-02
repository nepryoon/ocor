"""C2 transport adapter of the Named Query Gateway contract (wire form).

Exposes the six operations of ``ocor-named-query-gateway.openapi.yaml`` (:8-98) by
``operationId``. The request body is validated against the contract component schema of
the operation, the principal is the one the transport authenticated (never a body
field: ``QueryContext`` is closed, contract :142-149), and every answer is either the
contract response (``application/json``) or the contract ``Problem``
(``application/problem+json``, :486-491), both validated against the contract before
they leave.

Digest form (NORMATIVE-CONFORMANCE-PLAN point 4, NCR-C2-008 option 2): on the wire
``policy_bundle_digest``, ``governed_context_digest``, ``ontology_release_digest``,
``contract_digest`` and ``SchemaPin.digest`` are ``sha256:<hex>`` (contract :118,
:170-192); they are converted bijectively to and from the internal ``urn:sha256:<hex>``
(LLD v1.1 :37) and ``governed_context_digest`` is computed on the internal form of the
GovernedContext. A malformed digest is ``SCHEMA_VIOLATION``. An absent or empty
governed-context field is ``POLICY_DENIED`` (ADD v1.3 :380: Query, DENY without lookup).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from ..audit import AuditError, AuditEvent
from ..kernel.canonical import canonical_digest
from ..security.ports import AuthenticatedPrincipal
from .gateway import GatewayAnswer, NamedQueryGateway
from .ports import C2Error, ConsistencyRequirement, ContractCall, NamedQueryCall, QueryContext, TransportBoundQuery
from .problem import PROBLEM_MEDIA_TYPE, PROBLEM_STATUS, problem_document, served_document, wire_digest

CONTRACT_PATH = (
    Path(__file__).resolve().parents[3] / "docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml"
)
WIRE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
INTERNAL_DIGEST = re.compile(r"urn:sha256:[0-9a-f]{64}")
WIRE_DIGEST_FIELDS = ("ontology_release_digest", "policy_bundle_digest", "governed_context_digest")
GCS_WIRE_FIELDS = frozenset({
    "tenant_id", "organization_id", "domain_id", "compartments", "purpose", "classification_marking_ref",
    "ontology_release_digest", "policy_bundle_digest", "governed_context_digest", "correlation_id",
})
CONTRACT_CALL_FIELD = {
    "GetObject": "view_contract",
    "QueryObjectSet": "object_set_contract",
    "Search": "search_contract",
    "Traverse": "traversal_contract",
    "Explain": "explanation_contract",
}
UNRESOLVED_MARKING = canonical_digest({"marking": "unresolved"})


def to_internal_digest(value: object) -> str:
    if not isinstance(value, str) or WIRE_DIGEST.fullmatch(value) is None:
        raise C2Error("SCHEMA_VIOLATION", "a wire digest must be sha256:<64 lowercase hex>")
    return "urn:sha256:" + value.removeprefix("sha256:")


def to_wire_digest(value: object) -> str:
    if not isinstance(value, str) or INTERNAL_DIGEST.fullmatch(value) is None:
        raise C2Error("SCHEMA_VIOLATION", "an internal digest must be urn:sha256:<64 lowercase hex>")
    return wire_digest(value)


@dataclass(frozen=True, slots=True)
class GatewayReply:
    status: int
    media_type: str
    body: dict[str, Any]


class NamedQueryHttpAdapter:
    """The wire boundary of the gateway; one instance per contract file."""

    def __init__(self, gateway: NamedQueryGateway, *, contract_path: Path = CONTRACT_PATH) -> None:
        document = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
        self._gateway = gateway
        self._components = document["components"]
        self._operations: dict[str, tuple[str, str]] = {}
        for path in document["paths"].values():
            post = path["post"]
            request_ref = post["requestBody"]["content"]["application/json"]["schema"]["$ref"]
            response_ref = post["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
            self._operations[post["operationId"]] = (request_ref.rsplit("/", 1)[-1], response_ref.rsplit("/", 1)[-1])

    def _validator(self, name: str) -> jsonschema.Draft202012Validator:
        schema = {"$ref": f"#/components/schemas/{name}", "components": self._components}
        return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)

    @property
    def operations(self) -> tuple[str, ...]:
        return tuple(self._operations)

    # -- replies -------------------------------------------------------------------
    def _problem(self, error: C2Error, body: object) -> GatewayReply:
        context = body.get("context") if isinstance(body, Mapping) else None
        correlation = "00000000-0000-0000-0000-000000000000"
        marking = UNRESOLVED_MARKING
        if isinstance(context, Mapping):
            if isinstance(context.get("correlation_id"), str):
                candidate = context["correlation_id"]
                if jsonschema.Draft202012Validator.FORMAT_CHECKER.conforms(candidate, "uuid"):
                    correlation = candidate
            ref = context.get("classification_marking_ref")
            if isinstance(ref, str) and INTERNAL_DIGEST.fullmatch(ref):
                marking = ref
        document = problem_document(error, correlation_id=correlation, result_marking_ref=marking)
        self._validator("Problem").validate(document)
        return GatewayReply(PROBLEM_STATUS[error.reason_code], PROBLEM_MEDIA_TYPE, document)

    def _audit_rejection(self, operation: str, principal: AuthenticatedPrincipal, error: C2Error,
                         body: object) -> None:
        context = body.get("context") if isinstance(body, Mapping) else None
        correlation = context.get("correlation_id") if isinstance(context, Mapping) else None
        try:
            self._gateway.audit_port.append(AuditEvent(
                event_type="C2_QUERY_DENIED", actor=principal.principal_id, occurred_at=datetime.now(UTC),
                resource=f"operation:{operation}", reason_code=error.reason_code,
                authority_ref=principal.session_id,
                correlation_id=correlation if isinstance(correlation, str) and correlation else "unparsed-request",
                outcome="REJECTED", detail={"operation": operation, "stage": "transport"}))
        except AuditError as exc:
            raise C2Error("CONTROL_PLANE_UNAVAILABLE", "the rejection could not be durably audited") from exc

    def invoke(self, operation: str, body: Mapping[str, Any], principal: AuthenticatedPrincipal) -> GatewayReply:
        try:
            try:
                if operation not in self._operations:
                    raise C2Error("CONTRACT_NOT_FOUND", "no such operation")
                request_schema, response_schema = self._operations[operation]
                bound, arguments = self._parse(operation, request_schema, body, principal)
            except C2Error as error:
                if error.reason_code != "CONTROL_PLANE_UNAVAILABLE":
                    self._audit_rejection(operation, principal, error, body)
                raise
            answer = self._call(operation, bound, arguments)
            document = self._wire_response(answer)
            self._validator(response_schema).validate(document)
            return GatewayReply(200, "application/json", document)
        except C2Error as error:
            return self._problem(error, body)

    # -- parsing -------------------------------------------------------------------
    def _parse(self, operation: str, schema: str, body: object, principal: AuthenticatedPrincipal
               ) -> tuple[TransportBoundQuery, dict[str, Any]]:
        if not isinstance(body, Mapping):
            raise C2Error("SCHEMA_VIOLATION", "the request body must be an object")
        errors = list(self._validator(schema).iter_errors(dict(body)))
        if errors:
            raise C2Error("POLICY_DENIED" if self._governed_only(errors) else "SCHEMA_VIOLATION",
                          "the request violates the contract schema")
        context = body["context"]
        internal = {field: to_internal_digest(context[field]) for field in WIRE_DIGEST_FIELDS}
        query_context = QueryContext(
            request_id=context["request_id"], correlation_id=context["correlation_id"],
            tenant_id=context["tenant_id"], organization_id=context["organization_id"],
            domain_id=context["domain_id"], compartments=tuple(context["compartments"]),
            purpose=context["purpose"], classification_marking_ref=context["classification_marking_ref"],
            ontology_release_digest=internal["ontology_release_digest"],
            policy_bundle_digest=internal["policy_bundle_digest"],
            governed_context_digest=internal["governed_context_digest"],
            logic_version=context["logic_version"], branch=context["branch"],
            consistency=ConsistencyRequirement.from_mapping(context["consistency"]),
            scenario_id=context.get("scenario_id"),
        )
        call_field = CONTRACT_CALL_FIELD.get(operation)
        if call_field is None:
            # GetProvenance carries no contract call (contract :244-253): it is served by the
            # provenance contract registered in the active release, with no parameters.
            provenance = self._gateway.catalog.provenance_call()
            if provenance is None:
                raise C2Error("UNSUPPORTED_CAPABILITY", "no provenance contract is registered")
            contract_id, version, digest = provenance
            call = ContractCall(contract_id=contract_id, contract_version=version, contract_digest=digest,
                                parameters={})
        else:
            raw_call = body[call_field]
            call = ContractCall(contract_id=raw_call["contract_id"], contract_version=raw_call["contract_version"],
                                contract_digest=to_internal_digest(raw_call["contract_digest"]),
                                parameters=raw_call["parameters"])
        arguments = {key: value for key, value in body.items() if key not in {"context", call_field}}
        return TransportBoundQuery(principal=principal, query=NamedQueryCall(context=query_context, call=call)), arguments

    @staticmethod
    def _governed_only(errors: list[jsonschema.ValidationError]) -> bool:
        """True (POLICY_DENIED) only when every violation is an absent or empty governed-context
        field (ADD v1.3 :380); any other violation is SCHEMA_VIOLATION (contract :459)."""
        for error in errors:
            path = list(error.absolute_path)
            if error.validator == "required" and path == ["context"]:
                required: Any = error.validator_value
                instance: Any = error.instance
                missing = {name for name in required if name not in instance}
                if missing and missing <= GCS_WIRE_FIELDS:
                    continue
            if error.validator == "minLength" and path == ["context", "purpose"]:
                continue
            return False
        return True

    def _call(self, operation: str, bound: TransportBoundQuery, arguments: dict[str, Any]) -> GatewayAnswer:
        gateway = self._gateway
        if operation == "GetObject":
            return gateway.get_object(bound, object_ref=arguments["object_ref"])
        if operation == "QueryObjectSet":
            return gateway.query_object_set(bound, page_size=arguments["page_size"],
                                            page_token=arguments.get("page_token"))
        if operation == "Search":
            return gateway.search(bound, text=arguments["text"], page_size=arguments["page_size"],
                                  page_token=arguments.get("page_token"))
        if operation == "Traverse":
            return gateway.traverse(bound, start=tuple(arguments["start"]))
        if operation == "Explain":
            return gateway.explain(bound, target=arguments["target"], max_depth=arguments.get("max_depth", 5))
        return gateway.get_provenance(bound, target=arguments["target"], direction=arguments["direction"],
                                      max_depth=arguments["max_depth"],
                                      include_evidence=arguments.get("include_evidence", True))

    @staticmethod
    def _wire_response(answer: GatewayAnswer) -> dict[str, Any]:
        def convert(value: Any) -> Any:
            if isinstance(value, Mapping):
                result = {key: convert(item) for key, item in value.items()}
                schema = result.get("object_schema")
                if isinstance(schema, dict) and isinstance(schema.get("digest"), str):
                    schema["digest"] = to_wire_digest(schema["digest"])
                return result
            if isinstance(value, list | tuple):
                return [convert(item) for item in value]
            return value

        document: dict[str, Any] = {"served": served_document(answer.served)}
        document.update(convert(dict(answer.body)))
        return document
