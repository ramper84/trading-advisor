from datetime import datetime, timezone

from app.ingest.parsers.news_parser import parse_news

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
