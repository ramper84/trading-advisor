from datetime import datetime, timezone

from app.ingest.parsers.edgar_parser import (
    fetch_recent_filings,
    parse_filing,
    split_into_sections,
    strip_html_boilerplate,
)

SAMPLE_FILING_HTML = """
<html><body>
<p>Item 1. Business</p>
<p>We design, manufacture, and sell widgets.&nbsp;Revenue grew 12%.</p>
<p>Item 1A. Risk Factors</p>
<p>Our business is subject to supply chain risk.</p>
<p>Item 7. Management's Discussion and Analysis</p>
<p>Net income increased due to higher margins.</p>
</body></html>
"""


def test_strip_html_boilerplate_removes_tags_and_entities():
    cleaned = strip_html_boilerplate("<p>Hello&nbsp;World</p>")
    assert "<p>" not in cleaned
    assert "&nbsp;" not in cleaned
    assert "Hello" in cleaned and "World" in cleaned


def test_split_into_sections_finds_each_item():
    cleaned = strip_html_boilerplate(SAMPLE_FILING_HTML)
    sections = split_into_sections(cleaned)

    titles = [title for title, _ in sections]
    assert any(t.lower().startswith("item 1.") for t in titles)
    assert any(t.lower().startswith("item 1a.") for t in titles)
    assert any(t.lower().startswith("item 7.") for t in titles)
    assert len(sections) == 3


def test_split_into_sections_falls_back_to_full_filing_with_no_headings():
    sections = split_into_sections("Just a short 8-K with no Item headings at all.")
    assert len(sections) == 1
    assert sections[0][0] == "Full filing"


def test_parse_filing_produces_one_section_per_item():
    filed_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
    result = parse_filing(
        symbol="ACME",
        accession_number="0001-26-000123",
        form_type="10-K",
        filed_at=filed_at,
        raw_html=SAMPLE_FILING_HTML,
        url="https://www.sec.gov/example",
    )

    assert len(result) == 3
    assert all(s.symbol == "ACME" for s in result)
    assert all(s.form_type == "10-K" for s in result)
    risk_section = next(s for s in result if "risk factors" in s.section_title.lower())
    assert "supply chain" in risk_section.text.lower()


SAMPLE_SUBMISSIONS = {
    "filings": {
        "recent": {
            "form": ["10-Q", "8-K", "10-K"],
            "filingDate": ["2026-07-30", "2026-06-01", "2025-11-14"],
            "accessionNumber": ["0001-26-000030", "0001-26-000020", "0001-25-000010"],
            "primaryDocument": ["a.htm", "b.htm", "c.htm"],
        }
    }
}


def test_fetch_recent_filings_with_no_since_returns_all_tracked_forms(monkeypatch):
    monkeypatch.setattr(
        "app.ingest.parsers.edgar_parser.fetch_json", lambda url, headers=None: SAMPLE_SUBMISSIONS
    )
    filings = fetch_recent_filings("320193", "test-agent")
    assert len(filings) == 3


def test_fetch_recent_filings_bounds_by_timezone_aware_since(monkeypatch):
    """Regression guard (2026-09-10, live verification): SEC's filingDate
    is a plain date string, so filed_at is always naive — passing a
    timezone-aware `since` (as refresh_worker does, read back from a
    timestamptz column) must not raise, and must compare at date
    granularity."""
    monkeypatch.setattr(
        "app.ingest.parsers.edgar_parser.fetch_json", lambda url, headers=None: SAMPLE_SUBMISSIONS
    )
    since = datetime(2026, 6, 1, tzinfo=timezone.utc)

    filings = fetch_recent_filings("320193", "test-agent", since=since)

    assert len(filings) == 1
    assert filings[0]["accession_number"] == "0001-26-000030"
