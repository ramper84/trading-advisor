from datetime import date, datetime, timezone

from app.analysis.synthesis import CitationSignal, EvidenceAggregate
from app.guardrails.analysis_guard import (
    STRONG_RELIABILITY_TIER_FLOOR,
    check_citation_integrity,
    check_input_relevance,
    check_reliability_rule,
    guard_analysis,
    numeric_grounding,
)
from app.retrieval.hybrid_search import ChunkCandidate
from app.retrieval.sql_retriever import DailyBarRow, EconomicIndicatorRow, FundamentalsRow, ObservationRow
from app.retrieval.vector_retriever import RetrievalResult
from app.schemas import AnalysisSynthesis, Citation

NOW = datetime(2026, 9, 10, tzinfo=timezone.utc)


def _candidate(chunk_id, reliability_tier=5, source_name="finnhub_news"):
    return ChunkCandidate(
        chunk_id=chunk_id, source_name=source_name, symbol="AAPL", document_id=f"doc-{chunk_id}",
        reliability_tier=reliability_tier, content="content", published_at=NOW, url=None, section_title=None,
    )


def _observation(price=220.5, previous_close=219.0, day_high=221.0, day_low=218.0):
    return ObservationRow(
        "AAPL", NOW, price, previous_close, 5_000_000.0, 219.5, day_high, day_low,
        240.0, 190.0, 215.0, 210.0, 3_400_000_000_000.0, "yfinance_quotes",
    )


# --- check_input_relevance ---------------------------------------------

def test_input_relevance_flags_imperative_buy_command():
    result = check_input_relevance("Buy me 10 shares of TSLA.")
    assert result.in_scope is False
    assert result.reason


def test_input_relevance_flags_place_order():
    assert check_input_relevance("Please place an order for AAPL.").in_scope is False


def test_input_relevance_allows_question_about_buying():
    assert check_input_relevance("Should I buy AAPL right now?").in_scope is True
    assert check_input_relevance("Is AAPL a good buy at this price?").in_scope is True


def test_input_relevance_allows_normal_analysis_query():
    assert check_input_relevance("Why did AAPL move today?").in_scope is True


# --- check_citation_integrity -------------------------------------------

def test_citation_integrity_splits_resolved_and_dangling():
    citations = [Citation(chunk_id=1, claim="a"), Citation(chunk_id=99, claim="b")]
    resolved, dangling = check_citation_integrity(citations, retrieved_chunk_ids={1, 2, 3})
    assert resolved == [1]
    assert dangling == [99]


def test_citation_integrity_empty_citations():
    resolved, dangling = check_citation_integrity([], retrieved_chunk_ids={1, 2})
    assert resolved == []
    assert dangling == []


# --- check_reliability_rule ----------------------------------------------

def test_reliability_rule_neutral_always_passes():
    assert check_reliability_rule("NEUTRAL", [], {}) is True


def test_reliability_rule_directional_needs_strong_citation():
    candidates_by_id = {1: _candidate(1, reliability_tier=2)}
    assert check_reliability_rule("BULLISH", [1], candidates_by_id) is False


def test_reliability_rule_directional_passes_with_strong_citation():
    candidates_by_id = {1: _candidate(1, reliability_tier=STRONG_RELIABILITY_TIER_FLOOR)}
    assert check_reliability_rule("BULLISH", [1], candidates_by_id) is True


def test_reliability_rule_directional_fails_with_no_resolved_citations():
    assert check_reliability_rule("BEARISH", [], {}) is False


# --- numeric_grounding -----------------------------------------------------

def test_numeric_grounding_dollar_figure_matches_real_price():
    ungrounded = numeric_grounding("The stock traded around $220.50 today.", _observation(), [], None, [])
    assert ungrounded == []


def test_numeric_grounding_flags_fabricated_dollar_figure():
    ungrounded = numeric_grounding("The stock hit an all-time high of $999.99.", _observation(), [], None, [])
    assert 999.99 in ungrounded


def test_numeric_grounding_allows_small_rounding_drift():
    ungrounded = numeric_grounding("Trading near $220.6 today.", _observation(price=220.5), [], None, [])
    assert ungrounded == []


def test_numeric_grounding_matches_daily_bar_high_low():
    bars = [DailyBarRow("AAPL", date(2026, 9, 9), 315.0, 319.15, 314.0, 317.2, 45_000_000.0)]
    ungrounded = numeric_grounding("The high was $319.15 and low was $314.00.", None, bars, None, [])
    assert ungrounded == []


def test_numeric_grounding_percent_matches_fraction_times_100():
    fundamentals = FundamentalsRow(
        "AAPL", date(2026, 6, 30), 36.0, 44.3, 28.5, 0.34, 0.023,
        3_400_000_000_000.0, 109_000_000_000.0, 29_000_000_000.0, 2.02, 0.5006, 0.33, 0.78, 0.28,
    )
    ungrounded = numeric_grounding("Gross margin is about 50.06%.", None, [], fundamentals, [])
    assert ungrounded == []


def test_numeric_grounding_matches_economic_indicator():
    indicators = [EconomicIndicatorRow("FEDFUNDS", "Federal Funds Effective Rate", 3.63, date(2026, 8, 1), "US")]
    ungrounded = numeric_grounding("The Fed funds rate sits at 3.63%.", None, [], None, indicators)
    assert ungrounded == []


def test_numeric_grounding_no_pool_flags_everything():
    ungrounded = numeric_grounding("Priced at $42.00.", None, [], None, [])
    assert 42.0 in ungrounded


def test_numeric_grounding_ignores_bare_numbers_without_markers():
    # "14" (an RSI period, say) has no $ or % marker -> not checked at all.
    ungrounded = numeric_grounding("RSI-14 suggests momentum is neutral.", _observation(), [], None, [])
    assert ungrounded == []


# --- guard_analysis (full integration) --------------------------------------

def _aggregate_with_signal(chunk_id, weight):
    return EvidenceAggregate(
        anchor_lean=0.0, strong_low=0.0, strong_high=0.0, contested=False,
        citation_signals=[CitationSignal(chunk_id=chunk_id, weight=weight, lean=0.0)],
    )


def test_guard_analysis_grounded_when_everything_checks_out():
    candidate = _candidate(1, reliability_tier=5)
    synthesis = AnalysisSynthesis(
        stance="BULLISH", confidence=0.8, rationale="Trading at $220.50, a strong position.",
        citations=[Citation(chunk_id=1, claim="strong position")],
    )
    retrieval = RetrievalResult(low_confidence=False, candidates=[candidate], scores={1: 0.02}, best_distance=0.1, fused_rank={1: 1})
    aggregate = _aggregate_with_signal(1, weight=0.7)

    result = guard_analysis(synthesis, retrieval, aggregate, _observation(), [], None, [])

    assert result.quality_status == "grounded"
    assert result.stance == "BULLISH"
    assert result.confidence == 0.7
    assert result.dangling_citations == []
    assert result.ungrounded_figures == []


def test_guard_analysis_insufficient_forces_neutral_on_fully_dangling_citations():
    candidate = _candidate(1, reliability_tier=5)
    synthesis = AnalysisSynthesis(
        stance="BULLISH", confidence=0.8, rationale="Looks strong.",
        citations=[Citation(chunk_id=999, claim="fabricated")],
    )
    retrieval = RetrievalResult(low_confidence=False, candidates=[candidate], scores={1: 0.02}, best_distance=0.1, fused_rank={1: 1})
    aggregate = _aggregate_with_signal(1, weight=0.7)

    result = guard_analysis(synthesis, retrieval, aggregate, None, [], None, [])

    assert result.quality_status == "insufficient"
    assert result.stance == "NEUTRAL"
    assert result.dangling_citations == [999]


def test_guard_analysis_insufficient_forces_neutral_on_fabricated_figure():
    candidate = _candidate(1, reliability_tier=5)
    synthesis = AnalysisSynthesis(
        stance="BULLISH", confidence=0.8, rationale="Trading at an all-time high of $9999.00.",
        citations=[Citation(chunk_id=1, claim="high price")],
    )
    retrieval = RetrievalResult(low_confidence=False, candidates=[candidate], scores={1: 0.02}, best_distance=0.1, fused_rank={1: 1})
    aggregate = _aggregate_with_signal(1, weight=0.7)

    result = guard_analysis(synthesis, retrieval, aggregate, _observation(), [], None, [])

    assert result.quality_status == "insufficient"
    assert result.stance == "NEUTRAL"
    assert result.ungrounded_figures == [9999.0]


def test_guard_analysis_insufficient_forces_neutral_when_reliability_rule_fails():
    weak_candidate = _candidate(1, reliability_tier=2)
    synthesis = AnalysisSynthesis(
        stance="BEARISH", confidence=0.8, rationale="Concerning signals.",
        citations=[Citation(chunk_id=1, claim="concerning signal")],
    )
    retrieval = RetrievalResult(low_confidence=False, candidates=[weak_candidate], scores={1: 0.02}, best_distance=0.1, fused_rank={1: 1})
    aggregate = _aggregate_with_signal(1, weight=0.7)

    result = guard_analysis(synthesis, retrieval, aggregate, None, [], None, [])

    assert result.quality_status == "insufficient"
    assert result.stance == "NEUTRAL"
    assert result.reliability_rule_passed is False


def test_guard_analysis_degraded_on_partial_dangling_citations():
    candidate = _candidate(1, reliability_tier=5)
    synthesis = AnalysisSynthesis(
        stance="BULLISH", confidence=0.8, rationale="Solid quarter.",
        citations=[Citation(chunk_id=1, claim="solid quarter"), Citation(chunk_id=999, claim="fabricated")],
    )
    retrieval = RetrievalResult(low_confidence=False, candidates=[candidate], scores={1: 0.02}, best_distance=0.1, fused_rank={1: 1})
    aggregate = _aggregate_with_signal(1, weight=0.7)

    result = guard_analysis(synthesis, retrieval, aggregate, None, [], None, [])

    assert result.quality_status == "degraded"
    assert result.stance == "BULLISH"  # not forced to NEUTRAL — degraded, not insufficient
    assert result.confidence <= 0.5


def test_guard_analysis_degraded_on_low_confidence_retrieval_without_forcing_neutral():
    candidate = _candidate(1, reliability_tier=5)
    synthesis = AnalysisSynthesis(
        stance="BULLISH", confidence=0.8, rationale="Solid quarter.",
        citations=[Citation(chunk_id=1, claim="solid quarter")],
    )
    retrieval = RetrievalResult(low_confidence=True, candidates=[candidate], scores={1: 0.02}, best_distance=0.9, fused_rank={1: 1})
    aggregate = _aggregate_with_signal(1, weight=0.7)

    result = guard_analysis(synthesis, retrieval, aggregate, None, [], None, [])

    assert result.quality_status == "degraded"
    assert result.stance == "BULLISH"


def test_guard_analysis_neutral_with_no_citations_can_still_be_grounded():
    synthesis = AnalysisSynthesis(stance="NEUTRAL", confidence=0.5, rationale="Evidence is thin.", citations=[])
    retrieval = RetrievalResult(low_confidence=False, candidates=[], scores={}, best_distance=None, fused_rank={})
    aggregate = EvidenceAggregate(anchor_lean=0.0, strong_low=0.0, strong_high=0.0, contested=False, citation_signals=[])

    result = guard_analysis(synthesis, retrieval, aggregate, None, [], None, [])

    assert result.quality_status == "grounded"
    assert result.stance == "NEUTRAL"
