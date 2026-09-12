from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.ingest.general_news_store import upsert_general_news
from app.ingest.parsers.rss_parser import RawGeneralArticle


def _article(url="https://example.mx/a"):
    return RawGeneralArticle(
        source_name="el_economista_news",
        headline="Some headline",
        summary="Some summary",
        url=url,
        published_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
    )


def test_upsert_general_news_writes_one_row_per_article():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    count = upsert_general_news([_article(), _article(url="https://example.mx/b")], reliability_tier=4, conn=conn)

    assert count == 2
    assert cursor.execute.call_count == 2
    sql, params = cursor.execute.call_args_list[0][0]
    assert "ON CONFLICT (source_name, url) DO NOTHING" in sql
    assert params[0] == "el_economista_news"
    assert params[1] == 4


def test_upsert_general_news_noop_on_empty_list():
    conn = MagicMock()
    assert upsert_general_news([], reliability_tier=4, conn=conn) == 0
    conn.transaction.assert_not_called()
