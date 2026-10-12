"""merge sms_tool_message ensure and call/SMS balances heads

Revision ID: f4f4ad164ece
Revises: 5b9e1c3a7d42, 6dcb902f4a31
Create Date: 2026-10-01

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = 'f4f4ad164ece'
down_revision: Union[str, Sequence[str], None] = ('5b9e1c3a7d42', '6dcb902f4a31')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
