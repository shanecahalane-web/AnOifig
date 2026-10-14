"""Runtime connections and transaction-scoped PostgreSQL security context."""

from uuid import UUID

from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.orm import Session

from anoifig.config import Settings
from anoifig.identity.auth import VerifiedIdentity


class UnsafeDatabaseConfiguration(Exception):
    """Runtime privileges or schema protections do not satisfy the trust boundary."""


def build_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_connect_timeout,
        pool_recycle=1800,
        connect_args={
            "connect_timeout": settings.database_connect_timeout,
            "options": (
                f"-c statement_timeout={settings.database_statement_timeout_ms} "
                f"-c lock_timeout={settings.database_statement_timeout_ms} "
                "-c search_path=pg_catalog,public"
            ),
        },
        hide_parameters=True,
        echo=False,
    )


def check_runtime_database(connection: Connection, *, require_tls: bool = False) -> None:
    """Fail closed rather than run the application as a migration/owner account."""
    if require_tls and not connection.scalar(
        text("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
    ):
        raise UnsafeDatabaseConfiguration
    role = connection.execute(
        text(
            "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolreplication "
            "FROM pg_roles WHERE rolname = current_user"
        )
    ).one()
    if any(role):
        raise UnsafeDatabaseConfiguration
    inherited_privilege = connection.scalar(
        text(
            """
            SELECT EXISTS (
                SELECT 1 FROM pg_roles
                 WHERE pg_has_role(current_user, oid, 'MEMBER')
                   AND (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb
                        OR rolreplication OR rolname IN (
                            'pg_read_server_files', 'pg_write_server_files',
                            'pg_execute_server_program'))
            )
            """
        )
    )
    if inherited_privilege:
        raise UnsafeDatabaseConfiguration
    if connection.scalar(text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")):
        raise UnsafeDatabaseConfiguration
    tables = connection.execute(
        text(
            """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                   pg_has_role(current_user, c.relowner, 'MEMBER') AS owns_table,
                   (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS policies
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public'
               AND c.relname IN ('businesses', 'users', 'memberships', 'customers')
               AND c.relkind = 'r'
            """
        )
    ).all()
    if len(tables) != 4 or any(
        not row.relrowsecurity or not row.relforcerowsecurity or row.owns_table or not row.policies
        for row in tables
    ):
        raise UnsafeDatabaseConfiguration
    policies = connection.execute(
        text(
            """
            SELECT c.relname, p.polname
              FROM pg_policy p
              JOIN pg_class c ON c.oid = p.polrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public'
               AND c.relname IN ('businesses', 'users', 'memberships', 'customers')
            """
        )
    ).all()
    expected_policies = {
        ("users", "users_read_self"),
        ("memberships", "memberships_read_self"),
        ("businesses", "businesses_read_member"),
        ("customers", "customers_read_member"),
        ("customers", "customers_insert_writer"),
        ("customers", "customers_update_writer"),
        ("customers", "customers_delete_writer"),
    }
    if {(row.relname, row.polname) for row in policies} != expected_policies:
        raise UnsafeDatabaseConfiguration
    for table in ("businesses", "users", "memberships"):
        if connection.scalar(
            text("SELECT has_table_privilege(current_user, :table, 'INSERT,UPDATE,DELETE')"),
            {"table": f"public.{table}"},
        ):
            raise UnsafeDatabaseConfiguration


def set_identity_context(session: Session, identity: VerifiedIdentity) -> None:
    session.execute(
        text(
            "SELECT set_config('app.issuer', :issuer, true), "
            "set_config('app.subject', :subject, true), "
            "set_config('app.tenant_id', '', true)"
        ),
        {"issuer": identity.issuer, "subject": identity.subject},
    )


def set_tenant_context(session: Session, tenant_id: UUID) -> None:
    session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )
