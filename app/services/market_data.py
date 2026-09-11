"""Structured market data — Axis 2. yfinance primary, Finnhub fallback
(data_catalog.yaml's yfinance_quotes / finnhub_quotes). Both converge on
the same Quote shape; callers (the live-read path in Phase 10,
refresh_worker in Phase 9) never see which provider actually answered.

Quote carries the full yfinance fast_info set (ADR-007) — open/day-high/
day-low/52-week-hi-lo/SMA50/SMA200/market-cap/exchange/currency/quote-type
all come from the SAME call already made for the price, at zero extra API
cost. Finnhub's /quote endpoint doesn't return most of this, so the
fallback path leaves those fields None rather than guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import finnhub
import pandas as pd
import yfinance as yf

from app.config import get_settings


@dataclass
class Quote:
    symbol: str
    price: float
    previous_close: Optional[float]
    volume: Optional[float]
    observed_at: datetime
    source_name: str  # "yfinance_quotes" or "finnhub_quotes" — matches data_catalog.yaml

    # ADR-007 — free from the same fast_info call, None on the Finnhub path
    open: Optional[float] = None
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    year_high: Optional[float] = None
    year_low: Optional[float] = None
    fifty_day_average: Optional[float] = None
    two_hundred_day_average: Optional[float] = None
    market_cap: Optional[float] = None
    exchange: Optional[str] = None
    currency: Optional[str] = None
    quote_type: Optional[str] = None


def _fast_info_float(fast, key: str) -> Optional[float]:
    """yfinance's FastInfo.get() is unreliable — it silently returns None
    for several real keys (day_high, year_high, market_cap, quote_type
    confirmed live 2026-09-10) even though bracket access works correctly
    for the same keys. Never use FastInfo.get(); use this instead."""
    try:
        value = fast[key]
    except KeyError:
        return None
    return float(value) if value is not None else None


def _fast_info_str(fast, key: str) -> Optional[str]:
    try:
        return fast[key]
    except KeyError:
        return None


def get_quote_yfinance(symbol: str) -> Quote:
    fast = yf.Ticker(symbol).fast_info
    return Quote(
        symbol=symbol,
        price=float(fast["last_price"]),
        previous_close=_fast_info_float(fast, "previous_close"),
        volume=_fast_info_float(fast, "last_volume"),
        observed_at=datetime.now(timezone.utc),
        source_name="yfinance_quotes",
        open=_fast_info_float(fast, "open"),
        day_high=_fast_info_float(fast, "day_high"),
        day_low=_fast_info_float(fast, "day_low"),
        year_high=_fast_info_float(fast, "year_high"),
        year_low=_fast_info_float(fast, "year_low"),
        fifty_day_average=_fast_info_float(fast, "fifty_day_average"),
        two_hundred_day_average=_fast_info_float(fast, "two_hundred_day_average"),
        market_cap=_fast_info_float(fast, "market_cap"),
        exchange=_fast_info_str(fast, "exchange"),
        currency=_fast_info_str(fast, "currency"),
        quote_type=_fast_info_str(fast, "quote_type"),
    )


def get_quote_finnhub(symbol: str) -> Quote:
    settings = get_settings()
    data = finnhub.Client(api_key=settings.finnhub_api_key).quote(symbol)
    return Quote(
        symbol=symbol,
        price=float(data["c"]),
        previous_close=float(data["pc"]) if data.get("pc") else None,
        volume=None,  # Finnhub's /quote endpoint doesn't return volume
        observed_at=datetime.now(timezone.utc),
        source_name="finnhub_quotes",
        day_high=float(data["h"]) if data.get("h") else None,
        day_low=float(data["l"]) if data.get("l") else None,
        open=float(data["o"]) if data.get("o") else None,
    )


def get_quote(symbol: str) -> Quote:
    """yfinance first (data_catalog.yaml's primary); Finnhub on any failure."""
    try:
        return get_quote_yfinance(symbol)
    except Exception:
        return get_quote_finnhub(symbol)


def get_instrument_info(symbol: str) -> dict:
    """The slower Ticker.info call — sector/industry/name aren't in
    fast_info. Called once per symbol on monitor-add (instrument_parser.py),
    never on the quote-polling cadence."""
    return yf.Ticker(symbol).get_info()


def get_daily_history(symbol: str, period: str = "5d") -> pd.DataFrame:
    """Adjusted-close daily OHLCV bars — the chart backbone (ADR-007).
    auto_adjust=True (yfinance's own default) folds splits/dividends into
    open/high/low/close directly rather than returning a separate
    Adj Close column."""
    return yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=True)


def get_analyst_ratings(symbol: str) -> Optional[pd.DataFrame]:
    """Rating-change events (upgrade/downgrade + firm) — Ticker.
    upgrades_downgrades returns None when a symbol has no rating history,
    not an empty DataFrame; callers must handle both."""
    return yf.Ticker(symbol).upgrades_downgrades


def get_quarterly_financials(symbol: str) -> pd.DataFrame:
    return yf.Ticker(symbol).quarterly_financials


def get_quarterly_balance_sheet(symbol: str) -> pd.DataFrame:
    return yf.Ticker(symbol).quarterly_balance_sheet
