"""sms tool: fixed message text and moderation status (VOAD-60/VOAD-62)

Replaces `sms_tool_prompt` (a freeform "when to use the tool" instruction —
the model composed its own SMS text) with `sms_tool_message` (the fixed body
an operator writes once) and `sms_tool_message_status` (staff-authored text
needs owner/admin/super_admin sign-off before the tool is ever offered to
the model; text from owner/admin/super_admin is approved on sight).

Revision ID: 39f223faae3b
Revises: c8d3f6a9e152
Create Date: 2026-09-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '39f223faae3b'
down_revision: Union[str, Sequence[str], None] = 'c8d3f6a9e152'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUSES = ('approved', 'pending')


def _status_enum(create_type: bool = False) -> postgresql.ENUM:
    return postgresql.ENUM(
        *_STATUSES, name='smsmessagestatusenum', schema='call', create_type=create_type
    )


def upgrade() -> None:
    """Upgrade schema."""
    _status_enum().create(op.get_bind(), checkfirst=True)
    op.add_column(
        'voiceagent',
        sa.Column('sms_tool_message', sa.Text(), nullable=False, server_default=''),
        schema='call',
    )
    op.add_column(
        'voiceagent',
        sa.Column(
            'sms_tool_message_status',
            _status_enum(),
            nullable=False,
            server_default='approved',
        ),
        schema='call',
    )
    # The old field was an instruction for *when* to use the tool, not
    # message text — no data worth carrying forward into the new column.
    op.drop_column('voiceagent', 'sms_tool_prompt', schema='call')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        'voiceagent',
        sa.Column('sms_tool_prompt', sa.Text(), nullable=False, server_default=''),
        schema='call',
    )
    op.drop_column('voiceagent', 'sms_tool_message_status', schema='call')
    op.drop_column('voiceagent', 'sms_tool_message', schema='call')
    _status_enum().drop(op.get_bind(), checkfirst=True)
