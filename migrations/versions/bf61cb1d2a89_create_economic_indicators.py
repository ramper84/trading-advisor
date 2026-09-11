"""create economic_indicators

Official macro/economic series (Banxico SIE, FRED — ADR-006), economy-wide
rather than symbol-keyed (articles/s10-05's schema-divergence rule vs.
market_observations). UNIQUE(series_id, observed_on) makes re-ingestion
idempotent.

Revision ID: bf61cb1d2a89
Revises: 530cc3c5b181
Create Date: 2026-09-10 18:45:31.262217

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'bf61cb1d2a89'
down_revision: Union[str, None] = '530cc3c5b181'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "economic_indicators",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("series_id", sa.Text(), nullable=False),
        sa.Column("series_name", sa.Text(), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("country", sa.Text(), nullable=False),
        sa.UniqueConstraint("series_id", "observed_on", name="uq_economic_indicators_series_date"),
    )
    op.create_index(
        "ix_economic_indicators_series_date",
        "economic_indicators",
        ["series_id", sa.text("observed_on DESC")],
    )


def downgrade() -> None:
    op.drop_table("economic_indicators")
