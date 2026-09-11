"""create daily_bars

Adjusted-close daily OHLCV — the chart backbone (ADR-007), a different
grain from market_observations's intraday ticks (articles/s10-05).
UNIQUE(symbol, bar_date) makes re-ingestion idempotent — the same day's
bar re-fetched tomorrow upserts in place rather than duplicating.

Revision ID: cb772fef5e44
Revises: c91904815fd7
Create Date: 2026-09-10 18:45:30.329776

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'cb772fef5e44'
down_revision: Union[str, None] = 'c91904815fd7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_bars",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("bar_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(), nullable=False),
        sa.Column("high", sa.Numeric(), nullable=False),
        sa.Column("low", sa.Numeric(), nullable=False),
        sa.Column("close", sa.Numeric(), nullable=False),
        sa.Column("volume", sa.Numeric(), nullable=True),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("reliability_tier", sa.SmallInteger(), nullable=False),
        sa.UniqueConstraint("symbol", "bar_date", name="uq_daily_bars_symbol_date"),
    )
    op.create_index(
        "ix_daily_bars_symbol_date",
        "daily_bars",
        ["symbol", sa.text("bar_date DESC")],
    )


def downgrade() -> None:
    op.drop_table("daily_bars")
