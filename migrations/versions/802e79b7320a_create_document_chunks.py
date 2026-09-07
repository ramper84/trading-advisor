"""create document_chunks

Axis 3's vector store (ARCHITECTURE.md §1/ADR-004/ADR-005). One row per
chunk from any of sec_edgar_filings/finnhub_news/reddit_mentions — never
market_observations, which has no text to embed and gets its own table in
Phase 9.

embedding_version and source_hash exist from this first migration, not
added later (articles/s11-05's explicit warning: versioning is free
insurance now and a painful retrofit once a real embedding-model change
happens). content_tsv + its GIN index are created here too, since Phase
10's hybrid search (ADR-005) is adopted, not deferred, and the column is
schema — no reason to churn a second migration just to add it.

Revision ID: 802e79b7320a
Revises:
Create Date: 2026-09-06 18:32:47.925987

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '802e79b7320a'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIMENSIONS = 1536  # text-embedding-3-small


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("reliability_tier", sa.SmallInteger(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column("embedding_version", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("section_title", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("source_name", "document_id", name="uq_document_chunks_source_document"),
    )

    op.create_index("ix_document_chunks_symbol", "document_chunks", ["symbol"])
    op.create_index("ix_document_chunks_source_name", "document_chunks", ["source_name"])
    op.create_index("ix_document_chunks_embedding_version", "document_chunks", ["embedding_version"])

    # Lexical search branch (articles/s10-03) — generated column kept in
    # sync by Postgres itself, no application code or trigger needed.
    op.execute(
        "ALTER TABLE document_chunks "
        "ADD COLUMN content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED"
    )
    op.execute(
        "CREATE INDEX ix_document_chunks_content_tsv ON document_chunks USING gin (content_tsv)"
    )

    # No vector index (hnsw) yet — sequential scan is Axis 3's stated
    # default until a measured latency number justifies one (ARCHITECTURE.md §8).


def downgrade() -> None:
    op.drop_table("document_chunks")
