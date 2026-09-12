"""create suggestions

Discovery's persisted output (CLAUDE.md's "Extension — Discovery"):
append-only, like `analyses` — no `dismissed`/status tracking for v1, not
asked for. The UI reads the latest batch by `generated_at`.

Revision ID: 15c5d34d391e
Revises: 7f23c8dc2614
Create Date: 2026-09-12 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '15c5d34d391e'
down_revision: Union[str, None] = '7f23c8dc2614'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "suggestions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("company_name", sa.Text(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("source_article_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_suggestions_generated_at", "suggestions", ["generated_at"])


def downgrade() -> None:
    op.drop_table("suggestions")
