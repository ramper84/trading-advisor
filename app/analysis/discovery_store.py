"""Axis 2 write side for `suggestions` (Discovery, CLAUDE.md's "Extension
— Discovery"). Append-only — no dismissed/status tracking for v1, not
asked for; the read side (`sql_retriever.get_latest_suggestions`) is the
whole read contract.
"""

from __future__ import annotations

import json
from typing import Optional

import psycopg

from app.schemas import SuggestedCompany
from app.services.db import get_connection

_INSERT_SQL = """
    INSERT INTO suggestions (symbol, company_name, reasoning, source_article_ids)
    VALUES (%s, %s, %s, %s)
"""


def insert_suggestions(suggestions: list[SuggestedCompany], conn: Optional[psycopg.Connection] = None) -> int:
    if not suggestions:
        return 0

    def _write(c: psycopg.Connection) -> int:
        with c.transaction(), c.cursor() as cur:
            for suggestion in suggestions:
                cur.execute(
                    _INSERT_SQL,
                    (
                        suggestion.symbol,
                        suggestion.company_name,
                        suggestion.reasoning,
                        json.dumps(suggestion.source_article_ids),
                    ),
                )
        return len(suggestions)

    if conn is not None:
        return _write(conn)
    with get_connection() as owned_conn:
        return _write(owned_conn)
