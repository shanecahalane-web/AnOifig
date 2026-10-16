"""Sustained cross-tenant arrivals exercise the real PostgreSQL scheduler."""

import re
from concurrent.futures import ThreadPoolExecutor
from statistics import median
from threading import Barrier
from time import perf_counter
from uuid import UUID

import pytest
import test_messaging as messaging_tests
from sqlalchemy import text
from test_messaging import (
    OTHER_PHONE,
    PHONE,
    inbound_form,
    rows,
    set_context,
    signed_post,
    verify_link,
)

from anoifig.messaging.queue import PostgresWorkQueue
from anoifig.messaging.worker import MessagingWorker

pytestmark = pytest.mark.integration
messaging_client = messaging_tests.messaging_client
provider = messaging_tests.provider


@pytest.fixture
def sources(messaging_client, database, seed, bearer):
    """Create authorised routes through HTTP; retire the two fixture inputs.

    Load is cloned from these synthetic inputs so it still uses the real source
    constraints and queue-maintenance triggers, without thousands of HTTP calls.
    """
    for tenant, phone in (("a", PHONE), ("b", OTHER_PHONE)):
        verify_link(
            messaging_client, seed, bearer, tenant=tenant, subject=f"owner-{tenant}", phone=phone
        )
        assert signed_post(messaging_client, inbound_form(phone=phone)).status_code == 200
    originals = rows(database, "messages")
    with database.admin.begin() as connection:
        connection.execute(text("UPDATE messages SET processed_at = now(), status = 'processed'"))
    return {
        tenant: next(row["id"] for row in originals if row["tenant_id"] == seed.businesses[tenant])
        for tenant in ("a", "b")
    }


def arrive(database, source, count):
    # Each call commits a distinct transaction, and uses the statement clock:
    # new arrivals must really be newer than the preceding claim, not backdated
    # by a long-running fixture transaction's now().
    with database.admin.begin() as connection:
        return (
            connection.execute(
                text(
                    "INSERT INTO messages(id,tenant_id,conversation_id,phone_link_id,user_id,"
                    "direction,body,twilio_sid,account_sid,available_at) "
                    "SELECT gen_random_uuid(),m.tenant_id,m.conversation_id,m.phone_link_id,"
                    "m.user_id,'inbound',m.body,'SM' || replace(gen_random_uuid()::text,'-',''),"
                    "m.account_sid,"
                    "statement_timestamp() FROM messages m CROSS JOIN generate_series(1,:count) "
                    "WHERE m.id = :source RETURNING id"
                ),
                {"source": source, "count": count},
            )
            .scalars()
            .all()
        )


def queue_for(client):
    return PostgresWorkQueue(client.app.state.engine, client.app.state.settings)


def discover(database, limit=100):
    with database.runtime.begin() as connection:
        return (
            connection.execute(
                text("SELECT job_id FROM messaging_discover_jobs(:limit)"), {"limit": limit}
            )
            .scalars()
            .all()
        )


def expire(database, identifiers):
    with database.admin.begin() as connection:
        connection.execute(
            text(
                "UPDATE message_jobs SET claim_until = statement_timestamp() - interval '1 second' "
                "WHERE id = ANY(:ids)"
            ),
            {"ids": identifiers},
        )


def finish(database, seed, deliveries, *, tenant):
    """Settle queue-only load through the real runtime RLS and receipt gateway."""
    if not deliveries:
        return
    with database.runtime.begin() as connection:
        set_context(connection, seed, tenant=tenant, subject=f"owner-{tenant}")
        assert connection.execute(
            text(
                "UPDATE messages SET processed_at = statement_timestamp(),status = 'processed' "
                "WHERE id = ANY(:ids)"
            ),
            {"ids": [delivery.id for delivery in deliveries]},
        ).rowcount == len(deliveries)
        connection.execute(
            text(
                "SELECT messaging_release_job(job,receipt,0) FROM "
                "unnest(CAST(:ids AS uuid[]),CAST(:receipts AS uuid[])) AS d(job,receipt)"
            ),
            {
                "ids": [delivery.id for delivery in deliveries],
                "receipts": [UUID(delivery.receipt) for delivery in deliveries],
            },
        )


@pytest.mark.parametrize("recovery", ["retry", "expired_claim"])
def test_eligible_retry_gets_a_turn_in_every_batch_of_continuous_other_tenant_arrivals(
    messaging_client, database, seed, sources, recovery
):
    queue = queue_for(messaging_client)
    [retry_id] = arrive(database, sources["a"], 1)
    [previous] = queue.receive(1)
    with database.admin.begin() as connection:
        connection.execute(
            text(
                "UPDATE messages SET processing_attempts = 1,processing_error = 'synthetic_retry' "
                "WHERE id = :id"
            ),
            {"id": retry_id},
        )
    if recovery == "retry":
        queue.abandon(previous)
    expire(database, [retry_id])

    progress = []
    fresh_progress = []
    for _ in range(4):
        new_ids = arrive(database, sources["b"], 100)
        with database.admin.connect() as connection:
            assert connection.scalar(
                text(
                    "SELECT min(m.available_at) > j.last_claimed_at FROM messages m "
                    "CROSS JOIN message_jobs j WHERE m.id = ANY(:ids) AND j.id = :retry "
                    "GROUP BY j.last_claimed_at"
                ),
                {"ids": new_ids, "retry": retry_id},
            )
        expected = discover(database)
        batch = queue.receive(100)
        assert [delivery.id for delivery in batch] == expected
        assert len(batch) == 100
        progress.append(retry_id in {delivery.id for delivery in batch})
        fresh = [delivery for delivery in batch if delivery.id != retry_id]
        fresh_progress.append(len(fresh))
        finish(database, seed, fresh, tenant="b")
        current = next((delivery for delivery in batch if delivery.id == retry_id), None)
        if current is not None:
            # An old process cannot settle the newly recovered receipt.
            queue.complete(previous)
            assert rows(database, "message_jobs", "WHERE id = :id", {"id": retry_id})[0][
                "claim_token"
            ] == UUID(current.receipt)
            if recovery == "retry":
                queue.abandon(current)
            previous = current
        expire(database, [retry_id])
    # All four batches are measured, including when run against the old SQL.
    assert progress == [True] * 4, f"retry turns across four batches: {progress}"
    assert fresh_progress == [99] * 4


def test_fresh_messages_progress_while_hundreds_of_retries_keep_returning(
    messaging_client, database, seed, sources
):
    queue = queue_for(messaging_client)
    retry_ids = arrive(database, sources["a"], 400)
    # Four hundred previously attempted jobs form the older waiting population.
    previous = queue.receive(400)
    assert [delivery.id for delivery in previous] == sorted(retry_ids)
    expire(database, retry_ids)
    waiting = set()
    admitted_round = {}
    completed_round = {}
    retry_turns = 0
    for round_number in range(1, 9):
        if round_number <= 4:
            [new_id] = arrive(database, sources["b"], 1)
            waiting.add(new_id)
            admitted_round[new_id] = round_number
        assert len(discover(database)) == 100
        batch = queue.receive(100)
        assert len(batch) == 100
        fresh = [delivery for delivery in batch if delivery.id in waiting]
        finish(database, seed, fresh, tenant="b")
        for delivery in fresh:
            waiting.remove(delivery.id)
            completed_round[delivery.id] = round_number
        retry_turns += sum(delivery.id in retry_ids for delivery in batch)
        # These jobs remain contended or recover from another lease loss; every
        # claim must move their turn behind messages already waiting.
        expire(database, retry_ids)
    assert not waiting
    assert len(completed_round) == 4
    assert all(completed_round[id_] - admitted_round[id_] <= 4 for id_ in completed_round)
    assert retry_turns == 796


def test_concurrent_workers_recover_expiry_and_bypass_locked_rows_without_duplicate_sends(
    messaging_client, database, seed, sources, provider
):
    a_ids = arrive(database, sources["a"], 101)
    b_ids = arrive(database, sources["b"], 101)
    queue = queue_for(messaging_client)
    recovered_id = a_ids[-1]
    with database.admin.begin() as connection:
        connection.execute(
            text("UPDATE messages SET available_at = now() - interval '1 hour' WHERE id = :id"),
            {"id": recovered_id},
        )
    [lost_delivery] = queue.receive(1)
    assert lost_delivery.id == recovered_id
    expire(database, [recovered_id])

    def parallel_batches():
        start = Barrier(3)

        def run():
            replacement = MessagingWorker(
                messaging_client.app.state.engine, messaging_client.app.state.settings, provider
            )
            start.wait(timeout=10)
            return replacement.run_once()

        with ThreadPoolExecutor(max_workers=2) as executor:
            left, right = executor.submit(run), executor.submit(run)
            start.wait(timeout=10)
            return left.result(timeout=60) + right.result(timeout=60)

    locked_sources = a_ids[:100]
    with database.admin.begin() as connection:
        connection.execute(
            text("SELECT id FROM messages WHERE id = ANY(:ids) FOR UPDATE"),
            {"ids": locked_sources},
        ).all()
        connection.execute(
            text("SELECT id FROM message_jobs WHERE id = :id FOR UPDATE"), {"id": b_ids[0]}
        ).one()
        # Keep both source and metadata locks held across multiple complete
        # worker batches. No test stub replaces polling, claiming or processing.
        for _ in range(4):
            parallel_batches()
            expire(database, locked_sources)
        assert len(provider.calls) == 101  # tenant B's 100 unlocked inputs + A's recovered input
        assert all(
            message["processed_at"] is None
            for message in rows(
                database, "messages", "WHERE id = ANY(:ids)", {"ids": locked_sources}
            )
        )
        assert (
            rows(database, "messages", "WHERE id = :id", {"id": b_ids[0]})[0]["processed_at"]
            is None
        )
        assert (
            rows(database, "messages", "WHERE id = :id", {"id": recovered_id})[0][
                "processing_attempts"
            ]
            == 1
        )
    expire(database, locked_sources)
    for _ in range(12):
        # Source order can require another polling turn after a predecessor
        # settles. Advance the test's cooldowns after both workers have joined;
        # do not alter source retry times, receipts or external delivery state.
        with database.admin.begin() as connection:
            connection.execute(
                text(
                    "UPDATE message_jobs SET claim_until = now() - interval '1 second' "
                    "WHERE ready AND due_at <= now()"
                )
            )
        parallel_batches()
        if len(provider.calls) == 202:
            break
    queue.complete(lost_delivery)
    queue.abandon(lost_delivery)
    assert parallel_batches() == 0
    inputs = rows(database, "messages", "WHERE id = ANY(:ids)", {"ids": a_ids + b_ids})
    replies = rows(database, "messages", "WHERE direction = 'outbound'")
    assert len(inputs) == len(replies) == len(provider.calls) == 202
    assert all(message["processed_at"] is not None for message in inputs)
    assert {message["processing_attempts"] for message in inputs} == {1}
    assert {message["reply_to_id"] for message in replies} == set(a_ids + b_ids)
    assert len(set(provider.accepted_sids)) == 202
    assert {message["twilio_sid"] for message in replies} == set(provider.accepted_sids)
    assert {outbox["status"] for outbox in rows(database, "outbox")} == {"sent"}
    assert {outbox["attempts"] for outbox in rows(database, "outbox")} == {1}
    assert sum(call["to"] == "whatsapp:" + PHONE for call in provider.calls) == 101
    assert sum(call["to"] == "whatsapp:" + OTHER_PHONE for call in provider.calls) == 101
    for tenant in ("a", "b"):
        with database.runtime.begin() as connection:
            assert connection.scalar(text("SELECT count(*) FROM messages")) == 0
            set_context(connection, seed, tenant=tenant, subject=f"owner-{tenant}")
            visible = connection.execute(text("SELECT tenant_id FROM messages")).scalars().all()
            assert visible == [seed.businesses[tenant]] * 203
            other = "b" if tenant == "a" else "a"
            assert (
                connection.execute(
                    text("UPDATE messages SET status = 'failed' WHERE tenant_id = :other"),
                    {"other": seed.businesses[other]},
                ).rowcount
                == 0
            )
    with database.runtime.begin() as connection:
        set_context(connection, seed, tenant="a", subject="owner-b")
        assert connection.scalar(text("SELECT count(*) FROM messages")) == 0


def test_ready_turn_index_bounds_discovery_and_claim_cost_with_a_large_history(
    messaging_client, database, sources
):
    history = arrive(database, sources["a"], 16_000)
    future = arrive(database, sources["a"], 2_000)
    ready = arrive(database, sources["b"], 2_000)
    with database.admin.begin() as connection:
        connection.execute(
            text("UPDATE messages SET processed_at = now() WHERE id = ANY(:ids)"), {"ids": history}
        )
        connection.execute(
            text(
                "UPDATE messages SET available_at = now() + interval '1 day' WHERE id = ANY(:ids)"
            ),
            {"ids": future},
        )
        connection.execute(text("ANALYZE message_jobs"))
        connection.execute(text("SET LOCAL statement_timeout = '5s'"))
        # Explain the actual candidate SELECT stored in the claim function,
        # including SKIP LOCKED, rather than a separate benchmark-only query.
        source = connection.scalar(
            text(
                "SELECT prosrc FROM pg_proc "
                "WHERE oid = 'messaging_claim_jobs(integer)'::regprocedure"
            )
        )
        match = re.search(r"WITH candidates AS MATERIALIZED \((.*?)\), claimed AS", source, re.S)
        assert match is not None
        query = match.group(1).replace("batch_size", "100")
        explained = connection.scalar(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query))[0]

    def nodes(node):
        yield node
        for child in node.get("Plans", []):
            yield from nodes(child)

    plan = list(nodes(explained["Plan"]))
    assert "Sort" not in {node["Node Type"] for node in plan}
    [scan] = [node for node in plan if node.get("Index Name") == "ix_message_jobs_ready_turn"]
    assert scan["Actual Rows"] == 100
    assert scan["Rows Removed by Filter"] == 0
    assert "statement_timestamp()" in scan["Index Cond"]
    queue = queue_for(messaging_client)
    claimed = set()
    elapsed = []
    for _ in range(5):
        start = perf_counter()
        batch = queue.receive(100)
        elapsed.append((perf_counter() - start) * 1000)
        identifiers = {delivery.id for delivery in batch}
        assert len(identifiers) == 100
        assert identifiers <= set(ready)
        assert identifiers.isdisjoint(claimed)
        claimed.update(identifiers)
    assert len(claimed) == 500
    print(
        f"20,002 metadata rows; actual candidate plan: {explained['Execution Time']:.3f} ms, "
        f"100 index rows, no sort; five runtime 100-job claims: "
        f"median {median(elapsed):.2f} ms, max {max(elapsed):.2f} ms"
    )
