"""BA-02 -- TypeDB 3.x ``LogicProjection`` (C4): atomic visibility of facts and watermark.

Backend assumption under test: ADD v1.3 Part I §2.6 row ``BA-02`` ("Visibilità
atomica di facts e ``projection_watermark``, per transazione locale ...") with
its conformance column "Lettura concorrente durante la proiezione: nessun
lettore osserva watermark avanzato con facts mancanti", and the LLD v1.1 §7.1
oracle "TypeDB facts/relations e watermark atomici, policy-safe".

Real component: TypeDB CE 3.12.3 (``typedb`` compose service, image pinned in
``infra/services.lock.json``), driven exclusively through the sealed retained
adapter ``ocor_runtime.c4.typedb_adapter.TypeDBProjectionAdapter`` (its
``apply_commit`` writes the fact and the watermark in ONE real TypeDB write
transaction). The policy-safety half of the oracle is observed through the
sealed ``ocor_runtime.c2.planner.ConsistencyPlanner`` with the sealed
``ocor_runtime.c2.gateway.RegistrationAndMarkingPolicy`` whose marking port is
the sealed ``ocor_runtime.c4.jena_adapter.JenaSHACLProjectionAdapter`` on the
real Fuseki 6.2.0 (``fuseki`` compose service).

Isolation: every test runs against its own disposable TypeDB database (the
sealed adapter's module-level ``DATABASE`` is pointed at a unique name with
``monkeypatch``, exactly like the sealed tests repoint ``TYPEDB_URL``) which is
dropped at teardown and asserted absent; Fuseki resources use unique IRIs and
are deleted and asserted absent. Observations are read back from the real
servers: watermark and facts are read in ONE real TypeDB read transaction
(a server-side snapshot), never from in-process state.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from ocor_runtime.c2.gateway import RegisteredNamedQuery, RegistrationAndMarkingPolicy
from ocor_runtime.c2.planner import ConsistencyPlanner
from ocor_runtime.c2.ports import (
    C2Error,
    ConsistencyMode,
    ConsistencyRequirement,
    NamedQueryRequest,
    Watermark,
)
from ocor_runtime.c4 import jena_adapter, typedb_adapter
from ocor_runtime.c4.jena_adapter import JenaAdapterError, JenaSHACLProjectionAdapter
from ocor_runtime.c4.typedb_adapter import TypeDBAdapterError, TypeDBProjectionAdapter
from ocor_runtime.c4_marking import MarkingEngine, MarkingSchemeDefinition, MarkingSet
from ocor_runtime.kernel.governed_context import GovernedContext

pytestmark = pytest.mark.backend_assumption

BA_CASE = {
    "ba_id": "BA-02",
    "component": "TypeDB CE (LogicProjection, C4) via ocor_runtime.c4.typedb_adapter.TypeDBProjectionAdapter",
    "component_version": "3.12.3",
    "backend_services": ["typedb", "fuseki"],
    "add_v1_3_part_i_2_6": {
        "required_property": "Visibilità atomica di facts e `projection_watermark`, per transazione locale",
        "conformance_test": (
            "Lettura concorrente durante la proiezione: nessun lettore osserva watermark avanzato con facts mancanti"
        ),
    },
    "lld_v1_1_7_1_oracle": "TypeDB facts/relations e watermark atomici, policy-safe",
    "requirement_ids": ["FR-064", "NFR-077"],
    "requirement_binding": {
        "FR-064": (
            "Observes that facts and watermark are updated in the same local projection transaction, so under "
            "concurrent reads and injected crash/rejection the watermark never precedes its facts."
        ),
        "NFR-077": (
            "Observes that projection lag is surfaced as the explicit PROJECTION_NOT_READY state carrying the real "
            "watermark instead of a mixed answer, and that a served response discloses the commit/watermark served."
        ),
    },
    "positive_tests": [
        "test_ba_02_positive_concurrent_readers_never_see_an_advanced_watermark_with_missing_facts",
    ],
    "negative_tests": [
        "test_ba_02_negative_projection_lag_is_projection_not_ready_never_a_mixed_answer",
        "test_ba_02_negative_policy_denial_precedes_any_watermark_observation",
    ],
    "fault_tests": [
        "test_ba_02_fault_crash_before_commit_exposes_neither_fact_nor_watermark",
        "test_ba_02_fault_server_rejected_statement_rolls_back_fact_and_watermark_together",
    ],
}

DIGEST_ONTOLOGY = "urn:sha256:" + "b" * 64
DIGEST_POLICY = "urn:sha256:" + "c" * 64
DIGEST_CONTRACT = "urn:sha256:" + "a" * 64
MARKING_LOW = "urn:sha256:" + "1" * 64
MARKING_HIGH = "urn:sha256:" + "2" * 64
REQUEST_ID = "018f2f95-01b2-7cc3-8d4e-123456789abc"
CONTRACT_ID = "urn:ocor:contract:named-query:ba02-logic-projection"
PROJECTION_ID = "urn:ocor:projection:ba02-logic-projection"
BRANCH = "main"
CLASSIFICATION = MarkingSchemeDefinition("classification", levels=("UNCLASSIFIED", "SECRET", "TOP_SECRET"))
# TypeDB's HTTP endpoint refuses request bodies above its buffer limit (2 MiB)
# with HSR2; 2.5 MiB is a real, reproducible server-side resource rejection.
OVERSIZED = 5 << 19
COMMITS = 12
READERS = 4
OBSERVATION_TIMEOUT_S = 30.0


# --------------------------------------------------------------------------
# real-backend fixtures and helpers (copied/adapted from the sealed
# tests/tasks/test_ocor_dev_0037.py and test_ocor_dev_0038.py)
# --------------------------------------------------------------------------


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _database_names() -> set[str]:
    token = typedb_adapter._token()
    status, body = typedb_adapter._request("GET", f"{typedb_adapter.TYPEDB_URL}/v1/databases", headers=_auth(token))
    if status != 200:
        pytest.fail(f"cannot list TypeDB databases: {status}")
    return {entry["name"] for entry in json.loads(body).get("databases", [])}


def _drop_database(name: str) -> None:
    token = typedb_adapter._token()
    for _ in range(50):
        status, body = typedb_adapter._request(
            "DELETE", f"{typedb_adapter.TYPEDB_URL}/v1/databases/{name}", headers=_auth(token)
        )
        if status == 200:
            return
        if "DBD2" not in body:
            pytest.fail(f"cannot drop disposable TypeDB database {name!r}: {status} {body}")
        time.sleep(0.2)
    pytest.fail(f"disposable TypeDB database {name!r} is still in use after teardown")


@pytest.fixture
def projection(monkeypatch: pytest.MonkeyPatch) -> Iterator[TypeDBProjectionAdapter]:
    name = f"ocor_ba02_{uuid.uuid4().hex[:16]}"
    monkeypatch.setattr(typedb_adapter, "DATABASE", name)
    adapter = TypeDBProjectionAdapter()
    try:
        adapter.initialize()
    except (TypeDBAdapterError, OSError) as error:
        pytest.fail(f"a real, live TypeDB instance is mandatory qualifying evidence: {error}")
    yield adapter
    _drop_database(name)
    assert name not in _database_names()


def _resource_triples(iri: str) -> int:
    rows = jena_adapter._query(f"SELECT (COUNT(*) AS ?c) WHERE {{ <{iri}> ?p ?o }}")
    return int(rows[0]["c"]["value"])


@pytest.fixture
def marking_port() -> Iterator[tuple[JenaSHACLProjectionAdapter, list[str]]]:
    adapter = JenaSHACLProjectionAdapter(MarkingEngine([CLASSIFICATION]))
    created: list[str] = []
    try:
        jena_adapter._query("SELECT (COUNT(*) AS ?c) WHERE { ?s ?p ?o }")
    except (JenaAdapterError, OSError) as error:
        pytest.fail(f"a real, live Fuseki instance is mandatory qualifying evidence: {error}")
    yield adapter, created
    for iri in created:
        jena_adapter._update(f"DELETE WHERE {{ <{iri}> ?p ?o }}")
        assert _resource_triples(iri) == 0


@dataclass
class Snapshot:
    watermark: int
    facts: dict[int, int] = field(default_factory=dict)
    payloads: dict[int, str] = field(default_factory=dict)


def _commit_id(run: str, index: int) -> str:
    return f"urn:ocor:commit:ba02:{run}:{index:04d}"


def _fact_id(index: int) -> str:
    return f"urn:ocor:mission-object:ba02:{index:04d}"


def _index(value: str) -> int:
    return int(value.rsplit(":", 1)[1])


def _payload(index: int) -> str:
    return f"urn:sha256:{hashlib.sha256(f'ba02-fact-{index}'.encode()).hexdigest()}"


def _snapshot(token: str) -> Snapshot:
    """Reads the watermark AND every fact inside ONE real TypeDB read
    transaction, i.e. one server-side snapshot -- what a concurrent reader
    of the projection store can actually observe at one instant."""
    transaction_id = typedb_adapter._transaction("read", token)
    try:
        status_w, watermark = typedb_adapter._query(
            transaction_id, "match $w isa c4-watermark, has c4-commit-id $c;", token
        )
        status_f, facts = typedb_adapter._query(
            transaction_id,
            "match $f isa c4-fact, has c4-fact-id $i, has c4-commit-id $c, has c4-payload $p;",
            token,
        )
    finally:
        typedb_adapter._close(transaction_id, token)
    assert status_w == 200 and status_f == 200, (status_w, status_f)
    watermark_rows: list[dict[str, Any]] = watermark.get("answers") or []
    assert len(watermark_rows) <= 1, "more than one projection watermark is visible"
    result = Snapshot(watermark=_index(watermark_rows[0]["data"]["c"]["value"]) if watermark_rows else 0)
    for row in facts.get("answers") or []:
        data = row["data"]
        fact = _index(data["i"]["value"])
        result.facts[fact] = _index(data["c"]["value"])
        result.payloads[fact] = str(data["p"]["value"])
    return result


def _context(marking_ref: str) -> GovernedContext:
    return GovernedContext.from_mapping(
        {
            "tenant_id": "urn:ocor:tenant:synthetic",
            "organization_id": "urn:ocor:org:synthetic",
            "domain_id": "urn:ocor:domain:logistics",
            "compartments": ["urn:ocor:compartment:alpha"],
            "classification_marking_ref": marking_ref,
            "purpose": "ba02-logic-projection",
            "effective_principal_id": "spiffe://ocor.test/workload/c2",
            "actor_chain": ["urn:ocor:actor:synthetic", "urn:ocor:actor:c2"],
            "ontology_release_digest": DIGEST_ONTOLOGY,
            "policy_bundle_digest": DIGEST_POLICY,
            "correlation_id": REQUEST_ID,
        }
    )


def _request(
    *, fact_id: str, consistency: ConsistencyRequirement, marking_ref: str = MARKING_LOW, resource_id: str | None = None
) -> NamedQueryRequest:
    context = _context(marking_ref)
    parameters: dict[str, str] = {"fact_id": fact_id}
    if resource_id is not None:
        parameters["resource_id"] = resource_id
    return NamedQueryRequest(
        request_id=REQUEST_ID,
        contract_id=CONTRACT_ID,
        contract_version="1.0.0",
        contract_digest=DIGEST_CONTRACT,
        parameters=parameters,
        governed_context=context,
        governed_context_digest=context.digest(),
        consistency=consistency,
    )


def _sha(value: str) -> str:
    return "urn:sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


class CountingWatermarkPort:
    """Test-local pass-through around the real TypeDB ``WatermarkPort`` that
    counts consultations; it never alters what the real adapter returns."""

    def __init__(self, inner: TypeDBProjectionAdapter) -> None:
        self._inner = inner
        self.calls = 0

    def current(self, projection_id: str, branch: str) -> Watermark:
        self.calls += 1
        return self._inner.current(projection_id, branch)


def _planner(
    projection: TypeDBProjectionAdapter, marking: JenaSHACLProjectionAdapter
) -> tuple[ConsistencyPlanner, CountingWatermarkPort]:
    policy = RegistrationAndMarkingPolicy(
        registry={
            CONTRACT_ID: RegisteredNamedQuery(
                contract_id=CONTRACT_ID, versions=frozenset({"1.0.0"}), marking_scheme_id="classification"
            )
        },
        marking_engine=MarkingEngine([CLASSIFICATION]),
        marking_port=marking,
        clearance_by_marking_ref={
            MARKING_LOW: MarkingSet({"classification": "UNCLASSIFIED"}),
            MARKING_HIGH: MarkingSet({"classification": "TOP_SECRET"}),
        },
    )
    counting = CountingWatermarkPort(projection)
    planner = ConsistencyPlanner(policy=policy, watermark_port=counting, projection_id=PROJECTION_ID, branch=BRANCH)
    return planner, counting


# --------------------------------------------------------------------------
# BA-02 cases
# --------------------------------------------------------------------------


def test_ba_02_positive_concurrent_readers_never_see_an_advanced_watermark_with_missing_facts(
    projection: TypeDBProjectionAdapter,
) -> None:
    run = uuid.uuid4().hex[:12]
    condition = threading.Condition()
    stop = threading.Event()
    observed: set[int] = set()
    violations: list[str] = []
    errors: list[BaseException] = []
    snapshots = [0]
    port_reads = [0]

    def reader() -> None:
        try:
            token = typedb_adapter._token()
            last = 0
            while not stop.is_set():
                snap = _snapshot(token)
                expected = set(range(1, snap.watermark + 1))
                if set(snap.facts) != expected:
                    violations.append(f"watermark {snap.watermark} with facts {sorted(snap.facts)}")
                for fact, commit in snap.facts.items():
                    if commit != fact or snap.payloads[fact] != _payload(fact):
                        violations.append(f"fact {fact} carries commit {commit}")
                if snap.watermark < last:
                    violations.append(f"watermark regressed {last} -> {snap.watermark}")
                last = snap.watermark
                if snap.watermark:
                    # the sealed ProjectionReadPort path: whatever watermark it
                    # serves, the fact the reader just saw announced is there.
                    response = projection.read(
                        _request(
                            fact_id=_fact_id(snap.watermark),
                            consistency=ConsistencyRequirement(mode=ConsistencyMode.BEST_AVAILABLE),
                        )
                    )
                    if _index(response.served.projection_watermark) < snap.watermark:
                        violations.append("port served an older watermark than a prior snapshot")
                    if response.result_digest != _sha(_payload(snap.watermark)):
                        violations.append(f"port served a wrong payload for fact {snap.watermark}")
                    with condition:
                        port_reads[0] += 1
                with condition:
                    snapshots[0] += 1
                    observed.add(snap.watermark)
                    condition.notify_all()
        except BaseException as error:  # noqa: BLE001 - surfaced to the main thread below
            errors.append(error)
            with condition:
                condition.notify_all()

    threads = [threading.Thread(target=reader, name=f"ba02-reader-{i}") for i in range(READERS)]
    for thread in threads:
        thread.start()
    try:
        for index in range(1, COMMITS + 1):
            projection.apply_commit(fact_id=_fact_id(index), commit_id=_commit_id(run, index), payload=_payload(index))
            with condition:
                # lockstep: the next commit is applied only after a concurrent
                # reader has observed this one, so every intermediate state is
                # deterministically observed while the projection is running.
                reached = condition.wait_for(lambda: index in observed or bool(errors), OBSERVATION_TIMEOUT_S)
            assert reached, f"no concurrent reader observed commit {index}"
            assert not errors, errors
    finally:
        stop.set()
        for thread in threads:
            thread.join(OBSERVATION_TIMEOUT_S)
    assert not errors, errors
    assert all(not thread.is_alive() for thread in threads)
    assert violations == []
    assert set(range(1, COMMITS + 1)) <= observed
    assert snapshots[0] >= COMMITS and port_reads[0] >= COMMITS

    final = _snapshot(typedb_adapter._token())
    assert final.watermark == COMMITS and set(final.facts) == set(range(1, COMMITS + 1))
    response = projection.read(
        _request(
            fact_id=_fact_id(COMMITS),
            consistency=ConsistencyRequirement(
                mode=ConsistencyMode.EXACT_AT_COMMIT, required_commit=_commit_id(run, COMMITS)
            ),
        )
    )
    assert response.served.canonical_commit == _commit_id(run, COMMITS)
    assert response.served.projection_watermark == _commit_id(run, COMMITS)
    assert response.served.branch == BRANCH
    assert projection.current(PROJECTION_ID, BRANCH).canonical_commit == _commit_id(run, COMMITS)


def test_ba_02_negative_projection_lag_is_projection_not_ready_never_a_mixed_answer(
    projection: TypeDBProjectionAdapter, marking_port: tuple[JenaSHACLProjectionAdapter, list[str]]
) -> None:
    run = uuid.uuid4().hex[:12]
    projection.apply_commit(fact_id=_fact_id(1), commit_id=_commit_id(run, 1), payload=_payload(1))
    planner, counting = _planner(projection, marking_port[0])
    before = _snapshot(typedb_adapter._token())

    # positive control: the commit that HAS landed is served and disclosed.
    ready = _request(
        fact_id=_fact_id(1),
        consistency=ConsistencyRequirement(mode=ConsistencyMode.AT_LEAST_COMMIT, required_commit=_commit_id(run, 1)),
    )
    plan = planner.plan(ready)
    assert plan.observed_watermark.canonical_commit == _commit_id(run, 1)
    served = projection.read(ready)
    assert served.served.projection_watermark == _commit_id(run, 1)
    assert served.result_digest == _sha(_payload(1))

    # negative: commit 2 has not been projected yet.
    lagging = _request(
        fact_id=_fact_id(2),
        consistency=ConsistencyRequirement(mode=ConsistencyMode.AT_LEAST_COMMIT, required_commit=_commit_id(run, 2)),
    )
    with pytest.raises(C2Error) as planned:
        planner.plan(lagging)
    assert planned.value.reason_code == "PROJECTION_NOT_READY"
    assert repr(_commit_id(run, 1)) in str(planned.value)  # the real observed watermark is disclosed
    with pytest.raises(C2Error) as read:
        projection.read(lagging)
    assert read.value.reason_code == "PROJECTION_NOT_READY"
    assert counting.calls == 2

    after = _snapshot(typedb_adapter._token())
    assert after == before
    assert after.watermark == 1 and set(after.facts) == {1}


def test_ba_02_negative_policy_denial_precedes_any_watermark_observation(
    projection: TypeDBProjectionAdapter, marking_port: tuple[JenaSHACLProjectionAdapter, list[str]]
) -> None:
    run = uuid.uuid4().hex[:12]
    marking, created = marking_port
    resource = f"urn:ocor:resource:ba02:{run}:restricted"
    created.append(resource)
    marking.publish(
        resource,
        {"label": "restricted", "classification": "TOP_SECRET", "provenanceRef": f"urn:ocor:provenance:ba02:{run}"},
    )
    assert _resource_triples(resource) > 0  # the marked resource really exists on Fuseki
    projection.apply_commit(fact_id=_fact_id(1), commit_id=_commit_id(run, 1), payload=_payload(1))
    planner, counting = _planner(projection, marking)
    before = _snapshot(typedb_adapter._token())
    consistency = ConsistencyRequirement(mode=ConsistencyMode.AT_LEAST_COMMIT, required_commit=_commit_id(run, 1))

    # negative: an UNCLASSIFIED clearance asking about a TOP_SECRET resource is
    # denied by policy before the projection watermark is ever consulted.
    with pytest.raises(C2Error) as denied:
        planner.plan(
            _request(fact_id=_fact_id(1), consistency=consistency, marking_ref=MARKING_LOW, resource_id=resource)
        )
    assert denied.value.reason_code == "ARBITRARY_QUERY_FORBIDDEN"
    assert counting.calls == 0
    assert _commit_id(run, 1) not in str(denied.value)  # no watermark disclosed

    # positive control: the same request with a dominating clearance plans and
    # observes the real watermark.
    plan = planner.plan(
        _request(fact_id=_fact_id(1), consistency=consistency, marking_ref=MARKING_HIGH, resource_id=resource)
    )
    assert plan.observed_watermark.canonical_commit == _commit_id(run, 1)
    assert counting.calls == 1
    assert _snapshot(typedb_adapter._token()) == before


def test_ba_02_fault_crash_before_commit_exposes_neither_fact_nor_watermark(
    projection: TypeDBProjectionAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = uuid.uuid4().hex[:12]
    projection.apply_commit(fact_id=_fact_id(1), commit_id=_commit_id(run, 1), payload=_payload(1))
    before = _snapshot(typedb_adapter._token())
    real_commit = typedb_adapter._commit
    real_close = typedb_adapter._close
    reader_token = typedb_adapter._token()
    during: list[Snapshot] = []
    pending: list[str] = []

    def crash_before_commit(transaction_id: str, token: str) -> None:
        # every statement of apply_commit has executed inside the real
        # TypeDB write transaction; a concurrent reader looks now, then the
        # writer "dies": the transaction is closed without being committed.
        pending.append(transaction_id)
        during.append(_snapshot(reader_token))
        real_close(transaction_id, token)
        raise ConnectionResetError("injected projector crash before commit")

    monkeypatch.setattr(typedb_adapter, "_commit", crash_before_commit)
    with pytest.raises(ConnectionResetError):
        projection.apply_commit(fact_id=_fact_id(2), commit_id=_commit_id(run, 2), payload=_payload(2))
    with pytest.raises(ConnectionResetError):  # an UPDATE of an existing fact as well
        projection.apply_commit(fact_id=_fact_id(1), commit_id=_commit_id(run, 3), payload=_payload(3))
    monkeypatch.setattr(typedb_adapter, "_commit", real_commit)

    assert len(pending) == 2
    assert during == [before, before]
    assert _snapshot(typedb_adapter._token()) == before

    # recovery: the replayed commit lands fact and watermark together.
    projection.apply_commit(fact_id=_fact_id(2), commit_id=_commit_id(run, 2), payload=_payload(2))
    after = _snapshot(typedb_adapter._token())
    assert after.watermark == 2 and after.facts == {1: 1, 2: 2}


def test_ba_02_fault_server_rejected_statement_rolls_back_fact_and_watermark_together(
    projection: TypeDBProjectionAdapter,
) -> None:
    run = uuid.uuid4().hex[:12]
    projection.apply_commit(fact_id=_fact_id(1), commit_id=_commit_id(run, 1), payload=_payload(1))
    before = _snapshot(typedb_adapter._token())

    # apply_commit's first statement (delete the prior fact) succeeds inside
    # the real transaction; the second (insert with an oversized payload) is
    # rejected by the real server. Nothing of the transaction may survive.
    with pytest.raises(TypeDBAdapterError) as rejected:
        projection.apply_commit(fact_id=_fact_id(1), commit_id=_commit_id(run, 2), payload="x" * OVERSIZED)
    assert "write failed: 400" in str(rejected.value)
    assert "HSR2" in str(rejected.value)
    assert _snapshot(typedb_adapter._token()) == before
    assert projection.current_watermark() == _commit_id(run, 1)

    # positive control: the same update with a normal payload is applied.
    projection.apply_commit(fact_id=_fact_id(1), commit_id=_commit_id(run, 2), payload=_payload(2))
    after = _snapshot(typedb_adapter._token())
    assert after.watermark == 2 and after.facts == {1: 2}
