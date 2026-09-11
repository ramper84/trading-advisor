from datetime import date
from pathlib import Path

import pandas as pd

from app.ingest.catalog import load_catalog
from app.ingest.parsers.fundamentals_parser import parse_fundamentals

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data_catalog.yaml"

# Row labels and Ticker.info field names confirmed against live calls, 2026-09-10.
INFO = {
    "trailingPE": 36.09,
    "priceToBook": 44.37,
    "enterpriseToEbitda": 27.53,
    "dividendYield": 0.34,
    "marketCap": 4_766_021_713_920.0,
    "freeCashflow": 107_721_875_456.0,
}

QUARTERLY_FINANCIALS = pd.DataFrame(
    {pd.Timestamp("2026-06-30"): [50_000_000_000.0, 109_417_000_000.0, 30_000_000_000.0, 20_000_000_000.0, 1.85]},
    index=["Total Revenue", "Net Income", "Gross Profit", "Operating Income", "Diluted EPS"],
)

QUARTERLY_BALANCE_SHEET = pd.DataFrame(
    {pd.Timestamp("2026-06-30"): [100_000_000_000.0, 60_000_000_000.0]},
    index=["Total Debt", "Stockholders Equity"],
)


def test_parse_fundamentals_merges_valuation_and_financials():
    source = load_catalog(CATALOG_PATH).get("yfinance_fundamentals")

    record = parse_fundamentals("AAPL", INFO, QUARTERLY_FINANCIALS, QUARTERLY_BALANCE_SHEET, source)

    assert record.symbol == "AAPL"
    assert record.snapshot_date == date(2026, 6, 30)
    assert record.pe_ratio == 36.09
    assert record.pb_ratio == 44.37
    assert record.ev_ebitda == 27.53
    assert record.dividend_yield == 0.34
    assert record.market_cap == 4_766_021_713_920.0
    assert record.fcf_yield == 107_721_875_456.0 / 4_766_021_713_920.0
    assert record.revenue == 50_000_000_000.0
    assert record.net_income == 109_417_000_000.0
    assert record.eps == 1.85
    assert record.gross_margin == 30_000_000_000.0 / 50_000_000_000.0
    assert record.operating_margin == 20_000_000_000.0 / 50_000_000_000.0
    assert record.debt_to_equity == 100_000_000_000.0 / 60_000_000_000.0
    assert record.roe == 109_417_000_000.0 / 60_000_000_000.0
    assert record.reliability_tier == source.reliability_tier


def test_parse_fundamentals_handles_empty_financials():
    source = load_catalog(CATALOG_PATH).get("yfinance_fundamentals")
    empty = pd.DataFrame()

    record = parse_fundamentals("ZZZZ", {}, empty, empty, source)

    assert record.revenue is None
    assert record.net_income is None
    assert record.debt_to_equity is None
    assert record.pe_ratio is None
    assert record.fcf_yield is None
