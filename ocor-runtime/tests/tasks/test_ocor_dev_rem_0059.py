"""OCOR-DEV-REM-0059 (NCP-U11): governed memory conformance.

Unit NCP-U11 of NORMATIVE-CONFORMANCE-PLAN (2026-10-30) resolves the register
entries NCR-MEMORY-001..005 of ``reports/development/NORMATIVE_CONFORMANCE_REGISTER.json``:

* NCR-MEMORY-001 -- retrieval whose result, scores, work and error are
  independent of policy-denied items: the pre-query policy produces the
  authorised partition down to the item (LLD v1.1 §2.8.3, ``docs/OCOR_LLD_v1.1.md``
  :214), so unauthorised elements never influence content, existence, count,
  rank, score, cache or error (FR-119, Register v1.1 :268; FGM-16, LLD v1.1 :397).
* NCR-MEMORY-004 -- the contract operation ``getMemoryItemVersion`` (Governed
  Memory API 1.0.0, ``ocor-governed-memory.openapi.yaml`` :21-29, a materialised
  contract by LLD v1.1 §0.2 :26) is a governed service operation of the
  ``MemoryReadPort`` (ADD v1.3 Part II §2.2 :3761): it binds the authenticated
  GovernedContext and recalculates its digest (§2.5 :3789), evaluates policy,
  marking and lifecycle, and audits the read; an unauthorised item is
  indistinguishable from an absent one (FR-119).

Each ``test_ncr_memory_<nnn>_conforms`` was written first and run RED on the
unremediated code (``origin/main`` ``f683aa7``), then GREEN.  Qualifying cases
run on the real pinned backends of OCOR-DEV-0051 through the worlds of
OCOR-DEV-0052: PostgreSQL 16 (``OCOR_LIVE_POSTGRES_DSN``: metadata, encrypted
content objects, full-text index), Qdrant 1.15.1 (vector index) and OpenBao
2.6.2 transit.  A missing backend fails, it never skips.  Only the policy,
stop-state and audit ports are test ports (as in OCOR-DEV-0052).
"""

from __future__ import annotations

import importlib
from datetime import timedelta
from typing import Any

import pytest
import test_ocor_dev_0052 as t52
import test_ocor_dev_rem_0020 as r20
from ocor_runtime.kernel.governed_context import GovernedContext
from ocor_runtime.memory.model import MemoryAdmissionError
from ocor_runtime.memory.retrieval import MemoryRetrievalError, RetrievalAuthorization, RetrievalMode

# The live worlds of OCOR-DEV-0052: real PostgreSQL, Qdrant and OpenBao.
live_backends = t52.live_backends
backends = t52.backends

TEXT = "ration convoy schedule"
DENIED = 130


def _observe(world: t52.World, mode: RetrievalMode) -> dict[str, Any]:
    """Everything a caller or an observer of the index can see of one search."""

    try:
        response = r20.search(world, mode, text=TEXT)
    except MemoryRetrievalError as exc:
        outcome: Any = (exc.reason_code, exc.detail_code)
        explanations: Any = None
    else:
        outcome = [hit.to_mapping() for hit in response.hits]
        explanations = [dict(response.explanations[ref]) for ref in sorted(response.explanations)]
    return {
        "outcome": outcome,
        "explanations": explanations,
        "lookups": [(op, version) for op, _partition, version in r20.lookups(world)],
    }


@pytest.mark.parametrize("mode", [RetrievalMode.FULL_TEXT, RetrievalMode.VECTOR, RetrievalMode.HYBRID])
def test_ncr_memory_001_conforms(backends: t52.Backends, mode: RetrievalMode) -> None:
    """NCR-MEMORY-001: policy-denied items inside an authorised partition influence nothing.

    FR-119 (Register v1.1 :268): unauthorised elements must not influence
    content, existence, count, rank, score, cache or error.  LLD v1.1 §2.8.3
    (:214): the pre-query policy produces an authorised partition; unauthorised
    items do not influence score normalisation, rank, count, pagination, error
    or timing bucket.  FGM-16 (LLD v1.1 :397).  The same search over the same
    allowed item, without and with 130 policy-denied items matching the query
    in the same partition, returns identical hits, factors and explanations
    after the same ordered index lookups (the timing bucket is observed as the
    index work, not as a wall-clock measurement).
    """

    observed = {}
    for denied in (0, DENIED):
        world = backends.world()
        world.admit("allowed", TEXT)
        for n in range(denied):
            world.admit(f"denied-{n:03d}", TEXT)
            world.policy.denied_items.add(f"denied-{n:03d}")
        observed[denied] = _observe(world, mode)
    assert observed[0]["outcome"] != [], observed[0]
    assert isinstance(observed[0]["outcome"], list) and [h["memory_item_id"] for h in observed[0]["outcome"]] == ["allowed"]
    assert observed[DENIED] == observed[0]


# --------------------------------------------------------------------------
# NCR-MEMORY-004: getMemoryItemVersion
# --------------------------------------------------------------------------


class ReadGrantPolicy(t52.GrantPolicy):
    """The OCOR-DEV-0052 grant policy, also deciding exact-version reads."""

    def authorize_read(self, memory_item_id: str, memory_version: int, ctx: GovernedContext) -> RetrievalAuthorization:
        self.calls.append(f"read:{memory_item_id}:{memory_version}")
        if self.fail:
            raise ConnectionError("opa unavailable")
        return RetrievalAuthorization(
            permitted=self.permitted,
            decision_ref=f"decision:read:{memory_item_id}:{memory_version}",
            policy_bundle_digest=self.bundle or ctx.policy_bundle_digest,
            memory_kinds=self.kinds,
            memory_scopes=self.scopes,
            scope_bindings=dict(self.scope_bindings),
            domains=self.domains,
            denied_memory_item_ids=frozenset(self.denied_items),
        )


def _reader(world: t52.World) -> Any:
    retrieval = importlib.import_module("ocor_runtime.memory.retrieval")
    return retrieval.MemoryItemReadService(
        coordinator=world.coordinator, metadata=world.metadata, policy=world.policy, markings=world.markings,
        stop=world.stop, audit=world.audit, clock=world.clock,
    )


def _read_refused(world: t52.World, item_id: Any, version: Any, binding: Any) -> tuple[str, str]:
    with pytest.raises(MemoryAdmissionError) as caught:
        _reader(world).get_item_version(item_id, version, binding=binding)
    return caught.value.reason_code, caught.value.detail_code


def test_ncr_memory_004_conforms(backends: t52.Backends) -> None:
    """NCR-MEMORY-004: ``getMemoryItemVersion`` is a governed, policy-filtered, audited read.

    Governed Memory API 1.0.0 :21-29 (``getMemoryItemVersion``, response
    "Policy-filtered exact memory version"); LLD v1.1 §0.2 :26; ADD v1.3
    Part II §2.2 :3761 (``MemoryReadPort``) and §2.5 :3789 (the GCS digest is
    recalculated at retrieval); FR-119 (Register v1.1 :268): every retrieval
    is policy-filtered and unauthorised elements do not influence existence.
    """

    world = backends.world()
    world.policy = ReadGrantPolicy()
    first = world.admit("item", "harbour patrol schedule")
    second = world.admit("item", "harbour patrol schedule corrected", version=2)
    world.admit("secret", "harbour patrol schedule", ctx=t52.context(marking=t52.M_SECRET))
    world.admit("denied", "harbour patrol schedule")
    world.policy.denied_items.add("denied")
    caller = t52.binding()

    for record in (first, second):
        read = _reader(world).get_item_version("item", record.item.memory_version, binding=caller)
        assert read.item == record.item
        assert read.to_mapping() == record.item.to_mapping()
    events = [e for e in world.audit.events if e["action"] == "getMemoryItemVersion"]
    assert [e["memory_version_ref"] for e in events] == ["urn:ocor:memory:item:v1", "urn:ocor:memory:item:v2"]
    for event, record in zip(events, (first, second), strict=True):
        assert event["governed_context_digest"] == t52.CALLER.digest() == caller.expected.digest()
        assert event["binding_ref"] == caller.binding_ref
        assert event["item_digest"] == record.item.digest()
        assert event["audit_ref"]
    assert "read:item:1" in world.policy.calls and "materialize:urn:ocor:memory:item:v1" in world.policy.calls

    # An unauthorised item is indistinguishable from an absent one (existence is not leaked).
    absent = _read_refused(world, "absent", 1, caller)
    assert absent[0] == "MEMORY_NOT_FOUND"
    assert _read_refused(world, "denied", 1, caller) == absent
    assert _read_refused(world, "secret", 1, caller) == absent
    # A version beyond the visible item's history.
    assert _read_refused(world, "item", 3, caller)[0] == "MEMORY_VERSION_NOT_FOUND"

    # No authenticated binding, malformed path parameters, unknown stop state, no audit.
    assert _read_refused(world, "item", 1, None)[0] == "AUTHENTICATION_REQUIRED"
    for item_id, version in (("", 1), (7, 1), ("item", 0), ("item", True), ("item", "1"), ("item", 1.0)):
        assert _read_refused(world, item_id, version, caller)[0] == "MEMORY_SCHEMA_INVALID", (item_id, version)
    world.stop.fail = True
    assert _read_refused(world, "item", 1, caller)[0] == "CONTROL_PLANE_UNAVAILABLE"
    world.stop.fail = False
    world.policy.fail = True
    assert _read_refused(world, "item", 1, caller)[0] == "CONTROL_PLANE_UNAVAILABLE"
    world.policy.fail = False
    world.audit.fail = True
    assert _read_refused(world, "item", 1, caller)[0] == "CONTROL_PLANE_UNAVAILABLE"
    world.audit.fail = False

    # Lifecycle: a revoked head is no longer readable at any version.
    world.lifecycle(second, "REVOKED", "harbour patrol schedule corrected")
    assert _read_refused(world, "item", 1, caller) == absent
    assert _read_refused(world, "item", 2, caller) == absent

    # An expired item is not readable.
    world.admit("expiring", "harbour patrol schedule", expires_at=t52.NOW + timedelta(minutes=1))
    assert _reader(world).get_item_version("expiring", 1, binding=caller).item.memory_item_id == "expiring"
    world.clock.advance(timedelta(minutes=2))
    assert _read_refused(world, "expiring", 1, caller) == absent
    denied = [e for e in world.audit.events if e["action"] == "getMemoryItemVersion.denied"]
    assert {e["reason_code"] for e in denied} >= {"MEMORY_NOT_FOUND", "MEMORY_VERSION_NOT_FOUND", "MEMORY_SCHEMA_INVALID"}
    assert all(e["governed_context_digest"] == caller.expected.digest() for e in denied if e["reason_code"] == "MEMORY_NOT_FOUND")
