"""C8 -- tool boundary: sandbox, budgets and kill switch.

Wires together, for every model/tool call, five real fail-closed
bindings, all enforced BEFORE any tool effect ever runs:

* **capability-bound** -- a real lease authorized by the sealed
  ``ocor_runtime.c6_capabilities.CapabilityAuthority`` (never
  self-granted; a revoked or unknown lease is refused here, before
  anything else, so nothing is charged or attempted on its behalf);
* **purpose-bound** -- a validated
  ``ocor_runtime.kernel.governed_context.GovernedContext`` (sealed,
  reused unmodified) that already fails closed on a missing purpose
  at construction, revalidated here defensively;
* **marking-bound** -- a real clearance check via the sealed
  ``ocor_runtime.c4_marking.MarkingEngine.require_authorized``;
* **stop-bound** -- a real emergency-stop epoch fence via
  OCOR-DEV-0044's sealed
  ``ocor_runtime.c6.safety.EmergencyStopController.guard_dispatch``;
* **budget-bound** -- a real token charge via the sealed
  ``ocor_runtime.c8_agent.TokenBudget.consume``, raised before the
  tool is ever attempted, never refunded or bypassed after the fact.

Only once every one of the five gates has passed does the actual tool
expression ever reach the sealed
``ocor_runtime.c8_agent.StrictSandbox`` for real AST-whitelisted
execution -- an escape-syntax attempt is refused there, exactly as it
always was, before the registered tool function itself is ever
called. A successful call returns an immutable ``ToolCallReceipt``
recording every gate it passed; a refused call never reaches the
sandbox at all for a capability/purpose/marking/stop/budget denial,
and never reaches the registered tool function for an escape-syntax
denial -- no tool effect in either case.

OCOR-DEV-REM-0027 (LLD v1.1 sections 1.4, 4.3 and 6; ADD v1.3 section
5.5) makes the stop binding preemptive at every tool dispatch:

* the runtime binds its ``CapabilityAuthority`` to its own
  ``EmergencyStopController``, so every lease carries the trusted
  ``stop_epoch`` it was issued at; a lease from another epoch (issued
  before a stop, even after a dual-control reset) or bound to no epoch
  never dispatches, and the epoch presented by the caller is only
  checked against the lease, never trusted;
* every registered tool the expression calls must be covered by the
  lease, checked before anything is charged or run and again at each
  dispatch (a lease revoked mid-expression stops the next tool);
* each tool dispatch is fenced against the controller's current epoch
  and runs on a worker thread the runtime supervises: a stop accepted
  while it runs, or the per-call deadline (at most the ``<=10 s``
  containment target), cancels it cooperatively through
  ``cancellation_checkpoint`` and refuses the call at once with
  ``execution_unknown`` set (ADD v1.3 section 5.5 points 4-6), and no
  further tool of the expression is ever dispatched;
* a tool that does not cooperate is preempted (repair 1, VF-001 of the
  verdict ``OCOR-DEV-REM-0027-f48452c64777-0``): the runtime raises
  ``ToolPreempted`` -- a ``BaseException``, so an ordinary ``except
  Exception`` in the tool cannot swallow it -- asynchronously in the
  worker thread, which stops the tool at its next interpreter step,
  before any effect that would follow a blocking wait.

Residual limit, declared rather than claimed closed: in-process
preemption acts between interpreter steps. A registered tool that
catches ``BaseException`` or performs its effect inside a single native
call that is already running cannot be preempted here; its outcome stays
``execution_unknown`` and goes to reconciliation (ADD v1.3 section 5.5
points 5-6). Tools are registered by the platform, never by the model,
whose expressions cannot catch exceptions.
"""

from __future__ import annotations

import ast
import contextvars
import ctypes
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping

from ..c3_store import require_aware
from ..c4_marking import MarkingEngine, MarkingSet
from ..c6.safety import EmergencyStopController, SafetyError
from ..c6_capabilities import CapabilityAuthority, CapabilityLease, StopEpochDenied
from ..c8_agent import StrictSandbox, TokenBudget
from ..errors import AuthorizationError, OCORError
from ..kernel.governed_context import GovernedContext


class ToolRuntimeError(OCORError):
    """A tool call was refused before producing any effect.
    ``reason_code`` identifies which of the five bindings denied it,
    mirroring the reason-code pattern already established by every
    other retained C1-C8 component this session."""

    def __init__(self, reason_code: str, message: str, *, execution_unknown: bool = False) -> None:
        self.reason_code = reason_code
        # True when a dispatched tool may still have produced (or may yet
        # produce) its effect: the outcome goes to reconciliation, never to
        # a blind retry.
        self.execution_unknown = execution_unknown
        super().__init__(f"{reason_code}: {message}")


class ToolCancelled(OCORError):
    """Raised inside a dispatched tool by ``cancellation_checkpoint`` once
    its call has been cancelled by an accepted stop or by the deadline."""


class ToolPreempted(BaseException):
    """Raised asynchronously in the worker thread of a dispatched tool that
    did not stop at its cancellation: a ``BaseException`` so that an
    ordinary ``except Exception`` in the tool cannot swallow it."""


# CPython's PyThreadState_SetAsyncExc, called with the GIL held: one
# prototype schedules an exception in a thread, the other (NULL) clears it.
_set_async_exc = ctypes.PYFUNCTYPE(ctypes.c_int, ctypes.c_ulong, ctypes.py_object)(
    ("PyThreadState_SetAsyncExc", ctypes.pythonapi)
)
_clear_async_exc = ctypes.PYFUNCTYPE(ctypes.c_int, ctypes.c_ulong, ctypes.c_void_p)(
    ("PyThreadState_SetAsyncExc", ctypes.pythonapi)
)


class _ToolWorker:
    """The supervised worker thread of one tool dispatch. ``preempt`` and
    ``_retire`` share a lock, so an asynchronous exception is only ever
    scheduled in the worker while the tool call is still running -- never
    in a thread that has retired (whose identifier may be reused)."""

    def __init__(self, name: str, call: Callable[[], Any], dispatched: _DispatchedCall) -> None:
        self._call = call
        self._dispatched = dispatched
        self._lock = threading.Lock()
        self._retired = False
        self._preempted = False
        self.done = threading.Event()
        self.outcome: dict[str, Any] = {}
        self._thread = threading.Thread(
            target=contextvars.copy_context().run, args=(self._run,), name=f"ocor-c8-tool-{name}", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        try:
            try:
                _DISPATCHED_CALL.set(self._dispatched)
                self.outcome["result"] = self._call()
            except BaseException as error:  # noqa: BLE001 - re-raised on the calling thread
                self.outcome["error"] = error
        except ToolPreempted as late:
            # preempted after the tool returned, while its outcome was stored
            self.outcome["error"] = late
        finally:
            # retired inline: a pending preemption can only be raised inside
            # this try, and none is scheduled once ``_retired`` is set
            try:
                with self._lock:
                    self._retired = True
                    _clear_async_exc(threading.get_ident(), None)
            except ToolPreempted as late:
                self.outcome.setdefault("error", late)
                with self._lock:
                    self._retired = True
            finally:
                self.done.set()

    def preempt(self) -> bool:
        """Schedule ``ToolPreempted`` once in the running tool. Returns
        whether the tool was still running."""
        with self._lock:
            ident = self._thread.ident
            if self._retired or ident is None:
                return False
            if not self._preempted:
                self._preempted = True
                _set_async_exc(ident, ToolPreempted)
            return True


DEFAULT_TOOL_CALL_DEADLINE = timedelta(seconds=5)
CONTAINMENT_TARGET = timedelta(seconds=10)
_SUPERVISION_INTERVAL_SECONDS = 0.01
# time a cancelled tool has to reach a cancellation checkpoint before it is
# preempted; far below the containment target
_COOPERATIVE_GRACE_SECONDS = 0.25


@dataclass(frozen=True, slots=True)
class _DispatchedCall:
    stop: EmergencyStopController
    fenced_epoch: int
    cancelled: threading.Event


_DISPATCHED_CALL: contextvars.ContextVar[_DispatchedCall | None] = contextvars.ContextVar(
    "ocor_c8_dispatched_tool_call", default=None
)


def _stop_accepted(stop: EmergencyStopController, fenced_epoch: int) -> bool:
    try:
        stop.guard_dispatch(fenced_epoch=fenced_epoch)
    except SafetyError:
        return True
    return False


def cancellation_requested() -> bool:
    """Whether the tool call running on this thread has been cancelled.
    Outside a call dispatched by ``ToolCallRuntime`` it is always False."""
    call = _DISPATCHED_CALL.get()
    if call is None:
        return False
    return call.cancelled.is_set() or _stop_accepted(call.stop, call.fenced_epoch)


def cancellation_checkpoint() -> None:
    """Cooperative cancellation point (LLD v1.1 section 6) for tools: raises
    ``ToolCancelled`` once the current call is cancelled, so a cooperating
    tool stops before producing its effect."""
    if cancellation_requested():
        raise ToolCancelled("tool call cancelled by an accepted emergency stop or by its deadline")


@dataclass(frozen=True, slots=True)
class ToolCallReceipt:
    tool_name: str
    lease_id: str
    purpose: str
    tokens_spent: int
    stop_epoch: int
    result: Any
    called_at: datetime


class ToolCallRuntime:
    def __init__(
        self,
        *,
        sandbox: StrictSandbox,
        authority: CapabilityAuthority,
        marking_engine: MarkingEngine,
        stop: EmergencyStopController,
        tool_call_deadline: timedelta = DEFAULT_TOOL_CALL_DEADLINE,
    ) -> None:
        if not isinstance(tool_call_deadline, timedelta) or not timedelta(0) < tool_call_deadline <= CONTAINMENT_TARGET:
            raise ValueError(f"tool_call_deadline must be positive and at most {CONTAINMENT_TARGET}")
        authority.bind_stop_controller(stop)
        self._sandbox = sandbox
        self._authority = authority
        self._marking_engine = marking_engine
        self._stop = stop
        self._deadline_seconds = tool_call_deadline.total_seconds()

    def invoke(
        self,
        tool_name: str,
        expression: str,
        *,
        bindings: Mapping[str, Any] | None,
        lease: CapabilityLease | str,
        context: GovernedContext,
        content_marking: MarkingSet,
        clearance: MarkingSet,
        budget: TokenBudget,
        estimated_tokens: int,
        stop_epoch: int,
        at: datetime,
    ) -> ToolCallReceipt:
        instant = require_aware(at, field="at")

        try:
            authorized = self._authority.authorize(
                lease, f"tool:{tool_name}", tool_name, at=instant, subject=context.effective_principal_id, consume=True
            )
        except StopEpochDenied as error:
            raise ToolRuntimeError("STOP_BOUND_DENIED", str(error)) from error
        except AuthorizationError as error:
            raise ToolRuntimeError("CAPABILITY_DENIED", str(error)) from error

        subject = context.effective_principal_id
        for called in self._called_tools(expression):
            self._authorize_tool(authorized.lease_id, called, subject=subject, at=instant)

        if not context.purpose:
            raise ToolRuntimeError("PURPOSE_REQUIRED", "a tool call requires a non-empty GovernedContext purpose")

        try:
            self._marking_engine.require_authorized(content_marking, clearance)
        except AuthorizationError as error:
            raise ToolRuntimeError("MARKING_DENIED", str(error)) from error

        lease_epoch = authorized.stop_epoch
        if lease_epoch is None:
            raise ToolRuntimeError("STOP_BOUND_DENIED", "capability lease is not bound to an emergency-stop epoch")
        if stop_epoch != lease_epoch:
            raise ToolRuntimeError(
                "STOP_BOUND_DENIED", f"presented epoch {stop_epoch} differs from the lease's stop epoch {lease_epoch}"
            )
        self._fence(lease_epoch)

        charge = budget.consume(estimated_tokens, category=f"tool:{tool_name}")

        def dispatch(name: str, call: Callable[[], Any]) -> Any:
            return self._dispatch(name, call, lease_id=authorized.lease_id, subject=subject, at=instant, fenced_epoch=lease_epoch)

        result = self._sandbox.execute(expression, bindings, dispatch=dispatch)

        return ToolCallReceipt(
            tool_name=tool_name,
            lease_id=authorized.lease_id,
            purpose=context.purpose,
            tokens_spent=charge.tokens,
            stop_epoch=lease_epoch,
            result=result,
            called_at=instant,
        )

    def _called_tools(self, expression: str) -> tuple[str, ...]:
        """Registered tools the expression can call. Anything the sandbox
        would refuse anyway (non-string, oversized, invalid syntax,
        unregistered names) is left to its own refusal."""
        if not isinstance(expression, str) or len(expression) > self._sandbox.max_source_characters:
            return ()
        try:
            tree = ast.parse(expression, mode="eval")
        except (SyntaxError, ValueError):
            return ()
        registered = set(self._sandbox.tool_names)
        return tuple(
            sorted(
                {
                    node.func.id
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in registered
                }
            )
        )

    def _authorize_tool(self, lease_id: str, name: str, *, subject: str, at: datetime) -> None:
        try:
            self._authority.authorize(lease_id, f"tool:{name}", name, at=at, subject=subject)
        except StopEpochDenied as error:
            raise ToolRuntimeError("STOP_BOUND_DENIED", f"tool {name!r} is fenced by the emergency stop: {error}") from error
        except AuthorizationError as error:
            raise ToolRuntimeError("CAPABILITY_DENIED", f"tool {name!r} is not covered by the lease: {error}") from error

    def _fence(self, fenced_epoch: int) -> None:
        try:
            self._stop.guard_dispatch(fenced_epoch=fenced_epoch)
        except SafetyError as error:
            raise ToolRuntimeError("STOP_BOUND_DENIED", str(error)) from error

    def _dispatch(
        self, name: str, call: Callable[[], Any], *, lease_id: str, subject: str, at: datetime, fenced_epoch: int
    ) -> Any:
        """Run one tool call of the expression: re-authorized and fenced
        immediately before dispatch, supervised until it ends, the stop is
        accepted or the deadline expires."""
        self._authorize_tool(lease_id, name, subject=subject, at=at)
        self._fence(fenced_epoch)

        dispatched = _DispatchedCall(stop=self._stop, fenced_epoch=fenced_epoch, cancelled=threading.Event())
        worker = _ToolWorker(name, call, dispatched)
        deadline = time.monotonic() + self._deadline_seconds
        worker.start()
        while not worker.done.wait(_SUPERVISION_INTERVAL_SECONDS):
            if _stop_accepted(self._stop, fenced_epoch):
                self._cancel(worker, dispatched)
                raise ToolRuntimeError(
                    "STOP_BOUND_DENIED",
                    f"emergency stop accepted while tool {name!r} was running: cancelled, or preempted if it "
                    "does not cooperate; its outcome is EXECUTION_UNKNOWN",
                    execution_unknown=True,
                )
            if time.monotonic() >= deadline:
                self._cancel(worker, dispatched)
                raise ToolRuntimeError(
                    "TOOL_DEADLINE_EXCEEDED",
                    f"tool {name!r} exceeded its {self._deadline_seconds} s deadline: cancelled, or preempted if it "
                    "does not cooperate; its outcome is EXECUTION_UNKNOWN",
                    execution_unknown=True,
                )
        if _stop_accepted(self._stop, fenced_epoch):
            raise ToolRuntimeError(
                "STOP_BOUND_DENIED",
                f"emergency stop accepted while tool {name!r} was running; its outcome is EXECUTION_UNKNOWN",
                execution_unknown=True,
            )
        if "error" in worker.outcome:
            raise worker.outcome["error"]
        return worker.outcome["result"]

    @staticmethod
    def _cancel(worker: _ToolWorker, dispatched: _DispatchedCall) -> None:
        """Cooperative cancellation first; a tool still running after the
        cooperative grace is preempted."""
        dispatched.cancelled.set()
        if not worker.done.wait(_COOPERATIVE_GRACE_SECONDS):
            worker.preempt()
