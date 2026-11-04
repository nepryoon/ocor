"""C5 replay and authorised reprocessing requests (LLD v1.1 :165, ADD v1.3 :286 and :2577-2700).

"Replay dichiara window e reason, preserva event ID, non bypassa policy e non pubblica due
volte un canonical effect": a ``ReplayRequest`` declares a bounded ingest-time window and a
reason and names the requesting principal and its authority; a ``ReprocessRequest`` (port
``ReprocessAuthorized``) releases one quarantined event behind the operator gate. Both are
authorised by the C5 policy port before any read.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ReplayRequest:
    subscription_id: str
    window_start: datetime
    window_end: datetime
    reason: str
    requested_by: str
    authority_ref: str

    def well_formed(self) -> bool:
        texts = (self.subscription_id, self.reason, self.requested_by, self.authority_ref)
        if not all(isinstance(value, str) and value.strip() for value in texts):
            return False
        for moment in (self.window_start, self.window_end):
            if not isinstance(moment, datetime) or moment.tzinfo is None or moment.utcoffset() is None:
                return False
        return self.window_start < self.window_end


@dataclass(frozen=True, slots=True)
class ReprocessRequest:
    quarantine_id: str
    subscription_id: str
    reason: str
    requested_by: str
    authority_ref: str
