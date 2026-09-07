"""Structured market data — Axis 2. yfinance primary, Finnhub fallback
(data_catalog.yaml's yfinance_quotes / finnhub_quotes). Both converge on
the same Quote shape; callers (the live-read path in Phase 10,
refresh_worker in Phase 9) never see which provider actually answered.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import finnhub
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


def get_quote_yfinance(symbol: str) -> Quote:
    fast = yf.Ticker(symbol).fast_info
    return Quote(
        symbol=symbol,
        price=float(fast["last_price"]),
        previous_close=float(fast["previous_close"]) if fast.get("previous_close") else None,
        volume=float(fast["last_volume"]) if fast.get("last_volume") else None,
        observed_at=datetime.now(timezone.utc),
        source_name="yfinance_quotes",
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
    )


def get_quote(symbol: str) -> Quote:
    """yfinance first (data_catalog.yaml's primary); Finnhub on any failure."""
    try:
        return get_quote_yfinance(symbol)
    except Exception:
        return get_quote_finnhub(symbol)
