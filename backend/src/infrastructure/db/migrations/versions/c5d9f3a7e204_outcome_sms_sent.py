"""call outcome sms_sent

Revision ID: c5d9f3a7e204
Revises: b4c8e2f61a73
Create Date: 2026-10-01

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c5d9f3a7e204'
down_revision: Union[str, Sequence[str], None] = 'b4c8e2f61a73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Same posture as b4c8e2f61a73: ADD VALUE is safe in the migration's
    # transaction (PG 12+) because nothing here uses the new value.
    op.execute("ALTER TYPE call.calloutcomeenum ADD VALUE IF NOT EXISTS 'sms_sent'")


def downgrade() -> None:
    """Downgrade schema."""
    # Enum values cannot be removed from a type; rows keep 'sms_sent'.
    pass
