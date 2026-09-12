"""The request/response contract. Grows one model per capability as each
router lands (Phases 9-13); only the health check exists at Phase 1."""

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"


class Citation(BaseModel):
    """One claim in the rationale, grounded to a real retrieved chunk.
    `chunk_id` is validated post-generation against the actual retrieved
    set (`s11-03`'s citation integrity check) — Phase 13, not here; this
    schema only shapes what the model must produce."""

    chunk_id: int
    claim: str = Field(description="A short paraphrase of the specific fact this citation supports.")


class AnalysisSynthesis(BaseModel):
    """Phase 12's Instructor-validated generation output (`s11-02`/`s11-03`).
    `confidence` here is the model's own self-reported estimate — Phase
    13's `analysis_guard.py` computes the real, code-derived confidence
    and quality_status separately; the two are never conflated."""

    stance: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    citations: list[Citation]


class InputRelevanceResult(BaseModel):
    """Phase 13's cheapest, first check — run before retrieval/generation
    ever start. An execution-shaped request ("buy me 10 shares") is out
    of scope entirely, not an analysis question to answer."""

    in_scope: bool
    reason: str | None = None


class GuardedAnalysis(BaseModel):
    """Phase 13's confidence gate output — `s11-04`'s verification funnel
    (citation integrity -> numeric grounding -> the reliability-tier rule)
    combined into one code-derived `confidence` and `quality_status`.
    `insufficient` forces `stance=NEUTRAL` as an enforced invariant, never
    a convention the caller has to remember to apply."""

    stance: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    confidence: float = Field(ge=0.0, le=1.0)
    quality_status: Literal["grounded", "degraded", "insufficient"]
    rationale: str
    resolved_citations: list[int]
    dangling_citations: list[int]
    ungrounded_figures: list[float]
    reliability_rule_passed: bool


class SuggestedCompany(BaseModel):
    """Discovery's Actor output (`CLAUDE.md`'s "Extension — Discovery"),
    one candidate. `source_article_ids` must reference `general_news_items.id`
    rows actually given to the Actor — checked by the deterministic Critic
    (`discovery_guard.py`), never trusted to the model."""

    symbol: str = Field(description="The ticker as it would be looked up via yfinance, e.g. AAPL or WALMEX.MX.")
    company_name: str
    reasoning: str = Field(description="Why this is worth a look right now — catalysts, momentum, unusual news density, not just a name mention.")
    source_article_ids: list[int]


class DiscoverySuggestions(BaseModel):
    suggestions: list[SuggestedCompany]


class SymbolIdentityVerdict(BaseModel):
    """Discovery's one deliberate semantic-judge exception (`CLAUDE.md`'s
    "Extension — Discovery"): confirming a resolved instrument's real
    name matches the company a suggestion claims genuinely needs
    judgment — a resolved ticker being *real* (checked by
    `discovery_guard.check_symbol_resolves`) is not the same as it being
    the *right* one. `matches=False` is the safe default; when in doubt,
    doubt (`s11-04`'s own instruction to the reference judge)."""

    matches: bool
    reason: str
