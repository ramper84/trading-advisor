import feedparser

from app.ingest.parsers.rss_parser import parse_rss_for_symbol

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
