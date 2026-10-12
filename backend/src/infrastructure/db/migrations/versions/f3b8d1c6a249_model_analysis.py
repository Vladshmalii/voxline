"""organization-wide model for post-call analysis

Revision ID: f3b8d1c6a249
Revises: d2e6a8b4c157
Create Date: 2026-10-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f3b8d1c6a249'
down_revision: Union[str, Sequence[str], None] = 'd2e6a8b4c157'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # No backfill: with no row flagged, analysis keeps running on each call's
    # own LLM — the behaviour every organization already has.
    op.add_column(
        'model',
        sa.Column('is_analysis', sa.Boolean(), nullable=False, server_default='false'),
        schema='call',
    )
    op.create_index(
        'uq_model_analysis',
        'model',
        ['is_analysis'],
        unique=True,
        schema='call',
        postgresql_where=sa.text('is_analysis'),
    )
    op.create_check_constraint(
        'ck_model_analysis_active_ttt',
        'model',
        "NOT is_analysis OR (is_active AND kind = 'ttt')",
        schema='call',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'ck_model_analysis_active_ttt', 'model', schema='call', type_='check'
    )
    op.drop_index('uq_model_analysis', table_name='model', schema='call')
    op.drop_column('model', 'is_analysis', schema='call')
