"""Axis 2 write side for `analyses` and `monitored_symbols` (Phase 18,
ADR-012). The last write path Phases 10-13 deliberately deferred — their
pipeline was pure, independently-tested modules with nothing persisting
a `GuardedAnalysis` until a UI actually needed to show history. `Citation`
survives as JSONB since it's already a small, self-contained shape (Axis
3's `s08-04` schema-split rule: typed columns for what's queried by,
JSONB for what's only ever read back whole).
"""

from __future__ import annotations

import json
from typing import Optional

import psycopg

from app.schemas import AnalysisSynthesis, GuardedAnalysis
from app.services.db import get_connection

_INSERT_ANALYSIS_SQL = """
    INSERT INTO analyses (
        symbol, query, stance, confidence, quality_status, rationale,
        citations, resolved_citations, dangling_citations,
        ungrounded_figures, reliability_rule_passed
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id
"""


def insert_analysis(
    symbol: str,
    query: str,
    synthesis: AnalysisSynthesis,
    guarded: GuardedAnalysis,
    conn: Optional[psycopg.Connection] = None,
) -> int:
    """Persists the GUARDED result (`stance`/`confidence`/`quality_status`
    are the code-derived, gate-enforced values — never the model's own
    self-reported ones) alongside the original citations, for a symbol's
    history to show exactly what was cited, not just the final verdict."""
    citations = json.dumps([{"chunk_id": c.chunk_id, "claim": c.claim} for c in synthesis.citations])
    params = (
        symbol,
        query,
        guarded.stance,
        guarded.confidence,
        guarded.quality_status,
        guarded.rationale,
        citations,
        json.dumps(guarded.resolved_citations),
        json.dumps(guarded.dangling_citations),
        json.dumps(guarded.ungrounded_figures),
        guarded.reliability_rule_passed,
    )
    if conn is not None:
        with conn.cursor() as cur:
            cur.execute(_INSERT_ANALYSIS_SQL, params)
            return cur.fetchone()[0]
    with get_connection() as owned_conn, owned_conn.cursor() as cur:
        cur.execute(_INSERT_ANALYSIS_SQL, params)
        owned_conn.commit()
        return cur.fetchone()[0]


_ADD_TO_MONITOR_SQL = """
    INSERT INTO monitored_symbols (symbol, active, thesis)
    VALUES (%s, true, %s)
    ON CONFLICT (symbol) DO UPDATE SET
        active = true,
        thesis = COALESCE(EXCLUDED.thesis, monitored_symbols.thesis)
"""


def add_to_monitor(symbol: str, thesis: Optional[str] = None, conn: Optional[psycopg.Connection] = None) -> None:
    """Re-adding an already-watched symbol keeps its existing thesis
    unless a new one is given — an empty re-add must not silently erase
    the personal note that's the whole point of the field (ADR-007)."""
    if conn is not None:
        with conn.cursor() as cur:
            cur.execute(_ADD_TO_MONITOR_SQL, (symbol, thesis))
        return
    with get_connection() as owned_conn, owned_conn.cursor() as cur:
        cur.execute(_ADD_TO_MONITOR_SQL, (symbol, thesis))
        owned_conn.commit()


def remove_from_monitor(symbol: str, conn: Optional[psycopg.Connection] = None) -> None:
    """Soft-delete only (`active = false`) — history stays queryable for
    a symbol that's no longer watched, matching the table's own design
    intent (`monitored_symbols`'s migration docstring)."""
    sql = "UPDATE monitored_symbols SET active = false WHERE symbol = %s"
    if conn is not None:
        with conn.cursor() as cur:
            cur.execute(sql, (symbol,))
        return
    with get_connection() as owned_conn, owned_conn.cursor() as cur:
        cur.execute(sql, (symbol,))
        owned_conn.commit()
