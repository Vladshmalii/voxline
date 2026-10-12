"""messaging bindings and outbound SMS with delivery status

Revision ID: d1a73c05e6b8
Revises: c9f5e83d1a42
Create Date: 2026-09-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd1a73c05e6b8'
down_revision: Union[str, Sequence[str], None] = 'c9f5e83d1a42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MESSAGE_STATUSES = (
    'queued', 'sent', 'delivered', 'undelivered', 'failed', 'canceled',
)


def _status_enum(create_type: bool = False) -> postgresql.ENUM:
    return postgresql.ENUM(
        *_MESSAGE_STATUSES, name='messagestatusenum', schema='call', create_type=create_type
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('messaging',
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('adapter', sa.String(), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('account_id', sa.String(), nullable=True),
    sa.Column('auth_token', sa.String(), nullable=True),
    sa.Column('sender', sa.String(), nullable=True),
    sa.Column('sender_pool_id', sa.String(), nullable=True),
    sa.Column('control_url', sa.String(), nullable=True),
    sa.Column('capabilities', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('options', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='call'
    )

    _status_enum().create(op.get_bind(), checkfirst=True)
    op.create_table('message',
    sa.Column('messaging_id', sa.BigInteger(), nullable=False),
    sa.Column('to_number', sa.String(), nullable=False),
    sa.Column('sender', sa.String(), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('segments', sa.Integer(), server_default='1', nullable=False),
    sa.Column('status', _status_enum(), nullable=False),
    sa.Column('provider_ref', sa.String(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('sent_at', sa.DateTime(), nullable=True),
    sa.Column('settled_at', sa.DateTime(), nullable=True),
    sa.Column('uuid', sa.UUID(), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['messaging_id'], ['call.messaging.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    schema='call'
    )
    op.create_index('ix_message_status', 'message', ['status'], unique=False, schema='call')
    op.create_index('ix_message_to_number', 'message', ['to_number'], unique=False, schema='call')
    op.create_index(
        'ix_message_provider_ref', 'message', ['provider_ref'], unique=False, schema='call'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_message_provider_ref', table_name='message', schema='call')
    op.drop_index('ix_message_to_number', table_name='message', schema='call')
    op.drop_index('ix_message_status', table_name='message', schema='call')
    op.drop_table('message', schema='call')
    _status_enum().drop(op.get_bind(), checkfirst=True)
    op.drop_table('messaging', schema='call')
