"""Generation (Phase 12) and embedding (`ingest/embedding.py` already owns
the latter directly via the OpenAI SDK — this module is the generation
half of the tech-stack table's "LiteLLM + Instructor" entry).

`s11-02`'s two-stage split: `analysis/synthesis.py` computes the
deterministic aggregate in code; this module makes the one
Instructor-validated call that reasons over it rather than inventing the
arithmetic. gpt-4o-mini primary, a Claude Haiku fallback on any exception
from the primary call — matching CLAUDE.md §4's stated stack.
"""

from __future__ import annotations

import logging
from pathlib import Path

import instructor
import litellm
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.analysis.synthesis import EvidenceAggregate
from app.config import get_settings
from app.retrieval.sql_retriever import GeneralNewsItemRow
from app.schemas import AnalysisSynthesis, DiscoverySuggestions, SymbolIdentityVerdict

logger = logging.getLogger(__name__)

_PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts" / "analyze" / "v1"
_env = Environment(loader=FileSystemLoader(_PROMPT_DIR), undefined=StrictUndefined, autoescape=False)

_DISCOVERY_PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts" / "discovery" / "v1"
_discovery_env = Environment(loader=FileSystemLoader(_DISCOVERY_PROMPT_DIR), undefined=StrictUndefined, autoescape=False)

_client = instructor.from_litellm(litellm.completion)


def render_prompts(symbol: str, query: str, context: str, aggregate: EvidenceAggregate, low_confidence: bool) -> tuple[str, str]:
    system_prompt = _env.get_template("system.j2").render()
    user_prompt = _env.get_template("user.j2").render(
        symbol=symbol, query=query, context=context, aggregate=aggregate, low_confidence=low_confidence
    )
    return system_prompt, user_prompt


def generate_synthesis(
    symbol: str,
    query: str,
    context: str,
    aggregate: EvidenceAggregate,
    low_confidence: bool,
) -> AnalysisSynthesis:
    """The one generation call per `/analyze` request (§2: no orchestration
    — a single call, not an agentic loop). Falls back to
    `generation_model_fallback` only if the primary call itself raises;
    the fallback is not tried speculatively on every request."""
    settings = get_settings()
    system_prompt, user_prompt = render_prompts(symbol, query, context, aggregate, low_confidence)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        return _client.chat.completions.create(
            model=settings.generation_model_primary,
            messages=messages,
            response_model=AnalysisSynthesis,
            api_key=settings.openai_api_key,
        )
    except Exception:
        logger.exception(
            "primary generation model failed, falling back",
            extra={"symbol": symbol, "model": settings.generation_model_primary},
        )
        return _client.chat.completions.create(
            model=settings.generation_model_fallback,
            messages=messages,
            response_model=AnalysisSynthesis,
            api_key=settings.anthropic_api_key,
        )


def render_discovery_prompts(articles: list[GeneralNewsItemRow], feedback: str | None = None) -> tuple[str, str]:
    system_prompt = _discovery_env.get_template("system.j2").render()
    user_prompt = _discovery_env.get_template("user.j2").render(articles=articles, feedback=feedback)
    return system_prompt, user_prompt


def generate_discovery_suggestions(
    articles: list[GeneralNewsItemRow], feedback: str | None = None
) -> DiscoverySuggestions:
    """The Actor half of Discovery's Actor-Critic-Boss loop (`CLAUDE.md`'s
    "Extension — Discovery") — one call proposing candidate companies from
    a batch of general news. `feedback`, when given, is the Boss
    (`discovery.py`) retrying once with the Critic's specific rejection
    reasons — the same "retry with feedback, not a blind re-roll" pattern
    `s11-03`'s own citation-integrity retry discipline uses. Same
    primary/fallback pair as `generate_synthesis`."""
    settings = get_settings()
    system_prompt, user_prompt = render_discovery_prompts(articles, feedback)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        return _client.chat.completions.create(
            model=settings.generation_model_primary,
            messages=messages,
            response_model=DiscoverySuggestions,
            api_key=settings.openai_api_key,
        )
    except Exception:
        logger.exception("primary generation model failed for discovery, falling back")
        return _client.chat.completions.create(
            model=settings.generation_model_fallback,
            messages=messages,
            response_model=DiscoverySuggestions,
            api_key=settings.anthropic_api_key,
        )


def verify_symbol_identity(claimed_name: str, resolved_name: str) -> SymbolIdentityVerdict:
    """Discovery's one deliberate semantic-judge exception — the rest of
    this project's Critics are pure code, but live verification
    (2026-09-12) showed a real, dangerous gap a rule cannot close: a
    resolved ticker being real is not the same as it being the *right*
    one (`PEMEX` resolved to an unrelated mutual fund, not Petróleos
    Mexicanos), while a naive exact/fuzzy string match would also reject
    a genuinely correct case (`Volaris` vs. its own formal legal name,
    zero shared substrings). `PLAYBOOK.md`'s Axis 4 names this exact
    carve-out: reserve a model call for the Critic only when the check
    genuinely requires judgment no rule can express. Uses the fallback
    model as ITS primary — `s11-04`'s "a different, cheaper model than
    the generator" discipline — with the primary generation model as its
    own fallback."""
    messages = [
        {"role": "system", "content": _discovery_env.get_template("identity_judge_system.j2").render()},
        {
            "role": "user",
            "content": _discovery_env.get_template("identity_judge_user.j2").render(
                claimed_name=claimed_name, resolved_name=resolved_name
            ),
        },
    ]
    settings = get_settings()
    try:
        return _client.chat.completions.create(
            model=settings.generation_model_fallback,
            messages=messages,
            response_model=SymbolIdentityVerdict,
            api_key=settings.anthropic_api_key,
        )
    except Exception:
        logger.exception("identity judge model failed, falling back")
        return _client.chat.completions.create(
            model=settings.generation_model_primary,
            messages=messages,
            response_model=SymbolIdentityVerdict,
            api_key=settings.openai_api_key,
        )
