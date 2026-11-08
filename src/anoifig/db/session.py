"""Runtime connections and transaction-scoped PostgreSQL security context."""

from uuid import UUID

from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.orm import Session

from anoifig.config import Settings
from anoifig.db.connection_config import (
    UnsafeDatabaseTransport,
    database_connect_args,
    validate_database_url,
    verify_database_tls,
)
from anoifig.db.privileges import (
    RUNTIME_TABLE_PRIVILEGES,
    check_runtime_privileges,
)
from anoifig.db.privileges import (
    UnsafeDatabaseConfiguration as UnsafeDatabaseConfiguration,
)
from anoifig.identity.auth import VerifiedIdentity


def build_engine(settings: Settings) -> Engine:
    return create_engine(
        validate_database_url(settings.database_url.get_secret_value(), settings.environment),
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_connect_timeout,
        pool_recycle=1800,
        connect_args={
            **database_connect_args(
                settings.environment, timeout=settings.database_connect_timeout
            ),
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
    if require_tls:
        try:
            verify_database_tls(connection, "production")
        except UnsafeDatabaseTransport:
            raise UnsafeDatabaseConfiguration from None
    check_runtime_privileges(connection)
    tables = connection.execute(
        text(
            """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                   pg_has_role(current_user, c.relowner, 'MEMBER') AS owns_table,
                   (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS policies
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public'
               AND c.relname = ANY(:tables)
               AND c.relkind = 'r'
            """
        ),
        {"tables": list(RUNTIME_TABLE_PRIVILEGES)},
    ).all()
    if len(tables) != len(RUNTIME_TABLE_PRIVILEGES) or any(
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
               AND c.relname = ANY(:tables)
            """
        ),
        {"tables": list(RUNTIME_TABLE_PRIVILEGES)},
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
    expected_policies |= {
        (table, f"{table}_{action}")
        for table in (
            "phone_links",
            "conversations",
            "messages",
            "outbox",
            "tara_states",
            "tara_runs",
            "tara_usage",
        )
        if table in RUNTIME_TABLE_PRIVILEGES
        for action in ("read_member", "insert_writer", "update_writer")
    }
    expected_policies |= {
        ("phone_links", "phone_links_gateway_owner"),
        ("message_jobs", "message_jobs_gateway_owner"),
    }
    if {(row.relname, row.polname) for row in policies} != expected_policies:
        raise UnsafeDatabaseConfiguration
    triggers = connection.execute(
        text(
            """
            SELECT c.relname, t.tgname, t.tgtype, t.tgenabled, p.proname
              FROM pg_trigger t
              JOIN pg_class c ON c.oid = t.tgrelid
              JOIN pg_proc p ON p.oid = t.tgfoid
             WHERE c.relnamespace = 'public'::regnamespace
               AND c.relname = ANY(:tables) AND NOT t.tgisinternal
            """
        ),
        {"tables": ["phone_links", "conversations", "messages", "outbox"]},
    ).all()
    # tgtype: ROW=1, BEFORE=2, INSERT=4, UPDATE=16. Index updates must
    # run after source writes, while validation runs before inserts/updates.
    expected_triggers = {
        (table, "touch_updated_at", 19, "O", "touch_updated_at")
        for table in ("phone_links", "conversations", "messages", "outbox")
    }
    expected_triggers |= {
        ("phone_links", "messaging_guard_phone_link", 23, "O", "messaging_guard_phone_link"),
        ("messages", "messaging_index_inbound", 21, "O", "messaging_index_inbound"),
        ("outbox", "messaging_index_outbound", 21, "O", "messaging_index_outbound"),
    }
    if {tuple(row) for row in triggers} != expected_triggers:
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
