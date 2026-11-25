"""Settings read from environment variables, with defaults that work locally."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(f"AUTOKIT_{name}", default)


@dataclass(frozen=True, slots=True)
class Settings:
    redis_url: str = field(default_factory=lambda: _env("REDIS_URL", "redis://localhost:6379/0"))
    queue_name: str = field(default_factory=lambda: _env("QUEUE", "default"))
    user_agent: str = field(
        default_factory=lambda: _env(
            "USER_AGENT", "autokit/0.1 (+https://github.com/bbubertech/py-automation-kit)"
        )
    )
    requests_per_second: float = field(default_factory=lambda: float(_env("RPS", "2")))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))
    data_dir: str = field(default_factory=lambda: _env("DATA_DIR", "./data"))


def load_settings() -> Settings:
    return Settings()
