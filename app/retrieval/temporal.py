"""Per-source-family temporal weighting (`articles/s10-06`'s domain-transfer
note, CLAUDE.md §2's ADR), applied last, over the fused survivors only —
never before RRF, since a weight computed on a candidate that RRF would
have dropped anyway is wasted work (s10-06's "cheap and excluding first,
expensive and fine last" ordering).

Two source families, not one blanket recency curve:
- News (`finnhub_news`, `yfinance_news`, `elfinanciero_news`,
  `el_economista_news`): genuinely decays — sentiment ages fast — so an
  exponential half-life applies.
- Filings (`sec_edgar_filings`): a "validity flips" source — a 10-Q
  supersedes the prior quarter's 10-Q, it doesn't fade beside it. The most
  recent filing per form type keeps full weight; older filings of the same
  form type are discounted at a fixed rate rather than smooth-decayed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.retrieval.hybrid_search import ChunkCandidate

FILING_SOURCES = {"sec_edgar_filings"}

# A superseded filing of the same form type is still relevant background,
# just clearly secondary to the current one — a fixed discount, not a
# smooth decay, since "how many quarters old" isn't a fading signal the
# way a news article's age is.
SUPERSEDED_FILING_WEIGHT = 0.4


def _age_days(published_at: datetime | None, now: datetime) -> float:
    if published_at is None:
        return 0.0
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    return max((now - published_at).total_seconds() / 86400, 0.0)


def _news_weight(candidate: ChunkCandidate, now: datetime, half_life_days: int) -> float:
    """Exponential decay: weight halves every half_life_days. A missing
    published_at can't be decayed against an unknown age, so it keeps full
    weight rather than being penalized for an absent field."""
    if candidate.published_at is None:
        return 1.0
    age = _age_days(candidate.published_at, now)
    return 0.5 ** (age / half_life_days)


def _filing_weights(candidates: list[ChunkCandidate]) -> dict[int, float]:
    """Group filing candidates by (symbol, form_type); the most recent
    published_at within each group keeps weight 1.0, the rest are
    discounted — recency picks the current filing, it doesn't fade the
    others out gradually."""
    latest_by_group: dict[tuple[str, str], datetime] = {}
    for candidate in candidates:
        form_type = candidate.metadata.get("form_type", "")
        group = (candidate.symbol, form_type)
        published_at = candidate.published_at
        if published_at is None:
            continue
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        if group not in latest_by_group or published_at > latest_by_group[group]:
            latest_by_group[group] = published_at

    weights: dict[int, float] = {}
    for candidate in candidates:
        form_type = candidate.metadata.get("form_type", "")
        group = (candidate.symbol, form_type)
        published_at = candidate.published_at
        if published_at is None:
            weights[candidate.chunk_id] = 1.0
            continue
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        is_latest = published_at == latest_by_group.get(group)
        weights[candidate.chunk_id] = 1.0 if is_latest else SUPERSEDED_FILING_WEIGHT
    return weights


def apply_temporal_weighting(
    fused: list[tuple[ChunkCandidate, float]],
    half_life_days_news: int,
    now: datetime | None = None,
) -> list[tuple[ChunkCandidate, float]]:
    """Multiplies each fused RRF score by its source family's temporal
    weight, then re-sorts. Returns (candidate, weighted_score) pairs."""
    now = now or datetime.now(timezone.utc)
    filing_candidates = [c for c, _ in fused if c.source_name in FILING_SOURCES]
    filing_weights = _filing_weights(filing_candidates)

    weighted: list[tuple[ChunkCandidate, float]] = []
    for candidate, fused_score in fused:
        if candidate.source_name in FILING_SOURCES:
            weight = filing_weights.get(candidate.chunk_id, 1.0)
        else:
            weight = _news_weight(candidate, now, half_life_days_news)
        weighted.append((candidate, fused_score * weight))

    weighted.sort(key=lambda pair: pair[1], reverse=True)
    return weighted


def temporal_weight(
    candidate: ChunkCandidate, half_life_days_news: int, now: datetime | None = None
) -> float:
    """Single-candidate weight, exposed for testing and for callers that
    already know a candidate isn't in a filing group (news-only checks)."""
    now = now or datetime.now(timezone.utc)
    if candidate.source_name in FILING_SOURCES:
        return 1.0
    return _news_weight(candidate, now, half_life_days_news)
