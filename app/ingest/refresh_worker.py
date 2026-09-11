"""Scheduled-refresh loop, per source cadence in data_catalog.yaml
(articles/s06-01's offline pipeline). One process, one catalog-driven
schedule — not a bespoke cron job per source.

instruments is a special case: reference data, populated once per symbol
when it's first seen in monitored_symbols, never on a recurring cadence
(it has no data_catalog.yaml entry of its own for exactly this reason).
economic_indicators is the other special case: not per-symbol at all —
one fetch per configured macro series, shared across every monitored
symbol (articles/s10-05: a macro series is economy-wide).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import psycopg

from app.config import get_settings
from app.ingest.analyst_rating_store import insert_analyst_ratings
from app.ingest.catalog import CatalogSource, DataCatalog, load_catalog
from app.ingest.daily_bar_store import upsert_daily_bars
from app.ingest.economic_indicator_store import upsert_economic_observations
from app.ingest.embedding import embed_and_store
from app.ingest.fundamentals_store import upsert_fundamentals
from app.ingest.instrument_store import upsert_instrument
from app.ingest.normalizers import canonical
from app.ingest.observation_store import insert_observations
from app.ingest.parsers import (
    analyst_ratings_parser,
    daily_bar_parser,
    economic_data_parser,
    edgar_parser,
    fundamentals_parser,
    instrument_parser,
    news_parser,
    quotes_parser,
    rss_parser,
)
from app.services import market_data
from app.services.db import get_connection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 60  # how often the worker wakes to check which sources are due

# Banxico/FRED series this project tracks. FRED's ids are well-known and
# stable. Banxico's own ids were confirmed live against the real SIE API
# (2026-09-10, real BANXICO_SIE_TOKEN) — each id below was verified to
# resolve to the titled series with real recent data before being added
# here, not guessed from memory (ARCHITECTURE.md §8's reserved slot,
# now resolved).
FRED_SERIES = {
    "FEDFUNDS": "Federal Funds Effective Rate",
    "CPIAUCSL": "US CPI (All Urban Consumers)",
}
# FRED returns a series' ENTIRE history with no observation_start bound —
# 1823 rows landed for two series on a live, unbounded first poll
# (2026-09-11), most of it CPIAUCSL back to 1947. A grounding-context tool
# needs recent values, not a research archive; Banxico's own /datos/oportuno
# endpoint already returns just the latest observation, so this bound is
# FRED-specific.
FRED_LOOKBACK_DAYS = 730
BANXICO_SERIES = {
    "SF61745": "Tasa objetivo (Overnight Target Rate)",
    "SF43718": "Tipo de cambio FIX (USD/MXN)",
    "SP30578": "INPC variación anual (Annual Inflation Rate)",
}


def get_monitored_symbols(conn: psycopg.Connection) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT symbol FROM monitored_symbols WHERE active = true")
        return [row[0] for row in cur.fetchall()]


def _has_instrument_row(conn: psycopg.Connection, symbol: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM instruments WHERE symbol = %s", (symbol,))
        return cur.fetchone() is not None


def refresh_instrument_if_new(symbol: str, catalog_source: CatalogSource, conn: psycopg.Connection) -> None:
    if _has_instrument_row(conn, symbol):
        return
    info = market_data.get_instrument_info(symbol)
    record = instrument_parser.parse_instrument_info(symbol, info, catalog_source)
    upsert_instrument(record, conn=conn)
    logger.info("instrument reference row created", extra={"symbol": symbol})


def refresh_quotes(symbol: str, catalog_source: CatalogSource, conn: psycopg.Connection) -> None:
    """Each catalog source polls its OWN vendor specifically — never the
    generic get_quote() fallback (yfinance-first, Finnhub-on-failure),
    which belongs to Phase 10's live-read path ("give me any quote"), not
    here. Routing finnhub_quotes through get_quote() would silently call
    yfinance again on every healthy poll — a wasted duplicate fetch, and a
    latent reliability_tier/source_name mismatch if the two catalog
    entries' scores ever diverge.
    """
    if catalog_source.name == "finnhub_quotes":
        quote = market_data.get_quote_finnhub(symbol)
    else:
        quote = market_data.get_quote_yfinance(symbol)
    record = quotes_parser.parse_quote(quote, catalog_source)
    insert_observations([record], conn=conn)


def refresh_daily_bars(symbol: str, catalog_source: CatalogSource, conn: psycopg.Connection) -> None:
    history = market_data.get_daily_history(symbol, period="5d")
    records = daily_bar_parser.parse_daily_bars(symbol, history, catalog_source)
    upsert_daily_bars(records, conn=conn)


def refresh_fundamentals(symbol: str, catalog_source: CatalogSource, conn: psycopg.Connection) -> None:
    info = market_data.get_instrument_info(symbol)
    quarterly_financials = market_data.get_quarterly_financials(symbol)
    quarterly_balance_sheet = market_data.get_quarterly_balance_sheet(symbol)
    record = fundamentals_parser.parse_fundamentals(
        symbol, info, quarterly_financials, quarterly_balance_sheet, catalog_source
    )
    upsert_fundamentals(record, conn=conn)


def refresh_analyst_ratings(symbol: str, catalog_source: CatalogSource, conn: psycopg.Connection) -> None:
    ratings = market_data.get_analyst_ratings(symbol)
    records = analyst_ratings_parser.parse_analyst_ratings(symbol, ratings, catalog_source)
    insert_analyst_ratings(records, conn=conn)


def refresh_filings(symbol: str, catalog_source: CatalogSource, conn: psycopg.Connection) -> None:
    settings = get_settings()
    cik = edgar_parser.resolve_cik(symbol, settings.edgar_user_agent)
    filings = edgar_parser.fetch_recent_filings(cik, settings.edgar_user_agent)
    documents = []
    for filing in filings:
        raw_html = edgar_parser.fetch_filing_document(
            cik, filing["accession_number"], filing["primary_document"], settings.edgar_user_agent
        )
        url = edgar_parser.filing_document_url(cik, filing["accession_number"], filing["primary_document"])
        sections = edgar_parser.parse_filing(
            symbol, filing["accession_number"], filing["form_type"], filing["filed_at"], raw_html, url
        )
        documents.extend(canonical.from_filing_section(s, catalog_source) for s in sections)
    embed_and_store(documents, conn=conn)


def refresh_finnhub_news(symbol: str, catalog_source: CatalogSource, conn: psycopg.Connection) -> None:
    settings = get_settings()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    raw = news_parser.fetch_finnhub_news(symbol, settings.finnhub_api_key, week_ago, today)
    articles = news_parser.parse_news(symbol, raw)
    documents = [canonical.from_article(a, catalog_source) for a in articles]
    embed_and_store(documents, conn=conn)


def refresh_yfinance_news(symbol: str, catalog_source: CatalogSource, conn: psycopg.Connection) -> None:
    raw = news_parser.fetch_yfinance_news(symbol)
    articles = news_parser.parse_yfinance_news(symbol, raw)
    documents = [canonical.from_article(a, catalog_source) for a in articles]
    embed_and_store(documents, conn=conn)


def refresh_rss_news(symbol: str, catalog_source: CatalogSource, conn: psycopg.Connection) -> None:
    feed = rss_parser.fetch_rss_feed(catalog_source.location)
    # Symbol-only keyword matching: under-recalls (misses articles that
    # name the company but not the ticker) but never over-matches. A real
    # symbol -> company-name mapping is a monitor-add-time enrichment not
    # yet built.
    articles = rss_parser.parse_rss_for_symbol(feed, symbol, [symbol], catalog_source.name)
    documents = [canonical.from_article(a, catalog_source) for a in articles]
    embed_and_store(documents, conn=conn)


def refresh_economic_data(catalog_source: CatalogSource, conn: psycopg.Connection) -> None:
    """Not per-symbol: one fetch per configured series, shared across every
    monitored symbol."""
    settings = get_settings()
    if catalog_source.name == "fred_economic_data":
        if not settings.fred_api_key:
            logger.warning("FRED_API_KEY not set, skipping fred_economic_data")
            return
        observation_start = (datetime.now(timezone.utc) - timedelta(days=FRED_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        for series_id, series_name in FRED_SERIES.items():
            raw = economic_data_parser.fetch_fred_series(series_id, settings.fred_api_key, observation_start)
            records = economic_data_parser.parse_fred_series(raw, series_id, series_name)
            upsert_economic_observations(records, conn=conn)
    elif catalog_source.name == "banxico_sie":
        if not settings.banxico_sie_token or not BANXICO_SERIES:
            logger.warning("BANXICO_SIE_TOKEN not set or no series ids confirmed yet, skipping banxico_sie")
            return
        for series_id, series_name in BANXICO_SERIES.items():
            raw = economic_data_parser.fetch_banxico_series(series_id, settings.banxico_sie_token)
            records = economic_data_parser.parse_banxico_series(raw, series_name)
            upsert_economic_observations(records, conn=conn)


_ECONOMIC_SOURCES = {"banxico_sie", "fred_economic_data"}

_PER_SYMBOL_REFRESH = {
    "yfinance_quotes": refresh_quotes,
    "finnhub_quotes": refresh_quotes,
    "yfinance_daily_bars": refresh_daily_bars,
    "yfinance_fundamentals": refresh_fundamentals,
    "yfinance_analyst_ratings": refresh_analyst_ratings,
    "sec_edgar_filings": refresh_filings,
    "finnhub_news": refresh_finnhub_news,
    "yfinance_news": refresh_yfinance_news,
    "elfinanciero_news": refresh_rss_news,
    "el_economista_news": refresh_rss_news,
}


def run_once(catalog: DataCatalog, last_run: dict[str, float]) -> None:
    now = time.monotonic()
    with get_connection() as conn:
        symbols = get_monitored_symbols(conn)
        if not symbols:
            logger.info("no monitored symbols yet, nothing to refresh")
            return

        yfinance_quotes_source = catalog.get("yfinance_quotes")
        for symbol in symbols:
            try:
                refresh_instrument_if_new(symbol, yfinance_quotes_source, conn)
            except Exception:
                logger.exception("instrument refresh failed", extra={"symbol": symbol})

        for source in catalog.included_sources():
            last_run_at = last_run.get(source.name)
            # last_run_at is None means "never run" — always due, regardless
            # of what `now` happens to be. time.monotonic() is relative to
            # an arbitrary system-dependent start point (often boot time),
            # not the epoch — treating a 0 default as "long ago" silently
            # skipped every 86400s-cadence source on a freshly started
            # process whose monotonic clock hadn't yet reached 86400.
            if last_run_at is not None and (now - last_run_at) < source.refresh.interval_seconds:
                continue

            if source.name in _ECONOMIC_SOURCES:
                try:
                    refresh_economic_data(source, conn)
                except Exception:
                    logger.exception("economic data refresh failed", extra={"source": source.name})
                last_run[source.name] = now
                continue

            refresh_fn = _PER_SYMBOL_REFRESH.get(source.name)
            if refresh_fn is None:
                continue  # a catalog source with no dispatcher wired yet

            for symbol in symbols:
                try:
                    refresh_fn(symbol, source, conn)
                    logger.info("refreshed", extra={"source": source.name, "symbol": symbol})
                except Exception:
                    logger.exception("refresh failed", extra={"source": source.name, "symbol": symbol})
            last_run[source.name] = now


def main() -> None:
    catalog = load_catalog()
    logger.info(
        "refresh_worker started with %d source(s): %s",
        len(catalog.included_sources()),
        [s.name for s in catalog.included_sources()],
    )
    last_run: dict[str, float] = {}
    while True:
        run_once(catalog, last_run)
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
