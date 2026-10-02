"""Backoff policy (design B.9).

``BackoffPolicy.delay`` is pure given its injected RNG: the jittered delay for a
given attempt count is ``min(max_s, base_s * 2 ** (attempt - 1))`` scaled by a
uniform factor in ``[0.5, 1.0]``. There is no in-process retry loop; a FAILED
event simply waits until a later cycle finds it due.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

__all__ = ["BackoffPolicy"]


@dataclass(frozen=True)
class BackoffPolicy:
    """Exponential backoff with injected jitter, so tests are deterministic."""

    base_s: float
    max_s: float
    rng: random.Random

    def delay(self, attempt_count: int) -> float:
        """Return the delay in seconds before the next attempt.

        ``attempt_count`` is the number of attempts already made (>= 1).
        """
        exponent = max(0, attempt_count - 1)
        raw = self.base_s * (2**exponent)
        capped = min(self.max_s, raw)
        return float(capped * self.rng.uniform(0.5, 1.0))
