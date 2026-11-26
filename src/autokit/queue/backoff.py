"""Retry delays: exponential growth with full jitter, capped."""

from __future__ import annotations

import random


def backoff_delay(
    attempt: int,
    *,
    base: float = 2.0,
    cap: float = 300.0,
    rng: random.Random | None = None,
) -> float:
    """Seconds to wait before retry number `attempt` (1-based).

    Full jitter spreads retries of many failing jobs over the whole window
    instead of having them hit the same service again at the same moment.
    """
    if attempt < 1:
        raise ValueError("attempt starts at 1")

    ceiling = min(cap, base * 2 ** (attempt - 1))
    return (rng or random).uniform(ceiling / 2, ceiling)
