"""Phase 12's deterministic first stage (`articles/s11-02`'s two-stage
synthesis): a weighted signal per citation, and a weighted-median anchor
the generation call reasons over rather than invents.

The reference domain (historical budget "hours" per source) has a natural
per-source number to synthesize. This project's citations are market news/
filing chunks with no such number — and ADR-007 already ruled out adding
one via a per-article LLM call ("a real cost multiplier for no proven
benefit over computing stance once, at analysis time, from the retrieved
set"). `_keyword_lean` fills that gap the same way `s11-02` fills its own:
cheaply, deterministically, auditable in one sentence — a lexicon lookup,
not a model call, so it doesn't reopen ADR-007's decision. Its accuracy is
a known, named limitation (see its docstring), not assumed correctness.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.config import get_settings
from app.retrieval.hybrid_search import ChunkCandidate
from app.retrieval.temporal import temporal_weight
from app.retrieval.vector_retriever import RetrievalResult

# Three signals, not seven (s11-02's own "one sentence to justify each
# coefficient" discipline):
#  - fusion_rank weighs most: it's retrieval's own best signal of
#    relevance to THIS query, independent of source identity.
#  - temporal_weight next: freshness matters a lot for market-moving news,
#    less for a filing (temporal.py already caps filing weight at 1.0).
#  - reliability_tier last, but not zero: every INCLUDED catalog source
#    already clears ADR-006's quality floor, so it differentiates less
#    than the other two among sources that are all already "good enough".
FUSION_RANK_COEFFICIENT = 0.40
TEMPORAL_COEFFICIENT = 0.35
RELIABILITY_COEFFICIENT = 0.25

# A citation must clear this combined weight to count toward "strong" —
# the same floor value s11-02 itself uses, a reasonable starting point
# per its own "adjust by observing how many alerts are actionable"
# guidance (CLAUDE.md's Phase 17 golden set is where that tuning happens).
STRONG_WEIGHT_FLOOR = 0.4

# Absolute (not relative) sign-disagreement threshold: `s11-02`'s own
# `rel_spread = (high - low) / anchor` degenerates when the anchor is near
# zero, which is the common case here (many chunks have lean=0.0 — no
# keyword hit at all). Leans live in a bounded, zero-centered [-1, 1]
# range (unlike hours, always positive), so an absolute magnitude
# threshold on each side of zero is the honest adaptation, not the
# reference's relative-spread formula.
CONTESTED_LEAN_THRESHOLD = 0.3

_BULLISH_KEYWORDS = {
    "beat", "beats", "beating", "growth", "record", "upgrade", "upgraded",
    "outperform", "strong", "surge", "surged", "raised", "raises",
    "exceeds", "exceeded", "rally", "rallied", "gain", "gains", "gained",
}
_BEARISH_KEYWORDS = {
    "miss", "misses", "missed", "downgrade", "downgraded", "decline",
    "declined", "lawsuit", "investigation", "weak", "weakness", "plunge",
    "plunged", "cut", "cuts", "recall", "risk", "risks", "lawsuit",
    "loss", "losses", "warning", "warns", "layoffs", "probe",
}
_WORD_RE = re.compile(r"[a-z]+")


def _keyword_lean(content: str) -> float:
    """A cheap, deterministic bullish/bearish lean in [-1, 1] from lexicon
    hits alone — 0.0 means no signal (neutral or no match), not "confirmed
    neutral". Known, named limitation: a bare word-count heuristic can't
    tell a filing's standing "Item 1A. Risk Factors" section heading from
    an actual new risk being disclosed — it will skew every filing chunk
    slightly bearish just for containing that boilerplate heading. This is
    exactly `s11-01`'s own named trade-off (a word-matching filter degrades
    recall/precision silently); `evals/measure_retrieval.py` (Phase 17) is
    what would surface whether this costs real accuracy, not a guess now.
    """
    words = _WORD_RE.findall(content.lower())
    if not words:
        return 0.0
    bullish_hits = sum(1 for w in words if w in _BULLISH_KEYWORDS)
    bearish_hits = sum(1 for w in words if w in _BEARISH_KEYWORDS)
    total = bullish_hits + bearish_hits
    if total == 0:
        return 0.0
    return (bullish_hits - bearish_hits) / total


@dataclass
class CitationSignal:
    chunk_id: int
    weight: float  # combined_weight: fusion_rank + temporal + reliability_tier
    lean: float  # keyword-heuristic bullish/bearish lean, -1..1


@dataclass
class EvidenceAggregate:
    anchor_lean: float  # weighted median lean across ALL citations
    strong_low: float  # min lean among STRONG (weight >= floor) citations only
    strong_high: float  # max lean among STRONG citations only
    contested: bool  # strong citations disagree in direction, not just any two
    citation_signals: list[CitationSignal] = field(default_factory=list)


def weighted_median(values_weights: list[tuple[float, float]]) -> float:
    """Robust central tendency (`s11-02`): a single outlier citation
    cannot drag it, unlike a mean."""
    if not values_weights:
        return 0.0
    items = sorted(values_weights, key=lambda vw: vw[0])
    half = sum(weight for _, weight in items) / 2
    acc = 0.0
    for value, weight in items:
        acc += weight
        if acc >= half:
            return value
    return items[-1][0]


def combined_weight(fusion_rank_signal: float, temporal_signal: float, reliability_signal: float) -> float:
    return (
        FUSION_RANK_COEFFICIENT * fusion_rank_signal
        + TEMPORAL_COEFFICIENT * temporal_signal
        + RELIABILITY_COEFFICIENT * reliability_signal
    )


def compute_citation_signal(
    candidate: ChunkCandidate,
    rank: int,
    total: int,
    half_life_days_news: int,
) -> CitationSignal:
    fusion_rank_signal = (total - rank + 1) / total if total else 0.0
    temporal_signal = temporal_weight(candidate, half_life_days_news)
    reliability_signal = candidate.reliability_tier / 5.0
    weight = combined_weight(fusion_rank_signal, temporal_signal, reliability_signal)
    return CitationSignal(chunk_id=candidate.chunk_id, weight=weight, lean=_keyword_lean(candidate.content))


def aggregate_evidence(retrieval: RetrievalResult) -> EvidenceAggregate:
    """`s11-02`'s pipeline, corrected per CLAUDE.md's Phase 12 note (the
    handbook's own editor's note flags the same bug): `contested` and the
    low/high range are computed over STRONG citations only, never over the
    full set — a lone low-reliability outlier must not be able to
    manufacture a contradiction, and must not be able to widen the range
    the generation call is told to stay within."""
    settings = get_settings()
    total = len(retrieval.candidates)
    signals = [
        compute_citation_signal(
            candidate,
            rank=retrieval.fused_rank.get(candidate.chunk_id, i),
            total=total,
            half_life_days_news=settings.temporal_half_life_days_news,
        )
        for i, candidate in enumerate(retrieval.candidates, start=1)
    ]

    if not signals:
        return EvidenceAggregate(anchor_lean=0.0, strong_low=0.0, strong_high=0.0, contested=False, citation_signals=[])

    anchor = weighted_median([(s.lean, s.weight) for s in signals])
    strong = [s for s in signals if s.weight >= STRONG_WEIGHT_FLOOR]
    strong_leans = [s.lean for s in strong] or [anchor]
    strong_low, strong_high = min(strong_leans), max(strong_leans)
    contested = strong_high > CONTESTED_LEAN_THRESHOLD and strong_low < -CONTESTED_LEAN_THRESHOLD

    return EvidenceAggregate(
        anchor_lean=round(anchor, 4),
        strong_low=round(strong_low, 4),
        strong_high=round(strong_high, 4),
        contested=contested,
        citation_signals=signals,
    )
