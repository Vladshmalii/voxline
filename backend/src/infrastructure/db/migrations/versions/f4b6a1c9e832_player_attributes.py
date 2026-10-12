"""player attributes: player_id, vip_status, last_deposit, last_active, country, timezone

Revision ID: f4b6a1c9e832
Revises: d1a7f2b93c56
Create Date: 2026-09-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f4b6a1c9e832'
down_revision: Union[str, Sequence[str], None] = 'd1a7f2b93c56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('call', sa.Column('player_id', sa.String(), nullable=True), schema='call')
    op.add_column('call', sa.Column('vip_status', sa.String(), nullable=True), schema='call')
    op.add_column('call', sa.Column('last_deposit', sa.Float(), nullable=True), schema='call')
    op.add_column('call', sa.Column('last_active', sa.DateTime(), nullable=True), schema='call')
    op.add_column('call', sa.Column('country', sa.String(), nullable=True), schema='call')
    op.add_column('call', sa.Column('timezone', sa.String(), nullable=True), schema='call')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('call', 'timezone', schema='call')
    op.drop_column('call', 'country', schema='call')
    op.drop_column('call', 'last_active', schema='call')
    op.drop_column('call', 'last_deposit', schema='call')
    op.drop_column('call', 'vip_status', schema='call')
    op.drop_column('call', 'player_id', schema='call')
