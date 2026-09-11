"""Generic RSS parser — shared by elfinanciero_news and el_economista_news
(ADR-006). RSS has no per-symbol query, so articles are matched to a
monitored symbol/company by a keyword search over title+summary — the
client-side filter RSS forces on us, applied here once (articles/s06-04's
"one auditable cleaning layer" rule), not scattered into retrieval-time
patches.
"""

from __future__ import annotations

import time
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
        published_struct = entry.get("published_parsed")
        published_at = (
            datetime.fromtimestamp(time.mktime(published_struct), tz=timezone.utc)
            if published_struct
            else datetime.now(timezone.utc)
        )
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
