"""spoken phrase repeated while the caller has picked up but never answered

Revision ID: d4e19a7c0f2b
Revises: c3a9f6e2b715
Create Date: 2026-09-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4e19a7c0f2b'
down_revision: Union[str, Sequence[str], None] = 'c3a9f6e2b715'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'voiceagent',
        sa.Column('spoken_no_answer', sa.Text(), nullable=False, server_default=''),
        schema='call',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('voiceagent', 'spoken_no_answer', schema='call')
