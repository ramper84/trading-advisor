from datetime import date, datetime, timezone
from unittest.mock import MagicMock

from app.retrieval.sql_retriever import (
    country_for_symbol,
    get_instrument,
    get_latest_fundamentals,
    get_monitored_symbols,
    get_recent_daily_bars,
    get_recent_observations,
)


def _conn_returning(rows):
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn, cursor


def test_country_for_symbol_mx_suffix():
    assert country_for_symbol("WALMEX.MX") == "MX"
    assert country_for_symbol("walmex.mx") == "MX"


def test_country_for_symbol_default_us():
    assert country_for_symbol("AAPL") == "US"


def test_get_instrument_returns_none_when_absent():
    conn, _ = _conn_returning([])
    assert get_instrument("NOPE", conn=conn) is None


def test_get_instrument_maps_row():
    row = ("AAPL", "Apple Inc.", "NASDAQ", "USD", "EQUITY", "Technology", "Consumer Electronics", "US")
    conn, _ = _conn_returning([row])
    instrument = get_instrument("AAPL", conn=conn)
    assert instrument.symbol == "AAPL"
    assert instrument.exchange == "NASDAQ"


def test_get_recent_observations_orders_and_limits():
    row = ("AAPL", datetime(2026, 9, 10, tzinfo=timezone.utc), 220.5, 219.0, 5_000_000.0,
           219.5, 221.0, 218.0, 240.0, 190.0, 215.0, 210.0, 3_400_000_000_000.0, "yfinance_quotes")
    conn, cursor = _conn_returning([row])
    results = get_recent_observations("AAPL", limit=5, conn=conn)
    assert len(results) == 1
    assert results[0].symbol == "AAPL"
    sql, params = cursor.execute.call_args[0]
    assert "ORDER BY observed_at DESC" in sql
    assert params == ("AAPL", 5)


def test_get_recent_daily_bars_maps_rows():
    row = ("AAPL", date(2026, 9, 9), 315.0, 319.0, 314.0, 317.2, 45_000_000.0)
    conn, _ = _conn_returning([row])
    bars = get_recent_daily_bars("AAPL", conn=conn)
    assert bars[0].close == 317.2


def test_get_latest_fundamentals_none_when_absent():
    conn, _ = _conn_returning([])
    assert get_latest_fundamentals("WALMEX.MX", conn=conn) is None


def test_get_monitored_symbols_active_only_by_default():
    conn, cursor = _conn_returning([("AAPL", datetime(2026, 9, 1, tzinfo=timezone.utc), True, "long-term hold")])
    symbols = get_monitored_symbols(conn=conn)
    assert symbols[0].symbol == "AAPL"
    sql, params = cursor.execute.call_args[0]
    assert "WHERE active = %s" in sql
    assert params == (True,)


def test_get_monitored_symbols_all_when_not_active_only():
    conn, cursor = _conn_returning([])
    get_monitored_symbols(active_only=False, conn=conn)
    sql, params = cursor.execute.call_args[0]
    assert "WHERE" not in sql
    assert params == ()
