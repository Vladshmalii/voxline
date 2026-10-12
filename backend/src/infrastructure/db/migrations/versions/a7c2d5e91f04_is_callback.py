"""retry & callback: distinguish a named-time callback from a plain retry

Revision ID: a7c2d5e91f04
Revises: f4b6a1c9e832
Create Date: 2026-09-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a7c2d5e91f04'
down_revision: Union[str, Sequence[str], None] = 'f4b6a1c9e832'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'call',
        sa.Column('is_callback', sa.Boolean(), server_default='false', nullable=False),
        schema='call',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('call', 'is_callback', schema='call')
