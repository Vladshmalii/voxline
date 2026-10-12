"""post-call analysis: selected offer

Revision ID: d1a7f2b93c56
Revises: c9f5e83d1a42
Create Date: 2026-09-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd1a7f2b93c56'
down_revision: Union[str, Sequence[str], None] = 'c9f5e83d1a42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('callattempt', sa.Column('selected_offer', sa.String(), nullable=True), schema='call')
    op.add_column('call', sa.Column('selected_offer', sa.String(), nullable=True), schema='call')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('call', 'selected_offer', schema='call')
    op.drop_column('callattempt', 'selected_offer', schema='call')
