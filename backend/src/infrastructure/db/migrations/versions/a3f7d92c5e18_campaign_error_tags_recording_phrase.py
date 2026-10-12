"""campaign error status, call/attempt tags, recording ref, agent feedback phrase, audience upload history

Revision ID: a3f7d92c5e18
Revises: e2b8c47d1f65
Create Date: 2026-09-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a3f7d92c5e18'
down_revision: Union[str, Sequence[str], None] = 'e2b8c47d1f65'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # CampaignStatusEnum gains 'error' (VOAD-36). ADD VALUE is safe inside
    # this migration's transaction as long as nothing in the same migration
    # reads/writes the new value (PG 12+); Postgres has no equivalent
    # downgrade (values cannot be removed from an enum type).
    op.execute("ALTER TYPE call.campaignstatusenum ADD VALUE IF NOT EXISTS 'error'")

    # Call/CallAttempt tags (VOAD-28) — JSONB list, not a fixed enum, so a
    # future tag value needs no migration.
    op.add_column(
        'call',
        sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        schema='call',
    )
    op.add_column(
        'callattempt',
        sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        schema='call',
    )

    # Recording reference (VOAD-37).
    op.add_column('callattempt', sa.Column('recording_url', sa.Text(), nullable=True), schema='call')

    # Feedback-request phrase (VOAD-27) — a new spoken_* line on VoiceAgent,
    # mirroring spoken_reprompt; the two new SilencePolicy timeout knobs live
    # in the existing 'silence' JSONB section and need no migration.
    op.add_column(
        'voiceagent',
        sa.Column('spoken_feedback_request', sa.Text(), nullable=False, server_default=''),
        schema='call',
    )

    # Upload-batch history (VOAD-34's "История загрузок"). audience_id is
    # nullable: the status-segment client import (VOAD-32) has no single
    # audience to point at.
    op.create_table(
        'audienceupload',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('uuid', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('audience_id', sa.BigInteger(), nullable=True),
        sa.Column('uploaded_by', sa.BigInteger(), nullable=False),
        sa.Column('filename', sa.String(), nullable=False, server_default=''),
        sa.Column('total_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('valid_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('invalid_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['audience_id'], ['call.audience.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('uuid'),
        schema='call',
    )
    op.create_index('ix_audienceupload_audience_id', 'audienceupload', ['audience_id'], schema='call')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_audienceupload_audience_id', table_name='audienceupload', schema='call')
    op.drop_table('audienceupload', schema='call')
    op.drop_column('voiceagent', 'spoken_feedback_request', schema='call')
    op.drop_column('callattempt', 'recording_url', schema='call')
    op.drop_column('callattempt', 'tags', schema='call')
    op.drop_column('call', 'tags', schema='call')
    # 'error' cannot be removed from campaignstatusenum by Postgres; a
    # downgrade that actually needs this reversed requires recreating the
    # type (drop/rename dance) and is deliberately not attempted here.
