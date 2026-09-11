"""Axis 2 write side for daily_bars (ADR-007). Upsert on (symbol, bar_date)
— a corrected/finalized bar for a date already ingested replaces it rather
than duplicating.
"""

from __future__ import annotations

import psycopg

from app.ingest.parsers.daily_bar_parser import DailyBarRecord
from app.services.db import get_connection

_UPSERT_SQL = """
    INSERT INTO daily_bars (
        symbol, bar_date, open, high, low, close, volume, source_name, reliability_tier
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (symbol, bar_date) DO UPDATE SET
        open = EXCLUDED.open,
        high = EXCLUDED.high,
        low = EXCLUDED.low,
        close = EXCLUDED.close,
        volume = EXCLUDED.volume,
        source_name = EXCLUDED.source_name,
        reliability_tier = EXCLUDED.reliability_tier
"""


def _insert_all(conn: psycopg.Connection, records: list[DailyBarRecord]) -> None:
    with conn.transaction(), conn.cursor() as cur:
        for record in records:
            cur.execute(
                _UPSERT_SQL,
                (
                    record.symbol,
                    record.bar_date,
                    record.open,
                    record.high,
                    record.low,
                    record.close,
                    record.volume,
                    record.source_name,
                    record.reliability_tier,
                ),
            )


def upsert_daily_bars(records: list[DailyBarRecord], conn: psycopg.Connection | None = None) -> int:
    if not records:
        return 0
    if conn is not None:
        _insert_all(conn, records)
    else:
        with get_connection() as owned_conn:
            _insert_all(owned_conn, records)
    return len(records)
