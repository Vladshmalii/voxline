"""call outcome answerphone

Revision ID: d2e6a8b4c157
Revises: c9a1e5d7f342
Create Date: 2026-10-05

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'd2e6a8b4c157'
down_revision: Union[str, Sequence[str], None] = 'c9a1e5d7f342'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Same posture as c5d9f3a7e204: ADD VALUE is safe in the migration's
    # transaction (PG 12+) because nothing here uses the new value.
    op.execute("ALTER TYPE call.calloutcomeenum ADD VALUE IF NOT EXISTS 'answerphone'")


def downgrade() -> None:
    """Downgrade schema."""
    # Enum values cannot be removed from a type; rows keep 'answerphone'.
    pass
