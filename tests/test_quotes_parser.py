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
        open=149.0,
        day_high=151.0,
        day_low=148.0,
        year_high=180.0,
        year_low=120.0,
        fifty_day_average=145.0,
        two_hundred_day_average=140.0,
        market_cap=2_500_000_000_000.0,
        exchange="NMS",
        currency="USD",
        quote_type="EQUITY",
    )

    record = parse_quote(quote, source)

    assert record.symbol == "AAPL"
    assert record.price == 150.0
    assert record.previous_close == 148.5
    assert record.reliability_tier == source.quality.reliability
    # ADR-007: the full fast_info set rides along at zero extra API cost
    assert record.open == 149.0
    assert record.day_high == 151.0
    assert record.day_low == 148.0
    assert record.year_high == 180.0
    assert record.year_low == 120.0
    assert record.fifty_day_average == 145.0
    assert record.two_hundred_day_average == 140.0
    assert record.market_cap == 2_500_000_000_000.0


def test_parse_quote_handles_missing_optional_fields():
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

    assert record.previous_close is None
    assert record.volume is None
    assert record.fifty_day_average is None
    assert record.market_cap is None
