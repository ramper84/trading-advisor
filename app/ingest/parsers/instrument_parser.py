"""Instrument reference data (ADR-007) — static, rarely-changing facts
about a symbol: exchange, currency, asset type, sector, industry, country.
Populated once per symbol when it's added to monitored_symbols (Phase 9's
refresh_worker), not on the 5-minute quote-polling cadence — a reference
table doesn't need a price tick's freshness budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.ingest.catalog import CatalogSource


@dataclass
class InstrumentRecord:
    symbol: str
    name: Optional[str]
    exchange: Optional[str]
    currency: Optional[str]
    quote_type: Optional[str]  # yfinance's asset-type field: EQUITY, ETF, INDEX, ...
    sector: Optional[str]
    industry: Optional[str]
    country: Optional[str]
    source_name: str
    reliability_tier: int


def parse_instrument_info(symbol: str, info: dict, catalog_source: CatalogSource) -> InstrumentRecord:
    """info is yfinance's own Ticker.get_info() dict. Attributed to
    yfinance_quotes's catalog entry — same vendor/package as quotes, just a
    different endpoint, not a distinct data_catalog.yaml source."""
    return InstrumentRecord(
        symbol=symbol,
        name=info.get("longName") or info.get("shortName"),
        exchange=info.get("exchange"),
        currency=info.get("currency"),
        quote_type=info.get("quoteType"),
        sector=info.get("sector"),
        industry=info.get("industry"),
        country=info.get("country"),
        source_name=catalog_source.name,
        reliability_tier=catalog_source.reliability_tier,
    )
