from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.ingest.analyst_rating_store import insert_analyst_ratings
from app.ingest.parsers.analyst_ratings_parser import AnalystRatingRecord


def _record():
    return AnalystRatingRecord(
        symbol="AAPL",
        rated_at=datetime(2026, 9, 10, 13, 14, 37, tzinfo=timezone.utc),
        firm="TD Cowen",
        action="up",
        from_grade="Hold",
        to_grade="Buy",
        source_name="yfinance_analyst_ratings",
        reliability_tier=4,
    )


def test_insert_analyst_ratings_uses_do_nothing_on_conflict():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    count = insert_analyst_ratings([_record()], conn=conn)

    assert count == 1
    sql, params = cursor.execute.call_args[0]
    assert "ON CONFLICT (symbol, rated_at, firm) DO NOTHING" in sql
    assert params[2] == "TD Cowen"


def test_insert_analyst_ratings_noop_on_empty_list():
    conn = MagicMock()
    assert insert_analyst_ratings([], conn=conn) == 0
    conn.transaction.assert_not_called()
