"""Use a separate schema-owner connection for every migration operation."""

import os

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url

from anoifig.db.base import Base
from anoifig.db.models import Business, Customer, Membership, User  # noqa: F401

target_metadata = Base.metadata


def migration_url() -> str:
    url = os.getenv("ANOIFIG_MIGRATION_DATABASE_URL")
    if not url:
        raise RuntimeError("ANOIFIG_MIGRATION_DATABASE_URL is required for migrations")
    if make_url(url).drivername != "postgresql+psycopg":
        raise RuntimeError("Migrations require the postgresql+psycopg driver")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=migration_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(migration_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
