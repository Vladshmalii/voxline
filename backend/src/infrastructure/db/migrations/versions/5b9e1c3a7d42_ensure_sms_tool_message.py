"""ensure sms_tool_message / sms_tool_message_status exist

Databases that were migrated from the `new_models` chain (c8d3f6a9e152 ->
f7a2b8c14d90 -> ea92c5d78b10) never ran 39f223faae3b, and now sit at a head
that already counts it as applied. This brings them in line, and is a no-op
for databases where 39f223faae3b did run.

Revision ID: 5b9e1c3a7d42
Revises: ea92c5d78b10
Create Date: 2026-09-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '5b9e1c3a7d42'
down_revision: Union[str, Sequence[str], None] = 'ea92c5d78b10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    status = postgresql.ENUM(
        'approved', 'pending', name='smsmessagestatusenum', schema='call',
        create_type=False,
    )
    status.create(bind, checkfirst=True)
    columns = {c['name'] for c in sa.inspect(bind).get_columns('voiceagent', schema='call')}

    if 'sms_tool_message' not in columns:
        op.add_column(
            'voiceagent',
            sa.Column('sms_tool_message', sa.Text(), nullable=False, server_default=''),
            schema='call',
        )
    if 'sms_tool_message_status' not in columns:
        op.add_column(
            'voiceagent',
            sa.Column('sms_tool_message_status', status, nullable=False,
                      server_default='approved'),
            schema='call',
        )
    # Carry over text an operator already wrote in the other chain's field.
    if 'sms_tool_text' in columns:
        op.execute(
            "UPDATE call.voiceagent SET sms_tool_message = sms_tool_text "
            "WHERE sms_tool_message = '' AND sms_tool_text <> ''"
        )
        op.drop_column('voiceagent', 'sms_tool_text', schema='call')
    if 'sms_tool_prompt' in columns:
        op.drop_column('voiceagent', 'sms_tool_prompt', schema='call')


def downgrade() -> None:
    # Deliberately empty: this only repairs drift; 39f223faae3b owns the columns.
    pass
