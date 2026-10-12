"""let an agent name the SMS route its send_sms tool uses

Revision ID: e4b1c78d3a25
Revises: c3a9f6e2b715
Create Date: 2026-09-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e4b1c78d3a25'
down_revision: Union[str, Sequence[str], None] = 'c3a9f6e2b715'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable, and no backfill: NULL keeps the behaviour every existing agent
    # already has — the organization's single active route.
    op.add_column(
        'voiceagent',
        sa.Column('messaging_id', sa.BigInteger(), nullable=True),
        schema='call',
    )
    op.create_foreign_key(
        'voiceagent_messaging_id_fkey',
        'voiceagent',
        'messaging',
        ['messaging_id'],
        ['id'],
        source_schema='call',
        referent_schema='call',
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'voiceagent_messaging_id_fkey', 'voiceagent', schema='call', type_='foreignkey'
    )
    op.drop_column('voiceagent', 'messaging_id', schema='call')
