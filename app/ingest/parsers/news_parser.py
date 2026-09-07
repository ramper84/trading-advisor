"""Finnhub /company-news JSON -> intermediate article records. Short-form:
normalizers/canonical.py makes each article its own Document (Phase 7's
chunking note — recursive sub-chunking adds nothing to a 2-3 sentence
summary).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import finnhub


@dataclass
class RawArticle:
    symbol: str
    article_id: str
    headline: str
    summary: str
    url: str
    published_at: datetime
    source: str  # the outlet Finnhub attributes the article to


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
