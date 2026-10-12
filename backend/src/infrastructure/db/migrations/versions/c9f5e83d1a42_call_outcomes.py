"""post-call analysis: summary and outcome

Revision ID: c9f5e83d1a42
Revises: b7e41f2a9c30
Create Date: 2026-09-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c9f5e83d1a42'
down_revision: Union[str, Sequence[str], None] = 'b7e41f2a9c30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OUTCOMES = (
    'interested', 'not_interested', 'call_later', 'converted',
    'escalated', 'wrong_number', 'do_not_call', 'no_answer',
)


def _outcome_enum(create_type: bool = False) -> postgresql.ENUM:
    return postgresql.ENUM(
        *_OUTCOMES, name='calloutcomeenum', schema='call', create_type=create_type
    )


def upgrade() -> None:
    """Upgrade schema."""
    _outcome_enum().create(op.get_bind(), checkfirst=True)
    op.add_column('callattempt', sa.Column('summary', sa.Text(), nullable=True), schema='call')
    op.add_column('callattempt', sa.Column('outcome', _outcome_enum(), nullable=True), schema='call')
    op.add_column('call', sa.Column('outcome', _outcome_enum(), nullable=True), schema='call')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('call', 'outcome', schema='call')
    op.drop_column('callattempt', 'outcome', schema='call')
    op.drop_column('callattempt', 'summary', schema='call')
    _outcome_enum().drop(op.get_bind(), checkfirst=True)
