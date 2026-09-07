"""Generic HTTP fetch, shared by sec_edgar_filings and finnhub_news.
reddit_mentions uses PRAW directly (a different client model, not raw
HTTP) — see ingest/parsers/reddit_parser.py.
"""

from __future__ import annotations

import httpx

DEFAULT_TIMEOUT = 10.0


def fetch_json(url: str, *, params: dict | None = None, headers: dict | None = None) -> dict:
    response = httpx.get(url, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    return response.json()


def fetch_text(url: str, *, params: dict | None = None, headers: dict | None = None) -> str:
    response = httpx.get(url, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    return response.text
