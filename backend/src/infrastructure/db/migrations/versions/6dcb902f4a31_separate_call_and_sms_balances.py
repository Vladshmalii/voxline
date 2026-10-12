"""Independent call/SMS balances and channel-scoped transaction history.

Revision ID: 6dcb902f4a31
Revises: ea92c5d78b10
"""

from alembic import op
import sqlalchemy as sa

revision = "6dcb902f4a31"
down_revision = "ea92c5d78b10"
branch_labels = None
depends_on = None


def upgrade():
    # Preserve all existing funds in the call account. SMS starts at zero.
    op.alter_column(
        "organizationbalance", "balance", new_column_name="call_balance", schema="call"
    )
    op.add_column(
        "organizationbalance",
        sa.Column("sms_balance", sa.Float(), nullable=False, server_default="0.0"),
        schema="call",
    )
    op.add_column(
        "balancetransaction",
        sa.Column("channel", sa.String(8), nullable=False, server_default="calls"),
        schema="call",
    )
    op.add_column(
        "balancetransaction",
        sa.Column("legacy_balance_after", sa.Float(), nullable=True),
        schema="call",
    )
    # Preserve historical snapshots with their original shared-account meaning.
    op.execute(
        "UPDATE call.balancetransaction SET legacy_balance_after = balance_after, balance_after = NULL"
    )
    op.execute(
        "UPDATE call.balancetransaction SET channel = 'sms' WHERE type = 'sms_usage' OR sms_id IS NOT NULL"
    )
    op.create_check_constraint(
        "ck_balancetransaction_channel",
        "balancetransaction",
        "channel IN ('calls', 'sms')",
        schema="call",
    )
    op.create_index(
        "ix_balancetransaction_channel_created_at",
        "balancetransaction",
        ["channel", "created_at"],
        schema="call",
    )
    op.create_index("ix_message_created_at", "message", ["created_at"], schema="call")


def downgrade():
    # Both pools must survive a rollback to the old single-balance schema.
    op.execute(
        "UPDATE call.organizationbalance SET call_balance = call_balance + sms_balance"
    )
    op.drop_index("ix_message_created_at", table_name="message", schema="call")
    op.drop_index(
        "ix_balancetransaction_channel_created_at",
        table_name="balancetransaction",
        schema="call",
    )
    op.drop_constraint(
        "ck_balancetransaction_channel",
        "balancetransaction",
        type_="check",
        schema="call",
    )
    op.drop_column("balancetransaction", "channel", schema="call")
    op.execute(
        "UPDATE call.balancetransaction SET balance_after = COALESCE(balance_after, legacy_balance_after)"
    )
    op.drop_column("balancetransaction", "legacy_balance_after", schema="call")
    op.drop_column("organizationbalance", "sms_balance", schema="call")
    op.alter_column(
        "organizationbalance", "call_balance", new_column_name="balance", schema="call"
    )
