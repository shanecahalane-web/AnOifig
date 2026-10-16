"""Exercise RLS and constraints through raw SQL without application query filters."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from conftest import ISSUER
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from anoifig.db.privileges import provision_runtime_grants
from anoifig.db.session import UnsafeDatabaseConfiguration, check_runtime_database

pytestmark = pytest.mark.integration


def context(connection, subject="owner-a", tenant=None, issuer=ISSUER):
    connection.execute(
        text(
            "SELECT set_config('app.issuer', :issuer, true), "
            "set_config('app.subject', :subject, true), "
            "set_config('app.tenant_id', :tenant, true)"
        ),
        {"issuer": issuer, "subject": subject, "tenant": str(tenant) if tenant else ""},
    )


def test_runtime_role_is_nonowner_nonbypass_with_forced_rls(database):
    with database.runtime.connect() as connection:
        check_runtime_database(connection)
        attributes = connection.execute(
            text(
                "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole "
                "FROM pg_roles WHERE rolname=current_user"
            )
        ).one()
        assert tuple(attributes) == (False, False, False, False)
        tables = connection.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname IN ('businesses','users','memberships','customers') "
                "AND relnamespace='public'::regnamespace"
            )
        ).all()
        assert len(tables) == 4
        assert all(tuple(row) == (True, True) for row in tables)


def test_missing_identity_or_tenant_context_defaults_to_no_rows(database, seed):
    with database.runtime.begin() as connection:
        for table in ("customers", "users", "memberships", "businesses"):
            assert connection.execute(text(f"SELECT * FROM {table}")).all() == []
        context(connection, tenant=None)
        assert connection.execute(text("SELECT * FROM customers")).all() == []


def test_raw_query_without_filter_still_isolates_tenant(database, seed):
    with database.runtime.begin() as connection:
        context(connection, tenant=seed.businesses["a"])
        assert connection.execute(text("SELECT id FROM customers")).scalars().all() == [
            seed.customers["a"]
        ]
        assert connection.execute(text("SELECT id FROM users")).scalars().all() == [
            seed.users["owner-a"]
        ]
        assert connection.execute(text("SELECT id FROM businesses")).scalars().all() == [
            seed.businesses["a"]
        ]


@pytest.mark.parametrize("subject", ["owner-b", "revoked", "disabled", "outsider", "unknown"])
def test_setting_another_tenant_cannot_grant_membership(database, seed, subject):
    with database.runtime.begin() as connection:
        context(connection, subject, seed.businesses["a"])
        assert connection.execute(text("SELECT * FROM customers")).all() == []


def test_issuer_is_part_of_database_identity(database, seed):
    with database.runtime.begin() as connection:
        context(connection, tenant=seed.businesses["a"], issuer="https://other.example.test/")
        assert connection.execute(text("SELECT * FROM customers")).all() == []
        assert connection.execute(text("SELECT * FROM users")).all() == []


@pytest.mark.parametrize("subject", ["reader-a", "owner-b", "revoked", "disabled"])
def test_raw_insert_requires_active_writer_membership(database, seed, subject):
    with pytest.raises(DBAPIError), database.runtime.begin() as connection:
        context(connection, subject, seed.businesses["a"])
        connection.execute(
            text("INSERT INTO customers(id,tenant_id,name) VALUES (:id,:tenant,'Denied')"),
            {"id": uuid4(), "tenant": seed.businesses["a"]},
        )


@pytest.mark.parametrize(
    "operation", ["UPDATE customers SET name='Denied'", "DELETE FROM customers"]
)
def test_raw_update_and_delete_cannot_affect_other_tenants(database, seed, operation):
    with database.runtime.begin() as connection:
        context(connection, tenant=seed.businesses["a"])
        result = connection.execute(text(operation + " WHERE id=:id"), {"id": seed.customers["b"]})
        assert result.rowcount == 0
    with database.admin.connect() as connection:
        assert (
            connection.execute(
                text("SELECT name FROM customers WHERE id=:id"), {"id": seed.customers["b"]}
            ).scalar_one()
            == "Customer b"
        )


@pytest.mark.parametrize(
    "operation", ["UPDATE customers SET name='Denied'", "DELETE FROM customers"]
)
def test_read_only_cannot_mutate_even_own_tenant(database, seed, operation):
    with database.runtime.begin() as connection:
        context(connection, "reader-a", seed.businesses["a"])
        assert connection.execute(text(operation)).rowcount == 0


def test_customer_cannot_be_reparented_even_by_dual_member(database, seed):
    with pytest.raises(DBAPIError), database.runtime.begin() as connection:
        context(connection, "dual", seed.businesses["a"])
        connection.execute(
            text("UPDATE customers SET tenant_id=:other WHERE id=:id"),
            {"other": seed.businesses["b"], "id": seed.customers["a"]},
        )


def test_context_clears_on_commit_and_rollback_with_same_pooled_connection(database, seed):
    for rollback in (False, True):
        with database.runtime.connect() as connection:
            transaction = connection.begin()
            context(connection, tenant=seed.businesses["a"])
            pid = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
            assert connection.execute(text("SELECT count(*) FROM customers")).scalar_one() == 1
            transaction.rollback() if rollback else transaction.commit()
        with database.runtime.begin() as connection:
            assert connection.execute(text("SELECT pg_backend_pid()")).scalar_one() == pid
            assert connection.execute(text("SELECT count(*) FROM customers")).scalar_one() == 0


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO users(id, identity_provider_issuer,identity_provider_subject) VALUES (gen_random_uuid(),'https://fake','fake')",
        "UPDATE memberships SET role='owner'",
        "DELETE FROM businesses",
        "ALTER TABLE customers DISABLE ROW LEVEL SECURITY",
        "TRUNCATE customers",
        "CREATE TABLE public.unauthorised(id integer)",
    ],
)
def test_runtime_cannot_provision_escalate_or_change_schema(database, seed, statement):
    with pytest.raises(DBAPIError), database.runtime.begin() as connection:
        context(connection, tenant=seed.businesses["a"])
        connection.execute(text(statement))


def test_identity_and_membership_constraints(database, seed):
    for statement, values in (
        (
            "INSERT INTO users(id,identity_provider_issuer,identity_provider_subject) "
            "VALUES (:id,:issuer,'owner-a')",
            {"id": uuid4(), "issuer": ISSUER},
        ),
        (
            "UPDATE memberships SET role='platform_admin' WHERE user_id=:id",
            {"id": seed.users["reader-a"]},
        ),
        (
            "INSERT INTO customers(id,tenant_id,name) VALUES (:id,:tenant,'X')",
            {"id": uuid4(), "tenant": uuid4()},
        ),
        ("UPDATE customers SET name=' ' WHERE id=:id", {"id": seed.customers["a"]}),
    ):
        with pytest.raises(IntegrityError), database.admin.begin() as connection:
            connection.execute(text(statement), values)


def test_writer_update_sets_utc_timestamp(database, seed):
    with database.runtime.begin() as connection:
        context(connection, "staff-a", seed.businesses["a"])
        row = connection.execute(
            text(
                "UPDATE customers SET name='Updated' WHERE id=:id RETURNING created_at,updated_at"
            ),
            {"id": seed.customers["a"]},
        ).one()
        assert row.updated_at >= row.created_at
        assert row.updated_at.utcoffset().total_seconds() == 0


def test_unsafe_owner_runtime_rejected(database):
    with database.admin.connect() as connection, pytest.raises(UnsafeDatabaseConfiguration):
        check_runtime_database(connection)


def test_migration_matches_models_and_is_reversible(database):
    # All data is disposable; restore schema and grants before subsequent fixtures.
    with patch.dict("os.environ", {"ANOIFIG_MIGRATION_DATABASE_URL": database.admin_url}):
        config = Config("alembic.ini")
        command.check(config)
        command.downgrade(config, "base")
        with database.admin.connect() as connection:
            assert (
                connection.execute(text("SELECT to_regclass('public.customers')")).scalar_one()
                is None
            )
        command.upgrade(config, "head")
    with database.admin.begin() as connection:
        from sqlalchemy.engine import make_url

        provision_runtime_grants(connection, make_url(database.runtime_url).username)
