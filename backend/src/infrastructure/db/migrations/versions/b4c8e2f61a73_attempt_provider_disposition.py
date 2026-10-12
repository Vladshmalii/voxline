"""attempt provider status/reason, rejected and invalid_number call statuses

Revision ID: b4c8e2f61a73
Revises: a9d3e7b1c458
Create Date: 2026-10-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b4c8e2f61a73'
down_revision: Union[str, Sequence[str], None] = 'a9d3e7b1c458'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ADD VALUE is safe inside this migration's transaction (PG 12+) as long
    # as nothing here reads/writes the new values; values cannot be removed
    # from an enum type, so downgrade leaves them.
    op.execute("ALTER TYPE call.callstatusenum ADD VALUE IF NOT EXISTS 'rejected'")
    op.execute("ALTER TYPE call.callstatusenum ADD VALUE IF NOT EXISTS 'invalid_number'")
    op.add_column('callattempt', sa.Column('provider_status', sa.String(), nullable=True), schema='call')
    op.add_column('callattempt', sa.Column('provider_reason', sa.String(), nullable=True), schema='call')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('callattempt', 'provider_reason', schema='call')
    op.drop_column('callattempt', 'provider_status', schema='call')
