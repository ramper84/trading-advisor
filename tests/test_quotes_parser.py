from datetime import datetime, timezone
from pathlib import Path

from app.ingest.catalog import load_catalog
from app.ingest.parsers.quotes_parser import parse_quote
from app.services.market_data import Quote

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data_catalog.yaml"


def test_parse_quote_carries_reliability_tier_from_catalog():
    catalog = load_catalog(CATALOG_PATH)
    source = catalog.get("yfinance_quotes")
    quote = Quote(
        symbol="AAPL",
        price=150.0,
        previous_close=148.5,
        volume=1_000_000.0,
        observed_at=datetime.now(timezone.utc),
        source_name="yfinance_quotes",
    )

    record = parse_quote(quote, source)

    assert record.symbol == "AAPL"
    assert record.price == 150.0
    assert record.reliability_tier == source.quality.reliability
    assert record.indicators == {"previous_close": 148.5}


def test_parse_quote_handles_missing_previous_close():
    catalog = load_catalog(CATALOG_PATH)
    source = catalog.get("finnhub_quotes")
    quote = Quote(
        symbol="MSFT",
        price=300.0,
        previous_close=None,
        volume=None,
        observed_at=datetime.now(timezone.utc),
        source_name="finnhub_quotes",
    )

    record = parse_quote(quote, source)

    assert record.indicators == {}
    assert record.volume is None
