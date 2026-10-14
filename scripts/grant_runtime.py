"""Grant current runtime tables after migrations, using the separate schema owner.

Only use with a reviewed local/CI database or an approved production change process.
Never run migration or grant commands with the application credentials.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from anoifig.db.connection_config import (
    database_connect_args,
    validate_database_url,
    validate_environment,
    verify_database_tls,
)
from anoifig.db.privileges import provision_runtime_grants


def main() -> None:
    environment = validate_environment(os.getenv("ANOIFIG_ENVIRONMENT", "development"))
    owner_url = validate_database_url(os.environ["ANOIFIG_MIGRATION_DATABASE_URL"], environment)
    runtime_url = validate_database_url(os.environ["ANOIFIG_DATABASE_URL"], environment)
    runtime_name = runtime_url.username
    if not runtime_name or runtime_name == owner_url.username:
        raise RuntimeError("Runtime and migration roles must be distinct")
    if (owner_url.host, owner_url.port, owner_url.database) != (
        runtime_url.host,
        runtime_url.port,
        runtime_url.database,
    ):
        raise RuntimeError("Runtime and migration URLs must refer to the same database")

    engine = create_engine(
        owner_url,
        hide_parameters=True,
        poolclass=NullPool,
        connect_args=database_connect_args(environment),
    )
    try:
        with engine.begin() as connection:
            verify_database_tls(connection, environment)
            provision_runtime_grants(connection, runtime_name)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
