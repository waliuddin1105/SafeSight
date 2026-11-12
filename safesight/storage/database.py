"""Database connection factory shared by web and worker processes."""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


def database(url: str):
    options = {"pool_pre_ping": True, "hide_parameters": True}
    if url.startswith("postgresql"):
        options.update(pool_size=3, max_overflow=2, pool_recycle=600, connect_args={"connect_timeout": 10})
    engine = create_engine(url, **options)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    return engine, sessionmaker(engine, expire_on_commit=False)
