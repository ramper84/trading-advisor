"""Phase 13's confidence gate — `s11-03`/`s11-04`'s verification funnel,
cheap checks first, none of them a model call:

  (1) citation integrity (`s11-03`) — every cited `chunk_id` must have
      been in the retrieved set, checked in code, never trusted to the
      model: a dangling citation looks exactly like a legitimate one.
  (2) numeric grounding (`s11-04`) — every $ or % figure in the rationale
      must match a real retrieved value; a figure matching nothing is
      flagged.
  (3) the reliability-tier rule (CLAUDE.md §2's ADR) — a directional
      stance needs >=1 resolved citation with `reliability_tier >= 3`.

These combine into one code-derived `confidence` and `quality_status`;
`insufficient` forces `stance=NEUTRAL` as an enforced invariant.

Also: `check_input_relevance`, run before retrieval/generation ever start
— an execution-shaped request is out of scope entirely, not a thin
analysis to answer and then abstain on.
"""

from __future__ import annotations

import re
from typing import Optional

from app.analysis.synthesis import EvidenceAggregate
from app.retrieval.sql_retriever import DailyBarRow, EconomicIndicatorRow, FundamentalsRow, ObservationRow
from app.retrieval.vector_retriever import RetrievalResult
from app.schemas import AnalysisSynthesis, GuardedAnalysis, InputRelevanceResult

# CLAUDE.md §2's Axis-4 ADR: a directional stance needs >=1 citation
# clearing this floor. Every currently-included catalog source already
# scores reliability>=4 (ADR-006 dropped the one source that didn't), so
# this is defense-in-depth for a future lower-quality source, not a live
# constraint on today's catalog.
STRONG_RELIABILITY_TIER_FLOOR = 3

# A figure within this relative fraction of a real retrieved value counts
# as grounded — light rounding tolerance (the model paraphrases "$326.57"
# as "$326.6" routinely), not license to drift arbitrarily far.
NUMERIC_GROUNDING_RELATIVE_TOLERANCE = 0.01

# Imperative execution shapes only — "buy me 10 shares", "place an order"
# — never a question about buying ("should I buy AAPL", "is AAPL a buy"),
# which is a legitimate analysis request this system must still answer.
_EXECUTION_PATTERNS = [
    re.compile(r"\bbuy\s+(?:me\s+)?\d", re.IGNORECASE),
    re.compile(r"\bsell\s+(?:me\s+)?\d", re.IGNORECASE),
    re.compile(r"\bpurchase\s+\d+\s+shares?\b", re.IGNORECASE),
    re.compile(r"\bplace\s+(?:an?\s+)?(?:buy|sell|trade|order)\b", re.IGNORECASE),
    re.compile(r"\bexecute\s+(?:a\s+)?(?:trade|order)\b", re.IGNORECASE),
]

_OUT_OF_SCOPE_REASON = (
    "This system cannot place trades or execute orders of any kind — no brokerage "
    "account, no order execution. It can only analyze and report on market data."
)

_DOLLAR_FIGURE_RE = re.compile(r"\$\s?(-?\d[\d,]*\.?\d*)")
_PERCENT_FIGURE_RE = re.compile(r"(-?\d[\d,]*\.?\d*)\s?%")


def check_input_relevance(query: str) -> InputRelevanceResult:
    for pattern in _EXECUTION_PATTERNS:
        if pattern.search(query):
            return InputRelevanceResult(in_scope=False, reason=_OUT_OF_SCOPE_REASON)
    return InputRelevanceResult(in_scope=True)


def check_citation_integrity(
    citations: list, retrieved_chunk_ids: set[int]
) -> tuple[list[int], list[int]]:
    """Referential integrity (`s11-03`): resolved ids were actually in the
    retrieved context; dangling ids were not, regardless of how plausible
    they look."""
    resolved: list[int] = []
    dangling: list[int] = []
    for citation in citations:
        (resolved if citation.chunk_id in retrieved_chunk_ids else dangling).append(citation.chunk_id)
    return resolved, dangling


def check_reliability_rule(
    stance: str, resolved_chunk_ids: list[int], candidates_by_id: dict
) -> bool:
    """CLAUDE.md §2's ADR: NEUTRAL needs no strong backing to be
    defensible; a directional stance does."""
    if stance == "NEUTRAL":
        return True
    return any(
        candidates_by_id[cid].reliability_tier >= STRONG_RELIABILITY_TIER_FLOOR
        for cid in resolved_chunk_ids
        if cid in candidates_by_id
    )


def _parse_figures(pattern: re.Pattern, text: str) -> list[float]:
    figures = []
    for match in pattern.finditer(text):
        try:
            figures.append(float(match.group(1).replace(",", "")))
        except ValueError:
            continue
    return figures


def _matches_pool(figure: float, pool: list[float], relative_tolerance: float) -> bool:
    if not pool:
        return False  # no grounding data at all -> nothing can be grounded (s11-04's fabrication case)
    return any(abs(figure - v) <= max(abs(v) * relative_tolerance, 0.01) for v in pool)


def _dollar_pool(observation: Optional[ObservationRow], daily_bars: list[DailyBarRow]) -> list[float]:
    values: list[float] = []
    if observation is not None:
        for v in (
            observation.price, observation.previous_close, observation.day_high, observation.day_low,
            observation.year_high, observation.year_low, observation.fifty_day_average,
            observation.two_hundred_day_average,
        ):
            if v is not None:
                values.append(float(v))
    for bar in daily_bars:
        for v in (bar.open, bar.high, bar.low, bar.close):
            if v is not None:
                values.append(float(v))
    return values


def _percent_pool(
    fundamentals: Optional[FundamentalsRow], economic_indicators: list[EconomicIndicatorRow]
) -> list[float]:
    values: list[float] = []
    if fundamentals is not None:
        if fundamentals.dividend_yield is not None:
            values.append(float(fundamentals.dividend_yield))  # already percent-scale (yfinance convention)
        # These are 0..1 fractions (yfinance convention); the rationale may
        # phrase either "0.50" or "50%" — include both readings rather
        # than guess which the model will use. A known imprecision, not a
        # claim of unit certainty.
        for v in (fundamentals.gross_margin, fundamentals.operating_margin, fundamentals.roe, fundamentals.fcf_yield):
            if v is not None:
                values.append(float(v))
                values.append(float(v) * 100)
    for indicator in economic_indicators:
        values.append(float(indicator.value))
    return values


def numeric_grounding(
    rationale: str,
    observation: Optional[ObservationRow],
    daily_bars: list[DailyBarRow],
    fundamentals: Optional[FundamentalsRow],
    economic_indicators: list[EconomicIndicatorRow],
    relative_tolerance: float = NUMERIC_GROUNDING_RELATIVE_TOLERANCE,
) -> list[float]:
    """`s11-04`'s numeric anchoring, adapted: nothing is synthesized into
    a [low, high] range in this domain (unlike the reference's budget
    hours), so a figure is grounded iff it matches a real retrieved value
    directly, not "falls within an interpolated range". Only $ and %
    figures are checked — a deliberate scope limit to avoid false
    positives on bare numbers that aren't financial claims at all (an
    Item number, an RSI period). Returns the figures that matched
    nothing, i.e. the ones flagged as unsupported."""
    dollar_pool = _dollar_pool(observation, daily_bars)
    percent_pool = _percent_pool(fundamentals, economic_indicators)

    ungrounded: list[float] = []
    for figure in _parse_figures(_DOLLAR_FIGURE_RE, rationale):
        if not _matches_pool(figure, dollar_pool, relative_tolerance):
            ungrounded.append(figure)
    for figure in _parse_figures(_PERCENT_FIGURE_RE, rationale):
        if not _matches_pool(figure, percent_pool, relative_tolerance):
            ungrounded.append(figure)
    return ungrounded


def guard_analysis(
    synthesis: AnalysisSynthesis,
    retrieval: RetrievalResult,
    aggregate: EvidenceAggregate,
    observation: Optional[ObservationRow],
    daily_bars: list[DailyBarRow],
    fundamentals: Optional[FundamentalsRow],
    economic_indicators: list[EconomicIndicatorRow],
) -> GuardedAnalysis:
    """Combines the three checks into one `confidence` + `quality_status`.
    `confidence` is derived from Phase 12's own per-citation weights
    (`aggregate.citation_signals`) over the RESOLVED citations only — the
    same signal that already decided ranking and the contested flag, not
    a new number invented for this layer."""
    retrieved_ids = {c.chunk_id for c in retrieval.candidates}
    candidates_by_id = {c.chunk_id: c for c in retrieval.candidates}

    resolved, dangling = check_citation_integrity(synthesis.citations, retrieved_ids)
    ungrounded_figures = numeric_grounding(synthesis.rationale, observation, daily_bars, fundamentals, economic_indicators)
    reliability_ok = check_reliability_rule(synthesis.stance, resolved, candidates_by_id)

    signals_by_id = {s.chunk_id: s for s in aggregate.citation_signals}
    resolved_weights = [signals_by_id[cid].weight for cid in resolved if cid in signals_by_id]
    base_confidence = sum(resolved_weights) / len(resolved_weights) if resolved_weights else 0.0

    # A citation list that is entirely dangling is the worst form of
    # referential-integrity failure (s11-03: "the one that is never
    # acceptable is ignoring it") — insufficient regardless of stance,
    # not merely degraded.
    fully_fabricated_citations = bool(synthesis.citations) and not resolved
    has_fabricated_figure = bool(ungrounded_figures)

    if fully_fabricated_citations or has_fabricated_figure or not reliability_ok:
        quality_status = "insufficient"
        stance = "NEUTRAL"
        confidence = min(base_confidence, 0.2)
    elif dangling or retrieval.low_confidence:
        # Phase 10's own soft-fail signal (retrieval.low_confidence) is
        # folded in here as a confidence-degrading input, not re-declared
        # as a fourth named check — it's exactly the "thin evidence"
        # s11-04's abstention discipline already covers, and forcing
        # NEUTRAL on thin-but-otherwise-clean evidence would be the
        # over-abstention the same article warns against.
        quality_status = "degraded"
        stance = synthesis.stance
        confidence = min(base_confidence, 0.5)
    else:
        quality_status = "grounded"
        stance = synthesis.stance
        confidence = round(base_confidence, 4)

    return GuardedAnalysis(
        stance=stance,
        confidence=confidence,
        quality_status=quality_status,
        rationale=synthesis.rationale,
        resolved_citations=resolved,
        dangling_citations=dangling,
        ungrounded_figures=ungrounded_figures,
        reliability_rule_passed=reliability_ok,
    )
