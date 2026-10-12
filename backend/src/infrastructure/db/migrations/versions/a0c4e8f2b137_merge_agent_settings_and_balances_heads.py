"""merge organization agent settings with the call/SMS balances head

Revision ID: a0c4e8f2b137
Revises: f4f4ad164ece, e7a3c1d9b256
Create Date: 2026-10-02

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = 'a0c4e8f2b137'
down_revision: Union[str, Sequence[str], None] = ('f4f4ad164ece', 'e7a3c1d9b256')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
