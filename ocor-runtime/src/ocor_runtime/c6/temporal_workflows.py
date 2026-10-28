"""C6 -- deterministic Temporal workflow definitions (OCOR-DEV-REM-0039).

Workflow code is replayed by the Temporal worker, so this module imports only
the standard library pieces that are deterministic and the Temporal SDK. All
values crossing the boundary are JSON primitives prepared by
``temporal_adapter``; instants are integer microseconds since the Unix epoch so
comparisons are exact.

``LeaseStateWorkflow`` is the durable form of ``InMemoryLeaseState``: one
workflow per lease-state scope serialises every update, so the evaluation order
and the at-most-once consumption of ``consume_if_current`` are the reference
ones. ``ActionEffectsWorkflow`` is the durable form of a C6 ``EffectSink`` for
one action. Neither workflow ever treats a cancellation request as an outcome:
after a dispatch nothing is presumed cancelled, state is only carried forward.
"""

from __future__ import annotations

import asyncio
from typing import Any

from temporalio import workflow
from temporalio.exceptions import ApplicationError

LEASE_STATE_WORKFLOW = "OcorC6LeaseState"
ACTION_EFFECTS_WORKFLOW = "OcorC6ActionEffects"


def _refuse(reason_code: str, message: str) -> ApplicationError:
    return ApplicationError(f"{reason_code}: {message}", type=reason_code, non_retryable=True)


def _positive(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


async def _carry_forward() -> None:
    """Wait until history should roll over; a cancellation request is ignored."""
    while True:
        try:
            await workflow.wait_condition(
                lambda: workflow.info().is_continue_as_new_suggested() and workflow.all_handlers_finished()
            )
            return
        except asyncio.CancelledError:
            continue


@workflow.defn(name=LEASE_STATE_WORKFLOW)
class LeaseStateWorkflow:
    @workflow.init
    def __init__(self, initial: dict[str, Any]) -> None:
        self._stop_epoch: int = initial["stop_epoch"]
        self._tokens: dict[str, int] = dict(initial["fencing_tokens"])
        self._revoked: list[str] = list(initial["revoked_lease_ids"])
        self._consumed: dict[str, list[Any]] = {key: list(value) for key, value in initial.get("consumed", {}).items()}
        self._attempts: list[dict[str, Any]] = list(initial.get("attempts", []))

    @workflow.run
    async def run(self, initial: dict[str, Any]) -> None:
        await _carry_forward()
        workflow.continue_as_new(self._snapshot())

    def _snapshot(self) -> dict[str, Any]:
        return {
            "stop_epoch": self._stop_epoch,
            "fencing_tokens": dict(self._tokens),
            "revoked_lease_ids": list(self._revoked),
            "consumed": {key: list(value) for key, value in self._consumed.items()},
            "attempts": list(self._attempts),
        }

    @workflow.update(name="set_stop_epoch")
    def set_stop_epoch(self, stop_epoch: int) -> None:
        self._stop_epoch = stop_epoch

    @set_stop_epoch.validator
    def _validate_stop_epoch(self, stop_epoch: int) -> None:
        if isinstance(stop_epoch, bool) or not isinstance(stop_epoch, int):
            raise _refuse("STOP_EPOCH_INVALID", "stop_epoch must be an integer")
        if stop_epoch < self._stop_epoch:
            raise _refuse("STOP_EPOCH_BACKWARDS", "stop_epoch cannot move backwards")

    @workflow.update(name="set_fencing_token")
    def set_fencing_token(self, action_instance_id: str, fencing_token: int) -> None:
        self._tokens[action_instance_id] = fencing_token

    @set_fencing_token.validator
    def _validate_fencing_token(self, action_instance_id: str, fencing_token: int) -> None:
        if not _identifier(action_instance_id) or not _positive(fencing_token):
            raise _refuse("FENCING_TOKEN_INVALID", "a valid action id and positive fencing token are required")
        current = self._tokens.get(action_instance_id)
        if current is not None and fencing_token < current:
            raise _refuse("FENCING_TOKEN_BACKWARDS", "fencing token cannot move backwards")

    @workflow.update(name="revoke")
    def revoke(self, lease_id: str) -> None:
        if lease_id not in self._revoked:
            self._revoked.append(lease_id)

    @revoke.validator
    def _validate_revoke(self, lease_id: str) -> None:
        if not _identifier(lease_id):
            raise _refuse("LEASE_ID_INVALID", "lease_id must be non-empty")

    @workflow.update(name="consume_if_current")
    def consume_if_current(self, request: dict[str, Any]) -> str:
        now = request["now_us"]
        lease_id = request["lease_id"]
        action = request["action_instance_id"]
        if now < request["issued_at_us"] or now >= request["expires_at_us"]:
            outcome = "EXPIRED"
        elif lease_id in self._revoked:
            outcome = "REVOKED"
        elif request["stop_epoch"] != self._stop_epoch:
            outcome = "STOP_EPOCH_MISMATCH"
        elif request["fencing_token"] != self._tokens.get(action):
            outcome = "FENCING_TOKEN_STALE"
        elif lease_id in self._consumed:
            outcome = "ALREADY_CONSUMED"
        else:
            self._consumed[lease_id] = [action, request["emission_attempt"]]
            outcome = "CONSUMED"
        self._attempts.append(
            {
                "lease_id": lease_id,
                "action_instance_id": action,
                "emission_attempt": request["emission_attempt"],
                "stop_epoch": request["stop_epoch"],
                "fencing_token": request["fencing_token"],
                "evaluated_at": request["evaluated_at"],
                "outcome": outcome,
            }
        )
        return outcome

    @consume_if_current.validator
    def _validate_consume(self, request: dict[str, Any]) -> None:
        expected = {
            "lease_id", "action_instance_id", "stop_epoch", "fencing_token", "emission_attempt",
            "issued_at_us", "expires_at_us", "now_us", "evaluated_at",
        }
        if not isinstance(request, dict) or set(request) != expected:
            raise _refuse("CONSUME_REQUEST_INVALID", "consume request fields differ from the contract")
        if not _identifier(request["lease_id"]) or not _identifier(request["action_instance_id"]):
            raise _refuse("CONSUME_REQUEST_INVALID", "lease and action identifiers are required")
        integers = ("stop_epoch", "fencing_token", "emission_attempt", "issued_at_us", "expires_at_us", "now_us")
        if any(isinstance(request[key], bool) or not isinstance(request[key], int) for key in integers):
            raise _refuse("CONSUME_REQUEST_INVALID", "consume request counters and instants must be integers")

    @workflow.query(name="consumption")
    def consumption(self, lease_id: str) -> list[Any] | None:
        value = self._consumed.get(lease_id)
        return list(value) if value is not None else None

    @workflow.query(name="attempts")
    def attempts(self) -> list[dict[str, Any]]:
        return list(self._attempts)


@workflow.defn(name=ACTION_EFFECTS_WORKFLOW)
class ActionEffectsWorkflow:
    @workflow.init
    def __init__(self, initial: dict[str, Any]) -> None:
        self._correlation_id: str = initial["correlation_id"]
        self._effects: list[dict[str, Any]] = list(initial.get("effects", []))
        self._digests: dict[str, str] = {item["idempotency_key"]: item["digest"] for item in self._effects}

    @workflow.run
    async def run(self, initial: dict[str, Any]) -> None:
        await _carry_forward()
        workflow.continue_as_new({"correlation_id": self._correlation_id, "effects": list(self._effects)})

    @workflow.update(name="persist_effect")
    def persist_effect(self, effect: dict[str, Any]) -> str:
        if effect["idempotency_key"] in self._digests:
            return "DUPLICATE"
        self._effects.append(dict(effect))
        self._digests[effect["idempotency_key"]] = effect["digest"]
        return "PERSISTED"

    @persist_effect.validator
    def _validate_effect(self, effect: dict[str, Any]) -> None:
        expected = {"idempotency_key", "digest", "record"}
        if not isinstance(effect, dict) or set(effect) != expected:
            raise _refuse("EFFECT_INVALID", "effect fields differ from the contract")
        record = effect["record"]
        if not isinstance(record, dict) or record.get("correlation_id") != self._correlation_id:
            raise _refuse("EFFECT_INVALID", "effect belongs to another action")
        known = self._digests.get(effect["idempotency_key"])
        if known is not None and known != effect["digest"]:
            raise _refuse("EFFECT_CONFLICT", "a different effect was already persisted under this key")

    @workflow.query(name="effects")
    def effects(self) -> list[dict[str, Any]]:
        return [dict(item["record"]) for item in self._effects]
