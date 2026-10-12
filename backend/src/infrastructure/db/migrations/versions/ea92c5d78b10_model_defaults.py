"""Organization defaults for client-created voice agents."""

from alembic import op
import sqlalchemy as sa

revision = "ea92c5d78b10"
# Both published SMS histories remain ancestors. Databases already stamped
# here (or at the balance revision) are repaired by 5b9e1c3a7d42.
down_revision = ("39f223faae3b", "f7a2b8c14d90")
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "model",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        schema="call",
    )
    # Preserve an unambiguous existing setup; never guess among multiple models.
    op.execute("""
        UPDATE call.model SET is_default = true
        WHERE id IN (
            SELECT min(id) FROM call.model WHERE is_active
            GROUP BY kind HAVING count(*) = 1
        )
    """)
    op.create_index(
        "uq_model_default_kind",
        "model",
        ["kind"],
        unique=True,
        schema="call",
        postgresql_where=sa.text("is_default"),
    )
    op.create_check_constraint(
        "ck_model_default_active", "model", "NOT is_default OR is_active", schema="call"
    )


def downgrade():
    op.drop_constraint("ck_model_default_active", "model", schema="call", type_="check")
    op.drop_index("uq_model_default_kind", table_name="model", schema="call")
    op.drop_column("model", "is_default", schema="call")
