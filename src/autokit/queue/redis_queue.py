"""A small reliable queue on Redis lists.

Keys (prefix ``autokit:<queue>``):
    ready       list of jobs waiting to run
    processing  list of jobs a worker has taken
    deadlines   hash job id -> unix time after which the job counts as lost
    delayed     sorted set of jobs waiting for a retry, scored by run time
    dead        list of jobs that ran out of attempts

A job moves from ready to processing atomically with LMOVE, so a crashed worker
never loses it: the reaper puts jobs whose deadline passed back on ready.
"""

from __future__ import annotations

import time
from typing import Any

from redis.asyncio import Redis

from autokit.queue.backoff import backoff_delay
from autokit.queue.jobs import Job


class RedisQueue:
    def __init__(
        self, redis: Redis, name: str = "default", visibility_timeout: float = 300
    ) -> None:
        # redis-py's inline types are narrower than what the server accepts
        # (float timeouts, bytes members), so the client is used untyped here.
        self.redis: Any = redis
        self.name = name
        self.visibility_timeout = visibility_timeout
        prefix = f"autokit:{name}"
        self.ready_key = f"{prefix}:ready"
        self.processing_key = f"{prefix}:processing"
        self.deadlines_key = f"{prefix}:deadlines"
        self.delayed_key = f"{prefix}:delayed"
        self.dead_key = f"{prefix}:dead"

    async def enqueue(
        self, name: str, payload: dict[str, Any], *, max_attempts: int = 5, delay: float = 0
    ) -> Job:
        job = Job(name=name, payload=payload, max_attempts=max_attempts)
        if delay > 0:
            await self.redis.zadd(self.delayed_key, {job.dumps(): time.time() + delay})
        else:
            await self.redis.rpush(self.ready_key, job.dumps())
        return job

    async def reserve(self, block_for: float = 1.0) -> tuple[Job, str] | None:
        """Take the next job, waiting up to `block_for` seconds. Returns it with its raw form."""
        raw = await self.redis.blmove(
            self.ready_key, self.processing_key, block_for, "LEFT", "RIGHT"
        )
        if raw is None:
            return None

        raw_str = raw.decode() if isinstance(raw, bytes) else str(raw)
        job = Job.loads(raw_str)
        await self.redis.hset(self.deadlines_key, job.id, time.time() + self.visibility_timeout)
        return job, raw_str

    async def ack(self, job: Job, raw: str) -> None:
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.lrem(self.processing_key, 1, raw)
            pipe.hdel(self.deadlines_key, job.id)
            await pipe.execute()

    async def fail(self, job: Job, raw: str, error: str) -> bool:
        """Record a failed attempt. Returns True if the job will be retried."""
        job.attempts += 1
        job.last_error = error[:500]

        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.lrem(self.processing_key, 1, raw)
            pipe.hdel(self.deadlines_key, job.id)
            if job.exhausted:
                pipe.rpush(self.dead_key, job.dumps())
            else:
                pipe.zadd(
                    self.delayed_key, {job.dumps(): time.time() + backoff_delay(job.attempts)}
                )
            await pipe.execute()

        return not job.exhausted

    async def promote_due(self, now: float | None = None) -> int:
        """Move retries whose time has come back to the ready list."""
        now = time.time() if now is None else now
        moved = 0
        for raw in await self.redis.zrangebyscore(self.delayed_key, "-inf", now):
            # ZREM returns 1 for exactly one caller, so two workers never both move a job.
            if await self.redis.zrem(self.delayed_key, raw):
                await self.redis.rpush(self.ready_key, raw)
                moved += 1
        return moved

    async def requeue_lost(self, now: float | None = None) -> int:
        """Put jobs back on ready when the worker holding them stopped reporting."""
        now = time.time() if now is None else now
        moved = 0
        for raw in await self.redis.lrange(self.processing_key, 0, -1):
            job = Job.loads(raw)
            deadline = await self.redis.hget(self.deadlines_key, job.id)
            if deadline is not None and float(deadline) > now:
                continue
            if await self.redis.lrem(self.processing_key, 1, raw):
                await self.redis.hdel(self.deadlines_key, job.id)
                await self.redis.rpush(self.ready_key, raw)
                moved += 1
        return moved

    async def sizes(self) -> dict[str, int]:
        return {
            "ready": await self.redis.llen(self.ready_key),
            "processing": await self.redis.llen(self.processing_key),
            "delayed": await self.redis.zcard(self.delayed_key),
            "dead": await self.redis.llen(self.dead_key),
        }
