"""Lexical search branch (`content_tsv`/GIN, built in Phase 8's migration)
plus Reciprocal Rank Fusion with the semantic branch (`articles/s10-03`).

RRF fuses by RANK POSITION, never raw score — cosine distance and
`ts_rank` live on different, non-comparable scales, so averaging them
directly would be meaningless. Each candidate's RRF score is
`sum(1 / (k + rank))` across every list it appears in (rank is 1-based);
missing from a list contributes nothing, not a zero-filled penalty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import psycopg

from app.services.db import get_connection

RRF_K = 60  # articles/s10-03's default constant


@dataclass
class ChunkCandidate:
    chunk_id: int
    source_name: str
    symbol: str
    document_id: str
    reliability_tier: int
    content: str
    published_at: Optional[datetime]
    url: Optional[str]
    section_title: Optional[str]
    metadata: dict = field(default_factory=dict)


def lexical_search(
    symbol: str, query: str, top_k: int, conn: Optional[psycopg.Connection] = None
) -> list[ChunkCandidate]:
    """Hard filter by symbol first (s10-06's "cheap and excluding first"),
    then rank the survivors by ts_rank against the already-materialized
    content_tsv column — no computation of the tsvector at query time."""
    sql = (
        "SELECT id, source_name, symbol, document_id, reliability_tier, content, "
        "published_at, url, section_title, metadata "
        "FROM document_chunks "
        "WHERE symbol = %s AND content_tsv @@ plainto_tsquery('english', %s) "
        "ORDER BY ts_rank(content_tsv, plainto_tsquery('english', %s)) DESC "
        "LIMIT %s"
    )
    params = (symbol, query, query, top_k)
    if conn is not None:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    else:
        with get_connection() as owned_conn, owned_conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [ChunkCandidate(*row) for row in rows]


def reciprocal_rank_fusion(
    ranked_lists: list[list[ChunkCandidate]], k: int = RRF_K
) -> list[tuple[ChunkCandidate, float]]:
    """Fuse any number of already-ranked candidate lists by position.
    Returns (candidate, fused_score) pairs sorted descending by score."""
    scores: dict[int, float] = {}
    candidates_by_id: dict[int, ChunkCandidate] = {}
    for ranked_list in ranked_lists:
        for rank, candidate in enumerate(ranked_list, start=1):
            scores[candidate.chunk_id] = scores.get(candidate.chunk_id, 0.0) + 1.0 / (k + rank)
            candidates_by_id.setdefault(candidate.chunk_id, candidate)

    fused = [(candidates_by_id[chunk_id], score) for chunk_id, score in scores.items()]
    fused.sort(key=lambda pair: pair[1], reverse=True)
    return fused
