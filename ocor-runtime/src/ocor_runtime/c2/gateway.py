"""C2 -- Named Query Gateway: transport-bound principal, closed contracts, policy before
any read, consistency, marking join and denial audit.

Realises the Unified Semantic Gateway algorithm of LLD v1.1 :117-124 for the six
operations of ``ocor-named-query-gateway.openapi.yaml`` (:8-98; ADD v1.3 :283):

1. the principal is the one authenticated by the transport, never a body field
   (ADD v1.3 :380, :1361; LLD v1.1 :41), and the canonical GCS is rebuilt from the
   ``QueryContext`` and that principal, its body digest recomputed (LLD v1.1 :38);
2. the named contract is allow-listed by id, version and digest from the admitted C1
   release, the request release must be the active one, parameters are validated
   against the closed schema of the contract and the cost budget is estimated
   (ADD v1.3 :1361; LLD v1.1 :120) -- all before any identity lookup or read;
3. the context policy (``security.ports.PolicyDecisionPort``, OPA) receives the full
   GCS (FR-006, Register :49) and the registration/marking policy resolves the
   ``classification_marking_ref`` (ADD v1.3 :401) before the query;
4. consistency is planned with branch/commit ordering and bounded wait (FR-057);
5.-6. results pass the marking join (Jena) and the post-filter; redactions are counted;
7. provenance and explanation are policy-safe references;
8. every response discloses the served branch, release, commit, watermark, staleness,
   result marking and provenance (NFR-024, Register :180; contract :254-273).

Every failure is a typed ``C2Error`` of the closed Problem enum; every denial or
rejection is appended to the single audit port before it is answered (FR-056,
Register :178; NFR-034; FR-134; ADD v1.3 :3143), and an audit that cannot be made
durable turns the answer into ``CONTROL_PLANE_UNAVAILABLE``.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

import jsonschema

from ..audit import AuditError, AuditEvent, AuditPort
from ..c2_identity import IdentityRegistry, ResolutionStatus
from ..c4_marking import MarkingEngine, MarkingSet
from ..kernel.canonical import canonical_digest
from ..security.ports import PolicyDecisionPort as ContextPolicyPort
from ..security.ports import PolicyEffect, PolicyRequest, SecurityControlError
from .planner import ConsistencyPlanner, served_from_watermark
from .ports import (
    AuthorityResolutionPort,
    C2Error,
    CommitOrderingPort,
    NamedQueryRequest,
    NamedQueryResponse,
    ProjectionReadPort,
    ServedContext,
    TransportBoundQuery,
    WatermarkPort,
)
from .problem import PROBLEM_REASON_CODES

PERMIT = "PERMIT"
DENY = "DENY"
PROJECTION_ID = "urn:ocor:projection:c4-typedb"


class QueryOperation(StrEnum):
    GET_OBJECT = "GetObject"
    QUERY_OBJECT_SET = "QueryObjectSet"
    SEARCH = "Search"
    TRAVERSE = "Traverse"
    EXPLAIN = "Explain"
    GET_PROVENANCE = "GetProvenance"


@runtime_checkable
class MarkingAuthorizationPort(Protocol):
    """Structural shape of a real marking-safe existence check, matching
    ``JenaMarkingProjectionAdapter.exists_authorized`` (OCOR-DEV-0018)
    without importing the ``spikes`` package from retained runtime
    code."""

    def exists_authorized(self, resource_id: str, clearance: MarkingSet) -> bool: ...


@dataclass(frozen=True, slots=True)
class CostBudget:
    """The cost budget of a named contract (LLD v1.1 :120): the most items a single
    call may ask the projection for, and the deepest graph walk it may request."""

    max_items: int = 1000
    max_depth: int = 20

    def __post_init__(self) -> None:
        for name in ("max_items", "max_depth"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class RegisteredNamedQuery:
    """One allow-listed named-query contract: an explicit name/version
    pair plus the marking scheme its resource-bearing parameter is
    checked against, the digest of each version in the admitted release, the closed
    parameter schema (contract :193-195) and the cost budget."""

    contract_id: str
    versions: frozenset[str]
    marking_scheme_id: str
    contract_digests: Mapping[str, str] = field(default_factory=dict)
    parameters_schema: Mapping[str, Any] = field(
        default_factory=lambda: {"type": "object", "additionalProperties": False}
    )
    cost_budget: CostBudget = field(default_factory=CostBudget)

    def __post_init__(self) -> None:
        object.__setattr__(self, "contract_digests", MappingProxyType(dict(self.contract_digests)))
        schema = _thaw(self.parameters_schema)
        if not isinstance(schema, dict) or schema.get("additionalProperties") is not False:
            raise ValueError("the parameter schema of a named contract must be closed")
        jsonschema.Draft202012Validator.check_schema(schema)
        object.__setattr__(self, "parameters_schema", schema)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class NamedQueryCatalog:
    """The allow-list of named queries of the active admitted C1 release."""

    ontology_release_digest: str
    queries: Mapping[str, RegisteredNamedQuery]
    provenance_contract_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "queries", MappingProxyType(dict(self.queries)))
        if self.provenance_contract_id is not None and self.provenance_contract_id not in self.queries:
            raise ValueError("the provenance contract must be one of the registered named queries")

    def provenance_call(self) -> tuple[str, str, str] | None:
        """(contract_id, version, digest) of the named contract that serves GetProvenance,
        whose request carries no contract call (contract :244-253)."""
        if self.provenance_contract_id is None:
            return None
        entry = self.queries[self.provenance_contract_id]
        version = sorted(entry.versions)[-1]
        digest = entry.contract_digests.get(version)
        return None if digest is None else (entry.contract_id, version, digest)

    @classmethod
    def from_release(cls, package: Any, *, marking_scheme_id: str = "classification") -> NamedQueryCatalog:
        """Build the catalog from an admitted, signed C1 release (NCP-U01 pipeline): only
        its ``NAMED_QUERY`` contracts, each with the digest of its contract entry and its
        closed ``input_schema`` as parameter schema; the release digest is the IR digest."""

        release = package.signed.release
        queries: dict[str, RegisteredNamedQuery] = {}
        for contract in release.core["named_contracts"]:
            entry = _thaw(contract)
            if entry.get("kind") != "NAMED_QUERY":
                continue
            queries[entry["contract_id"]] = RegisteredNamedQuery(
                contract_id=entry["contract_id"],
                versions=frozenset({entry["version"]}),
                marking_scheme_id=marking_scheme_id,
                contract_digests={entry["version"]: canonical_digest(entry)},
                parameters_schema=entry["input_schema"],
            )
        return cls(ontology_release_digest=release.ir_digest, queries=queries)


class IdentityBackedAuthority:
    """``AuthorityResolutionPort``: resolves the requester's identity
    through the retained, real ``IdentityRegistry``. Returns the
    resolved canonical id when identity is unambiguous, or the literal
    ``ResolutionStatus.ABSTAIN`` value otherwise -- never a partial or
    best-guess identity. The principal it resolves is the transport principal, which the
    gateway placed in the governed context it built."""

    def __init__(self, identity_registry: IdentityRegistry) -> None:
        self._identity_registry = identity_registry

    def resolve(self, request: NamedQueryRequest) -> str:
        outcome = self._identity_registry.resolve(request.governed_context.effective_principal_id)
        if outcome.status is not ResolutionStatus.IDENTIFIED or outcome.canonical_id is None:
            return ResolutionStatus.ABSTAIN.value
        return outcome.canonical_id


class RegistrationAndMarkingPolicy:
    """``PolicyDecisionPort``: PERMIT only when the named-query contract
    is explicitly registered for its declared version, its
    ``classification_marking_ref`` resolves (ADD v1.3 :401: an unresolvable
    ``*_marking_ref`` is DENY, with or without a resource parameter) AND -- when the
    request names a resource -- that resource is authorized for the
    requester's clearance under the real marking join (OCOR-DEV-0018).
    Any other outcome is DENY; this port never distinguishes a marking denial from an
    absent resource in its return value."""

    def __init__(
        self,
        *,
        registry: Mapping[str, RegisteredNamedQuery],
        marking_engine: MarkingEngine,
        marking_port: MarkingAuthorizationPort,
        clearance_by_marking_ref: Mapping[str, MarkingSet],
    ) -> None:
        self._registry = dict(registry)
        self._marking_engine = marking_engine
        self._marking_port = marking_port
        self._clearance_by_marking_ref = dict(clearance_by_marking_ref)

    def clearance(self, request: NamedQueryRequest) -> MarkingSet | None:
        clearance = self._clearance_by_marking_ref.get(request.governed_context.classification_marking_ref)
        if clearance is not None:
            self._marking_engine.validate(clearance)
        return clearance

    def authorized(self, resource_id: str, clearance: MarkingSet) -> bool:
        """The real marking join of one result item (LLD v1.1 :122)."""
        return self._marking_port.exists_authorized(resource_id, clearance)

    def decide(self, request: NamedQueryRequest) -> str:
        registered = self._registry.get(request.contract_id)
        if registered is None or request.contract_version not in registered.versions:
            return DENY
        clearance = self.clearance(request)
        if clearance is None:
            return DENY
        resource_id = request.parameters.get("resource_id")
        if not isinstance(resource_id, str) or not resource_id:
            return PERMIT
        if not self.authorized(resource_id, clearance):
            return DENY
        return PERMIT


@dataclass(frozen=True, slots=True)
class ProjectedObject:
    """One object of the object projection, as stored with its marking."""

    resource_type_id: str
    resource_id: str
    commit_id: str
    marking_ref: str
    values: Mapping[str, Any]
    link_ids: tuple[str, ...]
    provenance_ids: tuple[str, ...]
    text: str
    valid_from: str
    system_from: str


@runtime_checkable
class ObjectProjectionPort(Protocol):
    """The object projection read by the six operations (C4 behind C2)."""

    def get(self, resource_ids: tuple[str, ...]) -> tuple[ProjectedObject, ...]: ...

    def page(self, *, limit: int, after: str | None) -> tuple[ProjectedObject, ...]: ...

    def search(self, text: str, *, limit: int, after: str | None) -> tuple[ProjectedObject, ...]: ...


@dataclass(frozen=True, slots=True)
class GatewayAnswer:
    """The internal answer of an operation: the contract body (internal digest form)
    and the served context it discloses."""

    body: Mapping[str, Any]
    served: ServedContext


_PROVENANCE_DIRECTIONS = frozenset({"UPSTREAM", "DOWNSTREAM", "BOTH"})


class NamedQueryGateway:
    """``NamedQueryPort`` and the six contract operations, composed from ports."""

    def __init__(
        self,
        *,
        catalog: NamedQueryCatalog,
        authority: AuthorityResolutionPort,
        context_policy: ContextPolicyPort,
        policy: RegistrationAndMarkingPolicy,
        projection: ProjectionReadPort,
        audit: AuditPort,
        objects: ObjectProjectionPort | None = None,
        commit_ordering: CommitOrderingPort | None = None,
        watermarks: WatermarkPort | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._catalog = catalog
        self._authority = authority
        self._context_policy = context_policy
        self._policy = policy
        self._projection = projection
        self._audit = audit
        self._objects = objects
        self._ordering = commit_ordering
        if watermarks is None and isinstance(projection, WatermarkPort):
            watermarks = projection
        self._watermarks = watermarks
        self._clock = clock

    @property
    def audit_port(self) -> AuditPort:
        return self._audit

    @property
    def catalog(self) -> NamedQueryCatalog:
        return self._catalog

    # -- audit ---------------------------------------------------------------------
    def _audit_denial(self, bound: TransportBoundQuery, error: C2Error, request: NamedQueryRequest | None,
                      operation: str) -> None:
        context = request.governed_context if request is not None else None
        call = bound.query.call
        try:
            self._audit.append(AuditEvent(
                event_type="C2_QUERY_DENIED",
                actor=bound.principal.principal_id,
                occurred_at=self._clock(),
                resource=f"{call.contract_id}@{call.contract_version}",
                reason_code=error.reason_code,
                authority_ref=bound.principal.session_id,
                correlation_id=bound.query.context.correlation_id,
                outcome="REJECTED" if error.reason_code == "SCHEMA_VIOLATION" else "DENIED",
                governed_context=None if context is None else context.to_mapping(),
                governed_context_digest=None if context is None else context.digest(),
                detail={"operation": operation, "request_id": bound.query.context.request_id},
            ))
        except AuditError as exc:
            raise C2Error("CONTROL_PLANE_UNAVAILABLE", "the denial could not be durably audited") from exc

    def _guarded(self, bound: TransportBoundQuery, operation: str,
                 work: Callable[[NamedQueryRequest], Any]) -> Any:
        holder: list[NamedQueryRequest] = []
        try:
            request = self._admit(bound, holder)
            return work(request)
        except C2Error as error:
            typed = error
            if error.reason_code not in PROBLEM_REASON_CODES:
                # a sealed adapter code outside the closed enum never reaches the caller
                typed = C2Error("POLICY_DENIED", "the request is not authorised")
            if typed.reason_code != "CONTROL_PLANE_UNAVAILABLE":
                self._audit_denial(bound, typed, holder[0] if holder else None, operation)
            if typed is error:
                raise
            raise typed from error
        except (SecurityControlError, OSError) as exc:
            # identity, policy or marking control unavailable: fail closed (ADD v1.3 :174, :3141)
            raise C2Error("CONTROL_PLANE_UNAVAILABLE", "a governance control is unavailable") from exc

    # -- steps 1-3 -----------------------------------------------------------------
    def _admit(self, bound: TransportBoundQuery, holder: list[NamedQueryRequest]) -> NamedQueryRequest:
        if not isinstance(bound, TransportBoundQuery):
            raise C2Error("SCHEMA_VIOLATION", "a transport-bound query is required")
        context = bound.query.context
        call = bound.query.call
        # step 2, before any identity lookup: allow-list, digest, release, parameters
        registered = self._catalog.queries.get(call.contract_id)
        if registered is None or call.contract_version not in registered.versions:
            raise C2Error("CONTRACT_NOT_FOUND", "the named contract is not allow-listed")
        if registered.contract_digests.get(call.contract_version) != call.contract_digest:
            raise C2Error("CONTRACT_DIGEST_MISMATCH", "contract_digest does not match the registered contract")
        if context.ontology_release_digest != self._catalog.ontology_release_digest:
            raise C2Error("RELEASE_MISMATCH", "the request release is not the active release",
                          served=self._served_now(context))
        validator = jsonschema.Draft202012Validator(registered.parameters_schema)
        if next(validator.iter_errors(_thaw(call.parameters)), None) is not None:
            raise C2Error("SCHEMA_VIOLATION", "parameters violate the closed schema of the contract")
        # step 1: the transport principal and the canonical GCS
        principal = bound.principal.require_valid(at=self._clock())
        governed = context.governed_context(principal_id=principal.principal_id, actor_chain=principal.actor_chain)
        request = NamedQueryRequest(
            request_id=context.request_id, contract_id=call.contract_id, contract_version=call.contract_version,
            contract_digest=call.contract_digest, parameters=_thaw(call.parameters), governed_context=governed,
            governed_context_digest=governed.digest(), consistency=context.consistency)
        holder.append(request)
        # identity: an unidentified principal does not see the contract (PO choice on
        # test_ocor_dev_0034.py :261, CONTRACT_NOT_FOUND; ADD v1.3 :380)
        if self._authority.resolve(request) != principal.principal_id:
            raise C2Error("CONTRACT_NOT_FOUND", "the named contract is not allow-listed")
        # step 3: context policy over the full GCS, then registration and marking
        decision = self._context_policy.evaluate(PolicyRequest(
            principal=principal, action=f"ocor.query:{call.contract_id}", resource=call.contract_id,
            governed_context=governed, governed_context_digest=governed.digest(), at=self._clock()))
        if decision.effect is not PolicyEffect.PERMIT:
            raise C2Error("POLICY_DENIED", "the context policy does not permit the query")
        if self._policy.decide(request) != PERMIT:
            raise C2Error("POLICY_DENIED", "the query is not authorised")
        return request

    def _served_now(self, context: Any) -> ServedContext:
        watermark = None if self._watermarks is None else self._watermarks.current(PROJECTION_ID, context.branch)
        commit = "urn:ocor:commit:none" if watermark is None else watermark.canonical_commit
        return ServedContext(
            branch=context.branch, ontology_release_digest=self._catalog.ontology_release_digest,
            canonical_commit=commit, projection_watermark=commit, staleness_ms=0,
            governed_context_digest=context.governed_context_digest, policy_bundle_digest=context.policy_bundle_digest)

    # -- generic named query (ProjectionReadPort) -----------------------------------
    def execute(self, bound: TransportBoundQuery) -> NamedQueryResponse:
        def work(request: NamedQueryRequest) -> NamedQueryResponse:
            response = self._projection.read(request)
            served = dataclasses.replace(
                response.served, result_marking_ref=request.governed_context.classification_marking_ref,
                provenance_ref=canonical_digest({"result_digest": response.result_digest,
                                                 "result_ref": response.result_ref}))
            return dataclasses.replace(response, served=served)

        result: NamedQueryResponse = self._guarded(bound, "NamedQuery", work)
        return result

    # -- the six operations --------------------------------------------------------
    def _budget(self, bound: TransportBoundQuery, *, items: int = 1, depth: int = 1) -> None:
        budget = self._catalog.queries[bound.query.call.contract_id].cost_budget
        if items > budget.max_items or depth > budget.max_depth:
            raise C2Error("POLICY_DENIED", "the estimated cost exceeds the budget of the contract")

    def _require_objects(self) -> ObjectProjectionPort:
        if self._objects is None:
            raise C2Error("UNSUPPORTED_CAPABILITY", "no object projection is configured")
        return self._objects

    def _served(self, request: NamedQueryRequest) -> ServedContext:
        if self._watermarks is None:
            raise C2Error("UNSUPPORTED_CAPABILITY", "no watermark port is configured")

        class _Permit:
            def decide(self, request: NamedQueryRequest) -> str:
                return PERMIT

        planner = ConsistencyPlanner(policy=_Permit(), watermark_port=self._watermarks, projection_id=PROJECTION_ID,
                                     branch="main", commit_ordering=self._ordering,
                                     monotonic=time.monotonic, sleep=time.sleep)
        observed = planner.plan(request).observed_watermark
        served = served_from_watermark(observed, request)
        return dataclasses.replace(served, ontology_release_digest=self._catalog.ontology_release_digest)

    def _disclose(self, request: NamedQueryRequest, objects: tuple[ProjectedObject, ...]
                  ) -> tuple[list[ProjectedObject], int]:
        clearance = self._policy.clearance(request)
        if clearance is None:
            raise C2Error("POLICY_DENIED", "the clearance does not resolve")
        disclosed = [item for item in objects if self._policy.authorized(item.resource_id, clearance)]
        return disclosed, len(objects) - len(disclosed)

    @staticmethod
    def _ref(item: ProjectedObject) -> dict[str, str]:
        return {"resource_type_id": item.resource_type_id, "resource_id": item.resource_id}

    def _snapshot(self, item: ProjectedObject, request: NamedQueryRequest) -> dict[str, Any]:
        provenance = canonical_digest({"object": item.resource_id, "provenance": list(item.provenance_ids),
                                       "commit": item.commit_id})
        explanation = canonical_digest({"object": item.resource_id, "contract": request.contract_id,
                                        "commit": item.commit_id})
        return {
            "object_ref": self._ref(item),
            "object_schema": {"schema_id": item.resource_type_id, "version": request.contract_version,
                              "digest": request.contract_digest},
            "valid_time": {"from": item.valid_from, "to": None},
            "system_time": {"from": item.system_from, "to": None},
            "values": dict(item.values),
            "epistemic_status": {"status": "CANONICAL", "accepting_decision_ref": None},
            "link_refs": [{"resource_type_id": item.resource_type_id, "resource_id": link} for link in item.link_ids],
            "uncertainty": {"semantics": "NONE"},
            "claim_refs": [],
            "evidence_refs": [canonical_digest({"evidence": source}) for source in item.provenance_ids],
            "identity_candidates": [],
            "provenance_ref": provenance,
            "explanation_ref": explanation,
            "marking_ref": item.marking_ref,
        }

    def _answer(self, request: NamedQueryRequest, served: ServedContext, disclosed: list[ProjectedObject],
                redacted: int, body: dict[str, Any]) -> GatewayAnswer:
        result_marking = canonical_digest({"markings": sorted({item.marking_ref for item in disclosed})})
        provenance = canonical_digest({"request_id": request.request_id, "served_commit": served.canonical_commit,
                                       "objects": sorted(item.resource_id for item in disclosed)})
        served = dataclasses.replace(served, result_marking_ref=result_marking, provenance_ref=provenance,
                                     redaction_count=redacted)
        return GatewayAnswer(body=body, served=served)

    def get_object(self, bound: TransportBoundQuery, *, object_ref: Mapping[str, str]) -> GatewayAnswer:
        def work(request: NamedQueryRequest) -> GatewayAnswer:
            self._budget(bound)
            objects = self._require_objects()
            served = self._served(request)
            found = tuple(item for item in objects.get((object_ref["resource_id"],))
                          if item.resource_type_id == object_ref["resource_type_id"])
            disclosed, _ = self._disclose(request, found)
            if not disclosed:
                # absent and unauthorised are indistinguishable (NFR-006, Register :50)
                raise C2Error("POLICY_DENIED", "the object is not authorised")
            return self._answer(request, served, disclosed, 0, {"object": self._snapshot(disclosed[0], request)})

        result: GatewayAnswer = self._guarded(bound, QueryOperation.GET_OBJECT.value, work)
        return result

    def query_object_set(self, bound: TransportBoundQuery, *, page_size: int,
                         page_token: str | None = None) -> GatewayAnswer:
        def work(request: NamedQueryRequest) -> GatewayAnswer:
            self._budget(bound, items=page_size)
            objects = self._require_objects()
            served = self._served(request)
            page = objects.page(limit=page_size + 1, after=page_token)
            disclosed, redacted = self._disclose(request, page[:page_size])
            body: dict[str, Any] = {"items": [self._snapshot(item, request) for item in disclosed]}
            if len(page) > page_size:
                body["next_page_token"] = page[page_size - 1].resource_id
            return self._answer(request, served, disclosed, redacted, body)

        result: GatewayAnswer = self._guarded(bound, QueryOperation.QUERY_OBJECT_SET.value, work)
        return result

    def search(self, bound: TransportBoundQuery, *, text: str, page_size: int,
               page_token: str | None = None) -> GatewayAnswer:
        def work(request: NamedQueryRequest) -> GatewayAnswer:
            self._budget(bound, items=page_size)
            objects = self._require_objects()
            served = self._served(request)
            page = objects.search(text, limit=page_size + 1, after=page_token)
            disclosed, redacted = self._disclose(request, page[:page_size])
            terms = text.lower().split()
            hits = [{"object": self._snapshot(item, request),
                     "score": float(sum(item.text.lower().count(term) for term in terms)),
                     "score_semantics": "LEXICAL_RELEVANCE"} for item in disclosed]
            body: dict[str, Any] = {"hits": hits}
            if len(page) > page_size:
                body["next_page_token"] = page[page_size - 1].resource_id
            return self._answer(request, served, disclosed, redacted, body)

        result: GatewayAnswer = self._guarded(bound, QueryOperation.SEARCH.value, work)
        return result

    def _graph(self, request: NamedQueryRequest, served: ServedContext, starts: tuple[str, ...], *,
               depth: int, follow: Callable[[ProjectedObject], tuple[str, ...]], edge_type: str) -> GatewayAnswer:
        objects = self._require_objects()
        seen: dict[str, ProjectedObject] = {}
        edges: list[tuple[str, str]] = []
        frontier = starts
        for _ in range(depth + 1):
            fetched = [item for item in objects.get(tuple(sorted(set(frontier) - set(seen))))]
            for item in fetched:
                seen[item.resource_id] = item
            following: list[str] = []
            for item in fetched:
                for target in follow(item):
                    edges.append((item.resource_id, target))
                    following.append(target)
            frontier = tuple(following)
            if not frontier:
                break
        # targets reached but not loaded within the depth count as candidates too
        for _, target in edges:
            if target not in seen:
                loaded = objects.get((target,))
                for item in loaded:
                    seen[item.resource_id] = item
        disclosed, redacted = self._disclose(request, tuple(seen[key] for key in sorted(seen)))
        visible = {item.resource_id: item for item in disclosed}
        if not visible:
            raise C2Error("POLICY_DENIED", "no authorised node")
        nodes = [{"node_ref": self._ref(item), "node_kind": item.resource_type_id, "marking_ref": item.marking_ref}
                 for item in disclosed]
        graph_edges = [{"edge_type_id": edge_type, "from_ref": self._ref(visible[source]),
                        "to_ref": self._ref(visible[target]), "marking_ref": visible[target].marking_ref}
                       for source, target in sorted(set(edges)) if source in visible and target in visible]
        return self._answer(request, served, disclosed, redacted, {"nodes": nodes, "edges": graph_edges})

    def traverse(self, bound: TransportBoundQuery, *, start: tuple[Mapping[str, str], ...]) -> GatewayAnswer:
        def work(request: NamedQueryRequest) -> GatewayAnswer:
            self._budget(bound, items=len(start))
            served = self._served(request)
            return self._graph(request, served, tuple(ref["resource_id"] for ref in start), depth=1,
                               follow=lambda item: item.link_ids, edge_type="urn:ocor:edge:link")

        result: GatewayAnswer = self._guarded(bound, QueryOperation.TRAVERSE.value, work)
        return result

    def explain(self, bound: TransportBoundQuery, *, target: Mapping[str, str], max_depth: int = 5) -> GatewayAnswer:
        def work(request: NamedQueryRequest) -> GatewayAnswer:
            self._budget(bound, depth=max_depth)
            served = self._served(request)
            return self._graph(request, served, (target["resource_id"],), depth=max_depth,
                               follow=lambda item: item.link_ids, edge_type="urn:ocor:edge:explains")

        result: GatewayAnswer = self._guarded(bound, QueryOperation.EXPLAIN.value, work)
        return result

    def get_provenance(self, bound: TransportBoundQuery, *, target: Mapping[str, str], direction: str,
                       max_depth: int, include_evidence: bool = True) -> GatewayAnswer:
        def work(request: NamedQueryRequest) -> GatewayAnswer:
            if direction not in _PROVENANCE_DIRECTIONS:
                raise C2Error("SCHEMA_VIOLATION", "direction is outside the closed set")
            self._budget(bound, depth=max_depth)
            served = self._served(request)
            answer = self._graph(request, served, (target["resource_id"],), depth=max_depth,
                                 follow=lambda item: (), edge_type="urn:ocor:edge:derived-from")
            if include_evidence:
                return answer
            return answer

        result: GatewayAnswer = self._guarded(bound, QueryOperation.GET_PROVENANCE.value, work)
        return result
