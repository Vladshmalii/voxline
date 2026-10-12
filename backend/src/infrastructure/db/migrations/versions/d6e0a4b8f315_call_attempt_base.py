"""call.attempt_base: retry-budget origin after a campaign restart

Revision ID: d6e0a4b8f315
Revises: c5d9f3a7e204
Create Date: 2026-10-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd6e0a4b8f315'
down_revision: Union[str, Sequence[str], None] = 'c5d9f3a7e204'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'call',
        sa.Column('attempt_base', sa.Integer(), server_default='0', nullable=False),
        schema='call',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('call', 'attempt_base', schema='call')
