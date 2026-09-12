"""create general_news_items

Discovery's own storage (CLAUDE.md's "Extension — Discovery", 2026-09-12):
Axis 2 (plain SQL), not Axis 3 — there is no user query to semantically
retrieve these against, only a time-windowed "recent" read, so this is
NOT document_chunks with a nullable symbol. `url` is a real, stable
natural key here (unlike document_chunks's synthetic document_id, needed
only because one filing splits into several chunks).

Revision ID: 7f23c8dc2614
Revises: b2150f7605e6
Create Date: 2026-09-12 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7f23c8dc2614'
down_revision: Union[str, None] = 'b2150f7605e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "general_news_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("reliability_tier", sa.SmallInteger(), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("source_name", "url", name="uq_general_news_items_source_url"),
    )
    op.create_index("ix_general_news_items_published_at", "general_news_items", ["published_at"])


def downgrade() -> None:
    op.drop_table("general_news_items")
