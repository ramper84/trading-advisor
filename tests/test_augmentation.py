from datetime import date, datetime, timezone

from app.analysis.augmentation import (
    assemble_context,
    build_market_data_block,
    compress_chunks,
    compress_filing_chunk,
    fit_to_budget,
    reorder_u_pattern,
)
from app.retrieval.hybrid_search import ChunkCandidate
from app.retrieval.sql_retriever import (
    AnalystRatingRow,
    DailyBarRow,
    EconomicIndicatorRow,
    FundamentalsRow,
    InstrumentRow,
    ObservationRow,
)
from app.retrieval.vector_retriever import RetrievalResult


def _candidate(chunk_id, source_name="sec_edgar_filings", content="line one\nline two", **kwargs):
    defaults = dict(
        symbol="AAPL",
        document_id=f"doc-{chunk_id}",
        reliability_tier=5,
        content=content,
        published_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        url=None,
        section_title=None,
    )
    defaults.update(kwargs)
    return ChunkCandidate(chunk_id=chunk_id, source_name=source_name, **defaults)


def test_compress_filing_chunk_keeps_symbol_and_figure_lines():
    candidate = _candidate(
        1,
        content="Item 1A. Risk Factors\nAAPL faces supply chain risk.\nUnrelated boilerplate about the board.\nRevenue grew 12% this quarter.",
    )
    compressed = compress_filing_chunk(candidate, "AAPL")
    assert "AAPL faces supply chain risk." in compressed.content
    assert "Revenue grew 12% this quarter." in compressed.content
    assert "Unrelated boilerplate about the board." not in compressed.content


def test_compress_filing_chunk_falls_back_to_full_content_when_nothing_kept():
    candidate = _candidate(1, content="Nothing relevant here at all.\nJust prose.")
    compressed = compress_filing_chunk(candidate, "AAPL")
    assert compressed.content == candidate.content


def test_compress_chunks_only_touches_filing_family():
    filing = _candidate(1, source_name="sec_edgar_filings", content="AAPL risk factors.\nboard trivia unrelated text.")
    news = _candidate(2, source_name="finnhub_news", content="Irrelevant headline about nothing specific.")

    result = compress_chunks([filing, news], "AAPL")

    assert "board trivia" not in result[0].content
    assert result[1].content == news.content


def test_reorder_u_pattern_matches_the_corrected_shape():
    items = ["e0", "e1", "e2", "e3"]
    assert reorder_u_pattern(items) == ["e0", "e2", "e3", "e1"]


def test_reorder_u_pattern_six_items():
    items = ["e0", "e1", "e2", "e3", "e4", "e5"]
    assert reorder_u_pattern(items) == ["e0", "e2", "e4", "e5", "e3", "e1"]


def test_reorder_u_pattern_empty_and_single():
    assert reorder_u_pattern([]) == []
    assert reorder_u_pattern(["only"]) == ["only"]


def test_fit_to_budget_keeps_items_that_fit_whole():
    wrapped = [(1, "short"), (2, "also short")]
    kept, dropped, used = fit_to_budget(wrapped, token_budget=1000)
    assert kept == ["short", "also short"]
    assert dropped == []
    assert used > 0


def test_fit_to_budget_skips_oversized_item_but_continues_checking_later_ones():
    """Regression guard for the s11-01 vs s09-04 divergence: unlike a
    break-on-first-miss loop, a small item AFTER a too-large one must
    still be kept, since edge-loading means relevance is no longer
    monotonic by position."""
    huge = "x " * 5000  # far over budget alone
    wrapped = [(1, huge), (2, "tiny")]
    kept, dropped, used = fit_to_budget(wrapped, token_budget=50)
    assert "tiny" in kept
    assert 1 in dropped
    assert 2 not in dropped


def test_fit_to_budget_never_splits_a_chunk():
    wrapped = [(1, "x " * 5000)]
    kept, dropped, used = fit_to_budget(wrapped, token_budget=10)
    assert kept == []
    assert dropped == [1]


def test_build_market_data_block_includes_available_sections():
    instrument = InstrumentRow("AAPL", "Apple Inc.", "NASDAQ", "USD", "EQUITY", "Technology", "Consumer Electronics", "US")
    observation = ObservationRow(
        "AAPL", datetime(2026, 9, 10, tzinfo=timezone.utc), 220.5, 219.0, 5_000_000.0,
        219.5, 221.0, 218.0, 240.0, 190.0, 215.0, 210.0, 3_400_000_000_000.0, "yfinance_quotes",
    )
    daily_bars = [
        DailyBarRow("AAPL", date(2026, 9, 9), 218.0, 221.0, 217.0, 220.0, 1_000_000.0),
        DailyBarRow("AAPL", date(2026, 9, 8), 215.0, 219.0, 214.0, 218.0, 900_000.0),
    ]
    fundamentals = FundamentalsRow(
        "AAPL", date(2026, 6, 30), 36.0, 44.3, 28.5, 0.34, 0.023,
        3_400_000_000_000.0, 109_000_000_000.0, 29_000_000_000.0, 2.02, 0.5, 0.33, 0.78, 0.28,
    )
    ratings = [AnalystRatingRow("AAPL", datetime(2026, 9, 10, tzinfo=timezone.utc), "TD Cowen", "reit", "Buy", "Buy")]
    indicators = [EconomicIndicatorRow("FEDFUNDS", "Federal Funds Effective Rate", 3.63, date(2026, 8, 1), "US")]

    block = build_market_data_block("AAPL", instrument, observation, daily_bars, fundamentals, ratings, indicators)

    assert '<market_data symbol="AAPL">' in block
    assert 'exchange="NASDAQ"' in block
    assert 'price="220.5"' in block
    assert "<technical_indicators" in block
    assert 'pe_ratio="36.0"' in block
    assert 'firm="TD Cowen"' in block
    assert 'series_id="FEDFUNDS"' in block


def test_build_market_data_block_omits_missing_sections():
    block = build_market_data_block("UNKNOWN", None, None, [], None, [], [])
    assert '<market_data symbol="UNKNOWN">' in block
    assert "<instrument" not in block
    assert "<latest_quote" not in block
    assert "<technical_indicators" not in block
    assert "<fundamentals" not in block
    assert "<analyst_ratings>" not in block
    assert "<economic_indicators" not in block


def test_assemble_context_propagates_low_confidence_and_includes_market_data():
    candidate = _candidate(1, content="AAPL had a strong quarter, revenue up 12%.")
    retrieval = RetrievalResult(low_confidence=True, candidates=[candidate], scores={1: 0.01234}, best_distance=0.9)

    result = assemble_context(
        "AAPL",
        instrument=None,
        observation=None,
        daily_bars=[],
        fundamentals=None,
        analyst_ratings=[],
        economic_indicators=[],
        retrieval=retrieval,
    )

    assert result.low_confidence is True
    assert "<market_data" in result.context
    assert "<source" in result.context
    assert result.dropped_chunk_ids == []


def test_assemble_context_drops_chunks_over_a_tight_budget_and_reports_them():
    huge_candidate = _candidate(1, content="AAPL risk factor line. " * 2000)
    small_candidate = _candidate(2, content="AAPL small figure: 12%.")
    retrieval = RetrievalResult(
        low_confidence=False,
        candidates=[huge_candidate, small_candidate],
        scores={1: 0.02, 2: 0.01},
        best_distance=0.1,
    )

    result = assemble_context(
        "AAPL",
        instrument=None,
        observation=None,
        daily_bars=[],
        fundamentals=None,
        analyst_ratings=[],
        economic_indicators=[],
        retrieval=retrieval,
        token_budget=200,
    )

    assert 1 in result.dropped_chunk_ids
    assert "<market_data" in result.context
