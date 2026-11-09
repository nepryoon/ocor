"""OCOR-DEV-REM-0059 (NCP-U11): governed memory conformance.

Unit NCP-U11 of NORMATIVE-CONFORMANCE-PLAN (2026-10-30) resolves the register
entries NCR-MEMORY-001..005 of ``reports/development/NORMATIVE_CONFORMANCE_REGISTER.json``:

* NCR-MEMORY-001 -- retrieval whose result, scores, work and error are
  independent of policy-denied items: the pre-query policy produces the
  authorised partition down to the item (LLD v1.1 §2.8.3, ``docs/OCOR_LLD_v1.1.md``
  :214), so unauthorised elements never influence content, existence, count,
  rank, score, cache or error (FR-119, Register v1.1 :268; FGM-16, LLD v1.1 :397).

Each ``test_ncr_memory_<nnn>_conforms`` was written first and run RED on the
unremediated code (``origin/main`` ``f683aa7``), then GREEN.  Qualifying cases
run on the real pinned backends of OCOR-DEV-0051 through the worlds of
OCOR-DEV-0052: PostgreSQL 16 (``OCOR_LIVE_POSTGRES_DSN``: metadata, encrypted
content objects, full-text index), Qdrant 1.15.1 (vector index) and OpenBao
2.6.2 transit.  A missing backend fails, it never skips.  Only the policy,
stop-state and audit ports are test ports (as in OCOR-DEV-0052).
"""

from __future__ import annotations

from typing import Any

import pytest
import test_ocor_dev_0052 as t52
import test_ocor_dev_rem_0020 as r20
from ocor_runtime.memory.retrieval import MemoryRetrievalError, RetrievalMode

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
