"""organization balance: minutes_only flag (no billing section for per-minute clients)

Revision ID: d3b7f19c4a60
Revises: c9a1e5d7f342
Create Date: 2026-10-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd3b7f19c4a60'
down_revision: Union[str, Sequence[str], None] = 'c9a1e5d7f342'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'organizationbalance',
        sa.Column('minutes_only', sa.Boolean(), server_default=sa.false(), nullable=False),
        schema='call',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('organizationbalance', 'minutes_only', schema='call')
