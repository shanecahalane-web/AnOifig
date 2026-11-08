"""Real outbox ordering and bounded Tara recovery with offline provider transports."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from test_messaging import (
    ACCOUNT_SID,
    OTHER_PHONE,
    PHONE,
    FakeProvider,
    rows,
    signed_post,
    verify_link,
)
from test_messaging import messaging_client as _messaging_client
from test_tara import SCENARIOS, accept, make_worker, model_result, notes

from anoifig.messaging.provider import AmbiguousFailure, SafeRetry
from anoifig.messaging.service import lookup_job
from anoifig.messaging.worker import MAX_ATTEMPTS, MessagingWorker
from anoifig.tara.provider import MockAIProvider
from anoifig.tara.service import FALLBACK

messaging_client = _messaging_client
pytestmark = pytest.mark.integration


def outbox_for(database, inbound_id):
    return rows(
        database,
        "outbox",
        "WHERE message_id IN (SELECT id FROM messages WHERE reply_to_id = :id)",
        {"id": inbound_id},
    )[0]


def make_due(database, table, identifier):
    assert table in {"messages", "outbox"}
    with database.admin.begin() as connection:
        connection.execute(
            text(f"UPDATE {table} SET available_at = now() - interval '1 second' WHERE id = :id"),
            {"id": identifier},
        )


def prepare_price_turns(client, worker, ai, *, amounts=(450, 500, 600)):
    turns = [SCENARIOS[0]["turns"][0]]
    turns.extend(
        {
            "message": f"Actually make that €{amount} for the job.",
            "decision": {
                "proposal": {
                    "intent": "correction",
                    "changes": [
                        {"field": "amount", "value": str(amount), "evidence": f"€{amount}"}
                    ],
                    "line_items": None,
                    "line_items_evidence": None,
                }
            },
        }
        for amount in amounts[1:]
    )
    # Accept the full burst before processing any turn.
    inbound_ids = [accept(client, turn["message"]) for turn in turns]
    for identifier, turn in zip(inbound_ids, turns, strict=True):
        ai.results.append(model_result(turn["decision"]))
        assert worker.process_delivery(identifier)
    return inbound_ids


def restarted_worker(worker, provider=None):
    ai = MockAIProvider()
    restarted = MessagingWorker(
        worker.engine, worker.settings, provider or worker.provider, ai_provider=ai
    )
    return restarted, ai


def test_rate_limit_preserves_rapid_financial_correction_order_across_restart(
    messaging_client, database, seed, bearer
):
    verify_link(messaging_client, seed, bearer)
    worker, ai = make_worker(messaging_client)
    inbound_ids = prepare_price_turns(messaging_client, worker, ai)
    outboxes = [outbox_for(database, identifier) for identifier in inbound_ids]
    provider = worker.provider
    provider.failures.append(SafeRetry(retry_after=60))
    assert worker.process_delivery(outboxes[0]["id"])
    for index, later in enumerate(outboxes[1:], start=1):
        assert not worker.process_delivery(later["id"])
        assert outbox_for(database, inbound_ids[index])["attempts"] == 0
    assert len(provider.calls) == 1

    restarted, replacement_ai = restarted_worker(worker)
    make_due(database, "outbox", outboxes[0]["id"])
    assert not restarted.process_delivery(outboxes[2]["id"])
    for index, outbox in enumerate(outboxes):
        assert restarted.process_delivery(outbox["id"])
        if index == 0:
            assert not restarted.process_delivery(outboxes[2]["id"])
    for amount, call in zip((450, 450, 500, 600), provider.calls, strict=True):
        assert f"€{amount}" in call["body"]
    assert len(provider.accepted_sids) == 3
    assert len(set(provider.accepted_sids)) == 3
    assert replacement_ai.requests == []
    assert notes(database)["amount"] == "600"
    for outbox in outboxes:
        assert restarted.process_delivery(outbox["id"])
    assert len(provider.calls) == 4


def test_equal_inbound_times_use_uuid_ties_even_when_reply_creation_order_differs(
    messaging_client, database, seed, bearer
):
    verify_link(messaging_client, seed, bearer)
    worker, _ = make_worker(messaging_client)
    identifiers = sorted([accept(messaging_client, "Hello"), accept(messaging_client, "Hi")])
    accepted_at = datetime.now(UTC)
    with database.admin.begin() as connection:
        connection.execute(
            text("UPDATE messages SET received_at = :at WHERE direction = 'inbound'"),
            {"at": accepted_at},
        )
    for identifier in identifiers:
        assert worker.process_delivery(identifier)
    first, second = [outbox_for(database, identifier) for identifier in identifiers]
    with database.admin.begin() as connection:
        # Deliberately make reply timestamps contradict their source positions.
        connection.execute(
            text(
                "UPDATE messages SET received_at = :at + interval '10 minutes', body = 'first' "
                "WHERE id = :id"
            ),
            {"at": accepted_at, "id": first["message_id"]},
        )
        connection.execute(
            text("UPDATE messages SET received_at = :at, body = 'second' WHERE id = :id"),
            {"at": accepted_at, "id": second["message_id"]},
        )
    assert not worker.process_delivery(second["id"])
    assert worker.process_delivery(first["id"])
    assert worker.process_delivery(second["id"])
    assert [call["body"] for call in worker.provider.calls] == ["first", "second"]


def test_concurrent_dispatch_preparation_is_serialised_per_conversation(
    messaging_client, database, seed, bearer, monkeypatch
):
    verify_link(messaging_client, seed, bearer)
    worker, ai = make_worker(messaging_client)
    inbound_ids = prepare_price_turns(messaging_client, worker, ai, amounts=(450, 500))
    first, second = [outbox_for(database, identifier) for identifier in inbound_ids]
    checking, release = Event(), Event()
    original = worker._has_unresolved_predecessor

    def paused_check(session, message):
        if message.reply_to_id == inbound_ids[0] and not checking.is_set():
            checking.set()
            assert release.wait(10)
        return original(session, message)

    monkeypatch.setattr(worker, "_has_unresolved_predecessor", paused_check)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(worker.process_delivery, first["id"])
        try:
            assert checking.wait(10)
            assert not worker.process_delivery(second["id"])
            assert worker.provider.calls == []
        finally:
            release.set()
        assert pending.result(timeout=10)
    assert worker.process_delivery(second["id"])
    assert [
        "€450" in worker.provider.calls[0]["body"],
        "€500" in worker.provider.calls[1]["body"],
    ] == [True, True]


def test_inflight_send_gates_same_conversation_without_holding_a_database_lock(
    messaging_client, database, seed, bearer
):
    verify_link(messaging_client, seed, bearer)
    verify_link(messaging_client, seed, bearer, phone=OTHER_PHONE, subject="staff-a")
    started, release = Event(), Event()

    class BlockingProvider(FakeProvider):
        def send_text(self, **kwargs):
            if kwargs["to"] == "whatsapp:" + PHONE and not started.is_set():
                started.set()
                assert release.wait(10)
            return super().send_text(**kwargs)

    worker, ai = make_worker(messaging_client)
    worker.provider = BlockingProvider()
    inbound_ids = prepare_price_turns(messaging_client, worker, ai, amounts=(450, 500))
    other = accept(messaging_client, "Hello", phone=OTHER_PHONE)
    assert worker.process_delivery(other)
    first, second = [outbox_for(database, identifier) for identifier in inbound_ids]
    with ThreadPoolExecutor(max_workers=2) as pool:
        inflight = pool.submit(worker.process_delivery, first["id"])
        try:
            assert started.wait(10)
            assert not worker.process_delivery(second["id"])
            assert not worker.process_delivery(first["id"])
            # The other conversation can process and send during provider I/O.
            assert worker.process_delivery(outbox_for(database, other)["id"])
        finally:
            release.set()
        assert inflight.result(timeout=10)
    assert worker.process_delivery(second["id"])
    target_calls = [call for call in worker.provider.calls if call["to"] == "whatsapp:" + PHONE]
    assert len(target_calls) == 2
    assert "€450" in target_calls[0]["body"]
    assert "€500" in target_calls[1]["body"]


def test_uncertain_predecessor_waits_for_signed_callback_and_is_never_replayed(
    messaging_client, database, seed, bearer
):
    verify_link(messaging_client, seed, bearer)
    worker, ai = make_worker(messaging_client)
    inbound_ids = prepare_price_turns(messaging_client, worker, ai, amounts=(450, 500))
    first, second = [outbox_for(database, identifier) for identifier in inbound_ids]
    worker.provider.failures.append(AmbiguousFailure("transport_timeout"))
    assert worker.process_delivery(first["id"])
    assert outbox_for(database, inbound_ids[0])["status"] == "uncertain"
    restarted, replacement_ai = restarted_worker(worker)
    for _ in range(3):
        assert not restarted.process_delivery(second["id"])
        assert restarted.process_delivery(first["id"])
    assert len(worker.provider.calls) == 1
    assert (
        signed_post(
            messaging_client,
            {
                "AccountSid": ACCOUNT_SID,
                "MessageSid": "SM" + uuid4().hex,
                "MessageStatus": "delivered",
            },
            public_url=worker.provider.calls[0]["callback_url"],
        ).status_code
        == 204
    )
    assert restarted.process_delivery(second["id"])
    assert len(worker.provider.calls) == 2
    assert replacement_ai.requests == []


def test_exhausted_delivery_retries_release_the_next_reply(
    messaging_client, database, seed, bearer
):
    verify_link(messaging_client, seed, bearer)
    worker, ai = make_worker(messaging_client)
    inbound_ids = prepare_price_turns(messaging_client, worker, ai, amounts=(450, 500))
    first, second = [outbox_for(database, identifier) for identifier in inbound_ids]
    worker.provider.failures.extend(SafeRetry(retry_after=1) for _ in range(MAX_ATTEMPTS))
    for attempt in range(1, MAX_ATTEMPTS + 1):
        make_due(database, "outbox", first["id"])
        assert worker.process_delivery(first["id"])
        if attempt < MAX_ATTEMPTS:
            assert not worker.process_delivery(second["id"])
    assert outbox_for(database, inbound_ids[0])["status"] == "failed"
    assert outbox_for(database, inbound_ids[0])["attempts"] == MAX_ATTEMPTS
    assert worker.process_delivery(second["id"])
    assert outbox_for(database, inbound_ids[1])["status"] == "sent"
    assert len(worker.provider.calls) == MAX_ATTEMPTS + 1
    assert len(worker.provider.accepted_sids) == 1


def test_database_failures_before_reservation_are_bounded_and_release_the_next_turn(
    messaging_client, database, seed, bearer, monkeypatch, caplog
):
    verify_link(messaging_client, seed, bearer)
    worker, ai = make_worker(messaging_client)
    first = accept(messaging_client, "Hello")
    second = accept(messaging_client, "Hi again")
    original = worker.tara._prepare

    def fail_preparation(job):
        if job.entity_id == first:
            raise SQLAlchemyError("sensitive conversation and database details")
        return original(job)

    monkeypatch.setattr(worker.tara, "_prepare", fail_preparation)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        make_due(database, "messages", first)
        assert worker.process_delivery(first)
        message = rows(database, "messages", "WHERE id = :id", {"id": first})[0]
        assert message["processing_attempts"] == attempt
        if attempt < MAX_ATTEMPTS:
            assert message["available_at"] > datetime.now(UTC)
            assert message["processed_at"] is None
            assert not worker.process_delivery(second)
    assert (
        rows(database, "messages", "WHERE reply_to_id = :id", {"id": first})[0]["body"] == FALLBACK
    )
    assert ai.requests == []
    assert worker.process_delivery(second)
    assert len(ai.requests) == 1
    assert len(rows(database, "outbox")) == 2
    assert "sensitive" not in caplog.text and "database details" not in caplog.text


def test_preparation_errors_cannot_terminally_complete_a_later_inbound_turn(
    messaging_client, database, seed, bearer, monkeypatch
):
    verify_link(messaging_client, seed, bearer)
    worker, ai = make_worker(messaging_client)
    first = accept(messaging_client, "Hello")
    second = accept(messaging_client, "Hi again")
    original = worker.tara._prepare

    def fail_before_head_check(job):
        if job.entity_id == second:
            raise SQLAlchemyError("synthetic failure before conversation head check")
        return original(job)

    monkeypatch.setattr(worker.tara, "_prepare", fail_before_head_check)
    for _ in range(MAX_ATTEMPTS + 1):
        assert not worker.process_delivery(second)
    later = rows(database, "messages", "WHERE id = :id", {"id": second})[0]
    assert later["processing_attempts"] == 0
    assert later["processed_at"] is None
    assert rows(database, "tara_runs") == []
    assert rows(database, "outbox") == []
    assert ai.requests == []
    assert worker.process_delivery(first)
    for _ in range(MAX_ATTEMPTS):
        make_due(database, "messages", second)
        assert worker.process_delivery(second)
    assert rows(database, "messages", "WHERE id = :id", {"id": second})[0]["processed_at"]
    assert len(rows(database, "outbox")) == 2
    assert len(ai.requests) == 1


def test_completion_failure_preserves_run_and_reservation_without_repeating_ai(
    messaging_client, database, seed, bearer, monkeypatch
):
    verify_link(messaging_client, seed, bearer)
    worker, ai = make_worker(messaging_client)
    first = accept(messaging_client, "Hello")

    def fail_completion(*_args, **_kwargs):
        raise SQLAlchemyError("synthetic reply transaction failure")

    with monkeypatch.context() as patch:
        patch.setattr(worker.tara, "_complete", fail_completion)
        assert worker.process_delivery(first)
    assert len(ai.requests) == 1
    reservation = dict(rows(database, "tara_usage")[0])
    assert rows(database, "tara_runs")[0]["status"] == "processing"
    restarted, replacement_ai = restarted_worker(worker)
    make_due(database, "messages", first)
    assert not restarted.process_delivery(first)
    with database.admin.begin() as connection:
        connection.execute(text("UPDATE tara_runs SET expires_at = now() - interval '1 second'"))
    assert restarted.process_delivery(first)
    assert replacement_ai.requests == []
    assert dict(rows(database, "tara_usage")[0]) == reservation
    assert len(rows(database, "outbox")) == 1
    assert rows(database, "tara_runs")[0]["error_code"] == "processing_interrupted"


def test_retry_exhaustion_fences_a_previously_committed_run_and_late_result(
    messaging_client, database, seed, bearer, monkeypatch
):
    verify_link(messaging_client, seed, bearer)
    worker, ai = make_worker(messaging_client)
    first = accept(messaging_client, "Hello")
    second = accept(messaging_client, "Hi again")
    with Session(worker.engine) as session, session.begin():
        job = lookup_job(session, first)
    command = worker.tara._prepare(job)
    reservation = dict(rows(database, "tara_usage")[0])
    original = worker.tara._prepare

    def fail_preparation(job):
        if job.entity_id == first:
            raise SQLAlchemyError("synthetic database failure after committed reservation")
        return original(job)

    with monkeypatch.context() as patch:
        patch.setattr(worker.tara, "_prepare", fail_preparation)
        for _ in range(MAX_ATTEMPTS):
            make_due(database, "messages", first)
            assert worker.process_delivery(first)
    assert rows(database, "tara_runs")[0]["status"] == "complete"
    assert dict(rows(database, "tara_usage")[0]) == reservation
    assert ai.requests == []
    assert worker.tara._complete(command, MockAIProvider().respond(command.request), None)
    assert len(rows(database, "outbox")) == 1
    assert (
        rows(database, "messages", "WHERE reply_to_id = :id", {"id": first})[0]["body"] == FALLBACK
    )
    assert worker.process_delivery(second)
    assert len(ai.requests) == 1
    assert len(rows(database, "outbox")) == 2
