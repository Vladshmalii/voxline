"""client: persistent country/language/vip_status/last_deposit/last_active/segment

Revision ID: e2b8c47d1f65
Revises: c1d84f7a930e
Create Date: 2026-09-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e2b8c47d1f65'
down_revision: Union[str, Sequence[str], None] = 'c1d84f7a930e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEGMENTS = ('cold', 'warm', 'hot')


def _segment_enum(create_type: bool = False) -> postgresql.ENUM:
    return postgresql.ENUM(*_SEGMENTS, name='clientsegmentenum', schema='call', create_type=create_type)


def upgrade() -> None:
    """Upgrade schema."""
    _segment_enum().create(op.get_bind(), checkfirst=True)
    op.add_column('client', sa.Column('country', sa.String(), nullable=True), schema='call')
    op.add_column('client', sa.Column('language', sa.String(), nullable=True), schema='call')
    op.add_column('client', sa.Column('vip_status', sa.String(), nullable=True), schema='call')
    op.add_column('client', sa.Column('last_deposit', sa.Float(), nullable=True), schema='call')
    op.add_column('client', sa.Column('last_active', sa.DateTime(), nullable=True), schema='call')
    op.add_column('client', sa.Column('segment', _segment_enum(), nullable=True), schema='call')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('client', 'segment', schema='call')
    op.drop_column('client', 'last_active', schema='call')
    op.drop_column('client', 'last_deposit', schema='call')
    op.drop_column('client', 'vip_status', schema='call')
    op.drop_column('client', 'language', schema='call')
    op.drop_column('client', 'country', schema='call')
    _segment_enum().drop(op.get_bind(), checkfirst=True)
