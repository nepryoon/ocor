"""OCOR-DEV-0046: Implement C8 AgentRun Task Assignment Commitment
Handoff and Dissent.

Proves that agent/team state transitions (assignment, commitment,
handoff, dissent) all require a real, independently-issued capability
lease, are durably written through the sealed C3 canonical commit
path, and that none of the three negative claims can be bypassed: an
agent cannot self-grant a capability (a fabricated lease id, a
wrong-capability lease, a wrong-resource lease, and a revoked lease
are all refused identically to a real authority denial), cannot
mutate canonical state directly (the sealed AtomicOutboxStore's own
single-writer boundary refuses a write from any writer_id other than
the orchestrator itself), and cannot suppress a registered dissent
(there is no method to remove, retract or overwrite one). Pure,
in-memory, deterministic component (no external service needed, like
OCOR-DEV-0028/0030/0042/0043/0044/0045's own C1/C6/C7 slices).
"""

# OCOR-DEV-REM-0050 (NCP-U04, NCR-C3-002) realignment, case 1 of point 5 of
# NORMATIVE-CONFORMANCE-PLAN (2026-10-30). AgentRun state is operational run state of
# C8 in the PostgreSQL Run Ledger (ADD v1.3 §2.2,
# ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:276), and
# every canonical mutation is produced exclusively by C6 on the governed path; C3
# admits a command only with a valid Decision and Authority coherent with the frozen
# GatePackage (ADD v1.3 §2.5 rule 10, same file :342). The assertions on the legacy
# AtomicOutboxStore (``store.get`` of AgentRun aggregates, the store's own
# ``SingleWriterViolation``) contradict those elements and are realigned: the
# lifecycle is asserted on the real Run Ledger, and an agent's own canonical write is
# refused by the real C3 admission while the C6-signed command is admitted. The
# references to the store in the module docstring above describe the sealed task as
# it was; the backend is now the real PostgreSQL (``OCOR_LIVE_POSTGRES_DSN``).

from __future__ import annotations

import hashlib
import importlib
import inspect
import os
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ocor_runtime.c6_capabilities import CapabilityAuthority
from ocor_runtime.c8.orchestrator import AgentRunOrchestrator, Dissent, OrchestratorError

NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def dsn() -> str:
    value = os.environ.get("OCOR_LIVE_POSTGRES_DSN", "")
    if not value:
        pytest.fail("OCOR_LIVE_POSTGRES_DSN is mandatory: the C8 Run Ledger and C3 are qualified on the real PostgreSQL")
    return value


@pytest.fixture
def authority() -> CapabilityAuthority:
    return CapabilityAuthority(issuer="ocor-c8-orchestrator-authority")


@pytest.fixture
def ledger(dsn: str) -> Any:
    from ocor_runtime.c8.adapters.postgres_ledger import PostgresRunLedger

    value = PostgresRunLedger(dsn)
    value.initialize()
    # The ledger is append-only for the product (no UPDATE or DELETE); the suite starts
    # every case from an empty ledger of the disposable test database.
    import psycopg

    with psycopg.connect(dsn) as connection:
        connection.execute("TRUNCATE c8_run_ledger RESTART IDENTITY")
    return value


@pytest.fixture
def orchestrator(authority: CapabilityAuthority, ledger: Any) -> AgentRunOrchestrator:
    return AgentRunOrchestrator(authority=authority, ledger=ledger)


def grant(authority: CapabilityAuthority, *, subject: str, capability: str, resource: str, ttl: timedelta = timedelta(hours=1)):
    return authority.issue(subject=subject, capabilities=[capability], resources=[resource], issued_at=NOW, ttl=ttl)


def _kinds(ledger: Any, task_id: str) -> list[tuple[str, str]]:
    return [(entry.kind, entry.agent_id) for entry in ledger.entries(task_id)]


def test_the_full_assign_commit_dissent_lifecycle_writes_real_canonical_state(
    orchestrator: AgentRunOrchestrator, authority: CapabilityAuthority, ledger: Any
) -> None:
    # Realigned (ADD v1.3 :276): the lifecycle is durable in the C8 Run Ledger.
    assign_lease = grant(authority, subject="team-lead-1", capability="agent:assign", resource="agent-1")
    assignment = orchestrator.assign("task-1", "agent-1", capability="act:do-thing", lease=assign_lease, assigned_by="team-lead-1", at=NOW)
    assert assignment.agent_id == "agent-1"
    assert _kinds(ledger, "task-1") == [("TASK_ASSIGNED", "agent-1")]

    commit_lease = grant(authority, subject="agent-1", capability="agent:commit", resource="agent-1")
    commitment = orchestrator.commit("task-1", lease=commit_lease, at=NOW)
    assert commitment.agent_id == "agent-1"
    assert _kinds(ledger, "task-1") == [("TASK_ASSIGNED", "agent-1"), ("TASK_COMMITTED", "agent-1")]

    dissent_lease = grant(authority, subject="agent-1", capability="agent:dissent", resource="agent-1")
    dissent = orchestrator.register_dissent("task-1", "agent-1", reason="risk ceiling exceeded", lease=dissent_lease, at=NOW)
    assert dissent.reason == "risk ceiling exceeded"
    assert orchestrator.dissents == (dissent,)
    assert _kinds(ledger, "task-1") == [
        ("TASK_ASSIGNED", "agent-1"),
        ("TASK_COMMITTED", "agent-1"),
        ("DISSENT_REGISTERED", "agent-1"),
    ]
    assert ledger.entries("task-1")[-1].payload["reason"] == "risk ceiling exceeded"


def test_handoff_transfers_the_commitment_to_a_new_agent(orchestrator: AgentRunOrchestrator, authority: CapabilityAuthority) -> None:
    assign_lease = grant(authority, subject="team-lead-1", capability="agent:assign", resource="agent-1")
    orchestrator.assign("task-2", "agent-1", capability="act:do-thing", lease=assign_lease, assigned_by="team-lead-1", at=NOW)
    commit_lease = grant(authority, subject="agent-1", capability="agent:commit", resource="agent-1")
    orchestrator.commit("task-2", lease=commit_lease, at=NOW)

    handoff_lease = grant(authority, subject="agent-2", capability="agent:handoff", resource="agent-2")
    record = orchestrator.handoff("task-2", to_agent_id="agent-2", reason="agent-1 is overloaded", lease=handoff_lease, at=NOW)

    assert record.from_agent_id == "agent-1"
    assert record.to_agent_id == "agent-2"
    assert orchestrator.handoffs == (record,)
    assert orchestrator.assignment("task-2").agent_id == "agent-2"
    assert orchestrator.commitment("task-2").agent_id == "agent-2"

    # the new agent can now commit again using its own real lease
    second_commit_lease = grant(authority, subject="agent-2", capability="agent:commit", resource="agent-2")
    recommitment = orchestrator.commit("task-2", lease=second_commit_lease, at=NOW)
    assert recommitment.agent_id == "agent-2"


def test_a_handoff_without_a_reason_is_refused(orchestrator: AgentRunOrchestrator, authority: CapabilityAuthority) -> None:
    assign_lease = grant(authority, subject="team-lead-1", capability="agent:assign", resource="agent-1")
    orchestrator.assign("task-3", "agent-1", capability="act:do-thing", lease=assign_lease, assigned_by="team-lead-1", at=NOW)
    commit_lease = grant(authority, subject="agent-1", capability="agent:commit", resource="agent-1")
    orchestrator.commit("task-3", lease=commit_lease, at=NOW)

    handoff_lease = grant(authority, subject="agent-2", capability="agent:handoff", resource="agent-2")
    with pytest.raises(OrchestratorError) as excinfo:
        orchestrator.handoff("task-3", to_agent_id="agent-2", reason="", lease=handoff_lease, at=NOW)
    assert excinfo.value.reason_code == "HANDOFF_REASON_REQUIRED"


def test_committing_or_handing_off_an_unassigned_task_is_refused(orchestrator: AgentRunOrchestrator, authority: CapabilityAuthority) -> None:
    commit_lease = grant(authority, subject="agent-1", capability="agent:commit", resource="agent-1")
    with pytest.raises(OrchestratorError) as excinfo:
        orchestrator.commit("never-assigned", lease=commit_lease, at=NOW)
    assert excinfo.value.reason_code == "UNKNOWN_TASK"

    handoff_lease = grant(authority, subject="agent-2", capability="agent:handoff", resource="agent-2")
    with pytest.raises(OrchestratorError) as excinfo:
        orchestrator.handoff("never-committed", to_agent_id="agent-2", reason="x", lease=handoff_lease, at=NOW)
    assert excinfo.value.reason_code == "UNKNOWN_TASK"


# --- an agent cannot self-grant a capability ---------------------------------


def test_a_fabricated_lease_id_never_issued_by_the_authority_is_refused(orchestrator: AgentRunOrchestrator) -> None:
    with pytest.raises(OrchestratorError) as excinfo:
        orchestrator.assign("task-4", "agent-1", capability="act:do-thing", lease="agent-1-made-this-up", assigned_by="agent-1", at=NOW)
    assert excinfo.value.reason_code == "CAPABILITY_DENIED"


def test_a_lease_for_a_different_capability_is_refused(orchestrator: AgentRunOrchestrator, authority: CapabilityAuthority) -> None:
    wrong_capability_lease = grant(authority, subject="agent-1", capability="agent:invoke", resource="agent-1")
    with pytest.raises(OrchestratorError) as excinfo:
        orchestrator.register_dissent("task-5", "agent-1", reason="x", lease=wrong_capability_lease, at=NOW)
    assert excinfo.value.reason_code == "CAPABILITY_DENIED"


def test_a_lease_scoped_to_a_different_resource_is_refused(orchestrator: AgentRunOrchestrator, authority: CapabilityAuthority) -> None:
    wrong_resource_lease = grant(authority, subject="agent-1", capability="agent:dissent", resource="agent-999")
    with pytest.raises(OrchestratorError) as excinfo:
        orchestrator.register_dissent("task-6", "agent-1", reason="x", lease=wrong_resource_lease, at=NOW)
    assert excinfo.value.reason_code == "CAPABILITY_DENIED"


def test_a_revoked_lease_is_refused_even_though_it_was_valid_when_issued(orchestrator: AgentRunOrchestrator, authority: CapabilityAuthority) -> None:
    lease = grant(authority, subject="agent-1", capability="agent:dissent", resource="agent-1")
    authority.revoke(lease.lease_id, at=NOW)
    with pytest.raises(OrchestratorError) as excinfo:
        orchestrator.register_dissent("task-7", "agent-1", reason="x", lease=lease, at=NOW)
    assert excinfo.value.reason_code == "CAPABILITY_DENIED"


# --- an agent cannot mutate canonical state directly -------------------------


def test_an_agent_cannot_write_canonical_state_directly_only_the_orchestrator_can(dsn: str) -> None:
    """Real fault injection, realigned (ADD v1.3 :342): an agent that freezes and signs
    its own canonical commit with its own key is refused by the real C3 admission, with
    no mutation; the same command frozen and signed on the C6 governed path is
    admitted. C8 itself holds no canonical commit port at all (ADD v1.3 :276)."""
    from ocor_runtime.c1.signing import Ed25519SigningKey
    from ocor_runtime.c3.admission import issue_governed_command
    from ocor_runtime.c3.ports import C3Error
    from ocor_runtime.c3.service import PostgresC3Service
    from ocor_runtime.kernel.governance import InMemoryTrustedClock

    governed_path = importlib.import_module("test_ocor_dev_rem_0050")
    governed = governed_path.GovernedC3(
        release=governed_path.RELEASE,
        preconditions=(governed_path.PRECONDITION,),
        invariants=(governed_path.INVARIANT,),
    )
    service = PostgresC3Service(dsn, admission=governed.admission())
    service.initialize()
    service.reset()
    aggregate_ref = "urn:ocor:agentrun:assignment:tampered"
    path = governed_path.GovernedPath(
        governed_path.RecordStore(), governed_path.Fence(), InMemoryTrustedClock(NOW), aggregate_ref=aggregate_ref
    )
    fields = path.command("urn:sha256:" + "0" * 64).to_mapping()
    fields.pop("gate_package_digest")

    def revision() -> int:
        rows = governed_path._sql(dsn, "SELECT revision FROM c3_aggregate WHERE aggregate_ref=%s", aggregate_ref)
        return int(rows[0][0]) if rows else 0

    agent_key = Ed25519SigningKey.from_seed(hashlib.sha256(b"agent-1-own-key").digest())
    forged = issue_governed_command(
        fields,
        key=agent_key,
        keyid="urn:ocor:key:agent-1",
        sink=governed.records,
        fence=governed.fence,
        issued_at=governed.clock.now(),
        validity=timedelta(hours=1),
    )
    with pytest.raises(C3Error) as caught:
        service.commit(forged)
    assert caught.value.reason_code == "GATE_PACKAGE_MISMATCH"
    assert revision() == 0

    assert service.commit(governed.command(fields)).to_revision == 1
    assert revision() == 1
    assert set(inspect.signature(AgentRunOrchestrator).parameters) == {"authority", "ledger"}
    service.reset()


# --- dissent can never be suppressed -----------------------------------------


def test_dissent_is_append_only_and_the_class_exposes_no_removal_method(orchestrator: AgentRunOrchestrator, authority: CapabilityAuthority) -> None:
    lease_a = grant(authority, subject="agent-1", capability="agent:dissent", resource="agent-1")
    lease_b = grant(authority, subject="agent-1", capability="agent:dissent", resource="agent-1")
    first = orchestrator.register_dissent("task-8", "agent-1", reason="first objection", lease=lease_a, at=NOW)
    second = orchestrator.register_dissent("task-8", "agent-1", reason="second objection", lease=lease_b, at=NOW)

    assert orchestrator.dissents == (first, second)
    assert not any(name.startswith(("remove", "retract", "delete", "clear", "update")) for name in dir(orchestrator) if "dissent" in name.lower())


def test_a_dissent_record_itself_is_frozen_and_cannot_be_mutated() -> None:
    dissent = Dissent(task_id="task-9", agent_id="agent-1", reason="objection", registered_at=NOW)
    with pytest.raises(FrozenInstanceError):
        dissent.reason = "tampered"  # type: ignore[misc]


def test_a_dissent_without_a_reason_is_refused(orchestrator: AgentRunOrchestrator, authority: CapabilityAuthority) -> None:
    lease = grant(authority, subject="agent-1", capability="agent:dissent", resource="agent-1")
    with pytest.raises(OrchestratorError) as excinfo:
        orchestrator.register_dissent("task-10", "agent-1", reason="", lease=lease, at=NOW)
    assert excinfo.value.reason_code == "DISSENT_REASON_REQUIRED"
