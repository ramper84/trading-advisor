"""Axis 2 write side for `general_news_items` (Discovery, CLAUDE.md's
"Extension — Discovery"). Idempotent on `(source_name, url)` — a real,
stable natural key here, unlike `document_chunks`'s synthetic
`document_id` needed only for multi-chunk filings.
"""

from __future__ import annotations

from typing import Optional

import psycopg

from app.ingest.parsers.rss_parser import RawGeneralArticle
from app.services.db import get_connection

_UPSERT_SQL = """
    INSERT INTO general_news_items (
        source_name, reliability_tier, headline, summary, url, published_at
    ) VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (source_name, url) DO NOTHING
"""


def upsert_general_news(
    articles: list[RawGeneralArticle],
    reliability_tier: int,
    conn: Optional[psycopg.Connection] = None,
) -> int:
    """DO NOTHING on conflict, not DO UPDATE: a general news item's content
    doesn't change once published the way a filing might get corrected —
    the URL already existing means it was already ingested."""
    if not articles:
        return 0

    def _write(c: psycopg.Connection) -> int:
        with c.transaction(), c.cursor() as cur:
            for article in articles:
                cur.execute(
                    _UPSERT_SQL,
                    (
                        article.source_name,
                        reliability_tier,
                        article.headline,
                        article.summary,
                        article.url,
                        article.published_at,
                    ),
                )
        return len(articles)

    if conn is not None:
        return _write(conn)
    with get_connection() as owned_conn:
        return _write(owned_conn)
