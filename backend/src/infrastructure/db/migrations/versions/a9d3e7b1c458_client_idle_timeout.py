"""per-client idle timeout

Revision ID: a9d3e7b1c458
Revises: 5b9e1c3a7d42
Create Date: 2026-10-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a9d3e7b1c458'
down_revision: Union[str, Sequence[str], None] = '5b9e1c3a7d42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'client',
        sa.Column('idle_timeout_seconds', sa.Integer(), nullable=True),
        schema='call',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('client', 'idle_timeout_seconds', schema='call')
