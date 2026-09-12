from datetime import datetime, timezone

import feedparser

from app.ingest.parsers.rss_parser import parse_rss_for_symbol, parse_rss_general

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>Lo último</title>
  <item>
    <title>ACME Corp reporta resultados trimestrales</title>
    <description>ACME Corp anuncio ingresos por arriba de lo esperado.</description>
    <link>https://example.mx/acme-resultados</link>
    <guid>https://example.mx/acme-resultados</guid>
    <pubDate>Thu, 10 Sep 2026 17:56:53 -0600</pubDate>
  </item>
  <item>
    <title>Rafa Marquez y la seleccion mexicana</title>
    <description>Noticias de futbol, nada relacionado a mercados.</description>
    <link>https://example.mx/futbol</link>
    <guid>https://example.mx/futbol</guid>
    <pubDate>Thu, 10 Sep 2026 17:50:00 -0600</pubDate>
  </item>
</channel>
</rss>
"""


def test_parse_rss_for_symbol_keeps_only_matching_articles():
    feed = feedparser.parse(SAMPLE_RSS)

    matched = parse_rss_for_symbol(feed, symbol="ACME", company_keywords=["ACME"], source_name="el_economista_news")

    assert len(matched) == 1
    assert matched[0].symbol == "ACME"
    assert "ACME Corp" in matched[0].headline
    assert matched[0].source == "el_economista_news"
    assert matched[0].url == "https://example.mx/acme-resultados"


def test_parse_rss_for_symbol_is_case_insensitive():
    feed = feedparser.parse(SAMPLE_RSS)
    matched = parse_rss_for_symbol(feed, symbol="ACME", company_keywords=["acme corp"], source_name="x")
    assert len(matched) == 1


def test_parse_rss_for_symbol_no_matches_returns_empty():
    feed = feedparser.parse(SAMPLE_RSS)
    matched = parse_rss_for_symbol(feed, symbol="ZZZZ", company_keywords=["zzzz corp"], source_name="x")
    assert matched == []


def test_parse_rss_general_keeps_every_entry_no_keyword_filter():
    feed = feedparser.parse(SAMPLE_RSS)

    articles = parse_rss_general(feed, source_name="el_economista_news")

    assert len(articles) == 2  # both the market item and the unrelated football item
    assert articles[0].source_name == "el_economista_news"
    assert "ACME Corp" in articles[0].headline
    assert articles[1].headline == "Rafa Marquez y la seleccion mexicana"


def test_parse_rss_general_maps_fields_correctly():
    feed = feedparser.parse(SAMPLE_RSS)
    articles = parse_rss_general(feed, source_name="el_economista_news")
    first = articles[0]
    assert first.url == "https://example.mx/acme-resultados"
    assert "ingresos por arriba" in first.summary
    assert first.published_at.year == 2026


def test_parse_rss_general_empty_feed():
    empty_feed = feedparser.parse("<?xml version=\"1.0\"?><rss version=\"2.0\"><channel></channel></rss>")
    assert parse_rss_general(empty_feed, source_name="x") == []


def test_published_at_is_correct_utc_regardless_of_host_timezone():
    """Regression guard (2026-09-12, live verification): time.mktime()
    interprets feedparser's already-UTC-normalized struct as the host's
    LOCAL timezone, silently shifting every article's timestamp by the
    host's UTC offset — caught live on a host running America/Mexico_City
    (UTC-6), where freshly-ingested articles appeared ~6 hours in the
    future relative to Postgres's own now(). "Thu, 10 Sep 2026 17:56:53
    -0600" is unambiguously 2026-09-10 23:56:53 UTC; asserting that exact
    value (not just the year, as the tests above do) is what would have
    caught this on any host, not only a UTC one where the bug happens to
    be invisible."""
    feed = feedparser.parse(SAMPLE_RSS)
    matched = parse_rss_for_symbol(feed, symbol="ACME", company_keywords=["ACME"], source_name="x")
    assert matched[0].published_at == datetime(2026, 9, 10, 23, 56, 53, tzinfo=timezone.utc)

    general = parse_rss_general(feed, source_name="x")
    assert general[0].published_at == datetime(2026, 9, 10, 23, 56, 53, tzinfo=timezone.utc)
