"""Axis 2 typed reads — the SQL-retrieval side of /analyze's augmentation
step (Phase 11) and the read side behind GET /trending, GET /symbols/*.
Offline/online split (articles/s06-01): this module never writes, never
triggers a fetch — it only reads what ingest/ already persisted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import psycopg

from app.services.db import get_connection


@dataclass
class ObservationRow:
    symbol: str
    observed_at: datetime
    price: float
    previous_close: Optional[float]
    volume: Optional[float]
    open: Optional[float]
    day_high: Optional[float]
    day_low: Optional[float]
    year_high: Optional[float]
    year_low: Optional[float]
    fifty_day_average: Optional[float]
    two_hundred_day_average: Optional[float]
    market_cap: Optional[float]
    source_name: str


@dataclass
class DailyBarRow:
    symbol: str
    bar_date: date
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float]


@dataclass
class FundamentalsRow:
    symbol: str
    snapshot_date: date
    pe_ratio: Optional[float]
    pb_ratio: Optional[float]
    ev_ebitda: Optional[float]
    dividend_yield: Optional[float]
    fcf_yield: Optional[float]
    market_cap: Optional[float]
    revenue: Optional[float]
    net_income: Optional[float]
    eps: Optional[float]
    gross_margin: Optional[float]
    operating_margin: Optional[float]
    debt_to_equity: Optional[float]
    roe: Optional[float]


@dataclass
class AnalystRatingRow:
    symbol: str
    rated_at: datetime
    firm: str
    action: str
    from_grade: Optional[str]
    to_grade: Optional[str]


@dataclass
class EconomicIndicatorRow:
    series_id: str
    series_name: str
    value: float
    observed_on: date
    country: str


@dataclass
class InstrumentRow:
    symbol: str
    name: Optional[str]
    exchange: Optional[str]
    currency: Optional[str]
    quote_type: Optional[str]
    sector: Optional[str]
    industry: Optional[str]
    country: Optional[str]


@dataclass
class MonitoredSymbolRow:
    symbol: str
    added_at: datetime
    active: bool
    thesis: Optional[str]


@dataclass
class AnalysisRow:
    """Reads the analyses table — created in Phase 12, not before. Calling
    get_recent_analyses before then raises a plain "relation does not
    exist" from Postgres, which is the correct, self-explanatory failure
    mode for calling ahead of the schema that owns this table."""

    symbol: str
    requested_at: datetime
    stance: str
    confidence: float
    quality_status: str
    rationale: str


@dataclass
class GeneralNewsItemRow:
    """Discovery's own read (CLAUDE.md's "Extension — Discovery") — no
    `symbol` field, unlike every other row in this module: a general news
    item is never scoped to one monitored symbol."""

    id: int
    source_name: str
    reliability_tier: int
    headline: str
    summary: str
    url: str
    published_at: Optional[datetime]


def _query(conn: Optional[psycopg.Connection], sql: str, params: tuple) -> list[tuple]:
    if conn is not None:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    with get_connection() as owned_conn, owned_conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def country_for_symbol(symbol: str) -> str:
    """ARCHITECTURE.md's request-path rule: MX symbols get banxico_sie,
    US symbols get fred_economic_data. The .MX suffix is the same Yahoo
    Finance/yfinance convention used everywhere else in this project."""
    return "MX" if symbol.upper().endswith(".MX") else "US"


def get_instrument(symbol: str, conn: Optional[psycopg.Connection] = None) -> Optional[InstrumentRow]:
    rows = _query(
        conn,
        "SELECT symbol, name, exchange, currency, quote_type, sector, industry, country "
        "FROM instruments WHERE symbol = %s",
        (symbol,),
    )
    return InstrumentRow(*rows[0]) if rows else None


def get_recent_observations(
    symbol: str, limit: int = 10, conn: Optional[psycopg.Connection] = None
) -> list[ObservationRow]:
    rows = _query(
        conn,
        "SELECT symbol, observed_at, price, previous_close, volume, open, day_high, day_low, "
        "year_high, year_low, fifty_day_average, two_hundred_day_average, market_cap, source_name "
        "FROM market_observations WHERE symbol = %s ORDER BY observed_at DESC LIMIT %s",
        (symbol, limit),
    )
    return [ObservationRow(*r) for r in rows]


def get_recent_daily_bars(
    symbol: str, limit: int = 30, conn: Optional[psycopg.Connection] = None
) -> list[DailyBarRow]:
    rows = _query(
        conn,
        "SELECT symbol, bar_date, open, high, low, close, volume "
        "FROM daily_bars WHERE symbol = %s ORDER BY bar_date DESC LIMIT %s",
        (symbol, limit),
    )
    return [DailyBarRow(*r) for r in rows]


def get_latest_fundamentals(
    symbol: str, conn: Optional[psycopg.Connection] = None
) -> Optional[FundamentalsRow]:
    rows = _query(
        conn,
        "SELECT symbol, snapshot_date, pe_ratio, pb_ratio, ev_ebitda, dividend_yield, fcf_yield, "
        "market_cap, revenue, net_income, eps, gross_margin, operating_margin, debt_to_equity, roe "
        "FROM fundamentals WHERE symbol = %s ORDER BY snapshot_date DESC LIMIT 1",
        (symbol,),
    )
    return FundamentalsRow(*rows[0]) if rows else None


def get_recent_analyst_ratings(
    symbol: str, limit: int = 10, conn: Optional[psycopg.Connection] = None
) -> list[AnalystRatingRow]:
    rows = _query(
        conn,
        "SELECT symbol, rated_at, firm, action, from_grade, to_grade "
        "FROM analyst_ratings WHERE symbol = %s ORDER BY rated_at DESC LIMIT %s",
        (symbol, limit),
    )
    return [AnalystRatingRow(*r) for r in rows]


def get_recent_economic_indicators(
    country: str, limit: int = 20, conn: Optional[psycopg.Connection] = None
) -> list[EconomicIndicatorRow]:
    rows = _query(
        conn,
        "SELECT series_id, series_name, value, observed_on, country "
        "FROM economic_indicators WHERE country = %s ORDER BY observed_on DESC LIMIT %s",
        (country, limit),
    )
    return [EconomicIndicatorRow(*r) for r in rows]


def get_monitored_symbols(
    active_only: bool = True, conn: Optional[psycopg.Connection] = None
) -> list[MonitoredSymbolRow]:
    sql = "SELECT symbol, added_at, active, thesis FROM monitored_symbols"
    params: tuple = ()
    if active_only:
        sql += " WHERE active = %s"
        params = (True,)
    sql += " ORDER BY symbol"
    rows = _query(conn, sql, params)
    return [MonitoredSymbolRow(*r) for r in rows]


def get_recent_analyses(
    symbol: str, limit: int = 5, conn: Optional[psycopg.Connection] = None
) -> list[AnalysisRow]:
    rows = _query(
        conn,
        "SELECT symbol, requested_at, stance, confidence, quality_status, rationale "
        "FROM analyses WHERE symbol = %s ORDER BY requested_at DESC LIMIT %s",
        (symbol, limit),
    )
    return [AnalysisRow(*r) for r in rows]


def get_recent_general_news(
    lookback_days: int, limit: int = 200, conn: Optional[psycopg.Connection] = None
) -> list[GeneralNewsItemRow]:
    """Discovery's own read: a time-windowed batch, not a search result —
    there is no query to retrieve against, only "what's recent" (CLAUDE.md's
    "Extension — Discovery" Axis-2 decision)."""
    rows = _query(
        conn,
        "SELECT id, source_name, reliability_tier, headline, summary, url, published_at "
        "FROM general_news_items "
        "WHERE published_at >= now() - (%s || ' days')::interval "
        "ORDER BY published_at DESC LIMIT %s",
        (lookback_days, limit),
    )
    return [GeneralNewsItemRow(*r) for r in rows]
