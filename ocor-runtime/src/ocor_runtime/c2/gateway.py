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

Every failure is a typed ``C2Error`` of the closed Problem enum; every denial, rejection
or failure is appended to the single audit port before it is answered (FR-056,
Register :178; NFR-034; FR-134; ADD v1.3 :3143), and an audit that cannot be made
durable turns the answer into ``CONTROL_PLANE_UNAVAILABLE``. The context-policy decision
is verified against the very request before it permits anything (ADD v1.3 :3141); an
invalid transport identity is ``AUTHORITY_MISSING``, an unavailable control
``CONTROL_PLANE_UNAVAILABLE`` (ADD v1.3 :174). The marking join precedes paging and graph
expansion: pages, tokens and walks are built from authorised objects only, and a
withheld node is never expanded (LLD v1.1 :121-122; NFR-006, Register :50). The requested
branch and scenario reach the planned read; a branch or scenario the projections do not
serve is ``UNSUPPORTED_CAPABILITY``, never answered from ``main`` (LLD v1.1 :124, :126).
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, NoReturn, Protocol, runtime_checkable

import jsonschema

from ..audit import AuditError, AuditEvent, AuditPort
from ..c2_identity import IdentityRegistry, ResolutionStatus
from ..c4.typedb_adapter import TypeDBUnavailableError
from ..c4.watermark import ConfirmedWatermark
from ..c4_marking import MarkingEngine, MarkingSet
from ..kernel.canonical import canonical_digest
from ..security.ports import PolicyDecisionPort as ContextPolicyPort
from ..security.ports import PolicyDecision, PolicyEffect, PolicyRequest, SecurityControlError
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
from .problem import PROBLEM_REASON_CODES, SERVED_REQUIRED

PERMIT = "PERMIT"
DENY = "DENY"
PROJECTION_ID = "urn:ocor:projection:c4-typedb"
# Branches the C4 projections serve (the canonical projection of ``main``).
SERVED_BRANCHES = frozenset({"main"})
NO_WATERMARK = "urn:ocor:commit:none"
# Refusals of the transport identity itself (security.ports.AuthenticatedPrincipal and
# PolicyRequest bindings): the request has no valid authority, which is AUTHORITY_MISSING
# (contract :455), not an outage. Every other security-control failure -- an unavailable
# control or a policy decision that cannot be verified for the request -- is
# CONTROL_PLANE_UNAVAILABLE on a read (ADD v1.3 :174, :3141).
AUTHENTICATION_REFUSALS = frozenset({
    "IDENTITY_EXPIRED", "ANONYMOUS_IDENTITY_FORBIDDEN", "IDENTITY_BINDING_MISMATCH", "PRINCIPAL_BINDING_MISMATCH",
})


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
        served_branches: frozenset[str] = SERVED_BRANCHES,
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
        self._branches = frozenset(served_branches)

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
                outcome=_OUTCOME.get(error.reason_code, "DENIED"),
                governed_context=None if context is None else context.to_mapping(),
                governed_context_digest=None if context is None else context.digest(),
                detail={"operation": operation, "request_id": bound.query.context.request_id},
            ))
        except AuditError as exc:
            raise C2Error("CONTROL_PLANE_UNAVAILABLE", "the denial could not be durably audited") from exc

    def _guarded(self, bound: TransportBoundQuery, operation: str,
                 work: Callable[[NamedQueryRequest], Any]) -> Any:
        if not isinstance(bound, TransportBoundQuery):
            # no transport principal: nothing in a body can stand in for it (ADD v1.3 :380)
            raise C2Error("SCHEMA_VIOLATION", "a transport-bound query is required")
        holder: list[NamedQueryRequest] = []
        try:
            request = self._admit(bound, holder)
            return work(request)
        except C2Error as error:
            if error.reason_code in SERVED_REQUIRED and error.served is None:
                # a projection port that is down has no request: the Gateway builds the served
                # context of the confirmed watermark (ADD v1.3 :1364, :3406; NCR-C2-013)
                self._refuse(bound, holder, operation, self._projection_down(holder, error.detail), error)
            self._refuse(bound, holder, operation, error, error)
        except SecurityControlError as exc:
            refusal = C2Error("AUTHORITY_MISSING" if exc.reason_code in AUTHENTICATION_REFUSALS
                              else "CONTROL_PLANE_UNAVAILABLE", "the governance controls refused the request")
            self._refuse(bound, holder, operation, refusal, exc)
        except TypeDBUnavailableError as exc:  # the watermark port: the projection is down (ADD v1.3 :3406)
            self._refuse(bound, holder, operation, self._not_ready(holder, str(exc), exc.confirmed), exc)
        except Exception as exc:  # a port failed outside its typed contract: fail closed (ADD v1.3 :174)
            self._refuse(bound, holder, operation,
                         C2Error("CONTROL_PLANE_UNAVAILABLE", "a governance control or projection is unavailable"), exc)

    def _projection_down(self, holder: list[NamedQueryRequest], message: str) -> C2Error:
        """``PROJECTION_NOT_READY`` of a projection port that is down, with the served context of
        the watermark the watermark port reports as confirmed; a watermark port that cannot say is
        the typed fail-closed ``CONTROL_PLANE_UNAVAILABLE``."""
        if not holder or self._watermarks is None:
            return C2Error("CONTROL_PLANE_UNAVAILABLE", "a governance control or projection is unavailable")
        request = holder[0]
        try:
            observed = self._watermarks.current(PROJECTION_ID, request.branch)
        except TypeDBUnavailableError as exc:
            return self._not_ready(holder, message, exc.confirmed)
        except Exception:  # the watermark port failed outside its typed contract (ADD v1.3 :174)
            return C2Error("CONTROL_PLANE_UNAVAILABLE", "a governance control or projection is unavailable")
        try:
            if observed.branch != request.branch:
                raise C2Error("CONTROL_PLANE_UNAVAILABLE", "the watermark names another branch")
            served = dataclasses.replace(served_from_watermark(observed, request),
                                         ontology_release_digest=self._catalog.ontology_release_digest)
        except (C2Error, AttributeError, TypeError, ValueError):
            return C2Error("CONTROL_PLANE_UNAVAILABLE", "a governance control or projection is unavailable")
        return C2Error("PROJECTION_NOT_READY", message, served=served)

    def _not_ready(self, holder: list[NamedQueryRequest], message: str,
                   confirmed: ConfirmedWatermark | None) -> C2Error:
        """``PROJECTION_NOT_READY`` with the served context of the last watermark C4 confirmed
        durably and the staleness from its instant (ADD v1.3 :1364); without a confirmed watermark
        the served commit is the no-watermark sentinel and the release the active one, never a
        fabricated commit. A confirmed watermark of another branch, or one that does not form a
        served context, is the typed fail-closed ``CONTROL_PLANE_UNAVAILABLE``."""
        if not holder:
            return C2Error("CONTROL_PLANE_UNAVAILABLE", "a governance control or projection is unavailable")
        request = holder[0]
        try:
            if confirmed is None:
                commit, release, staleness = NO_WATERMARK, self._catalog.ontology_release_digest, 0
            else:
                if confirmed.branch != request.branch:
                    raise C2Error("CONTROL_PLANE_UNAVAILABLE", "the confirmed watermark names another branch")
                commit, release = confirmed.commit_id, confirmed.release_digest
                staleness = max(0, int((self._clock() - confirmed.confirmed_at).total_seconds() * 1000))
            served = ServedContext(
                branch=request.branch, ontology_release_digest=release, canonical_commit=commit,
                projection_watermark=commit, staleness_ms=staleness,
                governed_context_digest=request.governed_context_digest,
                policy_bundle_digest=request.governed_context.policy_bundle_digest)
        except (C2Error, AttributeError, TypeError, ValueError, OverflowError):
            return C2Error("CONTROL_PLANE_UNAVAILABLE", "a governance control or projection is unavailable")
        return C2Error("PROJECTION_NOT_READY", message, served=served)

    def _refuse(self, bound: TransportBoundQuery, holder: list[NamedQueryRequest], operation: str,
                error: C2Error, cause: BaseException) -> NoReturn:
        typed = error
        if error.reason_code not in PROBLEM_REASON_CODES:
            # a sealed adapter code outside the closed enum never reaches the caller
            typed = C2Error("POLICY_DENIED", "the request is not authorised")
        self._audit_denial(bound, typed, holder[0] if holder else None, operation)
        if typed is cause:
            raise typed
        raise typed from cause

    # -- steps 1-3 -----------------------------------------------------------------
    def _admit(self, bound: TransportBoundQuery, holder: list[NamedQueryRequest]) -> NamedQueryRequest:
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
            governed_context_digest=governed.digest(), consistency=context.consistency, branch=context.branch,
            logic_version=context.logic_version, scenario_id=context.scenario_id)
        holder.append(request)
        # identity: an unidentified principal does not see the contract (PO choice on
        # test_ocor_dev_0034.py :261, CONTRACT_NOT_FOUND; ADD v1.3 :380)
        if self._authority.resolve(request) != principal.principal_id:
            raise C2Error("CONTRACT_NOT_FOUND", "the named contract is not allow-listed")
        # step 3: context policy over the full GCS -- a decision counts only if it binds this
        # very request within its validity (ADD v1.3 :3141) -- then registration and marking
        policy_request = PolicyRequest(
            principal=principal, action=f"ocor.query:{call.contract_id}", resource=call.contract_id,
            governed_context=governed, governed_context_digest=governed.digest(), at=self._clock())
        decision = self._context_policy.evaluate(policy_request)
        if not isinstance(decision, PolicyDecision):
            raise SecurityControlError("POLICY_DECISION_INVALID", "the context policy returned no decision")
        decision.verify(policy_request, at=self._clock())
        if decision.effect is not PolicyEffect.PERMIT:
            raise C2Error("POLICY_DENIED", "the context policy does not permit the query")
        if self._policy.decide(request) != PERMIT:
            raise C2Error("POLICY_DENIED", "the query is not authorised")
        # step 4 starts with the projection: only the branches it serves, never a scenario
        # world answered from main (LLD v1.1 :124, :126)
        if request.branch not in self._branches or request.scenario_id is not None:
            raise C2Error("UNSUPPORTED_CAPABILITY", "the projection does not serve the requested branch or scenario")
        return request

    def _served_now(self, context: Any) -> ServedContext:
        served_branch = context.branch in self._branches and context.scenario_id is None
        watermark = None if self._watermarks is None or not served_branch else self._watermarks.current(
            PROJECTION_ID, context.branch)
        commit = NO_WATERMARK if watermark is None else watermark.canonical_commit
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
                                     branch=request.branch, commit_ordering=self._ordering,
                                     monotonic=time.monotonic, sleep=time.sleep)
        observed = planner.plan(request).observed_watermark
        served = dataclasses.replace(served_from_watermark(observed, request),
                                     ontology_release_digest=self._catalog.ontology_release_digest)
        if served.branch != request.branch:
            raise C2Error("STALE_CONTEXT", "the served branch is not the requested branch", served=served)
        return served

    def _disclosure(self, request: NamedQueryRequest) -> _Disclosure:
        clearance = self._policy.clearance(request)
        if clearance is None:
            raise C2Error("POLICY_DENIED", "the clearance does not resolve")
        return _Disclosure(self._policy, clearance)

    @staticmethod
    def _ref(resource_type_id: str, resource_id: str) -> dict[str, str]:
        return {"resource_type_id": resource_type_id, "resource_id": resource_id}

    def _snapshot(self, item: ProjectedObject, request: NamedQueryRequest, disclosure: _Disclosure) -> dict[str, Any]:
        """``ObjectSnapshot`` (contract :313-362, FR-007): links to resources the clearance
        does not authorise are withheld and counted, never shown as references."""
        provenance = canonical_digest({"object": item.resource_id, "provenance": list(item.provenance_ids),
                                       "commit": item.commit_id})
        explanation = canonical_digest({"object": item.resource_id, "contract": request.contract_id,
                                        "commit": item.commit_id})
        links = [link for link in item.link_ids if disclosure.allows(link)]
        return {
            "object_ref": self._ref(item.resource_type_id, item.resource_id),
            "object_schema": {"schema_id": item.resource_type_id, "version": request.contract_version,
                              "digest": request.contract_digest},
            "valid_time": {"from": item.valid_from, "to": None},
            "system_time": {"from": item.system_from, "to": None},
            "values": dict(item.values),
            "epistemic_status": {"status": "CANONICAL", "accepting_decision_ref": None},
            "link_refs": [self._ref(item.resource_type_id, link) for link in links],
            "uncertainty": {"semantics": "NONE"},
            "claim_refs": [],
            "evidence_refs": [evidence_ref(item.resource_id, source) for source in item.provenance_ids],
            "identity_candidates": [],
            "provenance_ref": provenance,
            "explanation_ref": explanation,
            "marking_ref": item.marking_ref,
        }

    def _answer(self, request: NamedQueryRequest, served: ServedContext, disclosure: _Disclosure,
                body: dict[str, Any]) -> GatewayAnswer:
        """Step 8 (LLD v1.1 :124): the served context with the result marking join, the
        provenance of the answer and the number of withheld resources."""
        result_marking = canonical_digest({"markings": sorted(disclosure.markings)})
        provenance = canonical_digest({"request_id": request.request_id, "served_commit": served.canonical_commit,
                                       "objects": sorted(disclosure.disclosed)})
        served = dataclasses.replace(served, result_marking_ref=result_marking, provenance_ref=provenance,
                                     redaction_count=len(disclosure.withheld))
        return GatewayAnswer(body=body, served=served)

    def get_object(self, bound: TransportBoundQuery, *, object_ref: Mapping[str, str]) -> GatewayAnswer:
        def work(request: NamedQueryRequest) -> GatewayAnswer:
            self._budget(bound)
            objects = self._require_objects()
            served = self._served(request)
            disclosure = self._disclosure(request)
            found = [item for item in objects.get((object_ref["resource_id"],))
                     if item.resource_type_id == object_ref["resource_type_id"] and disclosure.admit(item)]
            if not found:
                # absent and unauthorised are indistinguishable (NFR-006, Register :50)
                raise C2Error("POLICY_DENIED", "the object is not authorised")
            body = {"object": self._snapshot(found[0], request, disclosure)}
            return self._answer(request, served, disclosure, body)

        result: GatewayAnswer = self._guarded(bound, QueryOperation.GET_OBJECT.value, work)
        return result

    def _page(self, bound: TransportBoundQuery, operation: QueryOperation, page_size: int, page_token: str | None,
              fetch: Callable[[ObjectProjectionPort, int, str | None], tuple[ProjectedObject, ...]],
              shape: Callable[[ProjectedObject, NamedQueryRequest, _Disclosure], dict[str, Any]],
              key: str) -> GatewayAnswer:
        """A page holds the first ``page_size`` authorised objects after the token: the
        marking join runs before the page is cut, the token is the last authorised object
        returned, and it is issued only when a further authorised object exists -- so neither
        an identifier nor the existence of a withheld object past the page is disclosed
        (LLD v1.1 :121-122, :126; NFR-006, Register :50). Withheld objects between the first
        and the last returned object are counted as redactions (contract :322)."""

        def work(request: NamedQueryRequest) -> GatewayAnswer:
            self._budget(bound, items=page_size)
            objects = self._require_objects()
            served = self._served(request)
            disclosure = self._disclosure(request)
            visible: list[ProjectedObject] = []
            pending: list[str] = []
            more = False
            cursor = page_token
            while not more:
                batch = fetch(objects, page_size + 1, cursor)
                for item in batch:
                    if not disclosure.authorized(item.resource_id):
                        pending.append(item.resource_id)
                    elif len(visible) == page_size:
                        more = True
                        break
                    else:
                        for withheld in pending:
                            disclosure.withhold(withheld)
                        pending.clear()
                        visible.append(item)
                if len(batch) <= page_size:
                    break
                cursor = batch[-1].resource_id
            for item in visible:
                disclosure.admit(item)
            body: dict[str, Any] = {key: [shape(item, request, disclosure) for item in visible]}
            if more:
                body["next_page_token"] = visible[-1].resource_id
            return self._answer(request, served, disclosure, body)

        result: GatewayAnswer = self._guarded(bound, operation.value, work)
        return result

    def query_object_set(self, bound: TransportBoundQuery, *, page_size: int,
                         page_token: str | None = None) -> GatewayAnswer:
        return self._page(bound, QueryOperation.QUERY_OBJECT_SET, page_size, page_token,
                          lambda objects, limit, after: objects.page(limit=limit, after=after),
                          self._snapshot, "items")

    def search(self, bound: TransportBoundQuery, *, text: str, page_size: int,
               page_token: str | None = None) -> GatewayAnswer:
        terms = text.lower().split()

        def hit(item: ProjectedObject, request: NamedQueryRequest, disclosure: _Disclosure) -> dict[str, Any]:
            # PoC profile: lexical relevance only; VECTOR_SIMILARITY and HYBRID_RANK are
            # UNSUPPORTED_CAPABILITY while ELM-011 is deferred (ADD v1.3 :1361).
            return {"object": self._snapshot(item, request, disclosure),
                    "score": float(sum(item.text.lower().count(term) for term in terms)),
                    "score_semantics": "LEXICAL_RELEVANCE"}

        return self._page(bound, QueryOperation.SEARCH, page_size, page_token,
                          lambda objects, limit, after: objects.search(text, limit=limit, after=after), hit, "hits")

    def _roots(self, refs: tuple[Mapping[str, str], ...], disclosure: _Disclosure) -> dict[str, ProjectedObject]:
        """The requested start objects that exist with the requested type and that the
        clearance authorises; any other start is absent -- not shown and not counted, so a
        withheld start is indistinguishable from a missing one (NFR-006, Register :50)."""
        wanted = {ref["resource_id"]: ref["resource_type_id"] for ref in refs}
        return {item.resource_id: item for item in self._require_objects().get(tuple(sorted(wanted)))
                if wanted.get(item.resource_id) == item.resource_type_id and disclosure.authorized(item.resource_id)}

    def _walk(self, roots: dict[str, ProjectedObject], depth: int,
              follow: Callable[[ProjectedObject], tuple[str, ...]], disclosure: _Disclosure
              ) -> tuple[dict[str, ProjectedObject], list[tuple[str, str]]]:
        """Breadth-first walk that expands only authorised nodes: a withheld node may be
        reached (and is then counted as a redaction) but its links are never followed."""
        objects = self._require_objects()
        seen = dict(roots)
        edges: list[tuple[str, str]] = []
        frontier = tuple(sorted(roots))
        for level in range(depth):
            following: list[str] = []
            for key in frontier:
                if key in seen and disclosure.authorized(key):
                    for target in follow(seen[key]):
                        edges.append((key, target))
                        following.append(target)
            frontier = tuple(sorted(set(following) - set(seen)))
            if not frontier:
                break
            for item in objects.get(frontier):
                seen[item.resource_id] = item
        return seen, edges

    def _graph_answer(self, request: NamedQueryRequest, served: ServedContext, disclosure: _Disclosure,
                      seen: dict[str, ProjectedObject], edges: list[tuple[str, str]], edge_type: str,
                      extra_nodes: list[dict[str, Any]] | None = None,
                      extra_edges: list[dict[str, Any]] | None = None) -> GatewayAnswer:
        visible = {key: item for key, item in sorted(seen.items()) if disclosure.admit(item)}
        for _, target in edges:
            if target not in seen:
                disclosure.withhold(target)  # dangling or not loaded within the bound: never shown
        if not visible:
            raise C2Error("POLICY_DENIED", "no authorised node")
        nodes = [{"node_ref": self._ref(item.resource_type_id, key), "node_kind": item.resource_type_id,
                  "marking_ref": item.marking_ref} for key, item in visible.items()]
        graph_edges = [{"edge_type_id": edge_type,
                        "from_ref": self._ref(visible[source].resource_type_id, source),
                        "to_ref": self._ref(visible[target].resource_type_id, target),
                        "marking_ref": visible[target].marking_ref}
                       for source, target in sorted(set(edges)) if source in visible and target in visible]
        body = {"nodes": nodes + (extra_nodes or []), "edges": graph_edges + (extra_edges or [])}
        return self._answer(request, served, disclosure, body)

    def traverse(self, bound: TransportBoundQuery, *, start: tuple[Mapping[str, str], ...]) -> GatewayAnswer:
        def work(request: NamedQueryRequest) -> GatewayAnswer:
            self._budget(bound, items=len(start))
            served = self._served(request)
            disclosure = self._disclosure(request)
            seen, edges = self._walk(self._roots(start, disclosure), 1, lambda item: item.link_ids, disclosure)
            return self._graph_answer(request, served, disclosure, seen, edges, "urn:ocor:edge:link")

        result: GatewayAnswer = self._guarded(bound, QueryOperation.TRAVERSE.value, work)
        return result

    def explain(self, bound: TransportBoundQuery, *, target: Mapping[str, str], max_depth: int = 5) -> GatewayAnswer:
        def work(request: NamedQueryRequest) -> GatewayAnswer:
            self._budget(bound, depth=max_depth)
            served = self._served(request)
            disclosure = self._disclosure(request)
            seen, edges = self._walk(self._roots((target,), disclosure), max_depth, lambda item: item.link_ids,
                                     disclosure)
            return self._graph_answer(request, served, disclosure, seen, edges, "urn:ocor:edge:explains")

        result: GatewayAnswer = self._guarded(bound, QueryOperation.EXPLAIN.value, work)
        return result

    def get_provenance(self, bound: TransportBoundQuery, *, target: Mapping[str, str], direction: str,
                       max_depth: int, include_evidence: bool = True) -> GatewayAnswer:
        """``GetProvenance`` (contract :244-253): UPSTREAM follows the provenance of the
        target (and, with ``include_evidence``, its evidence nodes); DOWNSTREAM the objects
        derived from it; BOTH the union -- always after the marking join."""

        def work(request: NamedQueryRequest) -> GatewayAnswer:
            if direction not in _PROVENANCE_DIRECTIONS:
                raise C2Error("SCHEMA_VIOLATION", "direction is outside the closed set")
            self._budget(bound, depth=max_depth)
            objects = self._require_objects()
            served = self._served(request)
            disclosure = self._disclosure(request)
            root = target["resource_id"]
            # a withheld, mistyped or absent target is POLICY_DENIED alike, before any
            # derivation is looked up (NFR-006, Register :50; LLD v1.1 :123)
            seen = self._roots((target,), disclosure)
            if root not in seen:
                raise C2Error("POLICY_DENIED", "the target is not authorised")
            edges: list[tuple[str, str]] = []
            if direction in {"DOWNSTREAM", "BOTH"}:
                derived = [item for item in objects.page(limit=self._catalog.queries[
                    bound.query.call.contract_id].cost_budget.max_items, after=None) if root in item.provenance_ids]
                for item in derived[:max_depth * 100]:
                    seen[item.resource_id] = item
                    edges.append((item.resource_id, root))
            extra_nodes: list[dict[str, Any]] = []
            extra_edges: list[dict[str, Any]] = []
            target_item = seen.get(root)
            if direction in {"UPSTREAM", "BOTH"} and include_evidence and target_item is not None \
                    and disclosure.admit(target_item):
                for source in target_item.provenance_ids:
                    ref = self._ref(EVIDENCE_TYPE, evidence_ref(root, source))
                    extra_nodes.append({"node_ref": ref, "node_kind": EVIDENCE_TYPE,
                                        "marking_ref": target_item.marking_ref})
                    extra_edges.append({"edge_type_id": "urn:ocor:edge:derived-from",
                                        "from_ref": self._ref(target_item.resource_type_id, root), "to_ref": ref,
                                        "marking_ref": target_item.marking_ref})
            return self._graph_answer(request, served, disclosure, seen, edges, "urn:ocor:edge:derived-from",
                                      extra_nodes, extra_edges)

        result: GatewayAnswer = self._guarded(bound, QueryOperation.GET_PROVENANCE.value, work)
        return result

    # -- EvidenceReadPort ----------------------------------------------------------
    def get(self, evidence_ref_value: str, query: TransportBoundQuery) -> Mapping[str, object]:
        """``EvidenceReadPort`` (LLD v1.1 :113): an evidence read is admitted exactly like the
        six operations -- transport principal, allow-list, digest, release, identity, verified
        context policy (LLD v1.1 :117-120; FR-006) -- and every refusal is audited (FR-134);
        the reference then resolves only through an object the clearance authorises, anything
        else being POLICY_DENIED."""

        def work(request: NamedQueryRequest) -> Mapping[str, object]:
            objects = self._require_objects()
            disclosure = self._disclosure(request)
            for item in objects.page(limit=MAX_EVIDENCE_SCAN, after=None):
                for source in item.provenance_ids:
                    if evidence_ref(item.resource_id, source) == evidence_ref_value and disclosure.admit(item):
                        return {"evidence_ref": evidence_ref_value, "object_ref": item.resource_id,
                                "source": source, "marking_ref": item.marking_ref, "commit": item.commit_id}
            raise C2Error("POLICY_DENIED", "the evidence is not authorised")

        result: Mapping[str, object] = self._guarded(query, "EvidenceRead", work)
        return result


EVIDENCE_TYPE = "urn:ocor:type:evidence"
MAX_EVIDENCE_SCAN = 1000
_OUTCOME = {"SCHEMA_VIOLATION": "REJECTED", "CONTROL_PLANE_UNAVAILABLE": "FAILED"}


def evidence_ref(object_id: str, source: str) -> str:
    """Content address of one evidence item of an object (``urn:sha256``, contract :356)."""
    return canonical_digest({"object": object_id, "evidence": source})


class _Disclosure:
    """The marking join of one answer (LLD v1.1 :121-122): which resources the clearance
    authorises, which are withheld (counted once each, contract :322) and the markings of
    what is disclosed."""

    def __init__(self, policy: RegistrationAndMarkingPolicy, clearance: MarkingSet) -> None:
        self._policy = policy
        self._clearance = clearance
        self._decisions: dict[str, bool] = {}
        self.disclosed: set[str] = set()
        self.withheld: set[str] = set()
        self.markings: set[str] = set()

    def authorized(self, resource_id: str) -> bool:
        """The marking join of one resource, without recording a disclosure or redaction."""
        decision = self._decisions.get(resource_id)
        if decision is None:
            decision = self._policy.authorized(resource_id, self._clearance)
            self._decisions[resource_id] = decision
        return decision

    def allows(self, resource_id: str) -> bool:
        decision = self.authorized(resource_id)
        if not decision:
            self.withheld.add(resource_id)
        return decision

    def admit(self, item: ProjectedObject) -> bool:
        if not self.allows(item.resource_id):
            return False
        self.disclosed.add(item.resource_id)
        self.markings.add(item.marking_ref)
        return True

    def withhold(self, resource_id: str) -> None:
        if resource_id not in self.disclosed:
            self.withheld.add(resource_id)


def compose_named_query_gateway(
    *,
    release_package: Any,
    identity_registry: IdentityRegistry,
    context_policy: ContextPolicyPort,
    marking_engine: MarkingEngine,
    marking_port: MarkingAuthorizationPort,
    clearance_by_marking_ref: Mapping[str, MarkingSet],
    projection: ProjectionReadPort,
    objects: ObjectProjectionPort,
    audit: AuditPort,
    commit_ordering: CommitOrderingPort | None = None,
    provenance_contract_id: str | None = None,
) -> NamedQueryGateway:
    """Composition root of C2: the allow-list and active release come from the admitted C1
    release; identity, context policy, marking join, projections and audit are ports."""
    base = NamedQueryCatalog.from_release(release_package)
    catalog = NamedQueryCatalog(ontology_release_digest=base.ontology_release_digest, queries=base.queries,
                                provenance_contract_id=provenance_contract_id)
    policy = RegistrationAndMarkingPolicy(registry=catalog.queries, marking_engine=marking_engine,
                                          marking_port=marking_port, clearance_by_marking_ref=clearance_by_marking_ref)
    return NamedQueryGateway(catalog=catalog, authority=IdentityBackedAuthority(identity_registry),
                             context_policy=context_policy, policy=policy, projection=projection, audit=audit,
                             objects=objects, commit_ordering=commit_ordering)
