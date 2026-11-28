"""Round-robin proxy pool that rests proxies after failures."""

from __future__ import annotations

import itertools
import time
from collections.abc import Callable, Iterable


class ProxyPool:
    def __init__(
        self,
        proxies: Iterable[str],
        *,
        cooldown: float = 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.proxies = list(proxies)
        if not self.proxies:
            raise ValueError("at least one proxy is required")
        self.cooldown = cooldown
        self._clock = clock
        self._cycle = itertools.cycle(self.proxies)
        self._resting_until: dict[str, float] = {}

    def next(self) -> str:
        """The next proxy that is not resting. Falls back to any proxy if all are."""
        now = self._clock()
        for _ in range(len(self.proxies)):
            proxy = next(self._cycle)
            if self._resting_until.get(proxy, 0) <= now:
                return proxy
        return min(self.proxies, key=lambda p: self._resting_until.get(p, 0))

    def mark_failed(self, proxy: str) -> None:
        self._resting_until[proxy] = self._clock() + self.cooldown

    def mark_ok(self, proxy: str) -> None:
        self._resting_until.pop(proxy, None)
