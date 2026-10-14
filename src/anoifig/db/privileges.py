"""Least-privilege contract shared by runtime checks and owner-run provisioning.

Check effective permissions, including PUBLIC grants, rather than just direct ACLs.
New application tables require a reviewed addition to this explicit contract.
"""

from sqlalchemy import Connection, text


class UnsafeDatabaseConfiguration(Exception):
    """Runtime privileges or schema protections do not satisfy the trust boundary."""


RUNTIME_TABLE_PRIVILEGES: dict[str, frozenset[str]] = {
    "businesses": frozenset({"SELECT"}),
    "users": frozenset({"SELECT"}),
    "memberships": frozenset({"SELECT"}),
    "customers": frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"}),
}


def provision_runtime_grants(connection: Connection, runtime_name: str) -> None:
    """Add reviewed grants inside the caller's transaction, failing on privilege drift.

    Unknown excess grants may affect other applications or stem from PUBLIC/role
    changes. Fail before mutation so an operator can investigate; do not revoke
    unknown access automatically. A savepoint also removes partial grants if the
    postcheck or a grant fails, even if the caller handles the exception.
    """
    with connection.begin_nested():
        check_runtime_privileges(connection, role_name=runtime_name, require_expected=False)
        quote = connection.dialect.identifier_preparer.quote_identifier
        role = quote(runtime_name)
        database = quote(connection.scalar(text("SELECT current_database()")))
        connection.exec_driver_sql(f"GRANT CONNECT ON DATABASE {database} TO {role}")
        connection.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {role}")
        for table, privileges in RUNTIME_TABLE_PRIVILEGES.items():
            allowed = ", ".join(sorted(privileges))
            connection.exec_driver_sql(f"GRANT {allowed} ON TABLE public.{quote(table)} TO {role}")
        check_runtime_privileges(connection, role_name=runtime_name)


def check_runtime_privileges(
    connection: Connection, *, role_name: str | None = None, require_expected: bool = True
) -> None:
    """Reject excess authority; optionally allow missing grants before provisioning.

    No role memberships are supported: even a non-inherited membership may permit
    SET ROLE. The provisioning preflight must never silently revoke unknown grants
    or accept excess permissions while adding missing ones.
    """
    role_name = role_name or connection.scalar(text("SELECT current_user"))
    flags = connection.execute(
        text(
            """
            SELECT r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb
                       OR r.rolreplication AS privileged,
                   EXISTS (SELECT 1 FROM pg_auth_members WHERE member = r.oid)
                       AS memberships,
                   EXISTS (SELECT 1 FROM pg_database
                            WHERE datname = current_database() AND datdba = r.oid)
                       OR EXISTS (SELECT 1 FROM pg_namespace
                                   WHERE nspname = 'public' AND nspowner = r.oid)
                       OR EXISTS (SELECT 1 FROM pg_class
                                   WHERE relnamespace = 'public'::regnamespace
                                     AND relowner = r.oid)
                       OR EXISTS (SELECT 1 FROM pg_proc
                                   WHERE pronamespace = 'public'::regnamespace
                                     AND proowner = r.oid)
                       AS owns_objects,
                   has_database_privilege(r.oid, current_database(), 'CREATE,TEMP')
                       OR has_database_privilege(
                           r.oid, current_database(), 'CONNECT WITH GRANT OPTION')
                       OR has_schema_privilege(r.oid, 'public', 'CREATE')
                       OR has_schema_privilege(r.oid, 'public', 'USAGE WITH GRANT OPTION')
                       AS excess_scope,
                   has_database_privilege(r.oid, current_database(), 'CONNECT')
                       AND has_schema_privilege(r.oid, 'public', 'USAGE') AS expected_scope
              FROM pg_roles r WHERE r.rolname = :role
            """
        ),
        {"role": role_name},
    ).one_or_none()
    if (
        flags is None
        or flags.privileged
        or flags.memberships
        or flags.owns_objects
        or flags.excess_scope
        or (require_expected and not flags.expected_scope)
    ):
        raise UnsafeDatabaseConfiguration

    table_rights = connection.execute(
        text(
            """
            SELECT c.relname, c.relkind, p.privilege,
                   has_table_privilege(:role, c.oid, p.privilege) AS allowed,
                   has_table_privilege(:role, c.oid, p.privilege || ' WITH GRANT OPTION')
                       AS grantable
              FROM pg_class c
              CROSS JOIN unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE',
                                      'TRUNCATE', 'REFERENCES', 'TRIGGER']
                                || CASE WHEN current_setting('server_version_num')::int >= 170000
                                        THEN ARRAY['MAINTAIN'] ELSE ARRAY[]::text[] END)
                         AS p(privilege)
             WHERE c.relnamespace = 'public'::regnamespace
               AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
            """
        ),
        {"role": role_name},
    ).all()
    present_tables: set[str] = set()
    for right in table_rights:
        expected = RUNTIME_TABLE_PRIVILEGES.get(right.relname, frozenset())
        if right.relname in RUNTIME_TABLE_PRIVILEGES and right.relkind != "r":
            raise UnsafeDatabaseConfiguration
        present_tables.add(right.relname)
        if (
            right.grantable
            or (right.allowed and right.privilege not in expected)
            or (require_expected and right.privilege in expected and not right.allowed)
        ):
            raise UnsafeDatabaseConfiguration
    if not RUNTIME_TABLE_PRIVILEGES.keys() <= present_tables:
        raise UnsafeDatabaseConfiguration

    column_rights = connection.execute(
        text(
            """
            SELECT c.relname, p.privilege,
                   has_any_column_privilege(:role, c.oid, p.privilege) AS allowed,
                   has_any_column_privilege(
                       :role, c.oid, p.privilege || ' WITH GRANT OPTION') AS grantable
              FROM pg_class c
              CROSS JOIN unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'REFERENCES'])
                         AS p(privilege)
             WHERE c.relnamespace = 'public'::regnamespace
               AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
            """
        ),
        {"role": role_name},
    ).all()
    for right in column_rights:
        if right.grantable or (
            right.allowed
            and right.privilege not in RUNTIME_TABLE_PRIVILEGES.get(right.relname, frozenset())
        ):
            raise UnsafeDatabaseConfiguration

    if connection.scalar(
        text(
            """
            SELECT EXISTS (
                SELECT 1 FROM pg_class c
                 WHERE c.relnamespace = 'public'::regnamespace
                   AND CASE WHEN c.relkind = 'S'
                            THEN has_sequence_privilege(:role, c.oid, 'USAGE,SELECT,UPDATE')
                            ELSE false END)
            """
        ),
        {"role": role_name},
    ):
        raise UnsafeDatabaseConfiguration
