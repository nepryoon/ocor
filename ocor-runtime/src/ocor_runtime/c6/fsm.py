"""C6 -- complete 44-transition FSM table and effect-persistence runtime.

OCOR-DEV-0030 built retained, executable code for the single
representative path a risk-bearing action takes through LLD v1.1
section 3.2's normative C6 workflow (Authority -> Human Gate ->
Decision -> EMISSION-FENCE). This task builds the complementary,
complete piece OCOR-DEV-0030 deliberately left out of its own smallest
slice: a runtime transition table covering all 44 approved
transitions, and a generic mechanism that durably persists a record of
whichever transition's declared effect actually fires.

The table is parsed directly from the approved LLD document with the
same closed, five-column format OCOR-DEV-0020's sealed
``spikes.c6_fsm_fidelity.generator`` already proved fidelity for
(reimplemented here rather than imported, since ``spikes/`` lies
outside ``ocor-runtime``'s own pythonpath in production, the same
precedent OCOR-DEV-0028/0037/0040 already established) and validated
against the identical sealed digests at import time: any missing,
extra, duplicate or semantically altered transition -- a wrong source,
event/guard, durable effect or destination -- raises
``FSMTableIntegrityError`` before this module can even finish
importing, failing both local startup and CI.

OCOR-DEV-REM-0053 (NCP-U07, NCR-C6-003) makes the table an executable state machine: every
transition has a source state and an event/guard (LLD v1.1 :260-305). ``apply`` reads the
current state of the action instance from an ``ActionStatePort`` under its per-action
transaction, refuses a transition whose source is not that state (``INVALID_SOURCE_STATE``),
refuses a transition without a ``GuardEvaluation`` bound to the same transition and action
(``GUARD_NOT_EVALUATED``, ``GUARD_MISMATCH``) or evaluated as unsatisfied
(``GUARD_NOT_SATISFIED``), and lets a stop observed on the evaluation snapshot win over
dispatch, retry and canonical commit (``STOP_PRECEDENCE``: ACT-T23 precedes T14, T19 and T29,
LLD v1.1 :307, ADD v1.3 :2905). The effect is persisted before the state advances, both inside
the same per-action transaction: a refused transition or a failed effect persistence leaves
the state unchanged.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from ..c3_store import require_aware
from ..errors import OCORError

LLD_SHA256 = "bd464bfef50dc5a5e1b7ffac389fdf12be57a3b545225a92cf1564dc6a01d219"
TRANSITION_TABLE_SHA256 = "de1a242107f29c9e5106a3b4894fbb15dec8a77e52a62eb8d373b28931bb6eee"
TRANSITION_TABLE_MARKER = "### 3.2 Tabella completa delle 44 transizioni"
DEFAULT_LLD_PATH = Path(__file__).resolve().parents[4] / "docs" / "OCOR_LLD_v1.1.md"


class FSMTableIntegrityError(OCORError):
    """The runtime transition table is not identical to the approved LLD table."""


class FSMTransitionError(OCORError):
    """An FSM operation was refused. ``reason_code`` identifies why
    (UNKNOWN_TRANSITION, INVALID_SOURCE_STATE, GUARD_NOT_EVALUATED,
    GUARD_MISMATCH, GUARD_NOT_SATISFIED or STOP_PRECEDENCE), mirroring the
    reason-code pattern already established by the other retained C1-C8
    components this session."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


@dataclass(frozen=True, slots=True)
class Transition:
    transition_id: str
    source: str
    guard: str
    durable_effect: str
    destination: str


def _clean(cell: str) -> str:
    return cell.strip().replace("`", "")


def parse_transition_table(lld_path: Path) -> tuple[Transition, ...]:
    """Parse only the closed five-column table under LLD section 3.2,
    refusing to proceed at all unless the document is byte-identical
    to the approved, sealed baseline."""

    content = lld_path.read_bytes()
    actual_lld_digest = hashlib.sha256(content).hexdigest()
    if actual_lld_digest != LLD_SHA256:
        raise FSMTableIntegrityError(f"approved LLD digest mismatch: {actual_lld_digest}")
    text = content.decode("utf-8")
    try:
        table = text.split(TRANSITION_TABLE_MARKER, 1)[1].lstrip().split("\n\n", 1)[0]
    except IndexError as exc:
        raise FSMTableIntegrityError("LLD section 3.2 transition table not found") from exc

    transitions: list[Transition] = []
    for line in table.splitlines():
        if not line.startswith("| `ACT-"):
            continue
        cells = [_clean(cell) for cell in line.strip().strip("|").split("|")]
        if len(cells) != 5:
            raise FSMTableIntegrityError(f"transition row must have exactly five cells: {line}")
        transitions.append(Transition(*cells))
    return tuple(transitions)


def canonical_bytes(transitions: Iterable[Transition]) -> bytes:
    body = [asdict(item) for item in transitions]
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def transition_digest(transitions: Iterable[Transition]) -> str:
    return hashlib.sha256(canonical_bytes(transitions)).hexdigest()


def validate_transition_set(transitions: Iterable[Transition]) -> tuple[Transition, ...]:
    """Fail on missing, extra, duplicate or altered transition semantics."""

    candidate = tuple(transitions)
    ids = [item.transition_id for item in candidate]
    if len(candidate) != 44:
        raise FSMTableIntegrityError(f"expected exactly 44 transitions, found {len(candidate)}")
    if len(set(ids)) != len(ids):
        raise FSMTableIntegrityError("duplicate transition id")
    if not all(
        item.transition_id.startswith("ACT-T") and item.source and item.guard and item.durable_effect and item.destination
        for item in candidate
    ):
        raise FSMTableIntegrityError("empty or malformed transition field")
    digest = transition_digest(candidate)
    if digest != TRANSITION_TABLE_SHA256:
        raise FSMTableIntegrityError(f"transition table semantic digest mismatch: {digest}")
    return candidate


def load_transitions(lld_path: Path = DEFAULT_LLD_PATH) -> tuple[Transition, ...]:
    return validate_transition_set(parse_transition_table(lld_path))


TRANSITIONS: tuple[Transition, ...] = load_transitions()


@dataclass(frozen=True, slots=True)
class PersistedEffect:
    """An immutable, durable record that a declared transition effect
    actually fired -- never mutated once persisted."""

    transition_id: str
    source: str
    destination: str
    durable_effect: str
    occurred_at: datetime
    correlation_id: str
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_aware(self.occurred_at, field="occurred_at")
        if not self.correlation_id:
            raise ValueError("a PersistedEffect requires a correlation_id")
        object.__setattr__(self, "context", MappingProxyType(dict(self.context)))


class EffectSink(Protocol):
    def persist_effect(self, record: PersistedEffect) -> None: ...


INITIAL_STATE = "[*]"
# LLD v1.1 :307: ACT-T23 precedes T14, T19 and T29.
STOP_PRECEDED_TRANSITIONS = frozenset({"ACT-T14", "ACT-T19", "ACT-T29"})
STOP_TRANSITIONS = frozenset({"ACT-T23a", "ACT-T23b"})


@dataclass(frozen=True, slots=True)
class GuardEvaluation:
    """The outcome of evaluating one transition's event/guard for one action instance on one
    evaluation snapshot (LLD v1.1 :254-256 and :260-305). ``stop_requested`` is the cancel/stop
    observed on the same snapshot: with it, ACT-T23 wins over T14, T19 and T29 (ADD v1.3 :2905).
    The guard is evaluated by the component that owns it; the FSM only accepts an evaluation
    bound to the transition, the action and an instant not after the transition."""

    transition_id: str
    correlation_id: str
    satisfied: bool
    snapshot_id: str
    evaluated_at: datetime
    stop_requested: bool = False

    def __post_init__(self) -> None:
        for name in ("transition_id", "correlation_id", "snapshot_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"a GuardEvaluation requires {name}")
        if type(self.satisfied) is not bool or type(self.stop_requested) is not bool:
            raise TypeError("satisfied and stop_requested must be booleans")
        require_aware(self.evaluated_at, field="evaluated_at")


class ActionStateTransaction(Protocol):
    """The per-action transaction of an ``ActionStatePort``: the state read when it opened and
    the only way to advance it."""

    @property
    def state(self) -> str | None: ...

    def advance(self, destination: str) -> None: ...


@runtime_checkable
class ActionStatePort(Protocol):
    """Current state of each action instance. ``transaction`` serialises the transitions of one
    action instance: the state it exposes is current for the whole transaction, and ``advance``
    is its only write. ``None`` is the initial pseudo-state ``[*]``."""

    def current_state(self, correlation_id: str) -> str | None: ...

    def transaction(self, correlation_id: str) -> AbstractContextManager[ActionStateTransaction]: ...


class _InMemoryTransaction:
    def __init__(self, store: InMemoryActionStateStore, correlation_id: str) -> None:
        self._store = store
        self._correlation_id = correlation_id
        self._state = store.current_state(correlation_id)

    @property
    def state(self) -> str | None:
        return self._state

    def advance(self, destination: str) -> None:
        if not isinstance(destination, str) or not destination or destination == INITIAL_STATE:
            raise ValueError("destination must be a state of the approved table")
        self._store._states[self._correlation_id] = destination
        self._state = destination


class InMemoryActionStateStore:
    """Process-local ``ActionStatePort``: one lock per action instance, held for the whole
    transaction, so two FSMs sharing the store never both apply a transition from the same
    state."""

    def __init__(self) -> None:
        self._states: dict[str, str] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def current_state(self, correlation_id: str) -> str | None:
        return self._states.get(correlation_id)

    @contextmanager
    def transaction(self, correlation_id: str) -> Iterator[ActionStateTransaction]:
        with self._guard:
            lock = self._locks.setdefault(correlation_id, threading.Lock())
        with lock:
            yield _InMemoryTransaction(self, correlation_id)


class GovernedActionFSM:
    """The complete, approved 44-transition C6 table as an executable state
    machine: applying a transition checks the current state of the action
    instance against the transition's source, checks the evaluation of its
    event/guard and the ACT-T23 precedence, then durably records its
    declared effect via an injected sink and advances the state, in that
    order and inside the per-action transaction of the state port."""

    def __init__(self, transitions: tuple[Transition, ...] = TRANSITIONS, *, states: ActionStatePort | None = None) -> None:
        self._by_id = {item.transition_id: item for item in transitions}
        if states is None:
            states = InMemoryActionStateStore()
        if not isinstance(states, ActionStatePort):
            raise TypeError("states must implement ActionStatePort")
        self._states = states

    @property
    def transitions(self) -> tuple[Transition, ...]:
        return tuple(self._by_id.values())

    def transition(self, transition_id: str) -> Transition:
        try:
            return self._by_id[transition_id]
        except KeyError:
            raise FSMTransitionError("UNKNOWN_TRANSITION", f"no such C6 transition: {transition_id!r}") from None

    def current_state(self, correlation_id: str) -> str | None:
        return self._states.current_state(correlation_id)

    @staticmethod
    def _check_guard(transition: Transition, guard: object, *, correlation_id: str, at: datetime) -> None:
        if guard is None:
            raise FSMTransitionError("GUARD_NOT_EVALUATED", f"{transition.transition_id} requires its event/guard evaluation")
        if (
            not isinstance(guard, GuardEvaluation)
            or guard.transition_id != transition.transition_id
            or guard.correlation_id != correlation_id
            or guard.evaluated_at > at
        ):
            raise FSMTransitionError(
                "GUARD_MISMATCH", f"the guard evaluation is not bound to {transition.transition_id} for this action"
            )
        if transition.transition_id in STOP_PRECEDED_TRANSITIONS and guard.stop_requested:
            raise FSMTransitionError(
                "STOP_PRECEDENCE", f"a stop on snapshot {guard.snapshot_id} precedes {transition.transition_id} (ACT-T23)"
            )
        if not guard.satisfied or (transition.transition_id in STOP_TRANSITIONS and not guard.stop_requested):
            raise FSMTransitionError("GUARD_NOT_SATISFIED", f"the event/guard of {transition.transition_id} is not satisfied")

    def apply(
        self,
        transition_id: str,
        *,
        sink: EffectSink | Callable[[PersistedEffect], Any],
        at: datetime,
        correlation_id: str,
        context: Mapping[str, Any] | None = None,
        guard: GuardEvaluation | None = None,
    ) -> PersistedEffect:
        transition = self.transition(transition_id)
        record = PersistedEffect(
            transition_id=transition.transition_id,
            source=transition.source,
            destination=transition.destination,
            durable_effect=transition.durable_effect,
            occurred_at=require_aware(at, field="at"),
            correlation_id=correlation_id,
            context=context or {},
        )
        self._check_guard(transition, guard, correlation_id=correlation_id, at=at)
        with self._states.transaction(correlation_id) as state:
            expected = None if transition.source == INITIAL_STATE else transition.source
            if state.state != expected:
                raise FSMTransitionError(
                    "INVALID_SOURCE_STATE",
                    f"{transition.transition_id} starts from {transition.source}, the action is in {state.state or INITIAL_STATE}",
                )
            if hasattr(sink, "persist_effect"):
                sink.persist_effect(record)
            else:
                sink(record)
            state.advance(transition.destination)
        return record
