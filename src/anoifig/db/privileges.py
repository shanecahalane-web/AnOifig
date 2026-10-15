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
    "phone_links": frozenset({"SELECT", "INSERT", "UPDATE"}),
    "conversations": frozenset({"SELECT", "INSERT", "UPDATE"}),
    "messages": frozenset({"SELECT", "INSERT", "UPDATE"}),
    "outbox": frozenset({"SELECT", "INSERT", "UPDATE"}),
    "message_jobs": frozenset(),
}

# Do not give the application generic function execution. These functions reveal
# only routing IDs/identity context or consume an existing phone challenge.
RUNTIME_FUNCTIONS = frozenset(
    {
        "messaging_route_phone(text)",
        "messaging_redeem_phone(text,text)",
        "messaging_lookup_job(uuid)",
        "messaging_discover_jobs(integer)",
        "messaging_park_job(uuid)",
    }
)
GATEWAY_TRIGGER_FUNCTIONS = frozenset({"messaging_index_inbound()", "messaging_index_outbound()"})
GATEWAY_GUARD_FUNCTIONS = frozenset({"messaging_guard_phone_link()"})


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
            if not privileges:
                continue
            allowed = ", ".join(sorted(privileges))
            connection.exec_driver_sql(f"GRANT {allowed} ON TABLE public.{quote(table)} TO {role}")
        for function in sorted(RUNTIME_FUNCTIONS):
            connection.exec_driver_sql(f"GRANT EXECUTE ON FUNCTION public.{function} TO {role}")
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
    check_runtime_functions(connection, role_name=role_name, require_expected=require_expected)


def check_runtime_functions(
    connection: Connection, *, role_name: str, require_expected: bool
) -> None:
    """Validate callable gateway functions and the privileged trigger helpers.

    Fixed search paths and metadata ownership remain mandatory even before the
    first grant. Ordinary source-table triggers never expose a callable runtime
    entrypoint. PUBLIC execute is forbidden for every gateway/helper function.
    """
    functions = connection.execute(
        text(
            """
            SELECT p.oid, p.oid::regprocedure::text AS signature, p.prosecdef,
                   p.proconfig, p.prokind,
                   p.proowner = (SELECT relowner FROM pg_class
                                WHERE oid = 'public.phone_links'::regclass) AS metadata_owner,
                   has_function_privilege(:role, p.oid, 'EXECUTE') AS allowed,
                   has_function_privilege(:role, p.oid, 'EXECUTE WITH GRANT OPTION') AS grantable,
                   EXISTS (SELECT 1 FROM aclexplode(
                                        COALESCE(p.proacl, acldefault('f', p.proowner))) a
                            WHERE a.grantee = 0 AND a.privilege_type = 'EXECUTE') AS public_execute
              FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace
            """
        ),
        {"role": role_name},
    ).all()
    expected = RUNTIME_FUNCTIONS | GATEWAY_TRIGGER_FUNCTIONS | GATEWAY_GUARD_FUNCTIONS
    found: set[str] = set()
    for function in functions:
        signature = function.signature.removeprefix("public.")
        if function.grantable or (function.allowed and signature not in RUNTIME_FUNCTIONS):
            raise UnsafeDatabaseConfiguration
        if signature in expected:
            found.add(signature)
            if (
                function.prosecdef != (signature not in GATEWAY_GUARD_FUNCTIONS)
                or function.prokind != "f"
                or function.proconfig != ["search_path=pg_catalog"]
                or not function.metadata_owner
                or function.public_execute
                or (require_expected and signature in RUNTIME_FUNCTIONS and not function.allowed)
            ):
                raise UnsafeDatabaseConfiguration
    if found != expected:
        raise UnsafeDatabaseConfiguration
