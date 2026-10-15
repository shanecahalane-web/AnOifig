"""Routing gateways retain FORCE RLS and cannot turn runtime writes into linking."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from conftest import ISSUER
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from anoifig.db.privileges import (
    GATEWAY_GUARD_FUNCTIONS,
    GATEWAY_TRIGGER_FUNCTIONS,
    RUNTIME_FUNCTIONS,
    UnsafeDatabaseConfiguration,
    check_runtime_functions,
)
from anoifig.db.session import check_runtime_database

pytestmark = pytest.mark.integration


def insert_pending_link(connection, seed):
    link_id = uuid4()
    connection.execute(
        text(
            "INSERT INTO phone_links(id,tenant_id,user_id,phone,issuer,subject,token_hash,"
            "expires_at) "
            "VALUES (:id,:tenant,:user,'+353860000091',:issuer,'owner-a',:digest,:expires)"
        ),
        {
            "id": link_id,
            "tenant": seed.businesses["a"],
            "user": seed.users["owner-a"],
            "issuer": ISSUER,
            "digest": "a" * 64,
            "expires": datetime.now(UTC) + timedelta(minutes=10),
        },
    )
    return link_id


def identity_context(connection, tenant):
    connection.execute(
        text(
            "SELECT set_config('app.issuer', :issuer, true), "
            "set_config('app.subject', 'owner-a', true), "
            "set_config('app.tenant_id', :tenant, true)"
        ),
        {"issuer": ISSUER, "tenant": str(tenant)},
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "verified_at = statement_timestamp()",
        "phone = '+353860000092'",
        "expires_at = expires_at + interval '1 day'",
        "token_hash = repeat('b', 64)",
        "subject = 'owner-b'",
    ],
)
def test_runtime_cannot_verify_or_replace_phone_link(database, seed, mutation):
    with database.admin.begin() as connection:
        link_id = insert_pending_link(connection, seed)
    with pytest.raises(IntegrityError), database.runtime.begin() as connection:
        identity_context(connection, seed.businesses["a"])
        connection.execute(text(f"UPDATE phone_links SET {mutation} WHERE id=:id"), {"id": link_id})


def test_runtime_cannot_insert_preverified_phone_link(database, seed):
    with pytest.raises(IntegrityError), database.runtime.begin() as connection:
        identity_context(connection, seed.businesses["a"])
        connection.execute(
            text(
                "INSERT INTO phone_links(id,tenant_id,user_id,phone,issuer,subject,token_hash,"
                "expires_at,verified_at) VALUES (:id,:tenant,:user,'+353860000093',:issuer,"
                "'owner-a',:digest,statement_timestamp()+interval '10 minutes',"
                "statement_timestamp())"
            ),
            {
                "id": uuid4(),
                "tenant": seed.businesses["a"],
                "user": seed.users["owner-a"],
                "issuer": ISSUER,
                "digest": "c" * 64,
            },
        )


@pytest.mark.parametrize(
    "statement",
    [
        "GRANT EXECUTE ON FUNCTION public.messaging_route_phone(text) TO PUBLIC",
        "GRANT EXECUTE ON FUNCTION public.messaging_index_inbound() TO {role}",
        "GRANT EXECUTE ON FUNCTION public.messaging_guard_phone_link() TO {role}",
        "GRANT EXECUTE ON FUNCTION public.messaging_lookup_job(uuid) TO {role} WITH GRANT OPTION",
        "ALTER FUNCTION public.messaging_route_phone(text) SECURITY INVOKER",
        "ALTER FUNCTION public.messaging_route_phone(text) SET search_path = public",
    ],
)
def test_function_privilege_or_security_drift_is_rejected(database, statement):
    with database.admin.connect() as connection:
        transaction = connection.begin()
        try:
            runtime_name = make_url(database.runtime_url).username
            role = connection.dialect.identifier_preparer.quote_identifier(runtime_name)
            connection.execute(text(statement.format(role=role)))
            with pytest.raises(UnsafeDatabaseConfiguration):
                check_runtime_functions(connection, role_name=runtime_name, require_expected=True)
        finally:
            transaction.rollback()


@pytest.mark.parametrize(
    "statement",
    [
        "ALTER TABLE public.messages DISABLE TRIGGER messaging_index_inbound",
        "DROP TRIGGER messaging_index_outbound ON public.outbox",
        "DROP TRIGGER messaging_guard_phone_link ON public.phone_links",
    ],
)
def test_missing_or_disabled_reliability_trigger_fails_readiness(database, statement):
    with database.admin.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(statement))
            role = connection.dialect.identifier_preparer.quote_identifier(
                make_url(database.runtime_url).username
            )
            connection.execute(text(f"SET LOCAL ROLE {role}"))
            with pytest.raises(UnsafeDatabaseConfiguration):
                check_runtime_database(connection)
            connection.execute(text("SET LOCAL ROLE NONE"))
        finally:
            transaction.rollback()


def test_gateways_work_for_non_superuser_metadata_owner_without_content_bypass(database, seed):
    # The *_test database is disposable. All role creation, ownership changes,
    # grants and records below roll back atomically, including on assertion failure.
    with database.admin.connect() as connection:
        transaction = connection.begin()
        try:
            link_id = insert_pending_link(connection, seed)
            conversation_id, message_id = uuid4(), uuid4()
            values = {
                "tenant": seed.businesses["a"],
                "user": seed.users["owner-a"],
                "link": link_id,
                "conversation": conversation_id,
                "message": message_id,
            }
            connection.execute(
                text(
                    "INSERT INTO conversations(id,tenant_id,phone_link_id,user_id) "
                    "VALUES (:conversation,:tenant,:link,:user)"
                ),
                values,
            )
            connection.execute(
                text(
                    "INSERT INTO messages(id,tenant_id,conversation_id,phone_link_id,user_id,"
                    "direction,body,account_sid) VALUES (:message,:tenant,:conversation,:link,"
                    ":user,'inbound','Gateway test','AC00000000000000000000000000000000')"
                ),
                values,
            )
            role = connection.dialect.identifier_preparer.quote_identifier(
                f"metadata_owner_test_{uuid4().hex}"
            )
            connection.execute(
                text(
                    f"CREATE ROLE {role} NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                )
            )
            connection.execute(text(f"GRANT USAGE,CREATE ON SCHEMA public TO {role}"))
            for table in ("phone_links", "message_jobs"):
                connection.execute(text(f"ALTER TABLE public.{table} OWNER TO {role}"))
            for function in RUNTIME_FUNCTIONS | GATEWAY_TRIGGER_FUNCTIONS | GATEWAY_GUARD_FUNCTIONS:
                connection.execute(text(f"ALTER FUNCTION public.{function} OWNER TO {role}"))
            connection.execute(
                text(
                    "GRANT SELECT ON businesses,users,memberships,conversations,messages,outbox "
                    f"TO {role}"
                )
            )
            connection.execute(text(f"SET LOCAL ROLE {role}"))
            assert connection.scalar(text("SELECT count(*) FROM public.messages")) == 0
            route = connection.execute(
                text("SELECT * FROM public.messaging_redeem_phone('+353860000091',:digest)"),
                {"digest": "a" * 64},
            ).one()
            assert route.link_id == link_id
            assert (
                connection.scalar(
                    text("SELECT link_id FROM public.messaging_route_phone('+353860000091')")
                )
                == link_id
            )
            assert (
                connection.scalar(text("SELECT job_id FROM public.messaging_discover_jobs(100)"))
                == message_id
            )
            assert connection.scalar(text("SELECT count(*) FROM public.messages")) == 0
            connection.execute(text("SET LOCAL ROLE NONE"))
        finally:
            transaction.rollback()
