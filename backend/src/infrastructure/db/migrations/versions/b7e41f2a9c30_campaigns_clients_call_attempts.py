"""campaigns, clients, call/callattempt split

The old ``call`` table (one row per leg) becomes ``callattempt``; ``call`` is
now the assignment row (client, campaign, pinned script inputs, scheduling
state). The table is dropped and recreated rather than renamed/altered — the
schema shipped pre-production with no data to carry.

Revision ID: b7e41f2a9c30
Revises: 2db99478baa3
Create Date: 2026-09-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import src.core.db.models

# revision identifiers, used by Alembic.
revision: str = 'b7e41f2a9c30'
down_revision: Union[str, Sequence[str], None] = '2db99478baa3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_enum(*values: str, name: str) -> postgresql.ENUM:
    """A pg enum type that already exists in the schema — reference, don't create."""
    return postgresql.ENUM(*values, name=name, schema='call', create_type=False)


_DIRECTION = ('inbound', 'outbound')
_ATTEMPT_STATUS = (
    'queued', 'dialing', 'in_progress', 'completed', 'busy', 'no_answer', 'failed', 'canceled'
)


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index('ix_call_status', table_name='call', schema='call')
    op.drop_index('ix_call_agent_id', table_name='call', schema='call')
    op.drop_table('call', schema='call')

    op.drop_column('voiceagent', 'call_script', schema='call')

    op.create_table('client',
    sa.Column('phone', sa.String(), nullable=False),
    sa.Column('name', sa.String(), server_default='', nullable=False),
    sa.Column('status', src.core.db.models.Enum('active', 'do_not_call', 'blocked', name='clientstatusenum', schema='call'), nullable=False),
    sa.Column('uuid', sa.UUID(), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('phone'),
    schema='call'
    )
    op.create_table('campaign',
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('status', src.core.db.models.Enum('draft', 'scheduled', 'running', 'paused', 'completed', name='campaignstatusenum', schema='call'), nullable=False),
    sa.Column('agent_id', sa.BigInteger(), nullable=False),
    sa.Column('call_script', sa.Text(), server_default='', nullable=False),
    sa.Column('starts_at', sa.DateTime(), nullable=True),
    sa.Column('ends_at', sa.DateTime(), nullable=True),
    sa.Column('calling_hours', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('retry', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('uuid', sa.UUID(), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['call.voiceagent.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    schema='call'
    )
    op.create_table('call',
    sa.Column('client_id', sa.BigInteger(), nullable=True),
    sa.Column('campaign_id', sa.BigInteger(), nullable=True),
    sa.Column('agent_id', sa.BigInteger(), nullable=True),
    sa.Column('direction', _existing_enum(*_DIRECTION, name='calldirectionenum'), nullable=False),
    sa.Column('status', src.core.db.models.Enum('pending', 'calling', 'completed', 'exhausted', 'canceled', 'blocked', name='calllifecycleenum', schema='call'), nullable=False),
    sa.Column('from_number', sa.String(), nullable=True),
    sa.Column('language', sa.String(), nullable=True),
    sa.Column('bonuses', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('attributes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('overrides', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('attempts_made', sa.Integer(), server_default='0', nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(), nullable=True),
    sa.Column('uuid', sa.UUID(), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['call.voiceagent.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['campaign_id'], ['call.campaign.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['client_id'], ['call.client.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    schema='call'
    )
    op.create_index('ix_call_due', 'call', ['status', 'next_attempt_at'], unique=False, schema='call')
    op.create_index('ix_call_campaign_id', 'call', ['campaign_id'], unique=False, schema='call')
    op.create_index('ix_call_client_id', 'call', ['client_id'], unique=False, schema='call')

    op.create_table('callattempt',
    sa.Column('call_id', sa.BigInteger(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('status', _existing_enum(*_ATTEMPT_STATUS, name='callstatusenum'), nullable=False),
    sa.Column('language', sa.String(), nullable=True),
    sa.Column('provider_ref', sa.String(), nullable=True),
    sa.Column('profile_summary', sa.String(), nullable=True),
    sa.Column('messages', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('answered_at', sa.DateTime(), nullable=True),
    sa.Column('ended_at', sa.DateTime(), nullable=True),
    sa.Column('uuid', sa.UUID(), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['call_id'], ['call.call.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('call_id', 'seq'),
    schema='call'
    )
    op.create_index('ix_callattempt_status', 'callattempt', ['status'], unique=False, schema='call')
    op.create_index('ix_callattempt_call_id', 'callattempt', ['call_id'], unique=False, schema='call')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_callattempt_call_id', table_name='callattempt', schema='call')
    op.drop_index('ix_callattempt_status', table_name='callattempt', schema='call')
    op.drop_table('callattempt', schema='call')
    op.drop_index('ix_call_client_id', table_name='call', schema='call')
    op.drop_index('ix_call_campaign_id', table_name='call', schema='call')
    op.drop_index('ix_call_due', table_name='call', schema='call')
    op.drop_table('call', schema='call')
    op.drop_table('campaign', schema='call')
    op.drop_table('client', schema='call')
    for enum_name in ('calllifecycleenum', 'campaignstatusenum', 'clientstatusenum'):
        postgresql.ENUM(name=enum_name, schema='call').drop(op.get_bind(), checkfirst=True)

    op.add_column(
        'voiceagent',
        sa.Column('call_script', sa.Text(), server_default='', nullable=False),
        schema='call',
    )
    op.create_table('call',
    sa.Column('agent_id', sa.BigInteger(), nullable=True),
    sa.Column('direction', _existing_enum(*_DIRECTION, name='calldirectionenum'), nullable=False),
    sa.Column('status', _existing_enum(*_ATTEMPT_STATUS, name='callstatusenum'), nullable=False),
    sa.Column('to_number', sa.String(), nullable=False),
    sa.Column('from_number', sa.String(), nullable=True),
    sa.Column('language', sa.String(), nullable=True),
    sa.Column('provider_ref', sa.String(), nullable=True),
    sa.Column('customer', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('overrides', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('profile_summary', sa.String(), nullable=True),
    sa.Column('messages', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('answered_at', sa.DateTime(), nullable=True),
    sa.Column('ended_at', sa.DateTime(), nullable=True),
    sa.Column('uuid', sa.UUID(), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['call.voiceagent.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    schema='call'
    )
    op.create_index('ix_call_agent_id', 'call', ['agent_id'], unique=False, schema='call')
    op.create_index('ix_call_status', 'call', ['status'], unique=False, schema='call')
