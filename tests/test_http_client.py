import httpx
import pytest
import respx

from autokit.http import Disallowed, HostRateLimiter, PoliteClient, ProxyPool


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def make_client(sleeps: Sleeps, **kwargs: object) -> PoliteClient:
    return PoliteClient(user_agent="autokit-test", sleep=sleeps, **kwargs)  # type: ignore[arg-type]


@respx.mock
async def test_retries_server_errors_and_honors_retry_after() -> None:
    respx.get("https://shop.test/robots.txt").respond(404)
    route = respx.get("https://shop.test/items").mock(
        side_effect=[
            httpx.Response(503, headers={"Retry-After": "7"}),
            httpx.Response(502),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    sleeps = Sleeps()

    async with make_client(sleeps, requests_per_second=1000) as client:
        response = await client.get("https://shop.test/items")

    assert response.status_code == 200
    assert route.call_count == 3
    assert 7 in sleeps.calls


@respx.mock
async def test_gives_up_after_max_retries_and_returns_the_last_answer() -> None:
    respx.get("https://shop.test/robots.txt").respond(404)
    respx.get("https://shop.test/items").respond(500)

    async with make_client(Sleeps(), max_retries=2, requests_per_second=1000) as client:
        response = await client.get("https://shop.test/items")

    assert response.status_code == 500


@respx.mock
async def test_robots_txt_is_respected() -> None:
    respx.get("https://shop.test/robots.txt").respond(200, text="User-agent: *\nDisallow: /admin\n")
    respx.get("https://shop.test/catalog").respond(200)

    async with make_client(Sleeps(), requests_per_second=1000) as client:
        assert (await client.get("https://shop.test/catalog")).status_code == 200
        with pytest.raises(Disallowed):
            await client.get("https://shop.test/admin/users")


@respx.mock
async def test_cookies_are_kept_and_can_be_saved(tmp_path: object) -> None:
    from pathlib import Path

    respx.get("https://shop.test/robots.txt").respond(404)
    respx.post("https://shop.test/login").respond(
        200, headers={"Set-Cookie": "session=abc; Path=/"}
    )
    me = respx.get("https://shop.test/me").respond(200)

    async with make_client(Sleeps(), requests_per_second=1000) as client:
        await client.post("https://shop.test/login")
        await client.get("https://shop.test/me")
        file = Path(str(tmp_path)) / "cookies.json"
        client.save_cookies(file)

    assert me.calls.last.request.headers["cookie"] == "session=abc"

    async with make_client(Sleeps(), requests_per_second=1000) as fresh:
        fresh.load_cookies(file)
        assert fresh.cookies.get("session") == "abc"


async def test_rate_limiter_spaces_requests_per_host() -> None:
    now = [100.0]
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limiter = HostRateLimiter(2, clock=lambda: now[0], sleep=fake_sleep)
    for _ in range(3):
        await limiter.wait("a.test")
    await limiter.wait("b.test")

    assert sleeps == [0.5, 0.5]


def test_proxy_pool_skips_resting_proxies() -> None:
    now = [0.0]
    pool = ProxyPool(["http://p1", "http://p2"], cooldown=30, clock=lambda: now[0])

    pool.mark_failed("http://p1")
    assert [pool.next() for _ in range(3)] == ["http://p2"] * 3

    now[0] = 31
    assert {pool.next(), pool.next()} == {"http://p1", "http://p2"}
