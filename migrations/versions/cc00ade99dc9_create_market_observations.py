"""create market_observations

Axis 2's structured quote-tick table (ARCHITECTURE.md §1, ADR-007). Built
with the full yfinance fast_info field set from day one — OHLC-today,
52-week hi/lo, SMA50/SMA200, market cap — since that data rides along free
on the same call already made for the price; no reason to ship a
tick-only table and widen it later.

Revision ID: cc00ade99dc9
Revises: 802e79b7320a
Create Date: 2026-09-10 18:45:29.788740

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'cc00ade99dc9'
down_revision: Union[str, None] = '802e79b7320a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_observations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Numeric(), nullable=False),
        sa.Column("previous_close", sa.Numeric(), nullable=True),
        sa.Column("bid", sa.Numeric(), nullable=True),
        sa.Column("ask", sa.Numeric(), nullable=True),
        sa.Column("volume", sa.Numeric(), nullable=True),
        sa.Column("open", sa.Numeric(), nullable=True),
        sa.Column("day_high", sa.Numeric(), nullable=True),
        sa.Column("day_low", sa.Numeric(), nullable=True),
        sa.Column("year_high", sa.Numeric(), nullable=True),
        sa.Column("year_low", sa.Numeric(), nullable=True),
        sa.Column("fifty_day_average", sa.Numeric(), nullable=True),
        sa.Column("two_hundred_day_average", sa.Numeric(), nullable=True),
        sa.Column("market_cap", sa.Numeric(), nullable=True),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("reliability_tier", sa.SmallInteger(), nullable=False),
    )
    op.create_index(
        "ix_market_observations_symbol_observed_at",
        "market_observations",
        ["symbol", sa.text("observed_at DESC")],
    )


def downgrade() -> None:
    op.drop_table("market_observations")
