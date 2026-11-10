"""OCOR-DEV-0031: Integrate first real C1-C8 synthetic mission thread.

NCP-U12 (OCOR-DEV-REM-0060): adapted to the retained components (case 3 of NORMATIVE-CONFORMANCE-PLAN (2026-10-30)
point 5) with the realignments of NCP-U12-TEST-REALIGNMENT-SCOPE (2026-11-10) option B1 and
NCP-U12-MISSION-THREAD-RESIDUAL-ASSERTIONS (2026-11-10) option 1; NCP-U01-RETAINED-C1-BUILDERS (2026-11-01) point 4.

Proves that a single content-addressed fixture, identified by one
``correlation_id``, crosses every real selected service through the retained
C1-C8 components and produces correlated canonical, projection, event, causal,
agent and action receipts:

  - C1 (compile):      ``ocor_runtime.c1`` OaC compiler, generators, DSSE signer and release admission
  - C2/C8 (identity):  ``ocor_runtime.c2.gateway`` identity resolution, ``ocor_runtime.c8.orchestrator``
                        Fusion/Identity task of the Coordination Kernel
  - C3 (canonical):    ``ocor_runtime.c3.service`` against real PostgreSQL
  - C4 (projection):   ``ocor_runtime.c4`` TypeDB exact-at-commit and Jena/SHACL marking-safe
                        projections; governed-memory context assembly over Qdrant
  - C5 (event):        ``ocor_runtime.c5`` canonical event backbone on a real, isolated Kafka broker
  - C6 (action):       ``ocor_runtime.c6.engine``
  - C7 (causal):       ``ocor_runtime.c7.runtime``
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from ocor_runtime.c1.ports import CompilerRequest
from ocor_runtime.c2.gateway import IdentityBackedAuthority
from ocor_runtime.c2.ports import ConsistencyMode, ConsistencyRequirement, NamedQueryRequest
from ocor_runtime.c3.service import PostgresC3Service
from ocor_runtime.c4.jena_adapter import JenaAdapterError
from ocor_runtime.c4.typedb_adapter import TypeDBAdapterError
from ocor_runtime.c5.subscription import DeliveredEvent
from ocor_runtime.c6.engine import C3CanonicalOutboxView, GovernedActionError
from ocor_runtime.c7.runtime import CausalQuery, estimate_intervention, verify_reproduction
from ocor_runtime.c7.runtime import canonical_digest as causal_pin_digest
from ocor_runtime.c8.orchestrator import AgentRole
from ocor_runtime.kernel.canonical import canonical_digest, parse_i_json
from ocor_runtime.kernel.governed_context import GovernedContext

# NCP-U12-TEST-REALIGNMENT-SCOPE (2026-11-10) option A1: legacy-slice classes only as arguments a retained signature requires.
from ocor_runtime.c2_identity import IdentityRecord, IdentityRegistry  # legacy: c2/gateway.py:209 IdentityBackedAuthority(identity_registry)
from ocor_runtime.c7_emission import EmissionFence  # legacy: c6/engine.py:595 relay

TASK_TESTS = Path(__file__).resolve().parents[1] / "tasks"
if str(TASK_TESTS) not in sys.path:
    sys.path.insert(0, str(TASK_TESTS))

import c4_projection_fixture as c4_world  # noqa: E402
import c5_backbone_fixture as c5_world  # noqa: E402
import c8_orchestrator_fixture as c8_world  # noqa: E402
import test_ocor_dev_0057 as memory_world  # noqa: E402
import test_ocor_dev_rem_0047 as c1_world  # noqa: E402
import test_ocor_dev_rem_0050 as governed_path  # noqa: E402
from c5_kafka_qualification import KafkaBrokerError, QualificationKafkaBroker  # noqa: E402
from c6_action_fixture import ActionWorld  # noqa: E402

DIGEST_A = "urn:sha256:" + "a" * 64
DIGEST_B = "urn:sha256:" + "b" * 64
DIGEST_C = "urn:sha256:" + "c" * 64
NOW = datetime(2026, 9, 13, 14, 0, 0, tzinfo=UTC)
GOLDEN_SCM = Path(__file__).resolve().parents[1] / "techniques/golden/causal_logistics_scm.json"
GOVERNED = governed_path.GovernedC3(
    release=DIGEST_B,
    preconditions=("urn:ocor:precondition:revision-0", "urn:ocor:precondition:governed-action"),
    invariants=("urn:ocor:invariant:mission-thread", "urn:ocor:invariant:governed-action"),
)
ACTIONS = ActionWorld(now=NOW, release=DIGEST_B)
MISSION_ACTION = ACTIONS.action_type("urn:ocor:action-type:mission", risk="R3_HIGH_IMPACT", capability="act:mission")


def governed_engine(c3: PostgresC3Service, context: GovernedContext) -> tuple[Any, Any]:
    outbox_store = C3CanonicalOutboxView(c3, tenant_id=context.tenant_id, aggregate_type="MissionAction")
    fence = EmissionFence(store=outbox_store)  # type: ignore[arg-type]
    path = GOVERNED.engine_path(aggregate_type="MissionAction", governed_context=context)
    engine = ACTIONS.engine(commit_port=c3, relay=fence, canonical_path=path, emission_outbox=outbox_store)
    return outbox_store, engine


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("OCOR_LIVE_POSTGRES_DSN")
    if not dsn:
        pytest.fail("OCOR_LIVE_POSTGRES_DSN is mandatory qualifying evidence")
    return dsn


@pytest.fixture(scope="session")
def typedb_reachable() -> None:
    try:
        c4_world.projection(DIGEST_B).initialize()
    except (TypeDBAdapterError, OSError) as error:
        pytest.fail(f"a real, live TypeDB instance is mandatory qualifying evidence: {error}")


@pytest.fixture(scope="session")
def fuseki_reachable() -> None:
    try:
        c4_world.jena_projection(DIGEST_B).reset()
    except (JenaAdapterError, OSError) as error:
        pytest.fail(f"a real, live Fuseki instance is mandatory qualifying evidence: {error}")


def compile_mission_fixture(mission_id: str) -> Any:
    with tempfile.TemporaryDirectory() as workdir:
        signing = c1_world._Signing(Path(workdir))
        request: CompilerRequest = c1_world.oac_request()
        package = c1_world._package(signing, request)
        signing.admission().verify(package)  # VerifyRelease (ADD v1.3 :523) raises on a package it does not admit
    return package.signed.release


def resolve_operator_identity() -> tuple[IdentityRegistry, str]:
    registry = IdentityRegistry()
    registry.register(IdentityRecord(canonical_id="urn:ocor:operator:alice", aliases={"alice"}))
    probe = make_governed_context(correlation_id=str(uuid.uuid4()), effective_principal_id="alice")
    canonical_id = IdentityBackedAuthority(registry).resolve(make_typedb_query(fact_id="operator", context=probe, required_commit=None))
    # NCP-U12-MISSION-THREAD-RESIDUAL-ASSERTIONS option 1: the canonical id the retained gateway resolution returns
    # (c2/gateway.py:200-215), equal to the registered one and never the ABSTAIN value.
    assert canonical_id == "urn:ocor:operator:alice"
    assert canonical_id != "ABSTAIN"
    return registry, canonical_id


def make_governed_context(*, correlation_id: str, effective_principal_id: str) -> GovernedContext:
    return GovernedContext.from_mapping(
        {
            "tenant_id": "urn:ocor:tenant:synthetic",
            "organization_id": "urn:ocor:org:synthetic",
            "domain_id": "urn:ocor:domain:logistics",
            "compartments": ["urn:ocor:compartment:alpha"],
            "classification_marking_ref": DIGEST_A,
            "purpose": "mission-thread",
            "effective_principal_id": effective_principal_id,
            "actor_chain": ["urn:ocor:actor:synthetic", effective_principal_id],
            "ontology_release_digest": DIGEST_B,
            "policy_bundle_digest": DIGEST_C,
            "correlation_id": correlation_id,
        }
    )


def make_typedb_query(*, fact_id: str, context: GovernedContext, required_commit: str | None) -> NamedQueryRequest:
    consistency = (
        ConsistencyRequirement(mode=ConsistencyMode.BEST_AVAILABLE)
        if required_commit is None
        else ConsistencyRequirement(mode=ConsistencyMode.EXACT_AT_COMMIT, required_commit=required_commit)
    )
    return NamedQueryRequest(
        request_id=str(uuid.uuid4()),
        contract_id="urn:ocor:contract:named-query:mission-thread",
        contract_version="1.0.0",
        contract_digest=DIGEST_A,
        parameters={"fact_id": fact_id},
        governed_context=context,
        governed_context_digest=context.digest(),
        consistency=consistency,
    )


class _SimulatedEffectSink:
    def __init__(self, kafka_record_digest: str) -> None:
        self.kafka_record_digest = kafka_record_digest
        self.calls: list[tuple[Any, str]] = []

    def emit(self, event: Any, *, idempotency_key: str) -> dict[str, Any]:
        self.calls.append((event, idempotency_key))
        return {"simulated": True, "kafka_record_digest": self.kafka_record_digest}


@dataclass(frozen=True, slots=True)
class _Record:
    """A delivered C5 event as the thread reads it: the payload and the integrity digest."""

    value: dict[str, Any]
    payload_digest: str


class _Backbone:
    """The C5 canonical event backbone of one topic on an isolated broker (c5_backbone_fixture.C5Rig)."""

    def __init__(self, broker: QualificationKafkaBroker, topic: str, dsn: str) -> None:
        self.broker, self.topic, self.dsn = broker, topic, dsn
        self.rig = c5_world.C5Rig(broker, topic, dsn=dsn, schema=f"ocor_mission_{uuid.uuid4().hex[:12]}")
        self.revisions: dict[str, int] = {}

    def produce(self, records: list[dict[str, Any]]) -> None:
        for record in records:
            ordering_key = str(record["aggregate_id"])
            self.revisions[ordering_key] = self.revisions.get(ordering_key, 0) + 1
            self.rig.publish(c5_world.draft(aggregate_ref=ordering_key, sequence=self.revisions[ordering_key],
                                            correlation_id=str(record["correlation_id"]),
                                            payload={k: str(v) for k, v in record.items()}))

    def consume(self, count: int) -> list[_Record]:
        events: tuple[DeliveredEvent, ...] = self.rig.consume(count)
        return [_Record(value=dict(event.envelope["payload"]), payload_digest=event.envelope["integrity"]["payload_digest"])
                for event in events]

    def restart_broker(self) -> None:
        self.broker.stop()
        self.broker.start()
        self.rig = self.rig.restarted()


@dataclass(frozen=True, slots=True)
class MissionThreadReceipts:
    canonical_ir_digest: str
    commit_id: str
    typedb_result_digest: str
    jena_authorized: bool
    context_receipt_digest: str
    kafka_record_digest: str
    action_event_id: str
    agent_decision: Any
    causal_outcome: Any


def run_mission_thread(
    *, correlation_id: str, postgres_dsn: str, kafka: _Backbone, topic: str, qdrant: Any, collection: Any
) -> MissionThreadReceipts:
    mission_id = f"urn:ocor:resource:mission-{correlation_id}"

    # C1 -- compile, generate, sign and admit the release.
    release = compile_mission_fixture(mission_id)

    # C2/C8 -- the gateway resolves the operator identity; the Fusion/Identity task of the kernel reports it.
    registry, effective_principal_id = resolve_operator_identity()
    team = c8_world.TeamWorld(postgres_dsn, members=(("team-lead-1", "COORDINATOR"), ("agent-1", "FUSION_IDENTITY")))
    identity_task_id = f"urn:ocor:task:mission-identity:{correlation_id}"
    team.accepted(identity_task_id, "agent-1", role=AgentRole.FUSION_IDENTITY.name)
    identity_output = {"summary": effective_principal_id}
    identity_task = team.orchestrator.complete(identity_task_id, output=identity_output, evidence_refs=("urn:ocor:evidence:operator-alias",),
                                               at=c8_world.NOW, **c8_world.caller("agent-1"))
    # NCP-U12-TEST-REALIGNMENT-SCOPE option B1: the typed outcome of the Fusion/Identity role of the current C8 kernel over the
    # gateway resolution (ADD v1.3 :3057-3064, :3101-3106): a completed FusionIdentityFinding@1 bound to the validated output.
    assert (identity_task.state.value, identity_task.output_type, identity_task.output_digest) == (
        "COMPLETED", "FusionIdentityFinding@1", canonical_digest(identity_output))

    context = make_governed_context(correlation_id=correlation_id, effective_principal_id=effective_principal_id)

    c3 = PostgresC3Service(postgres_dsn, admission=GOVERNED.admission())
    c3.initialize()
    command = GOVERNED.command(
        {
            "command_id": f"urn:ocor:command:mission-thread:{correlation_id}",
            "action_instance_id": f"urn:ocor:action:mission-thread:{correlation_id}",
            "aggregate_type": "MissionObject",
            "aggregate_ref": f"urn:ocor:mission-object:{correlation_id}",
            "expected_revision": 0,
            "canonical_delta": {"ir_digest": release.ir_digest, "status": "ASSESSED"},
            "decision_ref": f"urn:ocor:decision:mission-thread:{correlation_id}",
            "authority_ref": f"urn:ocor:authority:mission-thread:{correlation_id}",
            "evidence_refs": [release.ir_digest],
            "claim_source_bindings": [
                {
                    "claim_ref": f"urn:ocor:claim:mission-thread:{correlation_id}",
                    "source_ref": f"urn:ocor:source:mission-thread:{correlation_id}",
                    "evidence_ref": release.ir_digest,
                }
            ],
            "precondition_bindings": ["urn:ocor:precondition:revision-0"],
            "invariant_bindings": ["urn:ocor:invariant:mission-thread"],
            "idempotency_key": f"mission-thread-key-{correlation_id}",
            "governed_context": context.to_mapping(),
            "governed_context_digest": context.digest(),
            "branch": "main",
        }
    )
    commit_receipt = c3.commit(command)

    # C4a -- TypeDB projection exact-at-commit.
    typedb = c4_world.projection(DIGEST_B)
    typedb.reset()
    typedb.apply_commit(fact_id=correlation_id, commit_id=commit_receipt.commit_id, payload=release.ir_digest)
    typedb_response = typedb.read(
        make_typedb_query(fact_id=correlation_id, context=context, required_commit=commit_receipt.commit_id)
    )

    # C4b -- Jena/SHACL marking-safe projection.
    jena = c4_world.jena_projection(DIGEST_B)
    jena.reset()
    jena.publish(mission_id, {"label": "first governed mission thread",
                              "provenanceRef": f"urn:ocor:provenance:mission-thread:{correlation_id}"},
                 marking=c4_world.classification_marking("UNCLASSIFIED"), commit_id=commit_receipt.commit_id)
    authorized = jena.list_authorized(c4_world.classification_marking("UNCLASSIFIED"))
    jena_authorized = any(row["resource"] == mission_id for row in authorized)

    # C4c -- governed-memory context assembly over Qdrant (vector), PostgreSQL and OpenBao.
    world = qdrant.world()
    world.admit("mission-1", f"objective: first governed mission thread commit: {commit_receipt.commit_id}")
    audit = qdrant.audit(world)
    context_receipt = memory_world.assembler(world, audit, memory_world.ContextPolicy()).assemble(
        memory_world.assembly_request(world, text="first governed mission thread", operation=f"mission-{correlation_id}"),
        binding=memory_world.binding())

    # C5 -- canonical event backbone.
    kafka.produce([{"aggregate_id": mission_id, "correlation_id": correlation_id,
                    "commit_id": commit_receipt.commit_id, "ir_digest": release.ir_digest}])
    (kafka_record,) = kafka.consume(1)

    # C6 -- Authority -> Human Gate -> Decision -> EMISSION-FENCE -> simulated effect.
    outbox_store, engine = governed_engine(c3, context)
    sink = _SimulatedEffectSink(kafka_record.payload_digest)
    proposal = ACTIONS.proposal(
        MISSION_ACTION,
        action_id=f"urn:ocor:action:mission-thread:{correlation_id}",
        proposer=effective_principal_id,
        target=mission_id,
        governed_context_digest=context.digest(),
    )
    approval_set = ACTIONS.approval_set(proposal)
    decision = ACTIONS.decide(proposal, approval_set, rationale="within approved risk ceiling")
    lease = ACTIONS.lease(proposal, decision)
    action_outcome = engine.execute(proposal, lease=lease, approval=approval_set, decision=decision, sink=sink, at=NOW)
    assert len(sink.calls) == 1

    # C7 -- causal runtime; its causation_id is the C6 action's emission event id.
    golden = parse_i_json(GOLDEN_SCM.read_text(encoding="utf-8"))
    causal_query = CausalQuery(
        baseline_commit=commit_receipt.commit_id,
        scenario_branch="scenario/mission-thread",
        model_digest=causal_pin_digest(golden["model"]),
        data_digest=causal_pin_digest(golden["factual_rows"]),
        intervention_digest=causal_pin_digest(golden["intervention"]),
        ontology_release_digest=DIGEST_B,
        expected_release_digest=DIGEST_B,
        treatment="expedite",
        outcome="delay_hours",
        seed=golden["seed"],
        correlation_id=correlation_id,
        causation_id=action_outcome.emission_receipt.event_id,
    )
    causal_outcome = estimate_intervention(causal_query, model=golden["model"], factual_rows=golden["factual_rows"],
                                           intervention=golden["intervention"])

    return MissionThreadReceipts(
        canonical_ir_digest=release.ir_digest,
        commit_id=commit_receipt.commit_id,
        typedb_result_digest=typedb_response.result_digest,
        jena_authorized=jena_authorized,
        context_receipt_digest=context_receipt.audit_ref,
        kafka_record_digest=kafka_record.payload_digest,
        action_event_id=action_outcome.emission_receipt.event_id,
        agent_decision=identity_output["summary"],
        causal_outcome=causal_outcome,
    )


@contextmanager
def _kafka_backbone(postgres_dsn: str) -> Iterator[tuple[_Backbone, str]]:
    """An isolated Kafka broker with one topic and the C5 backbone over it, destroyed on exit."""
    try:
        broker, _container, volume = QualificationKafkaBroker.provision(f"ocor-mission-thread-{uuid.uuid4().hex[:12]}")
    except KafkaBrokerError as error:
        pytest.fail(f"a real, isolated Kafka broker is mandatory qualifying evidence: {error}")
    topic = broker.create_topic(f"ocor-mission-thread-{uuid.uuid4().hex[:12]}")
    try:
        yield _Backbone(broker, topic, postgres_dsn), topic
    finally:
        broker.destroy(volume)


@contextmanager
def _memory_backends(postgres_dsn: str) -> Iterator[tuple[Any, None]]:
    """Qdrant, OpenBao and the governed-memory backends over them, released on exit."""
    qdrant = memory_world.r.base.QdrantHarness.provision()
    bao = memory_world.OpenBaoHarness.provision()
    backends = memory_world.Backends(dsn=postgres_dsn, qdrant=qdrant, bao=bao)
    try:
        yield backends, None
    finally:
        try:
            backends.release()
        finally:
            try:
                bao.destroy()
            finally:
                qdrant.destroy()


@pytest.fixture
def kafka_topic(typedb_reachable: None, fuseki_reachable: None, postgres_dsn: str):
    with _kafka_backbone(postgres_dsn) as backbone:
        yield backbone


@pytest.fixture
def qdrant_collection(postgres_dsn: str):
    with _memory_backends(postgres_dsn) as backends:
        yield backends


def test_mission_thread_produces_correlated_receipts_across_all_governed_components(
    postgres_dsn: str, kafka_topic, qdrant_collection
):
    kafka, topic = kafka_topic
    qdrant, collection = qdrant_collection
    correlation_id = str(uuid.uuid4())

    receipts = run_mission_thread(
        correlation_id=correlation_id,
        postgres_dsn=postgres_dsn,
        kafka=kafka,
        topic=topic,
        qdrant=qdrant,
        collection=collection,
    )

    assert receipts.canonical_ir_digest.startswith("urn:sha256:")
    assert receipts.commit_id
    assert receipts.typedb_result_digest.startswith("urn:sha256:")
    assert receipts.jena_authorized is True
    assert receipts.context_receipt_digest.startswith("urn:sha256:")
    # B1: the C5 envelope integrity.payload_digest, sha256: followed by 64 lowercase hex digits (LLD v1.1 :154).
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", receipts.kafka_record_digest)
    # B1: the identity in the typed output of the Fusion/Identity role, the canonical one resolved (ADD v1.3 :3057-3064).
    assert receipts.agent_decision == "urn:ocor:operator:alice"
    # B1: the retained causal runtime returns ESTIMATED for an identified estimand (ADD v1.3 :2981).
    assert receipts.causal_outcome.status == "ESTIMATED"
    # NCP-U12-MISSION-THREAD-RESIDUAL-ASSERTIONS option 1: the trace identifiers, outside the lineage and the
    # reproducibility digest (NCR-C7-005; Register v1.1 :61).
    assert receipts.causal_outcome.trace["correlation_id"] == correlation_id
    assert receipts.causal_outcome.trace["causation_id"] == receipts.action_event_id


def test_causal_receipt_reproduces_identically_with_the_same_pinned_inputs(
    postgres_dsn: str, kafka_topic, qdrant_collection
):
    kafka, topic = kafka_topic
    qdrant, collection = qdrant_collection
    correlation_id = str(uuid.uuid4())

    first = run_mission_thread(
        correlation_id=correlation_id,
        postgres_dsn=postgres_dsn,
        kafka=kafka,
        topic=topic,
        qdrant=qdrant,
        collection=collection,
    )
    golden = parse_i_json(GOLDEN_SCM.read_text(encoding="utf-8"))
    second_outcome = estimate_intervention(
        CausalQuery(
            baseline_commit=first.commit_id,
            scenario_branch="scenario/mission-thread",
            model_digest=first.causal_outcome.lineage["model_digest"],
            data_digest=first.causal_outcome.lineage["data_digest"],
            intervention_digest=first.causal_outcome.lineage["intervention_digest"],
            ontology_release_digest=DIGEST_B,
            expected_release_digest=DIGEST_B,
            treatment="expedite",
            outcome="delay_hours",
            seed=golden["seed"],
            correlation_id=correlation_id,
            causation_id=first.action_event_id,
        ),
        model=golden["model"],
        factual_rows=golden["factual_rows"],
        intervention=golden["intervention"],
    )
    verify_reproduction(first.causal_outcome, second_outcome)


def test_action_denied_at_authority_halts_the_thread_before_any_effect(postgres_dsn: str):
    correlation_id = str(uuid.uuid4())
    mission_id = f"urn:ocor:resource:mission-{correlation_id}"
    registry, effective_principal_id = resolve_operator_identity()
    c3 = PostgresC3Service(postgres_dsn, admission=GOVERNED.admission())
    c3.initialize()
    context = make_governed_context(correlation_id=correlation_id, effective_principal_id=effective_principal_id)
    outbox_store, engine = governed_engine(c3, context)
    calls: list[Any] = []
    proposal = ACTIONS.proposal(
        MISSION_ACTION,
        action_id=f"urn:ocor:action:mission-thread:{correlation_id}",
        proposer=effective_principal_id,
        target=mission_id,
        governed_context_digest=context.digest(),
    )
    lease = ACTIONS.lease(proposal, capability_id="act:read-only")
    approval_set = ACTIONS.approval_set(proposal)

    with pytest.raises(GovernedActionError) as excinfo:
        engine.execute(
            proposal,
            lease=lease,
            approval=approval_set,
            decision=ACTIONS.decide(proposal, approval_set, rationale="ok"),
            sink=lambda event, *, idempotency_key: calls.append(event),
            at=NOW,
        )

    assert excinfo.value.reason_code == "AUTHORITY_DENIED"
    assert calls == []
    assert outbox_store.get(proposal.aggregate_id) is None


def test_typedb_projection_read_enforces_exact_at_commit_consistency_with_the_real_canonical_commit(
    postgres_dsn: str, typedb_reachable: None
):
    from ocor_runtime.c2.ports import C2Error

    correlation_id = str(uuid.uuid4())
    registry, effective_principal_id = resolve_operator_identity()
    context = make_governed_context(correlation_id=correlation_id, effective_principal_id=effective_principal_id)

    c3 = PostgresC3Service(postgres_dsn, admission=GOVERNED.admission())
    c3.initialize()
    command = GOVERNED.command(
        {
            "command_id": f"urn:ocor:command:mission-thread-consistency:{correlation_id}",
            "action_instance_id": f"urn:ocor:action:mission-thread-consistency:{correlation_id}",
            "aggregate_type": "MissionObject",
            "aggregate_ref": f"urn:ocor:mission-object:{correlation_id}",
            "expected_revision": 0,
            "canonical_delta": {"status": "ASSESSED"},
            "decision_ref": f"urn:ocor:decision:mission-thread-consistency:{correlation_id}",
            "authority_ref": f"urn:ocor:authority:mission-thread-consistency:{correlation_id}",
            "evidence_refs": [DIGEST_A],
            "claim_source_bindings": [
                {
                    "claim_ref": f"urn:ocor:claim:mission-thread-consistency:{correlation_id}",
                    "source_ref": f"urn:ocor:source:mission-thread-consistency:{correlation_id}",
                    "evidence_ref": DIGEST_A,
                }
            ],
            "precondition_bindings": ["urn:ocor:precondition:revision-0"],
            "invariant_bindings": ["urn:ocor:invariant:mission-thread"],
            "idempotency_key": f"mission-thread-consistency-key-{correlation_id}",
            "governed_context": context.to_mapping(),
            "governed_context_digest": context.digest(),
            "branch": "main",
        }
    )
    commit_receipt = c3.commit(command)

    typedb = c4_world.projection(DIGEST_B)
    typedb.reset()
    # The commit is observed but never applied: a read demanding EXACT_AT_COMMIT must fail closed.
    typedb.observe(commit_receipt.commit_id)
    with pytest.raises(C2Error) as excinfo:
        typedb.read(make_typedb_query(fact_id=correlation_id, context=context, required_commit=commit_receipt.commit_id))
    # NCP-U03 (NCR-C2-012): PROJECTION_NOT_READY, never a downgrade -- docs/OCOR_LLD_v1.1.md:369
    assert excinfo.value.reason_code == "PROJECTION_NOT_READY"


def test_a_real_kafka_broker_restart_during_the_event_step_is_detected_and_recovers(kafka_topic):
    kafka, topic = kafka_topic
    correlation_id = str(uuid.uuid4())
    mission_id = f"urn:ocor:resource:mission-{correlation_id}"

    kafka.produce([{"aggregate_id": mission_id, "correlation_id": correlation_id, "phase": "before-restart"}])
    (before,) = kafka.consume(1)
    assert before.value["phase"] == "before-restart"

    kafka.restart_broker()

    kafka.produce([{"aggregate_id": mission_id, "correlation_id": correlation_id, "phase": "after-restart"}])
    records = kafka.consume(2)
    assert [record.value["phase"] for record in records] == ["before-restart", "after-restart"]
