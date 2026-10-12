"""merge max-call-duration and agent-messaging-binding heads

Revision ID: c8d3f6a9e152
Revises: f1c6b3a482de, e4b1c78d3a25
Create Date: 2026-09-24

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = 'c8d3f6a9e152'
down_revision: Union[str, Sequence[str], None] = ('f1c6b3a482de', 'e4b1c78d3a25')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
