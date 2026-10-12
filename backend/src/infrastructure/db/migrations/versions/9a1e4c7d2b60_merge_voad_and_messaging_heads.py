"""merge VOAD batch and messaging/audiences heads

Revision ID: 9a1e4c7d2b60
Revises: a3f7d92c5e18, f8c2ff22b594
Create Date: 2026-09-16

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = '9a1e4c7d2b60'
down_revision: Union[str, Sequence[str], None] = ('a3f7d92c5e18', 'f8c2ff22b594')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
