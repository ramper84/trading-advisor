import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.ingest import refresh_worker
from app.ingest.catalog import load_catalog

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data_catalog.yaml"

# Captured before the autouse fixture below neutralizes the module attribute,
# so the orchestration test can restore and exercise the real function.
_REAL_RUN_DISCOVERY_SCAN = refresh_worker.run_discovery_scan


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
    violating this project's own "no network calls in tests" rule.

    `run_discovery_scan` is neutralized here too — a real bug found while
    building it (2026-09-12): `run_once` now calls it unconditionally
    (discovery runs regardless of monitored symbols), and it was NOT
    covered by this fixture, so every existing test calling `run_once`
    was silently making two real, unmocked RSS fetches to
    elfinanciero_news/el_economista_news before failing later at a
    MagicMock-cursor DB read (caught by `run_once`'s own try/except, so
    no test failed — but the network calls still happened, every run)."""
    for name in list(refresh_worker._PER_SYMBOL_REFRESH):
        monkeypatch.setitem(refresh_worker._PER_SYMBOL_REFRESH, name, lambda *a, **k: None)
    monkeypatch.setattr(refresh_worker, "refresh_economic_data", lambda *a, **k: None)
    monkeypatch.setattr(refresh_worker, "refresh_instrument_if_new", lambda *a, **k: None)
    monkeypatch.setattr(refresh_worker, "run_discovery_scan", lambda *a, **k: None)


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


def test_latest_filing_date_reads_max_published_at():
    from datetime import datetime, timezone

    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = (datetime(2026, 7, 30, tzinfo=timezone.utc),)
    conn.cursor.return_value.__enter__.return_value = cursor

    result = refresh_worker._latest_filing_date(conn, "AAPL")

    assert result == datetime(2026, 7, 30, tzinfo=timezone.utc)
    sql, params = cursor.execute.call_args[0]
    assert "MAX(published_at)" in sql
    assert params == ("AAPL", "sec_edgar_filings")


def test_refresh_filings_bounds_fetch_by_latest_ingested_date(monkeypatch):
    """Regression guard (2026-09-10, live verification): without a `since`
    bound, refresh_filings re-fetched a large filer's ENTIRE tracked-form
    history from SEC on every poll (140+ document requests for AAPL alone)
    even though source_hash already made the resulting writes no-ops —
    the waste was at the fetch layer, not the write layer."""
    from datetime import datetime, timezone

    catalog = load_catalog(CATALOG_PATH)
    source = catalog.get("sec_edgar_filings")
    latest = datetime(2026, 7, 30, tzinfo=timezone.utc)

    monkeypatch.setattr(refresh_worker, "_latest_filing_date", lambda conn, symbol: latest)
    monkeypatch.setattr(refresh_worker.edgar_parser, "resolve_cik", lambda symbol, ua: "320193")

    captured = {}

    def fake_fetch_recent_filings(cik, user_agent, since=None):
        captured["since"] = since
        return []

    monkeypatch.setattr(refresh_worker.edgar_parser, "fetch_recent_filings", fake_fetch_recent_filings)
    monkeypatch.setattr(refresh_worker, "embed_and_store", lambda documents, conn=None: 0)

    refresh_worker.refresh_filings("AAPL", source, conn=MagicMock())

    assert captured["since"] == latest


def test_run_once_calls_discovery_scan_even_with_no_monitored_symbols(monkeypatch):
    """Discovery's whole point is helping a user go from zero monitored
    symbols to their first few, so it must not be gated behind the
    per-symbol refresh loop the way every other dispatcher legitimately
    is (CLAUDE.md's "Extension — Discovery")."""
    catalog = load_catalog(CATALOG_PATH)
    conn = _make_fake_conn([])
    monkeypatch.setattr(refresh_worker, "get_connection", lambda: conn)

    discovery_calls = []
    monkeypatch.setattr(refresh_worker, "run_discovery_scan", lambda c, conn: discovery_calls.append(True))

    refresh_worker.run_once(catalog, {})

    assert discovery_calls == [True]


def test_run_once_skips_discovery_scan_before_its_cadence_elapses(monkeypatch):
    catalog = load_catalog(CATALOG_PATH)
    conn = _make_fake_conn(["AAPL"])
    monkeypatch.setattr(refresh_worker, "get_connection", lambda: conn)

    discovery_calls = []
    monkeypatch.setattr(refresh_worker, "run_discovery_scan", lambda c, conn: discovery_calls.append(True))

    last_run = {refresh_worker._DISCOVERY_JOB_NAME: time.monotonic()}  # just ran
    refresh_worker.run_once(catalog, last_run)

    assert discovery_calls == []


def test_run_once_reruns_discovery_scan_once_cadence_elapses(monkeypatch):
    catalog = load_catalog(CATALOG_PATH)
    conn = _make_fake_conn(["AAPL"])
    monkeypatch.setattr(refresh_worker, "get_connection", lambda: conn)

    discovery_calls = []
    monkeypatch.setattr(refresh_worker, "run_discovery_scan", lambda c, conn: discovery_calls.append(True))

    stale = time.monotonic() - refresh_worker.DISCOVERY_SCAN_INTERVAL_SECONDS - 1
    last_run = {refresh_worker._DISCOVERY_JOB_NAME: stale}
    refresh_worker.run_once(catalog, last_run)

    assert discovery_calls == [True]
    assert last_run[refresh_worker._DISCOVERY_JOB_NAME] > stale


def test_run_discovery_scan_orchestrates_ingest_then_scan_then_persist(monkeypatch):
    """The autouse fixture neutralizes run_discovery_scan for every other
    test in this module — restore the real function here since this test
    exists specifically to exercise its own internal orchestration."""
    monkeypatch.setattr(refresh_worker, "run_discovery_scan", _REAL_RUN_DISCOVERY_SCAN)
    catalog = load_catalog(CATALOG_PATH)
    conn = MagicMock()

    fetch_calls = []
    monkeypatch.setattr(
        refresh_worker.rss_parser, "fetch_rss_feed", lambda location: fetch_calls.append(location) or "FEED"
    )

    parse_calls = []

    def fake_parse_rss_general(feed, source_name):
        parse_calls.append(source_name)
        return [f"article-from-{source_name}"]

    monkeypatch.setattr(refresh_worker.rss_parser, "parse_rss_general", fake_parse_rss_general)

    upsert_calls = []
    monkeypatch.setattr(
        refresh_worker,
        "upsert_general_news",
        lambda articles, reliability_tier, conn=None: upsert_calls.append((tuple(articles), reliability_tier)),
    )

    monkeypatch.setattr(refresh_worker, "get_recent_general_news", lambda lookback_days, conn=None: ["recent-1", "recent-2"])

    run_discovery_calls = []
    monkeypatch.setattr(
        refresh_worker, "run_discovery", lambda articles: run_discovery_calls.append(articles) or ["accepted-1"]
    )

    insert_calls = []
    monkeypatch.setattr(
        refresh_worker, "insert_suggestions", lambda suggestions, conn=None: insert_calls.append(suggestions)
    )

    refresh_worker.run_discovery_scan(catalog, conn)

    assert parse_calls == list(refresh_worker._DISCOVERY_RSS_SOURCES)
    assert len(fetch_calls) == len(refresh_worker._DISCOVERY_RSS_SOURCES)
    assert len(upsert_calls) == len(refresh_worker._DISCOVERY_RSS_SOURCES)
    assert run_discovery_calls == [["recent-1", "recent-2"]]
    assert insert_calls == [["accepted-1"]]


def test_refresh_filings_passes_none_since_on_first_ingest(monkeypatch):
    catalog = load_catalog(CATALOG_PATH)
    source = catalog.get("sec_edgar_filings")

    monkeypatch.setattr(refresh_worker, "_latest_filing_date", lambda conn, symbol: None)
    monkeypatch.setattr(refresh_worker.edgar_parser, "resolve_cik", lambda symbol, ua: "320193")

    captured = {}

    def fake_fetch_recent_filings(cik, user_agent, since=None):
        captured["since"] = since
        return []

    monkeypatch.setattr(refresh_worker.edgar_parser, "fetch_recent_filings", fake_fetch_recent_filings)
    monkeypatch.setattr(refresh_worker, "embed_and_store", lambda documents, conn=None: 0)

    refresh_worker.refresh_filings("AAPL", source, conn=MagicMock())

    assert captured["since"] is None
