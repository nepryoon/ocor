"""OCOR-DEV-0062: qualifying FGM-11 through FGM-20 campaign on the real memory stack.

Acceptance (backlog): FGM-11..20 each prove hold, deletion, dissent, promotion,
non-interference, stop, restore, quota and replay oracles.  Negative: any
resurrection, direct promotion, leakage or non-reproducible receipt fails the
campaign; a SKIPPED, UNAVAILABLE, mock-only or NOT_EXECUTED qualifying case is
not accepted.

Oracles: LLD v1.1 §7.2 (the ``FGM-11``..``FGM-20`` rows, quoted in
``CAMPAIGN``), ADD v1.3 Part II §§2.4-2.13 and the IRB acceptance text of the
requirements that ``docs/development_plan/OCOR_TRACEABILITY_PLAN.csv`` assigns
to this task for verification.  Every FGM identifier has exactly one positive
and one negative qualifying case below; each case names the specific
requirements it verifies, never the generic task requirement.

Every qualifying case runs the real G5 composition -- the OCOR-DEV-0050
admission service, the OCOR-DEV-0051/0053 store and embedding coordinators,
the OCOR-DEV-0052 retrieval service, the OCOR-DEV-0054 consolidation service,
the OCOR-DEV-0055 lifecycle coordinator and deletion saga, the OCOR-DEV-0056
restore gate, the OCOR-DEV-0057 context assembler, the OCOR-DEV-0058
promotion service and C6 consumer and the OCOR-DEV-0059 operations, backup
and restore services -- over the real, pinned backends of the G5 qualifying worlds: PostgreSQL 16 from
``OCOR_LIVE_POSTGRES_DSN`` (metadata, encrypted content, full-text index,
representation descriptors, denial and receipt audit, C3 canonical store; one
schema per world), Qdrant 1.15.1 (native and parallel vector indexes, one
namespace per world), OpenBao 2.6.2 transit (content encryption, C6 gate and
deletion-checkpoint signatures) and the OPA of the bootstrap stack (C6
promotion policy).  FGM-17 also runs the real C8 tool boundary of
OCOR-DEV-0047/REM-0027 (``ToolCallRuntime`` over the real capability
authority, emergency-stop controller, sandbox, budget and C6 outcome
reconciler); its stop controller is the kill switch memory reads its stop
epoch from, and its tools reach memory only through the lease channel.  The worlds, the 0061 campaign world and the explicit
policy/authority test ports are imported from the sealed G5/G6 modules; no
imported test function is collected again.  A missing backend fails, it
never skips.  The two structural cases at the end bind the campaign to the
normative FGM rows and to the traceability plan; they are not qualifying
store cases.

Declared limits: the timing channel of FGM-16 is observed as the backend work
(the ordered index lookups) of the policy-filtered query, which is identical
with and without unauthorized items; no wall-clock tolerance is defined by the
normative text and none is asserted.  The use of procedural memory in FGM-14
is retrieval and context assembly: no runtime component consumes memory
instruction eligibility for tool execution.  FGM-16 covers the
cross-compartment case only: membership inference through retained digests
remains an open, unassigned residual risk (PO decision
OCOR-DEV-0055-VF002-REMEDIATION, VF-004).  FGM-17 does not close, and does
not claim closed, two residual risks: the window between the last stop-epoch
check and the append, commit or delivery of the memory lifecycle, promotion
and operations services, which are not atomic with an external control plane
(OCOR-DEV-0055-VF002-REMEDIATION, VF-001); and the in-process preemption of
C8, best-effort between interpreter steps, so that a native call already
running and the ``finally`` after it are not interruptible and an effect on a
channel the platform does not govern is not contained
(REM-0027-REPAIR-2-SCOPE-AND-VF001-DISPOSITION).  What FGM-17 observes is
that every use of memory and every tool effect on the lease channel after the
stop or the revocation is refused.
"""

from __future__ import annotations

import csv
import dataclasses
import inspect
import re
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest

TASKS = Path(__file__).resolve().parents[2] / "tasks"
if str(TASKS) not in sys.path:
    sys.path.insert(0, str(TASKS))

import test_fgm_01_10 as f10  # noqa: E402
import test_ocor_dev_0051 as base  # noqa: E402
import test_ocor_dev_0052 as t52  # noqa: E402
import test_ocor_dev_0054 as t54  # noqa: E402
import test_ocor_dev_0055 as life  # noqa: E402
import test_ocor_dev_0056 as t56  # noqa: E402
import test_ocor_dev_0057 as t57  # noqa: E402
import test_ocor_dev_0058 as t58  # noqa: E402
import test_ocor_dev_0059 as ops  # noqa: E402
from ocor_runtime.c2_identity import IdentityRecord, IdentityRegistry  # noqa: E402
from ocor_runtime.c3.ports import GovernedCanonicalCommitCommand  # noqa: E402
from ocor_runtime.c4_marking import MarkingEngine, MarkingSchemeDefinition, MarkingSet  # noqa: E402
from ocor_runtime.c6.safety import EmergencyStopController, OutcomeReconciler, OutcomeStatus, SafetyError  # noqa: E402
from ocor_runtime.c6_capabilities import CapabilityAuthority, CapabilityLease  # noqa: E402
from ocor_runtime.c8.tool_runtime import ToolCallRuntime, ToolRuntimeError  # noqa: E402
from ocor_runtime.c8_agent import StrictSandbox, TokenBudget  # noqa: E402
from ocor_runtime.kernel.canonical import canonical_digest  # noqa: E402
from ocor_runtime.memory.deletion import DeletionJournalSnapshot, DeletionRecoveryError  # noqa: E402
from ocor_runtime.memory.lifecycle import JournalTombstoneStore  # noqa: E402
from ocor_runtime.memory.model import (  # noqa: E402
    AdmissionLimits,
    AdmittedMemoryVersion,
    InstructionApproval,
    MemoryAdmissionError,
    MemoryAdmissionService,
    MemoryKind,
)
from ocor_runtime.memory.lifecycle import LifecycleGuardPolicy  # noqa: E402
from ocor_runtime.memory.operations import MemoryQuotaDemand  # noqa: E402
from ocor_runtime.memory.promotion import MemoryPromotionService  # noqa: E402
from ocor_runtime.memory.retrieval import MemoryRetrievalError, RetrievalMode  # noqa: E402
from ocor_runtime.memory.stores import MemoryPartition  # noqa: E402

REPO = Path(__file__).resolve().parents[4]
LLD = REPO / "docs/OCOR_LLD_v1.1.md"
TRACE = REPO / "docs/development_plan/OCOR_TRACEABILITY_PLAN.csv"
TASK_ID = "OCOR-DEV-0062"

NOW = base.NOW
CALLER = t52.CALLER
TEXT = life.TEXT
HOLD = life.HOLD

# The FGM rows of LLD v1.1 §7.2 (scenario, oracle) and the requirements each
# case verifies.  ``test_campaign_rows_match_the_normative_lld_table`` and
# ``test_every_planned_requirement_is_bound_to_a_positive_and_negative_case``
# keep this binding mechanical.
CAMPAIGN: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "FGM-11": (
        "legal hold e rilascio",
        "deletion bloccata e prior disposition ripristinata",
        ("FR-118",),
    ),
    "FGM-12": (
        "deletion saga con failure parziale",
        "`DELETION_INCOMPLETE` fail-closed, poi completamento",
        ("FR-118",),
    ),
    "FGM-13": (
        "consolidation conflict/dissent",
        "fonti conflittuali preservate, nessun majority merge silenzioso",
        ("FR-010", "FR-174"),
    ),
    "FGM-14": (
        "procedural activation",
        "approvazione separata e policy/capability live rivalidate",
        ("FR-140", "NFR-016"),
    ),
    "FGM-15": (
        "memory→canonical promotion",
        "percorso C6/C3 completo, nessuna write diretta",
        ("FR-118", "NFR-016", "NFR-048"),
    ),
    "FGM-16": (
        "non-interference cross-compartment",
        "zero leakage content/existence/rank/count/cache/timing",
        ("FR-006", "NFR-006"),
    ),
    "FGM-17": (
        "race kill switch/revoca delega",
        "nessuna retrieval o tool influence successiva",
        ("FR-038", "FR-174", "NFR-048"),
    ),
    "FGM-18": (
        "restore dopo deletion",
        "nessuna resurrezione; tombstone riconciliato",
        ("FR-118",),
    ),
    "FGM-19": (
        "quota/retention pressure",
        "selezione deterministica; legal hold protetto",
        ("FR-118",),
    ),
    "FGM-20": (
        "context assembly",
        "replay esatto di item/version/redaction/order/truncation digest",
        ("FR-118",),
    ),
}


# --------------------------------------------------------------------------
# Campaign worlds on the shared real backends
# --------------------------------------------------------------------------


class OpenBaoHarness(base.OpenBaoHarness):
    PREFIX = "ocor-test-fgm-11-20-openbao-"


@dataclass
class Campaign(f10.Campaign):
    """The 0061 campaign worlds, plus the 0055 lifecycle options and a 0052/0058 view."""

    retrieval: Any = None
    temporary: list[tempfile.TemporaryDirectory[str]] = field(default_factory=list)

    def release(self) -> None:
        try:
            super().release()
        finally:
            try:
                if self.retrieval is not None:
                    self.retrieval.release()
            finally:
                for directory in self.temporary:
                    directory.cleanup()
                self.temporary.clear()

    def _schema(self) -> str:
        schema = f"ocor_fgm1120_{uuid.uuid4().hex[:12]}"
        self.schemas.append(schema)
        return schema

    def world(self, *, schema: str | None = None, **kwargs: Any) -> f10.FgmWorld:
        schema = schema or self._schema()
        postgres = base.PostgresStores(self.dsn, schema)
        return f10.FgmWorld(
            admission_audit=f10.denial.SchemaPostgresAudit(self.dsn, schema),
            metadata=postgres,
            content=base.PostgresContentStore(postgres),
            lexical=base.PostgresLexicalIndex(postgres),
            vector=t52.CompactQdrantVectorIndex(self.qdrant.endpoint, schema),
            cipher=base.OpenBaoTransitCipher(self.bao),
            representations=f10.t53.PostgresRepresentationStore(self.dsn, schema),
            parallel=t52.CompactQdrantVectorIndex(self.qdrant.endpoint, schema),
            **kwargs,
        )

    def tmp(self) -> Path:
        directory = tempfile.TemporaryDirectory(prefix="ocor-fgm-11-20-")
        self.temporary.append(directory)
        return Path(directory.name)

    def promotion_backends(self) -> t52.Backends:
        """The 0052 world view the sealed 0058 C6/C3 workflow runs on, over the same backends."""

        if self.retrieval is not None:
            self.retrieval.release()
        self.retrieval = t52.Backends(dsn=self.dsn, qdrant=self.qdrant, bao=self.bao)
        return self.retrieval


@pytest.fixture(scope="module")
def live_campaign() -> Iterator[Campaign]:
    dsn = __import__("os").environ.get("OCOR_LIVE_POSTGRES_DSN")
    if not dsn:
        pytest.fail("OCOR_LIVE_POSTGRES_DSN is mandatory qualifying evidence (real PostgreSQL)")
    qdrant = base.QdrantHarness.provision()
    bao: OpenBaoHarness | None = None
    state: Campaign | None = None
    try:
        bao = OpenBaoHarness.provision()
        state = Campaign(dsn=dsn, qdrant=qdrant, bao=bao)
        yield state
    finally:
        try:
            if state is not None:
                state.release()
        finally:
            try:
                if bao is not None:
                    bao.destroy()
            finally:
                qdrant.destroy()


@pytest.fixture
def campaign(live_campaign: Campaign) -> Iterator[Campaign]:
    """Per-case worlds on the shared real backends, released after the case."""

    try:
        yield live_campaign
    finally:
        live_campaign.release()


assert_backends_real = f10.assert_backends_real
raises = f10.raises
rejected = f10.rejected
hit_ids = f10.hit_ids


def lifecycle_error(action: Callable[[], object], reason: str, detail: str) -> MemoryAdmissionError:
    return life.assert_error(action, reason, detail)


def absent_everywhere(world: f10.FgmWorld, item_id: str, text: str = TEXT) -> bool:
    return all(not any(r.startswith(f"urn:ocor:memory:{item_id}:") for r in refs) for refs in world.every_mode(text).values())


# --------------------------------------------------------------------------
# FGM-11 -- legal hold and release (FR-118)
# --------------------------------------------------------------------------


def test_fgm_11_positive_a_legal_hold_blocks_every_deletion_and_release_restores_the_prior_disposition(
    campaign: Campaign,
) -> None:
    world = campaign.world()
    assert_backends_real(campaign, world)
    items = life.populate(world)
    world.admit("revoked-held", TEXT + " east")
    world.move("revoked-held", "REVOKED", reason="SOURCE_RETRACTED")
    world.holds.place()
    world.move("x", "LEGAL_HOLD", hold=HOLD, reason="LITIGATION_HOLD")
    world.move("revoked-held", "LEGAL_HOLD", hold=HOLD, reason="LITIGATION_HOLD")
    held = world.lifecycle.head("x")
    assert held is not None and held.item.legal_hold_ref == HOLD and held.item.prior_lifecycle_status is life.S.ACTIVE
    snapshot = (life.native_entries(world, items["x"]), life.content_present(world, items["x"]))
    # FR-118: legal hold blocks the deletion request, the forgetting transition and retention.
    lifecycle_error(lambda: world.delete("x"), "LEGAL_HOLD_ACTIVE", "LEGAL_HOLD_NOT_RELEASED")
    lifecycle_error(lambda: world.move("x", "DELETION_PENDING", reason="AUTHORIZED_REQUEST"), "LEGAL_HOLD_ACTIVE", "LEGAL_HOLD_NOT_RELEASED")
    world.clock.advance(life.HORIZON + timedelta(days=1))
    report = world.lifecycle.enforce_retention(binding=t52.binding(), operation_id="fgm11-retention")
    assert set(report.held) == {"urn:ocor:memory:x:v2", "urn:ocor:memory:revoked-held:v3"}
    assert not {"urn:ocor:memory:x:v2", "urn:ocor:memory:revoked-held:v3"} & set(report.processed)
    assert world.status("keep") == "DELETED"  # the same sweep forgot the unheld item
    assert (life.native_entries(world, items["x"]), life.content_present(world, items["x"])) == snapshot
    assert world.tombstones.entries("x") == () and world.tombstones.entries("revoked-held") == ()
    # Release: the registry reports the hold lifted, the item returns to its prior disposition only.
    world.holds.lift()
    released = world.move("x", "ACTIVE", reason="HOLD_RELEASED")
    assert released.lifecycle_status == "ACTIVE"
    head = world.lifecycle.head("x")
    assert head is not None and head.item.legal_hold_ref is None and head.item.prior_lifecycle_status is None
    assert head.item.content_digest == items["x"].item.content_digest
    assert "urn:ocor:memory:x:v3" in world.every_mode("north")["FULL_TEXT"]
    world.move("revoked-held", "REVOKED", reason="HOLD_RELEASED")
    assert world.status("revoked-held") == "REVOKED" and absent_everywhere(world, "revoked-held", TEXT + " east")
    # After release the ordinary deletion is no longer blocked.
    assert world.delete("revoked-held").lifecycle_status == "DELETED"


def test_fgm_11_negative_invalid_or_unreleased_holds_never_change_the_item_and_every_refusal_is_audited(
    campaign: Campaign,
) -> None:
    world = campaign.world()
    items = life.populate(world)
    before = life.ledger_snapshot(world)
    # Only an active hold of the item's tenant can be placed.
    for label, setup in (
        ("unknown", lambda: None),
        ("foreign-tenant", lambda: world.holds.place(tenant="tenant-b")),
        ("released", lambda: (world.holds.place(), world.holds.lift())),
    ):
        world.holds.holds.clear()
        setup()
        lifecycle_error(lambda: world.move("x", "LEGAL_HOLD", hold=HOLD), "POLICY_DENIED", "LEGAL_HOLD_NOT_ACTIVE")
        assert life.ledger_snapshot(world) == before and world.status("x") == "ACTIVE", label
    world.holds.holds.clear()
    world.holds.place()
    world.move("x", "LEGAL_HOLD", hold=HOLD)
    held = life.ledger_snapshot(world)
    # While held: no deletion, no leaving the hold, no other disposition, registry outage fails closed.
    lifecycle_error(lambda: world.delete("x"), "LEGAL_HOLD_ACTIVE", "LEGAL_HOLD_NOT_RELEASED")
    lifecycle_error(lambda: world.move("x", "ACTIVE"), "LEGAL_HOLD_ACTIVE", "LEGAL_HOLD_NOT_RELEASED")
    world.holds.fail = True
    lifecycle_error(lambda: world.move("x", "ACTIVE"), "CONTROL_PLANE_UNAVAILABLE", "LEGAL_HOLD_REGISTRY_UNAVAILABLE")
    lifecycle_error(lambda: world.delete("x"), "CONTROL_PLANE_UNAVAILABLE", "LEGAL_HOLD_REGISTRY_UNAVAILABLE")
    world.holds.fail = False
    world.holds.lift()
    lifecycle_error(lambda: world.move("x", "REVOKED"), "LIFECYCLE_TRANSITION_INVALID", "PRIOR_DISPOSITION_REQUIRED")
    with pytest.raises(MemoryAdmissionError):
        world.admit("x", TEXT + " north rewritten", version=3)
    assert life.ledger_snapshot(world) == held and world.status("x") == "LEGAL_HOLD"
    assert life.content_present(world, items["x"]) and world.tombstones.entries("x") == ()
    assert life.denials(world) == [("POLICY_DENIED", "LEGAL_HOLD_NOT_ACTIVE")] * 3 + [
        ("LEGAL_HOLD_ACTIVE", "LEGAL_HOLD_NOT_RELEASED")] * 2 + [
        ("CONTROL_PLANE_UNAVAILABLE", "LEGAL_HOLD_REGISTRY_UNAVAILABLE")] * 2 + [
        ("LIFECYCLE_TRANSITION_INVALID", "PRIOR_DISPOSITION_REQUIRED")]
    assert life.no_content_in(world.lc_audit.events, TEXT)


# --------------------------------------------------------------------------
# FGM-12 -- deletion saga with partial failure (FR-118)
# --------------------------------------------------------------------------


def test_fgm_12_positive_a_partial_deletion_is_incomplete_and_closed_until_a_retry_completes_it(
    campaign: Campaign,
) -> None:
    replica = life.FailingParticipant(failures=1)
    world = campaign.world(tombstones=JournalTombstoneStore(campaign.tmp() / "tombstones.jsonl"), replica=replica)
    assert_backends_real(campaign, world)
    items = life.populate(world)
    world.rebuild(items["keep"])
    replica.track(items["x"])
    first = world.delete("x", op="fgm12-1")
    assert first.lifecycle_status == "DELETION_INCOMPLETE" and first.to_mapping()["status"] == "FAILED"
    assert world.status("x") == "DELETION_INCOMPLETE"
    started = world.tombstones.entries("x")
    assert [e.phase for e in started] == ["STARTED", "INCOMPLETE"] and started[-1].residue_counts == (("replica", 1),)
    # Fail closed while incomplete: no retrieval mode, no parallel representation, no content.
    assert all(not any(r.startswith("urn:ocor:memory:x:") for r in refs) for refs in world.every_mode("north", v2=True).values())
    assert life.native_entries(world, items["x"]) == {"lexical": 0, "vector": 0}
    assert life.parallel_descriptors(world, items["x"]) == [] and not life.content_present(world, items["x"])
    # The retry completes the saga under the same deletion epoch.
    done = world.delete("x", op="fgm12-2")
    assert done.lifecycle_status == "DELETED" and done.deletion_epoch == first.deletion_epoch == 1
    assert replica.residue(life._Target(items["x"])) == ()
    entries = world.tombstones.entries("x")
    assert [e.phase for e in entries] == ["STARTED", "INCOMPLETE", "STARTED", "COMPLETED"]
    assert entries[-1].digest == done.tombstone_digest and entries[-1].residue_counts == ()
    assert JournalTombstoneStore(world.tombstones._path).entries("x") == entries  # type: ignore[attr-defined]
    assert life.no_content_in([e.to_mapping() for e in entries], TEXT, items["x"].item.content_digest)
    assert [world.ledger.get("x", v).item.lifecycle_status.value for v in range(2, 6)] == [  # type: ignore[union-attr]
        "DELETION_PENDING", "DELETION_INCOMPLETE", "DELETION_PENDING", "DELETED",
    ]
    assert world.status("keep") == "ACTIVE" and "urn:ocor:memory:keep:v1" in world.every_mode()["FULL_TEXT"]


def test_fgm_12_negative_an_incomplete_or_interrupted_deletion_never_reopens_or_serves_the_item(campaign: Campaign) -> None:
    replica = life.FailingParticipant(failures=5)
    world = campaign.world(replica=replica)
    items = life.populate(world)
    replica.track(items["x"])
    assert world.delete("x", op="fgm12n-1").lifecycle_status == "DELETION_INCOMPLETE"
    incomplete = life.ledger_snapshot(world)
    # No transition, re-admission or competing request can reopen an incomplete deletion.
    for target in ("ACTIVE", "REVOKED", "QUARANTINED"):
        with pytest.raises(MemoryAdmissionError):
            world.move("x", target)
    with pytest.raises(MemoryAdmissionError):
        world.admit("x", TEXT + " north", version=world.ledger.latest_version("x") + 1)
    assert world.delete("x", op="fgm12n-2").lifecycle_status == "DELETION_INCOMPLETE"
    assert world.status("x") == "DELETION_INCOMPLETE" and absent_everywhere(world, "x", TEXT + " north")
    assert world.tombstones.latest_epoch() == 1 and len(life.ledger_snapshot(world)) == len(incomplete) + 2
    # A saga interrupted after DELETION_PENDING is already out of every backend query.
    participant = world.lifecycle._participants[0]
    real_purge = participant.purge
    participant.purge = lambda target: (_ for _ in ()).throw(KeyboardInterrupt())  # type: ignore[method-assign]
    try:
        with pytest.raises(KeyboardInterrupt):
            world.delete("y", op="fgm12n-y")
    finally:
        participant.purge = real_purge  # type: ignore[method-assign]
    assert world.status("y") == "DELETION_PENDING" and life.native_entries(world, items["y"]) == {"lexical": 1, "vector": 1}
    assert absent_everywhere(world, "y", TEXT + " south")
    lifecycle_error(lambda: world.delete("y", op="fgm12n-other"), "LIFECYCLE_TRANSITION_INVALID", "DELETION_IN_PROGRESS")
    assert world.lifecycle.metrics[("requestMemoryDeletion", "INCOMPLETE", "NONE")] == 2


# --------------------------------------------------------------------------
# FGM-13 -- consolidation conflict/dissent (FR-010, FR-174)
# --------------------------------------------------------------------------


def test_fgm_13_positive_conflicting_sources_keep_every_alternative_and_a_dissent_without_majority_merge(
    campaign: Campaign,
) -> None:
    world = campaign.consolidation_world()
    assert_backends_real(campaign, world)
    records = t54.convoy_sources(world)  # five 'open' against one 'closed', unanimous sector
    refs = t54.refs_of(records)
    before = world.snapshot(refs)
    outcome = world.consolidator().consolidate(t54.consolidation_request(refs, kind="SEMANTIC"), binding=t52.binding(t54.CTX))
    payload = world.payload(outcome.derived_ref)
    # FR-174: the minority is never voted away; FR-010: the dissenting hypothesis is kept verifiable.
    assert {(s["subject"], s["attribute"]) for s in payload["statements"]} == {("bridge-7", "sector")}
    (conflict,) = payload["conflicts"]
    assert conflict["resolution"] == "UNRESOLVED"
    assert [(a["value"], a["support_count"]) for a in conflict["alternatives"]] == [("closed", 1), ("open", 5)]
    assert conflict["alternatives"][0]["support_refs"] == [records[5].item.version_ref]
    (dissent_ref,) = outcome.dissent_refs
    dissent = world.item(dissent_ref).item
    assert dissent.memory_kind.value == "DISSENT" and dissent.instruction_eligible is False
    assert list(dissent.consolidates_refs) == sorted(refs) and dissent_ref in world.item(outcome.derived_ref).item.derived_from_refs
    assert world.payload(dissent_ref)["conflict"] == {k: v for k, v in conflict.items() if k != "dissent_ref"}
    assert world.snapshot(refs) == before  # conflicting sources preserved byte for byte
    # A tied and a three-way disagreement keep every alternative too.
    a = world.source("t-a", ("depot", "fuel", "low"), ("gate", "state", "open"))
    b = world.source("t-b", ("depot", "fuel", "medium"), ("gate", "state", "shut"))
    c = world.source("t-c", ("depot", "fuel", "high"))
    tied = world.consolidator().consolidate(t54.consolidation_request(t54.refs_of([a, b, c]), op="fgm13-tied"), binding=t52.binding(t54.CTX))
    by_attr = {conf["attribute"]: conf for conf in world.payload(tied.derived_ref)["conflicts"]}
    assert world.payload(tied.derived_ref)["statements"] == []
    assert [alt["value"] for alt in by_attr["fuel"]["alternatives"]] == ["high", "low", "medium"]
    assert [alt["support_count"] for alt in by_attr["state"]["alternatives"]] == [1, 1]
    assert len(tied.dissent_refs) == 2 and world.item(tied.derived_ref).item.confidence == 0.0
    completed = [e for e in world.consolidation_audit.events if e["outcome"] == "COMPLETED"]
    assert completed[0]["dissent_refs"] == [dissent_ref] and canonical_digest(dict(completed[0])) == outcome.receipt["audit_ref"]


def test_fgm_13_negative_dissent_cannot_be_erased_rewritten_or_merged_around_the_service(campaign: Campaign) -> None:
    world = campaign.consolidation_world()
    records = t54.convoy_sources(world)
    refs = t54.refs_of(records)
    outcome = world.consolidator().consolidate(t54.consolidation_request(refs, kind="SEMANTIC"), binding=t52.binding(t54.CTX))
    service = world.consolidator()
    watched = [*refs, outcome.derived_ref, *outcome.dissent_refs]
    before, count = world.snapshot(watched), len(world.ledger.records())
    cases = [
        (outcome.derived_ref, {"subject": "bridge-7", "attribute": "status", "value": "open", "support_refs": refs[:5]}, "DISSENT_ERASURE"),
        (outcome.derived_ref, {"subject": "bridge-7", "attribute": "status", "value": "closed", "support_refs": refs[5:]}, "DISSENT_ERASURE"),
        (outcome.dissent_refs[0], {"subject": "bridge-7", "attribute": "status", "value": "open", "support_refs": refs[:1]}, "DISSENT_IMMUTABLE"),
        (outcome.derived_ref, {"subject": "bridge-7", "attribute": "sector", "value": "south", "support_refs": [refs[0], "urn:ocor:memory:invented:v1"]}, "CORRECTION_SOURCE_REWRITE"),
    ]
    for n, (target, statement, detail) in enumerate(cases):
        t54.refused(
            lambda target=target, statement=statement, n=n: service.correct(
                t54.correction_request(target, [statement], op=f"fgm13-bad-{n}"), binding=t52.binding(t54.CTX)
            ),
            "POLICY_DENIED",
            detail,
        )
    # FR-174: no majority merge or dissent rewrite through plain admission either.
    summary, dissent = world.item(outcome.derived_ref).item, world.item(outcome.dissent_refs[0]).item
    forged = b'{"statements": "status open, no conflict"}'
    for n, item in enumerate((summary, dissent)):
        mapping = item.to_mapping()
        mapping.update(
            memory_version=2, supersedes_ref=item.version_ref, correction_of_ref=item.version_ref,
            content_digest=base.d(forged), created_at=f10.format_utc_timestamp(world.clock.now()),
            governed_context_digest=t54.CTX.digest(),
        )
        t54.refused(lambda mapping=mapping, n=n: t54._direct(world, mapping, forged, f"fgm13-direct-{n}"), "POLICY_DENIED", "ADMISSION_DENIED")
    assert len(world.ledger.records()) == count and world.snapshot(watched) == before
    assert [e["detail_code"] for e in t54.denials(world)] == [c[2] for c in cases]


# --------------------------------------------------------------------------
# FGM-14 -- procedural activation (FR-140, NFR-016)
# --------------------------------------------------------------------------

PROCEDURE = TEXT + " procedure: verify the lane manifest before release"
APPROVAL = "urn:ocor:instruction-approval:proc-1"


@dataclass
class ApprovalResolver(t52.Resolver):
    """The 0052 resolver plus the separate instruction-approval records (test port)."""

    approvals: dict[str, InstructionApproval] = field(default_factory=dict)

    def instruction_approval(self, approval_ref: str, ctx: Any) -> InstructionApproval | None:
        return self.approvals.get(approval_ref)


def procedural_world(campaign: Campaign) -> tuple[f10.FgmWorld, ApprovalResolver]:
    """A campaign world whose real admission resolves separate instruction approvals."""

    world = campaign.world()
    resolver = ApprovalResolver()
    world.admission = MemoryAdmissionService(
        ledger=world.ledger,
        resolver=resolver,
        audit=world.admission_audit,
        policy=LifecycleGuardPolicy(base.Policy(), ledger=world.ledger),
        markings=world.markings,
        clock=world.clock,
        limits=AdmissionLimits(retention_horizons={"retention:standard": life.HORIZON, "retention:short": timedelta(days=30)}),
    )
    return world, resolver


def approval(**changes: Any) -> InstructionApproval:
    values: dict[str, Any] = {
        "approval_ref": APPROVAL,
        "memory_item_id": "proc-1",
        "approved_content_digest": base.d(PROCEDURE.encode()),
        "approver_principal_id": "human-approver-1",
        "tenant_id": "tenant-a",
        "valid_until": NOW + timedelta(days=1),
    }
    values.update(changes)
    return InstructionApproval(**values)


def admit_procedure(world: f10.FgmWorld, item_id: str = "proc-1", text: str = PROCEDURE, **kwargs: Any) -> AdmittedMemoryVersion:
    return world.admit_with(
        item_id, text, {"instruction_eligible": True, "instruction_approval_ref": APPROVAL},
        kind="PROCEDURAL", source_kind="PROCEDURE", content_schema="urn:ocor:memory-content:procedure:1.0", **kwargs,
    )


def procedural_assembly(world: f10.FgmWorld, operation: str) -> dict[str, Any]:
    body = t57.assembly_request(world, text=TEXT + " procedure", operation=operation)
    body["search_request"]["memory_kinds"] = ["EPISODIC", "PROCEDURAL"]
    return body


def test_fgm_14_positive_a_separately_approved_procedure_is_eligible_and_every_use_revalidates_live_controls(
    campaign: Campaign,
) -> None:
    world, resolver = procedural_world(campaign)
    assert_backends_real(campaign, world)
    resolver.approvals[APPROVAL] = approval()
    record = admit_procedure(world)
    item = record.item
    # FR-140: eligibility is bound to a separate approval of this exact content by another principal.
    assert item.instruction_eligible is True and item.instruction_approval_ref == APPROVAL
    assert item.memory_kind is MemoryKind.PROCEDURAL and resolver.approvals[APPROVAL].approver_principal_id != item.owner_principal_id
    assert world.metadata.head("proc-1") == 1 and record.audit_event["action"] == "admitMemory"
    world.admit("note", TEXT + " procedure note")
    audit, policy = campaign.receipts(world), t57.ContextPolicy()
    world.policy.calls.clear()
    stop_reads = world.stop.reads
    assembly = t57.assembler(world, audit, policy).assemble(procedural_assembly(world, "fgm14-a1"), binding=t52.binding())
    assert item.version_ref in assembly.selected_item_version_refs
    # Every use re-evaluates the live retrieval capability, materialisation and context policy and the stop epoch.
    assert world.policy.calls[0] == "retrieval" and f"materialize:{item.version_ref}" in world.policy.calls
    assert item.version_ref in policy.calls and world.stop.reads > stop_reads
    block = next(b for b in t57.blocks(assembly) if b["memory_version_ref"] == item.version_ref)
    # NFR-016: even eligible memory is rendered as data under the data role; it grants no Authority.
    assert block["role"] == f10.CONTEXT_ROLE and block["instruction_eligible"] is True and block["data"] == PROCEDURE
    assert CALLER.digest() == t52.CALLER.digest()
    stored = audit.receipt(assembly.audit_ref)
    assert stored is not None and stored["action"] == "assembleMemoryContext"
    # The next use sees the live controls again: a second assembly calls them again.
    calls = len(policy.calls)
    t57.assembler(world, audit, policy).assemble(procedural_assembly(world, "fgm14-a2"), binding=t52.binding())
    assert policy.calls[calls:].count(item.version_ref) == 1


def test_fgm_14_negative_without_a_separate_exact_current_approval_or_live_policy_a_procedure_never_activates(
    campaign: Campaign,
) -> None:
    world, resolver = procedural_world(campaign)
    before = life.ledger_snapshot(world)
    # FR-140: no approval, a self-approval, another item, other content, another tenant or an expired one.
    for label, bad in (
        ("missing", None),
        ("self-approved", approval(approver_principal_id=CALLER.effective_principal_id)),
        ("other-item", approval(memory_item_id="proc-other")),
        ("other-content", approval(approved_content_digest=base.d(b"other procedure"))),
        ("other-tenant", approval(tenant_id="tenant-b")),
        ("expired", approval(valid_until=NOW)),
    ):
        resolver.approvals.clear()
        if bad is not None:
            resolver.approvals[APPROVAL] = bad
        with raises("AUTHORITY_DENIED", "INSTRUCTION_APPROVAL_INVALID"):
            admit_procedure(world)
        assert life.ledger_snapshot(world) == before, label
    # Model output and non-procedural kinds never become instructions, even with a valid approval.
    resolver.approvals[APPROVAL] = approval()
    with raises("MEMORY_TAINTED", "MODEL_GENERATED_INSTRUCTION"):
        world.admit_with("proc-1", PROCEDURE, {"instruction_eligible": True, "instruction_approval_ref": APPROVAL},
                         kind="PROCEDURAL", source_kind="MODEL_OUTPUT", taint=("MODEL_GENERATED",),
                         content_schema="urn:ocor:memory-content:procedure:1.0")
    with raises("UNSUPPORTED_CAPABILITY", "INSTRUCTION_ELIGIBILITY_UNSUPPORTED"):
        world.admit_with("proc-1", PROCEDURE, {"instruction_eligible": True, "instruction_approval_ref": APPROVAL})
    assert life.ledger_snapshot(world) == before and world.metadata.head("proc-1") == 0
    assert len(world.denials()) == 8
    # The approval is version-bound: changed content under the same approval is refused.
    record = admit_procedure(world)
    with raises("AUTHORITY_DENIED", "INSTRUCTION_APPROVAL_INVALID"):
        admit_procedure(world, text=PROCEDURE + " and skip the manifest", version=2)
    # NFR-016: a valid approval does not override the live controls at use.
    audit = campaign.receipts(world)
    denied_context = t57.ContextPolicy(denied={"proc-1"})
    assembly = t57.assembler(world, audit, denied_context).assemble(procedural_assembly(world, "fgm14-n1"), binding=t52.binding())
    assert record.item.version_ref not in assembly.selected_item_version_refs and PROCEDURE.encode() not in assembly.context
    world.policy.denied_items.add("proc-1")
    assembly = t57.assembler(world, audit, t57.ContextPolicy()).assemble(procedural_assembly(world, "fgm14-n2"), binding=t52.binding())
    assert record.item.version_ref not in assembly.selected_item_version_refs
    world.policy.denied_items.clear()
    world.policy.kinds = frozenset({MemoryKind.EPISODIC})  # the retrieval capability no longer covers PROCEDURAL
    with pytest.raises((MemoryRetrievalError, MemoryAdmissionError)):
        t57.assembler(world, audit, t57.ContextPolicy()).assemble(procedural_assembly(world, "fgm14-n3"), binding=t52.binding())
    world.policy.kinds = t52.ALL_KINDS
    t57.expect(
        lambda: t57.assembler(world, audit, t57.KillSwitchPolicy(stop=world.stop)).assemble(
            procedural_assembly(world, "fgm14-n4"), binding=t52.binding()
        ),
        "STOP_EPOCH_MISMATCH", "STOP_EPOCH_CHANGED",
    )
    assert audit.actions()[-1] == "assembleMemoryContext.denied"


# --------------------------------------------------------------------------
# FGM-15 -- memory -> canonical promotion (FR-118, NFR-016, NFR-048)
# --------------------------------------------------------------------------


def test_fgm_15_positive_promotion_commits_only_through_the_complete_c6_c3_path(campaign: Campaign) -> None:
    backends = campaign.promotion_backends()
    with t58.workflow(backends) as x:
        assert_backends_real(campaign, x.w)
        # FR-118: the proposal binds the exact source version and changes no memory.
        assert x.result.proposal.source_version_ref == "urn:ocor:memory:c6-source:v1"
        assert x.result.to_mapping()["status"] == "ACCEPTED"
        x.controls.put(x.result.audit_ref, x.body)
        before = x.w.ledger.records()
        assert x.c3.read(x.ctx.tenant_id, "Situation", x.req["target_aggregate_ref"]) is None
        receipt = x.consumer.commit(x.result.audit_ref, binding=t52.binding(x.ctx))
        command = GovernedCanonicalCommitCommand.from_mapping(x.body["command"])
        assert receipt.verify(command) == receipt
        state = x.c3.read(x.ctx.tenant_id, "Situation", x.req["target_aggregate_ref"])
        assert state is not None and state.revision == 1 and dict(state.state) == command.canonical_delta
        # NFR-016: Authority, Approval and Decision come from C6, never from memory; memory is unchanged.
        assert command.authority_ref == x.body["authority"]["authority_id"] and command.decision_ref == x.body["decision"]["decision_ref"]
        assert x.w.ledger.records() == before
        assert x.audit.actions() == ["proposeMemoryPromotion.recorded", "commitMemoryPromotion.intent", "commitMemoryPromotion.completed"]
        again = x.consumer.commit(x.result.audit_ref, binding=t52.binding(x.ctx))
        assert again.replayed is True and again.commit_id == receipt.commit_id
        assert x.c3.current_revision(x.ctx.tenant_id, "Situation", x.req["target_aggregate_ref"]) == 1


def test_fgm_15_negative_no_direct_write_smuggled_authority_or_missing_c6_control_reaches_canonical_state(
    campaign: Campaign,
) -> None:
    backends = campaign.promotion_backends()
    with t58.workflow(backends) as x:
        before = x.w.ledger.records()
        target = x.req["target_aggregate_ref"]
        # FR-118/NFR-016: the memory port has no commit, grant or admission capability at all.
        fields = set(inspect.signature(MemoryPromotionService).parameters)
        assert not fields & {"c3", "commit", "authority", "capabilities", "ledger", "admission", "c6"}
        assert not {"commit", "grant", "execute", "issue", "admit", "transition"} & set(dir(MemoryPromotionService))
        # NFR-048: smuggled effects and non-proposal targets are refused and audited.
        for n, member in enumerate(("canonical_delta", "authority_ref", "approval", "decision", "capability", "action_command")):
            t58.refused(lambda member=member, n=n: x.s.propose(
                "c6-source", {**x.req, member: "attempt", "operation_id": f"fgm15-smuggle-{n}"}, binding=t52.binding(x.ctx)
            ), "REQUEST_INVALID")
        for n, aggregate in enumerate(("Authority", "Policy", "CapabilityLease")):
            t58.refused(lambda aggregate=aggregate, n=n: x.s.propose(
                "c6-source", {**x.req, "target_aggregate_type": aggregate, "operation_id": f"fgm15-target-{n}"},
                binding=t52.binding(x.ctx),
            ), "PROFILE_NOT_REGISTERED")
        # Without a signed C6 gate, or without the human approval in it, C3 is never reached.
        t58.refused(lambda: x.consumer.commit(x.result.audit_ref, binding=t52.binding(x.ctx)), "C6_GATE_MISSING")
        unapproved = {**x.body, "signatures": []}
        x.controls.put(x.result.audit_ref, unapproved)
        t58.refused(lambda: x.consumer.commit(x.result.audit_ref, binding=t52.binding(x.ctx)), "C6_APPROVAL_INVALID")
        x.controls.put(x.result.audit_ref, x.body, broken_signature=True)
        t58.refused(lambda: x.consumer.commit(x.result.audit_ref, binding=t52.binding(x.ctx)), "C6_GATE_UNSIGNED")
        # The real OPA of the C6 commit: a denial or another policy bundle never reaches C3.
        x.controls.put(x.result.audit_ref, x.body)
        x.policy.permitted = False
        t58.refused(lambda: x.consumer.commit(x.result.audit_ref, binding=t52.binding(x.ctx)), "C6_POLICY_DENIED")
        x.policy.permitted, x.policy.stale = True, True
        t58.refused(lambda: x.consumer.commit(x.result.audit_ref, binding=t52.binding(x.ctx)), "POLICY_BUNDLE_MISMATCH")
        x.policy.stale = False
        assert x.c3.read(x.ctx.tenant_id, "Situation", target) is None
        with psycopg.connect(campaign.dsn) as conn:
            assert conn.execute("SELECT count(*) FROM c3_outbox WHERE aggregate_ref=%s", (target,)).fetchone() == (0,)
        assert x.w.ledger.records() == before
        actions = x.audit.actions()
        assert actions.count("proposeMemoryPromotion.denied") == 9 and actions.count("commitMemoryPromotion.denied") == 5
        # The intent is audited before the live C6 revalidation, so only the two OPA refusals carry one.
        assert "commitMemoryPromotion.completed" not in actions and actions.count("commitMemoryPromotion.intent") == 2


# --------------------------------------------------------------------------
# FGM-16 -- cross-compartment non-interference (FR-006, NFR-006)
# --------------------------------------------------------------------------


def _populate_unauthorized(world: f10.FgmWorld) -> None:
    """The 0052 unauthorized classes; the revocation runs through the real lifecycle coordinator."""

    text = "harbour patrol schedule secret leak"
    ctx = t52.context
    world.admit("x-compartment", text, ctx=ctx(compartments=("charlie",)))
    world.admit("x-compartment-mixed", text, ctx=ctx(compartments=("alpha", "charlie")))
    world.admit("x-tenant", text, ctx=ctx(tenant="tenant-b"))
    world.admit("x-organization", text, ctx=ctx(organization="org-b"))
    world.admit("x-marking", text, ctx=ctx(marking=t52.M_SECRET))
    world.admit("x-purpose", text, ctx=ctx(purpose="training"))
    world.admit("x-domain", text, ctx=ctx(domain="domain-intel"))
    world.admit("x-project", text, bindings={"project_id": "project-2"})
    world.admit("x-run", text, scope="RUN", bindings={"agent_run_id": "run-2"})
    world.admit("x-agent", text, scope="AGENT", bindings={"agent_id": "agent-2"})
    world.admit("x-federated", text, scope="FEDERATED", bindings={"federation_policy_ref": "federation:fed-1"})
    world.admit("x-quarantined", text, lifecycle="QUARANTINED")
    world.admit("x-proposed", text, lifecycle="PROPOSED")
    world.admit("x-expired", text, expires_at=NOW + timedelta(minutes=1))
    world.admit("x-not-yet-valid", text, valid_from=NOW + timedelta(minutes=5))
    world.admit("x-validity-elapsed", text, valid_from=NOW - timedelta(days=2), valid_until=NOW + timedelta(seconds=30))
    world.admit("x-pending", text, commit=False)
    world.admit("x-revoked", text)
    world.move("x-revoked", "REVOKED", reason="SOURCE_RETRACTED")
    world.admit("x-denied", text)
    world.admit("x-other-kind", text, kind="PREFERENCE", source_kind="PREFERENCE", taint=("HUMAN_SUPPLIED",))
    world.admit("x-reclassified", text)
    world.admit("x-reclassified", text, version=2, ctx=ctx(marking=t52.M_SECRET))


CROSS_COMPARTMENT = (
    t52.context(compartments=("charlie",)),
    t52.context(compartments=("alpha", "charlie")),
    t52.context(tenant="tenant-b"),
    t52.context(organization="org-b"),
    t52.context(marking=t52.M_SECRET),
    t52.context(purpose="training"),
    t52.context(domain="domain-intel"),
)
OUTSIDER = t52.context(compartments=("delta",))


def _non_interference_worlds(campaign: Campaign) -> tuple[f10.FgmWorld, f10.FgmWorld]:
    clean, noisy = campaign.world(), campaign.world()
    for world in (clean, noisy):
        t52._populate_authorized(world)
    _populate_unauthorized(noisy)
    for world in (clean, noisy):
        t52._searchable_now(world)
    return clean, noisy


def _lookups(world: f10.FgmWorld, since: tuple[int, int]) -> list[tuple[str, str, str]]:
    calls = world.lexical.calls[since[0]:] + world.vector.calls[since[1]:]
    return [call for call in calls if call[0] in t52.INDEX_LOOKUPS]


def test_fgm_16_positive_unauthorized_compartments_change_no_content_existence_rank_count_cache_or_work(
    campaign: Campaign,
) -> None:
    clean, noisy = _non_interference_worlds(campaign)
    assert_backends_real(campaign, noisy)
    observed: dict[str, Any] = {}
    for name, world in (("clean", clean), ("noisy", noisy)):
        since = (len(world.lexical.calls), len(world.vector.calls))
        responses = t52._responses(world)
        observed[name] = (responses, _lookups(world, since))
    for mode in RetrievalMode:
        # Result, rank, score factors, count, explanation and receipt are identical.
        assert observed["noisy"][0][mode.value] == observed["clean"][0][mode.value], mode
        ids = {hit["memory_item_id"] for hit in observed["noisy"][0][mode.value]["response"]["hits"]}
        assert not any(i.startswith("x-") for i in ids), (mode, ids)
    # Work: the same ordered index lookups, only inside authorized partitions.
    assert observed["noisy"][1] == observed["clean"][1] and observed["noisy"][1]
    unauthorized = {
        MemoryPartition.for_item(r.item).digest for r in noisy.ledger.records() if r.item.memory_item_id.startswith("x-")
    } - {MemoryPartition.for_item(r.item).digest for r in noisy.ledger.records() if r.item.memory_item_id.startswith("auth-")}
    assert unauthorized and not {partition for _, partition, _ in observed["noisy"][1]} & unauthorized
    # Agent context and the operations count of the caller's partition are identical too.
    contexts = {}
    for name, world in (("clean", clean), ("noisy", noisy)):
        audit = campaign.receipts(world)
        contexts[name] = [
            t57.assembler(world, audit, t57.ContextPolicy()).assemble(
                t57.assembly_request(world, mode=mode, text="harbour patrol schedule secret leak", operation=f"fgm16-{mode.value}"),
                binding=t52.binding(),
            )
            for mode in RetrievalMode
        ]
    for want, got in zip(contexts["clean"], contexts["noisy"], strict=True):
        assert (got.context, got.selected_item_version_refs, got.truncation_record) == (
            want.context, want.selected_item_version_refs, want.truncation_record,
        )
        assert b"secret leak" not in got.context
    # The operations count of the caller's partition ignores items of every other compartment.
    partition = MemoryPartition.for_item(clean.ledger.get("auth-1", 1).item)  # type: ignore[union-attr]
    service, _, _ = ops.setup(clean, audit=campaign.receipts(clean))
    counts = [ops.invoke(service, clean, partition).to_mapping()]
    for n, foreign in enumerate(CROSS_COMPARTMENT):
        clean.admit(f"x-foreign-{n}", "harbour patrol schedule secret leak", ctx=foreign)
    counts.append(ops.invoke(service, clean, partition).to_mapping())
    assert {k: v for k, v in counts[0].items() if k != "audit_ref"} == {k: v for k, v in counts[1].items() if k != "audit_ref"}
    # No cache: a later run over the same noisy stores recomputes the same clean answer.
    later = campaign.fresh(noisy)
    later.policy.denied_items.add("x-denied")
    assert t52._responses(later) == observed["clean"][0]


def test_fgm_16_negative_probes_of_unauthorized_memory_are_indistinguishable_from_absence(campaign: Campaign) -> None:
    clean, noisy = _non_interference_worlds(campaign)

    def shape(world: f10.FgmWorld, text: str) -> dict[str, Any]:
        body = t52.request(RetrievalMode.FULL_TEXT, text=text, deadline=world.deadline())
        mapping = world.service().search(body, binding=t52.binding()).to_mapping()
        return {k: v for k, v in mapping.items() if k not in {"query_digest", "audit_ref"}}

    # A query matching only unauthorized items answers exactly like a query matching nothing.
    assert shape(noisy, "leak") == shape(noisy, "nonexistentterm") == shape(clean, "leak")
    assert shape(noisy, "leak")["hits"] == []
    # A caller outside every compartment of the items learns nothing in any mode.
    for mode in RetrievalMode:
        assert noisy.search(mode, "harbour patrol schedule secret leak", ctx=OUTSIDER).hits == (), mode
    # A foreign binding is refused before any index lookup.
    since = (len(noisy.lexical.calls), len(noisy.vector.calls))
    body = t52.request(RetrievalMode.HYBRID, text="harbour patrol schedule secret leak", deadline=noisy.deadline())
    with raises("GOVERNED_CONTEXT_MISMATCH", "GOVERNED_CONTEXT_MISMATCH"):
        noisy.service().search(body, binding=t52.binding(t52.context(compartments=("charlie",))))
    assert _lookups(noisy, since) == []
    # Operations on a partition outside the verified context: same refusal whether it holds items or not.
    audit = campaign.receipts(noisy)  # ``ops.setup`` returns its own default audit, not this one
    service, _, _ = ops.setup(noisy, audit=audit)
    hidden = MemoryPartition.for_item(noisy.ledger.get("x-tenant", 1).item)  # type: ignore[union-attr]
    empty = dataclasses.replace(hidden, tenant_id="tenant-z")
    refusals = [ops.refused(lambda p=p: ops.invoke(service, noisy, p), "PARTITION_DENIED") for p in (hidden, empty)]
    assert (refusals[0].reason_code, refusals[0].detail_code) == (refusals[1].reason_code, refusals[1].detail_code)
    assert audit.actions()[-2:] == ["memoryMonitor.denied", "memoryMonitor.denied"]


# --------------------------------------------------------------------------
# FGM-17 -- kill switch / delegation revocation race (FR-038, FR-174, NFR-048)
# --------------------------------------------------------------------------


# The FGM-17 tool path: the real OCOR-DEV-0047/REM-0027 C8 tool boundary.  Its
# ``EmergencyStopController`` is the kill switch memory reads its stop epoch
# from, so one accepted stop fences both memory use and tool dispatch; the
# registered tools reach the world's real memory only through the lease channel
# (``ToolCallRuntime.authorize_effect``).
TOOL_MARKING = MarkingSet({"classification": "SECRET"})
TOOL_CLEARANCE = MarkingSet({"classification": "TOP_SECRET"})
RESET_APPROVERS = ("urn:ocor:human:fgm17-a", "urn:ocor:human:fgm17-b")
RESET_REQUESTER = "urn:ocor:human:fgm17-c"
RECALL = "harbour patrol schedule"
STOP_AFTER_SECONDS = 0.3
NATIVE_WAIT_SECONDS = 1.5
CONTAINMENT_TARGET_SECONDS = 10.0


class ControllerStop:
    """Memory's stop-epoch port, read from the C6 controller of the tool boundary.

    ``stop_at_read`` makes the external control plane accept the stop at that
    read of the epoch: the race between the kill switch and a use in flight."""

    def __init__(self, boundary: ToolBoundary) -> None:
        self.boundary = boundary
        self.reads = 0
        self.stop_at_read: int | None = None

    def current_epoch(self, ctx: Any) -> int:
        self.reads += 1
        if self.stop_at_read == self.reads:
            self.boundary.accept_stop()
        return self.boundary.stop.epoch


class ToolBoundary:
    """``ToolCallRuntime`` over the real ``CapabilityAuthority``, ``MarkingEngine``,
    ``EmergencyStopController``, ``StrictSandbox``, ``TokenBudget`` and C6
    ``OutcomeReconciler``, with tools that use the world's real memory."""

    def __init__(self, world: f10.FgmWorld) -> None:
        self.world = world
        self.effects: list[tuple[str, tuple[str, ...]]] = []
        self.late: list[str] = []
        self.settled = threading.Event()
        self.stop_accepted_at: float | None = None
        self.sandbox = StrictSandbox()
        self.authority = CapabilityAuthority(issuer="fgm-17-authority")
        self.stop = EmergencyStopController()
        self.identities = IdentityRegistry(
            IdentityRecord(canonical_id=human, attributes={"principal_kind": "HUMAN", "status": "ACTIVE", "roles": ""})
            for human in (*RESET_APPROVERS, RESET_REQUESTER)
        )
        self.runtime = ToolCallRuntime(
            sandbox=self.sandbox,
            authority=self.authority,
            marking_engine=MarkingEngine([MarkingSchemeDefinition("classification", levels=("UNCLASSIFIED", "SECRET", "TOP_SECRET"))]),
            stop=self.stop,
            reconciler=OutcomeReconciler(),
        )
        self.memory_stop = ControllerStop(self)
        world.stop = self.memory_stop
        self.lease = self.issue()
        self.after_recall: Callable[[], None] | None = None
        self.sandbox.register_tool("recall_memory", self._recall)
        self.sandbox.register_tool("act_on", self._act)
        self.sandbox.register_tool("slow_recall", self._slow_recall)

    def issue(self) -> CapabilityLease:
        return self.authority.issue(
            subject=CALLER.effective_principal_id,
            capabilities=[f"tool:{tool}" for tool in ("recall_memory", "act_on", "slow_recall")],
            resources=["recall_memory", "act_on", "slow_recall"],
            issued_at=datetime.now(UTC) - timedelta(minutes=1),
            ttl=timedelta(hours=1),
        )

    def _authorize(self, tool: str) -> None:
        self.runtime.authorize_effect(self.lease, tool, subject=CALLER.effective_principal_id, at=datetime.now(UTC))

    def recall(self) -> tuple[str, ...]:
        """One use of memory by a tool: lease channel, then the real governed search."""
        self._authorize("recall_memory")
        body = t52.request(RetrievalMode.HYBRID, text=RECALL, deadline=self.world.deadline())
        found = tuple(sorted({hit.memory_item_id for hit in self.world.service().search(body, binding=t52.binding()).hits}))
        self.effects.append(("recall_memory", found))
        return found

    def _recall(self, _: str) -> tuple[str, ...]:
        found = self.recall()
        if self.after_recall is not None:
            self.after_recall()
        return found

    def _act(self, found: tuple[str, ...]) -> int:
        self._authorize("act_on")
        self.effects.append(("act_on", tuple(found)))
        return len(found)

    def _slow_recall(self, _: str) -> int:
        """A tool that does not cooperate: a native wait, then a late use of memory from its ``finally``."""
        try:
            time.sleep(NATIVE_WAIT_SECONDS)
        finally:
            try:
                self.recall()
                self.late.append("RECALLED")
            except ToolRuntimeError as error:
                self.late.append(error.reason_code)
            except BaseException as error:  # noqa: BLE001 - every late outcome is recorded
                self.late.append(type(error).__name__)
            finally:
                self.settled.set()
        return 0

    def accept_stop(self) -> None:
        """The external control plane accepts the stop on its own thread."""

        def run() -> None:
            self.stop.activate(reason="FGM-17 kill switch", at=datetime.now(UTC))
            self.stop_accepted_at = time.monotonic()

        worker = threading.Thread(target=run)
        worker.start()
        worker.join()

    def accept_stop_later(self, delay: float) -> None:
        def run() -> None:
            time.sleep(delay)
            self.accept_stop()

        threading.Thread(target=run, daemon=True).start()

    def reset(self) -> None:
        now = datetime.now(UTC)
        self.stop.finish_draining(at=now)
        self.stop.request_reset(approvers=RESET_APPROVERS, identities=self.identities, requester=RESET_REQUESTER, at=now)
        self.stop.confirm_reset(at=now)

    def invoke(self, expression: str, *, tool_name: str = "recall_memory", lease: CapabilityLease | None = None,
               stop_epoch: int | None = None) -> Any:
        return self.runtime.invoke(
            tool_name,
            expression,
            bindings={"text": RECALL},
            lease=lease or self.lease,
            context=CALLER,
            content_marking=TOOL_MARKING,
            clearance=TOOL_CLEARANCE,
            budget=TokenBudget(1000),
            estimated_tokens=10,
            stop_epoch=self.stop.epoch if stop_epoch is None else stop_epoch,
            at=datetime.now(UTC),
        )

    def refused(self, expression: str, reason: str, **kwargs: Any) -> ToolRuntimeError:
        with pytest.raises(ToolRuntimeError) as refused:
            self.invoke(expression, **kwargs)
        assert refused.value.reason_code == reason, str(refused.value)
        return refused.value

    def assert_reconciled(self, error: ToolRuntimeError, tool: str) -> None:
        """The racing call is EXECUTION_UNKNOWN, recorded with the C6 reconciler, never auto-retried."""
        outcome = error.reconciliation
        assert error.execution_unknown is True and outcome is not None
        assert (outcome.tool_name, outcome.lease_id, outcome.stop_epoch) == (tool, self.lease.lease_id, self.lease.stop_epoch)
        assert outcome.correlation_id == CALLER.correlation_id
        assert self.runtime.reconciler.records == (outcome.reconciliation,)
        assert outcome.reconciliation.status is OutcomeStatus.UNKNOWN
        with pytest.raises(SafetyError):
            self.runtime.reconciler.require_may_auto_retry(outcome.command_id)

    def names(self) -> list[str]:
        return [name for name, _ in self.effects]


def _search_events(world: f10.FgmWorld) -> list[tuple[object, object]]:
    return [(e["action"], e.get("reason_code")) for e in world.audit.events if str(e["action"]).startswith("searchMemory")]


def test_fgm_17_positive_a_kill_switch_or_revocation_racing_a_use_leaves_no_retrieval_or_tool_influence(
    campaign: Campaign,
) -> None:
    world = campaign.world()
    assert_backends_real(campaign, world)
    t57.populate(world)
    audit = campaign.receipts(world)
    body = t52.request(RetrievalMode.HYBRID, text="harbour patrol schedule", deadline=world.deadline())
    # Control: with an unchanged stop epoch and a live delegation the use succeeds.
    assert world.service().search(body, binding=t52.binding()).hits
    ledger = life.ledger_snapshot(world)
    # Kill switch raised during retrieval: audited denial, no hit.
    events = len(world.audit.events)
    world.stop.bump_after = world.stop.reads + 1
    t52.assert_retrieval_error(lambda: world.service().search(body, binding=t52.binding()), "STOP_EPOCH_MISMATCH", "STOP_EPOCH_CHANGED")
    assert [(e["action"], e["reason_code"]) for e in world.audit.events[events:]] == [("searchMemory.denied", "STOP_EPOCH_MISMATCH")]
    world.stop = t52.StopState()
    # Kill switch raised during context assembly: no context, no success receipt.
    t57.expect(
        lambda: t57.assembler(world, audit, t57.KillSwitchPolicy(stop=world.stop)).assemble(
            t57.assembly_request(world, operation="fgm17-ks"), binding=t52.binding()
        ),
        "STOP_EPOCH_MISMATCH", "STOP_EPOCH_CHANGED",
    )
    assert audit.actions()[-1] == "assembleMemoryContext.denied" and "assembleMemoryContext" not in audit.actions()

    class RevokedAfterPlan(t52.GrantPolicy):
        def authorize_materialization(self, item: Any, ctx: Any) -> Any:
            decision = super().authorize_materialization(item, ctx)
            revoked = sum(call.startswith("materialize:") for call in self.calls) > 1
            return dataclasses.replace(decision, permitted=decision.permitted and not revoked)

    # Delegation revoked between planning and materialisation: the whole answer is discarded.
    granted = world.policy
    world.policy = RevokedAfterPlan()
    events = len(world.audit.events)
    t52.assert_retrieval_error(lambda: world.service().search(body, binding=t52.binding()), "REPRESENTATION_NOT_READY", "CANDIDATE_CHANGED")
    assert [(e["action"], e["detail_code"]) for e in world.audit.events[events:]] == [("searchMemory.denied", "CANDIDATE_CHANGED")]
    world.policy = granted
    # FR-038 tool path: the real C8 boundary, one kill switch with memory.  Control: before any
    # stop a governed tool use of memory is dispatched and influences the next tool.
    tools = ToolBoundary(world)
    receipt = tools.invoke("act_on(recall_memory(text))")
    found = tools.effects[0][1]
    assert found and tools.effects == [("recall_memory", found), ("act_on", found)]
    assert receipt.result == len(found) and receipt.stop_epoch == tools.stop.epoch == 0
    assert tools.runtime.reconciler.records == ()
    # Kill switch accepted while the tool's retrieval is in flight: the retrieval is denied and
    # audited, the call is EXECUTION_UNKNOWN and reconciled, the next tool is never dispatched.
    tools.effects.clear()
    events = len(world.audit.events)
    tools.memory_stop.stop_at_read = tools.memory_stop.reads + 2
    refused = tools.refused("act_on(recall_memory(text))", "STOP_BOUND_DENIED")
    assert tools.stop_accepted_at is not None and tools.effects == []
    tools.assert_reconciled(refused, "recall_memory")
    assert [(e["action"], e["reason_code"]) for e in world.audit.events[events:]] == [("searchMemory.denied", "STOP_EPOCH_MISMATCH")]
    # After the stop the pre-stop lease is dead on the lease channel: no later use reaches memory.
    with pytest.raises(ToolRuntimeError) as late:
        tools.recall()
    assert late.value.reason_code == "STOP_BOUND_DENIED" and len(world.audit.events) == events + 1
    # Delegation revoked after a use of memory, while the expression runs: the tool that would act
    # on it is refused at its dispatch (ADD v1.3 Part II §2.12: every tool invocation re-evaluates
    # the live capability and delegation), so the revoked grant has no further tool influence.
    tools = ToolBoundary(world)
    tools.after_recall = lambda: tools.authority.revoke(tools.lease.lease_id, at=datetime.now(UTC))
    with pytest.raises(Exception) as revoked:
        tools.invoke("act_on(recall_memory(text))")
    assert tools.names() == ["recall_memory"]
    assert isinstance(revoked.value, ToolRuntimeError), f"the dispatch gate let the revoked lease through: {revoked.value!r}"
    assert revoked.value.reason_code == "CAPABILITY_DENIED" and revoked.value.execution_unknown is False
    events = len(world.audit.events)
    with pytest.raises(ToolRuntimeError) as late:
        tools.recall()
    assert late.value.reason_code == "CAPABILITY_DENIED" and len(world.audit.events) == events
    # NFR-048: zero memory mutation by any racing use.
    assert life.ledger_snapshot(world) == ledger


def test_fgm_17_negative_after_a_kill_switch_or_revoked_delegation_no_earlier_grant_can_be_used(campaign: Campaign) -> None:
    world = campaign.world()
    t57.populate(world)
    world.admit("source", "harbour patrol schedule promotion source")
    audit = campaign.receipts(world)
    policy = t58.PromotionPolicy()
    promotion = t58.service(world, audit, policy)
    proposal = promotion.propose("source", t58.request(world), binding=t52.binding())
    assembly = t57.assembler(world, audit, t57.ContextPolicy()).assemble(t57.assembly_request(world, operation="fgm17-a"), binding=t52.binding())
    ledger = life.ledger_snapshot(world)
    # Kill switch: the recorded proposal (the tool-effect path) and the assembly replay are dead.
    world.stop.epoch += 1
    with pytest.raises(MemoryAdmissionError):
        promotion.load(proposal.audit_ref, binding=t52.binding())
    assert audit.actions()[-1] == "consumeMemoryPromotion.denied"
    t57.expect(
        lambda: t57.assembler(world, audit, t57.KillSwitchPolicy(stop=world.stop)).replay(
            assembly.audit_ref, t57.assembly_request(world, operation="fgm17-r"), binding=t52.binding()
        ),
        "STOP_EPOCH_MISMATCH", "STOP_EPOCH_CHANGED",
    )
    # FR-038 tool path: a lease issued before the kill switch never reaches a tool or memory again,
    # whatever epoch is presented and even after the dual-control reset (LLD v1.1 §4.3).
    stopped = world.stop
    tools = ToolBoundary(world)
    tools.accept_stop()
    events = len(world.audit.events)
    tools.refused("act_on(recall_memory(text))", "STOP_BOUND_DENIED")
    tools.refused("act_on(recall_memory(text))", "STOP_BOUND_DENIED", stop_epoch=0)
    tools.reset()
    assert tools.stop.epoch == 2
    tools.refused("act_on(recall_memory(text))", "STOP_BOUND_DENIED")
    with pytest.raises(ToolRuntimeError) as late:
        tools.recall()
    assert late.value.reason_code == "STOP_BOUND_DENIED"
    # A revoked lease of the new epoch is refused before any tool or memory use.
    tools.lease = tools.issue()
    tools.authority.revoke(tools.lease.lease_id, at=datetime.now(UTC))
    tools.refused("act_on(recall_memory(text))", "CAPABILITY_DENIED")
    assert tools.effects == [] and tools.runtime.reconciler.records == () and len(world.audit.events) == events
    # A tool that does not cooperate races the stop: the call is refused within the containment
    # target and reconciled, and its late use of memory from a ``finally`` is refused on the lease
    # channel.  An effect on a channel the platform does not govern stays the declared residual.
    tools = ToolBoundary(world)
    tools.accept_stop_later(STOP_AFTER_SECONDS)
    refused = tools.refused("slow_recall(text)", "STOP_BOUND_DENIED", tool_name="slow_recall")
    returned = time.monotonic()
    assert tools.settled.wait(NATIVE_WAIT_SECONDS + 5.0)
    assert tools.stop_accepted_at is not None and returned - tools.stop_accepted_at <= CONTAINMENT_TARGET_SECONDS
    tools.assert_reconciled(refused, "slow_recall")
    assert tools.late == ["STOP_BOUND_DENIED"] and tools.effects == [] and len(world.audit.events) == events
    world.stop = stopped
    # Revoked delegation: retrieval is refused and earlier proposals cannot be consumed.
    world.policy.permitted = False
    body = t52.request(RetrievalMode.HYBRID, text="harbour patrol schedule", deadline=world.deadline())
    with pytest.raises((MemoryRetrievalError, MemoryAdmissionError)):
        world.service().search(body, binding=t52.binding())
    assert world.audit.events[-1]["action"] == "searchMemory.denied"
    policy.permitted = False
    with pytest.raises(MemoryAdmissionError):
        promotion.load(proposal.audit_ref, binding=t52.binding())
    with pytest.raises(MemoryAdmissionError):
        promotion.propose("source", {**t58.request(world), "operation_id": "fgm17-again"}, binding=t52.binding())
    # NFR-048: every attempt is audited, none mutates memory.
    assert life.ledger_snapshot(world) == ledger
    assert audit.actions().count("consumeMemoryPromotion.denied") == 2
    assert audit.actions()[-1] == "proposeMemoryPromotion.denied"


# --------------------------------------------------------------------------
# FGM-18 -- restore after deletion (FR-118)
# --------------------------------------------------------------------------


def test_fgm_18_positive_a_restored_backup_never_resurrects_and_reconciles_the_tombstone(campaign: Campaign) -> None:
    d = t56.drill(campaign, campaign.tmp(), twin=True)
    assert_backends_real(campaign, d.restored)
    x, twin = d.items["x"], d.items["twin"]
    assert d.source.delete("x", op="fgm18-forget-x").lifecycle_status == "DELETED"
    d.deliver_journal()
    # The backup really holds x in every store: the resurrection risk is real.
    assert all("urn:ocor:memory:x:v1" in refs for refs in d.refs().values())
    assert life.native_entries(d.restored, x) == {"lexical": 1, "vector": 1}
    gate = d.gate()
    with pytest.raises(DeletionRecoveryError, match="RESTORE_NOT_RECONCILED"):
        gate.serve(d.refs)
    receipt = gate.reconcile()
    # Tombstone reconciled: the attested deletion checkpoint is the authority's journal.
    assert receipt.obligations == 1
    assert receipt.checkpoint == DeletionJournalSnapshot.capture(d.authority_journal).checkpoint
    found = gate.serve(d.refs)
    assert not t56.mentions(found, "x") and all("urn:ocor:memory:twin:v1" in refs for refs in found.values())
    assert d.restored.status("x") == d.source.status("x") == "DELETED"
    assert life.native_entries(d.restored, x) == {"lexical": 0, "vector": 0}
    assert life.parallel_descriptors(d.restored, x) == [] and life.content_present(d.restored, twin)
    for version in range(1, d.source.ledger.latest_version("x") + 1):
        assert d.restored.ledger.get("x", version).to_mapping() == d.source.ledger.get("x", version).to_mapping()  # type: ignore[union-attr]
    # Restart over the restored stores starts closed and reconciles idempotently.
    restarted = campaign.world(schema=d.restored.metadata.schema)
    restarted.rep_audit.events.extend(d.restored.rep_audit.events)
    for item in d.items:
        for version in range(1, d.restored.ledger.latest_version(item) + 1):
            restarted.ledger.append(d.restored.ledger.get(item, version))
    versions = d.restored.ledger.latest_version("x")
    d.restored = restarted
    again = d.gate()
    with pytest.raises(DeletionRecoveryError, match="RESTORE_NOT_RECONCILED"):
        again.serve(d.refs)
    assert again.reconcile().obligations == 1 and restarted.ledger.latest_version("x") == versions
    assert not t56.mentions(again.serve(d.refs), "x")
    # The OCOR-DEV-0059 restore gate: a manifest signed by OpenBao before the deletion opens the
    # restore only through the tombstone replay; the deleted item is never served again.
    m = ops.live_drill(campaign, campaign.tmp())
    backup, signer, _ = ops.live_capture(m, campaign)
    assert m.source.delete("x", op="fgm18-manifest-forget-x").lifecycle_status == "DELETED"
    m.deliver_journal()
    assert ops.mentions(m.refs(), "x")
    restore = ops.live_restore(m, campaign, signer)
    ops.refused(lambda: restore.serve(m.refs), "RESTORE_NOT_OPEN")
    opened = restore.open(backup.payload, backup.signature)
    assert opened.obligations == 1 and opened.deleted_after_backup == ("x",) and opened.verified_items == 2
    served = restore.serve(m.refs)
    assert not ops.mentions(served, "x") and ops.mentions(served, "keep") and m.restored.status("x") == "DELETED"


def test_fgm_18_negative_unauthenticated_incomplete_or_stale_reconciliation_keeps_the_restore_closed(
    campaign: Campaign,
) -> None:
    replica = life.FailingParticipant(failures=1)
    d = t56.drill(campaign, campaign.tmp(), replica=replica)
    replica.track(d.items["y"])
    assert d.source.delete("y", op="fgm18n-forget-y").lifecycle_status == "DELETION_INCOMPLETE"
    assert d.source.delete("x", op="fgm18n-forget-x").lifecycle_status == "DELETED"
    d.deliver_journal()
    # A forged or foreign checkpoint is not authority: nothing is purged, nothing served.
    for forge, code in (("payload", "CHECKPOINT_UNAUTHENTICATED"), ("malformed", "CHECKPOINT_UNAUTHENTICATED"),
                        ("other-recovery-point", "RECOVERY_POINT_MISMATCH")):
        d.issuer.forge = forge
        gate = d.gate(t56.RestoredReplica({"urn:ocor:memory:y:v1"}))
        with pytest.raises(DeletionRecoveryError, match=code):
            gate.reconcile()
        with pytest.raises(DeletionRecoveryError, match="RESTORE_NOT_RECONCILED"):
            gate.serve(d.refs)
        assert t56.mentions(d.refs(), "x"), forge
    d.issuer.forge = None
    # A restore composition omitting a store the saga recorded cannot qualify.
    omitted = d.gate()
    with pytest.raises(DeletionRecoveryError, match="DELETION_PARTICIPANT_MISSING"):
        omitted.reconcile()
    with pytest.raises(DeletionRecoveryError, match="RESTORE_NOT_RECONCILED"):
        omitted.serve(d.refs)
    gate = d.gate(t56.RestoredReplica({"urn:ocor:memory:y:v1"}))
    gate.reconcile()
    assert not t56.mentions(gate.serve(d.refs), "x") and not t56.mentions(gate.serve(d.refs), "y")
    # A deletion made after reopening closes the gate until the new journal is reconciled.
    d.source.delete("keep", op="fgm18n-forget-keep")
    with pytest.raises(DeletionRecoveryError, match="CHECKPOINT_MISMATCH"):
        gate.serve(d.refs)
    with pytest.raises(DeletionRecoveryError, match="RESTORE_NOT_RECONCILED"):
        gate.serve(d.refs)
    # The OCOR-DEV-0059 restore gate: a tampered manifest, or a deletion authority behind the
    # manifest (a journal rollback), never opens the restore and purges nothing.
    m = ops.live_drill(campaign, campaign.tmp())
    rollback = campaign.tmp() / "before-deletion.jsonl"
    rollback.write_bytes(m.authority_journal.read_bytes())
    assert m.source.delete("y", op="fgm18n-manifest-forget-y").lifecycle_status == "DELETED"
    backup, signer, _ = ops.live_capture(m, campaign)
    m.deliver_journal()
    restore = ops.live_restore(m, campaign, signer)
    ops.refused(lambda: restore.open(backup.payload.replace(b'"keep"', b'"kept"'), backup.signature), "BACKUP_UNAUTHENTICATED")
    stale = ops.live_restore(m, campaign, signer, checkpoints=ops.Checkpoints(rollback))
    ops.refused(lambda: stale.open(backup.payload, backup.signature), "STALE_DELETION_EPOCH")
    for closed in (restore, stale):
        ops.refused(lambda closed=closed: closed.serve(m.refs), "RESTORE_NOT_OPEN")
    assert ops.mentions(m.refs(), "y")


# --------------------------------------------------------------------------
# FGM-19 -- quota/retention pressure (FR-118)
# --------------------------------------------------------------------------


def _pressure_world(campaign: Campaign) -> tuple[f10.FgmWorld, MemoryPartition]:
    world = campaign.world(tombstones=JournalTombstoneStore(campaign.tmp() / "tombstones.jsonl"))
    partition = ops.seed(world)  # "a-old"
    world.admit("b-old", TEXT + " b")
    world.admit("held", TEXT + " held")
    world.holds.place()
    world.move("held", "LEGAL_HOLD", hold=HOLD)
    return world, partition


def test_fgm_19_positive_pressure_and_retention_select_deterministically_and_protect_the_legal_hold(
    campaign: Campaign,
) -> None:
    selections = []
    for _ in range(2):  # the same inventory on two worlds selects identically
        world, partition = _pressure_world(campaign)
        assert_backends_real(campaign, world)
        audit = campaign.receipts(world)
        service, _, _ = ops.setup(world, audit=audit)
        first = ops.invoke(service, world, partition, "relieve_pressure", target_items=1, limit=1)
        assert first.deleted == ("a-old",) and first.satisfied is False and audit.receipt(first.audit_ref)["outcome"] == "BACKPRESSURE"
        second = ops.invoke(service, world, partition, "relieve_pressure", target_items=1, limit=1)
        assert second.deleted == ("b-old",) and second.satisfied
        selections.append((first.deleted, second.deleted))
        # FR-118: the held item is never selected, keeps its content and has no tombstone.
        assert world.status("held") == "LEGAL_HOLD" and world.tombstones.entries("held") == ()
        assert life.content_present(world, world.ledger.get("held", 1))  # type: ignore[arg-type]
        for item_id in ("a-old", "b-old"):
            assert world.tombstones.entries(item_id)[-1].phase == "COMPLETED"
            assert not life.content_present(world, world.ledger.get(item_id, 1))  # type: ignore[arg-type]
    assert selections[0] == selections[1]
    # Retention: due instant, then item id; new items and holds are kept.
    world, partition = _pressure_world(campaign)
    world.clock.advance(timedelta(days=20))
    world.admit("young", TEXT + " young")
    world.clock.advance(timedelta(days=350))
    service, _, _ = ops.setup(world, audit=campaign.receipts(world))
    report = ops.invoke(service, world, partition, "enforce_retention", limit=2)
    assert report.deleted == ("a-old", "b-old") and report.held == ("held",)
    assert world.status("young") == "ACTIVE" and world.status("held") == "LEGAL_HOLD"


def test_fgm_19_negative_a_racing_hold_audit_loss_or_unauthorized_demand_never_evicts_or_changes_the_quota(
    campaign: Campaign,
) -> None:
    # A legal hold placed during the pressure policy check refuses the stale selection.
    world = campaign.world()
    partition = ops.seed(world)
    service, _, policy = ops.setup(world, audit=campaign.receipts(world))
    original = policy.authorize_operations

    def raced(operation: str, target: MemoryPartition, ctx: Any) -> Any:
        if len(policy.calls) == 1:
            world.holds.place()
            world.move("a-old", "LEGAL_HOLD", hold=HOLD)
        return original(operation, target, ctx)

    policy.authorize_operations = raced  # type: ignore[method-assign]
    ops.refused(lambda: ops.invoke(service, world, partition, "relieve_pressure", target_items=0, limit=1), "CANDIDATE_CHANGED")
    assert world.status("a-old") == "LEGAL_HOLD" and world.tombstones.entries("a-old") == ()
    # Without an audit store no pressure deletion happens.
    other = campaign.world()
    other_partition = ops.seed(other)
    audit = campaign.receipts(other)
    other_service, _, _ = ops.setup(other, audit=audit)
    with psycopg.connect(campaign.dsn, autocommit=True) as conn:
        conn.execute(f'DROP TABLE "{other.metadata.schema}".memory_audit')
    ops.refused(lambda: ops.invoke(other_service, other, other_partition, "relieve_pressure", target_items=0, limit=1), "AUDIT_UNAVAILABLE")
    assert other.status("a-old") == "ACTIVE" and life.content_present(other, other.ledger.get("a-old", 1))  # type: ignore[arg-type]
    # Unauthorized items never change the quota decision; an unknown retention policy never forgets.
    third = campaign.world()
    third_partition = ops.seed(third)
    third_service, _, _ = ops.setup(third, audit=campaign.receipts(third))
    usage = ops.invoke(third_service, third, third_partition, "check_quota", demand=MemoryQuotaDemand(new_items=1)).usage
    for n in range(4):
        third.admit(f"hidden-{n}", TEXT, ctx=t52.context(compartments=("bravo",)))
    assert ops.invoke(third_service, third, third_partition, "check_quota", demand=MemoryQuotaDemand(new_items=1)).usage == usage
    ops.refused(lambda: ops.invoke(third_service, third, third_partition, "check_quota", demand=MemoryQuotaDemand(new_items=2)),
                "ITEM_QUOTA_EXCEEDED")
    third.clock.advance(timedelta(days=400))
    unconfigured, _, _ = ops.setup(third, audit=campaign.receipts(third), limits=ops.MemoryOperationsLimits(
        retention_horizons={"retention:other": timedelta(days=1)}))
    ops.refused(lambda: ops.invoke(unconfigured, third, third_partition, "enforce_retention", limit=2), "RETENTION_UNCONFIGURED")
    assert third.status("a-old") == "ACTIVE" and life.content_present(third, third.ledger.get("a-old", 1))  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# FGM-20 -- context assembly exact replay (FR-118)
# --------------------------------------------------------------------------


def test_fgm_20_positive_replay_reproduces_items_versions_redactions_order_and_truncation_exactly(campaign: Campaign) -> None:
    world = campaign.world()
    assert_backends_real(campaign, world)
    t57.populate(world)
    audit = campaign.receipts(world)
    policy = t57.ContextPolicy(redact={"p-1": (("RAVEN-7", "CALL_SIGN"),)})
    truncations: list[list[str]] = []
    for mode in RetrievalMode:
        original = t57.assembler(world, audit, policy).assemble(
            t57.assembly_request(world, mode=mode, max_bytes=900, operation=f"fgm20-{mode.value}"), binding=t52.binding()
        )
        stored = audit.receipt(original.audit_ref)
        assert stored is not None and canonical_digest({k: v for k, v in stored.items() if k != "audit_ref"}) == original.audit_ref
        blocks = stored["replay"]["blocks"]
        # FR-118: every influence on the context is receipted -- exact item, version, digests, order.
        included = original.truncation_record["included_count"]
        cut = list(original.truncation_record["truncated_item_version_refs"])
        assert [b["memory_version_ref"] for b in blocks][:included] == list(original.selected_item_version_refs), mode
        assert [b["memory_version_ref"] for b in blocks][included:] == cut, mode
        assert [b["position"] for b in blocks] == list(range(1, len(blocks) + 1))
        assert all(b["item_digest"].startswith("urn:sha256:") and b["content_digest"].startswith("urn:sha256:") for b in blocks)
        assert b"RAVEN-7" not in original.context
        if "urn:ocor:memory:p-1:v1" in original.selected_item_version_refs:
            assert original.redaction_refs, mode
        assert included == len(original.selected_item_version_refs)
        # A later run (new adapters and connections) replays the exact bytes and receipt core.
        later = campaign.fresh(world)
        world.clock.advance(timedelta(minutes=3))  # ranking recency drifts; the exact replay does not re-rank
        replayed = t57.assembler(later, campaign.receipts(later), policy).replay(
            original.audit_ref, t57.assembly_request(later, mode=mode, max_bytes=900, operation=f"fgm20-r-{mode.value}"),
            binding=t52.binding(),
        )
        assert replayed.context == original.context and replayed.context_digest == original.context_digest, mode
        for name in ("query_digest", "selected_item_version_refs", "redaction_refs", "ordering_profile_ref",
                     "truncation_record", "context_ref", "governed_context_digest"):
            assert getattr(replayed, name) == getattr(original, name), (mode, name)
        event = audit.receipt(replayed.audit_ref)
        assert event is not None and event["action"] == "replayMemoryContext" and event["replayed_audit_ref"] == original.audit_ref
        truncations.append(cut)
    # The budget really truncated: the replay covers a recorded truncation, not only whole contexts.
    assert any(truncations)


def test_fgm_20_negative_a_replay_that_cannot_be_exact_fails_closed_without_context(campaign: Campaign) -> None:
    world = campaign.world()
    t57.populate(world)
    audit = campaign.receipts(world)
    policy = t57.ContextPolicy()
    service = t57.assembler(world, audit, policy)
    original = service.assemble(t57.assembly_request(world, operation="fgm20n-a"), binding=t52.binding())
    # Any input that the receipt did not record is refused.
    for label, body, who, code in (
        ("query", t57.assembly_request(world, text="harbour patrol schedule bravo", operation="fgm20n-q"), t52.binding(),
         ("MEMORY_SCHEMA_INVALID", "REPLAY_INPUT_UNRECORDED")),
        ("max-bytes", t57.assembly_request(world, max_bytes=1000, operation="fgm20n-m"), t52.binding(),
         ("MEMORY_SCHEMA_INVALID", "REPLAY_INPUT_UNRECORDED")),
        ("target-model", {**t57.assembly_request(world, operation="fgm20n-t"), "target_model_ref": "urn:ocor:model:other:1"},
         t52.binding(), ("MEMORY_SCHEMA_INVALID", "REPLAY_INPUT_UNRECORDED")),
    ):
        t57.expect(lambda body=body, who=who: service.replay(original.audit_ref, body, binding=who), *code)
    t57.expect(lambda: service.replay("urn:sha256:" + "1" * 64, t57.assembly_request(world, operation="fgm20n-u"), binding=t52.binding()),
               "MEMORY_SCHEMA_INVALID", "RECEIPT_UNRECORDED")
    # A tampered durable receipt is detected.
    with psycopg.connect(campaign.dsn, autocommit=True) as conn:
        row = conn.execute(f'SELECT seq, body FROM "{world.metadata.schema}".memory_audit WHERE audit_ref=%s', (original.audit_ref,)).fetchone()
        assert row is not None
        tampered = bytes(row[1]).replace(b'"included_count":', b'"included_count":9', 1)
        assert tampered != bytes(row[1])
        conn.execute(f'UPDATE "{world.metadata.schema}".memory_audit SET body=%s WHERE seq=%s', (tampered, row[0]))
    with pytest.raises(MemoryAdmissionError):
        service.replay(original.audit_ref, t57.assembly_request(world, operation="fgm20n-tamper"), binding=t52.binding())
    with psycopg.connect(campaign.dsn, autocommit=True) as conn:
        conn.execute(f'UPDATE "{world.metadata.schema}".memory_audit SET body=%s WHERE seq=%s', (bytes(row[1]), row[0]))
    # A changed memory version, redaction policy or context decision never yields a context.
    policy.redact["p-1"] = (("RAVEN-7", "CALL_SIGN"),)
    t57.expect(lambda: service.replay(original.audit_ref, t57.assembly_request(world, operation="fgm20n-r"), binding=t52.binding()),
               "REPRESENTATION_NOT_READY", "CONTEXT_REPLAY_MISMATCH")
    policy.redact.clear()
    record = world.ledger.get("p-1", 1)
    assert record is not None
    world.move("p-1", "REVOKED", reason="SOURCE_RETRACTED")
    t57.expect(lambda: service.replay(original.audit_ref, t57.assembly_request(world, operation="fgm20n-v"), binding=t52.binding()),
               "REPRESENTATION_NOT_READY", "CANDIDATE_CHANGED")
    actions = audit.actions()
    assert actions.count("replayMemoryContext") == 0 and actions.count("replayMemoryContext.denied") == 7


# --------------------------------------------------------------------------
# Campaign structure (not qualifying store cases)
# --------------------------------------------------------------------------


def _lld_rows() -> dict[str, tuple[str, str]]:
    rows: dict[str, tuple[str, str]] = {}
    for line in LLD.read_text("utf-8").splitlines():
        match = re.match(r"^\| `(FGM-\d\d)` \| (.+?) \| (.+?) \|$", line)
        if match:
            rows[match.group(1)] = (match.group(2), match.group(3))
    return rows


def test_campaign_rows_match_the_normative_lld_table() -> None:
    rows = _lld_rows()
    assert len(rows) == 20
    for fgm, (scenario, oracle, _) in CAMPAIGN.items():
        assert rows[fgm] == (scenario, oracle), fgm
    assert sorted(CAMPAIGN) == [f"FGM-{n:02d}" for n in range(11, 21)]


def test_every_planned_requirement_is_bound_to_a_positive_and_negative_case() -> None:
    with TRACE.open(encoding="utf-8", newline="") as handle:
        planned = {row["requirement_id"] for row in csv.DictReader(handle) if row["verification_task"] == TASK_ID}
    bound = {req for _, _, reqs in CAMPAIGN.values() for req in reqs}
    assert planned and bound == planned
    assert "BR-003" not in bound
    module = sys.modules[__name__]
    names = [name for name in dir(module) if name.startswith("test_fgm_")]
    for fgm in CAMPAIGN:
        number = fgm.split("-")[1]
        for polarity in ("positive", "negative"):
            matches = [n for n in names if n.startswith(f"test_fgm_{number}_{polarity}_")]
            assert len(matches) == 1, (fgm, polarity, matches)
            parameters = getattr(module, matches[0]).__code__.co_varnames[:1]
            assert parameters == ("campaign",), (fgm, polarity)
