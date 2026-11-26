import random
import time
from typing import Any

import pytest
from fakeredis import FakeAsyncRedis

from autokit.queue import Job, RedisQueue, Worker, backoff_delay


@pytest.fixture
async def queue() -> RedisQueue:
    return RedisQueue(FakeAsyncRedis(), "test", visibility_timeout=30)


def test_backoff_grows_and_is_capped() -> None:
    rng = random.Random(1)
    delays = [backoff_delay(n, base=2, cap=60, rng=rng) for n in range(1, 10)]

    assert 1 <= delays[0] <= 2
    assert 4 <= delays[2] <= 8
    assert all(d <= 60 for d in delays)
    with pytest.raises(ValueError):
        backoff_delay(0)


def test_job_round_trips_through_json() -> None:
    job = Job(name="send", payload={"to": "a@example.test"}, max_attempts=3)

    assert Job.loads(job.dumps()) == job


async def test_enqueue_reserve_and_ack(queue: RedisQueue) -> None:
    await queue.enqueue("send", {"n": 1})

    reserved = await queue.reserve(block_for=0.1)
    assert reserved is not None
    job, raw = reserved
    assert job.payload == {"n": 1}
    assert (await queue.sizes())["processing"] == 1

    await queue.ack(job, raw)
    assert await queue.sizes() == {"ready": 0, "processing": 0, "delayed": 0, "dead": 0}


async def test_failed_job_is_retried_later_then_buried(queue: RedisQueue) -> None:
    await queue.enqueue("flaky", {}, max_attempts=2)

    job, raw = await queue.reserve(block_for=0.1) or pytest.fail("no job")
    assert await queue.fail(job, raw, "boom") is True
    assert (await queue.sizes())["delayed"] == 1

    assert await queue.promote_due(now=time.time() + 1000) == 1
    job, raw = await queue.reserve(block_for=0.1) or pytest.fail("no job")
    assert job.attempts == 1

    assert await queue.fail(job, raw, "boom again") is False
    assert await queue.sizes() == {"ready": 0, "processing": 0, "delayed": 0, "dead": 1}


async def test_jobs_of_a_crashed_worker_are_put_back(queue: RedisQueue) -> None:
    await queue.enqueue("long", {})
    await queue.reserve(block_for=0.1)

    assert await queue.requeue_lost(now=time.time()) == 0
    assert await queue.requeue_lost(now=time.time() + 31) == 1
    assert (await queue.sizes())["ready"] == 1


async def test_worker_runs_handlers_and_counts_results(queue: RedisQueue) -> None:
    seen: list[int] = []

    async def ok(payload: dict[str, Any]) -> None:
        seen.append(payload["n"])

    async def broken(payload: dict[str, Any]) -> None:
        raise RuntimeError("nope")

    for n in range(3):
        await queue.enqueue("ok", {"n": n})
    await queue.enqueue("broken", {}, max_attempts=1)
    await queue.enqueue("unknown", {}, max_attempts=1)

    worker = Worker(queue, {"ok": ok, "broken": broken})
    await worker.run(burst=True)

    assert seen == [0, 1, 2]
    assert worker.processed == 3
    assert worker.failed == 2
    assert (await queue.sizes())["dead"] == 2


async def test_worker_enforces_the_job_timeout(queue: RedisQueue) -> None:
    import asyncio

    async def slow(payload: dict[str, Any]) -> None:
        await asyncio.sleep(5)

    await queue.enqueue("slow", {}, max_attempts=1)
    worker = Worker(queue, {"slow": slow}, job_timeout=0.05)
    await worker.run(burst=True)

    assert worker.failed == 1
