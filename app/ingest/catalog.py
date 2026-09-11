"""Typed loader for data_catalog.yaml (articles/s06-02). Every source the
ingest pipeline touches is declared there, not hardcoded here — toggling a
source on/off is a YAML edit, never a code change.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel

DEFAULT_CATALOG_PATH = Path("data_catalog.yaml")


class Axis(str, Enum):
    SQL_RETRIEVAL = "sql_retrieval"
    VECTOR_RAG = "vector_rag"


class IngestionDecision(str, Enum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    REVIEW = "review"


class Volume(BaseModel):
    records: str
    size_mb: str


class Refresh(BaseModel):
    declared: str
    interval_seconds: int  # machine-readable cadence refresh_worker.py schedules against
    observed_last_update: str
    observed_lag_days: int


class Quality(BaseModel):
    completeness: int
    consistency: int
    actuality: int
    reliability: int

    @property
    def is_rag_ready(self) -> bool:
        """No dimension may drop below ACCEPTABLE=3 — dimensions do not
        average (articles/s06-02). reddit_mentions fails this by design;
        see its catalog entry's own notes for why it's included anyway,
        and ARCHITECTURE.md §1 for the guardrail rule that follows from it.
        """
        return all(
            v >= 3
            for v in (self.completeness, self.consistency, self.actuality, self.reliability)
        )


class Sensitivity(BaseModel):
    contains_pii: bool


class Lineage(BaseModel):
    upstream: str
    transformations: list[str] = []


class CatalogSource(BaseModel):
    name: str
    description: str
    location: str
    owner_technical: str
    owner_business: str
    format: str
    axis: Axis
    volume: Volume
    refresh: Refresh
    quality: Quality
    sensitivity: Sensitivity
    lineage: Lineage
    decision: IngestionDecision
    notes: str | None = None

    @property
    def reliability_tier(self) -> int:
        """Copied onto every observation/chunk this source produces at
        ingest time (ARCHITECTURE.md §6) — never recomputed at query time,
        so a later re-scoring of the catalog doesn't silently reclassify
        history that already shipped in a persisted analysis."""
        return self.quality.reliability


class DataCatalog(BaseModel):
    version: int
    last_audited: str
    sources: list[CatalogSource]

    def included_sources(self) -> list[CatalogSource]:
        return [s for s in self.sources if s.decision == IngestionDecision.INCLUDE]

    def by_axis(self, axis: Axis) -> list[CatalogSource]:
        return [s for s in self.included_sources() if s.axis == axis]

    def get(self, name: str) -> CatalogSource:
        for source in self.sources:
            if source.name == name:
                return source
        raise KeyError(f"No catalog source named {name!r}")


def load_catalog(path: Path = DEFAULT_CATALOG_PATH) -> DataCatalog:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return DataCatalog(**raw)
