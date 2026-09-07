"""Shared Postgres connection helper. Registers the pgvector adapter once
per connection so Python lists round-trip as `vector` columns
transparently — every module that reads or writes document_chunks goes
through this, not through a fresh ad-hoc psycopg.connect().
"""

from __future__ import annotations

import psycopg
from pgvector.psycopg import register_vector

from app.config import get_settings


def get_connection() -> psycopg.Connection:
    settings = get_settings()
    # Alembic/SQLAlchemy want the "+psycopg" dialect suffix; psycopg3's own
    # connect() does not understand it.
    dsn = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    conn = psycopg.connect(dsn)
    register_vector(conn)
    return conn
