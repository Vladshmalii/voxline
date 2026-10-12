"""archive flag on campaigns and audiences

Revision ID: a1b2c3d4e5f6
Revises: 9a1e4c7d2b60
Create Date: 2026-09-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '9a1e4c7d2b60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Archiving hides a campaign/audience from the default list without
    # touching what actually happened (unlike delete, which Campaign refuses
    # once a call exists — ondelete='RESTRICT' on Call.campaign_id — and
    # which is fine for an audience but loses the list itself). A campaign's
    # own service layer refuses to archive one that is still `running`
    # (pause or complete it first); audiences have no such lifecycle.
    op.add_column(
        'campaign',
        sa.Column('is_archived', sa.Boolean(), nullable=False, server_default='false'),
        schema='call',
    )
    op.add_column(
        'audience',
        sa.Column('is_archived', sa.Boolean(), nullable=False, server_default='false'),
        schema='call',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('audience', 'is_archived', schema='call')
    op.drop_column('campaign', 'is_archived', schema='call')
