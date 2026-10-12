"""organization-wide agent settings (admin-managed)

Revision ID: e7a3c1d9b256
Revises: d6e0a4b8f315
Create Date: 2026-10-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e7a3c1d9b256'
down_revision: Union[str, Sequence[str], None] = 'd6e0a4b8f315'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
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


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('organizationagentsettings', schema='call')
