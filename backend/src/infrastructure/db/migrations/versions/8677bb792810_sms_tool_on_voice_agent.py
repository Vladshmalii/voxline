"""sms tool toggle and prompt on voice agent

Revision ID: 8677bb792810
Revises: a1b2c3d4e5f6
Create Date: 2026-09-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '8677bb792810'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Lets an agent advertise a "send_sms" function to the model. Plain
    # columns, not a JSONB section — no nested structure, same shape as
    # spoken_feedback_request.
    op.add_column(
        'voiceagent',
        sa.Column('sms_tool_enabled', sa.Boolean(), nullable=False, server_default='false'),
        schema='call',
    )
    op.add_column(
        'voiceagent',
        sa.Column('sms_tool_prompt', sa.Text(), nullable=False, server_default=''),
        schema='call',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('voiceagent', 'sms_tool_prompt', schema='call')
    op.drop_column('voiceagent', 'sms_tool_enabled', schema='call')
