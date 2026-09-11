from pathlib import Path

from app.ingest.catalog import load_catalog
from app.ingest.parsers.instrument_parser import parse_instrument_info

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data_catalog.yaml"

# Shape confirmed against a live yf.Ticker("AAPL").get_info() call, 2026-09-10.
RAW_INFO = {
    "longName": "Apple Inc.",
    "shortName": "Apple Inc.",
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "country": "United States",
    "currency": "USD",
    "exchange": "NMS",
    "quoteType": "EQUITY",
}


def test_parse_instrument_info_maps_all_fields():
    source = load_catalog(CATALOG_PATH).get("yfinance_quotes")

    record = parse_instrument_info("AAPL", RAW_INFO, source)

    assert record.symbol == "AAPL"
    assert record.name == "Apple Inc."
    assert record.exchange == "NMS"
    assert record.currency == "USD"
    assert record.quote_type == "EQUITY"
    assert record.sector == "Technology"
    assert record.industry == "Consumer Electronics"
    assert record.country == "United States"
    assert record.reliability_tier == source.reliability_tier


def test_parse_instrument_info_falls_back_to_short_name():
    source = load_catalog(CATALOG_PATH).get("yfinance_quotes")
    info = {k: v for k, v in RAW_INFO.items() if k != "longName"}

    record = parse_instrument_info("AAPL", info, source)

    assert record.name == "Apple Inc."


def test_parse_instrument_info_handles_missing_fields():
    source = load_catalog(CATALOG_PATH).get("yfinance_quotes")

    record = parse_instrument_info("XYZ", {}, source)

    assert record.symbol == "XYZ"
    assert record.name is None
    assert record.sector is None
