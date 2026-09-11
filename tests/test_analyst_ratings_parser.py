from pathlib import Path

import pandas as pd

from app.ingest.catalog import load_catalog
from app.ingest.parsers.analyst_ratings_parser import parse_analyst_ratings

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data_catalog.yaml"

# Shape confirmed against a live Ticker.upgrades_downgrades call, 2026-09-10:
# a DataFrame indexed by GradeDate with Firm/ToGrade/FromGrade/Action columns.
RATINGS = pd.DataFrame(
    {
        "Firm": ["TD Cowen", "Rosenblatt"],
        "ToGrade": ["Buy", "Neutral"],
        "FromGrade": ["Hold", "Neutral"],
        "Action": ["up", "main"],
        "priceTargetAction": ["raises", "maintains"],
        "currentPriceTarget": [420.0, 303.0],
        "priorPriceTarget": [400.0, 303.0],
    },
    index=pd.to_datetime(["2026-09-10 13:14:37", "2026-09-10 11:52:11"]),
)
RATINGS.index.name = "GradeDate"


def test_parse_analyst_ratings_maps_fields():
    source = load_catalog(CATALOG_PATH).get("yfinance_analyst_ratings")

    records = parse_analyst_ratings("AAPL", RATINGS, source)

    assert len(records) == 2
    assert records[0].symbol == "AAPL"
    assert records[0].firm == "TD Cowen"
    assert records[0].action == "up"
    assert records[0].from_grade == "Hold"
    assert records[0].to_grade == "Buy"
    assert records[0].reliability_tier == source.reliability_tier


def test_parse_analyst_ratings_handles_none():
    """yfinance returns None (not an empty DataFrame) when a symbol has no
    rating history."""
    source = load_catalog(CATALOG_PATH).get("yfinance_analyst_ratings")
    assert parse_analyst_ratings("ZZZZ", None, source) == []


def test_parse_analyst_ratings_handles_empty_dataframe():
    source = load_catalog(CATALOG_PATH).get("yfinance_analyst_ratings")
    empty = pd.DataFrame(columns=["Firm", "ToGrade", "FromGrade", "Action"])
    assert parse_analyst_ratings("ZZZZ", empty, source) == []
