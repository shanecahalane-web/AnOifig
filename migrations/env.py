"""Use a separate schema-owner connection for every migration operation."""

import os

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import URL

from anoifig.db.base import Base
from anoifig.db.connection_config import (
    database_connect_args,
    validate_database_url,
    validate_environment,
    verify_database_tls,
)
from anoifig.db.models import Business, Customer, Membership, User  # noqa: F401

target_metadata = Base.metadata


def migration_url() -> URL:
    url = os.getenv("ANOIFIG_MIGRATION_DATABASE_URL")
    if not url:
        raise RuntimeError("ANOIFIG_MIGRATION_DATABASE_URL is required for migrations")
    return validate_database_url(url, migration_environment())


def migration_environment() -> str:
    return validate_environment(os.getenv("ANOIFIG_ENVIRONMENT", "development"))


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
    environment = migration_environment()
    engine = create_engine(
        migration_url(),
        poolclass=pool.NullPool,
        connect_args=database_connect_args(environment),
        hide_parameters=True,
    )
    try:
        with engine.connect() as connection:
            # This SELECT starts a SQLAlchemy transaction. Finish the transport
            # probe before Alembic owns its migration transaction boundaries.
            verify_database_tls(connection, environment)
            connection.commit()
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
