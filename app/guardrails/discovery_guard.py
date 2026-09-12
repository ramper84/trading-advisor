"""Discovery's Critic (`CLAUDE.md`'s "Extension — Discovery", Axis 4) —
mostly deterministic code, mirroring `analysis_guard.py`'s own shape
(citation integrity, a domain-specific grounding check, the reliability-
tier rule), plus one deliberate semantic-judge exception: confirming a
resolved symbol is not just real but the *right* company genuinely needs
judgment no string-matching rule can express (see
`verify_symbol_identity`'s own docstring for the live evidence).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.retrieval.sql_retriever import GeneralNewsItemRow
from app.schemas import SuggestedCompany
from app.services import market_data
from app.services.llm_service import verify_symbol_identity

# Matches analysis_guard.py's own STRONG_RELIABILITY_TIER_FLOOR — the
# same floor, not a separately-tuned one, since it's the same policy
# question ("does a claim have real backing") in both places.
STRONG_RELIABILITY_TIER_FLOOR = 3


def check_article_citations(
    suggestion: SuggestedCompany, article_ids: set[int]
) -> tuple[list[int], list[int]]:
    """Referential integrity (`s11-03`), applied here exactly as in
    `analysis_guard.check_citation_integrity` — this check is
    domain-agnostic, an article id either was or wasn't in the batch."""
    resolved = [aid for aid in suggestion.source_article_ids if aid in article_ids]
    dangling = [aid for aid in suggestion.source_article_ids if aid not in article_ids]
    return resolved, dangling


def resolve_symbol(symbol: str) -> Optional[dict]:
    """Confirmed live (2026-09-12): `yfinance` returns a near-empty dict
    for a bogus or non-equity symbol (e.g. `PEMEX.MX` — Pemex is
    state-owned with no traded common equity — a real case the Actor
    produced in live verification, not a hypothetical) rather than
    raising. Resolution is checked by the presence of real identifying
    fields, never by catching an exception that never comes. Returns the
    info dict (so the identity check below can reuse it without a second
    API call) or `None` if the symbol doesn't resolve at all."""
    try:
        info = market_data.get_instrument_info(symbol)
    except Exception:
        return None
    if info.get("symbol") and info.get("quoteType"):
        return info
    return None


def check_symbol_identity(claimed_name: str, resolved_info: dict) -> bool:
    """The semantic-judge exception (`llm_service.verify_symbol_identity`'s
    own docstring has the live evidence for why this can't be a rule) —
    only ever called after `resolve_symbol` already confirmed something
    real exists, per this project's own "cheap and excluding first,
    expensive and fine last" ordering (`s10-06`)."""
    resolved_name = resolved_info.get("longName") or resolved_info.get("shortName") or ""
    if not resolved_name:
        return False
    verdict = verify_symbol_identity(claimed_name, resolved_name)
    return verdict.matches


def check_reliability(resolved_article_ids: list[int], articles_by_id: dict[int, GeneralNewsItemRow]) -> bool:
    return any(
        articles_by_id[aid].reliability_tier >= STRONG_RELIABILITY_TIER_FLOOR
        for aid in resolved_article_ids
        if aid in articles_by_id
    )


@dataclass
class CriticVerdict:
    suggestion: SuggestedCompany
    passed: bool
    resolved_article_ids: list[int]
    dangling_article_ids: list[int]
    symbol_resolved: bool
    symbol_identity_matched: bool
    reliability_passed: bool
    reason: str


def review(suggestion: SuggestedCompany, articles_by_id: dict[int, GeneralNewsItemRow]) -> CriticVerdict:
    article_ids = set(articles_by_id.keys())
    resolved, dangling = check_article_citations(suggestion, article_ids)
    reliability_ok = check_reliability(resolved, articles_by_id)

    resolved_info = resolve_symbol(suggestion.symbol)
    symbol_ok = resolved_info is not None
    # The identity judge is a real LLM call — only spend it once the
    # symbol is confirmed to resolve to something at all (s10-06's own
    # cheap-first ordering, applied to a model call instead of a vector
    # search).
    identity_ok = check_symbol_identity(suggestion.company_name, resolved_info) if symbol_ok else False

    reasons = []
    if dangling:
        reasons.append(f"cited article id(s) {dangling} were not in the batch given")
    if not symbol_ok:
        reasons.append(f"symbol {suggestion.symbol!r} does not resolve to a real, tradeable instrument")
    elif not identity_ok:
        reasons.append(f"symbol {suggestion.symbol!r} resolves to a real instrument, but not to {suggestion.company_name!r}")
    if not reliability_ok:
        reasons.append("no cited article meets the reliability-tier floor")

    return CriticVerdict(
        suggestion=suggestion,
        passed=not reasons,
        resolved_article_ids=resolved,
        dangling_article_ids=dangling,
        symbol_resolved=symbol_ok,
        symbol_identity_matched=identity_ok,
        reliability_passed=reliability_ok,
        reason="; ".join(reasons),
    )
