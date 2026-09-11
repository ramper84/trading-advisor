from datetime import datetime, timezone

from app.ingest.parsers.news_parser import parse_news, parse_yfinance_news

RAW_ARTICLES = [
    {
        "id": 101,
        "headline": "ACME beats earnings expectations",
        "summary": "ACME reported Q3 earnings above analyst estimates.",
        "url": "https://news.example.com/101",
        "datetime": 1_725_000_000,
        "source": "Example Wire",
    },
    {
        "id": 102,
        "headline": "",
        "summary": "",
        "url": "https://news.example.com/102",
        "datetime": 1_725_000_100,
        "source": "Example Wire",
    },
]


def test_parse_news_keeps_well_formed_articles():
    parsed = parse_news("ACME", RAW_ARTICLES)
    assert len(parsed) == 1
    assert parsed[0].article_id == "101"
    assert parsed[0].symbol == "ACME"
    assert isinstance(parsed[0].published_at, datetime)
    assert parsed[0].published_at.tzinfo == timezone.utc


def test_parse_news_drops_disguised_nulls():
    parsed = parse_news("ACME", RAW_ARTICLES)
    ids = {a.article_id for a in parsed}
    assert "102" not in ids


# Shape confirmed against a live yf.Ticker("AAPL").news call, 2026-09-10 —
# yfinance's news shape has changed across versions before; if this starts
# failing, re-check the raw shape rather than assuming the fixture is stale.
RAW_YFINANCE_NEWS = [
    {
        "id": "story-1",
        "content": {
            "contentType": "STORY",
            "title": "Apple's iPhone leasing program: how it works",
            "summary": "Apple is partnering with a lender to offer device leases.",
            "pubDate": "2026-07-31T14:31:05Z",
            "provider": {"displayName": "Yahoo Personal Finance"},
            "canonicalUrl": {"url": "https://finance.yahoo.com/example"},
        },
    },
    {
        "id": "story-2",
        "content": {
            "contentType": "STORY",
            "title": "",
            "summary": "",
            "pubDate": "2026-07-31T15:00:00Z",
            "provider": {"displayName": "Yahoo Finance"},
        },
    },
]


def test_parse_yfinance_news_keeps_well_formed_articles():
    parsed = parse_yfinance_news("AAPL", RAW_YFINANCE_NEWS)
    assert len(parsed) == 1
    assert parsed[0].article_id == "story-1"
    assert parsed[0].symbol == "AAPL"
    assert parsed[0].source == "Yahoo Personal Finance"
    assert parsed[0].url == "https://finance.yahoo.com/example"
    assert parsed[0].published_at == datetime(2026, 7, 31, 14, 31, 5, tzinfo=timezone.utc)


def test_parse_yfinance_news_drops_empty_title_or_summary():
    parsed = parse_yfinance_news("AAPL", RAW_YFINANCE_NEWS)
    ids = {a.article_id for a in parsed}
    assert "story-2" not in ids
