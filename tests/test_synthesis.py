from datetime import datetime, timezone

from app.analysis.synthesis import (
    STRONG_WEIGHT_FLOOR,
    CitationSignal,
    aggregate_evidence,
    combined_weight,
    compute_citation_signal,
    weighted_median,
    _keyword_lean,
)
from app.retrieval.hybrid_search import ChunkCandidate
from app.retrieval.vector_retriever import RetrievalResult

NOW = datetime(2026, 9, 10, tzinfo=timezone.utc)


def _candidate(chunk_id, content, reliability_tier=5, published_at=NOW, source_name="finnhub_news"):
    return ChunkCandidate(
        chunk_id=chunk_id,
        source_name=source_name,
        symbol="AAPL",
        document_id=f"doc-{chunk_id}",
        reliability_tier=reliability_tier,
        content=content,
        published_at=published_at,
        url=None,
        section_title=None,
    )


def test_keyword_lean_bullish():
    assert _keyword_lean("Apple beats earnings, strong growth, record revenue.") > 0


def test_keyword_lean_bearish():
    assert _keyword_lean("Apple misses estimates amid a lawsuit and weak guidance.") < 0


def test_keyword_lean_no_signal_is_zero():
    assert _keyword_lean("Apple held its annual shareholder meeting today.") == 0.0


def test_keyword_lean_mixed_signals_partially_cancel():
    lean = _keyword_lean("Apple beats earnings but faces a new lawsuit.")
    assert -1.0 < lean < 1.0


def test_weighted_median_single_value():
    assert weighted_median([(0.5, 1.0)]) == 0.5


def test_weighted_median_robust_to_outlier():
    # Two strong sources agree near 0.1; one weak outlier at -1.0 should
    # not drag the median far.
    result = weighted_median([(0.1, 0.8), (0.12, 0.8), (-1.0, 0.05)])
    assert result in (0.1, 0.12)


def test_weighted_median_empty():
    assert weighted_median([]) == 0.0


def test_combined_weight_uses_documented_coefficients():
    w = combined_weight(fusion_rank_signal=1.0, temporal_signal=1.0, reliability_signal=1.0)
    assert abs(w - 1.0) < 1e-9  # coefficients sum to 1.0
    w2 = combined_weight(fusion_rank_signal=0.0, temporal_signal=0.0, reliability_signal=0.0)
    assert w2 == 0.0


def test_compute_citation_signal_best_rank_gets_full_fusion_signal():
    candidate = _candidate(1, "neutral content", reliability_tier=5, published_at=NOW)
    signal = compute_citation_signal(candidate, rank=1, total=1, half_life_days_news=14)
    assert signal.chunk_id == 1
    assert signal.weight > 0


def test_aggregate_evidence_empty_candidates_returns_neutral_defaults():
    retrieval = RetrievalResult(low_confidence=True, candidates=[], scores={}, best_distance=None, fused_rank={})
    result = aggregate_evidence(retrieval)
    assert result.anchor_lean == 0.0
    assert result.contested is False
    assert result.citation_signals == []


def test_aggregate_evidence_contested_when_strong_sources_disagree():
    bullish = _candidate(1, "Apple beats earnings, strong growth, record revenue, surge, upgraded.", reliability_tier=5)
    bearish = _candidate(2, "Apple misses, downgrade, weak, plunge, lawsuit, decline.", reliability_tier=5)
    retrieval = RetrievalResult(
        low_confidence=False,
        candidates=[bullish, bearish],
        scores={1: 0.02, 2: 0.019},
        best_distance=0.1,
        fused_rank={1: 1, 2: 2},
    )
    result = aggregate_evidence(retrieval)
    assert result.contested is True
    assert result.strong_high > 0
    assert result.strong_low < 0


def test_aggregate_evidence_lone_weak_outlier_not_contested():
    """CLAUDE.md's Phase 12 rule: a lone weak outlier must never read as a
    contradiction. reliability_tier alone (weight 0.25) isn't decisive by
    design — every currently-included source already clears ADR-006's
    quality floor — so "weak" here compounds all three signals: poor
    fusion rank (last of many), stale (fully decayed), and low
    reliability, matching how a genuinely low-trust citation would
    actually present."""
    from datetime import timedelta

    strong_a = _candidate(1, "Apple held its annual meeting today.", reliability_tier=5, published_at=NOW)
    strong_b = _candidate(2, "Apple confirmed its usual quarterly schedule.", reliability_tier=5, published_at=NOW)
    weak_bearish_outlier = _candidate(
        3, "miss downgrade weak plunge lawsuit decline",
        reliability_tier=4, published_at=NOW - timedelta(days=120),
    )
    retrieval = RetrievalResult(
        low_confidence=False,
        candidates=[strong_a, strong_b, weak_bearish_outlier],
        scores={1: 0.03, 2: 0.028, 3: 0.01},
        best_distance=0.1,
        fused_rank={1: 1, 2: 2, 3: 3},
    )
    result = aggregate_evidence(retrieval)
    weak_signal = next(s for s in result.citation_signals if s.chunk_id == 3)
    assert weak_signal.weight < STRONG_WEIGHT_FLOOR
    assert result.contested is False


def test_aggregate_evidence_agreeing_strong_sources_not_contested():
    a = _candidate(1, "Apple beats earnings, strong growth.", reliability_tier=5)
    b = _candidate(2, "Apple surge, record revenue, upgraded.", reliability_tier=5)
    retrieval = RetrievalResult(
        low_confidence=False,
        candidates=[a, b],
        scores={1: 0.02, 2: 0.019},
        best_distance=0.1,
        fused_rank={1: 1, 2: 2},
    )
    result = aggregate_evidence(retrieval)
    assert result.contested is False
