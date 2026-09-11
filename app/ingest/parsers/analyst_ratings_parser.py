"""Analyst rating-change events (ADR-007) — upgrade/downgrade + firm, via
yfinance's Ticker.upgrades_downgrades. Structured event data, Axis 2 — a
rating change is a fact with a firm and a date, not paraphrastic content.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd

from app.ingest.catalog import CatalogSource


@dataclass
class AnalystRatingRecord:
    symbol: str
    rated_at: datetime
    firm: str
    action: str  # e.g. "up", "down", "main", "init" — yfinance's own Action values
    from_grade: Optional[str]
    to_grade: Optional[str]
    source_name: str
    reliability_tier: int


def parse_analyst_ratings(
    symbol: str, ratings: Optional[pd.DataFrame], catalog_source: CatalogSource
) -> list[AnalystRatingRecord]:
    """ratings is yfinance's own Ticker.upgrades_downgrades DataFrame,
    indexed by GradeDate — or None, which yfinance returns (not an empty
    DataFrame) for a symbol with no rating history."""
    if ratings is None or ratings.empty:
        return []
    records = []
    for graded_at, row in ratings.iterrows():
        records.append(
            AnalystRatingRecord(
                symbol=symbol,
                rated_at=graded_at.to_pydatetime(),
                firm=row["Firm"],
                action=row["Action"],
                from_grade=row.get("FromGrade") or None,
                to_grade=row.get("ToGrade") or None,
                source_name=catalog_source.name,
                reliability_tier=catalog_source.reliability_tier,
            )
        )
    return records
