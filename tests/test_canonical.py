from datetime import datetime, timezone
from pathlib import Path

from app.ingest.catalog import load_catalog
from app.ingest.normalizers.canonical import from_article, from_filing_section
from app.ingest.parsers.edgar_parser import RawFilingSection
from app.ingest.parsers.news_parser import RawArticle

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data_catalog.yaml"


def _catalog():
    return load_catalog(CATALOG_PATH)


def test_from_filing_section_propagates_catalog_and_parser_metadata():
    source = _catalog().get("sec_edgar_filings")
    section = RawFilingSection(
        symbol="ACME",
        accession_number="0001-26-000123",
        form_type="10-K",
        filed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        section_title="Item 1A. Risk Factors",
        text="Our business is subject to supply chain risk.",
        url="https://www.sec.gov/example",
    )

    doc = from_filing_section(section, source)

    assert doc.content == section.text
    assert doc.metadata.source_name == "sec_edgar_filings"
    assert doc.metadata.reliability_tier == source.reliability_tier
    assert doc.metadata.symbol == "ACME"
    assert doc.metadata.section_title == "Item 1A. Risk Factors"
    assert doc.metadata.extra["form_type"] == "10-K"


def test_from_article_combines_headline_and_summary():
    source = _catalog().get("finnhub_news")
    article = RawArticle(
        symbol="ACME",
        article_id="101",
        headline="ACME beats earnings",
        summary="Q3 earnings above estimates.",
        url="https://news.example.com/101",
        published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        source="Example Wire",
    )

    doc = from_article(article, source)

    assert "ACME beats earnings" in doc.content
    assert "Q3 earnings above estimates." in doc.content
    assert doc.metadata.reliability_tier == source.reliability_tier
    assert doc.metadata.extra["outlet"] == "Example Wire"


def test_from_article_works_for_yfinance_news_too():
    """from_article is shared by finnhub_news and yfinance_news (ADR-006) —
    only the catalog_source passed in tells them apart."""
    source = _catalog().get("yfinance_news")
    article = RawArticle(
        symbol="WALMEX.MX",
        article_id="yf-1",
        headline="Walmex reports quarterly results",
        summary="Same-store sales grew year over year.",
        url="https://finance.yahoo.com/example",
        published_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        source="Yahoo Finance",
    )

    doc = from_article(article, source)

    assert doc.metadata.source_name == "yfinance_news"
    assert doc.metadata.reliability_tier == source.reliability_tier
