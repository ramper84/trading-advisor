"""Generic RSS parser — shared by elfinanciero_news and el_economista_news
(ADR-006). RSS has no per-symbol query, so articles are matched to a
monitored symbol/company by a keyword search over title+summary — the
client-side filter RSS forces on us, applied here once (articles/s06-04's
"one auditable cleaning layer" rule), not scattered into retrieval-time
patches.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser

from app.ingest.parsers.news_parser import RawArticle

# Both confirmed outlets' feeds are served to a standard browser
# User-Agent but 403 a generic client (2026-09-10 research) — every fetch
# needs one, or requests are silently rejected.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def fetch_rss_feed(feed_url: str) -> feedparser.FeedParserDict:
    return feedparser.parse(feed_url, agent=BROWSER_USER_AGENT)


def _parsed_published_at(entry: dict) -> datetime:
    """`feedparser` already normalizes `published_parsed` to a UTC
    `struct_time` — `time.mktime()` (used here originally) instead
    interprets ANY struct as the process's own LOCAL timezone, silently
    shifting every article's timestamp by the host's UTC offset. Live
    verification (2026-09-12, discovery build) caught a real ~6-hour
    future-dated skew on this exact host (`America/Mexico_City`, UTC-6)
    — confirmed by comparing freshly-ingested articles against Postgres's
    own `now()`. `calendar.timegm()` is the timezone-independent inverse
    of `time.gmtime()` and is the correct function for a struct that is
    already known to be UTC, regardless of what timezone the process
    happens to run in. This bug predates the discovery capability — it
    affected every RSS-sourced article ever ingested via `parse_rss_for_symbol`
    on a non-UTC host — not something newly introduced here."""
    published_struct = entry.get("published_parsed")
    if not published_struct:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(calendar.timegm(published_struct), tz=timezone.utc)


def parse_rss_for_symbol(
    feed: feedparser.FeedParserDict,
    symbol: str,
    company_keywords: list[str],
    source_name: str,
) -> list[RawArticle]:
    """Keep only entries whose title or summary mentions one of
    company_keywords (case-insensitive)."""
    keywords = [k.lower() for k in company_keywords]
    matched = []
    for entry in feed.entries:
        title = entry.get("title", "").strip()
        summary = entry.get("summary", "").strip()
        haystack = f"{title} {summary}".lower()
        if not any(keyword in haystack for keyword in keywords):
            continue
        published_at = _parsed_published_at(entry)
        matched.append(
            RawArticle(
                symbol=symbol,
                article_id=entry.get("id") or entry.get("link", ""),
                headline=title,
                summary=summary,
                url=entry.get("link", ""),
                published_at=published_at,
                source=source_name,
            )
        )
    return matched


@dataclass
class RawGeneralArticle:
    """Discovery's own shape (CLAUDE.md's "Extension — Discovery"), not
    `RawArticle`: a general-news item has no monitored symbol to attach —
    forcing one onto a mandatory `symbol` field would be a placeholder
    value standing in for "none", not a real one."""

    source_name: str
    headline: str
    summary: str
    url: str
    published_at: datetime


def parse_rss_general(feed: feedparser.FeedParserDict, source_name: str) -> list[RawGeneralArticle]:
    """No keyword filter — every entry in the feed is kept, since
    discovery's whole point is reading what a symbol-scoped filter would
    have discarded."""
    articles = []
    for entry in feed.entries:
        published_at = _parsed_published_at(entry)
        articles.append(
            RawGeneralArticle(
                source_name=source_name,
                headline=entry.get("title", "").strip(),
                summary=entry.get("summary", "").strip(),
                url=entry.get("link", ""),
                published_at=published_at,
            )
        )
    return articles
