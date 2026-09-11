"""create analyst_ratings

Rating-change events (ADR-007) — an append-only log, not a snapshot.
UNIQUE(symbol, rated_at, firm) makes re-ingestion idempotent: the same
firm's same rating action re-fetched on a later poll is a no-op, not a
duplicate row.

Revision ID: 530cc3c5b181
Revises: 2381e3c73952
Create Date: 2026-09-10 18:45:30.963056

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '530cc3c5b181'
down_revision: Union[str, None] = '2381e3c73952'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analyst_ratings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("rated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("firm", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("from_grade", sa.Text(), nullable=True),
        sa.Column("to_grade", sa.Text(), nullable=True),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("reliability_tier", sa.SmallInteger(), nullable=False),
        sa.UniqueConstraint("symbol", "rated_at", "firm", name="uq_analyst_ratings_symbol_date_firm"),
    )
    op.create_index(
        "ix_analyst_ratings_symbol_date",
        "analyst_ratings",
        ["symbol", sa.text("rated_at DESC")],
    )


def downgrade() -> None:
    op.drop_table("analyst_ratings")
