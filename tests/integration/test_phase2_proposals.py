"""Application-owned proposal confirmation through signed ingress and real RLS."""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from test_messaging import link_path, rows
from test_phase1_contract_regressions import established, state
from test_tara import accept
from test_tara import messaging_client as messaging_client
from test_tara_review_corrections import change, proposal

import anoifig.messaging.routes as messaging_routes
import anoifig.tara.service as tara_service
from anoifig.messaging.worker import MAX_ATTEMPTS

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

    def revoke_before_final_check(session, job, **kwargs):
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
        return original(session, job, **kwargs)

    monkeypatch.setattr(worker.tara, "_authorise", revoke_before_final_check)
    assert worker.process_delivery(identifier)
    assert calls == 2
    assert state(database)["notes"] == before["notes"]
    assert state(database)["version"] == before["version"]
    [job] = rows(database, "message_jobs", "WHERE id = :id", {"id": identifier})
    assert job["last_error"] == "access_revoked"


@pytest.mark.parametrize("verb", ["APPLY", "REJECT"])
def test_confirmation_challenge_is_not_replayed_to_model(
    verb, messaging_client, database, seed, bearer
):
    worker, ai = established(messaging_client, database, seed, bearer)
    _, _, outbox, token = propose(messaging_client, database, worker, ai)
    accept_preview(database, outbox)
    requests = len(ai.requests)
    identifier = accept(messaging_client, f"{verb} {token}")
    assert worker.process_delivery(identifier)
    assert len(ai.requests) == requests
    [record] = rows(database, "tara_pending_proposals")
    assert record["status"] == ("confirmed" if verb == "APPLY" else "rejected")
    [inbound] = rows(database, "messages", "WHERE id = :id", {"id": identifier})
    assert token not in inbound["body"]
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


@pytest.mark.parametrize(
    "template",
    [
        "APPLY {}x",
        "REJECT x{}",
        "please APPLY x{}x",
        "APPLY_{}",
        "x{}x",
        "APPLY A{}F",
        "APPLY {} please",
        "apply {}",
        '"APPLY {}"',
        "{}",
        "APPLY",
        "REJECT bad-code",
        "Please REJECT Z8B1234567890QZ1234567890Z12345 again",
    ],
)
def test_malformed_confirmation_never_reaches_model_or_changes_notes(
    template, messaging_client, database, seed, bearer, caplog
):
    caplog.set_level(logging.INFO)
    worker, ai = established(messaging_client, database, seed, bearer)
    before = state(database)
    _, _, outbox, token = propose(messaging_client, database, worker, ai)
    accept_preview(database, outbox)
    calls = len(ai.requests)
    command = template.format(token)
    identifier = accept(messaging_client, command)
    [inbound] = rows(database, "messages", "WHERE id = :id", {"id": identifier})
    assert inbound["body"] != command
    assert worker.process_delivery(identifier)
    assert len(ai.requests) == calls
    assert state(database)["notes"] == before["notes"]
    assert state(database)["version"] == before["version"]
    assert rows(database, "tara_pending_proposals")[0]["status"] == "pending"
    [reply] = rows(database, "messages", "WHERE reply_to_id = :id", {"id": identifier})
    assert reply["body"] == "Please send the exact APPLY or REJECT command from the preview."
    assert worker.process_delivery(accept(messaging_client, "Hello again"))
    assert token not in ai.requests[-1].payload()
    assert token not in caplog.text


@pytest.mark.parametrize("verb", ["APPLY", "REJECT"])
@pytest.mark.parametrize(
    "template",
    [
        "{verb} {first} {last}",
        "\t{verb}\t{first}\n{last}\u00a0",
        "Please [{mixed}: ({first})-({last})] again.",
        "{verb}_{lower_first}.{lower_last}",
        "{mixed} {first} {last}x",
        "{verb} {first}:{middle}:{end}",
    ],
    ids=["two-halves", "whitespace", "quoted", "lowercase", "suffix", "three-groups"],
)
def test_grouped_confirmation_is_private_through_ingress_and_history(
    verb, template, messaging_client, database, seed, bearer, caplog
):
    caplog.set_level(logging.INFO)
    worker, ai = established(messaging_client, database, seed, bearer)
    before = state(database)
    _, _, outbox, token = propose(messaging_client, database, worker, ai)
    accept_preview(database, outbox)
    first, last = token[:16], token[16:]
    command = template.format(
        verb=verb,
        mixed=verb.title(),
        first=first,
        last=last,
        lower_first=first.lower(),
        lower_last=last.lower(),
        middle=last[:8],
        end=last[8:],
    )
    calls = len(ai.requests)
    identifier = accept(messaging_client, command)
    [accepted] = rows(database, "messages", "WHERE id = :id", {"id": identifier})
    assert worker.process_delivery(identifier)
    [processed] = rows(database, "messages", "WHERE id = :id", {"id": identifier})
    [reply] = rows(database, "messages", "WHERE reply_to_id = :id", {"id": identifier})
    after = state(database)
    assert (after["notes"], after["version"]) == (before["notes"], before["version"])
    assert rows(database, "tara_pending_proposals")[0]["status"] == "pending"

    live_requests = ai.requests[calls:]
    ordinary = "Apply VAT 23% to this invoice"
    assert worker.process_delivery(accept(messaging_client, ordinary))
    assert ai.requests[-1].message == ordinary
    assert {"role": "inbound", "text": "Hello"} in ai.requests[-1].history
    diagnostics = caplog.text
    assert {
        "raw body persisted at ingress": accepted["body"] == command,
        "raw body persisted after processing": processed["body"] == command,
        "model invoked for confirmation": bool(live_requests),
        "challenge replayed to model": first.lower() in ai.requests[-1].payload().lower(),
        "challenge logged": first.lower() in diagnostics.lower()
        or last.lower() in diagnostics.lower(),
    } == {
        "raw body persisted at ingress": False,
        "raw body persisted after processing": False,
        "model invoked for confirmation": False,
        "challenge replayed to model": False,
        "challenge logged": False,
    }
    assert accepted["body"] == processed["body"] == "[confirmation omitted]"
    assert reply["body"] == "Please send the exact APPLY or REJECT command from the preview."
    for secret in (first, last, last[:8], last[8:]):
        assert secret.lower() not in ai.requests[-1].payload().lower()


@pytest.mark.parametrize("form", ["contiguous", "split-apply", "split-reject"])
def test_legacy_confirmation_without_action_is_not_replayed(
    form, messaging_client, database, seed, bearer
):
    worker, ai = established(messaging_client, database, seed, bearer)
    _, _, _, token = propose(messaging_client, database, worker, ai)
    # Simulate a historical processed record with the old raw body and no tag.
    identifier = accept(messaging_client, f"APPLY {token}x")
    assert worker.process_delivery(identifier)
    if form == "contiguous":
        command = f"APPLY {token}x"
        note = f"Legacy work reference x{token}x"
    else:
        verb = form.removeprefix("split-").upper()
        command = f"{verb} {token[:16]} {token[16:]}"
        note = f"Copied preview reply: {command}"
    with database.admin.begin() as connection:
        connection.execute(
            text("UPDATE messages SET body = :body WHERE id = :id"),
            {"id": identifier, "body": command},
        )
        connection.execute(
            text("UPDATE tara_runs SET action = NULL WHERE message_id = :id"), {"id": identifier}
        )
        connection.execute(
            text(
                "UPDATE tara_states SET notes = "
                "jsonb_set(notes, '{work_description}', to_jsonb(CAST(:body AS text)))"
            ),
            {"body": note},
        )

    assert worker.process_delivery(accept(messaging_client, "Apply VAT 23%"))
    request = ai.requests[-1]
    assert request.message == "Apply VAT 23%"
    assert request.history == ({"role": "inbound", "text": "Hello"},)
    assert token[:16] not in request.payload()
    assert token[16:] not in request.payload()


@pytest.mark.parametrize("form", ["exact", "legacy-split-apply", "legacy-split-reject"])
def test_confirmation_terminal_fallback_does_not_replay_challenge(
    form, messaging_client, database, seed, bearer, monkeypatch, caplog
):
    caplog.set_level(logging.INFO)
    worker, ai = established(messaging_client, database, seed, bearer)
    before = state(database)
    _, _, outbox, token = propose(messaging_client, database, worker, ai)
    accept_preview(database, outbox)
    identifier = accept(messaging_client, f"APPLY {token}")
    command = f"APPLY {token}"
    if form != "exact":
        verb = form.removeprefix("legacy-split-").upper()
        command = f"{verb} {token[:16]} {token[16:]}"
        with database.admin.begin() as connection:
            connection.execute(
                text("UPDATE messages SET body = :body WHERE id = :id"),
                {"id": identifier, "body": command},
            )
    requests = len(ai.requests)
    failed = 0
    reply_to_inbound = tara_service.reply_to_inbound

    def fail_confirmation_reply(session, message, body, *, error_code, conversation_version):
        nonlocal failed
        if message.id == identifier and error_code is None:
            failed += 1
            raise SQLAlchemyError(f"synthetic reply insertion failure with challenge {command}")
        return reply_to_inbound(
            session, message, body, error_code=error_code, conversation_version=conversation_version
        )

    monkeypatch.setattr(tara_service, "reply_to_inbound", fail_confirmation_reply)
    for attempt in range(MAX_ATTEMPTS):
        if attempt:
            with database.admin.begin() as connection:
                connection.execute(
                    text("UPDATE messages SET available_at = now() WHERE id = :id"),
                    {"id": identifier},
                )
        assert worker.process_delivery(identifier)
    assert failed == MAX_ATTEMPTS
    assert len(ai.requests) == requests
    assert state(database)["notes"] == before["notes"]
    assert state(database)["version"] == before["version"]
    assert rows(database, "tara_pending_proposals")[0]["status"] == "pending"
    [reply] = rows(database, "messages", "WHERE reply_to_id = :id", {"id": identifier})
    assert reply["body"] == tara_service.FALLBACK
    [run] = rows(database, "tara_runs", "WHERE message_id = :id", {"id": identifier})
    assert run["error_code"] == "processing_failed"
    assert run["action"] == "proposal_unavailable"

    assert worker.process_delivery(accept(messaging_client, "Hello after recovery"))
    assert any(turn["text"] == "Hello" for turn in ai.requests[-1].history)
    [inbound] = rows(database, "messages", "WHERE id = :id", {"id": identifier})
    assert inbound["body"] == "[confirmation omitted]"
    for output in (ai.requests[-1].payload(), caplog.text, reply["body"]):
        assert token[:16] not in output
        assert token[16:] not in output
    assert inbound["processing_attempts"] == MAX_ATTEMPTS


@pytest.mark.parametrize("first", ["confirmation", "revocation"])
def test_confirmation_and_phone_revocation_serialize(
    first, messaging_client, database, seed, bearer, monkeypatch
):
    worker, ai = established(messaging_client, database, seed, bearer)
    before = state(database)
    _, _, outbox, token = propose(messaging_client, database, worker, ai)
    accept_preview(database, outbox)
    identifier = accept(messaging_client, f"APPLY {token}")
    [link] = rows(database, "phone_links")
    started = {"confirmation": Event(), "revocation": Event()}
    first_locked = Event()
    release_first = Event()
    pids = {}
    authorise = worker.tara._authorise
    revoke = messaging_routes.revoke_link
    checks = 0

    def reached(kind, session):
        pids[kind] = session.scalar(text("SELECT pg_backend_pid()"))
        started[kind].set()

    def hold_first(kind):
        if kind == first:
            first_locked.set()
            assert release_first.wait(10)

    def check_confirmation(session, job, **kwargs):
        nonlocal checks
        checks += 1
        if checks != 2:
            return authorise(session, job, **kwargs)
        reached("confirmation", session)
        authorise(session, job, **kwargs)
        hold_first("confirmation")

    def revoke_phone(session, identity, tenant_id, link_id):
        reached("revocation", session)
        revoke(session, identity, tenant_id, link_id)
        session.flush()
        hold_first("revocation")

    def unlink():
        return messaging_client.delete(
            f"{link_path(seed)}/{link['id']}", headers=bearer("owner-a")
        ).status_code

    monkeypatch.setattr(worker.tara, "_authorise", check_confirmation)
    monkeypatch.setattr(messaging_routes, "revoke_link", revoke_phone)
    operations = {
        "confirmation": lambda: worker.process_delivery(identifier),
        "revocation": unlink,
    }
    second = "revocation" if first == "confirmation" else "confirmation"
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_result = pool.submit(operations[first])
        try:
            assert first_locked.wait(5)
            second_result = pool.submit(operations[second])
            assert started[second].wait(5)
            assert pids[first] != pids[second]
            deadline = monotonic() + 3
            with database.admin.connect() as connection:
                while not second_result.done() and monotonic() < deadline:
                    blockers = connection.scalar(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": pids[second]}
                    )
                    if pids[first] in blockers:
                        break
                    release_first.wait(0.01)
                else:
                    blockers = []
        finally:
            release_first.set()
        outcomes = {first: first_result.result(10), second: second_result.result(10)}
    assert outcomes == {"confirmation": True, "revocation": 204}
    assert rows(database, "phone_links")[0]["revoked_at"] is not None
    [proposal_row] = rows(database, "tara_pending_proposals")
    after = state(database)
    if first == "confirmation":
        assert after["notes"]["amount"] == "700"
        assert after["version"] == before["version"] + 1
        assert proposal_row["status"] == "confirmed"
    else:
        assert (after["notes"], after["version"]) == (before["notes"], before["version"])
        assert proposal_row["status"] == "pending"
        [job] = rows(database, "message_jobs", "WHERE id = :id", {"id": identifier})
        assert job["last_error"] == "access_revoked"
        assert rows(database, "messages", "WHERE reply_to_id = :id", {"id": identifier}) == []
    assert pids[first] in blockers


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

    def change_before_final_check(session, job, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            with database.admin.begin() as connection:
                connection.execute(text("UPDATE tara_states SET version = version + 1"))
        return original(session, job, **kwargs)

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

    def expire_before_final_check(session, job, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            with database.admin.begin() as connection:
                connection.execute(
                    text("UPDATE tara_states SET memory_since = now() - interval '31 days'")
                )
        return original(session, job, **kwargs)

    monkeypatch.setattr(worker.tara, "_authorise", expire_before_final_check)
    assert worker.process_delivery(identifier)
    assert calls == 2
    assert state(database)["notes"] == before["notes"]
    assert state(database)["version"] == before["version"]
    assert rows(database, "tara_pending_proposals")[0]["status"] == "superseded"
