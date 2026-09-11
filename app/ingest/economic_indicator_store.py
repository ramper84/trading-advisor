"""Axis 2 write side for economic_indicators (ADR-006). Upsert on
(series_id, observed_on) — official statistics agencies revise past
observations (Banxico and FRED both do), so a later poll's revised value
should replace the earlier one, not sit beside it as a duplicate.
"""

from __future__ import annotations

import psycopg

from app.ingest.parsers.economic_data_parser import RawEconomicObservation
from app.services.db import get_connection

_UPSERT_SQL = """
    INSERT INTO economic_indicators (
        series_id, series_name, value, observed_on, source_name, country
    ) VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (series_id, observed_on) DO UPDATE SET
        value = EXCLUDED.value,
        series_name = EXCLUDED.series_name,
        source_name = EXCLUDED.source_name,
        country = EXCLUDED.country
"""


def _insert_all(conn: psycopg.Connection, records: list[RawEconomicObservation]) -> None:
    with conn.transaction(), conn.cursor() as cur:
        for record in records:
            cur.execute(
                _UPSERT_SQL,
                (
                    record.series_id,
                    record.series_name,
                    record.value,
                    record.observed_on,
                    record.source_name,
                    record.country,
                ),
            )


def upsert_economic_observations(
    records: list[RawEconomicObservation], conn: psycopg.Connection | None = None
) -> int:
    if not records:
        return 0
    if conn is not None:
        _insert_all(conn, records)
    else:
        with get_connection() as owned_conn:
            _insert_all(owned_conn, records)
    return len(records)
