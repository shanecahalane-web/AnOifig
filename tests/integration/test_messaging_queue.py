"""Receipt-bound PostgreSQL claims coordinate workers without exposing content."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import UUID, uuid4

import pytest
import test_messaging as messaging_tests
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from test_messaging import (
    inbound_form,
    rows,
    set_context,
    signed_post,
    verify_link,
)

from anoifig.db.privileges import (
    GATEWAY_GUARD_FUNCTIONS,
    GATEWAY_TRIGGER_FUNCTIONS,
    RUNTIME_FUNCTIONS,
)
from anoifig.messaging.queue import PostgresWorkQueue, QueueDelivery

pytestmark = pytest.mark.integration
messaging_client = messaging_tests.messaging_client
provider = messaging_tests.provider
worker = messaging_tests.worker


def accept_messages(messaging_client, database, seed, bearer, count):
    """Accept one signed webhook, then clone synthetic source rows atomically."""
    verify_link(messaging_client, seed, bearer)
    assert signed_post(messaging_client, inbound_form()).status_code == 200
    original = rows(database, "messages")[0]
    identifiers = [original["id"], *(uuid4() for _ in range(count - 1))]
    if count > 1:
        with database.admin.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO messages(id,tenant_id,conversation_id,phone_link_id,user_id,"
                    "direction,body,twilio_sid,account_sid) "
                    "SELECT :id,tenant_id,conversation_id,phone_link_id,user_id,"
                    "direction,body,:sid,account_sid FROM messages WHERE id = :original"
                ),
                [
                    {"id": identifier, "sid": "SM" + uuid4().hex, "original": original["id"]}
                    for identifier in identifiers[1:]
                ],
            )
    return identifiers


def queue_for(messaging_client):
    return PostgresWorkQueue(messaging_client.app.state.engine, messaging_client.app.state.settings)


def expire_claims(database):
    with database.admin.begin() as connection:
        connection.execute(
            text("UPDATE message_jobs SET claim_until = now() - interval '1 second'")
        )


def test_hundred_locked_source_rows_do_not_starve_later_available_work(
    messaging_client, database, seed, bearer, worker, provider
):
    identifiers = accept_messages(messaging_client, database, seed, bearer, 101)
    old_ids, available_id = identifiers[:100], identifiers[100]
    with database.admin.begin() as connection:
        connection.execute(
            text("UPDATE messages SET available_at = now() - interval '1 hour' WHERE id != :id"),
            {"id": available_id},
        )
    # Hold the actual content rows, rather than only faking a worker no-op or
    # locking operational metadata. Queue claims themselves remain available.
    with database.admin.begin() as locked:
        assert (
            len(
                locked.execute(
                    text("SELECT id FROM messages WHERE id != :id FOR UPDATE"),
                    {"id": available_id},
                ).all()
            )
            == 100
        )
        assert worker.run_once() == 0
        assert worker.run_once() == 1
        available = rows(database, "messages", "WHERE id = :id", {"id": available_id})[0]
        assert available["processed_at"] is not None
        assert available["processing_attempts"] == 1
        old = rows(
            database, "messages", "WHERE id != :id AND direction = 'inbound'", {"id": available_id}
        )
        assert {message["id"] for message in old} == set(old_ids)
        assert all(message["processed_at"] is None for message in old)
        assert all(message["processing_attempts"] == 0 for message in old)
        assert provider.calls == []
        # The committed outbox is usable even while the older inputs stay locked.
        assert worker.run_once() == 1
        assert len(provider.calls) == 1


def test_crashed_claim_expires_and_old_receipt_cannot_release_new_delivery(
    messaging_client, database, seed, bearer
):
    [identifier] = accept_messages(messaging_client, database, seed, bearer, 1)
    queue = queue_for(messaging_client)
    [first] = queue.receive()
    assert first.id == identifier
    UUID(first.receipt)
    job = rows(database, "message_jobs")[0]
    assert job["claim_until"] - job["last_claimed_at"] == timedelta(seconds=120)
    assert queue.receive() == []
    # A distinct adapter represents a replacement process with no in-memory receipt.
    replacement = queue_for(messaging_client)
    expire_claims(database)
    [current] = replacement.receive()
    assert current.id == first.id and current.receipt != first.receipt
    queue.complete(first)
    queue.abandon(first)
    queue.complete(QueueDelivery(current.id, str(uuid4())))
    queue.complete(QueueDelivery(uuid4(), current.receipt))
    assert rows(database, "message_jobs")[0]["claim_token"] == UUID(current.receipt)
    assert replacement.receive() == []
    replacement.complete(current)
    assert rows(database, "message_jobs")[0]["claim_token"] is None
    [redelivered] = replacement.receive()
    assert redelivered.id == identifier
    assert redelivered.receipt not in {first.receipt, current.receipt}


def test_claim_order_fairness_cooldown_and_source_updates_preserve_receipts(
    messaging_client, database, seed, bearer
):
    identifiers = accept_messages(messaging_client, database, seed, bearer, 3)
    queue = queue_for(messaging_client)
    with database.runtime.begin() as connection:
        discovery = connection.execute(text("SELECT * FROM messaging_discover_jobs(100)")).all()
    [first] = queue.receive(1)
    assert first.id == discovery[0].job_id
    with database.admin.begin() as connection:
        connection.execute(
            text("UPDATE messages SET processing_error = 'synthetic' WHERE id = :id"),
            {"id": first.id},
        )
    assert rows(database, "message_jobs", "WHERE id = :id", {"id": first.id})[0][
        "claim_token"
    ] == UUID(first.receipt)
    with database.runtime.begin() as connection:
        visible = connection.execute(text("SELECT * FROM messaging_discover_jobs(100)")).all()
    assert {job.job_id for job in visible} == set(identifiers) - {first.id}
    queue.abandon(first)
    assert first.id not in {delivery.id for delivery in queue.receive()}
    expire_claims(database)
    # The original due ordering cannot put a repeatedly contended row ahead of
    # work which has never been tried; discover and claims use the same ordering.
    queue.complete(first)
    with database.admin.begin() as connection:
        connection.execute(
            text("UPDATE message_jobs SET last_claimed_at = NULL WHERE id != :id"),
            {"id": first.id},
        )
    assert [delivery.id for delivery in queue.receive()] == [
        *(job.job_id for job in visible),
        first.id,
    ]


def test_concurrent_pollers_claim_disjoint_work_without_waiting_for_locked_metadata(
    messaging_client, database, seed, bearer
):
    identifiers = accept_messages(messaging_client, database, seed, bearer, 25)
    start = Barrier(3)

    def receive():
        start.wait(timeout=10)
        return queue_for(messaging_client).receive(12)

    with database.admin.begin() as connection:
        locked_id = connection.scalar(
            text("SELECT id FROM message_jobs ORDER BY due_at, id LIMIT 1 FOR UPDATE")
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            first, second = executor.submit(receive), executor.submit(receive)
            start.wait(timeout=10)
            claimed = [first.result(timeout=20), second.result(timeout=20)]
        assert len(claimed[0]) == len(claimed[1]) == 12
        left, right = ({delivery.id for delivery in batch} for batch in claimed)
        assert left.isdisjoint(right)
        assert left | right == set(identifiers) - {locked_id}
    assert [delivery.id for delivery in queue_for(messaging_client).receive()] == [locked_id]


def test_claim_gateway_returns_only_receipts_and_retains_raw_runtime_rls(
    messaging_client, database, seed, bearer
):
    [identifier] = accept_messages(messaging_client, database, seed, bearer, 1)
    with database.runtime.begin() as connection:
        claimed = connection.execute(text("SELECT * FROM messaging_claim_jobs(100)"))
        assert list(claimed.keys()) == ["job_id", "receipt"]
        assert claimed.one().job_id == identifier
        assert connection.scalar(text("SELECT count(*) FROM messages")) == 0
        set_context(connection, seed, tenant="b", subject="owner-b")
        assert connection.scalar(text("SELECT count(*) FROM messages")) == 0
        set_context(connection, seed)
        assert connection.scalar(text("SELECT count(*) FROM messages")) == 1
    for statement in (
        "SELECT * FROM message_jobs",
        "UPDATE message_jobs SET claim_token = NULL",
        "SELECT body FROM messaging_claim_jobs(100)",
    ):
        with pytest.raises(DBAPIError), database.runtime.begin() as connection:
            connection.execute(text(statement))


def test_claim_and_release_work_with_non_superuser_owner_under_forced_rls(
    messaging_client, database, seed, bearer
):
    [identifier] = accept_messages(messaging_client, database, seed, bearer, 1)
    # Ownership and the role itself disappear in the rollback, even on failure.
    with database.admin.connect() as connection:
        transaction = connection.begin()
        try:
            quote = connection.dialect.identifier_preparer.quote_identifier
            owner = quote(f"queue_owner_test_{uuid4().hex}")
            runtime = quote(make_url(database.runtime_url).username)
            connection.execute(
                text(
                    f"CREATE ROLE {owner} NOLOGIN NOINHERIT NOSUPERUSER "
                    "NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                )
            )
            connection.execute(text(f"GRANT USAGE,CREATE ON SCHEMA public TO {owner}"))
            for table in ("phone_links", "message_jobs"):
                connection.execute(text(f"ALTER TABLE {table} OWNER TO {owner}"))
            for function in RUNTIME_FUNCTIONS | GATEWAY_TRIGGER_FUNCTIONS | GATEWAY_GUARD_FUNCTIONS:
                connection.execute(text(f"ALTER FUNCTION public.{function} OWNER TO {owner}"))
            connection.execute(
                text(
                    "GRANT SELECT ON businesses,users,memberships,"
                    f"conversations,messages,outbox TO {owner}"
                )
            )
            connection.execute(text(f"SET LOCAL ROLE {owner}"))
            assert connection.scalar(text("SELECT count(*) FROM messages")) == 0
            connection.execute(text(f"SET LOCAL ROLE {runtime}"))
            claim = connection.execute(text("SELECT * FROM messaging_claim_jobs(1)")).one()
            assert claim.job_id == identifier
            assert connection.scalar(text("SELECT count(*) FROM messages")) == 0
            assert connection.execute(text("SELECT * FROM messaging_claim_jobs(1)")).all() == []
            connection.execute(
                text("SELECT messaging_release_job(:job,:receipt,0)"),
                {"job": identifier, "receipt": claim.receipt},
            )
            again = connection.execute(text("SELECT * FROM messaging_claim_jobs(1)")).one()
            assert again.job_id == identifier and again.receipt != claim.receipt
            connection.execute(text("SET LOCAL ROLE NONE"))
        finally:
            transaction.rollback()
