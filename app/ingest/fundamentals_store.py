"""Axis 2 write side for fundamentals (ADR-007). Upsert on
(symbol, snapshot_date) — a revised figure for a period already ingested
replaces it rather than duplicating.
"""

from __future__ import annotations

import psycopg

from app.ingest.parsers.fundamentals_parser import FundamentalsRecord
from app.services.db import get_connection

_UPSERT_SQL = """
    INSERT INTO fundamentals (
        symbol, snapshot_date, pe_ratio, pb_ratio, ev_ebitda, dividend_yield,
        fcf_yield, market_cap, revenue, net_income, eps, gross_margin,
        operating_margin, debt_to_equity, roe, source_name, reliability_tier
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (symbol, snapshot_date) DO UPDATE SET
        pe_ratio = EXCLUDED.pe_ratio,
        pb_ratio = EXCLUDED.pb_ratio,
        ev_ebitda = EXCLUDED.ev_ebitda,
        dividend_yield = EXCLUDED.dividend_yield,
        fcf_yield = EXCLUDED.fcf_yield,
        market_cap = EXCLUDED.market_cap,
        revenue = EXCLUDED.revenue,
        net_income = EXCLUDED.net_income,
        eps = EXCLUDED.eps,
        gross_margin = EXCLUDED.gross_margin,
        operating_margin = EXCLUDED.operating_margin,
        debt_to_equity = EXCLUDED.debt_to_equity,
        roe = EXCLUDED.roe,
        source_name = EXCLUDED.source_name,
        reliability_tier = EXCLUDED.reliability_tier
"""


def upsert_fundamentals(record: FundamentalsRecord, conn: psycopg.Connection | None = None) -> None:
    def _write(c: psycopg.Connection) -> None:
        with c.transaction(), c.cursor() as cur:
            cur.execute(
                _UPSERT_SQL,
                (
                    record.symbol,
                    record.snapshot_date,
                    record.pe_ratio,
                    record.pb_ratio,
                    record.ev_ebitda,
                    record.dividend_yield,
                    record.fcf_yield,
                    record.market_cap,
                    record.revenue,
                    record.net_income,
                    record.eps,
                    record.gross_margin,
                    record.operating_margin,
                    record.debt_to_equity,
                    record.roe,
                    record.source_name,
                    record.reliability_tier,
                ),
            )

    if conn is not None:
        _write(conn)
    else:
        with get_connection() as owned_conn:
            _write(owned_conn)
