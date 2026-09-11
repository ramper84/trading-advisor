"""Axis 2 write side for instruments (ADR-007). Upsert on `symbol`, unlike
the time-series stores below — a reference row has one current truth, not
a history to accumulate.
"""

from __future__ import annotations

import psycopg

from app.ingest.parsers.instrument_parser import InstrumentRecord
from app.services.db import get_connection

_UPSERT_SQL = """
    INSERT INTO instruments (
        symbol, name, exchange, currency, quote_type, sector, industry,
        country, source_name, reliability_tier
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (symbol) DO UPDATE SET
        name = EXCLUDED.name,
        exchange = EXCLUDED.exchange,
        currency = EXCLUDED.currency,
        quote_type = EXCLUDED.quote_type,
        sector = EXCLUDED.sector,
        industry = EXCLUDED.industry,
        country = EXCLUDED.country,
        source_name = EXCLUDED.source_name,
        reliability_tier = EXCLUDED.reliability_tier,
        refreshed_at = now()
"""


def upsert_instrument(record: InstrumentRecord, conn: psycopg.Connection | None = None) -> None:
    def _write(c: psycopg.Connection) -> None:
        with c.transaction(), c.cursor() as cur:
            cur.execute(
                _UPSERT_SQL,
                (
                    record.symbol,
                    record.name,
                    record.exchange,
                    record.currency,
                    record.quote_type,
                    record.sector,
                    record.industry,
                    record.country,
                    record.source_name,
                    record.reliability_tier,
                ),
            )

    if conn is not None:
        _write(conn)
    else:
        with get_connection() as owned_conn:
            _write(owned_conn)
