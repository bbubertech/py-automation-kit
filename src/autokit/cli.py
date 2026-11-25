"""Command line entry point."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from autokit import __version__
from autokit.config import load_settings
from autokit.logging import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autokit", description=__doc__)
    parser.add_argument("--version", action="version", version=f"autokit {__version__}")
    parser.add_subparsers(dest="command", metavar="<command>")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    settings = load_settings()
    configure_logging(settings.log_level)

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    return 0
