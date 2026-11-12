"""Grant application roles to existing Supabase identities; no local passwords."""

from uuid import UUID
import click
from sqlalchemy import select
from safesight.backend.context import sessions
from safesight.storage.schema import User


@click.command("grant-user")
@click.argument("supabase_id")
@click.argument("email")
@click.option("--role", type=click.Choice(["admin", "reviewer"]), default="reviewer")
@click.option("--disabled", is_flag=True, help="Disable application access without deleting review history")
def grant_user(supabase_id: str, email: str, role: str, disabled: bool) -> None:
    """Bind a dashboard Auth user UUID to an application role using trusted operator access."""
    try:
        subject = str(UUID(supabase_id))
    except ValueError:
        raise click.ClickException("Use the Auth user UUID from the Supabase dashboard") from None
    email = email.strip().lower()
    if "@" not in email or len(email) > 320:
        raise click.ClickException("Provide a valid email address")
    with sessions.begin() as db:
        user = db.scalar(select(User).where(User.supabase_id == subject))
        if user is None:
            existing = db.scalar(select(User).where(User.username == email))
            if existing is not None:
                raise click.ClickException("Email already belongs to another profile; resolve the conflict explicitly")
            user = User(supabase_id=subject, username=email)
            db.add(user)
        user.role, user.active = role, not disabled
    click.echo("Updated SafeSight access; passwords and invites are managed in Supabase Auth")
