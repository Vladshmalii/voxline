"""billing: organization balance and balance transactions

NOTE: this revision file was missing from the repository copy and has been
reconstructed from its neighbours (``c3a9f6e2b715`` revises it,
``6dcb902f4a31`` / ``d3b7f19c4a60`` alter its tables) and the current models.
Replace it with the original revision file if one is available.

Revision ID: b5c8d2e1a904
Revises: 8a390f62760d
Create Date: 2026-09-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b5c8d2e1a904'
down_revision: Union[str, Sequence[str], None] = '8a390f62760d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'organizationbalance',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('currency', sa.String(length=10), server_default='USD', nullable=False),
        sa.Column('balance', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('cost_per_minute', sa.Float(), server_default='0.10', nullable=False),
        sa.Column('cost_per_sms', sa.Float(), server_default='0.02', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='call',
    )
    op.create_table(
        'balancetransaction',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('uuid', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('type', sa.String(length=32), nullable=False),
        sa.Column('description', sa.Text(), server_default='', nullable=False),
        sa.Column('call_id', sa.BigInteger(), nullable=True),
        sa.Column('sms_id', sa.BigInteger(), nullable=True),
        sa.Column('admin_id', sa.BigInteger(), nullable=True),
        sa.Column('balance_after', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['call_id'], ['call.call.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['sms_id'], ['call.message.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        schema='call',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('balancetransaction', schema='call')
    op.drop_table('organizationbalance', schema='call')
