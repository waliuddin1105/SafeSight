"""Explicit account administration commands."""

from __future__ import annotations


import click
from werkzeug.security import generate_password_hash

from safesight.storage.schema import (
    User,
)


from safesight.backend.context import sessions


@click.command("create-user")
@click.argument("username")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
@click.option("--role", type=click.Choice(["admin", "reviewer"]), default="reviewer")
def create_user(username, password, role):
    if len(password) < 12:
        raise click.ClickException("Password needs at least 12 characters")
    with sessions.begin() as db:
        db.add(User(username=username, password_hash=generate_password_hash(password), role=role))
    click.echo("User created")
