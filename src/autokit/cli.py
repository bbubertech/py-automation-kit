"""Command line entry point."""

from __future__ import annotations

import argparse
import asyncio
import importlib
from collections.abc import Sequence

from autokit import __version__
from autokit.config import Settings, load_settings
from autokit.logging import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autokit", description=__doc__)
    parser.add_argument("--version", action="version", version=f"autokit {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="<command>")

    worker = commands.add_parser("worker", help="run queued jobs")
    worker.add_argument(
        "--import",
        dest="modules",
        action="append",
        default=[],
        help="module that registers tasks with @task (repeatable)",
    )
    worker.add_argument("--queue", help="queue name (default: AUTOKIT_QUEUE)")
    worker.add_argument("--burst", action="store_true", help="exit when the queue is empty")

    return parser


async def run_worker(settings: Settings, args: argparse.Namespace) -> None:
    from redis.asyncio import Redis

    from autokit.queue import RedisQueue, Worker

    for module in args.modules:
        importlib.import_module(module)

    redis = Redis.from_url(settings.redis_url)
    worker = Worker(RedisQueue(redis, args.queue or settings.queue_name))
    worker.install_signal_handlers()
    try:
        await worker.run(burst=args.burst)
    finally:
        await redis.aclose()


def main(argv: Sequence[str] | None = None) -> int:
    settings = load_settings()
    configure_logging(settings.log_level)

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "worker":
        asyncio.run(run_worker(settings, args))
        return 0

    parser.print_help()
    return 0
