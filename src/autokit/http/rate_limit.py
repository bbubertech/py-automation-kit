"""Per-host spacing between requests."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


class HostRateLimiter:
    """Allow at most `per_second` requests per host, spread evenly.

    Each host has its own lock, so a slow site does not hold back requests to others.
    """

    def __init__(
        self,
        per_second: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if per_second <= 0:
            raise ValueError("per_second must be positive")
        self.interval = 1.0 / per_second
        self._clock = clock
        self._sleep = sleep
        self._next_slot: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def wait(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = self._clock()
            slot = max(now, self._next_slot.get(host, now))
            if slot > now:
                await self._sleep(slot - now)
            self._next_slot[host] = slot + self.interval
