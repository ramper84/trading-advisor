"""Axis 3 orchestrator — CLAUDE.md Phase 10's stated order
(`articles/s10-06`'s "cheap and excluding first, expensive and fine last,
soft at the close"):

  (a) hard filter by symbol in the SQL WHERE, before any vector math
  (b) semantic (pgvector) + lexical (tsvector/GIN) run, fused by RRF —
      positions only, never raw scores (`s10-03`)
  (c) temporal.py's per-source-family weighting, applied last, over the
      fused survivors only
  (d) a distance-threshold soft-fail returns low_confidence rather than
      forcing an answer (`s09-03`)

Query expansion/decomposition and reranking are explicitly not built here
— see CLAUDE.md §2's ADR and Phase 16.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import psycopg

from app.config import get_settings
from app.ingest.embedding import embed_texts
from app.retrieval.hybrid_search import ChunkCandidate, lexical_search, reciprocal_rank_fusion
from app.retrieval.temporal import apply_temporal_weighting
from app.services.db import get_connection


@dataclass
class RetrievalResult:
    low_confidence: bool
    candidates: list[ChunkCandidate] = field(default_factory=list)
    scores: dict[int, float] = field(default_factory=dict)
    best_distance: Optional[float] = None
    # 1-indexed rank in the RRF-fused list, captured BEFORE temporal
    # weighting re-sorts it (Phase 12, ADR-010). `scores` is already
    # fused-then-temporally-weighted — using its resulting order as a
    # "fusion rank" signal would double-count temporal effects into what
    # Phase 12's weighting formula treats as an independent input.
    fused_rank: dict[int, int] = field(default_factory=dict)


def semantic_search(
    symbol: str, query_embedding: list[float], top_k: int, conn: Optional[psycopg.Connection] = None
) -> list[tuple[ChunkCandidate, float]]:
    """Hard filter by symbol first, then order by cosine distance
    (pgvector's `<=>` operator). Returns (candidate, distance) pairs —
    smaller distance is more similar."""
    # Explicit ::vector cast: unlike an INSERT into a Vector-typed column,
    # a bare query parameter compared via <=> has no column context for
    # psycopg/pgvector to infer the target type from — passing a plain
    # Python list here raises "operator does not exist: vector <=> double
    # precision[]" (2026-09-10, live verification).
    sql = (
        "SELECT id, source_name, symbol, document_id, reliability_tier, content, "
        "published_at, url, section_title, metadata, embedding <=> %s::vector AS distance "
        "FROM document_chunks "
        "WHERE symbol = %s "
        "ORDER BY embedding <=> %s::vector "
        "LIMIT %s"
    )
    params = (query_embedding, symbol, query_embedding, top_k)
    if conn is not None:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    else:
        with get_connection() as owned_conn, owned_conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [(ChunkCandidate(*row[:-1]), row[-1]) for row in rows]


def retrieve(
    symbol: str,
    query: str,
    conn: Optional[psycopg.Connection] = None,
    now: Optional[datetime] = None,
) -> RetrievalResult:
    settings = get_settings()
    top_k = settings.vector_top_k

    query_embedding = embed_texts([query])[0]
    semantic_hits = semantic_search(symbol, query_embedding, top_k, conn=conn)

    distances_by_id = {candidate.chunk_id: distance for candidate, distance in semantic_hits}
    best_distance = min(distances_by_id.values()) if distances_by_id else None

    ranked_lists = [[candidate for candidate, _ in semantic_hits]]
    if settings.hybrid_search_enabled:
        lexical_hits = lexical_search(symbol, query, top_k, conn=conn)
        ranked_lists.append(lexical_hits)

    fused = reciprocal_rank_fusion(ranked_lists)
    fused_rank = {candidate.chunk_id: rank for rank, (candidate, _) in enumerate(fused, start=1)}
    weighted = apply_temporal_weighting(fused, settings.temporal_half_life_days_news, now=now)

    # Soft-fail (s09-03): nothing clears the distance threshold means
    # "don't force an answer," not "return nothing was retrieved at all" —
    # the caller decides how to represent low_confidence, this layer just
    # flags it.
    low_confidence = best_distance is None or best_distance > settings.vector_distance_threshold

    return RetrievalResult(
        low_confidence=low_confidence,
        candidates=[candidate for candidate, _ in weighted],
        scores={candidate.chunk_id: score for candidate, score in weighted},
        best_distance=best_distance,
        fused_rank=fused_rank,
    )
