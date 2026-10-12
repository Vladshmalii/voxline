"""index call.created_at for dashboard trend queries

Revision ID: 0b99443bd6da
Revises: a1b2c3d4e5f6
Create Date: 2026-09-18

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0b99443bd6da'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # StatsService.timeseries()/headline_counts() both filter or group by
    # this column (dashboard redesign) — it had no index before (see
    # Call.__table_args__: only status+next_attempt_at, campaign_id,
    # client_id).
    op.create_index(
        'ix_call_created_at',
        'call',
        ['created_at'],
        schema='call',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_call_created_at', table_name='call', schema='call')
