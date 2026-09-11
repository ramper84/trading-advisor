from datetime import date
from unittest.mock import MagicMock

from app.ingest.daily_bar_store import upsert_daily_bars
from app.ingest.parsers.daily_bar_parser import DailyBarRecord


def _record(bar_date=date(2026, 9, 9)):
    return DailyBarRecord(
        symbol="AAPL",
        bar_date=bar_date,
        open=315.49,
        high=319.15,
        low=314.0,
        close=317.2,
        volume=45_000_000.0,
        source_name="yfinance_daily_bars",
        reliability_tier=4,
    )


def test_upsert_daily_bars_writes_one_row_per_record():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    count = upsert_daily_bars([_record()], conn=conn)

    assert count == 1
    cursor.execute.assert_called_once()
    sql, params = cursor.execute.call_args[0]
    assert "ON CONFLICT (symbol, bar_date) DO UPDATE" in sql
    assert params[0] == "AAPL"
    assert params[1] == date(2026, 9, 9)


def test_upsert_daily_bars_noop_on_empty_list():
    conn = MagicMock()
    assert upsert_daily_bars([], conn=conn) == 0
    conn.transaction.assert_not_called()
