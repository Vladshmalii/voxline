"""link outbound SMS to the call that triggered it

Revision ID: c3a9f6e2b715
Revises: b5c8d2e1a904
Create Date: 2026-09-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3a9f6e2b715'
down_revision: Union[str, Sequence[str], None] = 'b5c8d2e1a904'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'message', sa.Column('call_id', sa.BigInteger(), nullable=True), schema='call'
    )
    op.create_index('ix_message_call_id', 'message', ['call_id'], unique=False, schema='call')
    op.create_foreign_key(
        'message_call_id_fkey',
        'message',
        'call',
        ['call_id'],
        ['id'],
        source_schema='call',
        referent_schema='call',
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('message_call_id_fkey', 'message', schema='call', type_='foreignkey')
    op.drop_index('ix_message_call_id', table_name='message', schema='call')
    op.drop_column('message', 'call_id', schema='call')
