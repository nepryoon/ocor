"""C7 causal jobs: the ``L2 asynchronous-compute`` lifecycle and its runner.

OCOR-DEV-REM-0057 (NCP-U09 of NORMATIVE-CONFORMANCE-PLAN (2026-10-30), ``NCR-C7-004``):

- a causal run is a job of ``L2 asynchronous-compute`` with the lifecycle
  ``queued -> running -> paused | cancelled | completed | failed | expired`` of ADD v1.3
  §4.2 :3026-3030; budget, quota, progress, cancellation, timeout and backpressure are
  mandatory and the timeout never makes a partial result valid (:3032);
- a client submits a ``ScenarioRunSpec``, observes the job, cancels it and retrieves a
  result that is versioned and bound to the pinned spec (Register FR-161 :402); cancel
  and timeout release the resources of the job and are audited (FR-103 :244); a
  cancelled causal job releases its resources within ``PT30S`` (ADD v1.3 :2927; LLD v1.1
  :357: the C7 job is cancellable with resource release and a sealed result);
- the ledger is the C7 job ledger on PostgreSQL (``c7.adapters.postgres_jobs``); the
  runner executes the prepared run in a separate worker process, so that cancellation,
  pause and timeout act on the computation itself: the process is stopped, resumed or
  terminated, and its resources are released and audited by the ledger.
"""

from __future__ import annotations

import multiprocessing
import os
import signal
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from multiprocessing.connection import Connection
from typing import Any, Protocol, runtime_checkable

from .runtime import CausalOutcome, CausalRuntimeError, outcome_document, outcome_from_document
from .scenario_overlay import ScenarioBranch
from .scenario_run import CausalModelTrustRoot, PreparedRun, ScenarioRunSpec, prepare_scenario_run

JOB_STATES = ("queued", "running", "paused", "cancelled", "completed", "failed", "expired")
TERMINAL_STATES = frozenset({"cancelled", "completed", "failed", "expired"})
ACTIVE_STATES = frozenset({"queued", "running", "paused"})
# ADD v1.3 :3029: queued -> running -> paused | cancelled | completed | failed | expired. A
# queued or paused job can still be cancelled or expire; a paused job resumes to running.
TRANSITIONS: Mapping[str, frozenset[str]] = {
    "queued": frozenset({"running", "cancelled", "expired"}),
    "running": frozenset({"paused", "cancelled", "completed", "failed", "expired"}),
    "paused": frozenset({"running", "cancelled", "expired"}),
}
RESOURCE_RELEASE_DEADLINE = timedelta(seconds=30)  # ADD v1.3 :2927
RETRY_SAFETY = ("SAFE_TO_RETRY", "NOT_SAFE_TO_RETRY")


class CausalJobError(CausalRuntimeError):
    """A job operation failed closed. ``code`` names the reason; the message never
    carries credentials or server text."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True, slots=True)
class CausalJob:
    """The observable state of one job (FR-161: identifier, state, progress, timeout,
    result reference)."""

    job_id: str
    principal: str
    spec_digest: str
    state: str
    progress: str
    deadline: datetime
    overdue: bool
    result_digest: str | None
    outcome_status: str | None
    technical_failure: str | None
    retry_safety: str | None
    submitted_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class JobTransition:
    """One audited transition (or refusal) of the ledger, append-only."""

    seq: int
    job_id: str | None
    from_state: str | None
    to_state: str
    actor: str
    reason: str
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class JobResource:
    """A resource held by a running job, with its release instant."""

    job_id: str
    resource: str
    quantity: int
    acquired_at: datetime
    released_at: datetime | None


@dataclass(frozen=True, slots=True)
class JobResult:
    """The versioned result of a completed job, bound to the pinned spec digest."""

    job_id: str
    spec_digest: str
    result_version: int
    outcome: CausalOutcome


@runtime_checkable
class CausalJobLedger(Protocol):
    """The C7 job ledger port. Every transition outside ``TRANSITIONS`` is refused with
    ``INVALID_TRANSITION`` and leaves no trace but the refusal; every transition and
    every refused submission is audited with its actor and reason."""

    def submit(self, spec: ScenarioRunSpec, *, actor: str) -> CausalJob: ...

    def job(self, job_id: str) -> CausalJob: ...

    def spec(self, job_id: str) -> ScenarioRunSpec: ...

    def start(self, job_id: str, *, actor: str, resources: Mapping[str, int]) -> CausalJob: ...

    def report_progress(self, job_id: str, progress: str, *, actor: str) -> CausalJob: ...

    def pause(self, job_id: str, *, actor: str, reason: str) -> CausalJob: ...

    def resume(self, job_id: str, *, actor: str, reason: str) -> CausalJob: ...

    def cancel(self, job_id: str, *, actor: str, reason: str) -> CausalJob: ...

    def expire(self, job_id: str, *, actor: str) -> CausalJob: ...

    def fail(self, job_id: str, *, actor: str, technical_failure: str, retry_safety: str) -> CausalJob: ...

    def complete(self, job_id: str, outcome: CausalOutcome, *, actor: str) -> CausalJob: ...

    def release_resources(self, job_id: str, *, actor: str) -> tuple[JobResource, ...]: ...

    def resources(self, job_id: str) -> tuple[JobResource, ...]: ...

    def transitions(self, job_id: str) -> tuple[JobTransition, ...]: ...

    def refusals(self, principal: str) -> tuple[JobTransition, ...]: ...

    def result(self, job_id: str) -> JobResult: ...


# --- the worker process -----------------------------------------------------------------------


def _worker(connection: Connection, payload: Mapping[str, Any]) -> None:
    """Executes one prepared run and sends back the outcome document and its digest.
    Any exception is reported by its type name only."""
    try:
        outcome = PreparedRun.from_payload(payload).execute()
        connection.send(("outcome", outcome_document(outcome), outcome.reproducibility_digest))
    except Exception as exc:  # noqa: BLE001 - reported to the runner as a typed failure
        connection.send(("error", type(exc).__name__, ""))
    finally:
        connection.close()


@dataclass(frozen=True, slots=True)
class RunInputs:
    """What the runner needs besides the spec: the overlay branch and revision of the
    hypothesis, the signed model and the factual set."""

    branch: ScenarioBranch
    revision: int
    model_envelope: Mapping[str, Any]
    factual_rows: Any


class CausalJobRunner:
    """Runs queued jobs of a ``CausalJobLedger`` in worker processes.

    The runner reads the spec back from the ledger (never from the caller), prepares the
    run through the overlay (``prepare_scenario_run``), starts the job with its
    resources, and supervises the worker: a ``paused`` job's worker is stopped
    (``SIGSTOP``) and resumed (``SIGCONT``) with the job; a ``cancelled`` job's worker is
    terminated and its resources released; an overdue job is expired, its worker
    terminated, and nothing of a partial computation is kept. A completed outcome is
    verified against its digest, sealed through the overlay store and recorded."""

    def __init__(
        self,
        ledger: CausalJobLedger,
        *,
        overlay: Any,
        trust_root: CausalModelTrustRoot,
        expected_release_digest: str,
        actor: str = "c7-job-runner",
        poll_interval: float = 0.05,
        on_worker: Callable[[int], None] | None = None,
    ) -> None:
        self._ledger = ledger
        self._overlay = overlay
        self._trust_root = trust_root
        self._expected_release = expected_release_digest
        self._actor = actor
        self._poll = poll_interval
        self._on_worker = on_worker
        self._context = multiprocessing.get_context("spawn")

    def run(self, job_id: str, inputs: RunInputs) -> CausalJob:
        spec = self._ledger.spec(job_id)
        prepared = prepare_scenario_run(
            spec,
            overlay=self._overlay,
            branch=inputs.branch,
            revision=inputs.revision,
            model_envelope=inputs.model_envelope,
            trust_root=self._trust_root,
            factual_rows=inputs.factual_rows,
            expected_release_digest=self._expected_release,
        )
        samples = int(spec.budget["max_samples"])
        if isinstance(prepared, PreparedRun):
            samples = int(prepared.model["samples"])
        self._ledger.start(job_id, actor=self._actor, resources={"worker_process": 1, "samples": samples})
        if isinstance(prepared, CausalOutcome):
            return self._finish(job_id, prepared)
        self._ledger.report_progress(job_id, "0.1", actor=self._actor)
        receiver, sender = self._context.Pipe(duplex=False)
        process = self._context.Process(target=_worker, args=(sender, prepared.to_payload()), daemon=True)
        process.start()
        sender.close()
        if self._on_worker is not None and process.pid is not None:
            self._on_worker(process.pid)
        try:
            return self._supervise(job_id, process, receiver)
        finally:
            self._stop(process)
            receiver.close()

    def _supervise(self, job_id: str, process: Any, receiver: Connection) -> CausalJob:
        stopped = False
        while True:
            job = self._ledger.job(job_id)
            if job.state in TERMINAL_STATES:
                self._stop(process)
                self._ledger.release_resources(job_id, actor=self._actor)
                return self._ledger.job(job_id)
            if job.overdue:
                self._stop(process)
                self._ledger.expire(job_id, actor=self._actor)
                self._ledger.release_resources(job_id, actor=self._actor)
                return self._ledger.job(job_id)
            if job.state == "paused" and not stopped:
                os.kill(process.pid, signal.SIGSTOP)
                stopped = True
            elif job.state == "running" and stopped:
                os.kill(process.pid, signal.SIGCONT)
                stopped = False
            if not stopped and receiver.poll(self._poll):
                try:
                    kind, document, digest = receiver.recv()
                except (EOFError, OSError):
                    return self._lost(job_id)
                if kind != "outcome":
                    return self._failed(job_id, "WORKER_ERROR", "SAFE_TO_RETRY")
                try:
                    outcome = outcome_from_document(document, digest)
                except CausalRuntimeError:
                    return self._failed(job_id, "WORKER_RESULT_INVALID", "SAFE_TO_RETRY")
                return self._finish(job_id, outcome)
            if stopped:
                process.join(self._poll)
            if not process.is_alive() and not receiver.poll():
                return self._lost(job_id)

    def _lost(self, job_id: str) -> CausalJob:
        return self._failed(job_id, "WORKER_LOST", "SAFE_TO_RETRY")

    def _failed(self, job_id: str, technical_failure: str, retry_safety: str) -> CausalJob:
        if self._ledger.job(job_id).state in TERMINAL_STATES:
            self._ledger.release_resources(job_id, actor=self._actor)
            return self._ledger.job(job_id)
        self._ledger.fail(job_id, actor=self._actor, technical_failure=technical_failure, retry_safety=retry_safety)
        self._ledger.release_resources(job_id, actor=self._actor)
        return self._ledger.job(job_id)

    def _finish(self, job_id: str, outcome: CausalOutcome) -> CausalJob:
        try:
            self._overlay.seal_result(outcome)
        except Exception:  # noqa: BLE001 - any seal failure leaves the job failed and retryable
            return self._failed(job_id, "SEAL_UNAVAILABLE", "SAFE_TO_RETRY")
        try:
            self._ledger.complete(job_id, outcome, actor=self._actor)
        except CausalJobError as error:
            if error.code not in {"JOB_EXPIRED", "INVALID_TRANSITION"}:
                raise
        self._ledger.release_resources(job_id, actor=self._actor)
        return self._ledger.job(job_id)

    @staticmethod
    def _stop(process: Any) -> None:
        if process.pid is None or not process.is_alive():
            process.join(0)
            return
        try:
            os.kill(process.pid, signal.SIGCONT)
        except ProcessLookupError:
            process.join(0)
            return
        process.terminate()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join(5)
