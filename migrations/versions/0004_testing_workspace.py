"""Pinned testing jobs, per-frame results and shared authentication limits."""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    for check in sa.inspect(op.get_bind()).get_check_constraints("processing_jobs"):
        if "state" in check["sqltext"]:
            op.drop_constraint(check["name"], "processing_jobs", type_="check")
    op.create_check_constraint(
        "ck_job_state", "processing_jobs", "state IN ('queued','running','completed','failed','paused','cancelled')"
    )
    op.add_column("processing_jobs", sa.Column("snapshot", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column(
        "processing_jobs", sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column("processing_jobs", sa.Column("processing_seconds", sa.Float(), nullable=False, server_default="0"))
    op.add_column("processing_jobs", sa.Column("processed_frames", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "job_frames",
        sa.Column("id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("job_id", sa.Uuid(as_uuid=False), sa.ForeignKey("processing_jobs.id"), nullable=False),
        sa.Column("timestamp", sa.Float(), nullable=False),
        sa.Column("predictions", sa.JSON(), nullable=False),
        sa.Column("unknown", sa.JSON(), nullable=False),
        sa.UniqueConstraint("job_id", "timestamp"),
    )
    op.create_index("ix_job_frames_job_id", "job_frames", ["job_id"])
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_login_attempts_expires_at", "login_attempts", ["expires_at"])
    for table in ("job_frames", "login_attempts"):
        op.execute(sa.text(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY'))


def downgrade():
    op.drop_table("login_attempts")
    op.drop_table("job_frames")
    op.execute("UPDATE processing_jobs SET state='failed' WHERE state='cancelled'")
    op.drop_constraint("ck_job_state", "processing_jobs", type_="check")
    op.create_check_constraint(
        "ck_job_state", "processing_jobs", "state IN ('queued','running','completed','failed','paused')"
    )
    for name in ("snapshot", "cancel_requested", "processing_seconds", "processed_frames"):
        op.drop_column("processing_jobs", name)
