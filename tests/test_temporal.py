from datetime import datetime, timedelta, timezone

from app.retrieval.hybrid_search import ChunkCandidate
from app.retrieval.temporal import SUPERSEDED_FILING_WEIGHT, apply_temporal_weighting, temporal_weight

NOW = datetime(2026, 9, 10, tzinfo=timezone.utc)


def _news_candidate(chunk_id, age_days, source_name="finnhub_news"):
    return ChunkCandidate(
        chunk_id=chunk_id,
        source_name=source_name,
        symbol="AAPL",
        document_id=f"doc-{chunk_id}",
        reliability_tier=4,
        content="content",
        published_at=NOW - timedelta(days=age_days),
        url=None,
        section_title=None,
    )


def _filing_candidate(chunk_id, published_at, form_type="10-Q"):
    return ChunkCandidate(
        chunk_id=chunk_id,
        source_name="sec_edgar_filings",
        symbol="AAPL",
        document_id=f"doc-{chunk_id}",
        reliability_tier=5,
        content="content",
        published_at=published_at,
        url=None,
        section_title="Item 2",
        metadata={"form_type": form_type},
    )


def test_news_weight_decays_by_half_life():
    candidate = _news_candidate(1, age_days=14)
    weight = temporal_weight(candidate, half_life_days_news=14, now=NOW)
    assert abs(weight - 0.5) < 1e-9


def test_news_weight_full_at_zero_age():
    candidate = _news_candidate(1, age_days=0)
    assert temporal_weight(candidate, half_life_days_news=14, now=NOW) == 1.0


def test_news_weight_full_when_published_at_missing():
    candidate = _news_candidate(1, age_days=0)
    candidate.published_at = None
    assert temporal_weight(candidate, half_life_days_news=14, now=NOW) == 1.0


def test_filing_weight_always_full_via_temporal_weight_helper():
    candidate = _filing_candidate(1, NOW - timedelta(days=400))
    assert temporal_weight(candidate, half_life_days_news=14, now=NOW) == 1.0


def test_apply_temporal_weighting_discounts_superseded_filing():
    latest = _filing_candidate(1, NOW - timedelta(days=1), form_type="10-Q")
    superseded = _filing_candidate(2, NOW - timedelta(days=95), form_type="10-Q")
    fused = [(latest, 1.0), (superseded, 1.0)]

    weighted = apply_temporal_weighting(fused, half_life_days_news=14, now=NOW)
    scores = {c.chunk_id: score for c, score in weighted}

    assert scores[1] == 1.0
    assert scores[2] == SUPERSEDED_FILING_WEIGHT
    assert weighted[0][0].chunk_id == 1


def test_apply_temporal_weighting_different_form_types_both_stay_latest():
    tenq = _filing_candidate(1, NOW - timedelta(days=1), form_type="10-Q")
    tenk = _filing_candidate(2, NOW - timedelta(days=1), form_type="10-K")
    fused = [(tenq, 1.0), (tenk, 1.0)]

    weighted = apply_temporal_weighting(fused, half_life_days_news=14, now=NOW)
    scores = {c.chunk_id: score for c, score in weighted}

    assert scores[1] == 1.0
    assert scores[2] == 1.0


def test_apply_temporal_weighting_reorders_news_by_recency():
    old = _news_candidate(1, age_days=60)
    fresh = _news_candidate(2, age_days=0)
    fused = [(old, 1.0), (fresh, 1.0)]  # old ranked first by RRF before temporal applies

    weighted = apply_temporal_weighting(fused, half_life_days_news=14, now=NOW)

    assert weighted[0][0].chunk_id == 2
