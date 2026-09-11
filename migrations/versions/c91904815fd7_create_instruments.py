"""create instruments

Reference/dimension table (ADR-007) — static facts about a symbol, not a
time series. symbol is the primary key: refresh_worker upserts this once
per symbol on monitor-add, never on the quote-polling cadence.

Revision ID: c91904815fd7
Revises: cc00ade99dc9
Create Date: 2026-09-10 18:45:30.039236

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c91904815fd7'
down_revision: Union[str, None] = 'cc00ade99dc9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("symbol", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("exchange", sa.Text(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("quote_type", sa.Text(), nullable=True),
        sa.Column("sector", sa.Text(), nullable=True),
        sa.Column("industry", sa.Text(), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("reliability_tier", sa.SmallInteger(), nullable=False),
        sa.Column(
            "refreshed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("instruments")
