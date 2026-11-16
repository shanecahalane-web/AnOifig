"""Executable Phase 1 contract checks against signed ingress and PostgreSQL.

Expected failures expose missing architecture, not passing security guarantees.
Confirmation checks currently stop at the missing pending-proposal prerequisite.
"""

import json
import re
from copy import deepcopy

import pytest
from sqlalchemy import text
from test_messaging import OTHER_PHONE, rows, verify_link
from test_messaging_queue_fairness import arrive, queue_for
from test_messaging_queue_fairness import provider as provider
from test_messaging_queue_fairness import sources as sources
from test_tara import accept, make_worker
from test_tara import messaging_client as messaging_client
from test_tara_review_corrections import change, proposal

from anoifig.tara.schemas import InvoiceNotes

pytestmark = pytest.mark.integration


def established(messaging_client, database, seed, bearer):
    verify_link(messaging_client, seed, bearer)
    worker, ai = make_worker(messaging_client)
    assert worker.process_delivery(accept(messaging_client, "Hello"))
    # Synthetic previously saved notes, installed directly so the test does not
    # depend on the not-yet-implemented confirmation flow to establish them.
    with database.admin.begin() as connection:
        connection.execute(
            text("UPDATE tara_states SET notes = CAST(:notes AS jsonb), version = 7"),
            {"notes": json.dumps(InvoiceNotes(amount="600").model_dump(mode="json"))},
        )
    return worker, ai


def state(database):
    [value] = rows(database, "tara_states")
    return deepcopy(value)


def pending_preview(messaging_client, database, worker, ai):
    before = state(database)
    message = "Set amount €700"
    ai.results.append(proposal([change("amount", "700", message)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    after = state(database)
    # On this baseline this is the expected failure: canonical mutation occurs
    # before any confirmation. The remaining checks execute after that is fixed.
    assert (after["notes"], after["version"]) == (before["notes"], before["version"])
    [reply] = rows(database, "messages", "WHERE reply_to_id = :id", {"id": identifier})
    match = re.search(r"\bAPPLY ([0-9A-F]{32})\b", reply["body"])
    assert match is not None
    [outbox] = rows(database, "outbox", "WHERE message_id = :id", {"id": reply["id"]})
    # Synthetic provider acceptance, in this disposable database only.
    with database.admin.begin() as connection:
        connection.execute(
            text("UPDATE outbox SET status = 'sent' WHERE id = :id"), {"id": outbox["id"]}
        )
    return before, match.group(1)


@pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="unconfirmed model proposal mutates notes"
)
@pytest.mark.parametrize("message", ["Invoice awaiting payment €700", "Invoice overdue €700"])
@pytest.mark.parametrize("cropped", [False, True], ids=["full-evidence", "cropped-evidence"])
def test_status_message_cannot_change_saved_amount(
    message, cropped, messaging_client, database, seed, bearer
):
    worker, ai = established(messaging_client, database, seed, bearer)
    before = state(database)
    assert before["notes"]["amount"] == "600"
    ai.results.append(proposal([change("amount", "700", "700" if cropped else message)]))
    identifier = accept(messaging_client, message)
    assert worker.process_delivery(identifier)
    after = state(database)
    assert (after["notes"], after["version"]) == (before["notes"], before["version"])


@pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="pending proposal prerequisite not implemented"
)
def test_stale_confirmation_cannot_overwrite_newer_notes(messaging_client, database, seed, bearer):
    worker, ai = established(messaging_client, database, seed, bearer)
    before, token = pending_preview(messaging_client, database, worker, ai)
    with database.admin.begin() as connection:
        connection.execute(text("UPDATE tara_states SET version = version + 1"))
    updated = state(database)
    assert worker.process_delivery(accept(messaging_client, f"APPLY {token}"))
    after = state(database)
    assert after["notes"] == before["notes"]
    assert after["version"] == updated["version"]


@pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="pending proposal prerequisite not implemented"
)
def test_confirmed_proposal_is_consumed_once_on_replay(messaging_client, database, seed, bearer):
    worker, ai = established(messaging_client, database, seed, bearer)
    before, token = pending_preview(messaging_client, database, worker, ai)
    identifier = accept(messaging_client, f"APPLY {token}")
    assert worker.process_delivery(identifier)
    after = state(database)
    assert after["notes"]["amount"] == "700"
    assert after["version"] == before["version"] + 1
    assert worker.process_delivery(identifier)
    assert state(database)["notes"] == after["notes"]
    assert state(database)["version"] == after["version"]
    assert len(rows(database, "messages", "WHERE reply_to_id = :id", {"id": identifier})) == 1


@pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="pending proposal prerequisite not implemented"
)
def test_other_tenant_cannot_confirm_proposal(messaging_client, database, seed, bearer):
    worker, ai = established(messaging_client, database, seed, bearer)
    before, token = pending_preview(messaging_client, database, worker, ai)
    verify_link(messaging_client, seed, bearer, tenant="b", subject="owner-b", phone=OTHER_PHONE)
    identifier = accept(messaging_client, f"APPLY {token}", phone=OTHER_PHONE)
    assert worker.process_delivery(identifier)
    original = next(
        row for row in rows(database, "tara_states") if row["tenant_id"] == before["tenant_id"]
    )
    assert original["notes"] == before["notes"]
    assert original["version"] == before["version"]


@pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="queue claims blocked inbound successors"
)
def test_blocked_inbound_successor_does_not_take_runnable_tenant_turn(
    messaging_client, database, sources
):
    a1, a2 = arrive(database, sources["a"], 2)
    [b1] = arrive(database, sources["b"], 1)
    with database.admin.begin() as connection:
        connection.execute(
            text(
                "UPDATE messages SET received_at = now() - interval '2 hours', "
                "available_at = now() + interval '1 hour' WHERE id = :id"
            ),
            {"id": a1},
        )
        connection.execute(
            text(
                "UPDATE messages SET received_at = now() - interval '1 hour', "
                "available_at = now() - interval '2 hours' WHERE id = :id"
            ),
            {"id": a2},
        )
        connection.execute(
            text("UPDATE messages SET available_at = now() - interval '1 hour' WHERE id = :id"),
            {"id": b1},
        )
    [delivery] = queue_for(messaging_client).receive(1)
    assert delivery.id != a2, "blocked inbound successor consumed the only claim"
    assert delivery.id == b1


@pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="queue claims blocked outbound successors"
)
def test_blocked_outbound_successor_does_not_take_runnable_tenant_turn(
    messaging_client, database, sources, provider
):
    from anoifig.messaging.worker import MessagingWorker

    a1, a2 = arrive(database, sources["a"], 2)
    [b1] = arrive(database, sources["b"], 1)
    with database.admin.begin() as connection:
        connection.execute(
            text("UPDATE messages SET received_at = now() - interval '2 hours' WHERE id = :id"),
            {"id": a1},
        )
        connection.execute(
            text("UPDATE messages SET received_at = now() - interval '1 hour' WHERE id = :id"),
            {"id": a2},
        )
    worker = MessagingWorker(
        messaging_client.app.state.engine, messaging_client.app.state.settings, provider
    )
    for identifier in (a1, a2, b1):
        assert worker.process_delivery(identifier)
    replies = {
        row["reply_to_id"]: row["id"]
        for row in rows(database, "messages")
        if row["reply_to_id"] in (a1, a2, b1)
    }
    assert set(replies) == {a1, a2, b1}
    outboxes = {row["message_id"]: row["id"] for row in rows(database, "outbox")}
    with database.admin.begin() as connection:
        for source, interval in ((a1, "1 hour"), (a2, "-2 hours"), (b1, "-1 hour")):
            connection.execute(
                text(
                    "UPDATE outbox SET available_at = now() + CAST(:delay AS interval) "
                    "WHERE message_id = :id"
                ),
                {"id": replies[source], "delay": interval},
            )
    [delivery] = queue_for(messaging_client).receive(1)
    assert delivery.id != outboxes[replies[a2]], (
        "blocked outbound successor consumed the only claim"
    )
    assert delivery.id == outboxes[replies[b1]]
