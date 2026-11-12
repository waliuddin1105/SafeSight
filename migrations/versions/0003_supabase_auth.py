"""Replace password credentials with Supabase identity profiles and backend sessions."""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("supabase_id", sa.Uuid(as_uuid=False), nullable=True))
    op.create_unique_constraint("uq_users_supabase_id", "users", ["supabase_id"])
    op.alter_column("users", "username", type_=sa.String(320), existing_type=sa.String(80))
    op.drop_column("users", "password_hash")
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Uuid(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    # Supabase exposes public through its Data API. No browser role should read
    # application tables or session tokens: all access goes through Flask's DB role.
    for table in (
        "users",
        "auth_sessions",
        "locations",
        "sources",
        "processing_jobs",
        "frame_packets",
        "model_versions",
        "incidents",
        "incident_predictions",
        "evidence",
        "incident_reviews",
        "system_state",
        "runtime_snapshots",
    ):
        op.execute(sa.text(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY'))


def downgrade() -> None:
    op.drop_table("auth_sessions")
    # Old credentials cannot be recovered. Legacy login remains disabled for these rows.
    op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=False, server_default=""))
    op.drop_constraint("uq_users_supabase_id", "users", type_="unique")
    op.drop_column("users", "supabase_id")
    # Keep expanded email capacity and RLS to preserve data/security on downgrade.
