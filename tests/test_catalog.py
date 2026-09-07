from pathlib import Path

from app.ingest.catalog import Axis, load_catalog

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data_catalog.yaml"


def test_catalog_loads_five_sources():
    catalog = load_catalog(CATALOG_PATH)
    assert len(catalog.sources) == 5


def test_all_sources_currently_included():
    catalog = load_catalog(CATALOG_PATH)
    assert len(catalog.included_sources()) == 5


def test_axis_split_matches_architecture_decision():
    catalog = load_catalog(CATALOG_PATH)
    assert {s.name for s in catalog.by_axis(Axis.SQL_RETRIEVAL)} == {
        "yfinance_quotes",
        "finnhub_quotes",
    }
    assert {s.name for s in catalog.by_axis(Axis.VECTOR_RAG)} == {
        "sec_edgar_filings",
        "finnhub_news",
        "reddit_mentions",
    }


def test_reddit_fails_is_rag_ready_by_design():
    """Encodes ARCHITECTURE.md §1's reliability-tier rule: reddit_mentions
    is included despite failing articles/s06-02's own quality bar, and the
    guardrail (Phase 13) depends on that gap being real, not smoothed over.
    """
    catalog = load_catalog(CATALOG_PATH)
    reddit = catalog.get("reddit_mentions")
    assert reddit.quality.is_rag_ready is False
    assert reddit.reliability_tier < 3

    edgar = catalog.get("sec_edgar_filings")
    assert edgar.quality.is_rag_ready is True
    assert edgar.reliability_tier >= 3
