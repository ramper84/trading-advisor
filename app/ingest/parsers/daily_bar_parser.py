"""Adjusted-close daily OHLCV bars (ADR-007) — the actual chart backbone,
a different grain from market_observations's intraday ticks. Sourced from
yfinance's Ticker.history(auto_adjust=True), which folds splits/dividends
into open/high/low/close directly rather than a separate Adj Close column
(confirmed against a live call, 2026-09-10).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import pandas as pd

from app.ingest.catalog import CatalogSource


@dataclass
class DailyBarRecord:
    symbol: str
    bar_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    source_name: str
    reliability_tier: int


def parse_daily_bars(symbol: str, history: pd.DataFrame, catalog_source: CatalogSource) -> list[DailyBarRecord]:
    """history is yfinance's own Ticker.history() DataFrame — a DatetimeIndex
    with Open/High/Low/Close/Volume columns. Today's still-forming bar (if
    the market is open) comes back with NaN OHLC — skipped, not persisted
    as if it were a closed bar."""
    records = []
    for timestamp, row in history.iterrows():
        if any(math.isnan(row[col]) for col in ("Open", "High", "Low", "Close")):
            continue
        records.append(
            DailyBarRecord(
                symbol=symbol,
                bar_date=timestamp.date(),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row["Volume"]) if not math.isnan(row["Volume"]) else 0.0,
                source_name=catalog_source.name,
                reliability_tier=catalog_source.reliability_tier,
            )
        )
    return records
