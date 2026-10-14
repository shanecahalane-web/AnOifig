"""Grant current runtime tables after migrations, using the separate schema owner.

Only use with a reviewed local/CI database or an approved production change process.
Never run migration or grant commands with the application credentials.
"""

import os

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url


def main() -> None:
    owner_url = make_url(os.environ["ANOIFIG_MIGRATION_DATABASE_URL"])
    runtime_url = make_url(os.environ["ANOIFIG_DATABASE_URL"])
    runtime_name = runtime_url.username
    if not runtime_name or runtime_name == owner_url.username:
        raise RuntimeError("Runtime and migration roles must be distinct")
    if (owner_url.host, owner_url.port, owner_url.database) != (
        runtime_url.host,
        runtime_url.port,
        runtime_url.database,
    ):
        raise RuntimeError("Runtime and migration URLs must refer to the same database")

    connection_url = owner_url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(connection_url) as connection:
        attributes = connection.execute(
            "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
            "FROM pg_roles WHERE rolname = %s",
            (runtime_name,),
        ).fetchone()
        if attributes is None or any(attributes):
            raise RuntimeError("Runtime role is missing or has privileged role attributes")
        owns_objects = connection.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner "
            "WHERE c.relnamespace = 'public'::regnamespace AND r.rolname = %s)",
            (runtime_name,),
        ).fetchone()
        if owns_objects is None or owns_objects[0]:
            raise RuntimeError("Runtime role must not own application schema objects")
        has_memberships = connection.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r "
            "ON r.oid = m.member WHERE r.rolname = %s)",
            (runtime_name,),
        ).fetchone()
        if has_memberships is None or has_memberships[0]:
            raise RuntimeError(
                "Runtime role must not have inherited or switchable role memberships"
            )

        role = sql.Identifier(runtime_name)
        connection.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
        for table in ("businesses", "users", "memberships"):
            connection.execute(
                sql.SQL("GRANT SELECT ON TABLE public.{} TO {}").format(sql.Identifier(table), role)
            )
        connection.execute(
            sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.customers TO {}").format(
                role
            )
        )


if __name__ == "__main__":
    main()
