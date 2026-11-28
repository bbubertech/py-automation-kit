"""An async HTTP client that is polite to the sites it talks to.

- checks robots.txt before fetching
- spaces requests per host
- retries 429 and 5xx answers and network errors, honoring Retry-After
- keeps cookies for the session and can save them between runs
- can spread requests over a pool of proxies
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from email.utils import parsedate_to_datetime
from pathlib import Path
from types import TracebackType
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from autokit.http.proxies import ProxyPool
from autokit.http.rate_limit import HostRateLimiter
from autokit.queue.backoff import backoff_delay

log = logging.getLogger(__name__)

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class Disallowed(Exception):
    """robots.txt does not allow this URL for our user agent."""


class PoliteClient:
    def __init__(
        self,
        *,
        user_agent: str,
        requests_per_second: float = 2,
        max_retries: int = 4,
        timeout: float = 20,
        respect_robots: bool = True,
        proxies: ProxyPool | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.user_agent = user_agent
        self.max_retries = max_retries
        self.respect_robots = respect_robots
        self.proxies = proxies
        self.cookies = httpx.Cookies()
        self._timeout = timeout
        self._transport = transport
        self._sleep = sleep
        self._limiter = HostRateLimiter(requests_per_second, sleep=sleep)
        self._robots: dict[str, RobotFileParser] = {}
        self._clients: dict[str | None, httpx.AsyncClient] = {}

    async def __aenter__(self) -> PoliteClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self.respect_robots and not await self.allowed(url):
            raise Disallowed(url)

        host = urlsplit(url).netloc
        attempt = 0
        while True:
            attempt += 1
            await self._limiter.wait(host)
            proxy = self.proxies.next() if self.proxies else None
            try:
                response = await self._client(proxy).request(method, url, **kwargs)
            except httpx.TransportError as exc:
                if proxy and self.proxies:
                    self.proxies.mark_failed(proxy)
                if attempt > self.max_retries:
                    raise
                delay = backoff_delay(attempt, base=1, cap=30)
                log.warning("%s %s failed (%s), retrying in %.1fs", method, url, exc, delay)
                await self._sleep(delay)
                continue

            if proxy and self.proxies:
                self.proxies.mark_ok(proxy)
            self.cookies.update(response.cookies)

            if response.status_code not in RETRY_STATUSES or attempt > self.max_retries:
                return response

            delay = self._retry_after(response) or backoff_delay(attempt, base=1, cap=30)
            log.info(
                "%s %s answered %d, retrying in %.1fs", method, url, response.status_code, delay
            )
            await self._sleep(delay)

    async def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        parser = self._robots.get(origin)
        if parser is None:
            parser = RobotFileParser()
            try:
                response = await self._client(None).get(f"{origin}/robots.txt")
                lines = response.text.splitlines() if response.status_code == 200 else []
            except httpx.HTTPError:
                lines = []
            parser.parse(lines)
            self._robots[origin] = parser
        return parser.can_fetch(self.user_agent, url)

    def save_cookies(self, path: str | Path) -> None:
        data = [
            {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
            for c in self.cookies.jar
        ]
        Path(path).write_text(json.dumps(data, indent=2))

    def load_cookies(self, path: str | Path) -> None:
        file = Path(path)
        if not file.exists():
            return
        for c in json.loads(file.read_text()):
            self.cookies.set(c["name"], c["value"], domain=c["domain"], path=c["path"])

    def _client(self, proxy: str | None) -> httpx.AsyncClient:
        client = self._clients.get(proxy)
        if client is None:
            client = httpx.AsyncClient(
                headers={"User-Agent": self.user_agent},
                timeout=self._timeout,
                follow_redirects=True,
                proxy=proxy,
                transport=self._transport,
            )
            self._clients[proxy] = client
        client.cookies = self.cookies
        return client

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if not value:
            return None
        if value.isdigit():
            return float(value)
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        date = response.headers.get("Date")
        now = parsedate_to_datetime(date) if date else None
        if now is None:
            return None
        return max(0.0, (retry_at - now).total_seconds())
