"""OCOR-DEV-REM-0054 (NCP-U08): C6 safety and policy conform to the closed normative elements.

Unit of NORMATIVE-CONFORMANCE-PLAN (2026-10-30), plan unit NCP-U08, register entries
NCR-C6-010 to NCR-C6-013.

* NCR-C6-010 -- ADD v1.3 :3343 (the emergency stop is activated immediately by an authorised
  Safety Officer, one activator, no quorum; the reset needs two approvers), ADD v1.3 :3347 (the
  break-glass is an exceptional signed Delegation with a minimal scope, a mandatory purpose, named
  capabilities, TTL at most 15 minutes and no renewal), ADD v1.3 :3351 (the Emergency Control
  Plane is outside the agents and the activation increments a signed ``stop_epoch``), ADD v1.3
  :3360 (every mutative call presents the current ``stop_epoch``; the reset needs dual control and
  generates a new epoch), LLD v1.1 :324 (typed reason, incident, minimal scope, short TTL, two
  distinct humans, synchronous audit), LLD v1.1 :328 (the stop increments ``stop_epoch``
  atomically; the reset needs dual control, the verification of incident and recovery and a new
  epoch, and never re-enables earlier leases), Register FR-139 :311 (break-glass prerequisites),
  NFR-047 :312 (the stop prevents new commands in the local boundary) and NFR-081 :413 (no single
  principal enables a high-impact action; break-glass limited, expiring and audited). Additional
  criterion of NORMATIVE-CONFORMANCE-PLAN point 2 for NCP-U08: the signed ``stop_epoch`` is
  durable and is read through a port by G-DISPATCH and by the C8 tool runtime; it is not an
  attribute of the process that activates the stop.

* NCR-C6-013 -- ADD v1.3 :3298-3305 (§5.4 risk classes ``R0_READ``, ``R1_ANALYZE``,
  ``R2_CONTROLLED``, ``R3_HIGH_IMPACT`` and their gates: R0 policy and Authority without Approval,
  R1 no mutation, R2 one independent human approver, R3 two independent human approvers), ADD
  v1.3 :2193 (the ``risk_class`` enum of the Action Type Contract), LLD v1.1 :313-318 (§4.1 names
  ``R1_DERIVE`` and ``R2_MUTATE``) and LLD v1.1 :16-18 (§0.1: ADD v1.3 prevails over the LLD; no
  correction through aliases). The kernel risk class and the control-plane operation class carry
  the ADD names only, the wire forms carry them, and the gates are those of ADD v1.3 §5.4.

* NCR-C6-011 -- ADD v1.3 :3141 (§5.1 authorisation: default-deny policy with the decisions
  ``Permit``, ``Deny``, ``PermitWithConstraints``, ``RequireApproval``, ``Obligate``; a policy that is
  absent or not evaluable gives no mutation) and Register FR-130 :295 (every governed contract
  produces a versioned, explainable Policy Decision applying those five decisions; requests without
  policy are denied). The OPA decision point derives the effect and its constraints, approval
  requirements or obligations from the signed bundle, rejects a malformed or ambiguous
  qualification, and a consumer admits a decision only when it enforces every constraint, holds every
  required approval and fulfils every obligation.

* NCR-C6-012 -- LLD v1.1 :67 (§1.3: a missing, incomparable or unresolvable marking produces
  ``MARKING_UNRESOLVED``; the join is the conservative least upper bound), Register FR-131 :298
  (conservative propagation of mandatory controls) and FR-006 :49 (uniform compartmentation). The
  C2 gateway and the C8 tool runtime evaluate marking with a resolving engine over the validated
  lattices: every scheme of the active set must be present with a known label, an incomparable pair
  is unresolved, never the legacy bottom default or an ignored scheme; C2 denies an unresolved
  clearance (ADD v1.3 :401) and C8 refuses the call with ``MARKING_UNRESOLVED`` before any effect.
  The legacy ``c4_marking.MarkingEngine`` is unchanged (programme point 6) and refused by both.

The durable stop-epoch store is the real PostgreSQL of the stack (``OCOR_LIVE_POSTGRES_DSN``);
the other cases use the in-memory implementation of the same port. The policy cases evaluate signed
bundles on the real OPA over mTLS (SPIFFE/SPIRE) for a real Keycloak principal, with the fixtures
of the sealed OCOR-DEV-0048 module, reused unmodified.
"""

from __future__ import annotations

import base64
import dataclasses
import importlib
import importlib.util
import inspect
import os
import threading
import uuid
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import Any

import pytest

NOW = datetime(2026, 11, 6, 9, 0, 0, tzinfo=UTC)
HUMAN_A = "urn:ocor:human:a"
HUMAN_B = "urn:ocor:human:b"
HUMAN_C = "urn:ocor:human:c"
SDO = "urn:ocor:human:security-duty-officer"
OWNER = "urn:ocor:human:maritime-owner"
REQUESTER = "urn:ocor:human:requester"
DOMAIN = "maritime"


def _mod(name: str) -> ModuleType:
    return importlib.import_module(f"ocor_runtime.{name}")


def _fx() -> ModuleType:
    return importlib.import_module("c6_safety_fixture")


def _safety() -> ModuleType:
    return _mod("c6.safety")


def _reason(excinfo: pytest.ExceptionInfo[BaseException]) -> str:
    return str(getattr(excinfo.value, "reason_code", type(excinfo.value).__name__))


def _registry(**roles: str) -> Any:
    identity = _mod("c2_identity")
    people = {HUMAN_A: "", HUMAN_B: "", HUMAN_C: "", SDO: "SECURITY_DUTY_OFFICER", OWNER: f"DOMAIN_OWNER:{DOMAIN}", REQUESTER: ""}
    people.update(roles)
    return identity.IdentityRegistry(
        identity.IdentityRecord(canonical_id=cid, attributes={"principal_kind": "HUMAN", "status": "ACTIVE", "roles": value})
        for cid, value in people.items()
    )


def _stopped(stop: Any) -> Any:
    _fx().activate(stop, reason="incident-42", at=NOW)
    return stop.finish_draining(at=NOW)


def _dsn() -> str:
    dsn = os.environ.get("OCOR_LIVE_POSTGRES_DSN")
    if not dsn:
        pytest.fail("OCOR_LIVE_POSTGRES_DSN is mandatory qualifying evidence (durable stop-epoch store on PostgreSQL)")
    return dsn


@pytest.fixture
def postgres_epochs() -> Any:
    adapters = importlib.import_module("ocor_runtime.c6.adapters.postgres_stop")
    store = adapters.PostgresStopEpochStore(_dsn(), schema=f"ocor_rem0054_{uuid.uuid4().hex[:12]}")
    store.initialize()
    try:
        yield store
    finally:
        store.drop()


# --- NCR-C6-010: activation by an authorised Safety Officer (ADD v1.3 :3343) ---------------------


def test_ncr_c6_010_conforms() -> None:
    """The register's RED probe: activation takes the activator and the incident, the reset takes
    the recovery verification, the epoch is signed and the break-glass grant is signed."""
    safety = _safety()
    stop = _fx().stop_controller(_registry())
    event = _fx().activate(stop, reason="incident-42", at=NOW)
    assert event.activated_by == _fx().SAFETY_OFFICER
    signed = stop.reader.current_signed()
    assert isinstance(signed, safety.SignedStopEpoch)
    assert signed.record.epoch == event.epoch == 1
    assert {field.name for field in dataclasses.fields(safety.BreakGlassGrant)} >= {"issuer_id", "keyid", "signature"}
    assert "recovery" in inspect.signature(safety.EmergencyStopController.request_reset).parameters


def test_ncr_c6_010_an_authorised_safety_officer_activates_alone_and_immediately() -> None:
    safety = _safety()
    stop = _fx().stop_controller(_registry())
    event = _fx().activate(stop, reason="incident-42", at=NOW)
    assert stop.status is safety.StopStatus.STOPPING
    assert (event.epoch, event.status, event.activated_by, event.incident_ref) == (
        1, safety.StopStatus.STOPPING, _fx().SAFETY_OFFICER, _fx().INCIDENT
    )


@pytest.mark.parametrize(
    "officer",
    [
        {"roles": ""},
        {"roles": "SECURITY_DUTY_OFFICER"},
        {"status": "SUSPENDED"},
        {"kind": "WORKLOAD"},
    ],
    ids=["no-role", "other-role", "inactive", "workload"],
)
def test_ncr_c6_010_an_activator_that_is_not_an_active_human_safety_officer_is_refused(officer: dict[str, str]) -> None:
    fx = _fx()
    safety = _safety()
    record = fx.safety_officer_record(**officer)
    stop = safety.EmergencyStopController(
        epochs=safety.InMemoryStopEpochStore(),
        identities=fx.WithSafetyOfficer(_registry(), officer=record),
        signing_key=fx.CONTROL_PLANE_KEY,
        issuer_id=fx.CONTROL_PLANE,
        keyid=fx.CONTROL_PLANE_KEYID,
        keyring=fx.keyring(),
    )
    with pytest.raises(safety.SafetyError) as excinfo:
        fx.activate(stop, reason="incident-42", at=NOW)
    assert _reason(excinfo) == "STOP_ACTIVATOR_UNAUTHORIZED"
    assert stop.status is safety.StopStatus.NORMAL
    assert stop.epoch == 0


@pytest.mark.parametrize("activator", ["", "urn:ocor:human:unknown", HUMAN_A], ids=["empty", "unresolved", "plain-human"])
def test_ncr_c6_010_an_unresolved_or_unauthorised_activator_is_refused(activator: str) -> None:
    safety = _safety()
    stop = _fx().stop_controller(_registry())
    with pytest.raises(safety.SafetyError) as excinfo:
        stop.activate(activator=activator, reason="incident-42", incident_ref=_fx().INCIDENT, at=NOW)
    assert _reason(excinfo) == "STOP_ACTIVATOR_UNAUTHORIZED"
    assert stop.epoch == 0


@pytest.mark.parametrize("incident_ref", ["", None, 42], ids=["empty", "none", "int"])
def test_ncr_c6_010_the_activation_names_its_incident(incident_ref: object) -> None:
    stop = _fx().stop_controller(_registry())
    with pytest.raises((ValueError, TypeError)):
        stop.activate(activator=_fx().SAFETY_OFFICER, reason="incident-42", incident_ref=incident_ref, at=NOW)
    assert stop.epoch == 0


# --- NCR-C6-010: the signed stop_epoch (ADD v1.3 :3351) --------------------------------------------


def test_ncr_c6_010_every_transition_publishes_a_signed_stop_epoch_record() -> None:
    fx = _fx()
    safety = _safety()
    stop = fx.stop_controller(_registry())
    _stopped(stop)
    stop.request_reset(approvers=(HUMAN_A, HUMAN_B), identities=_registry(), requester=HUMAN_C, recovery=fx.recovery((HUMAN_A, HUMAN_B)))
    stop.confirm_reset(at=NOW)
    history = stop.reader.signed_history()
    assert [(item.record.epoch, item.record.status.value) for item in history] == [
        (0, "NORMAL"), (1, "STOPPING"), (1, "STOPPED"), (1, "RESET_PENDING"), (2, "NORMAL")
    ]
    assert [item.record.sequence for item in history] == [0, 1, 2, 3, 4]
    for item in history:
        assert (item.issuer_id, item.keyid) == (fx.CONTROL_PLANE, fx.CONTROL_PLANE_KEYID)
        assert safety.verify_stop_epoch(item, keyring=fx.keyring(), issuer_id=fx.CONTROL_PLANE) == item.record
    assert history[1].record.actor == fx.SAFETY_OFFICER
    assert history[1].record.incident_ref == fx.INCIDENT


@pytest.mark.parametrize("field", ["epoch", "status", "actor", "incident_ref", "sequence", "at"])
def test_ncr_c6_010_a_tampered_stop_epoch_record_never_verifies(field: str) -> None:
    fx = _fx()
    safety = _safety()
    stop = fx.stop_controller(_registry())
    fx.activate(stop, reason="incident-42", at=NOW)
    signed = stop.reader.current_signed()
    changes: dict[str, Any] = {
        "epoch": 7, "status": safety.StopStatus.NORMAL, "actor": HUMAN_A, "incident_ref": "urn:ocor:incident:other",
        "sequence": 9, "at": NOW + timedelta(seconds=1),
    }
    forged = dataclasses.replace(signed, record=dataclasses.replace(signed.record, **{field: changes[field]}))
    with pytest.raises(safety.SafetyError) as excinfo:
        safety.verify_stop_epoch(forged, keyring=fx.keyring(), issuer_id=fx.CONTROL_PLANE)
    assert _reason(excinfo) == "STOP_EPOCH_SIGNATURE_INVALID"


def test_ncr_c6_010_a_stop_epoch_signed_by_another_key_or_issuer_never_verifies() -> None:
    fx = _fx()
    safety = _safety()
    stop = fx.stop_controller(_registry())
    signed = stop.reader.current_signed()
    other = safety.sign_stop_epoch(fx.signing_key("not the control plane"), issuer_id=fx.CONTROL_PLANE, keyid=fx.CONTROL_PLANE_KEYID, record=signed.record)
    for candidate, issuer in ((other, fx.CONTROL_PLANE), (signed, fx.BREAK_GLASS_AUTHORITY)):
        with pytest.raises(safety.SafetyError) as excinfo:
            safety.verify_stop_epoch(candidate, keyring=fx.keyring(), issuer_id=issuer)
        assert _reason(excinfo) == "STOP_EPOCH_SIGNATURE_INVALID"
    garbled = dataclasses.replace(signed, signature="not base64 !")
    with pytest.raises(safety.SafetyError) as excinfo:
        safety.verify_stop_epoch(garbled, keyring=fx.keyring(), issuer_id=fx.CONTROL_PLANE)
    assert _reason(excinfo) == "STOP_EPOCH_SIGNATURE_INVALID"


class _TamperingStore:
    """A stop-epoch port whose latest record is replaced by a forged one."""

    def __init__(self, inner: Any, forged: Any) -> None:
        self._inner = inner
        self._forged = forged

    def latest(self) -> Any:
        return self._forged

    def history(self) -> Any:
        return (*self._inner.history()[:-1], self._forged)

    def append(self, signed: Any, *, expected_sequence: int) -> bool:
        return bool(self._inner.append(signed, expected_sequence=expected_sequence))


def test_ncr_c6_010_a_reader_refuses_a_forged_epoch_and_g_dispatch_fails_closed() -> None:
    fx = _fx()
    safety = _safety()
    epochs = safety.InMemoryStopEpochStore()
    stop = fx.stop_controller(_registry(), epochs=epochs)
    signed = stop.reader.current_signed()
    forged = dataclasses.replace(signed, record=dataclasses.replace(signed.record, epoch=5))
    reader = fx.stop_reader(_TamperingStore(epochs, forged))
    for read in (lambda: reader.epoch, lambda: reader.current_stop_epoch(), lambda: reader.emergency_stop_active()):
        with pytest.raises(safety.SafetyError) as excinfo:
            read()
        assert _reason(excinfo) == "STOP_EPOCH_SIGNATURE_INVALID"
    with pytest.raises(safety.SafetyError) as excinfo:
        reader.guard_dispatch(fenced_epoch=5)
    assert _reason(excinfo) == "STOP_EPOCH_SIGNATURE_INVALID"
    dispatch = _mod("c6.dispatch")
    conditions = dispatch.InMemoryDispatchConditions(stop=reader)
    with pytest.raises(safety.SafetyError):
        conditions.current_stop_epoch()


def test_ncr_c6_010_an_empty_or_malformed_port_is_never_read_as_normal() -> None:
    fx = _fx()
    safety = _safety()

    class _Empty:
        def latest(self) -> Any:
            return None

        def history(self) -> tuple[Any, ...]:
            return ()

        def append(self, signed: Any, *, expected_sequence: int) -> bool:
            return False

    class _Wrong(_Empty):
        def latest(self) -> Any:
            return {"epoch": 0, "status": "NORMAL"}

    for store in (_Empty(), _Wrong()):
        reader = fx.stop_reader(store)
        with pytest.raises(safety.SafetyError) as excinfo:
            reader.emergency_stop_active()
        assert _reason(excinfo) in {"STOP_EPOCH_UNAVAILABLE", "STOP_EPOCH_SIGNATURE_INVALID"}


# --- NCR-C6-010: durable and read through a port, not a process attribute (PO criterion point 2) ---


def test_ncr_c6_010_a_reader_on_the_same_port_sees_the_stop_of_another_controller() -> None:
    fx = _fx()
    safety = _safety()
    epochs = safety.InMemoryStopEpochStore()
    controller = fx.stop_controller(_registry(), epochs=epochs)
    reader = fx.stop_reader(epochs)
    assert (reader.epoch, reader.emergency_stop_active()) == (0, False)
    fx.activate(controller, reason="incident-42", at=NOW)
    assert (reader.epoch, reader.current_stop_epoch(), reader.emergency_stop_active()) == (1, 1, True)
    with pytest.raises(safety.SafetyError) as excinfo:
        reader.guard_dispatch(fenced_epoch=1)
    assert _reason(excinfo) == "SYSTEM_NOT_NORMAL"
    successor = fx.stop_controller(_registry(), epochs=epochs)
    assert (successor.status, successor.epoch) == (safety.StopStatus.STOPPING, 1)


def test_ncr_c6_010_the_postgres_store_keeps_the_signed_epoch_across_processes(postgres_epochs: Any) -> None:
    fx = _fx()
    safety = _safety()
    adapters = importlib.import_module("ocor_runtime.c6.adapters.postgres_stop")
    controller = fx.stop_controller(_registry(), epochs=postgres_epochs)
    fx.activate(controller, reason="incident-42", at=NOW)
    del controller
    # A new process: a new store object on the same schema and a new reader, nothing shared.
    reopened = adapters.PostgresStopEpochStore(_dsn(), schema=postgres_epochs.schema)
    reader = fx.stop_reader(reopened)
    assert (reader.epoch, reader.emergency_stop_active()) == (1, True)
    record = reader.current_signed().record
    assert (record.sequence, record.status, record.actor) == (1, safety.StopStatus.STOPPING, fx.SAFETY_OFFICER)
    successor = fx.stop_controller(_registry(), epochs=reopened)
    successor.finish_draining(at=NOW)
    assert fx.stop_reader(postgres_epochs).status is safety.StopStatus.STOPPED


def test_ncr_c6_010_the_postgres_store_is_append_only_and_compare_and_set(postgres_epochs: Any) -> None:
    fx = _fx()
    adapters = importlib.import_module("ocor_runtime.c6.adapters.postgres_stop")
    controller = fx.stop_controller(_registry(), epochs=postgres_epochs)
    genesis = controller.reader.current_signed()
    assert postgres_epochs.append(genesis, expected_sequence=-1) is False
    assert postgres_epochs.append(genesis, expected_sequence=0) is False
    assert isinstance(adapters.PostgresStopEpochStore, type)
    psycopg = importlib.import_module("psycopg")
    for statement in (
        f"UPDATE {postgres_epochs.schema}.stop_epoch SET epoch = 9 WHERE sequence = 0",
        f"DELETE FROM {postgres_epochs.schema}.stop_epoch",
        f"TRUNCATE {postgres_epochs.schema}.stop_epoch",
    ):
        with pytest.raises(psycopg.Error), psycopg.connect(_dsn()) as connection:
            connection.execute(statement)
    assert [item.record.sequence for item in postgres_epochs.history()] == [0]
    assert fx.stop_reader(postgres_epochs).current_signed() == genesis


def test_ncr_c6_010_concurrent_activations_on_one_port_increment_the_epoch_once(postgres_epochs: Any) -> None:
    fx = _fx()
    safety = _safety()
    controllers = [fx.stop_controller(_registry(), epochs=postgres_epochs) for _ in range(4)]
    outcomes: list[str] = []
    barrier = threading.Barrier(len(controllers))

    def run(controller: Any) -> None:
        barrier.wait()
        try:
            fx.activate(controller, reason="incident-42", at=NOW)
            outcomes.append("ACTIVATED")
        except safety.SafetyError as error:
            outcomes.append(error.reason_code)

    threads = [threading.Thread(target=run, args=(controller,)) for controller in controllers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert sorted(outcomes) == ["ACTIVATED"] + ["INVALID_STOP_TRANSITION"] * 3
    assert [item.record.epoch for item in postgres_epochs.history()] == [0, 1]


def test_ncr_c6_010_g_dispatch_reads_the_stop_through_the_port() -> None:
    fx = _fx()
    safety = _safety()
    composition = _mod("c6.composition")
    epochs = safety.InMemoryStopEpochStore()
    controller = fx.stop_controller(_registry(), epochs=epochs)

    class _Releases:
        def active_release_digest(self) -> str:
            return "urn:sha256:" + "1" * 64

    fence = composition.EmergencyStopFence(stop=fx.stop_reader(epochs), releases=_Releases())
    dispatch = _mod("c6.dispatch")
    conditions = dispatch.InMemoryDispatchConditions(stop=fence)
    assert (conditions.current_stop_epoch(), conditions.emergency_stop_active()) == (0, False)
    fx.activate(controller, reason="incident-42", at=NOW)
    assert (conditions.current_stop_epoch(), conditions.emergency_stop_active()) == (1, True)


def test_ncr_c6_010_the_c8_tool_runtime_reads_the_stop_through_the_port() -> None:
    fx = _fx()
    safety = _safety()
    marking = _mod("c4_marking")
    capabilities = _mod("c6_capabilities")
    tool_runtime = _mod("c8.tool_runtime")
    agent = _mod("c8_agent")
    kernel = _mod("kernel.governed_context")
    epochs = safety.InMemoryStopEpochStore()
    controller = fx.stop_controller(_registry(), epochs=epochs)
    effects: list[str] = []
    sandbox = agent.StrictSandbox()

    def restart_service(name: str) -> str:
        effects.append(name)
        return name

    sandbox.register_tool("restart_service", restart_service)
    authority = capabilities.CapabilityAuthority(issuer="ocor-rem0054-tool-authority")
    engine = _mod("c4.marking_resolution").ResolvedMarkingEngine(
        [marking.MarkingSchemeDefinition("classification", levels=("UNCLASSIFIED", "SECRET"))])
    runtime = tool_runtime.ToolCallRuntime(sandbox=sandbox, authority=authority, marking_engine=engine, stop=fx.stop_reader(epochs))
    lease = authority.issue(subject="agent-1", capabilities=["tool:restart_service"], resources=["restart_service"], issued_at=NOW, ttl=timedelta(hours=1))
    context = kernel.GovernedContext(
        tenant_id="t1", organization_id="o1", domain_id="d1", compartments=("default",),
        classification_marking_ref="urn:sha256:" + "a" * 64, purpose="incident-response", effective_principal_id="agent-1",
        actor_chain=("agent-1",), ontology_release_digest="urn:sha256:" + "b" * 64, policy_bundle_digest="urn:sha256:" + "c" * 64,
        correlation_id="urn:ocor:correlation:rem0054",
    )

    def invoke(name: str) -> Any:
        return runtime.invoke(
            "restart_service", "restart_service(name)", bindings={"name": name}, lease=lease, context=context,
            content_marking=marking.MarkingSet({"classification": "SECRET"}), clearance=marking.MarkingSet({"classification": "SECRET"}),
            budget=agent.TokenBudget(100), estimated_tokens=1, stop_epoch=0, at=NOW,
        )

    invoke("before")
    fx.activate(controller, reason="incident-42", at=NOW)
    with pytest.raises(tool_runtime.ToolRuntimeError) as excinfo:
        invoke("after")
    assert excinfo.value.reason_code == "EMERGENCY_STOP_ACTIVE"
    assert effects == ["before"]


# --- NCR-C6-010: reset with dual control and incident/recovery verification (LLD v1.1 :328) ------


def test_ncr_c6_010_a_reset_with_verified_recovery_issues_a_new_signed_epoch() -> None:
    fx = _fx()
    safety = _safety()
    stop = fx.stop_controller(_registry())
    _stopped(stop)
    pending = stop.request_reset(approvers=(HUMAN_A, HUMAN_B), identities=_registry(), requester=HUMAN_C, recovery=fx.recovery((HUMAN_A, HUMAN_B)))
    assert pending.status is safety.StopStatus.RESET_PENDING
    record = stop.reader.current_signed().record
    assert (record.status, record.incident_ref, record.recovery_evidence, record.approvers) == (
        safety.StopStatus.RESET_PENDING, fx.INCIDENT, fx.RECOVERY_EVIDENCE, (HUMAN_A, HUMAN_B)
    )
    event = stop.confirm_reset(at=NOW)
    assert (event.epoch, stop.status) == (2, safety.StopStatus.NORMAL)
    with pytest.raises(safety.SafetyError) as excinfo:
        stop.guard_dispatch(fenced_epoch=1)
    assert _reason(excinfo) == "STOP_EPOCH_STALE"


@pytest.mark.parametrize(
    "change",
    [
        {"incident_ref": "urn:ocor:incident:other"},
        {"verified_by": HUMAN_C},
        {"verified_by": "urn:ocor:human:unknown"},
    ],
    ids=["other-incident", "verifier-not-an-approver", "unresolved-verifier"],
)
def test_ncr_c6_010_a_reset_without_a_matching_incident_and_recovery_verification_is_refused(change: dict[str, str]) -> None:
    fx = _fx()
    safety = _safety()
    stop = fx.stop_controller(_registry())
    _stopped(stop)
    verification = dataclasses.replace(fx.recovery((HUMAN_A, HUMAN_B)), **change)
    with pytest.raises(safety.SafetyError) as excinfo:
        stop.request_reset(approvers=(HUMAN_A, HUMAN_B), identities=_registry(), requester=HUMAN_C, recovery=verification)
    assert _reason(excinfo) == "RESET_RECOVERY_NOT_VERIFIED"
    assert stop.status is safety.StopStatus.STOPPED


@pytest.mark.parametrize("evidence", ["", "sha256:" + "0" * 64, "urn:sha256:" + "0" * 63, "urn:sha256:" + "G" * 64, None])
def test_ncr_c6_010_a_recovery_verification_needs_a_content_addressed_evidence(evidence: object) -> None:
    fx = _fx()
    with pytest.raises((ValueError, TypeError)):
        fx.recovery((HUMAN_A, HUMAN_B), evidence=evidence)


def test_ncr_c6_010_a_reset_without_recovery_verification_is_refused() -> None:
    fx = _fx()
    stop = fx.stop_controller(_registry())
    _stopped(stop)
    with pytest.raises(TypeError):
        stop.request_reset(approvers=(HUMAN_A, HUMAN_B), identities=_registry(), requester=HUMAN_C)
    with pytest.raises(_safety().SafetyError) as excinfo:
        stop.request_reset(approvers=(HUMAN_A, HUMAN_B), identities=_registry(), requester=HUMAN_C, recovery=None)
    assert _reason(excinfo) == "RESET_RECOVERY_NOT_VERIFIED"


# --- NCR-C6-010: break-glass is a signed Delegation with a typed reason (ADD v1.3 :3347, LLD :324) -


class _Sink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def record(self, event: Any) -> None:
        self.events.append(dict(event))

    def alert(self, event: Any) -> None:
        self.events.append(dict(event))


def _break_glass() -> tuple[Any, Any]:
    fx = _fx()
    governance = _mod("kernel.governance")
    stop = fx.stop_controller(_registry())
    sink = _Sink()
    controller = fx.break_glass_controller(
        identities=_registry(), stop=stop, clock=governance.InMemoryTrustedClock(NOW), audit=sink, alerts=_Sink()
    )
    return controller, sink


def _grant(controller: Any, **overrides: Any) -> Any:
    arguments: dict[str, Any] = {
        "grant_id": f"urn:ocor:break-glass:{uuid.uuid4()}",
        "requester": REQUESTER,
        "reason": "production-incident",
        "incident_ref": "urn:ocor:incident:42",
        "scope": "urn:ocor:target:site-1",
        "domain": DOMAIN,
        "capabilities": frozenset({"restart_service"}),
        "approvers": (SDO, OWNER),
        "ttl": timedelta(minutes=10),
    }
    arguments.update(overrides)
    return controller.grant(**arguments)


def test_ncr_c6_010_a_break_glass_grant_is_a_delegation_signed_by_the_break_glass_authority() -> None:
    fx = _fx()
    safety = _safety()
    controller, _ = _break_glass()
    grant = _grant(controller)
    assert (grant.issuer_id, grant.keyid) == (fx.BREAK_GLASS_AUTHORITY, fx.BREAK_GLASS_KEYID)
    assert base64.b64decode(grant.signature, validate=True)
    assert safety.verify_break_glass_grant(grant, keyring=fx.keyring(), issuer_id=fx.BREAK_GLASS_AUTHORITY) is None
    use = controller.authorize(grant, capability="restart_service", review_ref="urn:ocor:review:1")
    assert use.grant_id == grant.grant_id


@pytest.mark.parametrize(
    "change",
    [
        {"reason": "other-incident"},
        {"incident_ref": "urn:ocor:incident:other"},
        {"scope": "urn:ocor:target:everything"},
        {"capabilities": frozenset({"restart_service", "read_diagnostics"})},
        {"ttl": timedelta(minutes=15)},
        {"approvers": (OWNER, "urn:ocor:human:z")},
        {"granted_at": NOW + timedelta(minutes=1)},
        {"issuer_id": "urn:ocor:other-authority"},
    ],
    ids=["reason", "incident", "scope", "capabilities", "ttl", "approvers", "granted_at", "issuer"],
)
def test_ncr_c6_010_the_break_glass_signature_covers_every_field(change: dict[str, Any]) -> None:
    fx = _fx()
    safety = _safety()
    controller, _ = _break_glass()
    altered = dataclasses.replace(_grant(controller), **change)
    with pytest.raises(safety.SafetyError) as excinfo:
        safety.verify_break_glass_grant(altered, keyring=fx.keyring(), issuer_id=fx.BREAK_GLASS_AUTHORITY)
    assert _reason(excinfo) == "BREAK_GLASS_SIGNATURE_INVALID"


def test_ncr_c6_010_an_unsigned_or_foreign_signed_grant_never_verifies() -> None:
    fx = _fx()
    safety = _safety()
    controller, _ = _break_glass()
    grant = _grant(controller)
    for forged in (
        dataclasses.replace(grant, signature=""),
        dataclasses.replace(grant, signature="%%%"),
        dataclasses.replace(grant, keyid="unknown-key"),
        safety.sign_break_glass_grant(fx.signing_key("forger"), issuer_id=fx.BREAK_GLASS_AUTHORITY, keyid=fx.BREAK_GLASS_KEYID, grant=grant),
    ):
        with pytest.raises(safety.SafetyError) as excinfo:
            safety.verify_break_glass_grant(forged, keyring=fx.keyring(), issuer_id=fx.BREAK_GLASS_AUTHORITY)
        assert _reason(excinfo) == "BREAK_GLASS_SIGNATURE_INVALID"


@pytest.mark.parametrize(
    "reason",
    ["incident containment", "Production-Incident", "-incident", "incident-", "incident--42", "x" * 65, "incident\n42"],
    ids=["free-text", "upper", "leading-dash", "trailing-dash", "double-dash", "too-long", "newline"],
)
def test_ncr_c6_010_a_break_glass_reason_is_typed_never_free_text(reason: str) -> None:
    safety = _safety()
    controller, sink = _break_glass()
    with pytest.raises(safety.SafetyError) as excinfo:
        _grant(controller, reason=reason)
    assert _reason(excinfo) == "BREAK_GLASS_REASON_UNTYPED"
    assert [event["event"] for event in sink.events] == ["BREAK_GLASS_GRANT_DENIED"]
    assert sink.events[0]["reason_code"] == "BREAK_GLASS_REASON_UNTYPED"


def test_ncr_c6_010_the_break_glass_controller_requires_its_signing_authority() -> None:
    safety = _safety()
    governance = _mod("kernel.governance")
    stop = _fx().stop_controller(_registry())
    with pytest.raises(TypeError):
        safety.BreakGlassController(
            identities=_registry(), stop=stop, clock=governance.InMemoryTrustedClock(NOW), audit=_Sink(), alerts=_Sink()
        )


def test_ncr_c6_010_break_glass_never_overrides_a_stop_read_through_the_port() -> None:
    fx = _fx()
    safety = _safety()
    governance = _mod("kernel.governance")
    epochs = safety.InMemoryStopEpochStore()
    activator = fx.stop_controller(_registry(), epochs=epochs)
    controller = fx.break_glass_controller(
        identities=_registry(), stop=fx.stop_reader(epochs), clock=governance.InMemoryTrustedClock(NOW), audit=_Sink(), alerts=_Sink()
    )
    grant = _grant(controller)
    fx.activate(activator, reason="incident-42", at=NOW)
    with pytest.raises(safety.SafetyError) as excinfo:
        controller.authorize(grant, capability="restart_service", review_ref="urn:ocor:review:1")
    assert _reason(excinfo) == "BREAK_GLASS_STOP_ACTIVE"


# --- NCR-C6-010: input robustness of the stop epoch, reset and break-glass paths -----------------
# (NCP-THROUGHPUT-RULES point 1 self-check: data shape without conversion, typed errors, tampered
# data refused, boundary signatures re-verified, one negative test per parsing path.)


class _RefusingHistory:
    """A stop-epoch port whose history read is refused by the adapter with a typed error."""

    def __init__(self, inner: Any, error: BaseException) -> None:
        self._inner = inner
        self._error = error

    def latest(self) -> Any:
        return self._inner.latest()

    def history(self) -> Any:
        raise self._error

    def append(self, signed: Any, *, expected_sequence: int) -> bool:
        return bool(self._inner.append(signed, expected_sequence=expected_sequence))


def test_ncr_c6_010_a_typed_refusal_of_the_port_history_keeps_its_reason() -> None:
    fx = _fx()
    safety = _safety()
    epochs = safety.InMemoryStopEpochStore()
    fx.stop_controller(_registry(), epochs=epochs)
    malformed = safety.SafetyError("STOP_EPOCH_SIGNATURE_INVALID", "a stored stop epoch is malformed")
    with pytest.raises(safety.SafetyError) as excinfo:
        fx.stop_reader(_RefusingHistory(epochs, malformed)).history
    assert _reason(excinfo) == "STOP_EPOCH_SIGNATURE_INVALID"
    with pytest.raises(safety.SafetyError) as excinfo:
        fx.stop_reader(_RefusingHistory(epochs, RuntimeError("connection reset"))).history
    assert _reason(excinfo) == "STOP_EPOCH_UNAVAILABLE"


class _Incomparable:
    def __eq__(self, other: object) -> bool:
        raise RuntimeError("not comparable")

    def __ne__(self, other: object) -> bool:
        raise RuntimeError("not comparable")

    __hash__ = None  # type: ignore[assignment]


@pytest.mark.parametrize("fenced", [_Incomparable(), True, 0.0, "0", None], ids=["incomparable", "bool", "float", "str", "none"])
def test_ncr_c6_010_a_fenced_epoch_that_is_not_an_integer_is_stale(fenced: object) -> None:
    fx = _fx()
    safety = _safety()
    epochs = safety.InMemoryStopEpochStore()
    fx.stop_controller(_registry(), epochs=epochs)
    reader = fx.stop_reader(epochs)
    assert reader.epoch == 0
    with pytest.raises(safety.SafetyError) as excinfo:
        reader.guard_dispatch(fenced_epoch=fenced)
    assert _reason(excinfo) == "STOP_EPOCH_STALE"
    reader.guard_dispatch(fenced_epoch=0)


class _RevocableKeyring:
    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.revoked: set[tuple[str, str]] = set()

    def public_key(self, principal_id: str, keyid: str) -> bytes | None:
        if (principal_id, keyid) in self.revoked:
            return None
        return self._inner.public_key(principal_id, keyid)  # type: ignore[no-any-return]


def test_ncr_c6_010_a_reader_never_honours_a_signature_whose_key_the_keyring_no_longer_holds() -> None:
    fx = _fx()
    safety = _safety()
    epochs = safety.InMemoryStopEpochStore()
    fx.stop_controller(_registry(), epochs=epochs)
    keyring = _RevocableKeyring(fx.keyring())
    reader = safety.StopEpochReader(epochs=epochs, keyring=keyring, issuer_id=fx.CONTROL_PLANE)
    assert reader.epoch == 0
    keyring.revoked.add((fx.CONTROL_PLANE, fx.CONTROL_PLANE_KEYID))
    for read in (lambda: reader.epoch, lambda: reader.history):
        with pytest.raises(safety.SafetyError) as excinfo:
            read()
        assert _reason(excinfo) == "STOP_EPOCH_SIGNATURE_INVALID"


@pytest.mark.parametrize(
    "approvers,requester",
    [
        ("ab", HUMAN_C),
        ([HUMAN_A, HUMAN_B], HUMAN_C),
        ((HUMAN_A, ["unhashable"]), HUMAN_C),
        ((HUMAN_A, 42), HUMAN_C),
        (None, HUMAN_C),
        ((HUMAN_A, HUMAN_B), 42),
        ((HUMAN_A, HUMAN_B), None),
        ((HUMAN_A, HUMAN_B), ("urn:ocor:human:c",)),
    ],
    ids=["approvers-str", "approvers-list", "approver-unhashable", "approver-int", "approvers-none",
         "requester-int", "requester-none", "requester-tuple"],
)
def test_ncr_c6_010_a_reset_with_malformed_approvers_or_requester_is_the_dual_control_refusal(
    approvers: object, requester: object
) -> None:
    fx = _fx()
    safety = _safety()
    stop = fx.stop_controller(_registry())
    _stopped(stop)
    before = stop.history
    with pytest.raises(safety.SafetyError) as excinfo:
        stop.request_reset(approvers=approvers, identities=_registry(), requester=requester, recovery=fx.recovery((HUMAN_A, HUMAN_B)))
    assert _reason(excinfo) == "RESET_REQUIRES_DUAL_CONTROL"
    assert stop.status is safety.StopStatus.STOPPED
    assert stop.history == before


def test_ncr_c6_010_a_reset_whose_approver_cannot_be_read_is_the_dual_control_refusal() -> None:
    fx = _fx()
    safety = _safety()

    class _Unreadable:
        def get(self, canonical_id: str) -> Any:
            raise RuntimeError("identity registry unreachable")

    class _NotARecord:
        def get(self, canonical_id: str) -> Any:
            return {"principal_kind": "HUMAN", "status": "ACTIVE", "roles": ""}

    for identities in (_Unreadable(), _NotARecord()):
        stop = fx.stop_controller(_registry())
        _stopped(stop)
        with pytest.raises(safety.SafetyError) as excinfo:
            stop.request_reset(approvers=(HUMAN_A, HUMAN_B), identities=identities, requester=HUMAN_C,
                               recovery=fx.recovery((HUMAN_A, HUMAN_B)))
        assert _reason(excinfo) == "RESET_REQUIRES_DUAL_CONTROL"
        assert stop.status is safety.StopStatus.STOPPED


@pytest.mark.parametrize(
    "change",
    [
        {"capabilities": "restart_service"},
        {"capabilities": ["restart_service"]},
        {"capabilities": frozenset({"restart_service", 42})},
        {"approvers": SDO},
        {"approvers": [SDO, OWNER]},
        {"approvers": (SDO, 42)},
        {"grant_id": 42},
        {"incident_ref": ("urn:ocor:incident:42",)},
        {"scope": b"urn:ocor:target:site-1"},
        {"domain": 7},
    ],
    ids=["capabilities-str", "capabilities-list", "capability-int", "approvers-str", "approvers-list", "approver-int",
         "grant-id-int", "incident-tuple", "scope-bytes", "domain-int"],
)
def test_ncr_c6_010_a_break_glass_request_of_the_wrong_shape_is_refused_and_audited(change: dict[str, Any]) -> None:
    safety = _safety()
    controller, sink = _break_glass()
    with pytest.raises(safety.SafetyError) as excinfo:
        _grant(controller, **change)
    assert _reason(excinfo) == "BREAK_GLASS_GRANT_INVALID"
    assert [event["event"] for event in sink.events] == ["BREAK_GLASS_GRANT_DENIED"]
    assert sink.events[0]["reason_code"] == "BREAK_GLASS_GRANT_INVALID"


@pytest.mark.parametrize("ttl", [600, "PT10M", None], ids=["int", "str", "none"])
def test_ncr_c6_010_a_break_glass_ttl_that_is_not_a_duration_is_refused_and_audited(ttl: object) -> None:
    controller, sink = _break_glass()
    with pytest.raises(ValueError):
        _grant(controller, ttl=ttl)
    assert [event["event"] for event in sink.events] == ["BREAK_GLASS_GRANT_DENIED"]
    assert sink.events[0]["reason_code"] == "BREAK_GLASS_GRANT_INVALID"


@pytest.mark.parametrize(
    "change",
    [
        {"capabilities": "restart_service"},
        {"approvers": [OWNER, SDO]},
        {"grant_id": 42},
        {"ttl": 600},
        {"keyid": None},
        {"signature": b"c2ln"},
    ],
    ids=["capabilities-str", "approvers-list", "grant-id-int", "ttl-int", "keyid-none", "signature-bytes"],
)
def test_ncr_c6_010_a_break_glass_grant_of_the_wrong_shape_is_never_built(change: dict[str, Any]) -> None:
    safety = _safety()
    fields: dict[str, Any] = {
        "grant_id": "urn:ocor:break-glass:1",
        "requester": REQUESTER,
        "reason": "production-incident",
        "incident_ref": "urn:ocor:incident:42",
        "scope": "urn:ocor:target:site-1",
        "domain": DOMAIN,
        "capabilities": frozenset({"restart_service"}),
        "approvers": (OWNER, SDO),
        "granted_at": NOW,
        "ttl": timedelta(minutes=10),
    }
    safety.BreakGlassGrant(**fields)
    fields.update(change)
    with pytest.raises(ValueError):
        safety.BreakGlassGrant(**fields)


@pytest.mark.parametrize(
    "capability,review_ref,reason",
    [
        (["restart_service"], "urn:ocor:review:1", "BREAK_GLASS_CAPABILITY_NOT_GRANTED"),
        (None, "urn:ocor:review:1", "BREAK_GLASS_CAPABILITY_NOT_GRANTED"),
        ("restart_service", 42, "BREAK_GLASS_REVIEW_REQUIRED"),
        ("restart_service", ["urn:ocor:review:1"], "BREAK_GLASS_REVIEW_REQUIRED"),
    ],
    ids=["capability-list", "capability-none", "review-int", "review-list"],
)
def test_ncr_c6_010_a_break_glass_use_of_the_wrong_shape_is_refused_and_audited(
    capability: object, review_ref: object, reason: str
) -> None:
    safety = _safety()
    controller, sink = _break_glass()
    grant = _grant(controller)
    sink.events.clear()
    with pytest.raises(safety.SafetyError) as excinfo:
        controller.authorize(grant, capability=capability, review_ref=review_ref)
    assert _reason(excinfo) == reason
    assert [event["event"] for event in sink.events] == ["BREAK_GLASS_USE_DENIED"]
    controller.authorize(grant, capability="restart_service", review_ref="urn:ocor:review:1")


@pytest.mark.parametrize("grant", [None, "urn:ocor:break-glass:1", {"grant_id": "urn:ocor:break-glass:1"}], ids=["none", "str", "mapping"])
def test_ncr_c6_010_something_other_than_a_grant_is_never_issued(grant: object) -> None:
    safety = _safety()
    controller, sink = _break_glass()
    with pytest.raises(safety.SafetyError) as excinfo:
        controller.authorize(grant, capability="restart_service", review_ref="urn:ocor:review:1")
    assert _reason(excinfo) == "BREAK_GLASS_GRANT_NOT_ISSUED"
    assert [event["event"] for event in sink.events] == ["BREAK_GLASS_USE_DENIED"]
    with pytest.raises(safety.SafetyError) as excinfo:
        controller.revoke(grant)
    assert _reason(excinfo) == "BREAK_GLASS_GRANT_NOT_ISSUED"
# Preventive review OCOR-DEV-REM-0054-05049b13ee05-pre: a stop epoch read back from a store is
# rebuilt only from text, integers and lists of the declared shape; the PostgreSQL adapter turns
# every malformed row into STOP_EPOCH_SIGNATURE_INVALID and every driver failure into
# STOP_EPOCH_UNAVAILABLE, closing its connection on each path.


def _stored_mapping() -> dict[str, Any]:
    fx = _fx()
    stop = fx.stop_controller(_registry())
    _stopped(stop)
    stop.request_reset(approvers=(HUMAN_A, HUMAN_B), identities=_registry(), requester=HUMAN_C, recovery=fx.recovery((HUMAN_A, HUMAN_B)))
    signed = stop.reader.current_signed()
    assert signed.record.recovery_evidence == fx.RECOVERY_EVIDENCE
    return dict(signed.to_mapping())


@pytest.mark.parametrize("evidence", [None, False, 0, [], {}, b""], ids=["none", "false", "zero", "list", "dict", "bytes"])
def test_ncr_c6_010_a_stop_epoch_record_whose_recovery_evidence_is_not_text_is_never_built(evidence: object) -> None:
    safety = _safety()
    document = _stored_mapping()
    record = safety.StopEpochRecord.from_mapping(document["record"])
    with pytest.raises(ValueError):
        dataclasses.replace(record, recovery_evidence=evidence)
    with pytest.raises(ValueError):
        safety.StopEpochRecord.from_mapping({**document["record"], "recovery_evidence": evidence})
    with pytest.raises(ValueError):
        safety.SignedStopEpoch.from_mapping({**document, "record": {**document["record"], "recovery_evidence": evidence}})


@pytest.mark.parametrize(
    "change",
    [
        {"sequence": True},
        {"sequence": "4"},
        {"epoch": 1.0},
        {"status": "stopped"},
        {"status": None},
        {"actor": None},
        {"reason": 7},
        {"incident_ref": None},
        {"at": "2026-11-06 09:00:00"},
        {"at": 0},
        {"approvers": "ab"},
        {"approvers": [HUMAN_A, 42]},
        {"recovery_evidence": "urn:sha256:not-a-digest"},
        {"extra": "field"},
    ],
    ids=["sequence-bool", "sequence-str", "epoch-float", "status-unknown", "status-none", "actor-none", "reason-int",
         "incident-none", "at-not-canonical", "at-int", "approvers-str", "approver-int", "evidence-not-digest", "extra-field"],
)
def test_ncr_c6_010_a_stored_stop_epoch_record_of_the_wrong_shape_is_refused(change: dict[str, Any]) -> None:
    safety = _safety()
    record = _stored_mapping()["record"]
    safety.StopEpochRecord.from_mapping(record)
    with pytest.raises(ValueError):
        safety.StopEpochRecord.from_mapping({**record, **change})


@pytest.mark.parametrize(
    "change",
    [
        {"record": None},
        {"record": "{}"},
        {"issuer_id": 42},
        {"issuer_id": ""},
        {"keyid": None},
        {"signature": b"c2ln"},
        {"signature": ""},
        {"extra": "field"},
    ],
    ids=["record-none", "record-str", "issuer-int", "issuer-empty", "keyid-none", "signature-bytes", "signature-empty", "extra-field"],
)
def test_ncr_c6_010_a_stored_signed_stop_epoch_of_the_wrong_shape_is_refused(change: dict[str, Any]) -> None:
    safety = _safety()
    document = _stored_mapping()
    safety.SignedStopEpoch.from_mapping(document)
    with pytest.raises(ValueError):
        safety.SignedStopEpoch.from_mapping({**document, **change})
    missing = dict(document)
    missing.pop("keyid")
    with pytest.raises(ValueError):
        safety.SignedStopEpoch.from_mapping(missing)


@pytest.mark.parametrize(
    "change",
    [{"record": None}, {"record": {"sequence": 0}}, {"issuer_id": 42}, {"keyid": None}, {"signature": b"c2ln"}],
    ids=["record-none", "record-mapping", "issuer-int", "keyid-none", "signature-bytes"],
)
def test_ncr_c6_010_a_signed_stop_epoch_of_the_wrong_shape_is_never_built(change: dict[str, Any]) -> None:
    signed = _fx().stop_controller(_registry()).reader.current_signed()
    with pytest.raises(ValueError):
        dataclasses.replace(signed, **change)


def _postgres_adapter() -> ModuleType:
    return importlib.import_module("ocor_runtime.c6.adapters.postgres_stop")


@pytest.mark.parametrize(
    "arguments",
    [
        {"dsn": ""},
        {"dsn": None},
        {"dsn": b"postgresql://localhost"},
        {"schema": "Upper"},
        {"schema": "x; DROP SCHEMA public"},
        {"schema": None},
        {"connect_timeout": 0},
        {"connect_timeout": True},
        {"connect_timeout": 5.0},
        {"connect_timeout": "5"},
    ],
    ids=["dsn-empty", "dsn-none", "dsn-bytes", "schema-upper", "schema-injection", "schema-none", "timeout-zero",
         "timeout-bool", "timeout-float", "timeout-str"],
)
def test_ncr_c6_010_the_postgres_store_refuses_malformed_settings(arguments: dict[str, Any]) -> None:
    adapters = _postgres_adapter()
    settings: dict[str, Any] = {"dsn": "postgresql://localhost/ocor", "schema": "ocor_c6_stop", "connect_timeout": 5}
    adapters.PostgresStopEpochStore(**settings)
    settings.update(arguments)
    with pytest.raises(ValueError):
        adapters.PostgresStopEpochStore(**settings)


def _row_cases() -> list[tuple[str, Any]]:
    document = _stored_mapping()
    sequence, epoch = document["record"]["sequence"], document["record"]["epoch"]
    malformed = {**document, "record": {**document["record"], "recovery_evidence": None}}
    return [
        ("not-a-mapping", [sequence, epoch, document]),
        ("none", None),
        ("signed-missing", {"sequence": sequence, "epoch": epoch}),
        ("signed-not-a-mapping", {"sequence": sequence, "epoch": epoch, "signed": "{}"}),
        ("signed-malformed", {"sequence": sequence, "epoch": epoch, "signed": malformed}),
        ("sequence-bool", {"sequence": True, "epoch": epoch, "signed": document}),
        ("epoch-str", {"sequence": sequence, "epoch": str(epoch), "signed": document}),
        ("sequence-mismatch", {"sequence": sequence + 1, "epoch": epoch, "signed": document}),
        ("epoch-mismatch", {"sequence": sequence, "epoch": epoch + 1, "signed": document}),
    ]


def test_ncr_c6_010_a_malformed_stored_row_is_an_invalid_stop_epoch_never_an_empty_store() -> None:
    adapters = _postgres_adapter()
    safety = _safety()
    document = _stored_mapping()
    good = {"sequence": document["record"]["sequence"], "epoch": document["record"]["epoch"], "signed": document}
    assert adapters._signed(good) == safety.SignedStopEpoch.from_mapping(document)
    for case, row in _row_cases():
        with pytest.raises(safety.SafetyError) as excinfo:
            adapters._signed(row)
        assert _reason(excinfo) == "STOP_EPOCH_SIGNATURE_INVALID", case
    with pytest.raises(safety.SafetyError) as excinfo:
        adapters._row(("latest", 3))
    assert _reason(excinfo) == "STOP_EPOCH_SIGNATURE_INVALID"


class _FakeCursor:
    def __init__(self, result: Any) -> None:
        self._result = result

    def fetchone(self) -> Any:
        return self._result

    def fetchall(self) -> Any:
        return self._result


class _FakeConnection:
    """A psycopg connection stand-in: it returns the rows of the test, or raises the error of the
    test, and records whether its transaction and the connection were closed."""

    def __init__(self, result: Any = None, *, error: BaseException | None = None) -> None:
        self.result = result
        self.error = error
        self.closed = False
        self.transaction_closed = False

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *exc: object) -> None:
        self.closed = True

    def transaction(self) -> Any:
        connection = self

        class _Transaction:
            def __enter__(self) -> None:
                return None

            def __exit__(self, *exc: object) -> None:
                connection.transaction_closed = True

        return _Transaction()

    def execute(self, query: str, params: Any = None) -> _FakeCursor:
        if self.error is not None:
            raise self.error
        if "pg_advisory_xact_lock" in query:
            return _FakeCursor(None)
        return _FakeCursor(self.result)


def test_ncr_c6_010_the_postgres_store_turns_a_driver_failure_into_unavailable_and_closes_the_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapters = _postgres_adapter()
    safety = _safety()
    psycopg = adapters.psycopg
    signed = _fx().stop_controller(_registry()).reader.current_signed()
    store = adapters.PostgresStopEpochStore("postgresql://localhost/ocor", schema="ocor_rem0054_fake")

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(psycopg, "connect", refuse)
    for operation in (store.latest, store.history, store.initialize, lambda: store.append(signed, expected_sequence=-1)):
        with pytest.raises(adapters.StopEpochStoreError) as excinfo:
            operation()
        assert _reason(excinfo) == "STOP_EPOCH_UNAVAILABLE"
    for error in (psycopg.errors.DataError("bad data"), psycopg.InterfaceError("closed"), psycopg.errors.RaiseException("append-only")):
        connection = _FakeConnection(error=error)
        monkeypatch.setattr(psycopg, "connect", lambda *args, _c=connection, **kwargs: _c)
        for operation in (store.latest, store.history, lambda: store.append(signed, expected_sequence=-1)):
            with pytest.raises(safety.SafetyError) as excinfo:
                operation()
            assert _reason(excinfo) == "STOP_EPOCH_UNAVAILABLE"
        assert connection.closed and connection.transaction_closed


def test_ncr_c6_010_the_postgres_store_refuses_a_malformed_read_and_closes_the_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    adapters = _postgres_adapter()
    safety = _safety()
    psycopg = adapters.psycopg
    store = adapters.PostgresStopEpochStore("postgresql://localhost/ocor", schema="ocor_rem0054_fake")
    signed = _fx().stop_controller(_registry()).reader.current_signed()
    cases: list[tuple[str, Any, Any]] = [(f"latest-{case}", store.latest, row) for case, row in _row_cases() if row is not None]
    cases += [(f"history-{case}", store.history, [row]) for case, row in _row_cases()]
    cases += [
        ("history-not-a-list", store.history, ({"sequence": 0},)),
        ("append-not-a-mapping", lambda: store.append(signed, expected_sequence=-1), ("latest", None)),
        ("append-latest-bool", lambda: store.append(signed, expected_sequence=-1), {"latest": False}),
        ("append-latest-str", lambda: store.append(signed, expected_sequence=-1), {"latest": "-1"}),
    ]
    for case, operation, result in cases:
        connection = _FakeConnection(result)
        monkeypatch.setattr(psycopg, "connect", lambda *args, _c=connection, **kwargs: _c)
        with pytest.raises(safety.SafetyError) as excinfo:
            operation()
        assert _reason(excinfo) == "STOP_EPOCH_SIGNATURE_INVALID", case
        assert connection.closed and connection.transaction_closed, case
    empty = _FakeConnection(None)
    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: empty)
    assert store.latest() is None
    with pytest.raises(TypeError):
        store.append(signed.to_mapping(), expected_sequence=-1)
    with pytest.raises(TypeError):
        store.append(signed, expected_sequence=True)


# Preventive review OCOR-DEV-REM-0054-05049b13ee05-pre: a requester or a registry record of the
# wrong shape, and a registry that cannot be read, are typed refusals of the stop and of the
# break-glass, the latter always audited.


@pytest.mark.parametrize(
    "requester",
    [["unhashable"], {"k": "v"}, 42, None, b"urn:ocor:human:requester", (REQUESTER,)],
    ids=["list", "dict", "int", "none", "bytes", "tuple"],
)
def test_ncr_c6_010_a_break_glass_requester_that_is_not_a_principal_identifier_is_refused_and_audited(requester: object) -> None:
    safety = _safety()
    controller, sink = _break_glass()
    with pytest.raises(safety.SafetyError) as excinfo:
        _grant(controller, requester=requester)
    assert _reason(excinfo) == "BREAK_GLASS_GRANT_INVALID"
    assert [event["event"] for event in sink.events] == ["BREAK_GLASS_GRANT_DENIED"]
    assert sink.events[0]["reason_code"] == "BREAK_GLASS_GRANT_INVALID"


class _UnreadableDirectory:
    def get(self, canonical_id: str) -> Any:
        raise RuntimeError("identity registry unreachable")


class _MalformedDirectory:
    """A directory whose records are not registry records, or whose attributes are not a mapping."""

    def __init__(self, record: Any) -> None:
        self._record = record

    def get(self, canonical_id: str) -> Any:
        return self._record


def _broken_directories() -> list[Any]:
    attributes = {"principal_kind": "HUMAN", "status": "ACTIVE", "roles": "SAFETY_OFFICER"}

    class _NotAMapping:
        canonical_id = "urn:ocor:human:x"
        attributes = ("principal_kind", "HUMAN")

    record = _mod("c2_identity").IdentityRecord(canonical_id="urn:ocor:human:x", attributes=attributes)
    hollow = object.__new__(type(record))
    object.__setattr__(hollow, "canonical_id", "urn:ocor:human:x")
    object.__setattr__(hollow, "aliases", frozenset())
    object.__setattr__(hollow, "attributes", ["principal_kind", "HUMAN"])
    return [
        _UnreadableDirectory(),
        _MalformedDirectory(attributes),
        _MalformedDirectory(_NotAMapping()),
        _MalformedDirectory(hollow),
        _MalformedDirectory("urn:ocor:human:x"),
    ]


@pytest.mark.parametrize("index", range(5), ids=["unreadable", "mapping", "not-a-record", "attributes-list", "str"])
def test_ncr_c6_010_a_stop_activator_the_registry_cannot_read_is_unauthorized(index: int) -> None:
    fx = _fx()
    safety = _safety()
    directory = _broken_directories()[index]
    stop = safety.EmergencyStopController(
        epochs=safety.InMemoryStopEpochStore(), identities=directory, signing_key=fx.CONTROL_PLANE_KEY,
        issuer_id=fx.CONTROL_PLANE, keyid=fx.CONTROL_PLANE_KEYID, keyring=fx.keyring(),
    )
    with pytest.raises(safety.SafetyError) as excinfo:
        stop.activate(activator=fx.SAFETY_OFFICER, reason="incident-42", incident_ref=fx.INCIDENT, at=NOW)
    assert _reason(excinfo) == "STOP_ACTIVATOR_UNAUTHORIZED"
    assert stop.status is safety.StopStatus.NORMAL


class _Switchable:
    """The registry of the test until ``broken`` replaces it."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.broken: Any = None

    def get(self, canonical_id: str) -> Any:
        return (self.inner if self.broken is None else self.broken).get(canonical_id)


@pytest.mark.parametrize("index", range(5), ids=["unreadable", "mapping", "not-a-record", "attributes-list", "str"])
def test_ncr_c6_010_a_break_glass_principal_the_registry_cannot_read_is_refused_and_audited(index: int) -> None:
    fx = _fx()
    safety = _safety()
    governance = _mod("kernel.governance")
    directory = _Switchable(_registry())
    sink = _Sink()
    controller = fx.break_glass_controller(
        identities=directory, stop=fx.stop_controller(_registry()), clock=governance.InMemoryTrustedClock(NOW), audit=sink,
        alerts=_Sink(),
    )
    grant = _grant(controller)
    directory.broken = _broken_directories()[index]
    sink.events.clear()
    with pytest.raises(safety.SafetyError) as excinfo:
        controller.authorize(grant, capability="restart_service", review_ref="urn:ocor:review:1")
    assert _reason(excinfo) == "BREAK_GLASS_PRINCIPAL_ATTRIBUTES_INVALID"
    assert [(event["event"], event["reason_code"]) for event in sink.events] == [
        ("BREAK_GLASS_USE_DENIED", "BREAK_GLASS_PRINCIPAL_ATTRIBUTES_INVALID")
    ]
    sink.events.clear()
    with pytest.raises(safety.SafetyError) as excinfo:
        _grant(controller)
    assert _reason(excinfo) == "BREAK_GLASS_PRINCIPAL_ATTRIBUTES_INVALID"
    assert [(event["event"], event["reason_code"]) for event in sink.events] == [
        ("BREAK_GLASS_GRANT_DENIED", "BREAK_GLASS_PRINCIPAL_ATTRIBUTES_INVALID")
    ]


# --- NCR-C6-013: ADD v1.3 risk-class names and gates (ADD :3298-3305, :2193; LLD :16-18) --------

ADD_RISK_CLASSES = ["R0_READ", "R1_ANALYZE", "R2_CONTROLLED", "R3_HIGH_IMPACT"]


def test_ncr_c6_013_conforms() -> None:
    """The register's RED probe: the kernel RiskClass and the control-plane OperationClass names."""
    governance = _mod("kernel.governance")
    control_plane = _mod("security.control_plane")
    assert [member.name for member in governance.RiskClass] == ADD_RISK_CLASSES
    assert [member.name for member in control_plane.OperationClass] == ADD_RISK_CLASSES


@pytest.mark.parametrize("module,enum", [("kernel.governance", "RiskClass"), ("security.control_plane", "OperationClass")])
def test_ncr_c6_013_the_classes_are_the_add_names_in_impact_order_without_aliases(module: str, enum: str) -> None:
    kind = getattr(_mod(module), enum)
    # LLD v1.1 :18: no implicit correction through aliases -- __members__ also lists aliases.
    assert list(kind.__members__) == ADD_RISK_CLASSES
    assert [int(member) for member in kind] == [0, 1, 2, 3]
    for legacy in ("R0_INFORMATIONAL", "R1_LOW", "R1_DERIVE", "R2_MUTATE"):
        assert not hasattr(kind, legacy)


def test_ncr_c6_013_the_policy_input_carries_the_add_names() -> None:
    control_plane = _mod("security.control_plane")
    governance = _mod("kernel.governance")
    rows = []
    for level in range(4):
        invocation = control_plane.CapabilityInvocation(
            capability_id="urn:ocor:capability:rem0054", capability_version="1",
            effect_class=control_plane.OperationClass(level), risk_class=governance.RiskClass(level),
        )
        policy_input = invocation.to_policy_input()
        rows.append((policy_input["effect_class"], policy_input["risk_class"]))
    assert rows == [(name, name) for name in ADD_RISK_CLASSES]


@pytest.mark.parametrize("risk", ADD_RISK_CLASSES)
def test_ncr_c6_013_a_signed_action_type_carries_the_add_risk_class_on_the_wire(risk: str) -> None:
    fixture = importlib.import_module("c6_action_fixture")
    world = fixture.ActionWorld(now=NOW, release="urn:sha256:" + "1" * 64)
    action_type = world.action_type(f"urn:ocor:action-type:rem0054-{risk.lower()}", risk=risk, capability="act:launch")
    assert action_type.risk_class.name == risk
    assert action_type.to_mapping()["risk_class"] == risk


def test_ncr_c6_013_the_gates_are_those_of_add_v1_3() -> None:
    governance = _mod("kernel.governance")
    gate = _mod("c6.human_gate")
    risk = governance.RiskClass
    read, analyze, controlled, high = (gate.approval_requirement(getattr(risk, name)) for name in ADD_RISK_CLASSES)
    # R0_READ: Policy and Authority, no Approval; R1_ANALYZE: no mutation (ADD v1.3 :3302-3303).
    assert (read.mutation_admitted, read.quorum, analyze.mutation_admitted, analyze.quorum) == (False, 0, False, 0)
    # R2_CONTROLLED: one independent human approver (ADD v1.3 :3304), not the LLD R2_MUTATE gate.
    assert (controlled.mutation_admitted, controlled.quorum, controlled.required_roles) == (True, 1, frozenset())
    # R3_HIGH_IMPACT: two independent human approvers, Domain and National (ADD v1.3 :3305, :3338).
    assert (high.mutation_admitted, high.quorum, high.required_roles) == (
        True, 2, frozenset({gate.DOMAIN_APPROVER, gate.NATIONAL_APPROVER})
    )
    for name in ("R0_READ", "R1_ANALYZE"):
        with pytest.raises(gate.ApprovalGateError) as excinfo:
            gate.gate_disposition(getattr(risk, name), canonical_target=True)
        assert _reason(excinfo) == "NO_MUTATION_ADMITTED"


# --- NCR-C6-011: the five policy effects (ADD v1.3 :3141, Register FR-130 :295) ----------------

_M0048_PATH = importlib.import_module("pathlib").Path(__file__).resolve().parent / "test_ocor_dev_0048.py"
_SPEC = importlib.util.spec_from_file_location("ocor_dev_0048_fixtures_for_rem0054", _M0048_PATH)
assert _SPEC is not None and _SPEC.loader is not None
m0048 = importlib.util.module_from_spec(_SPEC)
importlib.import_module("sys").modules[_SPEC.name] = m0048
_SPEC.loader.exec_module(m0048)

# Real-backend fixtures of the sealed OCOR-DEV-0048 module, reused unmodified.
env = m0048.env
live_stack = m0048.live_stack
admin_token = m0048.admin_token
principals = m0048.principals
mtls = m0048.mtls
principal = m0048.principal


def _provider(mtls: dict[str, object]) -> Any:
    control_plane = _mod("security.control_plane")
    return control_plane.OpaPolicyDecisionProvider(
        str(mtls["opa"]), m0048.POLICY_ID, signer_public_key=(m0048._SIGNER_N, m0048._SIGNER_E),
        ssl_context=mtls["ssl_context"],
    )


def _bundle(principal_id: str, *qualifiers: str, allow: bool = True) -> str:
    rule = (
        "allow if {\n"
        f'    input.principal_id == "{principal_id}"\n'
        '    input.resource == "urn:ocor:target:site-1"\n'
        "}\n"
    ) if allow else ""
    return "package ocor.control_plane\n\ndefault allow := false\n\n" + rule + "".join(f"\n{item}\n" for item in qualifiers)


def _decide(mtls: dict[str, object], principal: Any, *qualifiers: str, allow: bool = True, action: str = "read") -> Any:
    provider = _provider(mtls)
    digest = provider.install_policy(m0048._sign_bundle(_bundle(principal.principal_id, *qualifiers, allow=allow)))
    return provider.evaluate(m0048._policy_request(principal, digest, action=action))


def test_ncr_c6_011_conforms(principal: Any, mtls: dict[str, object]) -> None:
    """The register's RED probe: the decision point produces more than PERMIT and DENY, with the
    obligations of the signed policy."""
    ports = _mod("security.ports")
    decision = _decide(mtls, principal, 'obligations contains "audit:access" if input.action == "read"')
    assert (decision.effect, decision.obligations) == (ports.PolicyEffect.OBLIGATE, ("audit:access",))


@pytest.mark.parametrize(
    "rule,effect,qualification",
    [
        ('constraints contains "mask:pii" if input.action == "read"', "PERMIT_WITH_CONSTRAINTS", ("mask:pii",)),
        ('approval_requirements contains "approval:domain-owner" if input.action == "read"', "REQUIRE_APPROVAL",
         ("approval:domain-owner",)),
        ('obligations contains "audit:access" if input.action == "read"\nobligations contains "notify:owner" if input.action == "read"',
         "OBLIGATE", ("audit:access", "notify:owner")),
    ],
    ids=["permit-with-constraints", "require-approval", "obligate"],
)
def test_ncr_c6_011_the_signed_policy_produces_each_qualified_effect(
    principal: Any, mtls: dict[str, object], rule: str, effect: str, qualification: tuple[str, ...]
) -> None:
    decision = _decide(mtls, principal, rule)
    assert (decision.effect.value, decision.obligations) == (effect, qualification)


def test_ncr_c6_011_a_permit_without_qualification_stays_permit_and_a_deny_drops_it(principal: Any, mtls: dict[str, object]) -> None:
    ports = _mod("security.ports")
    rule = 'constraints contains "mask:pii" if input.action == "read"'
    unqualified = _decide(mtls, principal, rule, action="list")
    assert (unqualified.effect, unqualified.obligations) == (ports.PolicyEffect.PERMIT, ())
    denied = _decide(mtls, principal, rule, allow=False)
    assert (denied.effect, denied.obligations) == (ports.PolicyEffect.DENY, ())


@pytest.mark.parametrize(
    "rules",
    [
        ('constraints contains "mask:pii" if input.action == "read"', 'obligations contains "audit:access" if input.action == "read"'),
        ('approval_requirements contains "approval:x" if input.action == "read"', 'constraints contains "mask:pii" if input.action == "read"'),
        ('constraints := "mask:pii"',),
        ("constraints := [1]",),
        ('obligations := ["audit:access", "audit:access"]',),
        ('obligations := [""]',),
        ('approval_requirements := {"approval": true}',),
    ],
    ids=["constraints-and-obligations", "approval-and-constraints", "text", "number", "duplicate", "empty", "object"],
)
def test_ncr_c6_011_an_ambiguous_or_malformed_qualification_is_not_a_decision(
    principal: Any, mtls: dict[str, object], rules: tuple[str, ...]
) -> None:
    ports = _mod("security.ports")
    with pytest.raises(ports.SecurityControlError) as excinfo:
        _decide(mtls, principal, *rules)
    assert _reason(excinfo) == "POLICY_DECISION_INVALID"


def test_ncr_c6_011_a_consumer_admits_a_decision_only_when_it_honours_its_qualification(principal: Any, mtls: dict[str, object]) -> None:
    ports = _mod("security.ports")
    constrained = _decide(mtls, principal, 'constraints contains "mask:pii" if input.action == "read"')
    approval = _decide(mtls, principal, 'approval_requirements contains "approval:domain-owner" if input.action == "read"')
    obligated = _decide(mtls, principal, 'obligations contains "audit:access" if input.action == "read"')
    denied = _decide(mtls, principal, allow=False)
    permitted = _decide(mtls, principal)
    cases = [
        (denied, {}, "POLICY_DENIED"),
        (constrained, {}, "POLICY_CONSTRAINT_NOT_ENFORCED"),
        (constrained, {"enforced_constraints": frozenset({"mask:other"})}, "POLICY_CONSTRAINT_NOT_ENFORCED"),
        (approval, {}, "APPROVAL_REQUIRED"),
        (approval, {"granted_approvals": frozenset({"approval:other"})}, "APPROVAL_REQUIRED"),
        (obligated, {}, "POLICY_OBLIGATION_NOT_FULFILLED"),
        (obligated, {"fulfilled_obligations": frozenset({"audit:other"})}, "POLICY_OBLIGATION_NOT_FULFILLED"),
    ]
    for decision, honoured, reason in cases:
        with pytest.raises(ports.SecurityControlError) as excinfo:
            decision.admit(**honoured)
        assert _reason(excinfo) == reason
    permitted.admit()
    constrained.admit(enforced_constraints=frozenset({"mask:pii"}))
    approval.admit(granted_approvals=frozenset({"approval:domain-owner"}))
    obligated.admit(fulfilled_obligations=frozenset({"audit:access"}))
    # An unqualified permit admits nothing more than it says: honouring extras changes nothing.
    permitted.admit(enforced_constraints=frozenset({"mask:pii"}))


def _decision(effect: Any, obligations: object) -> Any:
    ports = _mod("security.ports")
    digest = "urn:sha256:" + "c" * 64
    return ports.PolicyDecision(
        decision_id="urn:ocor:policy-decision:rem0054",
        effect=effect,
        principal_id="urn:ocor:principal:rem0054",
        action="read",
        resource="urn:ocor:resource:rem0054",
        purpose="incident-response",
        governed_context_digest="urn:sha256:" + "d" * 64,
        policy_bundle_digest=digest,
        evaluated_at=NOW,
        valid_until=NOW + timedelta(minutes=5),
        obligations=obligations,  # type: ignore[arg-type]
        status=ports.ControlStatus.available(ports.ControlName.POLICY, observed_at=NOW, source_digest=digest),
    )


@pytest.mark.parametrize(
    "obligations",
    ["audit:access", ["audit:access"], frozenset({"audit:access"}), None, ("audit:access", 42)],
    ids=["str", "list", "frozenset", "none", "item-int"],
)
def test_ncr_c6_011_a_decision_whose_qualifiers_are_not_a_tuple_of_strings_is_invalid(obligations: object) -> None:
    ports = _mod("security.ports")
    assert _decision(ports.PolicyEffect.OBLIGATE, ("audit:access",)).obligations == ("audit:access",)
    with pytest.raises(ports.SecurityControlError) as excinfo:
        _decision(ports.PolicyEffect.OBLIGATE, obligations)
    assert _reason(excinfo) == "POLICY_DECISION_INVALID"


@pytest.mark.parametrize(
    "honoured",
    [
        {"fulfilled_obligations": {"audit:access"}},
        {"fulfilled_obligations": "audit:access"},
        {"granted_approvals": frozenset({""})},
        {"enforced_constraints": frozenset({42})},
    ],
    ids=["set", "str", "empty-item", "int-item"],
)
def test_ncr_c6_011_a_consumer_states_what_it_honours_as_a_set_of_names(honoured: dict[str, Any]) -> None:
    ports = _mod("security.ports")
    obligated = _decision(ports.PolicyEffect.OBLIGATE, ("audit:access",))
    with pytest.raises(TypeError):
        obligated.admit(**honoured)
    obligated.admit(fulfilled_obligations=frozenset({"audit:access"}))
@pytest.mark.parametrize(
    "forge,reason",
    [
        (lambda status, body: (503, body), "POLICY_UNAVAILABLE"),
        (lambda status, body: (200, b"\xff\xfe"), "POLICY_DECISION_INVALID"),
        (lambda status, body: (200, b"not json"), "POLICY_DECISION_INVALID"),
        (lambda status, body: (200, b"[]"), "POLICY_DECISION_INVALID"),
        (lambda status, body: (200, b'{"result": ["allow"]}'), "POLICY_DECISION_INVALID"),
        (lambda status, body: (200, _rewrite(body, allow=False)), "POLICY_DECISION_INVALID"),
        (lambda status, body: (200, _rewrite(body, allow=None)), "POLICY_DECISION_INVALID"),
    ],
    ids=["http-503", "not-utf8", "not-json", "not-an-object", "result-not-an-object", "allow-false", "allow-missing"],
)
def test_ncr_c6_011_a_qualification_response_of_the_wrong_shape_is_not_a_decision(
    principal: Any, mtls: dict[str, object], monkeypatch: pytest.MonkeyPatch, forge: Any, reason: str
) -> None:
    """Preventive review OCOR-DEV-REM-0054-05049b13ee05-pre (advisory): the protocol paths of the
    qualification read of the signed package. Only that response is replaced; OPA answers every
    other request."""
    control_plane = _mod("security.control_plane")
    ports = _mod("security.ports")
    real = control_plane._request
    forged: list[str] = []

    def request(method: str, url: str, **kwargs: Any) -> tuple[int, bytes]:
        status, body = real(method, url, **kwargs)
        if url.endswith(f"{control_plane.OpaPolicyDecisionProvider._PACKAGE_PATH}?explain=full"):
            forged.append(url)
            return forge(status, body)  # type: ignore[no-any-return]
        return status, body

    monkeypatch.setattr(control_plane, "_request", request)
    with pytest.raises(ports.SecurityControlError) as excinfo:
        _decide(mtls, principal, 'obligations contains "audit:access" if input.action == "read"')
    assert _reason(excinfo) == reason
    assert len(forged) == 1


def _rewrite(body: bytes, *, allow: object) -> bytes:
    response = importlib.import_module("json").loads(body.decode())
    if allow is None:
        response["result"].pop("allow", None)
    else:
        response["result"]["allow"] = allow
    return importlib.import_module("json").dumps(response).encode()


# --- NCR-C6-012: MARKING_UNRESOLVED in the current components (LLD v1.1 :67; FR-131 :298; FR-006 :49)

FULL = {"classification": "SECRET", "compartment": "ALPHA"}
CLEARED = {"classification": "TOP_SECRET", "compartment": "ALL"}
UNRESOLVED_MARKINGS = [
    pytest.param({"classification": "SECRET"}, CLEARED, id="content-misses-a-scheme"),
    pytest.param(FULL, {"classification": "TOP_SECRET"}, id="clearance-misses-a-scheme"),
    pytest.param({}, CLEARED, id="content-names-no-scheme"),
    pytest.param({**FULL, "caveat": "NOFORN"}, CLEARED, id="content-names-an-unknown-scheme"),
    pytest.param({**FULL, "classification": "COSMIC"}, CLEARED, id="content-names-an-unknown-label"),
    pytest.param(FULL, {**CLEARED, "compartment": 1}, id="clearance-label-is-not-a-string"),
    pytest.param(FULL, {"classification": "TOP_SECRET", "compartment": "BRAVO"}, id="incomparable-compartments"),
]


def _lattices() -> tuple[Any, Any]:
    legacy = _mod("c4_marking")
    classification = legacy.MarkingSchemeDefinition("classification", levels=("UNCLASSIFIED", "SECRET", "TOP_SECRET"))
    compartment = legacy.MarkingSchemeDefinition(
        "compartment", labels=("NONE", "ALPHA", "BRAVO", "ALL"),
        relations=[("NONE", "ALPHA"), ("NONE", "BRAVO"), ("ALPHA", "ALL"), ("BRAVO", "ALL")],
    )
    return classification, compartment


def _resolving() -> Any:
    return _mod("c4.marking_resolution").ResolvedMarkingEngine(_lattices())


def _marks(values: dict[str, Any]) -> Any:
    return _mod("c4_marking").MarkingSet(values)


def _legacy_engine() -> Any:
    legacy = _mod("c4_marking")
    return legacy.MarkingEngine(_lattices())


def test_ncr_c6_012_conforms() -> None:
    """The register's RED probe: the C2 gateway and the C8 tool runtime no longer evaluate marking
    with the legacy ``MarkingEngine``, whose join defaults a missing scheme to the bottom and whose
    authorization ignores it; a missing scheme is ``MARKING_UNRESOLVED``."""
    for module in ("c2.gateway", "c8.tool_runtime"):
        assert not hasattr(_mod(module), "MarkingEngine")
    with pytest.raises(_mod("c4.marking").MarkingUnresolved) as excinfo:
        _resolving().join(_marks({"classification": "SECRET"}), _marks(FULL))
    assert _reason(excinfo) == "MARKING_UNRESOLVED"
    with pytest.raises(_mod("c4.marking").MarkingUnresolved):
        _resolving().authorized(_marks({"classification": "SECRET"}), _marks(CLEARED))
    # The legacy slice is unchanged (programme point 6): its defaults are still the ones the
    # current components no longer reach.
    legacy = _legacy_engine()
    assert legacy.join(_marks({"classification": "SECRET"}))["compartment"] == "NONE"
    assert legacy.is_authorized(_marks({"classification": "SECRET"}), _marks(CLEARED))


@pytest.mark.parametrize("content,clearance", UNRESOLVED_MARKINGS)
def test_ncr_c6_012_a_missing_unknown_or_incomparable_marking_is_unresolved(content: dict[str, Any], clearance: dict[str, Any]) -> None:
    with pytest.raises(_mod("c4.marking").MarkingUnresolved) as excinfo:
        _resolving().authorized(_marks(content), _marks(clearance))
    assert _reason(excinfo) == "MARKING_UNRESOLVED"


@pytest.mark.parametrize("value", [FULL, None, "SECRET", ("classification", "SECRET")])
def test_ncr_c6_012_a_marking_that_is_not_a_marking_set_is_unresolved(value: object) -> None:
    with pytest.raises(_mod("c4.marking").MarkingUnresolved):
        _resolving().resolve(value)


def test_ncr_c6_012_a_complete_marking_is_authorized_only_when_the_clearance_dominates_it() -> None:
    engine = _resolving()
    assert engine.authorized(_marks(FULL), _marks(CLEARED))
    assert engine.authorized(_marks(FULL), _marks(FULL))
    assert not engine.authorized(_marks(FULL), _marks({"classification": "UNCLASSIFIED", "compartment": "ALL"}))
    assert not engine.authorized(_marks(FULL), _marks({"classification": "TOP_SECRET", "compartment": "NONE"}))
    assert engine.resolve(_marks(FULL)).values == FULL


def test_ncr_c6_012_the_join_is_the_conservative_least_upper_bound_of_complete_markings() -> None:
    engine = _resolving()
    left, right = _marks(FULL), _marks({"classification": "UNCLASSIFIED", "compartment": "BRAVO"})
    joined = engine.join(left, right)
    assert dict(joined.values) == {"classification": "SECRET", "compartment": "ALL"}
    # FR-131: the derived marking is never less restrictive than any input.
    assert engine.authorized(left, joined) and engine.authorized(right, joined)
    assert dict(engine.join(left).values) == FULL


@pytest.mark.parametrize("partial", [
    pytest.param({"classification": "SECRET"}, id="missing-scheme"),
    pytest.param({**FULL, "compartment": "GAMMA"}, id="unknown-label"),
    pytest.param({**FULL, "caveat": "NOFORN"}, id="unknown-scheme"),
])
def test_ncr_c6_012_the_join_never_defaults_an_unresolved_marking_to_the_bottom(partial: dict[str, Any]) -> None:
    with pytest.raises(_mod("c4.marking").MarkingUnresolved):
        _resolving().join(_marks(FULL), _marks(partial))


def test_ncr_c6_012_the_join_of_no_marking_is_unresolved() -> None:
    with pytest.raises(_mod("c4.marking").MarkingUnresolved):
        _resolving().join()


def test_ncr_c6_012_the_engine_needs_distinct_validated_lattices() -> None:
    resolution = _mod("c4.marking_resolution")
    classification, _ = _lattices()
    for schemes in ([], [classification, classification]):
        with pytest.raises(_mod("c4.marking").MarkingSchemeError):
            resolution.ResolvedMarkingEngine(schemes)
    with pytest.raises(TypeError):
        resolution.ResolvedMarkingEngine([{"scheme_id": "classification", "levels": ["U"]}])


class _ToolWorld:
    """The C8 tool runtime on a resolving marking engine, the real capability authority, a stop
    reader and the strict sandbox, recording every effect."""

    def __init__(self, engine: Any) -> None:
        safety = _safety()
        capabilities = _mod("c6_capabilities")
        agent = _mod("c8_agent")
        kernel = _mod("kernel.governed_context")
        self.tool_runtime = _mod("c8.tool_runtime")
        self.effects: list[str] = []
        sandbox = agent.StrictSandbox()

        def restart_service(name: str) -> str:
            self.effects.append(name)
            return name

        sandbox.register_tool("restart_service", restart_service)
        epochs = safety.InMemoryStopEpochStore()
        _fx().stop_controller(_registry(), epochs=epochs)
        authority = capabilities.CapabilityAuthority(issuer="ocor-rem0054-marking-authority")
        self.runtime = self.tool_runtime.ToolCallRuntime(
            sandbox=sandbox, authority=authority, marking_engine=engine, stop=_fx().stop_reader(epochs))
        self.authority = authority
        self.budget = agent.TokenBudget(100)
        self.context = kernel.GovernedContext(
            tenant_id="t1", organization_id="o1", domain_id="d1", compartments=("default",),
            classification_marking_ref="urn:sha256:" + "a" * 64, purpose="incident-response", effective_principal_id="agent-1",
            actor_chain=("agent-1",), ontology_release_digest="urn:sha256:" + "b" * 64, policy_bundle_digest="urn:sha256:" + "c" * 64,
            correlation_id="urn:ocor:correlation:rem0054",
        )

    def invoke(self, content: Any, clearance: Any) -> Any:
        lease = self.authority.issue(subject="agent-1", capabilities=["tool:restart_service"], resources=["restart_service"],
                                     issued_at=NOW, ttl=timedelta(hours=1))
        return self.runtime.invoke(
            "restart_service", "restart_service(name)", bindings={"name": "svc"}, lease=lease, context=self.context,
            content_marking=content, clearance=clearance, budget=self.budget, estimated_tokens=1, stop_epoch=0, at=NOW,
        )


def test_ncr_c6_012_the_c8_tool_runtime_runs_a_call_whose_complete_marking_the_clearance_dominates() -> None:
    world = _ToolWorld(_resolving())
    receipt = world.invoke(_marks(FULL), _marks(CLEARED))
    assert receipt.result == "svc"
    assert world.effects == ["svc"]


@pytest.mark.parametrize("content,clearance", UNRESOLVED_MARKINGS)
def test_ncr_c6_012_the_c8_tool_runtime_refuses_an_unresolved_marking_before_any_effect(
        content: dict[str, Any], clearance: dict[str, Any]) -> None:
    world = _ToolWorld(_resolving())
    with pytest.raises(world.tool_runtime.ToolRuntimeError) as excinfo:
        world.invoke(_marks(content), _marks(clearance))
    assert excinfo.value.reason_code == "POLICY_DENIED"
    assert excinfo.value.marking_outcome == "MARKING_UNRESOLVED"
    assert world.effects == []
    assert world.budget.used == 0


def test_ncr_c6_012_the_c8_tool_runtime_denies_a_clearance_that_does_not_dominate() -> None:
    world = _ToolWorld(_resolving())
    with pytest.raises(world.tool_runtime.ToolRuntimeError) as excinfo:
        world.invoke(_marks(FULL), _marks({"classification": "UNCLASSIFIED", "compartment": "ALL"}))
    assert excinfo.value.reason_code == "POLICY_DENIED"
    assert excinfo.value.marking_outcome == "MARKING_DENIED"
    assert world.effects == [] and world.budget.used == 0


def test_ncr_c6_012_the_c8_tool_runtime_refuses_the_legacy_engine() -> None:
    with pytest.raises(TypeError):
        _ToolWorld(_legacy_engine())


class _RecordingMarkingPort:
    """A ``MarkingAuthorizationPort`` that records each clearance it is asked about."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, dict[str, str]]] = []

    def exists_authorized(self, resource_id: str, clearance: Any) -> bool:
        self.asked.append((resource_id, dict(clearance.values)))
        return True


C2_CONTRACT = "urn:ocor:contract:named-query:rem0054-marking"
C2_MARKING_REF = "urn:sha256:" + "a" * 64


def _named_query(*, resource_id: str | None = "urn:ocor:resource:rem0054") -> Any:
    ports = _mod("c2.ports")
    canonical = _mod("kernel.canonical")
    kernel = _mod("kernel.governed_context")
    context = kernel.GovernedContext(
        tenant_id="urn:ocor:tenant:synthetic", organization_id="urn:ocor:org:synthetic", domain_id="urn:ocor:domain:logistics",
        compartments=("urn:ocor:compartment:alpha",), classification_marking_ref=C2_MARKING_REF, purpose="rem0054-marking",
        effective_principal_id="urn:ocor:principal:analyst-1", actor_chain=("urn:ocor:principal:analyst-1",),
        ontology_release_digest="urn:sha256:" + "b" * 64, policy_bundle_digest="urn:sha256:" + "c" * 64,
        correlation_id="018f2f95-01b2-7cc3-8d4e-123456789abc",
    )
    parameters = {} if resource_id is None else {"resource_id": resource_id}
    return ports.NamedQueryRequest(
        request_id="018f2f95-01b2-7cc3-8d4e-123456789abd", contract_id=C2_CONTRACT, contract_version="1.0.0",
        contract_digest="urn:sha256:" + "d" * 64, parameters=parameters, governed_context=context,
        governed_context_digest=canonical.canonical_digest(context.to_mapping()),
        consistency=ports.ConsistencyRequirement(mode=ports.ConsistencyMode.BEST_AVAILABLE),
    )


def _c2_policy(engine: Any, clearance: Any, port: _RecordingMarkingPort) -> Any:
    gateway = _mod("c2.gateway")
    registered = gateway.RegisteredNamedQuery(contract_id=C2_CONTRACT, versions=frozenset({"1.0.0"}), marking_scheme_id="classification")
    return gateway.RegistrationAndMarkingPolicy(registry={C2_CONTRACT: registered}, marking_engine=engine, marking_port=port,
                                                clearance_by_marking_ref={C2_MARKING_REF: clearance})


def test_ncr_c6_012_the_c2_policy_permits_with_a_complete_clearance_and_asks_the_port_with_it() -> None:
    port = _RecordingMarkingPort()
    policy = _c2_policy(_resolving(), _marks(CLEARED), port)
    assert policy.decide(_named_query()) == _mod("c2.gateway").PERMIT
    assert port.asked == [("urn:ocor:resource:rem0054", CLEARED)]
    assert policy.decide(_named_query(resource_id=None)) == _mod("c2.gateway").PERMIT


@pytest.mark.parametrize("clearance", [
    pytest.param(_mod("c4_marking").MarkingSet({"classification": "TOP_SECRET"}), id="misses-a-scheme"),
    pytest.param(_mod("c4_marking").MarkingSet({**CLEARED, "compartment": "GAMMA"}), id="unknown-label"),
    pytest.param(_mod("c4_marking").MarkingSet({**CLEARED, "caveat": "NOFORN"}), id="unknown-scheme"),
    pytest.param(CLEARED, id="not-a-marking-set"),
])
@pytest.mark.parametrize("resource_id", ["urn:ocor:resource:rem0054", None])
def test_ncr_c6_012_the_c2_policy_denies_an_unresolved_clearance_without_asking_the_port(clearance: Any, resource_id: str | None) -> None:
    # ADD v1.3 :401: an unresolvable marking is DENY, never a permissive posture.
    port = _RecordingMarkingPort()
    policy = _c2_policy(_resolving(), clearance, port)
    assert policy.clearance(_named_query(resource_id=resource_id)) is None
    assert policy.decide(_named_query(resource_id=resource_id)) == _mod("c2.gateway").DENY
    assert port.asked == []


def test_ncr_c6_012_the_c2_policy_refuses_the_legacy_engine() -> None:
    with pytest.raises(TypeError):
        _c2_policy(_legacy_engine(), _marks(CLEARED), _RecordingMarkingPort())


def test_ncr_c6_012_the_c6_action_path_never_reaches_the_legacy_marking_default() -> None:
    """The C6 engine hands committed events to the C7 relay without markings, so a relay that
    carries the legacy engine refuses every emission and one without it evaluates no marking: the
    legacy missing-scheme default is never reached on the C6 path."""
    import ast

    engine_source = inspect.getsource(_mod("c6.engine"))
    calls = [node for node in ast.walk(ast.parse(engine_source))
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "emit"
             and ast.unparse(node.func.value) == "self._relay"]
    assert calls
    assert all({keyword.arg for keyword in call.keywords} <= {"at"} for call in calls)
    store = _mod("c3_store")
    emission = _mod("c7_emission")
    outbox = store.AtomicOutboxStore()
    event = outbox.write("agg-1", {"k": "v"}, expected_version=0, writer_id="ocor-core", event_type="Committed",
                         idempotency_key="rem0054-marking", occurred_at=NOW).event
    sunk: list[Any] = []
    fence = emission.EmissionFence(store=outbox, marking_engine=_legacy_engine())
    with pytest.raises(_mod("errors").EmissionBlocked):
        fence.emit(event, sunk.append, at=NOW)
    assert sunk == []
