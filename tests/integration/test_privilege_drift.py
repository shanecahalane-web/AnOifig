"""Rollback-only roles prove effective privilege drift cannot pass runtime checks."""

from collections.abc import Iterator
from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlalchemy import Connection, text

from anoifig.db import privileges
from anoifig.db.privileges import check_runtime_privileges, provision_runtime_grants
from anoifig.db.session import UnsafeDatabaseConfiguration, check_runtime_database

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class TemporaryRole:
    connection: Connection
    name: str
    identifier: str


@pytest.fixture
def bare_role(database) -> Iterator[TemporaryRole]:
    # CREATE ROLE and every grant remain uncommitted; rollback removes all changes,
    # even if a regression assertion fails. No LOGIN role or password is created.
    with database.admin.connect() as connection:
        transaction = connection.begin()
        name = f"privilege_test_{uuid4().hex}"
        identifier = connection.dialect.identifier_preparer.quote_identifier(name)
        try:
            connection.execute(
                text(
                    f"CREATE ROLE {identifier} NOLOGIN NOINHERIT NOSUPERUSER "
                    "NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                )
            )
            yield TemporaryRole(connection, name, identifier)
        finally:
            transaction.rollback()


@pytest.fixture
def runtime_role(bare_role: TemporaryRole) -> TemporaryRole:
    provision_runtime_grants(bare_role.connection, bare_role.name)
    return bare_role


def assert_runtime_rejected(role: TemporaryRole) -> None:
    connection = role.connection
    connection.execute(text(f"SET LOCAL ROLE {role.identifier}"))
    try:
        with pytest.raises(UnsafeDatabaseConfiguration):
            check_runtime_database(connection)
    finally:
        connection.execute(text("SET LOCAL ROLE NONE"))


def test_provisioning_adds_only_approved_missing_privileges(bare_role: TemporaryRole) -> None:
    connection = bare_role.connection
    with pytest.raises(UnsafeDatabaseConfiguration):
        check_runtime_privileges(connection, role_name=bare_role.name)
    provision_runtime_grants(connection, bare_role.name)
    # Provisioning is idempotent and the runtime path verifies the same contract.
    provision_runtime_grants(connection, bare_role.name)
    connection.execute(text(f"SET LOCAL ROLE {bare_role.identifier}"))
    check_runtime_database(connection)
    assert not connection.scalar(
        text("SELECT has_table_privilege(current_user, 'public.customers', 'TRUNCATE')")
    )
    connection.execute(text("SET LOCAL ROLE NONE"))


@pytest.mark.parametrize(
    "privilege,table",
    [
        ("TRUNCATE", "customers"),
        ("REFERENCES", "customers"),
        ("TRIGGER", "customers"),
        ("MAINTAIN", "customers"),
        ("INSERT", "businesses"),
        ("UPDATE", "users"),
        ("DELETE", "memberships"),
        ("TRUNCATE", "businesses"),
        ("TRIGGER", "memberships"),
    ],
)
def test_unexpected_table_privilege_is_rejected(
    runtime_role: TemporaryRole, privilege: str, table: str
) -> None:
    runtime_role.connection.execute(
        text(f"GRANT {privilege} ON public.{table} TO {runtime_role.identifier}")
    )
    assert_runtime_rejected(runtime_role)


@pytest.mark.parametrize(
    "privilege,column,table",
    [
        ("UPDATE", "legal_name", "businesses"),
        ("INSERT", "identity_provider_subject", "users"),
        ("REFERENCES", "user_id", "memberships"),
        ("REFERENCES", "name", "customers"),
    ],
)
def test_column_only_grants_cannot_bypass_table_contract(
    runtime_role: TemporaryRole, privilege: str, column: str, table: str
) -> None:
    runtime_role.connection.execute(
        text(f"GRANT {privilege} ({column}) ON public.{table} TO {runtime_role.identifier}")
    )
    assert_runtime_rejected(runtime_role)


@pytest.mark.parametrize(
    "grant",
    [
        "SELECT ON public.users",
        "INSERT ON public.customers",
        "SELECT (name) ON public.customers",
        "UPDATE (name) ON public.customers",
        "USAGE ON SCHEMA public",
        "CONNECT ON DATABASE {database}",
    ],
)
def test_delegation_of_allowed_privileges_is_rejected(
    runtime_role: TemporaryRole, grant: str
) -> None:
    connection = runtime_role.connection
    database = connection.dialect.identifier_preparer.quote_identifier(
        connection.scalar(text("SELECT current_database()"))
    )
    connection.execute(
        text(
            f"GRANT {grant.format(database=database)} TO "
            f"{runtime_role.identifier} WITH GRANT OPTION"
        )
    )
    assert_runtime_rejected(runtime_role)


@pytest.mark.parametrize("grantee", ["role", "PUBLIC"])
def test_effective_public_and_direct_truncate_grants_are_rejected(
    runtime_role: TemporaryRole, grantee: str
) -> None:
    target = runtime_role.identifier if grantee == "role" else "PUBLIC"
    runtime_role.connection.execute(text(f"GRANT TRUNCATE ON public.customers TO {target}"))
    assert_runtime_rejected(runtime_role)


@pytest.mark.parametrize("privilege", ["CREATE", "TEMP"])
@pytest.mark.parametrize("grantee", ["role", "PUBLIC"])
def test_effective_database_creation_privileges_are_rejected(
    runtime_role: TemporaryRole, privilege: str, grantee: str
) -> None:
    connection = runtime_role.connection
    database = connection.dialect.identifier_preparer.quote_identifier(
        connection.scalar(text("SELECT current_database()"))
    )
    target = runtime_role.identifier if grantee == "role" else "PUBLIC"
    connection.execute(text(f"GRANT {privilege} ON DATABASE {database} TO {target}"))
    assert_runtime_rejected(runtime_role)


@pytest.mark.parametrize("grantee", ["role", "PUBLIC"])
def test_public_schema_create_privileges_are_rejected(
    runtime_role: TemporaryRole, grantee: str
) -> None:
    target = runtime_role.identifier if grantee == "role" else "PUBLIC"
    runtime_role.connection.execute(text(f"GRANT CREATE ON SCHEMA public TO {target}"))
    assert_runtime_rejected(runtime_role)


@pytest.mark.parametrize(
    "statement,grant",
    [
        ("CREATE TABLE public.extra_table (id integer)", "SELECT ON public.extra_table"),
        ("CREATE VIEW public.extra_view AS SELECT 1 AS id", "SELECT ON public.extra_view"),
        ("CREATE SEQUENCE public.extra_sequence", "USAGE ON SEQUENCE public.extra_sequence"),
        ("CREATE SEQUENCE public.extra_sequence", "SELECT ON SEQUENCE public.extra_sequence"),
        ("CREATE SEQUENCE public.extra_sequence", "UPDATE ON SEQUENCE public.extra_sequence"),
    ],
)
def test_access_to_unapproved_public_relations_is_rejected(
    runtime_role: TemporaryRole, statement: str, grant: str
) -> None:
    runtime_role.connection.execute(text(statement))
    runtime_role.connection.execute(text(f"GRANT {grant} TO {runtime_role.identifier}"))
    assert_runtime_rejected(runtime_role)


def test_noninherited_switchable_role_membership_is_rejected(
    runtime_role: TemporaryRole,
) -> None:
    connection = runtime_role.connection
    group = connection.dialect.identifier_preparer.quote_identifier(f"group_{uuid4().hex}")
    connection.execute(text(f"CREATE ROLE {group} NOLOGIN"))
    connection.execute(text(f"GRANT TRUNCATE ON public.customers TO {group}"))
    connection.execute(text(f"GRANT {group} TO {runtime_role.identifier}"))
    assert_runtime_rejected(runtime_role)


@pytest.mark.parametrize("grantee", ["role", "PUBLIC"])
def test_provisioning_fails_before_adding_missing_grants_on_drift(
    bare_role: TemporaryRole, grantee: str
) -> None:
    connection = bare_role.connection
    target = bare_role.identifier if grantee == "role" else "PUBLIC"
    connection.execute(text(f"GRANT TRUNCATE ON public.customers TO {target}"))
    before = connection.execute(
        text("SELECT relname, relacl::text FROM pg_class WHERE relnamespace='public'::regnamespace")
    ).all()
    with pytest.raises(UnsafeDatabaseConfiguration):
        provision_runtime_grants(connection, bare_role.name)
    after = connection.execute(
        text("SELECT relname, relacl::text FROM pg_class WHERE relnamespace='public'::regnamespace")
    ).all()
    assert after == before
    assert connection.scalar(
        text("SELECT has_table_privilege(:role, 'public.customers', 'TRUNCATE')"),
        {"role": bare_role.name},
    )
    assert not connection.scalar(
        text("SELECT has_table_privilege(:role, 'public.customers', 'SELECT')"),
        {"role": bare_role.name},
    )


def test_missing_required_grant_fails_runtime_check(runtime_role: TemporaryRole) -> None:
    runtime_role.connection.execute(
        text(f"REVOKE DELETE ON public.customers FROM {runtime_role.identifier}")
    )
    assert_runtime_rejected(runtime_role)


def test_postcheck_failure_rolls_back_partial_grants_even_when_caught(
    bare_role: TemporaryRole, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = bare_role.connection
    original_check = check_runtime_privileges

    def failing_postcheck(connection, *, role_name=None, require_expected=True):
        if require_expected:
            # The grants have been applied before this simulated safety failure.
            assert connection.scalar(
                text("SELECT has_table_privilege(:role, 'public.customers', 'SELECT')"),
                {"role": bare_role.name},
            )
            raise UnsafeDatabaseConfiguration
        original_check(connection, role_name=role_name, require_expected=False)

    monkeypatch.setattr(privileges, "check_runtime_privileges", failing_postcheck)
    with pytest.raises(UnsafeDatabaseConfiguration):
        provision_runtime_grants(connection, bare_role.name)
    assert not connection.scalar(
        text("SELECT has_table_privilege(:role, 'public.customers', 'SELECT')"),
        {"role": bare_role.name},
    )
    assert not connection.scalar(
        text("SELECT has_schema_privilege(:role, 'public', 'USAGE')"),
        {"role": bare_role.name},
    )
