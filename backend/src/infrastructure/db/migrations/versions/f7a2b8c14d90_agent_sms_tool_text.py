"""fixed, operator-authored SMS text on the voice agent

Revision ID: f7a2b8c14d90
Revises: c8d3f6a9e152
Create Date: 2026-09-25

Keep this published revision reachable for databases from the new_models
branch. The model-defaults migration joins it with the moderation branch;
5b9e1c3a7d42 then carries this text into sms_tool_message and removes the
legacy column.
"""

from alembic import op
import sqlalchemy as sa

revision = "f7a2b8c14d90"
down_revision = "c8d3f6a9e152"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "voiceagent",
        sa.Column("sms_tool_text", sa.Text(), nullable=False, server_default=""),
        schema="call",
    )


def downgrade() -> None:
    # The later repair migration removes this column and deliberately does
    # not restore it on downgrade. Both old and merged schemas can reach here.
    columns = {
        c["name"]
        for c in sa.inspect(op.get_bind()).get_columns("voiceagent", schema="call")
    }
    if "sms_tool_text" in columns:
        op.drop_column("voiceagent", "sms_tool_text", schema="call")
