"""C5 failure taxonomy and bounded retry (LLD v1.1 :156-163, Register :205 FR-074).

| Class | Action (LLD v1.1 :160-163) |
|---|---|
| ``TRANSIENT`` | exponential backoff with bounded jitter and a retry budget |
| ``PERMANENT`` | immutable DLQ, no automatic retry |
| ``POLICY_DENIED`` | audit and non-disclosing quarantine |
| ``POISON`` | partition quarantine and operator gate |

``RetryPolicy`` is the only retry loop of the backbone: attempt ``k`` (from 0) that fails
transiently waits ``min(max_delay_s, base_delay_s * 2**k * (1 + jitter_ratio * rng()))``
before the next one, and after ``max_attempts`` attempts the budget is spent: no infinite loop.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


class FailureClass(str, Enum):
    TRANSIENT = "TRANSIENT"
    PERMANENT = "PERMANENT"
    POLICY_DENIED = "POLICY_DENIED"
    POISON = "POISON"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay_s: float = 0.2
    max_delay_s: float = 5.0
    jitter_ratio: float = 0.5
    sleep: Callable[[float], object] = field(default=time.sleep, repr=False)
    rng: Callable[[], float] = field(default=random.random, repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int) or not 1 <= self.max_attempts <= 100:
            raise ValueError("max_attempts is an integer budget between 1 and 100")
        for name in ("base_delay_s", "max_delay_s", "jitter_ratio"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int | float) or value < 0 or value != value:
                raise ValueError(f"{name} must be a finite non-negative number")
        if self.max_delay_s < self.base_delay_s or self.jitter_ratio > 1:
            raise ValueError("max_delay_s >= base_delay_s and jitter_ratio <= 1 are required")
        if not callable(self.sleep) or not callable(self.rng):
            raise TypeError("sleep and rng must be callables")

    def delay(self, attempt: int) -> float:
        """The bounded wait after the failed attempt ``attempt`` (0-based)."""
        draw = self.rng()
        if isinstance(draw, bool) or not isinstance(draw, int | float) or not 0 <= draw <= 1:
            raise ValueError("the jitter source must return a number in [0, 1]")
        return float(min(self.max_delay_s, self.base_delay_s * (2**attempt) * (1 + self.jitter_ratio * draw)))
