"""Persist source context and evidence windows for worker recovery."""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_snapshots",
        sa.Column("key", sa.String(160), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("runtime_snapshots")
