"""hard cap on total call length, independent of activity

Revision ID: f1c6b3a482de
Revises: d4e19a7c0f2b
Create Date: 2026-09-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f1c6b3a482de'
down_revision: Union[str, Sequence[str], None] = 'd4e19a7c0f2b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'voiceagent',
        sa.Column('max_duration_seconds', sa.Integer(), nullable=True),
        schema='call',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('voiceagent', 'max_duration_seconds', schema='call')
