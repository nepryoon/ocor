"""OCOR-DEV-0031: Integrate first real C1-C8 synthetic mission thread.

Proves that a single content-addressed fixture, identified by one
``correlation_id``, crosses every real selected service this delivery
has built or spiked and produces correlated canonical, projection,
event, causal, agent and action receipts:

  - C1 (compile):      ``ocor_runtime.c1.compiler`` (OCOR-DEV-0028, retained)
  - C2/C8 (identity):  ``ocor_runtime.c2_identity``/``ocor_runtime.c8_agent`` (retained)
  - C3 (canonical):    ``ocor_runtime.c3.service`` against real PostgreSQL (OCOR-DEV-0029, retained)
  - C4 (projection):   real TypeDB exact-at-commit (OCOR-DEV-0017), real
                        Fuseki marking-safe read (OCOR-DEV-0018), and a
                        real Qdrant-ranked context assembly (OCOR-DEV-0027)
  - C5 (event):        real, self-provisioned Kafka (OCOR-DEV-0019)
  - C6 (action):       ``ocor_runtime.c6.engine`` (OCOR-DEV-0030, retained)
  - C7 (causal):        the sealed causal-reproducibility oracle (OCOR-DEV-0022)

Every backend is real; no mocks anywhere in the qualifying path. The C6
action's own ``causation_id`` (its emission event id) becomes the C7
causal query's ``causation_id``, so the thread is a genuine causal
chain, not just a shared label. Reuses every sealed/spiked component
unmodified; this task adds no new production code, only the thread
itself.
"""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from ocor_runtime.c1.compiler import RetainedCanonicalIrBuilder
from ocor_runtime.c1.ports import CompilerRequest, SourceSyntax, SourceUnit
from ocor_runtime.c2.ports import ConsistencyMode, ConsistencyRequirement, NamedQueryRequest
from ocor_runtime.c2_identity import IdentityRecord, IdentityRegistry, ResolutionStatus
from ocor_runtime.c3.ports import GovernedCanonicalCommitCommand
from ocor_runtime.c3.service import PostgresC3Service
from ocor_runtime.c3_store import AtomicOutboxStore
from ocor_runtime.c4_marking import MarkingEngine, MarkingSchemeDefinition, MarkingSet
from ocor_runtime.c6.engine import (
    ActionProposal,
    Approval,
    Decision,
    GovernedActionEngine,
    GovernedActionError,
)
from ocor_runtime.c6_capabilities import CapabilityAuthority
from ocor_runtime.c7_emission import EmissionFence
from ocor_runtime.c8_agent import AgentDecision, AgentKernel
from ocor_runtime.kernel.governed_context import GovernedContext

# The spikes/ package lives at the repository root, a sibling of
# ocor-runtime/, and is outside ocor-runtime's own pytest pythonpath
# (["src"]). Explicit insertion here is required and must not depend on
# collection order: this file sorts alphabetically before
# ocor-runtime/tests/tasks/, so it cannot rely on another test module's
# own sys.path.insert side effect running first.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from spikes.causal_reproducibility.oracle import CausalQuery  # noqa: E402
from spikes.causal_reproducibility.oracle import canonical_digest as causal_pin_digest  # noqa: E402
from spikes.causal_reproducibility.oracle import execute as run_causal_query  # noqa: E402
from spikes.causal_reproducibility.oracle import verify_reproduction  # noqa: E402
from spikes.context_replay.replay import AssemblyRequest, PinnedItem, assemble_context  # noqa: E402
from spikes.jena_marking.adapter import JenaAdapterError, JenaMarkingProjectionAdapter  # noqa: E402
from spikes.kafka_delivery.oracle import KafkaCli  # noqa: E402
from spikes.typedb_exact_commit.adapter import TypeDBAdapterError, TypeDBExactCommitAdapter  # noqa: E402
from spikes.vector_partition.oracle import QdrantHarness  # noqa: E402

COMMIT = "0123456789abcdef0123456789abcdef01234567"
DIGEST_A = "urn:sha256:" + "a" * 64
DIGEST_B = "urn:sha256:" + "b" * 64
DIGEST_C = "urn:sha256:" + "c" * 64
CLASSIFICATION_SCHEME = MarkingSchemeDefinition("classification", levels=("UNCLASSIFIED", "SECRET"))
NOW = datetime(2026, 9, 13, 14, 0, 0, tzinfo=UTC)


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("OCOR_LIVE_POSTGRES_DSN")
    if not dsn:
        pytest.fail("OCOR_LIVE_POSTGRES_DSN is mandatory qualifying evidence")
    return dsn


@pytest.fixture(scope="session")
def typedb_reachable() -> None:
    try:
        TypeDBExactCommitAdapter().initialize()
    except (TypeDBAdapterError, OSError) as error:
        pytest.fail(f"a real, live TypeDB instance is mandatory qualifying evidence: {error}")


@pytest.fixture(scope="session")
def fuseki_reachable() -> None:
    try:
        JenaMarkingProjectionAdapter(MarkingEngine([CLASSIFICATION_SCHEME])).reset()
    except (JenaAdapterError, OSError) as error:
        pytest.fail(f"a real, live Fuseki instance is mandatory qualifying evidence: {error}")


def compile_mission_fixture(mission_id: str) -> Any:
    source = SourceUnit.create(
        resource_id=mission_id,
        version="1",
        syntax=SourceSyntax.YAML,
        content=f"id: {mission_id}\nfields:\n  objective: 'first governed mission thread'\n".encode(),
        source_path="mission.yaml",
    )
    request = CompilerRequest(
        package_id="urn:ocor:package:mission-thread",
        semantic_version="1.0.0",
        source_commit=COMMIT,
        compiler_version="0.1.0",
        mapping_version="1",
        release_profile="poc",
        sources=(source,),
        dependency_lock=(),
    )
    return RetainedCanonicalIrBuilder().build(request)


def resolve_operator_identity() -> tuple[IdentityRegistry, str]:
    registry = IdentityRegistry()
    registry.register(IdentityRecord(canonical_id="urn:ocor:operator:alice", aliases={"alice"}))
    outcome = registry.resolve("alice")
    assert outcome.status is ResolutionStatus.IDENTIFIED
    assert outcome.canonical_id is not None
    return registry, outcome.canonical_id


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
    """A real EventSink implementation (matching ocor_runtime.c7_emission's
    Protocol exactly) recording the durable event and idempotency key
    EMISSION-FENCE released for the simulated external effect."""

    def __init__(self, kafka_record_digest: str) -> None:
        self.kafka_record_digest = kafka_record_digest
        self.calls: list[tuple[Any, str]] = []

    def emit(self, event: Any, *, idempotency_key: str) -> dict[str, Any]:
        self.calls.append((event, idempotency_key))
        return {"simulated": True, "kafka_record_digest": self.kafka_record_digest}


@dataclass(frozen=True, slots=True)
class MissionThreadReceipts:
    canonical_ir_digest: str
    commit_id: str
    typedb_result_digest: str
    jena_authorized: bool
    context_receipt_digest: str
    kafka_record_digest: str
    action_event_id: str
    agent_decision: AgentDecision
    causal_outcome: Any


def run_mission_thread(
    *, correlation_id: str, postgres_dsn: str, kafka: KafkaCli, topic: str, qdrant: QdrantHarness, collection: str
) -> MissionThreadReceipts:
    mission_id = f"urn:ocor:resource:mission-{correlation_id}"

    # C1 -- compile the content-addressed fixture.
    release = compile_mission_fixture(mission_id)

    # C2/C8 -- resolve the operator identity, shared by the agent kernel.
    registry, effective_principal_id = resolve_operator_identity()
    agent = AgentKernel(identity_registry=registry, subject=effective_principal_id)
    agent_response = agent.identify_or_abstain("alice")
    assert agent_response.decision is AgentDecision.IDENTIFY

    context = make_governed_context(correlation_id=correlation_id, effective_principal_id=effective_principal_id)

    # C3 -- real canonical commit against real PostgreSQL.
    c3 = PostgresC3Service(postgres_dsn)
    c3.initialize()
    command = GovernedCanonicalCommitCommand.from_mapping(
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
            "gate_package_digest": DIGEST_C,
            "branch": "main",
        }
    )
    commit_receipt = c3.commit(command)

    # C4a -- real TypeDB exact-at-commit projection read.
    typedb = TypeDBExactCommitAdapter()
    typedb.reset()
    typedb.ingest(correlation_id, commit_receipt.commit_id, release.ir_digest)
    typedb.advance_watermark(commit_receipt.commit_id)
    typedb_response = typedb.read(
        make_typedb_query(fact_id=correlation_id, context=context, required_commit=commit_receipt.commit_id)
    )

    # C4b -- real Fuseki marking-safe projection read.
    jena = JenaMarkingProjectionAdapter(MarkingEngine([CLASSIFICATION_SCHEME]))
    jena.reset()
    jena.ingest_marked(mission_id, "first governed mission thread", "UNCLASSIFIED")
    authorized = jena.list_authorized(MarkingSet({"classification": "UNCLASSIFIED"}))
    jena_authorized = any(row["resource"] == mission_id for row in authorized)

    # C4c -- real Qdrant-ranked context assembly (reused unmodified from OCOR-DEV-0027).
    qdrant.request(
        "PUT",
        f"/collections/{collection}/points?wait=true",
        {"points": [{"id": 1, "vector": [1.0, 0.0, 0.0, 0.0], "payload": {"item_id": mission_id}}]},
    )
    context_receipt = assemble_context(
        qdrant,
        collection,
        AssemblyRequest(query_vector=(1.0, 0.0, 0.0, 0.0), top_k=1, redact_fields=(), truncation_chars=10_000),
        (PinnedItem(mission_id, "1", f"objective: first governed mission thread\ncommit: {commit_receipt.commit_id}"),),
    )

    # C5 -- real, self-provisioned Kafka event.
    kafka.produce(
        topic,
        [
            {
                "aggregate_id": mission_id,
                "correlation_id": correlation_id,
                "commit_id": commit_receipt.commit_id,
                "ir_digest": release.ir_digest,
            }
        ],
    )
    (kafka_record,) = kafka.consume(topic, 1)

    # C6 -- the governed-action slice (OCOR-DEV-0030): Authority -> Human
    # Gate -> Decision -> EMISSION-FENCE -> simulated effect.
    authority = CapabilityAuthority(issuer="ocor-mission-thread-authority")
    lease = authority.issue(
        subject=effective_principal_id,
        capabilities=["act:mission"],
        resources=[mission_id],
        issued_at=NOW,
        ttl=timedelta(hours=1),
    )
    outbox_store = AtomicOutboxStore()
    fence = EmissionFence(store=outbox_store)
    engine = GovernedActionEngine(authority=authority, store=outbox_store, fence=fence)
    sink = _SimulatedEffectSink(kafka_record.canonical_digest)

    proposal = ActionProposal(
        action_id=f"urn:ocor:action:mission-thread:{correlation_id}",
        subject=effective_principal_id,
        capability="act:mission",
        resource=mission_id,
        aggregate_id=f"urn:ocor:mission-action:{correlation_id}",
        risk_bearing=True,
    )
    action_outcome = engine.execute(
        proposal,
        lease=lease,
        approval=Approval(proposal.action_id, "urn:ocor:human:approver-1", True, NOW),
        decision=Decision(proposal.action_id, "urn:ocor:human:decider-1", True, "within approved risk ceiling", NOW),
        sink=sink,
        at=NOW,
    )
    assert len(sink.calls) == 1

    # C7 -- the sealed causal-reproducibility oracle. Its causation_id is
    # the C6 action's own emission event id: a genuine causal chain, not
    # a shared label.
    model = {"kind": "stratified-ate", "version": "1"}
    factual_rows = [
        {"stratum": "a", "treated": 0, "outcome": "1.0"},
        {"stratum": "a", "treated": 1, "outcome": "1.5"},
        {"stratum": "b", "treated": 0, "outcome": "2.0"},
        {"stratum": "b", "treated": 1, "outcome": "2.4"},
    ]
    intervention = {"value": 1, "valid_envelope": [0, 1]}
    causal_query = CausalQuery(
        baseline_commit=COMMIT,
        scenario_branch="scenario/mission-thread",
        model_digest=causal_pin_digest(model),
        data_digest=causal_pin_digest(factual_rows),
        intervention_digest=causal_pin_digest(intervention),
        ontology_release_digest=DIGEST_B,
        expected_release_digest=DIGEST_B,
        treatment="treated",
        outcome="outcome",
        adjustment="stratum",
        seed=42,
        correlation_id=correlation_id,
        causation_id=action_outcome.emission_receipt.event_id,
    )
    causal_outcome = run_causal_query(causal_query, model=model, factual_rows=factual_rows, intervention=intervention)

    return MissionThreadReceipts(
        canonical_ir_digest=release.ir_digest,
        commit_id=commit_receipt.commit_id,
        typedb_result_digest=typedb_response.result_digest,
        jena_authorized=jena_authorized,
        context_receipt_digest=context_receipt.receipt_digest,
        kafka_record_digest=kafka_record.canonical_digest,
        action_event_id=action_outcome.emission_receipt.event_id,
        agent_decision=agent_response.decision,
        causal_outcome=causal_outcome,
    )


@pytest.fixture
def kafka_topic(typedb_reachable: None, fuseki_reachable: None):
    kafka, volume = KafkaCli.provision()
    topic = f"ocor-mission-thread-{uuid.uuid4().hex[:12]}"
    kafka.create_topic(topic)
    try:
        yield kafka, topic
    finally:
        kafka.destroy(volume)


@pytest.fixture
def qdrant_collection():
    qdrant = QdrantHarness.provision()
    collection = f"ocor_mission_thread_{uuid.uuid4().hex[:12]}"
    qdrant.request("PUT", f"/collections/{collection}", {"vectors": {"size": 4, "distance": "Cosine"}})
    try:
        yield qdrant, collection
    finally:
        qdrant.destroy()


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
    assert len(receipts.kafka_record_digest) == 64  # KafkaRecord.canonical_digest is raw lowercase hex, no URN prefix
    assert receipts.agent_decision is AgentDecision.IDENTIFY
    assert receipts.causal_outcome.status == "IDENTIFIED"
    assert receipts.causal_outcome.lineage["correlation_id"] == correlation_id
    assert receipts.causal_outcome.lineage["causation_id"] == receipts.action_event_id


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
    # Re-run the pure, in-memory C7 step alone with the identical pinned
    # query (a second full thread would mint a new commit/event and thus
    # a genuinely different, not just re-run, causation_id).
    second_outcome = run_causal_query(
        CausalQuery(
            baseline_commit=COMMIT,
            scenario_branch="scenario/mission-thread",
            model_digest=first.causal_outcome.lineage["model_digest"],
            data_digest=first.causal_outcome.lineage["data_digest"],
            intervention_digest=first.causal_outcome.lineage["intervention_digest"],
            ontology_release_digest=DIGEST_B,
            expected_release_digest=DIGEST_B,
            treatment="treated",
            outcome="outcome",
            adjustment="stratum",
            seed=42,
            correlation_id=correlation_id,
            causation_id=first.action_event_id,
        ),
        model={"kind": "stratified-ate", "version": "1"},
        factual_rows=[
            {"stratum": "a", "treated": 0, "outcome": "1.0"},
            {"stratum": "a", "treated": 1, "outcome": "1.5"},
            {"stratum": "b", "treated": 0, "outcome": "2.0"},
            {"stratum": "b", "treated": 1, "outcome": "2.4"},
        ],
        intervention={"value": 1, "valid_envelope": [0, 1]},
    )
    verify_reproduction(first.causal_outcome, second_outcome)


def test_action_denied_at_authority_halts_the_thread_before_any_effect(postgres_dsn: str):
    correlation_id = str(uuid.uuid4())
    mission_id = f"urn:ocor:resource:mission-{correlation_id}"
    registry, effective_principal_id = resolve_operator_identity()
    authority = CapabilityAuthority(issuer="ocor-mission-thread-authority")
    # A lease granting the WRONG capability -- Authority must deny before
    # any canonical commit, projection, event or causal step is ever reached.
    lease = authority.issue(
        subject=effective_principal_id,
        capabilities=["act:read-only"],
        resources=[mission_id],
        issued_at=NOW,
        ttl=timedelta(hours=1),
    )
    outbox_store = AtomicOutboxStore()
    fence = EmissionFence(store=outbox_store)
    engine = GovernedActionEngine(authority=authority, store=outbox_store, fence=fence)
    calls: list[Any] = []
    proposal = ActionProposal(
        action_id=f"urn:ocor:action:mission-thread:{correlation_id}",
        subject=effective_principal_id,
        capability="act:mission",
        resource=mission_id,
        aggregate_id=f"urn:ocor:mission-action:{correlation_id}",
        risk_bearing=True,
    )

    with pytest.raises(GovernedActionError) as excinfo:
        engine.execute(
            proposal,
            lease=lease,
            approval=Approval(proposal.action_id, "urn:ocor:human:approver-1", True, NOW),
            decision=Decision(proposal.action_id, "urn:ocor:human:decider-1", True, "ok", NOW),
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

    c3 = PostgresC3Service(postgres_dsn)
    c3.initialize()
    command = GovernedCanonicalCommitCommand.from_mapping(
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
            "gate_package_digest": DIGEST_C,
            "branch": "main",
        }
    )
    commit_receipt = c3.commit(command)

    typedb = TypeDBExactCommitAdapter()
    typedb.reset()
    typedb.ingest(correlation_id, commit_receipt.commit_id, "payload")
    # Deliberately never advance the watermark to this commit -- a read
    # demanding EXACT_AT_COMMIT consistency must fail closed, never
    # silently serve the row as if it were already exact.
    with pytest.raises(C2Error) as excinfo:
        typedb.read(make_typedb_query(fact_id=correlation_id, context=context, required_commit=commit_receipt.commit_id))
    # NCP-U03 (NCR-C2-012): PROJECTION_NOT_READY, never a downgrade -- docs/OCOR_LLD_v1.1.md:369
    assert excinfo.value.reason_code == "PROJECTION_NOT_READY"


def test_a_real_kafka_broker_restart_during_the_event_step_is_detected_and_recovers(kafka_topic):
    kafka, topic = kafka_topic
    correlation_id = str(uuid.uuid4())
    mission_id = f"urn:ocor:resource:mission-{correlation_id}"

    kafka.produce(topic, [{"aggregate_id": mission_id, "correlation_id": correlation_id, "phase": "before-restart"}])
    (before,) = kafka.consume(topic, 1)
    assert before.value["phase"] == "before-restart"

    kafka.restart_broker()

    kafka.produce(topic, [{"aggregate_id": mission_id, "correlation_id": correlation_id, "phase": "after-restart"}])
    records = kafka.consume(topic, 2)
    assert [record.value["phase"] for record in records] == ["before-restart", "after-restart"]
