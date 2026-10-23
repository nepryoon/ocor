"""0058: memory is a proposal source; C6 owns controls and C3 owns commit.

RED first. The proposal port has no mutative memory/canonical/security port.
C6 consumption is a separate injected boundary, never a field of the request.
Unit fixtures exercise local refusal paths only; live cases qualify PostgreSQL,
Qdrant, OpenBao transit, the real Human Gate and C3 transaction service.
"""
from __future__ import annotations

import dataclasses
from datetime import timedelta
from typing import Any

import pytest
import test_ocor_dev_0052 as r
import test_ocor_dev_0057 as a
from ocor_runtime.kernel.canonical import canonical_digest, format_utc_timestamp
from ocor_runtime.memory.promotion import (
    MemoryPromotionError,
    MemoryPromotionService,
    PromotionProfile,
)

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
    assert result.to_mapping()["status"] == "PROPOSED"
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
    audit.events[0]["proposal"]["target_aggregate_ref"] = "forged"
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
