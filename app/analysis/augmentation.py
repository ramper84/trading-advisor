"""Phase 11 — augmentation: turns SQL + vector retrieval output into one
structured, XML-delimited context block (`articles/s09-04`), with
`s11-01`'s distillation discipline applied to the Axis-3 side only — the
Axis-2 side is already terse, typed data with nothing to compress.

Pure function, no DB/network access of its own: the caller (Phase 12's
generation step, once it exists) fetches rows via `sql_retriever.py` and a
`RetrievalResult` via `vector_retriever.retrieve()` and passes them in
here. No router wires this up yet — `POST /analyze` isn't a coherent
endpoint until generation (Phase 12) and the confidence gate (Phase 13)
exist behind it too; exposing "here is some context" alone would be a
half-built feature, not this phase's deliverable.

Pipeline order follows `s11-01`'s stated sequence — compress, order, fit
to budget (no abstractive "extract key points" stage: this project's
sources are already structured/short enough that a second LLM call to
summarize them would be pure cost for no proven benefit, the same
reasoning ADR-007 used to defer per-article sentiment tagging).
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from typing import Optional

import tiktoken
from pydantic import BaseModel

from app.analysis.technical_indicators import compute_technical_indicators
from app.config import get_settings
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

logger = logging.getLogger(__name__)

_ENCODING = tiktoken.get_encoding("cl100k_base")  # same encoder ingest/embedding.py uses

# Mirrors retrieval/temporal.py's own family split — the "validity flips"
# source gets compressed by symbol/figure relevance; the news sources are
# already short-form and skip compression entirely (CLAUDE.md §7 Phase 11).
FILING_SOURCES = {"sec_edgar_filings"}

_FIGURE_RE = re.compile(r"[$€£]|%|\b\d[\d,.]*\b")


class AugmentedContext(BaseModel):
    context: str
    dropped_chunk_ids: list[int]
    token_estimate: int
    low_confidence: bool


def _xml_attr_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;")


def _attr(name: str, value) -> str:
    return f'{name}="{value}"' if value is not None else ""


def _looks_like_figure(line: str) -> bool:
    """A line worth keeping even if it doesn't name the symbol — a
    heuristic, not a guarantee (s11-01's own named honest trade-off: a
    word-matching extractive filter degrades recall silently when a
    relevant line uses neither the symbol nor a recognizable figure)."""
    return bool(_FIGURE_RE.search(line))


def compress_filing_chunk(candidate: ChunkCandidate, symbol: str) -> ChunkCandidate:
    """Extractive compression (`s11-01`): keep only lines mentioning the
    symbol or that look like a figure. No model call, no rewriting — it
    only copies, so it cannot invent. If the filter empties the chunk, the
    original full content is kept instead: a compression that silently
    empties the context is the same failure as an over-aggressive
    retrieval filter, just one layer later."""
    symbol_lower = symbol.lower()
    kept = [
        line
        for line in candidate.content.splitlines()
        if symbol_lower in line.lower() or _looks_like_figure(line)
    ]
    if not kept:
        return candidate
    return replace(candidate, content="\n".join(kept))


def compress_chunks(candidates: list[ChunkCandidate], symbol: str) -> list[ChunkCandidate]:
    """Applies extractive compression only to filing-family chunks;
    news-family chunks pass through unchanged (already short-form)."""
    return [
        compress_filing_chunk(c, symbol) if c.source_name in FILING_SOURCES else c
        for c in candidates
    ]


def reorder_u_pattern(items: list) -> list:
    """`articles/s09-04`'s corrected edge-loading manoeuvre — NOT `s11-01`'s
    own broken `insert(0, item)` version, which the handbook itself flags
    as inverting the intent (see CLAUDE.md §7 Phase 11's note). Assumes
    `items` arrives sorted by descending relevance; builds the two halves
    separately and concatenates `front + reversed(back)`, e.g.
    `[e0, e1, e2, e3] -> [e0, e2, e3, e1]` — the two strongest survive at
    the edges, never pushed toward the middle."""
    front, back = [], []
    for i, item in enumerate(items):
        (front if i % 2 == 0 else back).append(item)
    return front + list(reversed(back))


def _wrap_chunk(candidate: ChunkCandidate, relevance_score: float) -> str:
    """XML `<source>` delimiter (`s09-04`) — the model recognizes this as
    an attributable, citable unit, unlike a bare `"\\n\\n".join`."""
    attrs = [
        _attr("id", candidate.chunk_id),
        _attr("source_name", candidate.source_name),
        _attr("symbol", candidate.symbol),
        _attr("reliability_tier", candidate.reliability_tier),
        _attr("relevance_score", f"{relevance_score:.5f}"),
    ]
    if candidate.published_at is not None:
        attrs.append(_attr("published_at", candidate.published_at.isoformat()))
    if candidate.section_title:
        attrs.append(_attr("section_title", _xml_attr_escape(candidate.section_title)))
    if candidate.url:
        attrs.append(_attr("url", _xml_attr_escape(candidate.url)))
    attr_str = " ".join(a for a in attrs if a)
    return f"<source {attr_str}>\n{candidate.content.strip()}\n</source>"


def fit_to_budget(
    wrapped: list[tuple[int, str]], token_budget: int
) -> tuple[list[str], list[int], int]:
    """`s11-01`'s greedy fit, run over already edge-loaded input: unlike
    `s09-04`'s original `truncate_to_token_budget` (which `break`s on the
    first miss, correct only for a monotonically-descending-relevance
    list), this keeps checking every remaining item — necessary here since
    edge-loading means relevance is no longer monotonic by position.
    Whole-chunk granularity only: a chunk that doesn't fit entire never
    enters partially."""
    kept_blocks: list[str] = []
    dropped_ids: list[int] = []
    used = 0
    for chunk_id, block in wrapped:
        cost = len(_ENCODING.encode(block))
        if used + cost <= token_budget:
            kept_blocks.append(block)
            used += cost
        else:
            dropped_ids.append(chunk_id)
    return kept_blocks, dropped_ids, used


def build_market_data_block(
    symbol: str,
    instrument: Optional[InstrumentRow],
    observation: Optional[ObservationRow],
    daily_bars: list[DailyBarRow],
    fundamentals: Optional[FundamentalsRow],
    analyst_ratings: list[AnalystRatingRow],
    economic_indicators: list[EconomicIndicatorRow],
) -> str:
    """Deterministic Axis-2 block — no compression or truncation applies
    here: it's already typed, terse data, never dropped for budget (the
    token-budget cutoff (`fit_to_budget`) only ever trims Axis-3 chunks)."""
    parts = [f'<market_data symbol="{symbol}">']

    if instrument is not None:
        attrs = " ".join(
            a
            for a in (
                _attr("exchange", instrument.exchange),
                _attr("currency", instrument.currency),
                _attr("quote_type", instrument.quote_type),
                _attr("sector", instrument.sector),
                _attr("industry", instrument.industry),
                _attr("country", instrument.country),
            )
            if a
        )
        parts.append(f"  <instrument {attrs} />")

    if observation is not None:
        attrs = " ".join(
            a
            for a in (
                _attr("observed_at", observation.observed_at.isoformat()),
                _attr("price", observation.price),
                _attr("previous_close", observation.previous_close),
                _attr("day_high", observation.day_high),
                _attr("day_low", observation.day_low),
                _attr("year_high", observation.year_high),
                _attr("year_low", observation.year_low),
                _attr("fifty_day_average", observation.fifty_day_average),
                _attr("two_hundred_day_average", observation.two_hundred_day_average),
                _attr("volume", observation.volume),
                _attr("market_cap", observation.market_cap),
                _attr("source", observation.source_name),
            )
            if a
        )
        parts.append(f"  <latest_quote {attrs} />")

    if daily_bars:
        # sql_retriever.get_recent_daily_bars returns newest-first
        # (ORDER BY bar_date DESC); compute_technical_indicators expects
        # oldest-first closes, since RSI/returns are directional.
        closes = [bar.close for bar in reversed(daily_bars)]
        indicators = compute_technical_indicators(closes)
        attrs = " ".join(
            a
            for a in (
                _attr("rsi_14", indicators.rsi_14),
                _attr("volatility", indicators.volatility),
                _attr("window_days", len(closes)),
            )
            if a
        )
        parts.append(f"  <technical_indicators {attrs} />")

    if fundamentals is not None:
        attrs = " ".join(
            a
            for a in (
                _attr("as_of", fundamentals.snapshot_date.isoformat()),
                _attr("pe_ratio", fundamentals.pe_ratio),
                _attr("pb_ratio", fundamentals.pb_ratio),
                _attr("ev_ebitda", fundamentals.ev_ebitda),
                _attr("dividend_yield", fundamentals.dividend_yield),
                _attr("fcf_yield", fundamentals.fcf_yield),
                _attr("market_cap", fundamentals.market_cap),
                _attr("revenue", fundamentals.revenue),
                _attr("net_income", fundamentals.net_income),
                _attr("eps", fundamentals.eps),
                _attr("gross_margin", fundamentals.gross_margin),
                _attr("operating_margin", fundamentals.operating_margin),
                _attr("debt_to_equity", fundamentals.debt_to_equity),
                _attr("roe", fundamentals.roe),
            )
            if a
        )
        parts.append(f"  <fundamentals {attrs} />")

    if analyst_ratings:
        parts.append("  <analyst_ratings>")
        for rating in analyst_ratings:
            attrs = " ".join(
                a
                for a in (
                    _attr("rated_at", rating.rated_at.isoformat()),
                    _attr("firm", _xml_attr_escape(rating.firm)),
                    _attr("action", rating.action),
                    _attr("from_grade", rating.from_grade),
                    _attr("to_grade", rating.to_grade),
                )
                if a
            )
            parts.append(f"    <rating {attrs} />")
        parts.append("  </analyst_ratings>")

    if economic_indicators:
        country = economic_indicators[0].country
        parts.append(f'  <economic_indicators country="{country}">')
        for indicator in economic_indicators:
            attrs = " ".join(
                a
                for a in (
                    _attr("series_id", indicator.series_id),
                    _attr("name", _xml_attr_escape(indicator.series_name)),
                    _attr("value", indicator.value),
                    _attr("observed_on", indicator.observed_on.isoformat()),
                )
                if a
            )
            parts.append(f"    <indicator {attrs} />")
        parts.append("  </economic_indicators>")

    parts.append("</market_data>")
    return "\n".join(parts)


def assemble_context(
    symbol: str,
    *,
    instrument: Optional[InstrumentRow],
    observation: Optional[ObservationRow],
    daily_bars: list[DailyBarRow],
    fundamentals: Optional[FundamentalsRow],
    analyst_ratings: list[AnalystRatingRow],
    economic_indicators: list[EconomicIndicatorRow],
    retrieval: RetrievalResult,
    token_budget: Optional[int] = None,
) -> AugmentedContext:
    """The full (a)-(d) pipeline: build the deterministic Axis-2 block,
    then compress -> order (edge-load) -> fit-to-budget the Axis-3 chunks,
    concatenate, and report what (if anything) the budget cutoff dropped —
    never silently."""
    budget = token_budget if token_budget is not None else get_settings().analysis_context_token_budget

    market_data_block = build_market_data_block(
        symbol, instrument, observation, daily_bars, fundamentals, analyst_ratings, economic_indicators
    )
    market_data_tokens = len(_ENCODING.encode(market_data_block))

    compressed = compress_chunks(retrieval.candidates, symbol)
    scored = [(c, retrieval.scores.get(c.chunk_id, 0.0)) for c in compressed]
    ordered = reorder_u_pattern(scored)
    wrapped = [(candidate.chunk_id, _wrap_chunk(candidate, score)) for candidate, score in ordered]

    remaining_budget = max(budget - market_data_tokens, 0)
    kept_blocks, dropped_ids, sources_tokens = fit_to_budget(wrapped, remaining_budget)

    if dropped_ids:
        logger.info(
            "augmentation_dropped_chunks",
            extra={"symbol": symbol, "dropped_chunk_ids": dropped_ids},
        )

    sources_block = "\n\n".join(kept_blocks)
    context = f"{market_data_block}\n\n{sources_block}" if sources_block else market_data_block

    return AugmentedContext(
        context=context,
        dropped_chunk_ids=dropped_ids,
        token_estimate=market_data_tokens + sources_tokens,
        low_confidence=retrieval.low_confidence,
    )
