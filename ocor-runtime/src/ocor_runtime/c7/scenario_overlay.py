"""C7 scenario overlays: the complete vendor-neutral ``ScenarioOverlayStore`` port.

OCOR-DEV-REM-0041, overlay unit (PO OCOR-DEV-0060-BA-SELECTED-COMPONENTS, change set
d; REM-0040-C7-SEALED-RESULT-PORT-DISPOSITION (2026-10-28), points 1, 3 and 9). ADD
v1.3 §4.2 defines ``ScenarioOverlayStore`` with six operations: ``openSnapshot``,
``forkScenario``, ``appendOverlay``, ``readAt``, ``sealResult`` and ``discard``.
OCOR-DEV-REM-0040 introduced ``sealResult`` and the read of a sealed result by its
digest as ``ScenarioOverlayStoreSealSubset``; this module composes that subset
unchanged -- same names, same signatures -- and adds the overlay operations.

Semantics (ADD v1.3 §4.2, Part I §2.4 ``VersionedAssertedState`` row, §2.5 rule 11):

- the baseline is a commit of the canonical branch ``main``, mounted read-only; the
  store has no ``main.write`` capability and never writes ``main``;
- every hypothesis is an append-only delta in a copy-on-write overlay isolated per
  ``(scenario_id, run_id, compartments)``; a delta is never rewritten or removed, and
  re-forking an existing run is refused (a rebase is a new run, never a rewrite);
- outbox entries replicated into a scenario overlay by ``fork_scenario`` are never
  publishable and never produce a ``DeliveryAttempt``; an overlay delta is opaque
  scenario data and can never become a canonical ``OutboxEntry``;
- ``discard`` removes the overlay only; sealed results stay immutable.

The implementation behind the port stays confined to an adapter
(``ocor_runtime.c7.adapters``). ``c7/runtime.py``, ``CausalOutcome``, contracts,
schemas and reason codes are unchanged; the ``code`` of ``ScenarioOverlayError`` is an
adapter failure code, never a ``CausalOutcome`` reason code.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..errors import OCORError
from .sealed_results import ScenarioOverlayStoreSealSubset

CANONICAL_BRANCH = "main"
SCENARIO_BRANCH_PREFIX = "scenario/"


class ScenarioOverlayError(OCORError):
    """A scenario-overlay operation failed closed. ``code`` names the reason; the
    message never carries credentials."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True, slots=True)
class ScenarioSnapshot:
    """A read-only pin of the canonical branch at one commit (``openSnapshot``)."""

    canonical_branch: str
    canonical_commit_ref: str


@dataclass(frozen=True, slots=True)
class ScenarioBranch:
    """The isolated overlay of one ``(scenario_id, run_id, compartments)`` forked from a
    snapshot (``forkScenario``). ``scenario_branch`` starts with ``scenario/``, the
    branch convention ``c7.runtime`` already enforces for causal queries."""

    scenario_id: str
    run_id: str
    compartments: tuple[str, ...]
    canonical_commit_ref: str
    scenario_branch: str


@dataclass(frozen=True, slots=True)
class OverlayDelta:
    """One append-only hypothesis delta. ``revision`` counts from 1; ``delta_digest``
    chains the delta to ``previous_digest`` (``None`` for the first delta)."""

    revision: int
    delta: Mapping[str, Any]
    delta_digest: str
    previous_digest: str | None


@dataclass(frozen=True, slots=True)
class OverlayView:
    """The overlay as of ``revision`` (``readAt``): the read-only baseline pin plus the
    first ``revision`` deltas, in order."""

    branch: ScenarioBranch
    revision: int
    deltas: tuple[OverlayDelta, ...]


@runtime_checkable
class ScenarioOverlayStore(ScenarioOverlayStoreSealSubset, Protocol):
    """The ``ScenarioOverlayStore`` port of ADD v1.3 §4.2.

    ``seal_result`` and ``read_sealed_result`` are inherited unchanged from
    ``ScenarioOverlayStoreSealSubset`` (OCOR-DEV-REM-0040). The overlay operations:

    - ``open_snapshot`` (``openSnapshot``) pins a commit of ``main``; a commit that is
      not in the history of ``main`` is refused;
    - ``fork_scenario`` (``forkScenario``) creates the overlay of one
      ``(scenario_id, run_id, compartments)`` from a snapshot; an existing run is
      never forked again;
    - ``append_overlay`` (``appendOverlay``) appends one delta and returns it with its
      revision; concurrent appends get distinct, gap-free revisions;
    - ``read_at`` (``readAt``) returns the overlay as of a revision after verifying
      the delta chain; a tampered or missing delta is rejected, never returned;
    - ``discard`` removes the overlay of a run; it returns ``False`` when the overlay
      was already absent. Sealed results are not affected.
    """

    def open_snapshot(self, canonical_commit_ref: str) -> ScenarioSnapshot: ...

    def fork_scenario(
        self, snapshot: ScenarioSnapshot, *, scenario_id: str, run_id: str, compartments: tuple[str, ...]
    ) -> ScenarioBranch: ...

    def append_overlay(self, branch: ScenarioBranch, delta: Mapping[str, Any]) -> OverlayDelta: ...

    def read_at(self, branch: ScenarioBranch, revision: int) -> OverlayView: ...

    def discard(self, branch: ScenarioBranch) -> bool: ...
