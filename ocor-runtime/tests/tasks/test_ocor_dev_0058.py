"""0058: memory is a proposal source; C6 owns controls and C3 owns commit.

RED first. The proposal port has no mutative memory/canonical/security port.
C6 consumption is a separate injected boundary, never a field of the request.
Unit fixtures exercise local refusal paths only; live cases qualify PostgreSQL,
Qdrant, OpenBao transit, the real Human Gate and C3 transaction service.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
import test_ocor_dev_0052 as r
import test_ocor_dev_0057 as a
from ocor_runtime.kernel.canonical import format_utc_timestamp
from ocor_runtime.memory.promotion import (
    MemoryPromotionError,
    MemoryPromotionService,
    PromotionProfile,
)


class CallerAssertedBinding:
    """Looks like a binding, but has never crossed the authentication boundary."""

    class Context:
        correlation_id = "attacker-correlation"

        def digest(self) -> str:
            return "attacker-digest"

    expected = Context()


@pytest.mark.parametrize("operation", ["propose", "load"])
@pytest.mark.parametrize("invalid_binding", [None, object(), {"expected": "caller-asserted"}, CallerAssertedBinding()],
                         ids=["missing", "unverified-object", "caller-mapping", "caller-duck"])
@pytest.mark.parametrize("audit_available", [True, False], ids=["audit-ready", "audit-unavailable"])
def test_proposal_and_load_invalid_binding_audit_without_caller_context(
    operation: str, invalid_binding: Any, audit_available: bool,
) -> None:
    w, audit, policy, s = unit()
    result = s.propose("source", request(w), binding=r.binding())
    before = w.ledger.records()
    audit.events.clear()
    policy.calls = 0
    audit.fail = not audit_available
    action = (lambda: s.propose("source", request(w), binding=invalid_binding)) if operation == "propose" else (
        lambda: s.load(result.audit_ref, binding=invalid_binding))
    error = refused(action, "BINDING_MISSING" if audit_available else "AUDIT_UNAVAILABLE")
    assert error.reason_code == ("AUTHENTICATION_REQUIRED" if audit_available else "CONTROL_PLANE_UNAVAILABLE")
    assert w.ledger.records() == before
    assert policy.calls == 0
    if audit_available:
        assert audit.actions() == [("proposeMemoryPromotion" if operation == "propose" else "consumeMemoryPromotion") + ".denied"]
        event = audit.events[0]
        assert event["reason_code"] == "AUTHENTICATION_REQUIRED"
        assert event["detail_code"] == "BINDING_MISSING"
        assert event["correlation_id"] is None
        assert event["governed_context_digest"] is None
    else:
        assert audit.events == []


@pytest.mark.parametrize("operation", ["propose", "load"])
def test_verified_binding_is_retained_for_authenticated_denial(operation: str) -> None:
    w, audit, policy, s = unit()
    result = s.propose("source", request(w), binding=r.binding())
    policy.permitted = False
    action = (lambda: s.propose("source", request(w), binding=r.binding())) if operation == "propose" else (
        lambda: s.load(result.audit_ref, binding=r.binding()))
    refused(action, "PROMOTION_DENIED")
    assert audit.events[-1]["correlation_id"] == r.CALLER.correlation_id
    assert audit.events[-1]["governed_context_digest"] == r.CALLER.digest()


@pytest.mark.parametrize("operation", ["propose", "load"])
@pytest.mark.parametrize("invalid_binding", [None, object(), {"expected": "caller-asserted"}, CallerAssertedBinding()],
                         ids=["missing", "unverified-object", "caller-mapping", "caller-duck"])
@pytest.mark.parametrize("audit_available", [True, False], ids=["audit-ready", "audit-unavailable"])
def test_live_proposal_and_load_invalid_binding_denial_is_durable_and_fail_closed(
    backends: r.Backends, operation: str, invalid_binding: Any, audit_available: bool,
) -> None:
    with workflow(backends) as x:
        before = x.w.ledger.records()
        if not audit_available:
            # Fault only the per-test audit authority; no volatile fallback.
            with psycopg.connect(backends.dsn, autocommit=True) as conn:
                conn.execute(f'DROP TABLE "{x.w.metadata.schema}".memory_audit')
        action = (lambda: x.s.propose("c6-source", x.req, binding=invalid_binding)) if operation == "propose" else (
            lambda: x.s.load(x.result.audit_ref, binding=invalid_binding))
        error = refused(action, "BINDING_MISSING" if audit_available else "AUDIT_UNAVAILABLE")
        assert error.reason_code == ("AUTHENTICATION_REQUIRED" if audit_available else "CONTROL_PLANE_UNAVAILABLE")
        assert x.w.ledger.records() == before
        assert x.c3.read(x.ctx.tenant_id, "Situation", x.req["target_aggregate_ref"]) is None
        with psycopg.connect(backends.dsn) as conn:
            assert conn.execute("SELECT count(*) FROM c3_outbox WHERE aggregate_ref=%s",
                                (x.req["target_aggregate_ref"],)).fetchone() == (0,)
            if audit_available:
                row = conn.execute(f'SELECT body FROM "{x.w.metadata.schema}".memory_audit ORDER BY seq DESC LIMIT 1').fetchone()
                assert row is not None
                event = json.loads(bytes(row[0]))
                fresh = a.PostgresReceiptAudit(backends.dsn, x.w.metadata.schema)
                assert fresh.receipt(event["audit_ref"]) == event
                assert fresh.actions() == ["proposeMemoryPromotion.recorded", (
                    "proposeMemoryPromotion" if operation == "propose" else "consumeMemoryPromotion") + ".denied"]
                assert event["reason_code"] == "AUTHENTICATION_REQUIRED"
                assert event["detail_code"] == "BINDING_MISSING"
                assert event["correlation_id"] is None
                assert event["governed_context_digest"] is None
            else:
                assert conn.execute("SELECT to_regclass(%s)", (x.w.metadata.schema + ".memory_audit",)).fetchone() == (None,)

PROFILE = PromotionProfile("urn:ocor:proposal:memory-claim:1.0", "Situation")


def request(w: r.World, **changes: Any) -> dict[str, Any]:
    return {
        "operation_id": "promote-1",
        "governed_context": r.CALLER.to_mapping(),
        "governed_context_digest": r.CALLER.digest(),
        "deadline": format_utc_timestamp(w.clock.now() + timedelta(minutes=5)),
        "memory_version": 1,
        "target_aggregate_type": "Situation",
        "target_aggregate_ref": "urn:ocor:situation:harbour",
        "proposal_schema_ref": PROFILE.schema_ref,
        **changes,
    }


class PromotionPolicy:
    def __init__(self) -> None:
        self.permitted = True
        self.fail = False
        self.bundle: str | None = None
        self.calls = 0

    def authorize_promotion(self, item: Any, ctx: Any, target_type: str, target_ref: str) -> Any:
        self.calls += 1
        if self.fail:
            raise ConnectionError("policy unavailable")
        return r.MemoryPolicyDecision(self.permitted, "urn:ocor:policy:promotion", self.bundle or ctx.policy_bundle_digest)


def service(w: r.World, audit: Any, policy: Any = None) -> MemoryPromotionService:
    return MemoryPromotionService(
        coordinator=w.coordinator, metadata=w.metadata, retrieval_policy=w.policy,
        promotion_policy=policy or PromotionPolicy(), markings=w.markings,
        stop=w.stop, audit=audit, receipts=audit, clock=w.clock, profiles=(PROFILE,),
    )


def unit() -> tuple[r.World, a.ReceiptAudit, PromotionPolicy, MemoryPromotionService]:
    w = r.unit_world()
    w.admit("source", "harbour patrol schedule")
    audit, policy = a.ReceiptAudit(), PromotionPolicy()
    return w, audit, policy, service(w, audit, policy)


def refused(action: Any, detail: str) -> MemoryPromotionError:
    with pytest.raises(MemoryPromotionError) as caught:
        action()
    assert caught.value.detail_code == detail
    return caught.value


def test_proposal_binds_exact_source_gcs_target_evidence_without_mutation() -> None:
    w, audit, _, s = unit()
    before = w.ledger.records()
    result = s.propose("source", request(w), binding=r.binding())
    assert result.proposal.source_version_ref == "urn:ocor:memory:source:v1"
    assert result.proposal.governed_context_digest == r.CALLER.digest()
    assert result.proposal.target_aggregate_ref == "urn:ocor:situation:harbour"
    assert result.proposal.evidence_refs
    assert result.proposal.provenance_refs
    assert w.ledger.records() == before
    assert result.to_mapping()["status"] == "ACCEPTED"
    assert result.to_mapping()["operation_id"] == "promote-1"
    assert audit.actions() == ["proposeMemoryPromotion.recorded"]
    assert s.load(result.audit_ref, binding=r.binding()) == result.proposal


@pytest.mark.parametrize("member", ["canonical_delta", "authority_ref", "approval", "decision", "capability", "policy", "content", "action_command"])
def test_request_cannot_smuggle_authority_effect_or_content(member: str) -> None:
    w, audit, _, s = unit()
    refused(lambda: s.propose("source", request(w, **{member: "attempt"}), binding=r.binding()), "REQUEST_INVALID")
    assert audit.actions() == ["proposeMemoryPromotion.denied"]


@pytest.mark.parametrize("changes,detail", [
    ({"memory_version": True}, "REQUEST_INVALID"),
    ({"memory_version": 0}, "REQUEST_INVALID"),
    ({"target_aggregate_type": "Authority"}, "PROFILE_NOT_REGISTERED"),
    ({"target_aggregate_type": "Policy"}, "PROFILE_NOT_REGISTERED"),
    ({"target_aggregate_type": "CapabilityLease"}, "PROFILE_NOT_REGISTERED"),
    ({"proposal_schema_ref": "arbitrary"}, "PROFILE_NOT_REGISTERED"),
    ({"target_aggregate_ref": ""}, "REQUEST_INVALID"),
    ({"deadline": "bad"}, "ENVELOPE_INVALID"),
    ({"governed_context_digest": r.d("forged")}, "GOVERNED_CONTEXT_DIGEST_MISMATCH"),
])
def test_malformed_and_unregistered_targets_fail_closed(changes: dict[str, Any], detail: str) -> None:
    w, audit, _, s = unit()
    with pytest.raises(r.MemoryAdmissionError) as caught:
        s.propose("source", request(w, **changes), binding=r.binding())
    if detail != "GOVERNED_CONTEXT_DIGEST_MISMATCH":
        assert caught.value.detail_code == detail
    assert audit.actions() == ["proposeMemoryPromotion.denied"]


def test_missing_binding_and_foreign_gcs_fail_closed() -> None:
    w, _, _, s = unit()
    refused(lambda: s.propose("source", request(w), binding=None), "BINDING_MISSING")
    with pytest.raises(r.MemoryAdmissionError):
        s.propose("source", request(w), binding=r.binding(r.context(tenant="other")))


@pytest.mark.parametrize("fault,detail", [("deny", "PROMOTION_DENIED"), ("outage", "PROMOTION_POLICY_UNAVAILABLE"), ("stale", "POLICY_BUNDLE_MISMATCH"), ("invalid", "PROMOTION_POLICY_INVALID")])
def test_promotion_policy_is_live_and_fail_closed(fault: str, detail: str) -> None:
    w, audit, p, s = unit()
    if fault == "deny":
        p.permitted = False
    elif fault == "outage":
        p.fail = True
    elif fault == "stale":
        p.bundle = r.d("other")
    else:
        p.authorize_promotion = lambda *args: None  # type: ignore[method-assign]
    refused(lambda: s.propose("source", request(w), binding=r.binding()), detail)
    assert audit.actions()[-1] == "proposeMemoryPromotion.denied"


def test_expired_deadline_is_audited() -> None:
    w, audit, _, s = unit()
    refused(lambda: s.propose("source", request(w, deadline=format_utc_timestamp(w.clock.now())), binding=r.binding()), "DEADLINE_EXCEEDED")
    assert audit.actions()[-1] == "proposeMemoryPromotion.denied"


def test_audit_outage_returns_no_proposal() -> None:
    w, audit, _, s = unit()
    audit.fail = True
    refused(lambda: s.propose("source", request(w), binding=r.binding()), "AUDIT_UNAVAILABLE")


def test_unrecorded_tampered_or_foreign_proposal_cannot_be_consumed() -> None:
    w, audit, _, s = unit()
    refused(lambda: s.load(r.d("unknown"), binding=r.binding()), "PROPOSAL_UNRECORDED")
    result = s.propose("source", request(w), binding=r.binding())
    with pytest.raises(r.MemoryAdmissionError):
        s.load(result.audit_ref, binding=r.binding(r.context(tenant="other")))
    next(e for e in audit.events if "proposal" in e)["proposal"]["target_aggregate_ref"] = "forged"
    refused(lambda: s.load(result.audit_ref, binding=r.binding()), "PROPOSAL_DIGEST_MISMATCH")


@pytest.mark.parametrize("fault", ["revocation", "correction", "expiry", "stop", "policy", "deadline"])
def test_consumption_revalidates_source_stop_policy_and_time(fault: str) -> None:
    w, audit, p, s = unit()
    result = s.propose("source", request(w), binding=r.binding())
    record = w.ledger.get("source", 1)
    assert record is not None
    if fault == "revocation":
        w.lifecycle(record, "REVOKED", "harbour patrol schedule")
    elif fault == "correction":
        w.admit("source", "corrected schedule", version=2)
    elif fault == "expiry":
        w.clock.advance(timedelta(days=400))
    elif fault == "stop":
        w.stop.epoch += 1
    elif fault == "policy":
        p.permitted = False
    else:
        w.clock.advance(timedelta(minutes=6))
    with pytest.raises(r.MemoryAdmissionError):
        s.load(result.audit_ref, binding=r.binding())
    assert audit.actions()[-1] == "consumeMemoryPromotion.denied"


def test_stop_change_during_policy_validation_returns_no_proposal() -> None:
    w, audit, p, s = unit()
    original = p.authorize_promotion
    def change(*args: Any) -> Any:
        out = original(*args)
        w.stop.epoch += 1
        return out
    p.authorize_promotion = change  # type: ignore[method-assign]
    refused(lambda: s.propose("source", request(w), binding=r.binding()), "STOP_EPOCH_CHANGED")
    assert audit.actions() == ["proposeMemoryPromotion.denied"]


def test_memory_port_has_no_canonical_security_or_mutative_memory_dependency() -> None:
    import inspect
    fields = set(inspect.signature(MemoryPromotionService).parameters)
    assert not fields & {"c3", "commit", "authority", "capabilities", "ledger", "admission", "c6"}
    assert not {"commit", "grant", "execute", "issue", "admit", "transition"} & set(dir(MemoryPromotionService))
    with pytest.raises(ValueError):
        PromotionProfile("urn:ocor:proposal:unsafe", "Authority")


# Imported fixtures provision real pinned backends; never skip.
live_backends = r.live_backends
backends = r.backends


def test_live_proposal_is_durable_and_consumed_from_fresh_adapters(backends: r.Backends) -> None:
    w = backends.world()
    w.admit("live-source", "harbour patrol observation")
    audit = a.PostgresReceiptAudit(backends.dsn, w.metadata.schema)
    p = PromotionPolicy()
    first = service(w, audit, p)
    before = w.ledger.records()
    result = first.propose("live-source", request(w), binding=r.binding())
    fresh = service(backends.fresh(w), a.PostgresReceiptAudit(backends.dsn, w.metadata.schema), p)
    assert fresh.load(result.audit_ref, binding=r.binding()) == result.proposal
    assert w.ledger.records() == before
    assert audit.actions() == ["proposeMemoryPromotion.recorded"]


@pytest.mark.parametrize("fault", ["revocation", "supersession", "foreign-compartment", "stop", "policy"])
def test_live_ineligible_source_or_changed_control_leaves_only_denial(backends: r.Backends, fault: str) -> None:
    w = backends.world()
    w.admit("live-source", "harbour patrol observation")
    audit = a.PostgresReceiptAudit(backends.dsn, w.metadata.schema)
    p = PromotionPolicy()
    s = service(w, audit, p)
    if fault == "foreign-compartment":
        w.admit("foreign", "private", ctx=r.context(compartments=("gamma",)))
        target = "foreign"
    else:
        target = "live-source"
        if fault == "revocation":
            record = w.ledger.get(target, 1)
            assert record is not None
            w.lifecycle(record, "REVOKED", "harbour patrol observation")
        elif fault == "supersession":
            w.admit(target, "corrected", version=2)
        elif fault == "policy":
            p.permitted = False
        else:
            w.stop.bump_after = w.stop.reads + 1
    before = w.ledger.records()
    with pytest.raises(r.MemoryAdmissionError):
        s.propose(target, request(w), binding=r.binding())
    assert w.ledger.records() == before
    assert audit.actions() == ["proposeMemoryPromotion.denied"]


def test_c6_consumer_requires_separate_control_authority_approval_decision_and_c3() -> None:
    from ocor_runtime.memory.promotion import C6MemoryPromotionConsumer
    import inspect
    fields = set(inspect.signature(C6MemoryPromotionConsumer).parameters)
    assert {"proposals", "controls", "verifier", "human_gate", "policy", "c3", "clock", "audit",
            "commit_capability"} <= fields
    assert not {"issue", "grant", "approve", "decide", "install_policy"} & set(dir(C6MemoryPromotionConsumer))


@pytest.mark.parametrize("invalid_binding", [None, object(), {"expected": "caller-asserted"}],
                         ids=["missing", "unverified-object", "caller-mapping"])
@pytest.mark.parametrize("audit_available", [True, False], ids=["audit-ready", "audit-unavailable"])
def test_commit_invalid_binding_audits_denial_before_any_control_or_c3_access(
    invalid_binding: Any, audit_available: bool,
) -> None:
    w, audit, _, s = unit()

    class Unreachable:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError("unauthenticated request reached " + name)

    boundary: Any = Unreachable()
    consumer = C6MemoryPromotionConsumer(
        proposals=s, controls=boundary, verifier=boundary, human_gate=boundary,
        policy=boundary, c3=boundary, clock=w.clock, audit=audit,
        commit_capability="canonical.commit",
    )
    audit.fail = not audit_available
    before = w.ledger.records()
    error = refused(lambda: consumer.commit(r.d("proposal"), binding=invalid_binding),
                    "BINDING_MISSING" if audit_available else "AUDIT_UNAVAILABLE")
    assert error.reason_code == ("AUTHENTICATION_REQUIRED" if audit_available else "CONTROL_PLANE_UNAVAILABLE")
    assert w.ledger.records() == before
    if audit_available:
        assert audit.actions() == ["commitMemoryPromotion.denied"]
        event = audit.events[0]
        assert event["reason_code"] == "AUTHENTICATION_REQUIRED"
        assert event["detail_code"] == "BINDING_MISSING"
        assert event["proposal_audit_ref"] == r.d("proposal")
        assert event["correlation_id"] is None
        assert event["governed_context_digest"] is None
    else:
        assert audit.events == []


# C6 integration fixtures: no caller-supplied controls. The independent issuer
# writes signed gates in its own PostgreSQL table. OpenBao verifies ed25519;
# OPA really evaluates every canonical-commit policy decision.

import base64  # noqa: E402
import json  # noqa: E402
import uuid  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from collections.abc import Iterator  # noqa: E402
from dataclasses import replace  # noqa: E402
from urllib.request import Request, urlopen  # noqa: E402

import psycopg  # noqa: E402
from ocor_runtime.c2_identity import IdentityRecord, IdentityRegistry  # noqa: E402
from ocor_runtime.c3.ports import GovernedCanonicalCommitCommand  # noqa: E402
from ocor_runtime.c3.service import PostgresC3Service  # noqa: E402
from ocor_runtime.c6.human_gate import HumanGateCoordinator  # noqa: E402
from ocor_runtime.kernel.canonical import canonical_bytes, canonical_digest  # noqa: E402
from ocor_runtime.memory.promotion import (  # noqa: E402
    C6MemoryPromotionConsumer,
    SignedPromotionGate,
    promotion_gate_digest,
)


class BaoSigner:
    def __init__(self, bao: Any) -> None:
        self.bao = bao
        self.key = "promotion-c6"
        bao.call("POST", f"/v1/ocor-memory-transit/keys/{self.key}", {"type": "ed25519"})

    def sign(self, payload: bytes) -> str:
        out = self.bao.call("POST", f"/v1/ocor-memory-transit/sign/{self.key}", {"input": base64.b64encode(payload).decode()})
        return str(out["data"]["signature"])

    def verify(self, payload: bytes, signature: str) -> bool:
        status, out = r.base._http("POST", f"{self.bao.endpoint}/v1/ocor-memory-transit/verify/{self.key}",
                                  {"input": base64.b64encode(payload).decode(), "signature": signature},
                                  headers={"X-Vault-Token": self.bao.token})
        if status == 400:
            return False
        assert status == 200
        return out["data"]["valid"] is True


class Controls:
    def __init__(self, dsn: str, schema: str, signer: Any) -> None:
        self.dsn, self.schema, self.signer = dsn, schema, signer
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute(f'CREATE TABLE "{schema}".c6_gate (ref text PRIMARY KEY, payload bytea NOT NULL, signature text NOT NULL)')
            c.execute(f'CREATE TABLE "{schema}".c6_revoked (ref text PRIMARY KEY)')
            # Written by C6 delegation admission, never by memory or the caller.
            c.execute(f'CREATE TABLE "{schema}".c6_delegation (binding_ref text PRIMARY KEY, delegation_ref text NOT NULL)')

    def admit_delegation(self, binding_ref: str, delegation_ref: str) -> None:
        with psycopg.connect(self.dsn, autocommit=True) as c:
            c.execute(f'INSERT INTO "{self.schema}".c6_delegation VALUES (%s,%s)', (binding_ref, delegation_ref))

    def verified_delegation(self, binding_ref: str) -> str | None:
        with psycopg.connect(self.dsn) as c:
            row = c.execute(f'SELECT delegation_ref FROM "{self.schema}".c6_delegation WHERE binding_ref=%s',
                            (binding_ref,)).fetchone()
        return None if row is None else str(row[0])

    def put(self, ref: str, body: dict[str, Any], *, broken_signature: bool = False) -> None:
        body["command"]["gate_package_digest"] = promotion_gate_digest(body)
        body["decision"]["gate_package_digest"] = body["command"]["gate_package_digest"]
        payload = canonical_bytes(body)
        signature = self.signer.sign(payload)
        if broken_signature:
            payload = payload.replace(b'harbour', b'forged')
        with psycopg.connect(self.dsn, autocommit=True) as c:
            c.execute(f'INSERT INTO "{self.schema}".c6_gate VALUES (%s,%s,%s) ON CONFLICT(ref) DO UPDATE SET payload=excluded.payload,signature=excluded.signature', (ref, payload, signature))

    def gate(self, ref: str) -> SignedPromotionGate | None:
        with psycopg.connect(self.dsn) as c:
            row = c.execute(f'SELECT payload,signature FROM "{self.schema}".c6_gate WHERE ref=%s', (ref,)).fetchone()
        return None if row is None else SignedPromotionGate(bytes(row[0]), row[1])

    def revoked(self, ref: str) -> bool:
        with psycopg.connect(self.dsn) as c:
            row = c.execute(f'SELECT 1 FROM "{self.schema}".c6_revoked WHERE ref=%s', (ref,)).fetchone()
        return row is not None

    def revoke(self, ref: str) -> None:
        with psycopg.connect(self.dsn, autocommit=True) as c:
            c.execute(f'INSERT INTO "{self.schema}".c6_revoked VALUES (%s)', (ref,))


class OpaPolicy:
    # One package per instance: OPA rejects a second module defining the same
    # default rule, so a leaked module could otherwise poison later cases.
    TEMPLATE = ('package ocor.promotion0058.{suffix}\n'
                'default allow := false\n'
                'allow if {{ input.action == "CANONICAL_COMMIT"; input.aggregate_type == "Situation"; '
                'input.branch == "main"; input.permitted == true }}\n')

    def __init__(self) -> None:
        suffix = "p" + uuid.uuid4().hex
        self.identifier = "ocor-promotion-0058-" + suffix
        self.SOURCE = self.TEMPLATE.format(suffix=suffix)
        self.path = "ocor/promotion0058/" + suffix + "/allow"
        self.permitted, self.outage, self.stale = True, False, False
        self.hook: Any = None
        req = Request("http://127.0.0.1:8181/v1/policies/" + self.identifier,
                      data=self.SOURCE.encode(), method="PUT", headers={"Content-Type": "text/plain"})
        with urlopen(req, timeout=5) as response:
            assert response.status == 200
        self.digest = canonical_digest(self.SOURCE)

    def close(self) -> None:
        with urlopen(Request("http://127.0.0.1:8181/v1/policies/" + self.identifier, method="DELETE"), timeout=5) as response:
            assert response.status == 200

    def authorize_commit(self, proposal: Any, command: Any) -> Any:
        if self.outage:
            # Real failed transport; no mock substitutes the boundary.
            with urlopen("http://127.0.0.1:1/v1/data/" + self.path, timeout=1):
                raise AssertionError("unreachable port answered")
        status, rules = r.base._http("GET", "http://127.0.0.1:8181/v1/policies/" + self.identifier)
        assert status == 200 and rules["result"]["raw"] == self.SOURCE
        status, out = r.base._http("POST", "http://127.0.0.1:8181/v1/data/" + self.path, {"input": {
            "action": "CANONICAL_COMMIT", "aggregate_type": command.aggregate_type,
            "branch": command.branch, "permitted": self.permitted,
        }})
        assert status == 200
        if self.hook is not None:
            self.hook()
        return r.MemoryPolicyDecision(out["result"] is True, "urn:ocor:policy:opa-promotion0058",
                                      r.d("stale") if self.stale else self.digest)


class OpaProposalPolicy(OpaPolicy):
    """Proposal policy test adapter: decode the response of the pinned OPA.

    No decision is synthesised by this adapter. Invalid responses and a refused
    TCP transport qualify local fail-closed handling, not OPA's own correctness.
    """

    TEMPLATE = ('package ocor.promotion0058.{suffix}\n'
                'default allow := false\n'
                'allow if {{ input.action == "MEMORY_PROMOTION"; '
                'input.aggregate_type == "Situation"; input.permitted == true }}\n')

    def install(self, source: str) -> None:
        req = Request("http://127.0.0.1:8181/v1/policies/" + self.identifier,
                      data=source.encode(), method="PUT", headers={"Content-Type": "text/plain"})
        with urlopen(req, timeout=5) as response:
            assert response.status == 200

    def authorize_promotion(self, item: Any, ctx: Any, target_type: str, target_ref: str) -> Any:
        if self.outage:
            with urlopen("http://127.0.0.1:1/v1/data/" + self.path, timeout=1):
                raise AssertionError("unreachable port answered")
        status, rules = r.base._http("GET", "http://127.0.0.1:8181/v1/policies/" + self.identifier)
        assert status == 200
        digest = canonical_digest(rules["result"]["raw"])
        status, out = r.base._http("POST", "http://127.0.0.1:8181/v1/data/" + self.path, {"input": {
            "action": "MEMORY_PROMOTION", "aggregate_type": target_type, "permitted": self.permitted,
        }})
        assert status == 200
        # A non-boolean OPA result cannot be interpreted as an allow decision.
        if not isinstance(out.get("result"), bool):
            return None
        return r.MemoryPolicyDecision(out["result"], "urn:ocor:policy:opa-proposal0058", digest)


def gate_body(proposal: Any, proposal_ref: str, ctx: Any) -> dict[str, Any]:
    now = r.NOW
    action = "urn:ocor:action:promotion:" + uuid.uuid4().hex
    authority_id = "urn:ocor:authority:c6:" + uuid.uuid4().hex
    decision_ref = "urn:ocor:decision:c6:" + uuid.uuid4().hex
    command: dict[str, Any] = {
        "command_id": "urn:ocor:command:" + uuid.uuid4().hex,
        "action_instance_id": action, "aggregate_type": proposal.target_aggregate_type,
        "aggregate_ref": proposal.target_aggregate_ref, "expected_revision": 0,
        "canonical_delta": {"patrol_status": "observed", "acceptedFromClaim": "urn:ocor:claim:harbour"},
        "decision_ref": decision_ref, "authority_ref": authority_id,
        "evidence_refs": list(proposal.evidence_refs),
        "claim_source_bindings": [{"claim_ref": "urn:ocor:claim:harbour", "source_ref": proposal.source_version_ref, "evidence_ref": proposal.evidence_refs[0]}],
        "precondition_bindings": [proposal.digest], "invariant_bindings": ["urn:ocor:invariant:memory-non-authoritative"],
        "idempotency_key": "promotion-" + uuid.uuid4().hex,
        "governed_context": ctx.to_mapping(), "governed_context_digest": ctx.digest(),
        "gate_package_digest": r.d("placeholder"), "branch": "main",
    }
    return {
        "proposal_audit_ref": proposal_ref, "proposal_digest": proposal.digest, "command": command,
        "authority": {
            "authority_id": authority_id, "effective_principal_id": ctx.effective_principal_id,
            "capability_ids": ["canonical.commit"], "resource_scopes": [proposal.target_aggregate_ref],
            "tenant_id": ctx.tenant_id, "domains": [ctx.domain_id], "compartments": list(ctx.compartments),
            "permitted_purposes": [ctx.purpose], "risk_ceiling": 3,
            "not_before": format_utc_timestamp(now - timedelta(minutes=1)),
            "expires_at": format_utc_timestamp(now + timedelta(minutes=10)),
            "delegation_ref": r.d("c6-verified-delegation"), "policy_bundle_digest": ctx.policy_bundle_digest,
            "signature_ref": "urn:ocor:signature:independent-c6-authority",
        },
        "decision": {"decision_ref": decision_ref, "action_id": action, "accepted": True,
                     "decided_at": format_utc_timestamp(now), "valid_until": format_utc_timestamp(now + timedelta(minutes=5)),
                     "gate_package_digest": r.d("placeholder")},
        "approval_policy": {"required_roles": ["COMPLIANCE", "RISK_OWNER"], "minimum_signatories": 2, "ttl_seconds": 600},
        "signatures": [{"action_id": action, "principal_id": "human-" + role.lower(), "role": role,
                        "scope": proposal.target_aggregate_ref, "signed_at": format_utc_timestamp(now)}
                       for role in ("COMPLIANCE", "RISK_OWNER")],
        "risk_class": 2, "capability_id": "canonical.commit",
    }


@contextmanager
def workflow(backends: r.Backends, *, proposal_policy: OpaProposalPolicy | None = None) -> Iterator[Any]:
    w = backends.world()
    policy = OpaPolicy()
    req: dict[str, Any] | None = None
    try:
        # The GCS pins the exact OPA rule bytes used in this component qualification.
        ctx = replace(r.CALLER, policy_bundle_digest=(proposal_policy or policy).digest)
        seed = w.admit("seed", "harbour patrol observation")
        candidate = seed.item.to_mapping()
        candidate.update(memory_item_id="c6-source", policy_bundle_digest=ctx.policy_bundle_digest,
                         governed_context_digest=ctx.digest(), compartments=list(ctx.compartments),
                         embedding_ref="embedding:c6-source:v1")
        w.admission.admit({"operation_id": "c6-source-admission", "governed_context": ctx.to_mapping(),
                           "governed_context_digest": ctx.digest(),
                           "deadline": format_utc_timestamp(w.clock.now() + timedelta(seconds=30)),
                           "candidate": candidate}, binding=r.binding(ctx), payload=b"harbour patrol observation")
        source = w.ledger.get("c6-source", 1)
        assert source is not None
        w.coordinator.commit(source, payload=b"harbour patrol observation", embedding=r.embed("harbour patrol observation"))
        audit = a.PostgresReceiptAudit(backends.dsn, w.metadata.schema)
        signer = BaoSigner(backends.bao)
        controls = Controls(backends.dsn, w.metadata.schema, signer)
        controls.admit_delegation(r.binding(ctx).binding_ref, r.d("c6-verified-delegation"))
        registry = IdentityRegistry(
            IdentityRecord("human-" + role.lower(), attributes={"principal_kind": "HUMAN", "status": "ACTIVE", "roles": role})
            for role in ("COMPLIANCE", "RISK_OWNER")
        )
        c3 = PostgresC3Service(backends.dsn)
        c3.initialize()
        s = service(w, audit, proposal_policy)
        req = request(w, governed_context=ctx.to_mapping(), governed_context_digest=ctx.digest(),
                      target_aggregate_ref="urn:ocor:situation:harbour:" + uuid.uuid4().hex)
        result = s.propose("c6-source", req, binding=r.binding(ctx))
        body = gate_body(result.proposal, result.audit_ref, ctx)
        consumer = C6MemoryPromotionConsumer(proposals=s, controls=controls, verifier=signer,
                                            human_gate=HumanGateCoordinator(identities=registry, clock=w.clock),
                                            policy=policy, c3=c3, clock=w.clock, audit=audit,
                                            commit_capability="canonical.commit")
        data = type("Workflow", (), {})()
        for name, value in locals().copy().items():
            setattr(data, name, value)
        yield data
    finally:
        try:
            policy.close()
        finally:
            if req is not None:
                # C3 uses its approved global schema; remove only this test's rows.
                with psycopg.connect(backends.dsn) as conn:
                    ref = req["target_aggregate_ref"]
                    conn.execute("DELETE FROM c3_outbox WHERE aggregate_ref=%s", (ref,))
                    for table in ("c3_idempotency", "c3_commit", "c3_aggregate"):
                        conn.execute(f"DELETE FROM {table} WHERE aggregate_ref=%s", (ref,))


def test_live_c6_approval_decision_produces_only_c3_commit_and_verified_receipt(backends: r.Backends) -> None:
    with workflow(backends) as x:
        x.controls.put(x.result.audit_ref, x.body)
        before = x.w.ledger.records()
        assert x.c3.read(x.ctx.tenant_id, "Situation", x.req["target_aggregate_ref"]) is None
        receipt = x.consumer.commit(x.result.audit_ref, binding=r.binding(x.ctx))
        command = GovernedCanonicalCommitCommand.from_mapping(x.body["command"])
        assert receipt.verify(command) == receipt
        state = x.c3.read(x.ctx.tenant_id, "Situation", x.req["target_aggregate_ref"])
        assert state is not None and state.revision == 1
        assert dict(state.state) == command.canonical_delta
        assert x.w.ledger.records() == before
        assert x.audit.actions()[-2:] == ["commitMemoryPromotion.intent", "commitMemoryPromotion.completed"]
        again = x.consumer.commit(x.result.audit_ref, binding=r.binding(x.ctx))
        assert again.replayed is True and again.commit_id == receipt.commit_id
        assert x.c3.current_revision(x.ctx.tenant_id, "Situation", x.req["target_aggregate_ref"]) == 1


@pytest.mark.parametrize("invalid_binding", [None, object(), {"expected": "caller-asserted"}],
                         ids=["missing", "unverified-object", "caller-mapping"])
def test_live_commit_invalid_binding_persists_denial_without_state_change(
    backends: r.Backends, invalid_binding: Any,
) -> None:
    with workflow(backends) as x:
        x.controls.put(x.result.audit_ref, x.body)
        before = x.w.ledger.records()
        refused(lambda: x.consumer.commit(x.result.audit_ref, binding=invalid_binding), "BINDING_MISSING")
        fresh_audit = a.PostgresReceiptAudit(backends.dsn, x.w.metadata.schema)
        assert fresh_audit.actions() == ["proposeMemoryPromotion.recorded", "commitMemoryPromotion.denied"]
        assert x.w.ledger.records() == before
        assert x.c3.read(x.ctx.tenant_id, "Situation", x.req["target_aggregate_ref"]) is None
        with psycopg.connect(backends.dsn) as conn:
            assert conn.execute("SELECT count(*) FROM c3_outbox WHERE aggregate_ref=%s",
                                (x.req["target_aggregate_ref"],)).fetchone() == (0,)


@pytest.mark.parametrize("fault,detail", [
    ("allow", None), ("deny", "PROMOTION_DENIED"), ("outage", "PROMOTION_POLICY_UNAVAILABLE"),
    ("stale", "POLICY_BUNDLE_MISMATCH"), ("invalid", "PROMOTION_POLICY_INVALID"),
])
def test_live_proposal_policy_opa_positive_and_faults(
    backends: r.Backends, fault: str, detail: str | None,
) -> None:
    policy = OpaProposalPolicy()
    try:
        with workflow(backends, proposal_policy=policy) as x:
            before = x.w.ledger.records()
            # The fixture's initial proposal is a positive using this exact
            # policy and binding. Mutate one boundary only before a second use.
            policy.permitted = fault != "deny"
            policy.outage = fault == "outage"
            if fault == "stale":
                policy.install(policy.SOURCE + "\n# new policy revision\n")
            elif fault == "invalid":
                package = policy.SOURCE.splitlines()[0]
                policy.install(package + '\nallow := {"invalid": "decision"}\n')
            if detail is None:
                result = x.s.propose("c6-source", x.req, binding=r.binding(x.ctx))
                assert result.proposal == x.result.proposal
                assert x.audit.actions() == ["proposeMemoryPromotion.recorded"] * 2
            else:
                error = refused(lambda: x.s.propose("c6-source", x.req, binding=r.binding(x.ctx)), detail)
                assert error.reason_code == {
                    "deny": "POLICY_DENIED", "outage": "CONTROL_PLANE_UNAVAILABLE",
                    "stale": "STALE_POLICY", "invalid": "CONTROL_PLANE_UNAVAILABLE",
                }[fault]
                assert x.audit.actions() == ["proposeMemoryPromotion.recorded", "proposeMemoryPromotion.denied"]
            assert x.w.ledger.records() == before
            assert x.c3.read(x.ctx.tenant_id, "Situation", x.req["target_aggregate_ref"]) is None
    finally:
        policy.close()


# Each fault mutates exactly one control of the otherwise accepted gate of the
# positive case above and must be refused for its own stable reason.
GATE_FAULT_DETAILS = {
    "missing": "C6_GATE_MISSING", "unsigned": "C6_GATE_UNSIGNED", "proposal": "C6_PROPOSAL_MISMATCH",
    "gate-digest": "GATE_PACKAGE_MISMATCH", "target": "C6_COMMAND_BINDING_MISMATCH",
    "gcs": "C6_COMMAND_BINDING_MISMATCH", "evidence": "C6_COMMAND_BINDING_MISMATCH",
    "claim": "C6_COMMAND_BINDING_MISMATCH", "authority-ref": "C6_AUTHORITY_MISMATCH",
    "authority-expired": "AUTHORITY_EXPIRED", "authority-revoked": "AUTHORITY_REVOKED",
    "authority-purpose": "AUTHORITY_SCOPE_MISMATCH", "authority-tenant": "AUTHORITY_SCOPE_MISMATCH",
    "authority-capability": "AUTHORITY_SCOPE_MISMATCH", "authority-scope": "AUTHORITY_SCOPE_MISMATCH",
    "authority-domain": "AUTHORITY_SCOPE_MISMATCH", "authority-compartments": "AUTHORITY_SCOPE_MISMATCH",
    "authority-risk": "AUTHORITY_SCOPE_MISMATCH", "authority-delegation": "AUTHORITY_BINDING_MISMATCH",
    "delegation-unverified": "AUTHORITY_BINDING_MISMATCH", "delegation-revoked": "AUTHORITY_REVOKED",
    "capability-mismatch": "C6_CAPABILITY_MISMATCH",
    "authority-not-yet-valid": "AUTHORITY_NOT_YET_VALID",
    "decision-denied": "C6_DECISION_REJECTED", "decision-expired": "C6_DECISION_EXPIRED_OR_REVOKED",
    "decision-revoked": "C6_DECISION_EXPIRED_OR_REVOKED", "decision-action": "C6_DECISION_REJECTED",
    "decision-ref": "C6_DECISION_REJECTED", "approval-absent": "C6_APPROVAL_INVALID",
    # The Human Gate deliberately never discloses which signature it excluded.
    "approval-quorum": "QUORUM_NOT_MET", "approval-self": "QUORUM_NOT_MET", "approval-role": "QUORUM_NOT_MET",
    "approval-expired": "QUORUM_NOT_MET", "approval-missing-role": "MISSING_REQUIRED_ROLE",
    "approval-expired-during-final-policy": "QUORUM_NOT_MET",
    "policy-denied": "C6_POLICY_DENIED", "policy-outage": "C6_CONTROL_UNAVAILABLE",
    "policy-stale": "POLICY_BUNDLE_MISMATCH", "stop-during-policy": "STOP_EPOCH_CHANGED",
    "source-during-policy": "SOURCE_NOT_ELIGIBLE", "revoked-during-policy": "C6_CONTROL_EXPIRED_OR_REVOKED",
}
GATE_FAULTS = list(GATE_FAULT_DETAILS)


@pytest.mark.parametrize("fault", GATE_FAULTS)
def test_live_every_c6_gate_refusal_leaves_canonical_and_memory_unchanged(backends: r.Backends, fault: str) -> None:
    with workflow(backends) as x:
        body, command, auth, decision = x.body, x.body["command"], x.body["authority"], x.body["decision"]
        if fault == "proposal":
            body["proposal_digest"] = r.d("forged")
        elif fault == "target":
            command["aggregate_type"] = "Authority"
        elif fault == "gcs":
            command["governed_context"]["tenant_id"] = "foreign"
            command["governed_context_digest"] = canonical_digest(command["governed_context"])
        elif fault == "evidence":
            command["evidence_refs"] = ["foreign"]
        elif fault == "claim":
            command["claim_source_bindings"][0]["source_ref"] = "foreign"
        elif fault == "authority-ref":
            auth["authority_id"] = "foreign"
        elif fault == "authority-expired":
            auth["expires_at"] = format_utc_timestamp(r.NOW)
        elif fault == "authority-revoked":
            x.controls.revoke(auth["authority_id"])
        elif fault == "authority-purpose":
            auth["permitted_purposes"] = ["other"]
        elif fault == "authority-tenant":
            auth["tenant_id"] = "other"
        elif fault == "authority-capability":
            auth["capability_ids"] = ["read"]
        elif fault == "authority-scope":
            auth["resource_scopes"] = ["other"]
        elif fault == "authority-domain":
            auth["domains"] = ["other"]
        elif fault == "authority-compartments":
            auth["compartments"] = ["other"]
        elif fault == "authority-risk":
            auth["risk_ceiling"] = 0
        elif fault == "authority-delegation":
            auth["delegation_ref"] = r.d("foreign-delegation")
        elif fault == "delegation-unverified":
            with psycopg.connect(backends.dsn, autocommit=True) as conn:
                conn.execute(f'DELETE FROM "{x.controls.schema}".c6_delegation')
        elif fault == "capability-mismatch":
            # Authority covers both, but C3 commit needs the composed capability.
            auth["capability_ids"] = ["canonical.commit", "memory.read"]
            body["capability_id"] = "memory.read"
        elif fault == "delegation-revoked":
            x.controls.revoke(auth["delegation_ref"])
        elif fault == "authority-not-yet-valid":
            auth["not_before"] = format_utc_timestamp(r.NOW + timedelta(minutes=1))
        elif fault == "decision-denied":
            decision["accepted"] = False
        elif fault == "decision-expired":
            decision["valid_until"] = format_utc_timestamp(r.NOW)
        elif fault == "decision-revoked":
            x.controls.revoke(decision["decision_ref"])
        elif fault == "decision-action":
            decision["action_id"] = "foreign"
        elif fault == "decision-ref":
            decision["decision_ref"] = "foreign"
        elif fault == "approval-absent":
            body["signatures"] = []
        elif fault == "approval-quorum":
            body["signatures"] = body["signatures"][:1]
        elif fault == "approval-self":
            body["signatures"][0]["principal_id"] = x.ctx.effective_principal_id
        elif fault == "approval-role":
            body["signatures"][0]["role"] = "RISK_OWNER"
        elif fault == "approval-expired":
            body["signatures"][0]["signed_at"] = format_utc_timestamp(r.NOW - timedelta(hours=1))
        elif fault == "approval-missing-role":
            # Quorum of two distinct valid humans, but nobody covers SAFETY_OFFICER.
            body["approval_policy"]["required_roles"] = ["COMPLIANCE", "RISK_OWNER", "SAFETY_OFFICER"]
        elif fault == "policy-denied":
            x.policy.permitted = False
        elif fault == "policy-outage":
            x.policy.outage = True
        elif fault == "policy-stale":
            x.policy.stale = True
        elif fault == "stop-during-policy":
            x.policy.hook = lambda: setattr(x.w.stop, "epoch", x.w.stop.epoch + 1)
        elif fault == "source-during-policy":
            x.policy.hook = lambda: x.w.lifecycle(x.source, "REVOKED", "harbour patrol observation")
        elif fault == "revoked-during-policy":
            x.policy.hook = lambda: x.controls.revoke(decision["decision_ref"])
        elif fault == "approval-expired-during-final-policy":
            # Only the last policy I/O outlives the approval TTL (decision and
            # Authority still valid): solely the final Human Gate check sees it.
            body["approval_policy"]["ttl_seconds"] = 120
            calls = iter(range(10))
            x.policy.hook = lambda: next(calls) == 1 and x.w.clock.advance(timedelta(seconds=150))
        if fault != "missing":
            x.controls.put(x.result.audit_ref, body, broken_signature=fault == "unsigned")
        if fault == "gate-digest":
            with psycopg.connect(backends.dsn, autocommit=True) as conn:
                gate = x.controls.gate(x.result.audit_ref)
                assert gate is not None
                forged = json.loads(gate.payload)
                forged["command"]["gate_package_digest"] = r.d("wrong-gate")
                payload = canonical_bytes(forged)
                conn.execute(f'UPDATE "{x.controls.schema}".c6_gate SET payload=%s,signature=%s', (payload, x.signer.sign(payload)))
        before = x.w.ledger.records()
        with pytest.raises(r.MemoryAdmissionError) as caught:
            x.consumer.commit(x.result.audit_ref, binding=r.binding(x.ctx))
        assert caught.value.detail_code == GATE_FAULT_DETAILS[fault]
        assert x.c3.read(x.ctx.tenant_id, "Situation", x.req["target_aggregate_ref"]) is None
        if fault != "source-during-policy":
            assert x.w.ledger.records() == before
        assert x.audit.actions()[-1] == "commitMemoryPromotion.denied"


def test_live_c3_refusal_after_dispatch_is_indeterminate_never_success(backends: r.Backends) -> None:
    # The GovernedCommitPort contract does not promise that a C3 error means
    # "not committed": after dispatch the consumer reports an unknown outcome
    # for reconciliation, never success and never a definite denial.
    with workflow(backends) as x:
        x.controls.put(x.result.audit_ref, x.body)
        rival = dict(x.body["command"], command_id="urn:ocor:command:" + uuid.uuid4().hex,
                     idempotency_key="rival-" + uuid.uuid4().hex,
                     canonical_delta={"patrol_status": "rival"})
        x.c3.commit(GovernedCanonicalCommitCommand.from_mapping(rival))
        before = x.w.ledger.records()
        with pytest.raises(r.MemoryAdmissionError) as caught:
            x.consumer.commit(x.result.audit_ref, binding=r.binding(x.ctx))
        assert (caught.value.reason_code, caught.value.detail_code) == ("CONTROL_PLANE_UNAVAILABLE", "COMMIT_OUTCOME_UNKNOWN")
        state = x.c3.read(x.ctx.tenant_id, "Situation", x.req["target_aggregate_ref"])
        assert state is not None and state.revision == 1 and dict(state.state)["patrol_status"] == "rival"
        assert x.w.ledger.records() == before
        assert x.audit.actions()[-2:] == ["commitMemoryPromotion.intent", "commitMemoryPromotion.indeterminate"]


class ForgedReceiptC3:
    """Fault injection at the port: real C3 commit, drifted receipt binding."""

    def __init__(self, c3: Any) -> None:
        self.c3 = c3

    def commit(self, command: Any) -> Any:
        return replace(self.c3.commit(command), decision_ref="urn:ocor:decision:forged")


def test_live_c3_receipt_not_bound_to_command_is_indeterminate(backends: r.Backends) -> None:
    with workflow(backends) as x:
        x.controls.put(x.result.audit_ref, x.body)
        consumer = C6MemoryPromotionConsumer(
            proposals=x.s, controls=x.controls, verifier=x.signer,
            human_gate=HumanGateCoordinator(identities=x.registry, clock=x.w.clock), policy=x.policy,
            c3=ForgedReceiptC3(x.c3), clock=x.w.clock, audit=x.audit, commit_capability="canonical.commit")
        with pytest.raises(r.MemoryAdmissionError) as caught:
            consumer.commit(x.result.audit_ref, binding=r.binding(x.ctx))
        assert (caught.value.reason_code, caught.value.detail_code) == ("CONTROL_PLANE_UNAVAILABLE", "COMMIT_OUTCOME_UNKNOWN")
        assert x.audit.actions()[-2:] == ["commitMemoryPromotion.intent", "commitMemoryPromotion.indeterminate"]
        # C3 did commit: the outcome is reconciled from C3, never reported as success.
        state = x.c3.read(x.ctx.tenant_id, "Situation", x.req["target_aggregate_ref"])
        assert state is not None and state.revision == 1
