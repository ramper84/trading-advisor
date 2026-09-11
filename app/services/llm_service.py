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
from app.schemas import AnalysisSynthesis

logger = logging.getLogger(__name__)

_PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts" / "analyze" / "v1"
_env = Environment(loader=FileSystemLoader(_PROMPT_DIR), undefined=StrictUndefined, autoescape=False)

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
