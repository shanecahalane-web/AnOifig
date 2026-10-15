"""The forward claim migration preserves messages accepted by revision 0002."""

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
from anoifig.db.privileges import provision_runtime_grants
from anoifig.db.session import check_runtime_database

pytestmark = pytest.mark.integration
TABLES = ("phone_links", "conversations", "messages", "outbox", "message_jobs")
CLAIM_COLUMNS = {"claim_token", "claim_until", "last_claimed_at"}


def snapshot(database):
    with database.admin.connect() as connection:
        return {
            table: [
                {key: value for key, value in row.items() if key not in CLAIM_COLUMNS}
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
                provision_runtime_grants(connection, make_url(database.runtime_url).username)
            with database.runtime.begin() as connection:
                check_runtime_database(connection)
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
                provision_runtime_grants(connection, make_url(database.runtime_url).username)
