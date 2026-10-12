"""merge messaging bindings and audiences heads

Revision ID: f8c2ff22b594
Revises: c1d84f7a930e, d1a73c05e6b8
Create Date: 2026-09-16

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = 'f8c2ff22b594'
down_revision: Union[str, Sequence[str], None] = ('c1d84f7a930e', 'd1a73c05e6b8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
