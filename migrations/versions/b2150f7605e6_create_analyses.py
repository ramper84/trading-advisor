"""create analyses

The last Axis-2 table named in CLAUDE.md §2's ADR ("analyses — persisted
on-demand analyses") but never built through Phases 10-13: those phases
built the full retrieval -> augmentation -> synthesis -> generation ->
guardrail pipeline as pure, independently-tested modules and deliberately
left persistence for whenever a UI actually needed it (ADR-011's own
scoping note). Phase 18 (Reflex, ADR-012) is that UI.

One row per completed `guard_analysis()` call — the GuardedAnalysis output,
plus the citations list and the original query, so a symbol's detail page
can show its analysis history verbatim, not just the final stance.

Revision ID: b2150f7605e6
Revises: da8a0c2b5aab
Create Date: 2026-09-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b2150f7605e6'
down_revision: Union[str, None] = 'da8a0c2b5aab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analyses",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("stance", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("quality_status", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("citations", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("resolved_citations", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("dangling_citations", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("ungrounded_figures", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("reliability_rule_passed", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_analyses_symbol_requested_at", "analyses", ["symbol", "requested_at"])


def downgrade() -> None:
    op.drop_table("analyses")
