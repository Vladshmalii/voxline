"""merge billing minutes_only with the model analysis head

Revision ID: b8e4a2c6d913
Revises: d3b7f19c4a60, f3b8d1c6a249
Create Date: 2026-10-07

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = 'b8e4a2c6d913'
down_revision: Union[str, Sequence[str], None] = ('d3b7f19c4a60', 'f3b8d1c6a249')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
