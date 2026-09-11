"""Two independent news sources (finnhub_news, yfinance_news — ADR-006)
converging on one shared RawArticle shape. Short-form: normalizers/
canonical.py makes each article its own Document (Phase 7's chunking
note — recursive sub-chunking adds nothing to a 2-3 sentence summary).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import finnhub
import yfinance as yf


@dataclass
class RawArticle:
    symbol: str
    article_id: str
    headline: str
    summary: str
    url: str
    published_at: datetime
    source: str  # the outlet the source attributes the article to


def fetch_finnhub_news(symbol: str, api_key: str, from_date: str, to_date: str) -> list[dict]:
    return finnhub.Client(api_key=api_key).company_news(symbol, _from=from_date, to=to_date)


def parse_news(symbol: str, raw_articles: list[dict]) -> list[RawArticle]:
    """raw_articles is Finnhub's own JSON list: [{id, headline, summary,
    url, datetime, source}, ...]."""
    parsed = []
    for item in raw_articles:
        if not item.get("headline") or not item.get("summary"):
            # Disguised-null guard (articles/s06-04): an empty summary is
            # not usable content — don't manufacture a Document from it.
            continue
        parsed.append(
            RawArticle(
                symbol=symbol,
                article_id=str(item["id"]),
                headline=item["headline"],
                summary=item["summary"],
                url=item.get("url", ""),
                published_at=datetime.fromtimestamp(item["datetime"], tz=timezone.utc),
                source=item.get("source", "unknown"),
            )
        )
    return parsed


def fetch_yfinance_news(symbol: str) -> list[dict]:
    """No API key required — same package as yfinance_quotes."""
    return yf.Ticker(symbol).news


def parse_yfinance_news(symbol: str, raw_articles: list[dict]) -> list[RawArticle]:
    """raw_articles is yfinance's own Ticker.news list: [{id, content:
    {title, summary, pubDate, provider: {displayName}, canonicalUrl:
    {url}}}, ...] — confirmed against a live call 2026-09-10; yfinance's
    news shape has changed across versions before, so if this starts
    silently returning nothing, check the raw shape again before assuming
    the symbol just has no news.
    """
    parsed = []
    for item in raw_articles:
        content = item.get("content", {})
        title = content.get("title")
        summary = content.get("summary")
        if not title or not summary:
            continue
        url = (content.get("canonicalUrl") or content.get("clickThroughUrl") or {}).get("url", "")
        published_at = datetime.fromisoformat(content["pubDate"]) if content.get("pubDate") else datetime.now(timezone.utc)
        parsed.append(
            RawArticle(
                symbol=symbol,
                article_id=str(item.get("id", "")),
                headline=title,
                summary=summary,
                url=url,
                published_at=published_at,
                source=(content.get("provider") or {}).get("displayName", "Yahoo Finance"),
            )
        )
    return parsed
