"""The forward claim migration preserves messages accepted by revision 0002."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from conftest import ISSUER
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from anoifig.db.messaging_models import Conversation, Message, Outbox, PhoneLink
from anoifig.db.privileges import RUNTIME_TABLE_PRIVILEGES, provision_runtime_grants
from anoifig.db.session import check_runtime_database

pytestmark = pytest.mark.integration
TABLES = ("phone_links", "conversations", "messages", "outbox", "message_jobs")
CLAIM_COLUMNS = {"claim_token", "claim_until", "last_claimed_at"}


@contextmanager
def historical_schema(connection):
    """Validate historical revisions against their own table privilege contract.

    Production still requires every current table. Only these migration tests
    temporarily select the pre-Tara contract while intentionally downgrading.
    """
    if connection.scalar(text("SELECT to_regclass('public.tara_states')")) is not None:
        yield
        return
    historical = {
        name: rights
        for name, rights in RUNTIME_TABLE_PRIVILEGES.items()
        if not name.startswith("tara_")
    }
    with (
        patch("anoifig.db.privileges.RUNTIME_TABLE_PRIVILEGES", historical),
        patch("anoifig.db.session.RUNTIME_TABLE_PRIVILEGES", historical),
    ):
        yield


def check_migration_database(connection):
    with historical_schema(connection):
        check_runtime_database(connection)


def provision_migration_grants(connection, role):
    with historical_schema(connection):
        provision_runtime_grants(connection, role)


def snapshot(database, *, include_claims=False):
    with database.admin.connect() as connection:
        return {
            table: [
                {
                    key: value
                    for key, value in row.items()
                    if include_claims or key not in CLAIM_COLUMNS
                }
                for row in connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings()
            ]
            for table in TABLES
        }


def insert_revision_0002_records(database, seed):
    now = datetime.now(UTC)
    tenant, user, link_id, conversation_id = (
        seed.businesses["a"],
        seed.users["owner-a"],
        uuid4(),
        uuid4(),
    )
    common = {
        "tenant_id": tenant,
        "user_id": user,
        "phone_link_id": link_id,
        "conversation_id": conversation_id,
        "account_sid": "AC" + "a" * 32,
    }
    processed_id, pending_id, reply_id, outbox_id = (uuid4() for _ in range(4))
    with Session(database.admin) as session, session.begin():
        session.add(
            PhoneLink(
                id=link_id,
                tenant_id=tenant,
                user_id=user,
                phone="+353855550193",
                issuer=ISSUER,
                subject="owner-a",
                expires_at=now + timedelta(minutes=10),
                verified_at=now,
            )
        )
        session.flush()
        session.add(
            Conversation(
                id=conversation_id,
                tenant_id=tenant,
                user_id=user,
                phone_link_id=link_id,
                last_inbound_at=now,
            )
        )
        session.flush()
        session.add_all(
            [
                Message(
                    id=processed_id,
                    **common,
                    direction="inbound",
                    body="Earlier accepted text",
                    twilio_sid="SM" + uuid4().hex,
                    status="processed",
                    processed_at=now,
                    processing_attempts=1,
                ),
                Message(
                    id=pending_id,
                    **common,
                    direction="inbound",
                    body="Accepted before upgrade",
                    twilio_sid="SM" + uuid4().hex,
                    status="received",
                ),
            ]
        )
        session.flush()
        session.add(
            Message(
                id=reply_id,
                **common,
                direction="outbound",
                body="Committed reply",
                reply_to_id=processed_id,
                status="retry",
            )
        )
        session.flush()
        session.add(
            Outbox(
                id=outbox_id,
                tenant_id=tenant,
                message_id=reply_id,
                phone_link_id=link_id,
                status="retry",
                attempts=1,
                last_error="rate_limited",
            )
        )
    return {pending_id, outbox_id}


def test_upgrade_existing_0002_records_and_claim_downgrade_preserve_durable_state(database, seed):
    config = Config("alembic.ini")
    with patch.dict("os.environ", {"ANOIFIG_MIGRATION_DATABASE_URL": database.admin_url}):
        try:
            command.downgrade(config, "0002_whatsapp_messaging")
            expected_ready = insert_revision_0002_records(database, seed)
            before = snapshot(database)
            assert len(before["messages"]) == 3
            assert len(before["message_jobs"]) == 3
            assert len(before["outbox"]) == 1
            command.upgrade(config, "0003_messaging_queue_claims")
            assert snapshot(database) == before
            with database.admin.begin() as connection:
                provision_migration_grants(connection, make_url(database.runtime_url).username)
            with database.runtime.begin() as connection:
                check_migration_database(connection)
                claims = connection.execute(text("SELECT * FROM messaging_claim_jobs(100)")).all()
                assert {claim.job_id for claim in claims} == expected_ready
                assert connection.scalar(text("SELECT count(*) FROM messages")) == 0
            assert snapshot(database) == before

            # Rollback removes operational claims alone, retaining all accepted
            # content, outbox retry state and source-trigger-maintained metadata.
            command.downgrade(config, "0002_whatsapp_messaging")
            assert snapshot(database) == before
            with database.admin.connect() as connection:
                discovered = (
                    connection.execute(text("SELECT job_id FROM messaging_discover_jobs(100)"))
                    .scalars()
                    .all()
                )
                assert set(discovered) == expected_ready
                assert (
                    connection.scalar(
                        text("SELECT to_regprocedure('public.messaging_claim_jobs(integer)')")
                    )
                    is None
                )
            command.upgrade(config, "head")
            assert snapshot(database) == before
            with database.admin.connect() as connection:
                assert (
                    connection.execute(
                        text("SELECT claim_token,claim_until,last_claimed_at FROM message_jobs")
                    ).all()
                    == [(None, None, None)] * 3
                )
            command.check(config)
        finally:
            command.upgrade(config, "head")
            with database.admin.begin() as connection:
                provision_migration_grants(connection, make_url(database.runtime_url).username)


def security_snapshot(database):
    """Compare policies, owners and exact existing ACLs across function replacement."""
    with database.admin.connect() as connection:
        return (
            connection.execute(
                text(
                    "SELECT relname,relowner,relrowsecurity,relforcerowsecurity,relacl::text "
                    "FROM pg_class WHERE oid IN "
                    "('phone_links'::regclass,'conversations'::regclass,'messages'::regclass,"
                    "'outbox'::regclass,'message_jobs'::regclass) ORDER BY relname"
                )
            ).all(),
            connection.execute(
                text(
                    "SELECT tablename,policyname,permissive,roles,cmd,qual,with_check "
                    "FROM pg_policies "
                    "WHERE schemaname = 'public' AND tablename NOT LIKE 'tara_%' "
                    "ORDER BY tablename,policyname"
                )
            ).all(),
            connection.execute(
                text(
                    "SELECT oid,proname,proowner,proacl::text,prosecdef,proconfig,provolatile "
                    "FROM pg_proc WHERE pronamespace = 'public'::regnamespace ORDER BY oid"
                )
            ).all(),
        )


def test_fairness_upgrade_keeps_applied_0003_data_receipts_rls_and_grants(database, seed):
    config = Config("alembic.ini")
    with patch.dict("os.environ", {"ANOIFIG_MIGRATION_DATABASE_URL": database.admin_url}):
        try:
            command.downgrade(config, "0003_messaging_queue_claims")
            ready_ids = insert_revision_0002_records(database, seed)
            with database.runtime.begin() as connection:
                check_migration_database(connection)
                [delivery] = connection.execute(text("SELECT * FROM messaging_claim_jobs(1)")).all()
            before = snapshot(database, include_claims=True)
            security = security_snapshot(database)
            for target in ("head", "0003_messaging_queue_claims", "head"):
                if target == "head":
                    command.upgrade(config, target)
                    with database.admin.begin() as connection:
                        provision_runtime_grants(
                            connection, make_url(database.runtime_url).username
                        )
                else:
                    command.downgrade(config, target)
                assert snapshot(database, include_claims=True) == before
                assert security_snapshot(database) == security
                with database.runtime.begin() as connection:
                    # CREATE OR REPLACE retains the existing narrow EXECUTE
                    # grants. Tara tables receive their own reviewed grants above.
                    check_migration_database(connection)
                    discovered = (
                        connection.execute(text("SELECT job_id FROM messaging_discover_jobs(100)"))
                        .scalars()
                        .all()
                    )
                    assert set(discovered) == ready_ids - {delivery.job_id}
                    assert connection.scalar(text("SELECT count(*) FROM messages")) == 0
            with database.runtime.begin() as connection:
                connection.execute(
                    text("SELECT messaging_release_job(:id,:receipt,0)"),
                    {"id": delivery.job_id, "receipt": delivery.receipt},
                )
                assert (
                    set(
                        connection.execute(
                            text("SELECT job_id FROM messaging_claim_jobs(100)")
                        ).scalars()
                    )
                    == ready_ids
                )
                assert connection.scalar(text("SELECT count(*) FROM messages")) == 0
            command.check(config)
        finally:
            command.upgrade(config, "head")
            with database.admin.begin() as connection:
                provision_migration_grants(connection, make_url(database.runtime_url).username)
