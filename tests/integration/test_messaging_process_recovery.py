"""Real interpreter death/restart across durable messaging transaction boundaries.

Every child uses the actual restricted PostgreSQL role and a local provider
journal. No live HTTP provider, owner credential or production exit hook is used.
"""

import json
import os
import selectors
import signal
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from conftest import AUDIENCE, ISSUER
from sqlalchemy import text
from test_messaging import (
    ACCOUNT_SID,
    AUTH_TOKEN,
    INBOUND_URL,
    PHONE,
    SENDER,
    STATUS_URL,
    TARA_RESPONSE,
    inbound_form,
    rows,
    signed_post,
    verify_link,
)
from test_messaging import (
    messaging_client as messaging_client,
)

pytestmark = pytest.mark.integration
PROJECT = Path(__file__).resolve().parents[2]
HELPER = PROJECT / "tests" / "helpers" / "worker_process.py"


@contextmanager
def child_worker(database, journal, mode, *, form=None):
    # Strip inherited application configuration; in particular, no owner URL or
    # live provider secret is passed to this runtime-role-only interpreter.
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("ANOIFIG_")
    }
    environment["ANOIFIG_DATABASE_URL"] = database.runtime_url
    config = {
        "mode": mode,
        "journal": str(journal),
        "form": form,
        "settings": {
            "environment": "test",
            "database_pool_size": 1,
            "database_max_overflow": 0,
            "oidc_issuer": ISSUER,
            "oidc_audience": AUDIENCE,
            "oidc_jwks_url": ISSUER + ".well-known/jwks.json",
            "twilio_enabled": True,
            "twilio_account_sid": ACCOUNT_SID,
            "twilio_auth_token": AUTH_TOKEN,
            "twilio_whatsapp_number": SENDER,
            "twilio_inbound_url": INBOUND_URL,
            "twilio_status_url": STATUS_URL,
        },
    }
    process = subprocess.Popen(
        [sys.executable, str(HELPER)],
        cwd=PROJECT,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert process.stdin is not None
        process.stdin.write(json.dumps(config) + "\n")
        process.stdin.flush()
        yield process
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        if process.stdin is not None:
            process.stdin.close()
        if process.stdout is not None:
            process.stdout.close()


def child_event(process, expected):
    assert process.stdout is not None
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        assert selector.select(timeout=20), "Subprocess did not reach its bounded boundary"
    line = process.stdout.readline()
    assert line, f"Subprocess exited before reaching {expected}; status={process.poll()}"
    event = json.loads(line)
    assert event["event"] == expected, event
    assert event["pid"] == process.pid


def kill_at_boundary(process, expected):
    child_event(process, expected)
    process.kill()
    assert process.wait(timeout=10) == -signal.SIGKILL
    return process.pid


def restart_and_drain(database, journal, previous_pid, *, form=None):
    mode = "redeliver_and_drain" if form else "drain"
    with child_worker(database, journal, mode, form=form) as process:
        assert process.pid != previous_pid
        child_event(process, "done")
        assert process.wait(timeout=10) == 0


def accepted_calls(journal):
    if not journal.exists():
        return []
    return [json.loads(line) for line in journal.read_text().splitlines()]


def expire_crashed_claims(database, *, dispatch=False):
    # Advance persisted lease deadlines deterministically rather than waiting
    # two minutes. Claim tokens are retained, so recovery uses the real expiry path.
    with database.admin.begin() as connection:
        connection.execute(
            text(
                "UPDATE message_jobs SET claim_until = now() - interval '1 second' "
                "WHERE claim_until IS NOT NULL"
            )
        )
        if dispatch:
            connection.execute(text("UPDATE outbox SET lease_until = now() - interval '1 second'"))


def assert_single_sent_reply(database, journal, form):
    inbound = rows(database, "messages", "WHERE direction = 'inbound'")
    outbound = rows(database, "messages", "WHERE direction = 'outbound'")
    outbox = rows(database, "outbox")
    calls = accepted_calls(journal)
    assert len(inbound) == len(outbound) == len(outbox) == len(calls) == 1
    assert inbound[0]["twilio_sid"] == form["MessageSid"]
    assert inbound[0]["processed_at"] is not None
    assert inbound[0]["processing_attempts"] == 1
    assert outbound[0]["reply_to_id"] == inbound[0]["id"]
    assert outbound[0]["body"] == TARA_RESPONSE
    assert outbound[0]["twilio_sid"] == calls[0]["sid"]
    assert outbox[0]["message_id"] == outbound[0]["id"]
    assert outbox[0]["status"] == "sent"
    assert outbox[0]["attempts"] == 1
    assert calls[0]["to"] == "whatsapp:" + PHONE
    assert calls[0]["callback_url"] == STATUS_URL + "?attempt_id=" + str(outbox[0]["id"])
    assert not any(job["ready"] for job in rows(database, "message_jobs"))


def test_killed_ingress_process_preserves_accepted_work_for_fresh_worker(
    messaging_client, database, seed, bearer, tmp_path
):
    verify_link(messaging_client, seed, bearer)
    journal = tmp_path / "provider.jsonl"
    form = inbound_form()
    with child_worker(database, journal, "accept_then_wait", form=form) as process:
        killed_pid = kill_at_boundary(process, "inbound_accepted")
    assert len(rows(database, "messages")) == len(rows(database, "message_jobs")) == 1
    assert rows(database, "messages")[0]["processed_at"] is None
    assert rows(database, "outbox") == accepted_calls(journal) == []

    restart_and_drain(database, journal, killed_pid)
    assert_single_sent_reply(database, journal, form)


@pytest.mark.parametrize("boundary", ["before_commit", "after_commit"])
def test_killed_reply_transaction_recovers_atomic_reply_and_outbox(
    messaging_client, database, seed, bearer, tmp_path, boundary
):
    verify_link(messaging_client, seed, bearer)
    form = inbound_form()
    assert signed_post(messaging_client, form).status_code == 200
    journal = tmp_path / "provider.jsonl"
    mode, marker = (
        ("reply_before_commit", "reply_flushed_before_commit")
        if boundary == "before_commit"
        else ("reply_after_commit", "reply_outbox_committed")
    )
    with child_worker(database, journal, mode) as process:
        killed_pid = kill_at_boundary(process, marker)
    inbound = rows(database, "messages", "WHERE direction = 'inbound'")[0]
    if boundary == "before_commit":
        assert inbound["processed_at"] is None
        assert inbound["processing_attempts"] == 0
        assert len(rows(database, "messages")) == 1
        assert rows(database, "outbox") == []
    else:
        assert inbound["processed_at"] is not None
        assert len(rows(database, "messages")) == 2
        assert rows(database, "outbox")[0]["status"] == "pending"
        assert rows(database, "outbox")[0]["attempts"] == 0
    assert accepted_calls(journal) == []
    assert any(job["claim_token"] is not None for job in rows(database, "message_jobs"))
    expire_crashed_claims(database)

    restart_and_drain(database, journal, killed_pid)
    assert_single_sent_reply(database, journal, form)


def test_killed_provider_call_recovers_uncertain_without_second_provider_call(
    messaging_client, database, seed, bearer, tmp_path
):
    verify_link(messaging_client, seed, bearer)
    assert signed_post(messaging_client, inbound_form()).status_code == 200
    journal = tmp_path / "provider.jsonl"
    with child_worker(database, journal, "provider_accept_then_wait") as process:
        killed_pid = kill_at_boundary(process, "provider_accepted_before_result_commit")
    calls = accepted_calls(journal)
    assert len(calls) == 1
    outbox = rows(database, "outbox")[0]
    assert outbox["status"] == "dispatching"
    assert outbox["attempts"] == 1
    assert outbox["lease_until"] is not None
    outbound = rows(database, "messages", "WHERE direction = 'outbound'")[0]
    assert outbound["twilio_sid"] is None
    assert any(job["claim_token"] is not None for job in rows(database, "message_jobs"))
    expire_crashed_claims(database, dispatch=True)

    restart_and_drain(database, journal, killed_pid)
    recovered = rows(database, "outbox")[0]
    assert recovered["status"] == "uncertain"
    assert recovered["last_error"] == "dispatch_interrupted"
    assert recovered["attempts"] == 1
    assert recovered["lease_until"] is None
    outbound = rows(database, "messages", "WHERE direction = 'outbound'")[0]
    assert outbound["status"] == "uncertain"
    assert outbound["twilio_sid"] is None
    assert not any(job["ready"] for job in rows(database, "message_jobs"))
    assert accepted_calls(journal) == calls
    restart_and_drain(database, journal, killed_pid)
    assert accepted_calls(journal) == calls


def test_committed_inbound_with_lost_commit_response_deduplicates_after_process_restart(
    messaging_client, database, seed, bearer, tmp_path
):
    verify_link(messaging_client, seed, bearer)
    form = inbound_form()
    journal = tmp_path / "provider.jsonl"
    with child_worker(database, journal, "accept_commit_response_lost", form=form) as process:
        killed_pid = kill_at_boundary(process, "accepted_commit_response_lost")
    # The HTTP attempt received 503, but PostgreSQL really committed the message
    # and its trigger-maintained discovery row before the simulated response loss.
    assert len(rows(database, "messages")) == len(rows(database, "message_jobs")) == 1
    original_window = rows(database, "conversations")[0]["last_inbound_at"]
    assert rows(database, "outbox") == accepted_calls(journal) == []

    restart_and_drain(database, journal, killed_pid, form=form)
    assert rows(database, "conversations")[0]["last_inbound_at"] == original_window
    assert_single_sent_reply(database, journal, form)
    restart_and_drain(database, journal, killed_pid, form=form)
    assert_single_sent_reply(database, journal, form)
