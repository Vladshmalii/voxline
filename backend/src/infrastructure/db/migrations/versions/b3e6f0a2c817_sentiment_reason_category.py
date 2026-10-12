"""AI analysis: sentiment and decline reason category

Revision ID: b3e6f0a2c817
Revises: a7c2d5e91f04
Create Date: 2026-09-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b3e6f0a2c817'
down_revision: Union[str, Sequence[str], None] = 'a7c2d5e91f04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SENTIMENTS = ('positive', 'neutral', 'negative')
_REASONS = (
    'bonus_conditions', 'payment_problem', 'lost_interest', 'competitor',
    'technical_issue', 'responsible_gaming', 'other',
)


def _sentiment_enum(create_type: bool = False) -> postgresql.ENUM:
    return postgresql.ENUM(
        *_SENTIMENTS, name='sentimentenum', schema='call', create_type=create_type
    )


def _reason_enum(create_type: bool = False) -> postgresql.ENUM:
    return postgresql.ENUM(
        *_REASONS, name='reasoncategoryenum', schema='call', create_type=create_type
    )


def upgrade() -> None:
    """Upgrade schema."""
    _sentiment_enum().create(op.get_bind(), checkfirst=True)
    _reason_enum().create(op.get_bind(), checkfirst=True)
    op.add_column('call', sa.Column('sentiment', _sentiment_enum(), nullable=True), schema='call')
    op.add_column(
        'call', sa.Column('reason_category', _reason_enum(), nullable=True), schema='call'
    )
    op.add_column(
        'callattempt', sa.Column('sentiment', _sentiment_enum(), nullable=True), schema='call'
    )
    op.add_column(
        'callattempt', sa.Column('reason_category', _reason_enum(), nullable=True), schema='call'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('callattempt', 'reason_category', schema='call')
    op.drop_column('callattempt', 'sentiment', schema='call')
    op.drop_column('call', 'reason_category', schema='call')
    op.drop_column('call', 'sentiment', schema='call')
    _reason_enum().drop(op.get_bind(), checkfirst=True)
    _sentiment_enum().drop(op.get_bind(), checkfirst=True)
