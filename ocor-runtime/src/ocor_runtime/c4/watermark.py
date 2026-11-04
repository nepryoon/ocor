"""C4 watermark ledger port (LLD v1.1 :146, package ``ocor.c4.watermark``).

OCOR-DEV-REM-0052 (NCP-U05, NCR-C4-001 and NCR-C4-003). C4 records durably, outside the
projection store, the commits it has received and the watermarks it has confirmed (PO
decision NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 5, NCP-U05 row):

* ``observe`` records a commit delivered to the projector and not yet applied, so a lag of
  the projection behind the commits C4 has received is measured, never declared as zero
  (NFR-024, Register :180; NFR-077, :403);
* ``confirm`` records the watermark the projection reached, with its position on the branch,
  the release it was projected under and its instant; confirmations are monotonic per
  ``(store, branch)``: the same commit is idempotent, an earlier position is refused
  (LLD v1.1 :355, watermark monotono, deduplica durable);
* ``latest`` serves the last confirmed watermark, from which the served context of an
  unreachable projection is built (ADD v1.3 :1364 and :3406).

The ledger is never authoritative for the projected facts: it holds positions and instants
only (ADD v1.3 §6.2 step 7).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


class WatermarkLedgerError(RuntimeError):
    """A typed failure of the ledger: ``CONTROL_PLANE_UNAVAILABLE`` when the ledger cannot be
    read or written, ``WATERMARK_REGRESSION`` when a confirmation would move it backwards."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


@dataclass(frozen=True, slots=True)
class ConfirmedWatermark:
    store_id: str
    branch: str
    commit_id: str
    sequence: int
    release_digest: str
    confirmed_at: datetime


@runtime_checkable
class WatermarkLedgerPort(Protocol):
    def observe(self, store_id: str, branch: str, commit_id: str, *, at: datetime) -> None: ...

    def confirm(
        self, store_id: str, branch: str, commit_id: str, *, sequence: int, release_digest: str, at: datetime
    ) -> ConfirmedWatermark: ...

    def latest(self, store_id: str, branch: str) -> ConfirmedWatermark | None: ...

    def pending_since(self, store_id: str, branch: str) -> datetime | None: ...

    def clear(self, store_id: str) -> None: ...
