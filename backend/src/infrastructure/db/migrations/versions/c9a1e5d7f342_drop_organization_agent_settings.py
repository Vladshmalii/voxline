"""drop organization-wide agent settings: tuning stays per agent

Revision ID: c9a1e5d7f342
Revises: a0c4e8f2b137
Create Date: 2026-10-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c9a1e5d7f342'
down_revision: Union[str, Sequence[str], None] = 'a0c4e8f2b137'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute('DROP TABLE IF EXISTS call.organizationagentsettings')


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        'organizationagentsettings',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('idle_timeout_seconds', sa.Integer(), server_default='300', nullable=False),
        sa.Column('max_duration_seconds', sa.Integer(), nullable=True),
        sa.Column('telephony_id', sa.BigInteger(), nullable=True),
        sa.Column('tts_sample_rate', sa.Integer(), server_default='24000', nullable=False),
        sa.ForeignKeyConstraint(['telephony_id'], ['call.telephony.id'], ondelete='SET NULL'),
        schema='call',
    )
