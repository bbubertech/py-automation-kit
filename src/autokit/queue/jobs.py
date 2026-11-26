from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Job:
    name: str
    payload: dict[str, Any]
    max_attempts: int = 5
    attempts: int = 0
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    last_error: str | None = None

    def dumps(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)

    @classmethod
    def loads(cls, raw: str | bytes) -> Job:
        return cls(**json.loads(raw))

    @property
    def exhausted(self) -> bool:
        return self.attempts >= self.max_attempts
