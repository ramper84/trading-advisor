from datetime import date
from pathlib import Path

import pandas as pd

from app.ingest.catalog import load_catalog
from app.ingest.parsers.daily_bar_parser import parse_daily_bars

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data_catalog.yaml"

# Shape confirmed against a live Ticker.history(auto_adjust=True) call,
# 2026-09-10: columns Open/High/Low/Close/Volume/Dividends/Stock Splits,
# a tz-aware DatetimeIndex named "Date". Today's still-forming bar (while
# the market is open) comes back with NaN OHLC.
HISTORY = pd.DataFrame(
    {
        "Open": [315.49, float("nan")],
        "High": [319.15, float("nan")],
        "Low": [314.00, float("nan")],
        "Close": [317.20, float("nan")],
        "Volume": [45_000_000.0, float("nan")],
        "Dividends": [0.0, 0.0],
        "Stock Splits": [0.0, 0.0],
    },
    # Midnight in America/New_York, matching yfinance's real index shape —
    # NOT midnight UTC converted, which shifts the date back a day.
    index=pd.DatetimeIndex(["2026-09-09", "2026-09-10"]).tz_localize("America/New_York"),
)
HISTORY.index.name = "Date"


def test_parse_daily_bars_skips_incomplete_todays_bar():
    source = load_catalog(CATALOG_PATH).get("yfinance_daily_bars")

    records = parse_daily_bars("AAPL", HISTORY, source)

    assert len(records) == 1
    assert records[0].bar_date == date(2026, 9, 9)
    assert records[0].open == 315.49
    assert records[0].close == 317.20
    assert records[0].volume == 45_000_000.0
    assert records[0].reliability_tier == source.reliability_tier


def test_parse_daily_bars_empty_history():
    source = load_catalog(CATALOG_PATH).get("yfinance_daily_bars")
    empty = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    assert parse_daily_bars("AAPL", empty, source) == []
