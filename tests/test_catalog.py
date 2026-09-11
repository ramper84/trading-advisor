from pathlib import Path

from app.ingest.catalog import Axis, IngestionDecision, load_catalog

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data_catalog.yaml"


def test_catalog_loads_fifteen_sources():
    """12 included (ADR-006 + ADR-007's three new yfinance-derived sources)
    + 3 deliberately-excluded-with-a-written-reason (articles/s06-02):
    tradingview_community, google_finance, investing_com_calendar."""
    catalog = load_catalog(CATALOG_PATH)
    assert len(catalog.sources) == 15


def test_twelve_sources_currently_included():
    catalog = load_catalog(CATALOG_PATH)
    assert len(catalog.included_sources()) == 12


def test_axis_split_matches_architecture_decision():
    catalog = load_catalog(CATALOG_PATH)
    assert {s.name for s in catalog.by_axis(Axis.SQL_RETRIEVAL)} == {
        "yfinance_quotes",
        "finnhub_quotes",
        "yfinance_daily_bars",
        "yfinance_fundamentals",
        "yfinance_analyst_ratings",
        "banxico_sie",
        "fred_economic_data",
    }
    assert {s.name for s in catalog.by_axis(Axis.VECTOR_RAG)} == {
        "sec_edgar_filings",
        "finnhub_news",
        "yfinance_news",
        "elfinanciero_news",
        "el_economista_news",
    }


def test_no_social_media_source_is_included():
    """ADR-006: no social/community feed of any kind — reddit_mentions is
    gone entirely (not merely excluded-with-a-reason like the other three),
    and tradingview_community (the other social-flavored candidate) is
    excluded, not included."""
    catalog = load_catalog(CATALOG_PATH)
    names = {s.name for s in catalog.sources}
    assert "reddit_mentions" not in names

    tradingview = catalog.get("tradingview_community")
    assert tradingview.decision == IngestionDecision.EXCLUDE


def test_excluded_sources_are_not_in_included_sources():
    catalog = load_catalog(CATALOG_PATH)
    included_names = {s.name for s in catalog.included_sources()}
    for excluded_name in ("tradingview_community", "google_finance", "investing_com_calendar"):
        assert excluded_name not in included_names


def test_economic_data_sources_score_well_above_is_rag_ready_bar():
    """Unlike the old reddit_mentions exception, banxico_sie/
    fred_economic_data are official government sources — no deliberate
    quality exception needed for them."""
    catalog = load_catalog(CATALOG_PATH)
    for name in ("banxico_sie", "fred_economic_data"):
        source = catalog.get(name)
        assert source.quality.is_rag_ready is True
        assert source.reliability_tier == 5
