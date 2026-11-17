"""Application-owned proposal confirmation through signed ingress and real RLS."""

import re

import pytest
from sqlalchemy import text
from test_messaging import rows
from test_phase1_contract_regressions import established, state
from test_tara import accept
from test_tara import messaging_client as messaging_client
from test_tara_review_corrections import change, proposal

pytestmark = pytest.mark.integration


def propose(client, database, worker, ai, value="700"):
    message = f"Set amount €{value}"
    ai.results.append(proposal([change("amount", value, message)]))
    source = accept(client, message)
    assert worker.process_delivery(source)
    [reply] = rows(database, "messages", "WHERE reply_to_id = :id", {"id": source})
    [outbox] = rows(database, "outbox", "WHERE message_id = :id", {"id": reply["id"]})
    match = re.search(r"APPLY ([0-9A-F]{32})", reply["body"])
    assert match is not None
    return source, reply, outbox, match.group(1)


def accept_preview(database, outbox):
    with database.admin.begin() as connection:
        connection.execute(
            text("UPDATE outbox SET status = 'sent' WHERE id = :id"), {"id": outbox["id"]}
        )


def test_defers_confirmation_until_preview_is_accepted(messaging_client, database, seed, bearer):
    worker, ai = established(messaging_client, database, seed, bearer)
    before = state(database)
    _, reply, outbox, token = propose(messaging_client, database, worker, ai)
    assert 'amount: "600" → "700"' in reply["body"]
    identifier = accept(messaging_client, f"APPLY {token}")
    count = len(ai.requests)
    assert not worker.process_delivery(identifier)
    assert not worker.process_delivery(identifier)
    [message] = rows(database, "messages", "WHERE id = :id", {"id": identifier})
    assert message["processing_attempts"] == 0
    assert not rows(database, "tara_runs", "WHERE message_id = :id", {"id": identifier})
    assert state(database)["notes"] == before["notes"]
    assert len(ai.requests) == count
    accept_preview(database, outbox)
    assert worker.process_delivery(identifier)
    assert state(database)["notes"]["amount"] == "700"
    assert state(database)["version"] == before["version"] + 1
    assert len(ai.requests) == count


@pytest.mark.parametrize(
    "action", ["expired", "rejected", "superseded", "preview_failed", "tampered"]
)
def test_ineligible_proposal_cannot_be_applied(action, messaging_client, database, seed, bearer):
    worker, ai = established(messaging_client, database, seed, bearer)
    before = state(database)
    _, _, outbox, token = propose(messaging_client, database, worker, ai)
    accept_preview(database, outbox)
    if action == "expired":
        with database.admin.begin() as connection:
            connection.execute(
                text(
                    "UPDATE tara_pending_proposals SET created_at = now() - interval '2 days', "
                    "expires_at = now() - interval '1 day'"
                )
            )
    elif action == "rejected":
        assert worker.process_delivery(accept(messaging_client, f"REJECT {token}"))
    elif action == "superseded":
        propose(messaging_client, database, worker, ai, "800")
    elif action == "preview_failed":
        with database.admin.begin() as connection:
            connection.execute(
                text("UPDATE messages SET status = 'undelivered' WHERE id = :id"),
                {"id": outbox["message_id"]},
            )
    else:
        with database.admin.begin() as connection:
            connection.execute(
                text(
                    "UPDATE tara_pending_proposals "
                    "SET after_notes = jsonb_set(after_notes, '{amount}', '\"800\"')"
                )
            )
    assert worker.process_delivery(accept(messaging_client, f"APPLY {token}"))
    assert state(database)["notes"] == before["notes"]
    assert state(database)["version"] == before["version"]
    [original] = rows(
        database, "tara_pending_proposals", "WHERE challenge = :token", {"token": token}
    )
    assert (
        original["status"]
        == {
            "expired": "expired",
            "rejected": "rejected",
            "superseded": "superseded",
            "preview_failed": "superseded",
            "tampered": "superseded",
        }[action]
    )


def test_proposal_rls_denies_other_user_and_tenant(messaging_client, database, seed, bearer):
    from test_messaging import set_context

    worker, ai = established(messaging_client, database, seed, bearer)
    propose(messaging_client, database, worker, ai)
    for tenant, subject in [("b", "owner-b"), ("a", "staff-a"), ("a", "reader-a")]:
        with database.runtime.begin() as connection:
            set_context(connection, seed, tenant=tenant, subject=subject)
            assert connection.scalar(text("SELECT count(*) FROM tara_pending_proposals")) == 0
            assert (
                connection.execute(
                    text("UPDATE tara_pending_proposals SET status = 'confirmed' RETURNING id")
                ).all()
                == []
            )


def test_lost_confirmation_commit_ack_does_not_repeat_mutation(
    messaging_client, database, seed, bearer, monkeypatch
):
    import psycopg

    worker, ai = established(messaging_client, database, seed, bearer)
    before = state(database)
    _, _, outbox, token = propose(messaging_client, database, worker, ai)
    accept_preview(database, outbox)
    identifier = accept(messaging_client, f"APPLY {token}")
    original = worker.engine.dialect.do_commit
    lost = False

    def commit_then_lose_ack(connection):
        nonlocal lost
        original(connection)
        if not lost and rows(database, "tara_pending_proposals")[0]["status"] == "confirmed":
            lost = True
            raise psycopg.OperationalError("synthetic lost commit acknowledgement")

    with monkeypatch.context() as context:
        context.setattr(worker.engine.dialect, "do_commit", commit_then_lose_ack)
        assert worker.process_delivery(identifier)
    assert lost
    assert worker.process_delivery(identifier)
    assert state(database)["notes"]["amount"] == "700"
    assert state(database)["version"] == before["version"] + 1
    assert len(rows(database, "messages", "WHERE reply_to_id = :id", {"id": identifier})) == 1
    assert rows(database, "tara_pending_proposals")[0]["status"] == "confirmed"


def test_reset_supersedes_pending_proposal(messaging_client, database, seed, bearer):
    worker, ai = established(messaging_client, database, seed, bearer)
    _, _, outbox, token = propose(messaging_client, database, worker, ai)
    accept_preview(database, outbox)
    assert worker.process_delivery(accept(messaging_client, "forget my notes"))
    cleared = state(database)
    assert cleared["notes"] == {}
    assert rows(database, "tara_pending_proposals")[0]["status"] == "superseded"
    assert worker.process_delivery(accept(messaging_client, f"APPLY {token}"))
    assert state(database)["notes"] == {}
    assert state(database)["version"] == cleared["version"]


def test_two_concurrent_confirmation_turns_apply_only_once(
    messaging_client, database, seed, bearer
):
    from concurrent.futures import ThreadPoolExecutor

    worker, ai = established(messaging_client, database, seed, bearer)
    before = state(database)
    _, _, outbox, token = propose(messaging_client, database, worker, ai)
    accept_preview(database, outbox)
    first = accept(messaging_client, f"APPLY {token}")
    second = accept(messaging_client, f"APPLY {token}")
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(worker.process_delivery, [first, second]))
    assert worker.process_delivery(first)
    assert worker.process_delivery(second)
    assert state(database)["notes"]["amount"] == "700"
    assert state(database)["version"] == before["version"] + 1
    assert rows(database, "tara_pending_proposals")[0]["status"] == "confirmed"
    for identifier in (first, second):
        assert len(rows(database, "messages", "WHERE reply_to_id = :id", {"id": identifier})) == 1


def test_other_member_cannot_confirm_proposal(messaging_client, database, seed, bearer):
    from test_messaging import OTHER_PHONE, verify_link

    worker, ai = established(messaging_client, database, seed, bearer)
    before = state(database)
    _, _, outbox, token = propose(messaging_client, database, worker, ai)
    accept_preview(database, outbox)
    verify_link(messaging_client, seed, bearer, phone=OTHER_PHONE, subject="staff-a")
    identifier = accept(messaging_client, f"APPLY {token}", phone=OTHER_PHONE)
    assert worker.process_delivery(identifier)
    original = next(
        row for row in rows(database, "tara_states") if row["user_id"] == before["user_id"]
    )
    assert original["notes"] == before["notes"]
    assert original["version"] == before["version"]
    assert rows(database, "tara_pending_proposals")[0]["status"] == "pending"


def test_revocation_before_final_authorisation_prevents_confirmation(
    messaging_client, database, seed, bearer, monkeypatch
):
    worker, ai = established(messaging_client, database, seed, bearer)
    before = state(database)
    _, _, outbox, token = propose(messaging_client, database, worker, ai)
    accept_preview(database, outbox)
    identifier = accept(messaging_client, f"APPLY {token}")
    original = worker.tara._authorise
    calls = 0

    def revoke_before_final_check(session, job):
        nonlocal calls
        calls += 1
        if calls == 2:
            with database.admin.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE memberships SET active = false "
                        "WHERE tenant_id = :tenant AND user_id = :user"
                    ),
                    {"tenant": seed.businesses["a"], "user": seed.users["owner-a"]},
                )
        return original(session, job)

    monkeypatch.setattr(worker.tara, "_authorise", revoke_before_final_check)
    assert worker.process_delivery(identifier)
    assert calls == 2
    assert state(database)["notes"] == before["notes"]
    assert state(database)["version"] == before["version"]
    [job] = rows(database, "message_jobs", "WHERE id = :id", {"id": identifier})
    assert job["last_error"] == "access_revoked"


def test_confirmation_challenge_is_not_replayed_to_model(messaging_client, database, seed, bearer):
    worker, ai = established(messaging_client, database, seed, bearer)
    _, _, outbox, token = propose(messaging_client, database, worker, ai)
    accept_preview(database, outbox)
    assert worker.process_delivery(accept(messaging_client, f"APPLY {token}"))
    assert worker.process_delivery(accept(messaging_client, "Hello again"))
    assert token not in ai.requests[-1].payload()
    assert "Set amount" not in str(ai.requests[-1].history)


def test_signed_callback_reconciles_uncertain_preview_before_confirmation(
    messaging_client, database, seed, bearer
):
    from uuid import uuid4

    from test_messaging import ACCOUNT_SID, signed_post

    from anoifig.messaging.delivery import callback_url

    worker, ai = established(messaging_client, database, seed, bearer)
    before = state(database)
    _, _, outbox, token = propose(messaging_client, database, worker, ai)
    with database.admin.begin() as connection:
        connection.execute(
            text("UPDATE outbox SET status = 'uncertain', attempts = 1 WHERE id = :id"),
            {"id": outbox["id"]},
        )
    identifier = accept(messaging_client, f"APPLY {token}")
    assert not worker.process_delivery(identifier)
    requests = len(ai.requests)
    response = signed_post(
        messaging_client,
        {"AccountSid": ACCOUNT_SID, "MessageSid": "SM" + uuid4().hex, "MessageStatus": "delivered"},
        public_url=callback_url(worker.settings.twilio_status_url, outbox["id"]),
    )
    assert response.status_code == 204
    assert worker.process_delivery(identifier)
    assert state(database)["notes"]["amount"] == "700"
    assert state(database)["version"] == before["version"] + 1
    assert len(ai.requests) == requests
    assert worker.provider.calls == []


@pytest.mark.parametrize("template", ["APPLY {} please", "apply {}", '"APPLY {}"', "{}"])
def test_malformed_confirmation_never_reaches_model_or_changes_notes(
    template, messaging_client, database, seed, bearer
):
    worker, ai = established(messaging_client, database, seed, bearer)
    before = state(database)
    _, _, outbox, token = propose(messaging_client, database, worker, ai)
    accept_preview(database, outbox)
    calls = len(ai.requests)
    assert worker.process_delivery(accept(messaging_client, template.format(token)))
    assert len(ai.requests) == calls
    assert state(database)["notes"] == before["notes"]
    assert state(database)["version"] == before["version"]
    assert worker.process_delivery(accept(messaging_client, "Hello again"))
    assert token not in ai.requests[-1].payload()


def test_version_change_while_waiting_for_preview_prevents_apply(
    messaging_client, database, seed, bearer, monkeypatch
):
    worker, ai = established(messaging_client, database, seed, bearer)
    before = state(database)
    _, _, outbox, token = propose(messaging_client, database, worker, ai)
    accept_preview(database, outbox)
    identifier = accept(messaging_client, f"APPLY {token}")
    original = worker.tara._authorise
    calls = 0

    def change_before_final_check(session, job):
        nonlocal calls
        calls += 1
        if calls == 2:
            with database.admin.begin() as connection:
                connection.execute(text("UPDATE tara_states SET version = version + 1"))
        return original(session, job)

    monkeypatch.setattr(worker.tara, "_authorise", change_before_final_check)
    assert worker.process_delivery(identifier)
    assert calls == 2
    assert state(database)["notes"] == before["notes"]
    assert state(database)["version"] == before["version"] + 1
    assert rows(database, "tara_pending_proposals")[0]["status"] == "superseded"


def test_failed_reply_commit_rolls_back_confirmation_and_retries_once(
    messaging_client, database, seed, bearer, monkeypatch
):
    from sqlalchemy.exc import SQLAlchemyError

    import anoifig.tara.service as tara_service

    worker, ai = established(messaging_client, database, seed, bearer)
    before = state(database)
    _, _, outbox, token = propose(messaging_client, database, worker, ai)
    accept_preview(database, outbox)
    identifier = accept(messaging_client, f"APPLY {token}")
    original = tara_service.reply_to_inbound

    def fail_reply(*args, **kwargs):
        raise SQLAlchemyError("synthetic reply insertion failure")

    with monkeypatch.context() as context:
        context.setattr(tara_service, "reply_to_inbound", fail_reply)
        assert worker.process_delivery(identifier)
    assert state(database)["notes"] == before["notes"]
    assert state(database)["version"] == before["version"]
    assert rows(database, "tara_pending_proposals")[0]["status"] == "pending"
    assert rows(database, "messages", "WHERE reply_to_id = :id", {"id": identifier}) == []
    assert tara_service.reply_to_inbound is original
    with database.admin.begin() as connection:
        connection.execute(
            text("UPDATE messages SET available_at = now() - interval '1 second' WHERE id = :id"),
            {"id": identifier},
        )
    assert worker.process_delivery(identifier)
    assert state(database)["notes"]["amount"] == "700"
    assert state(database)["version"] == before["version"] + 1
    assert len(rows(database, "messages", "WHERE reply_to_id = :id", {"id": identifier})) == 1
    assert worker.process_delivery(identifier)
    assert state(database)["version"] == before["version"] + 1


def test_stale_confirmation_does_not_clear_expired_memory(messaging_client, database, seed, bearer):
    worker, ai = established(messaging_client, database, seed, bearer)
    before = state(database)
    _, _, outbox, token = propose(messaging_client, database, worker, ai)
    accept_preview(database, outbox)
    with database.admin.begin() as connection:
        connection.execute(text("UPDATE tara_states SET memory_since = now() - interval '31 days'"))
    assert worker.process_delivery(accept(messaging_client, f"APPLY {token}"))
    assert state(database)["notes"] == before["notes"]
    assert state(database)["version"] == before["version"]
    assert rows(database, "tara_pending_proposals")[0]["status"] == "superseded"


def test_memory_expiring_while_waiting_cannot_be_confirmed(
    messaging_client, database, seed, bearer, monkeypatch
):
    worker, ai = established(messaging_client, database, seed, bearer)
    before = state(database)
    _, _, outbox, token = propose(messaging_client, database, worker, ai)
    accept_preview(database, outbox)
    identifier = accept(messaging_client, f"APPLY {token}")
    original = worker.tara._authorise
    calls = 0

    def expire_before_final_check(session, job):
        nonlocal calls
        calls += 1
        if calls == 2:
            with database.admin.begin() as connection:
                connection.execute(
                    text("UPDATE tara_states SET memory_since = now() - interval '31 days'")
                )
        return original(session, job)

    monkeypatch.setattr(worker.tara, "_authorise", expire_before_final_check)
    assert worker.process_delivery(identifier)
    assert calls == 2
    assert state(database)["notes"] == before["notes"]
    assert state(database)["version"] == before["version"]
    assert rows(database, "tara_pending_proposals")[0]["status"] == "superseded"
