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

## Roadmap

- [x] Project setup, CI
- [ ] Redis job queue and worker with retries
- [ ] Async HTTP client with rate limiting and retries
- [ ] Browser flows on Playwright
- [ ] Scraping pipeline and Excel/PDF reports
- [ ] Monitoring, alerts and Docker
