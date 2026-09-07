"""The canonical ingest contract (articles/s06-03): every unstructured
parser converges here before chunking (Phase 7) and embedding (Phase 8).
Structured sources (yfinance_quotes/finnhub_quotes) never produce a
Document — they go straight to a typed MarketObservationRecord, since
there's no text to chunk or embed for a price tick.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    """Three-tier metadata (articles/s06-03): catalog (source_name,
    reliability_tier — known before touching the document), parser
    (document_id, published_at, url, section_title — known after parsing),
    pipeline (ingested_at — known at processing time)."""

    source_name: str
    symbol: str
    reliability_tier: int
    ingested_at: datetime

    document_id: str
    published_at: Optional[datetime] = None
    url: Optional[str] = None
    section_title: Optional[str] = None
    extra: dict = Field(default_factory=dict)


class Document(BaseModel):
    content: str
    metadata: DocumentMetadata
