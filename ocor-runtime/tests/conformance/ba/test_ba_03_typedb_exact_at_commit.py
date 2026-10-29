"""BA-03 -- TypeDB 3.x time travel: ``EXACT_AT_COMMIT(Cn)`` on named logical queries.

Backend assumption under test: ADD v1.3 Part I §2.6 row ``BA-03`` (disposable
sandbox serving ``EXACT_AT_COMMIT(Cn)`` on named logical queries; conformance
column "Benchmark di creazione sandbox; test di esaurimento risorse; test
negativo con emulazione indisponibile") read together with ADD v1.3 §3.3
(``EXACT_AT_COMMIT(Cn)`` never silently degrades to ``AT_LEAST_COMMIT``) and the
LLD v1.1 §7.1 oracle "TypeDB exact-at-commit o ``PROJECTION_NOT_READY``, mai
downgrade".

Real component: TypeDB CE 3.12.3 (``typedb`` compose service, image pinned in
``infra/services.lock.json``) through the sealed retained adapter
``ocor_runtime.c4.typedb_adapter.TypeDBProjectionAdapter`` (``read`` with the
sealed fail-closed ``NamedQueryRequest.verify_served``) and the sealed C2
planner ``ocor_runtime.c2.planner.ConsistencyPlanner`` with the sealed
``ocor_runtime.c2.gateway.RegistrationAndMarkingPolicy``.

What the sealed runtime provides and this module observes: the adapter has NO
time-travel sandbox/emulation -- it can only serve the commit currently
projected. A request ``EXACT_AT_COMMIT(Cn)`` is therefore served exactly when
the projection is at ``Cn`` and is otherwise refused (planner:
``PROJECTION_NOT_READY`` with the real watermark; adapter:
``CONSISTENCY_DOWNGRADE``), never answered with another commit. Not covered
(no runtime implementation behind the sealed adapter): sandbox creation
benchmark, and the ADD §3.3 reason code ``UNSUPPORTED_CAPABILITY`` for an
unavailable emulation (the runtime refuses with the codes above instead).

Isolation: every test uses its own disposable TypeDB database (the sealed
adapter's module-level ``DATABASE`` is repointed with ``monkeypatch``), dropped
at teardown and asserted absent.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from ocor_runtime.c2.gateway import RegisteredNamedQuery, RegistrationAndMarkingPolicy
from ocor_runtime.c2.planner import ConsistencyPlanner
from ocor_runtime.c2.ports import (
    C2Error,
    ConsistencyMode,
    ConsistencyRequirement,
    NamedQueryRequest,
    NamedQueryResponse,
)
from ocor_runtime.c4 import typedb_adapter
from ocor_runtime.c4.jena_adapter import JenaSHACLProjectionAdapter
from ocor_runtime.c4.typedb_adapter import TypeDBAdapterError, TypeDBProjectionAdapter
from ocor_runtime.c4_marking import MarkingEngine, MarkingSchemeDefinition
from ocor_runtime.kernel.governed_context import GovernedContext

pytestmark = pytest.mark.backend_assumption

BA_CASE = {
    "ba_id": "BA-03",
    "component": "TypeDB CE (time travel / EXACT_AT_COMMIT, C2+C4) via ocor_runtime.c4.typedb_adapter",
    "component_version": "3.12.3",
    "backend_services": ["typedb"],
    "add_v1_3_part_i_2_6": {
        "required_property": "`EXACT_AT_COMMIT(Cn)` su query logiche nominate",
        "conformance_test": "test di esaurimento risorse; test negativo con emulazione indisponibile",
    },
    "lld_v1_1_7_1_oracle": "TypeDB exact-at-commit o `PROJECTION_NOT_READY`, mai downgrade",
    "requirement_ids": ["FR-057", "NFR-077"],
    "requirement_binding": {
        "FR-057": (
            "Observes the exact-at-commit half of the consistency token: a projection beyond Cn never serves "
            "exact-at-commit(Cn)."
        ),
        "NFR-077": (
            "Observes that exact-at-commit(Cn) is served only exactly at Cn with the served commit/watermark "
            "disclosed, and that projection lag or a missing snapshot yields an explicit state, never a mixed answer."
        ),
    },
    "positive_tests": [
        "test_ba_03_positive_exact_at_commit_is_served_exactly_or_projection_not_ready",
    ],
    "negative_tests": [
        "test_ba_03_negative_past_commit_without_time_travel_emulation_is_refused_never_downgraded",
    ],
    "fault_tests": [
        "test_ba_03_fault_oversized_request_exhausting_the_server_buffer_fails_closed",
        "test_ba_03_fault_concurrent_burst_under_projection_churn_never_serves_a_downgraded_answer",
    ],
}

DIGEST_ONTOLOGY = "urn:sha256:" + "b" * 64
DIGEST_POLICY = "urn:sha256:" + "c" * 64
DIGEST_CONTRACT = "urn:sha256:" + "a" * 64
MARKING_REF = "urn:sha256:" + "1" * 64
REQUEST_ID = "018f2f95-01b2-7cc3-8d4e-123456789abc"
CONTRACT_ID = "urn:ocor:contract:named-query:ba03-exact-at-commit"
PROJECTION_ID = "urn:ocor:projection:ba03-exact-at-commit"
BRANCH = "main"
FACT = "urn:ocor:mission-object:ba03:1"
# TypeDB's HTTP endpoint refuses request bodies above its buffer limit (2 MiB)
# with HSR2: 2.5 MiB is a real, reproducible server-side resource rejection.
OVERSIZED = 5 << 19
BURST_WORKERS = 16
BURST_READS = 64
CHURN_COMMITS = 6
REFUSALS = frozenset({"CONSISTENCY_DOWNGRADE", "PROJECTION_NOT_READY"})


# --------------------------------------------------------------------------
# real-backend fixtures and helpers (copied/adapted from the sealed
# tests/tasks/test_ocor_dev_0037.py)
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
    name = f"ocor_ba03_{uuid.uuid4().hex[:16]}"
    monkeypatch.setattr(typedb_adapter, "DATABASE", name)
    adapter = TypeDBProjectionAdapter()
    try:
        adapter.initialize()
    except (TypeDBAdapterError, OSError) as error:
        pytest.fail(f"a real, live TypeDB instance is mandatory qualifying evidence: {error}")
    yield adapter
    _drop_database(name)
    assert name not in _database_names()


def _server_state() -> tuple[str | None, list[tuple[str, str, str]]]:
    """Watermark and facts read back from the real server in ONE read
    transaction (a server-side snapshot)."""
    token = typedb_adapter._token()
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
    current = str(watermark_rows[0]["data"]["c"]["value"]) if watermark_rows else None
    rows = sorted(
        (str(row["data"]["i"]["value"]), str(row["data"]["c"]["value"]), str(row["data"]["p"]["value"]))
        for row in facts.get("answers") or []
    )
    return current, rows


def _commit_id(run: str, index: int) -> str:
    return f"urn:ocor:commit:ba03:{run}:{index:04d}"


def _payload(index: int) -> str:
    return f"urn:sha256:{hashlib.sha256(f'ba03-state-{index}'.encode()).hexdigest()}"


def _sha(value: str) -> str:
    return "urn:sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _request(*, consistency: ConsistencyRequirement, fact_id: str = FACT) -> NamedQueryRequest:
    context = GovernedContext.from_mapping(
        {
            "tenant_id": "urn:ocor:tenant:synthetic",
            "organization_id": "urn:ocor:org:synthetic",
            "domain_id": "urn:ocor:domain:logistics",
            "compartments": ["urn:ocor:compartment:alpha"],
            "classification_marking_ref": MARKING_REF,
            "purpose": "ba03-exact-at-commit",
            "effective_principal_id": "spiffe://ocor.test/workload/c2",
            "actor_chain": ["urn:ocor:actor:synthetic", "urn:ocor:actor:c2"],
            "ontology_release_digest": DIGEST_ONTOLOGY,
            "policy_bundle_digest": DIGEST_POLICY,
            "correlation_id": REQUEST_ID,
        }
    )
    return NamedQueryRequest(
        request_id=REQUEST_ID,
        contract_id=CONTRACT_ID,
        contract_version="1.0.0",
        contract_digest=DIGEST_CONTRACT,
        parameters={"fact_id": fact_id},
        governed_context=context,
        governed_context_digest=context.digest(),
        consistency=consistency,
    )


def _exact(commit: str, *, fact_id: str = FACT) -> NamedQueryRequest:
    return _request(
        consistency=ConsistencyRequirement(mode=ConsistencyMode.EXACT_AT_COMMIT, required_commit=commit),
        fact_id=fact_id,
    )


def _planner(projection: TypeDBProjectionAdapter) -> ConsistencyPlanner:
    # Real sealed policy; the request names no resource_id, so the marking
    # port (the sealed Jena adapter) is not consulted and Fuseki is not used.
    classification = MarkingSchemeDefinition("classification", levels=("UNCLASSIFIED", "SECRET"))
    policy = RegistrationAndMarkingPolicy(
        registry={
            CONTRACT_ID: RegisteredNamedQuery(
                contract_id=CONTRACT_ID, versions=frozenset({"1.0.0"}), marking_scheme_id="classification"
            )
        },
        marking_engine=MarkingEngine([classification]),
        marking_port=JenaSHACLProjectionAdapter(MarkingEngine([classification])),
        clearance_by_marking_ref={},
    )
    return ConsistencyPlanner(policy=policy, watermark_port=projection, projection_id=PROJECTION_ID, branch=BRANCH)


def _assert_exact(response: NamedQueryResponse, commit: str, payload: str) -> None:
    assert response.served.canonical_commit == commit
    assert response.served.projection_watermark == commit
    assert response.served.branch == BRANCH
    assert response.served.staleness_ms == 0
    assert response.result_digest == _sha(payload)


# --------------------------------------------------------------------------
# BA-03 cases
# --------------------------------------------------------------------------


def test_ba_03_positive_exact_at_commit_is_served_exactly_or_projection_not_ready(
    projection: TypeDBProjectionAdapter,
) -> None:
    run = uuid.uuid4().hex[:12]
    planner = _planner(projection)
    projection.apply_commit(fact_id=FACT, commit_id=_commit_id(run, 1), payload=_payload(1))
    projection.apply_commit(fact_id=FACT, commit_id=_commit_id(run, 2), payload=_payload(2))
    assert _server_state() == (_commit_id(run, 2), [(FACT, _commit_id(run, 2), _payload(2))])

    plan = planner.plan(_exact(_commit_id(run, 2)))
    assert plan.required_commit == _commit_id(run, 2)
    assert plan.observed_watermark.canonical_commit == _commit_id(run, 2)
    _assert_exact(projection.read(_exact(_commit_id(run, 2))), _commit_id(run, 2), _payload(2))

    # C3 is requested before it lands: explicit not-ready, never a C2 answer.
    with pytest.raises(C2Error) as not_ready:
        planner.plan(_exact(_commit_id(run, 3)))
    assert not_ready.value.reason_code == "PROJECTION_NOT_READY"
    with pytest.raises(C2Error) as refused:
        projection.read(_exact(_commit_id(run, 3)))
    assert refused.value.reason_code == "CONSISTENCY_DOWNGRADE"
    assert _server_state() == (_commit_id(run, 2), [(FACT, _commit_id(run, 2), _payload(2))])

    projection.apply_commit(fact_id=FACT, commit_id=_commit_id(run, 3), payload=_payload(3))
    assert planner.plan(_exact(_commit_id(run, 3))).observed_watermark.canonical_commit == _commit_id(run, 3)
    _assert_exact(projection.read(_exact(_commit_id(run, 3))), _commit_id(run, 3), _payload(3))


def test_ba_03_negative_past_commit_without_time_travel_emulation_is_refused_never_downgraded(
    projection: TypeDBProjectionAdapter,
) -> None:
    run = uuid.uuid4().hex[:12]
    planner = _planner(projection)
    projection.apply_commit(fact_id=FACT, commit_id=_commit_id(run, 1), payload=_payload(1))
    projection.apply_commit(fact_id=FACT, commit_id=_commit_id(run, 2), payload=_payload(2))
    before = _server_state()

    # positive control: the current commit is servable exactly, so the
    # refusal below is not caused by a broken backend or request.
    _assert_exact(projection.read(_exact(_commit_id(run, 2))), _commit_id(run, 2), _payload(2))
    best = projection.read(_request(consistency=ConsistencyRequirement(mode=ConsistencyMode.BEST_AVAILABLE)))
    assert best.served.canonical_commit == _commit_id(run, 2)

    # negative: C1 is in the past and the adapter has no sandbox/emulation to
    # materialize it. The request is refused -- never served with C2 data.
    with pytest.raises(C2Error) as planned:
        planner.plan(_exact(_commit_id(run, 1)))
    assert planned.value.reason_code == "PROJECTION_NOT_READY"
    assert repr(_commit_id(run, 2)) in str(planned.value)  # real watermark disclosed
    with pytest.raises(C2Error) as read:
        projection.read(_exact(_commit_id(run, 1)))
    assert read.value.reason_code == "CONSISTENCY_DOWNGRADE"
    assert _server_state() == before


def test_ba_03_fault_oversized_request_exhausting_the_server_buffer_fails_closed(
    projection: TypeDBProjectionAdapter,
) -> None:
    run = uuid.uuid4().hex[:12]
    projection.apply_commit(fact_id=FACT, commit_id=_commit_id(run, 1), payload=_payload(1))
    before = _server_state()

    # The named-query parameter exceeds what the real TypeDB server will
    # buffer: the read fails closed, no NamedQueryResponse exists at all.
    oversized = "urn:ocor:mission-object:ba03:" + "x" * OVERSIZED
    with pytest.raises(TypeDBAdapterError) as exhausted:
        projection.read(_exact(_commit_id(run, 1), fact_id=oversized))
    assert "read failed: 400" in str(exhausted.value)
    assert "HSR2" in str(exhausted.value)

    # The same exhaustion on the write path leaves the projection untouched.
    with pytest.raises(TypeDBAdapterError) as rejected:
        projection.apply_commit(fact_id=FACT, commit_id=_commit_id(run, 2), payload="x" * OVERSIZED)
    assert "HSR2" in str(rejected.value)
    assert _server_state() == before

    # recovery / positive control: the server keeps serving exactly.
    _assert_exact(projection.read(_exact(_commit_id(run, 1))), _commit_id(run, 1), _payload(1))


def test_ba_03_fault_concurrent_burst_under_projection_churn_never_serves_a_downgraded_answer(
    projection: TypeDBProjectionAdapter,
) -> None:
    run = uuid.uuid4().hex[:12]
    projection.apply_commit(fact_id=FACT, commit_id=_commit_id(run, 1), payload=_payload(1))
    payload_by_commit = {_commit_id(run, index): _payload(index) for index in range(1, CHURN_COMMITS + 2)}

    def exact_read(commit: str) -> tuple[str, str, float]:
        started = time.perf_counter()
        try:
            response = projection.read(_exact(commit))
        except C2Error as error:
            return "refused", error.reason_code, time.perf_counter() - started
        assert response.served.canonical_commit == commit, "served a commit other than the one required"
        assert response.served.projection_watermark == commit
        assert response.result_digest == _sha(payload_by_commit[commit])
        return "served", commit, time.perf_counter() - started

    # Phase 1 -- burst with a stable projection: every EXACT read is served.
    with ThreadPoolExecutor(max_workers=BURST_WORKERS) as pool:
        stable = list(pool.map(exact_read, [_commit_id(run, 1)] * BURST_READS))
    assert all(outcome == "served" for outcome, _, _ in stable)

    # Phase 2 -- the same burst while the projection churns C2..C7: each
    # outcome is either exactly the required commit or an explicit refusal.
    stop = threading.Event()
    churn_errors: list[BaseException] = []

    def churn() -> None:
        try:
            for index in range(2, CHURN_COMMITS + 2):
                projection.apply_commit(fact_id=FACT, commit_id=_commit_id(run, index), payload=_payload(index))
        except BaseException as error:  # noqa: BLE001 - surfaced to the main thread below
            churn_errors.append(error)
        finally:
            stop.set()

    writer = threading.Thread(target=churn, name="ba03-churn")
    requested = [_commit_id(run, 1 + (index % (CHURN_COMMITS + 1))) for index in range(BURST_READS)]
    writer.start()
    with ThreadPoolExecutor(max_workers=BURST_WORKERS) as pool:
        churned = list(pool.map(exact_read, requested))
    writer.join(60.0)
    assert stop.is_set() and not writer.is_alive()
    assert not churn_errors, churn_errors
    refused = [code for outcome, code, _ in churned if outcome == "refused"]
    assert set(refused) <= REFUSALS, refused
    assert len(churned) == BURST_READS

    final_commit = _commit_id(run, CHURN_COMMITS + 1)
    assert _server_state() == (final_commit, [(FACT, final_commit, _payload(CHURN_COMMITS + 1))])
    _assert_exact(projection.read(_exact(final_commit)), final_commit, _payload(CHURN_COMMITS + 1))
    with pytest.raises(C2Error) as stale:
        projection.read(_exact(_commit_id(run, 1)))
    assert stale.value.reason_code == "CONSISTENCY_DOWNGRADE"
