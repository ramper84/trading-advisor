"""Turns a services.market_data.Quote into the typed record
observation_store.py persists as a market_observations row (Phase 9).
Thin by design: quotes are already structured (Axis 2), so there's no
Document/chunking step here, unlike the unstructured parsers below.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.ingest.catalog import CatalogSource
from app.services.market_data import Quote


@dataclass
class MarketObservationRecord:
    symbol: str
    observed_at: datetime
    price: float
    previous_close: Optional[float]
    bid: Optional[float]
    ask: Optional[float]
    volume: Optional[float]
    source_name: str
    reliability_tier: int

    # ADR-007 — free from the same fast_info call as price/volume
    open: Optional[float] = None
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    year_high: Optional[float] = None
    year_low: Optional[float] = None
    fifty_day_average: Optional[float] = None
    two_hundred_day_average: Optional[float] = None
    market_cap: Optional[float] = None


def parse_quote(quote: Quote, catalog_source: CatalogSource) -> MarketObservationRecord:
    return MarketObservationRecord(
        symbol=quote.symbol,
        observed_at=quote.observed_at,
        price=quote.price,
        previous_close=quote.previous_close,
        bid=None,
        ask=None,
        volume=quote.volume,
        source_name=quote.source_name,
        reliability_tier=catalog_source.reliability_tier,
        open=quote.open,
        day_high=quote.day_high,
        day_low=quote.day_low,
        year_high=quote.year_high,
        year_low=quote.year_low,
        fifty_day_average=quote.fifty_day_average,
        two_hundred_day_average=quote.two_hundred_day_average,
        market_cap=quote.market_cap,
    )
