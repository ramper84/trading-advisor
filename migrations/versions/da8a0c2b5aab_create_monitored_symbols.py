"""create monitored_symbols

The watchlist driving refresh_worker's per-symbol polling loop and the
future trending/dashboard reads. `thesis` (ADR-007) is a personal one-line
note on why a symbol is being watched — an annotation, not a position;
this project tracks no cost basis, quantity, or P&L (ADR-001).
`active` is a soft-delete flag so history stays queryable after a symbol
is removed from the watchlist.

Revision ID: da8a0c2b5aab
Revises: bf61cb1d2a89
Create Date: 2026-09-10 18:45:31.633342

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'da8a0c2b5aab'
down_revision: Union[str, None] = 'bf61cb1d2a89'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monitored_symbols",
        sa.Column("symbol", sa.Text(), primary_key=True),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("thesis", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("monitored_symbols")
