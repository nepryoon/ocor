"""OCOR-DEV-REM-0021: eligibility re-validated after the content read of every hit.

The independent verification of OCOR-DEV-0055 (verdict
``OCOR-DEV-0055-38b7734bd97f-0``, finding VF-002) reproduced on the real
backends that ``MemorySearchService._materialize`` re-validated a ranked
version only *before* reading its content: a revocation committed while the
content was being read still returned the revoked version as a hit, although
the module documents that a revocation during the read leaves no hit behind
and ADD v1.3 Part II §2.10 excludes a non-``ACTIVE`` head from retrieval from
the instant it is committed.

The remediation re-runs the complete eligibility check (committed exact head,
``ACTIVE``, no deletion epoch, same stage digest, live materialisation
policy) after the content read of every hit and once more over every hit
right before the audit receipt is written.  A version that changed fails the
request closed with ``CANDIDATE_CHANGED``, as the pre-read check already did,
and the refusal is an audited denial without success receipt.

Every scenario was written first and run RED on the unremediated code
(``origin/main`` ``0662051``), then GREEN.  Qualifying cases run on the real
pinned backends of the OCOR-DEV-0052 worlds: PostgreSQL 16
(``OCOR_LIVE_POSTGRES_DSN``), Qdrant 1.15.1 and OpenBao 2.6.2 transit.  A
missing backend fails, it never skips.  Only the policy, stop-state and audit
ports are test ports (as in 0052 and REM-0020).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

import pytest
import test_ocor_dev_0052 as t52
import test_ocor_dev_rem_0020 as r20
from ocor_runtime.memory.model import AdmittedMemoryVersion, GovernedMemoryItem, MemoryPolicyDecision
from ocor_runtime.memory.retrieval import RetrievalMode
from ocor_runtime.memory.stores import MemoryPartition

World = t52.World
live_backends = t52.live_backends
backends = t52.backends
search = r20.search
refused = r20.refused
denials = r20.denials
receipts = r20.receipts
refs = t52.refs

TEXT = "convoy route update"
CHANGED = ("REPRESENTATION_NOT_READY", "CANDIDATE_CHANGED")


def _intercept(world: World, on_read: Callable[[list[str]], None]) -> list[str]:
    """Run ``on_read(reads)`` right after each content read, inside the read window."""

    original = world.coordinator.read_version
    reads: list[str] = []

    def read(partition: MemoryPartition, memory_item_id: str, memory_version: int) -> Any:
        materialized = original(partition, memory_item_id, memory_version)
        reads.append(memory_item_id)
        on_read(reads)
        return materialized

    world.coordinator.read_version = read  # type: ignore[method-assign]
    return reads


def _two_items(world: World) -> dict[str, AdmittedMemoryVersion]:
    return {"x": world.admit("x", TEXT), "keep": world.admit("keep", TEXT)}


# --------------------------------------------------------------------------
# VF-002: a change committed during the read of the same hit
# --------------------------------------------------------------------------


@pytest.mark.parametrize("mode", list(RetrievalMode))
@pytest.mark.parametrize("status", ["REVOKED", "QUARANTINED"])
@pytest.mark.parametrize("position", [1, 2])
def test_a_head_left_active_during_its_own_read_leaves_no_hit(
    backends: t52.Backends, mode: RetrievalMode, status: str, position: int
) -> None:
    """The hit read at ``position`` changes during its own read; nothing is read after it."""

    world = backends.world()
    admitted = _two_items(world)
    changed: list[str] = []

    def change_current(reads: list[str]) -> None:
        if len(reads) == position and not changed:
            changed.append(world.lifecycle(admitted[reads[-1]], status, TEXT).item.version_ref)

    reads = _intercept(world, change_current)
    refused(world, mode, *CHANGED, text=TEXT)
    assert len(reads) == position  # no content is read after the changed hit
    assert changed == [f"urn:ocor:memory:{reads[-1]}:v2"]
    assert receipts(world) == [] and denials(world) == [CHANGED]


@pytest.mark.parametrize("mode", list(RetrievalMode))
def test_a_correction_committed_during_the_read_leaves_no_hit(backends: t52.Backends, mode: RetrievalMode) -> None:
    world = backends.world()
    admitted = _two_items(world)
    corrected: list[str] = []

    def correct_first(reads: list[str]) -> None:
        if not corrected:
            corrected.append(world.lifecycle(admitted[reads[0]], "ACTIVE", TEXT).item.version_ref)

    reads = _intercept(world, correct_first)
    refused(world, mode, *CHANGED, text=TEXT)
    assert len(reads) == 1 and corrected == [f"urn:ocor:memory:{reads[0]}:v2"]
    assert receipts(world) == [] and denials(world) == [CHANGED]
    # The new head is the one returned afterwards: v1 is never served again.
    expected = sorted(["urn:ocor:memory:keep:v1", "urn:ocor:memory:x:v1"])
    expected[expected.index(f"urn:ocor:memory:{reads[0]}:v1")] = corrected[0]
    assert sorted(refs(search(world, mode, text=TEXT))) == sorted(expected)


@pytest.mark.parametrize("mode", list(RetrievalMode))
def test_a_policy_revoked_during_the_read_leaves_no_hit(backends: t52.Backends, mode: RetrievalMode) -> None:
    world = backends.world()
    _two_items(world)

    class RevokesOne(t52.GrantPolicy):
        revoked: str | None = None

        def authorize_materialization(self, item: GovernedMemoryItem, ctx: Any) -> MemoryPolicyDecision:
            decision = super().authorize_materialization(item, ctx)
            if item.memory_item_id == self.revoked:
                return dataclasses.replace(decision, permitted=False)
            return decision

    policy = RevokesOne()
    world.policy = policy

    def revoke_first(reads: list[str]) -> None:
        if policy.revoked is None:
            policy.revoked = reads[0]

    reads = _intercept(world, revoke_first)
    refused(world, mode, *CHANGED, text=TEXT)
    assert len(reads) == 1
    assert receipts(world) == [] and denials(world) == [CHANGED]


@pytest.mark.parametrize("mode", list(RetrievalMode))
def test_a_hit_revoked_while_an_earlier_hit_is_read_is_never_read(backends: t52.Backends, mode: RetrievalMode) -> None:
    world = backends.world()
    admitted = _two_items(world)
    revoked: list[str] = []

    def revoke_the_other(reads: list[str]) -> None:
        if not revoked:
            other = "keep" if reads[0] == "x" else "x"
            revoked.append(world.lifecycle(admitted[other], "REVOKED", TEXT).item.version_ref)

    reads = _intercept(world, revoke_the_other)
    refused(world, mode, *CHANGED, text=TEXT)
    assert len(reads) == 1  # the revoked version's content is never read
    assert revoked and not revoked[0].startswith(f"urn:ocor:memory:{reads[0]}:")
    assert receipts(world) == [] and denials(world) == [CHANGED]


# --------------------------------------------------------------------------
# VF-002 class: a change to an earlier hit during the read of a later one
# --------------------------------------------------------------------------


@pytest.mark.parametrize("mode", list(RetrievalMode))
def test_a_hit_revoked_while_a_later_hit_is_read_leaves_no_hit(backends: t52.Backends, mode: RetrievalMode) -> None:
    world = backends.world()
    admitted = _two_items(world)
    revoked: list[str] = []

    def revoke_first(reads: list[str]) -> None:
        if len(reads) == 2 and not revoked:
            revoked.append(world.lifecycle(admitted[reads[0]], "REVOKED", TEXT).item.version_ref)

    reads = _intercept(world, revoke_first)
    refused(world, mode, *CHANGED, text=TEXT)
    assert len(reads) == 2 and revoked == [f"urn:ocor:memory:{reads[0]}:v2"]
    assert receipts(world) == [] and denials(world) == [CHANGED]


# --------------------------------------------------------------------------
# Positive counterparts: changes outside the hits never fail a search
# --------------------------------------------------------------------------


@pytest.mark.parametrize("mode", list(RetrievalMode))
def test_a_change_to_a_non_hit_during_the_read_returns_every_hit(backends: t52.Backends, mode: RetrievalMode) -> None:
    world = backends.world()
    _two_items(world)
    # A kind outside the query: never a candidate, so its change is not a hit's.
    other = world.admit(
        "other", TEXT, kind="PREFERENCE", source_kind="PREFERENCE", taint=("HUMAN_SUPPLIED",)
    )
    changed: list[str] = []

    def revoke_other(reads: list[str]) -> None:
        if not changed:
            changed.append(world.lifecycle(other, "REVOKED", TEXT).item.version_ref)

    reads = _intercept(world, revoke_other)
    response = search(world, mode, text=TEXT)
    assert sorted(refs(response)) == ["urn:ocor:memory:keep:v1", "urn:ocor:memory:x:v1"]
    assert sorted(reads) == ["keep", "x"] and changed == ["urn:ocor:memory:other:v2"]
    assert denials(world) == [] and [r["audit_ref"] for r in receipts(world)] == [response.audit_ref]


@pytest.mark.parametrize("mode", list(RetrievalMode))
def test_an_unchanged_read_returns_every_hit_with_its_receipt(backends: t52.Backends, mode: RetrievalMode) -> None:
    world = backends.world()
    _two_items(world)
    reads = _intercept(world, lambda reads: None)
    response = search(world, mode, text=TEXT)
    assert sorted(refs(response)) == ["urn:ocor:memory:keep:v1", "urn:ocor:memory:x:v1"]
    assert sorted(reads) == ["keep", "x"]
    assert denials(world) == [] and len(receipts(world)) == 1


def test_a_revocation_after_the_response_does_not_alter_the_returned_receipt(backends: t52.Backends) -> None:
    world = backends.world()
    admitted = _two_items(world)
    response = search(world, RetrievalMode.FULL_TEXT, text=TEXT)
    world.lifecycle(admitted["x"], "REVOKED", TEXT)
    assert sorted(refs(response)) == ["urn:ocor:memory:keep:v1", "urn:ocor:memory:x:v1"]
    assert refs(search(world, RetrievalMode.FULL_TEXT, text=TEXT)) == ["urn:ocor:memory:keep:v1"]


def test_qualifying_worlds_are_the_real_backends(backends: t52.Backends) -> None:
    r20.test_qualifying_worlds_use_the_real_version_2_adapters(backends)
