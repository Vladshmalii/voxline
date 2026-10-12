"""audiences: reusable contact lists, added to campaigns

Revision ID: c1d84f7a930e
Revises: b3e6f0a2c817
Create Date: 2026-09-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c1d84f7a930e'
down_revision: Union[str, Sequence[str], None] = 'b3e6f0a2c817'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('audience',
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('uuid', sa.UUID(), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='call'
    )
    op.create_table('audiencemember',
    sa.Column('audience_id', sa.BigInteger(), nullable=False),
    sa.Column('client_id', sa.BigInteger(), nullable=False),
    sa.Column('language', sa.String(), nullable=True),
    sa.Column('bonuses', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('player_id', sa.String(), nullable=True),
    sa.Column('vip_status', sa.String(), nullable=True),
    sa.Column('last_deposit', sa.Float(), nullable=True),
    sa.Column('last_active', sa.DateTime(), nullable=True),
    sa.Column('country', sa.String(), nullable=True),
    sa.Column('timezone', sa.String(), nullable=True),
    sa.Column('attributes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('uuid', sa.UUID(), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['audience_id'], ['call.audience.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['client_id'], ['call.client.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('audience_id', 'client_id'),
    schema='call'
    )
    op.create_index(
        'ix_audiencemember_audience_id', 'audiencemember', ['audience_id'],
        unique=False, schema='call',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_audiencemember_audience_id', table_name='audiencemember', schema='call')
    op.drop_table('audiencemember', schema='call')
    op.drop_table('audience', schema='call')
