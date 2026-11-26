"""Worker loop that runs registered task handlers."""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from collections.abc import Awaitable, Callable
from typing import Any

from autokit.queue.jobs import Job
from autokit.queue.redis_queue import RedisQueue

log = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], Awaitable[Any]]

_registry: dict[str, Handler] = {}


def task(name: str) -> Callable[[Handler], Handler]:
    """Register an async function as the handler for jobs called `name`."""

    def decorator(fn: Handler) -> Handler:
        _registry[name] = fn
        return fn

    return decorator


def registered_tasks() -> dict[str, Handler]:
    return dict(_registry)


class Worker:
    def __init__(
        self,
        queue: RedisQueue,
        handlers: dict[str, Handler] | None = None,
        *,
        job_timeout: float = 120,
        reap_every: float = 30,
    ) -> None:
        self.queue = queue
        self.handlers = handlers if handlers is not None else registered_tasks()
        self.job_timeout = job_timeout
        self.reap_every = reap_every
        self.stopping = asyncio.Event()
        self.processed = 0
        self.failed = 0
        self.last_beat = time.time()

    def install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.stop)

    def stop(self) -> None:
        log.info("stopping after the current job")
        self.stopping.set()

    async def run(self, *, burst: bool = False) -> None:
        """Process jobs until stopped. With burst=True, return once the queue is empty."""
        last_reap = 0.0
        while not self.stopping.is_set():
            self.last_beat = time.time()
            await self.queue.promote_due()
            if time.time() - last_reap >= self.reap_every:
                await self.queue.requeue_lost()
                last_reap = time.time()

            reserved = await self.queue.reserve(block_for=0.1 if burst else 1.0)
            if reserved is None:
                if burst:
                    return
                continue

            await self.process(*reserved)

    async def process(self, job: Job, raw: str) -> None:
        handler = self.handlers.get(job.name)
        if handler is None:
            await self.queue.fail(job, raw, f"no handler registered for {job.name!r}")
            self.failed += 1
            return

        started = time.perf_counter()
        try:
            await asyncio.wait_for(handler(job.payload), timeout=self.job_timeout)
        except Exception as exc:
            retried = await self.queue.fail(job, raw, f"{type(exc).__name__}: {exc}")
            self.failed += 1
            log.warning(
                "job %s (%s) failed on attempt %d: %s%s",
                job.id,
                job.name,
                job.attempts,
                exc,
                ", will retry" if retried else ", moved to dead",
            )
        else:
            await self.queue.ack(job, raw)
            self.processed += 1
            log.info("job %s (%s) done in %.2fs", job.id, job.name, time.perf_counter() - started)
