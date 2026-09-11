"""Axis 2 write side for market_observations. The read side (for
/trending, /symbols/{symbol}/status) is retrieval/sql_retriever.py, built
in Phase 10 — this module only writes, matching the offline/online split
(articles/s06-01).
"""

from __future__ import annotations

import psycopg
from psycopg.types.json import Json

from app.ingest.parsers.quotes_parser import MarketObservationRecord
from app.services.db import get_connection

_INSERT_SQL = """
    INSERT INTO market_observations (
        symbol, observed_at, price, bid, ask, volume, indicators, source_name, reliability_tier
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def _insert_all(conn: psycopg.Connection, records: list[MarketObservationRecord]) -> None:
    with conn.transaction(), conn.cursor() as cur:
        for record in records:
            cur.execute(
                _INSERT_SQL,
                (
                    record.symbol,
                    record.observed_at,
                    record.price,
                    record.bid,
                    record.ask,
                    record.volume,
                    Json(record.indicators),
                    record.source_name,
                    record.reliability_tier,
                ),
            )


def insert_observations(
    records: list[MarketObservationRecord], conn: psycopg.Connection | None = None
) -> int:
    """Every observation is an insert, never an upsert — unlike
    document_chunks, a market_observations row is a point-in-time reading,
    not a document with a stable identity to overwrite. History
    accumulates; nothing here is ever updated in place."""
    if not records:
        return 0
    if conn is not None:
        _insert_all(conn, records)
    else:
        with get_connection() as owned_conn:
            _insert_all(owned_conn, records)
    return len(records)
