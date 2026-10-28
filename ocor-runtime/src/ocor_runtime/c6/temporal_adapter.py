"""C6 -- Temporal runtime adapter behind the existing ports (OCOR-DEV-REM-0039).

Change set b. of the PO normative decision OCOR-DEV-0060-BA-SELECTED-COMPONENTS
(2026-10-26): the BA-05 candidate component of ADD v1.3 Part I §2.6 (Temporal with
its own PostgreSQL) backs two ports that already exist, without changing them:

* ``TemporalLeaseState`` implements ``kernel.governance.LeaseStatePort``. One
  workflow per scope serialises every update, so stop-epoch precedence,
  stale-worker fencing, revocation, the trusted time window and at-most-once
  consumption are evaluated atomically at emission exactly as the in-process
  ``InMemoryLeaseState`` reference does, and survive worker and process loss.
  Every evaluated delivery attempt is preserved (FR-081).
* ``TemporalEffectSink`` implements ``c6.fsm.EffectSink``: one workflow per
  action durably records each declared transition effect; a duplicate delivery
  is persisted once and a conflicting re-delivery is refused.

The ports are synchronous and the SDK is asynchronous: ``TemporalC6Runtime``
owns one event loop on a dedicated thread, the client and, when asked, the
in-process worker. Every Temporal failure or timeout surfaces as
``TemporalAdapterError``; ``LeaseConsumptionLedger`` maps it to
``CONTROL_PLANE_UNAVAILABLE``, so an ambiguous outcome never authorises an
emission. The workflow code lives in ``temporal_workflows``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import uuid
from collections.abc import Coroutine, Mapping, Sequence
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar

from google.protobuf.duration_pb2 import Duration
from temporalio.api.workflowservice.v1 import (
    DescribeNamespaceRequest,
    GetSystemInfoRequest,
    RegisterNamespaceRequest,
)
from temporalio.client import (
    Client,
    WithStartWorkflowOperation,
    WorkflowHandle,
    WorkflowUpdateFailedError,
)
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

from ..errors import OCORError
from ..kernel.governance import (
    CORRELATION_ZERO,
    GovernanceFault,
    LeaseStateDecision,
    LeaseStateOutcome,
    TrustedClock,
    _aware,
)
from .fsm import PersistedEffect
from .temporal_workflows import (
    ACTION_EFFECTS_WORKFLOW,
    LEASE_STATE_WORKFLOW,
    ActionEffectsWorkflow,
    LeaseStateWorkflow,
)

DEFAULT_TEMPORAL_ADDRESS = "127.0.0.1:17233"
DEFAULT_NAMESPACE = "ocor-c6"
NAMESPACE_RETENTION = timedelta(days=1)
DEFAULT_CALL_TIMEOUT = timedelta(seconds=10)
NAMESPACE_READY_TIMEOUT = timedelta(seconds=60)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_T = TypeVar("_T")


class TemporalAdapterError(OCORError):
    """Temporal was unreachable, timed out, or refused the operation."""


def _micros(value: datetime) -> int:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError("instants crossing the Temporal boundary must be timezone-aware")
    return (value - _EPOCH) // timedelta(microseconds=1)


def _from_micros(value: int) -> datetime:
    return _EPOCH + timedelta(microseconds=value)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _workflow_failure(error: BaseException) -> ApplicationError | None:
    cause = error.cause if isinstance(error, WorkflowUpdateFailedError) else None
    return cause if isinstance(cause, ApplicationError) else None


class TemporalC6Runtime:
    """Client, event loop and optional in-process worker for the C6 workflows."""

    def __init__(
        self,
        *,
        address: str = DEFAULT_TEMPORAL_ADDRESS,
        namespace: str = DEFAULT_NAMESPACE,
        task_queue: str,
        call_timeout: timedelta = DEFAULT_CALL_TIMEOUT,
    ) -> None:
        if not address or not namespace or not task_queue:
            raise ValueError("address, namespace and task_queue are required")
        if call_timeout <= timedelta(0):
            raise ValueError("call_timeout must be positive")
        self.address = address
        self.namespace = namespace
        self.task_queue = task_queue
        self.call_timeout = call_timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client: Client | None = None
        self._worker: Worker | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._guard = threading.RLock()

    # -- lifecycle -----------------------------------------------------------------

    def start(self) -> None:
        with self._guard:
            if self._client is not None:
                return
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=loop.run_forever, name=f"ocor-c6-temporal-{self.task_queue}", daemon=True)
            thread.start()
            self._loop, self._thread = loop, thread
            try:
                self._client = self._run(Client.connect(self.address, namespace=self.namespace))
            except BaseException:
                self.close()
                raise

    def close(self) -> None:
        with self._guard:
            loop, thread = self._loop, self._thread
            if loop is None:
                return
            try:
                self.stop_worker()
            finally:
                loop.call_soon_threadsafe(loop.stop)
                if thread is not None:
                    thread.join(timeout=30)
                loop.close()
                self._loop = self._thread = None
                self._client = None

    def _run(self, coroutine: Coroutine[Any, Any, _T], *, timeout: timedelta | None = None) -> _T:
        loop = self._loop
        if loop is None:
            coroutine.close()
            raise TemporalAdapterError("the Temporal runtime is not started")
        limit = (timeout or self.call_timeout).total_seconds()
        future = asyncio.run_coroutine_threadsafe(asyncio.wait_for(coroutine, limit), loop)
        try:
            return future.result(timeout=limit + 5)
        except (asyncio.TimeoutError, FutureTimeoutError) as exc:
            future.cancel()
            raise TemporalAdapterError(f"Temporal call exceeded {limit:g} s; outcome unknown") from exc
        except (TemporalAdapterError, TypeError, ValueError):
            raise
        except Exception as exc:
            raise TemporalAdapterError(f"Temporal call failed: {exc}") from exc

    @property
    def client(self) -> Client:
        if self._client is None:
            raise TemporalAdapterError("the Temporal runtime is not started")
        return self._client

    def ensure_namespace(self) -> None:
        """Register the namespace if absent and wait until it serves workflows."""
        self._run(self._ensure_namespace(), timeout=NAMESPACE_READY_TIMEOUT + timedelta(seconds=10))

    async def _ensure_namespace(self) -> None:
        client = self.client
        retention = Duration()
        retention.FromTimedelta(NAMESPACE_RETENTION)
        try:
            await client.workflow_service.register_namespace(
                RegisterNamespaceRequest(namespace=self.namespace, workflow_execution_retention_period=retention)
            )
        except RPCError as exc:
            if exc.status is not RPCStatusCode.ALREADY_EXISTS:
                raise
        deadline = asyncio.get_running_loop().time() + NAMESPACE_READY_TIMEOUT.total_seconds()
        while True:
            try:
                await client.workflow_service.describe_namespace(DescribeNamespaceRequest(namespace=self.namespace))
                probe = await client.start_workflow(
                    LEASE_STATE_WORKFLOW,
                    {"stop_epoch": 0, "fencing_tokens": {}, "revoked_lease_ids": []},
                    id=f"ocor-c6-namespace-probe/{uuid.uuid4().hex}",
                    task_queue=self.task_queue,
                )
                await probe.terminate(reason="namespace readiness probe")
                return
            except RPCError as exc:
                if exc.status is not RPCStatusCode.NOT_FOUND or asyncio.get_running_loop().time() > deadline:
                    raise
                await asyncio.sleep(1)

    def server_version(self) -> str:
        response = self._run(self.client.workflow_service.get_system_info(GetSystemInfoRequest()))
        return str(response.server_version)

    # -- worker --------------------------------------------------------------------

    def start_worker(self) -> None:
        with self._guard:
            if self._worker is not None:
                return
            self._run(self._start_worker())

    async def _start_worker(self) -> None:
        runner = SandboxedWorkflowRunner(restrictions=SandboxRestrictions.default.with_passthrough_modules("ocor_runtime"))
        worker = Worker(
            self.client,
            task_queue=self.task_queue,
            workflows=[LeaseStateWorkflow, ActionEffectsWorkflow],
            workflow_runner=runner,
        )
        self._worker = worker
        self._worker_task = asyncio.get_running_loop().create_task(worker.run())

    def stop_worker(self) -> None:
        with self._guard:
            if self._worker is None:
                return
            try:
                self._run(self._stop_worker(), timeout=timedelta(seconds=30))
            finally:
                self._worker = None
                self._worker_task = None

    async def _stop_worker(self) -> None:
        worker, task = self._worker, self._worker_task
        if worker is not None:
            await worker.shutdown()
        if task is not None:
            await task

    # -- workflow administration -------------------------------------------------------

    def _handle(self, workflow_id: str) -> WorkflowHandle[Any, Any]:
        return self.client.get_workflow_handle(workflow_id)

    def workflow_status(self, workflow_id: str) -> str:
        description = self._run(self._handle(workflow_id).describe())
        status = description.status
        return status.name if status is not None else "UNKNOWN"

    def cancel_workflow(self, workflow_id: str) -> None:
        self._run(self._handle(workflow_id).cancel())

    def terminate_workflow(self, workflow_id: str, *, reason: str) -> None:
        self._run(self._handle(workflow_id).terminate(reason=reason))


class TemporalLeaseState:
    """Durable ``LeaseStatePort`` backed by one Temporal workflow per scope."""

    def __init__(self, runtime: TemporalC6Runtime, workflow_id: str) -> None:
        self._runtime = runtime
        self.workflow_id = workflow_id

    @staticmethod
    def workflow_id_for(scope: str) -> str:
        if not isinstance(scope, str) or not scope:
            raise ValueError("scope must be non-empty")
        return f"ocor-c6-lease-state/{scope}"

    @classmethod
    def create(
        cls,
        runtime: TemporalC6Runtime,
        *,
        scope: str,
        stop_epoch: int,
        fencing_tokens: Mapping[str, int],
        revoked_lease_ids: Sequence[str] = (),
    ) -> TemporalLeaseState:
        """Start a new scope; an existing one is never re-initialised."""
        if isinstance(stop_epoch, bool) or not isinstance(stop_epoch, int) or stop_epoch < 0:
            raise ValueError("stop_epoch must be a non-negative integer")
        tokens = dict(fencing_tokens)
        if any(
            not isinstance(action_id, str)
            or not action_id
            or isinstance(token, bool)
            or not isinstance(token, int)
            or token < 1
            for action_id, token in tokens.items()
        ):
            raise ValueError("fencing tokens require action ids and positive integers")
        if isinstance(revoked_lease_ids, (str, bytes, bytearray)) or any(
            not isinstance(lease_id, str) or not lease_id for lease_id in revoked_lease_ids
        ):
            raise ValueError("revoked lease ids must be a sequence of non-empty strings")
        workflow_id = cls.workflow_id_for(scope)
        initial = {"stop_epoch": stop_epoch, "fencing_tokens": tokens, "revoked_lease_ids": list(revoked_lease_ids)}
        try:
            runtime._run(
                runtime.client.start_workflow(
                    LEASE_STATE_WORKFLOW,
                    initial,
                    id=workflow_id,
                    task_queue=runtime.task_queue,
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                    id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
                )
            )
        except TemporalAdapterError as exc:
            if isinstance(exc.__cause__, WorkflowAlreadyStartedError):
                raise TemporalAdapterError(f"LEASE_STATE_EXISTS: scope {scope!r} already exists") from exc
            raise
        return cls(runtime, workflow_id)

    @classmethod
    def attach(cls, runtime: TemporalC6Runtime, *, scope: str) -> TemporalLeaseState:
        """Attach to a running scope, for example after worker or process loss."""
        workflow_id = cls.workflow_id_for(scope)
        status = runtime.workflow_status(workflow_id)
        if status != "RUNNING":
            raise TemporalAdapterError(f"LEASE_STATE_NOT_RUNNING: scope {scope!r} is {status}")
        return cls(runtime, workflow_id)

    def _update(self, name: str, *args: Any) -> Any:
        handle = self._runtime._handle(self.workflow_id)
        return self._runtime._run(handle.execute_update(name, args=list(args)))

    def _query(self, name: str, *args: Any) -> Any:
        handle = self._runtime._handle(self.workflow_id)
        return self._runtime._run(handle.query(name, args=list(args)))

    def set_stop_epoch(self, stop_epoch: int) -> None:
        if isinstance(stop_epoch, bool) or not isinstance(stop_epoch, int):
            raise TypeError("stop_epoch must be an integer")
        try:
            self._update("set_stop_epoch", stop_epoch)
        except TemporalAdapterError as exc:
            failure = _workflow_failure(exc.__cause__) if exc.__cause__ is not None else None
            if failure is not None and failure.type == "STOP_EPOCH_BACKWARDS":
                raise ValueError("stop_epoch cannot move backwards") from exc
            raise

    def set_fencing_token(self, action_instance_id: str, fencing_token: int) -> None:
        if (
            not isinstance(action_instance_id, str)
            or not action_instance_id
            or isinstance(fencing_token, bool)
            or not isinstance(fencing_token, int)
            or fencing_token < 1
        ):
            raise ValueError("a valid action id and positive fencing token are required")
        try:
            self._update("set_fencing_token", action_instance_id, fencing_token)
        except TemporalAdapterError as exc:
            failure = _workflow_failure(exc.__cause__) if exc.__cause__ is not None else None
            if failure is not None and failure.type == "FENCING_TOKEN_BACKWARDS":
                raise ValueError("fencing token cannot move backwards") from exc
            raise

    def revoke(self, lease_id: str) -> None:
        if not isinstance(lease_id, str) or not lease_id:
            raise ValueError("lease_id must be non-empty")
        self._update("revoke", lease_id)

    def consume_if_current(
        self,
        *,
        clock: TrustedClock,
        lease_id: str,
        action_instance_id: str,
        stop_epoch: int,
        fencing_token: int,
        emission_attempt: int,
        issued_at: datetime,
        expires_at: datetime,
    ) -> LeaseStateDecision:
        try:
            now = _aware("authoritative now", clock.now(), CORRELATION_ZERO)
        except (AttributeError, GovernanceFault, OSError, RuntimeError, TypeError, ValueError):
            return LeaseStateDecision(LeaseStateOutcome.CONTROL_PLANE_UNAVAILABLE, None)
        request = {
            "lease_id": lease_id,
            "action_instance_id": action_instance_id,
            "stop_epoch": stop_epoch,
            "fencing_token": fencing_token,
            "emission_attempt": emission_attempt,
            "issued_at_us": _micros(issued_at),
            "expires_at_us": _micros(expires_at),
            "now_us": _micros(now),
            "evaluated_at": _stamp(now),
        }
        outcome = self._update("consume_if_current", request)
        return LeaseStateDecision(LeaseStateOutcome(outcome), now)

    def consumption(self, lease_id: str) -> tuple[str, int] | None:
        value = self._query("consumption", lease_id)
        if value is None:
            return None
        action, attempt = value
        return (str(action), int(attempt))

    def attempts(self) -> list[dict[str, Any]]:
        return list(self._query("attempts"))


class TemporalEffectSink:
    """Durable ``EffectSink``: one Temporal workflow per action correlation id."""

    def __init__(self, runtime: TemporalC6Runtime) -> None:
        self._runtime = runtime

    @staticmethod
    def workflow_id(correlation_id: str) -> str:
        if not isinstance(correlation_id, str) or not correlation_id:
            raise ValueError("correlation_id must be non-empty")
        return f"ocor-c6-action/{correlation_id}"

    @staticmethod
    def _payload(record: PersistedEffect) -> dict[str, Any]:
        context = dict(record.context)
        json.dumps(context, allow_nan=False)  # TypeError/ValueError before any network call
        body = {
            "transition_id": record.transition_id,
            "source": record.source,
            "destination": record.destination,
            "durable_effect": record.durable_effect,
            "occurred_at": _stamp(record.occurred_at),
            "occurred_at_us": _micros(record.occurred_at),
            "correlation_id": record.correlation_id,
            "context": context,
        }
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        return {
            "idempotency_key": f"{record.transition_id}@{body['occurred_at_us']}",
            "digest": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "record": body,
        }

    def persist_effect(self, record: PersistedEffect) -> None:
        """Persist ``record`` once; the idempotency key is ``transition_id@occurred_at``.

        A retry must pass the original ``PersistedEffect`` unchanged: a record rebuilt with a
        new ``occurred_at`` has a different key and is stored as a distinct effect.
        """
        effect = self._payload(record)
        workflow_id = self.workflow_id(record.correlation_id)
        runtime = self._runtime

        async def update_with_start() -> Any:
            # The operation owns an asyncio future, so it is built on the runtime loop.
            operation: WithStartWorkflowOperation[Any, Any] = WithStartWorkflowOperation(
                ACTION_EFFECTS_WORKFLOW,
                {"correlation_id": record.correlation_id},
                id=workflow_id,
                task_queue=runtime.task_queue,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            )
            return await runtime.client.execute_update_with_start_workflow(
                "persist_effect", effect, start_workflow_operation=operation
            )

        try:
            runtime._run(update_with_start())
        except TemporalAdapterError as exc:
            failure = _workflow_failure(exc.__cause__) if exc.__cause__ is not None else None
            if failure is not None and failure.type in {"EFFECT_CONFLICT", "EFFECT_INVALID"}:
                raise TemporalAdapterError(str(failure.message)) from exc
            raise

    def effects(self, correlation_id: str) -> list[PersistedEffect]:
        handle = self._runtime._handle(self.workflow_id(correlation_id))
        records = self._runtime._run(handle.query("effects"))
        return [
            PersistedEffect(
                transition_id=item["transition_id"],
                source=item["source"],
                destination=item["destination"],
                durable_effect=item["durable_effect"],
                occurred_at=_from_micros(item["occurred_at_us"]),
                correlation_id=item["correlation_id"],
                context=item["context"],
            )
            for item in records
        ]
