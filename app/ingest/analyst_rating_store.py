"""Axis 2 write side for analyst_ratings (ADR-007). Insert with
ON CONFLICT DO NOTHING — a rating event, once recorded, doesn't get
revised the way a fundamentals snapshot might.
"""

from __future__ import annotations

import psycopg

from app.ingest.parsers.analyst_ratings_parser import AnalystRatingRecord
from app.services.db import get_connection

_INSERT_SQL = """
    INSERT INTO analyst_ratings (
        symbol, rated_at, firm, action, from_grade, to_grade, source_name, reliability_tier
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (symbol, rated_at, firm) DO NOTHING
"""


def _insert_all(conn: psycopg.Connection, records: list[AnalystRatingRecord]) -> None:
    with conn.transaction(), conn.cursor() as cur:
        for record in records:
            cur.execute(
                _INSERT_SQL,
                (
                    record.symbol,
                    record.rated_at,
                    record.firm,
                    record.action,
                    record.from_grade,
                    record.to_grade,
                    record.source_name,
                    record.reliability_tier,
                ),
            )


def insert_analyst_ratings(
    records: list[AnalystRatingRecord], conn: psycopg.Connection | None = None
) -> int:
    if not records:
        return 0
    if conn is not None:
        _insert_all(conn, records)
    else:
        with get_connection() as owned_conn:
            _insert_all(owned_conn, records)
    return len(records)
