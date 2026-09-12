"""Deterministic trending ranking (Phase 18) — NO LLM import, matching
`technical_indicators.py`'s own rule. Ranks monitored symbols by how much
they've moved, from the same `market_observations` data the rest of the
pipeline already reads — no separate computation path to keep in sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.retrieval.sql_retriever import ObservationRow


@dataclass
class TrendingEntry:
    symbol: str
    price: float
    percent_change: Optional[float]
    volume: Optional[float]


def percent_change(observation: ObservationRow) -> Optional[float]:
    if not observation.previous_close:
        return None
    return (observation.price - observation.previous_close) / observation.previous_close * 100


def rank_by_movement(observations: dict[str, ObservationRow]) -> list[TrendingEntry]:
    """Biggest movers first, by absolute percent change, regardless of
    direction — a gap up and a gap down are equally "trending". A symbol
    with no `previous_close` (can't compute a change yet) sorts last, not
    excluded — it still belongs on the dashboard."""
    entries = [
        TrendingEntry(symbol=symbol, price=obs.price, percent_change=percent_change(obs), volume=obs.volume)
        for symbol, obs in observations.items()
    ]
    entries.sort(key=lambda e: abs(e.percent_change) if e.percent_change is not None else -1, reverse=True)
    return entries
