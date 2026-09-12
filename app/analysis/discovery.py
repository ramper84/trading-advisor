"""Discovery's Boss (`CLAUDE.md`'s "Extension — Discovery", Axis 4):
calls the Actor once, runs the Critic over every suggestion, retries with
feedback for what failed, then — past one retry — drops only the
suggestions that never passed, never the whole batch, the same "never
silently discard" discipline `augmentation.py`'s token-budget cutoff
already established.
"""

from __future__ import annotations

import logging

from app.guardrails import discovery_guard
from app.retrieval.sql_retriever import GeneralNewsItemRow
from app.schemas import SuggestedCompany
from app.services.llm_service import generate_discovery_suggestions

logger = logging.getLogger(__name__)

MAX_RETRIES = 1


def _build_feedback(verdicts: list[discovery_guard.CriticVerdict]) -> str:
    lines = [f"- {v.suggestion.symbol}: {v.reason}" for v in verdicts if not v.passed]
    return "\n".join(lines)


def run_discovery(articles: list[GeneralNewsItemRow]) -> list[SuggestedCompany]:
    """The whole Actor-Critic-Boss loop for one scan. Returns only the
    suggestions that cleared the Critic — an empty list is a correct,
    expected result when nothing in the batch was worth surfacing (the
    Actor's own system prompt already instructs this), not a failure.

    Live verification (2026-09-12) found a real flaw in an earlier
    version of this loop: retrying the *whole* Actor call when even one
    suggestion failed discarded already-passing suggestions from the
    first attempt, and the retry was not guaranteed to be any better —
    a real run went from 2 good suggestions + 1 bad one down to 0 after
    a whole-batch retry threw away the 2 good ones and the retry's own
    output happened to fail too. Accepted suggestions now survive across
    retries; only a retry naming what's still missing/failing is sent
    back to the Actor, and only its *new* passing suggestions are added."""
    if not articles:
        return []
    articles_by_id = {a.id: a for a in articles}

    result = generate_discovery_suggestions(articles)
    verdicts = [discovery_guard.review(s, articles_by_id) for s in result.suggestions]
    accepted = [v.suggestion for v in verdicts if v.passed]
    last_failing = [v for v in verdicts if not v.passed]

    retries = 0
    while last_failing and retries < MAX_RETRIES:
        feedback = _build_feedback(verdicts)
        logger.info("discovery_retrying_with_feedback", extra={"feedback": feedback})
        result = generate_discovery_suggestions(articles, feedback=feedback)
        verdicts = [discovery_guard.review(s, articles_by_id) for s in result.suggestions]
        accepted_symbols = {s.symbol for s in accepted}
        accepted.extend(v.suggestion for v in verdicts if v.passed and v.suggestion.symbol not in accepted_symbols)
        last_failing = [v for v in verdicts if not v.passed]
        retries += 1

    if last_failing:
        logger.info(
            "discovery_suggestions_dropped",
            extra={"dropped": [(v.suggestion.symbol, v.reason) for v in last_failing]},
        )
    return accepted
