# py-automation-kit

Building blocks I reach for when writing automation jobs in Python: a Redis job queue
with retries, an async HTTP client that behaves well towards the sites it talks to,
browser flows on Playwright, and exports to Excel and PDF.

Examples only target sites made for scraping practice, such as
[books.toscrape.com](https://books.toscrape.com) and
[quotes.toscrape.com](https://quotes.toscrape.com).

Work in progress. The roadmap below tracks what is done.

## Stack

- Python 3.12, asyncio
- httpx, Redis, Playwright, BeautifulSoup
- openpyxl and ReportLab for reports
- pytest, ruff and mypy (strict) on GitHub Actions

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Settings come from `AUTOKIT_*` environment variables (`AUTOKIT_REDIS_URL`,
`AUTOKIT_RPS`, `AUTOKIT_LOG_LEVEL`, ...). See `src/autokit/config.py`.

## Job queue

```python
from autokit.queue import RedisQueue, task

@task("send_report")
async def send_report(payload: dict) -> None:
    ...

await RedisQueue(redis).enqueue("send_report", {"week": 48}, max_attempts=5)
```

```bash
autokit worker --import myproject.tasks
```

Jobs move from `ready` to `processing` with an atomic `LMOVE`, so a crashed worker never
loses one: the worker puts jobs whose visibility deadline passed back on the queue.
Failures retry with exponential backoff and full jitter; after the last attempt the job
goes to a dead list with its error. `SIGTERM` lets the current job finish first.

## HTTP client

```python
from autokit.http import PoliteClient

async with PoliteClient(user_agent="my-bot/1.0 (+contact)", requests_per_second=2) as http:
    response = await http.get("https://books.toscrape.com/")
```

- checks `robots.txt` once per site and raises `Disallowed` for blocked paths
- spaces requests per host, with a separate lock per host
- retries 429, 5xx and network errors, using `Retry-After` when the server sends it
- keeps cookies for the session; `save_cookies` / `load_cookies` reuse a login later
- optional `ProxyPool` rotates proxies and rests the ones that fail

## Roadmap

- [x] Project setup, CI
- [x] Redis job queue and worker with retries
- [x] Async HTTP client with rate limiting and retries
- [ ] Browser flows on Playwright
- [ ] Scraping pipeline and Excel/PDF reports
- [ ] Monitoring, alerts and Docker
