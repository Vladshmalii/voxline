"""merge call.created_at index and sms tool heads

Revision ID: 8a390f62760d
Revises: 0b99443bd6da, 8677bb792810
Create Date: 2026-09-18

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = '8a390f62760d'
down_revision: Union[str, Sequence[str], None] = ('0b99443bd6da', '8677bb792810')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
