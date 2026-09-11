"""create fundamentals

Valuation ratios and reported financials merged into one snapshot table
(ADR-007, articles/s10-05: both are "a company's financial snapshot as of
a date," not divergent enough to split into two tables).
UNIQUE(symbol, snapshot_date) makes re-ingestion idempotent.

Revision ID: 2381e3c73952
Revises: cb772fef5e44
Create Date: 2026-09-10 18:45:30.636900

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2381e3c73952'
down_revision: Union[str, None] = 'cb772fef5e44'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fundamentals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("pe_ratio", sa.Numeric(), nullable=True),
        sa.Column("pb_ratio", sa.Numeric(), nullable=True),
        sa.Column("ev_ebitda", sa.Numeric(), nullable=True),
        sa.Column("dividend_yield", sa.Numeric(), nullable=True),
        sa.Column("fcf_yield", sa.Numeric(), nullable=True),
        sa.Column("market_cap", sa.Numeric(), nullable=True),
        sa.Column("revenue", sa.Numeric(), nullable=True),
        sa.Column("net_income", sa.Numeric(), nullable=True),
        sa.Column("eps", sa.Numeric(), nullable=True),
        sa.Column("gross_margin", sa.Numeric(), nullable=True),
        sa.Column("operating_margin", sa.Numeric(), nullable=True),
        sa.Column("debt_to_equity", sa.Numeric(), nullable=True),
        sa.Column("roe", sa.Numeric(), nullable=True),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("reliability_tier", sa.SmallInteger(), nullable=False),
        sa.UniqueConstraint("symbol", "snapshot_date", name="uq_fundamentals_symbol_date"),
    )
    op.create_index(
        "ix_fundamentals_symbol_date",
        "fundamentals",
        ["symbol", sa.text("snapshot_date DESC")],
    )


def downgrade() -> None:
    op.drop_table("fundamentals")
