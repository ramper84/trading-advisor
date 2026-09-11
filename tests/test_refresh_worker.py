import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.ingest import refresh_worker
from app.ingest.catalog import load_catalog

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data_catalog.yaml"


def _make_fake_conn(symbols: list[str], instrument_exists: bool = True) -> MagicMock:
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.return_value = [(s,) for s in symbols]
    cursor.fetchone.return_value = (1,) if instrument_exists else None
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    return conn


@pytest.fixture(autouse=True)
def _neutralize_all_dispatchers(monkeypatch):
    """run_once iterates every included catalog source; without this, a
    test exercising one dispatcher would also fire real network calls for
    every other source (Finnhub, EDGAR, yfinance, RSS, FRED, Banxico) —
    violating this project's own "no network calls in tests" rule."""
    for name in list(refresh_worker._PER_SYMBOL_REFRESH):
        monkeypatch.setitem(refresh_worker._PER_SYMBOL_REFRESH, name, lambda *a, **k: None)
    monkeypatch.setattr(refresh_worker, "refresh_economic_data", lambda *a, **k: None)
    monkeypatch.setattr(refresh_worker, "refresh_instrument_if_new", lambda *a, **k: None)


def test_run_once_does_nothing_with_no_monitored_symbols(monkeypatch):
    catalog = load_catalog(CATALOG_PATH)
    conn = _make_fake_conn([])
    monkeypatch.setattr(refresh_worker, "get_connection", lambda: conn)

    called = []
    monkeypatch.setitem(refresh_worker._PER_SYMBOL_REFRESH, "yfinance_quotes", lambda *a: called.append("x"))

    refresh_worker.run_once(catalog, {})

    assert called == []


def test_run_once_calls_due_source_for_each_symbol(monkeypatch):
    catalog = load_catalog(CATALOG_PATH)
    conn = _make_fake_conn(["AAPL", "MSFT"])
    monkeypatch.setattr(refresh_worker, "get_connection", lambda: conn)

    called = []
    monkeypatch.setitem(
        refresh_worker._PER_SYMBOL_REFRESH,
        "yfinance_quotes",
        lambda symbol, source, c: called.append(symbol),
    )

    last_run: dict[str, float] = {}
    refresh_worker.run_once(catalog, last_run)

    assert called == ["AAPL", "MSFT"]
    assert "yfinance_quotes" in last_run


def test_run_once_skips_sources_not_yet_due(monkeypatch):
    catalog = load_catalog(CATALOG_PATH)
    conn = _make_fake_conn(["AAPL"])
    monkeypatch.setattr(refresh_worker, "get_connection", lambda: conn)

    called = []
    monkeypatch.setitem(
        refresh_worker._PER_SYMBOL_REFRESH,
        "yfinance_quotes",
        lambda symbol, source, c: called.append(symbol),
    )

    last_run = {"yfinance_quotes": time.monotonic()}  # just ran — 300s cadence, not due again
    refresh_worker.run_once(catalog, last_run)

    assert called == []


def test_run_once_dispatches_economic_sources_separately_from_per_symbol(monkeypatch):
    """banxico_sie/fred_economic_data are economy-wide, not per-symbol —
    they must go through refresh_economic_data exactly once per due check,
    not once per monitored symbol."""
    catalog = load_catalog(CATALOG_PATH)
    conn = _make_fake_conn(["AAPL", "MSFT"])
    monkeypatch.setattr(refresh_worker, "get_connection", lambda: conn)

    economic_calls = []
    monkeypatch.setattr(refresh_worker, "refresh_economic_data", lambda source, c: economic_calls.append(source.name))

    refresh_worker.run_once(catalog, {})

    assert economic_calls.count("fred_economic_data") == 1
    assert economic_calls.count("banxico_sie") == 1


def test_run_once_calls_instrument_refresh_once_per_symbol(monkeypatch):
    catalog = load_catalog(CATALOG_PATH)
    conn = _make_fake_conn(["AAPL", "MSFT"], instrument_exists=False)
    monkeypatch.setattr(refresh_worker, "get_connection", lambda: conn)

    instrument_calls = []
    monkeypatch.setattr(
        refresh_worker,
        "refresh_instrument_if_new",
        lambda symbol, source, c: instrument_calls.append(symbol),
    )

    refresh_worker.run_once(catalog, {})

    assert instrument_calls == ["AAPL", "MSFT"]


def test_has_instrument_row_reflects_cursor_result():
    conn = _make_fake_conn(["AAPL"], instrument_exists=True)
    assert refresh_worker._has_instrument_row(conn, "AAPL") is True

    conn_missing = _make_fake_conn(["AAPL"], instrument_exists=False)
    assert refresh_worker._has_instrument_row(conn_missing, "AAPL") is False


def test_get_monitored_symbols_reads_active_only():
    conn = _make_fake_conn(["AAPL", "MSFT"])
    assert refresh_worker.get_monitored_symbols(conn) == ["AAPL", "MSFT"]


def test_refresh_quotes_routes_finnhub_source_to_finnhub_call(monkeypatch):
    """finnhub_quotes must poll Finnhub specifically, never fall through to
    yfinance-first get_quote() — that fallback belongs to Phase 10's
    live-read path, not the scheduled per-vendor poll."""
    catalog = load_catalog(CATALOG_PATH)
    finnhub_source = catalog.get("finnhub_quotes")
    yfinance_source = catalog.get("yfinance_quotes")

    calls = []
    monkeypatch.setattr(refresh_worker.market_data, "get_quote_finnhub", lambda s: calls.append(("finnhub", s)) or _fake_quote(s, "finnhub_quotes"))
    monkeypatch.setattr(refresh_worker.market_data, "get_quote_yfinance", lambda s: calls.append(("yfinance", s)) or _fake_quote(s, "yfinance_quotes"))
    monkeypatch.setattr(refresh_worker, "insert_observations", lambda records, conn=None: None)

    refresh_worker.refresh_quotes("AAPL", finnhub_source, conn=MagicMock())
    refresh_worker.refresh_quotes("AAPL", yfinance_source, conn=MagicMock())

    assert calls == [("finnhub", "AAPL"), ("yfinance", "AAPL")]


def _fake_quote(symbol, source_name):
    from datetime import datetime, timezone

    from app.services.market_data import Quote

    return Quote(symbol=symbol, price=1.0, previous_close=None, volume=None, observed_at=datetime.now(timezone.utc), source_name=source_name)
