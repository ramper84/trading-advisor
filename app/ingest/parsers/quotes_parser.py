"""Turns a services.market_data.Quote into the typed record
observation_store.py persists as a market_observations row (Phase 9-10).
Thin by design: quotes are already structured (Axis 2), so there's no
Document/chunking step here, unlike the unstructured parsers below.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.ingest.catalog import CatalogSource
from app.services.market_data import Quote


@dataclass
class MarketObservationRecord:
    symbol: str
    observed_at: datetime
    price: float
    bid: float | None
    ask: float | None
    volume: float | None
    indicators: dict
    source_name: str
    reliability_tier: int


def parse_quote(quote: Quote, catalog_source: CatalogSource) -> MarketObservationRecord:
    return MarketObservationRecord(
        symbol=quote.symbol,
        observed_at=quote.observed_at,
        price=quote.price,
        bid=None,
        ask=None,
        volume=quote.volume,
        indicators={"previous_close": quote.previous_close} if quote.previous_close else {},
        source_name=quote.source_name,
        reliability_tier=catalog_source.reliability_tier,
    )
