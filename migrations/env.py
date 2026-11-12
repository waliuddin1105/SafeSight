"""Alembic environment using environment-provided database credentials."""

from alembic import context
from sqlalchemy import create_engine
from safesight.config import settings
from safesight.storage.schema import Base

url = settings()["migration_database_url"]
if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(url).connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
