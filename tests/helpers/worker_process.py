"""Test-only subprocess harness; runtime DSN uses the environment, never argv.

The only provider is a local, fsynced journal. Barriers let the parent SIGKILL
this interpreter at real transaction boundaries without production exit hooks.
"""

import fcntl
import json
import os
import select
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from anoifig.api.main import create_app
from anoifig.config import Settings
from anoifig.db.session import build_engine
from anoifig.messaging.provider import SendResult
from anoifig.messaging.worker import MessagingWorker


def emit(event, **values):
    print(json.dumps({"event": event, "pid": os.getpid(), **values}), flush=True)


def barrier(event):
    emit(event)
    # A lost parent must not leave a subprocess or open transaction indefinitely.
    select.select([sys.stdin], [], [], 30)
    raise RuntimeError("Parent did not terminate the transaction-boundary subprocess")


class JournalProvider:
    """A process-safe record of synthetic provider acceptance, with no HTTP."""

    def __init__(self, path, *, wait_after_acceptance=False):
        self.path = Path(path)
        self.wait_after_acceptance = wait_after_acceptance

    def send_text(self, *, to, body, callback_url):
        sid = "SM" + uuid4().hex
        record = (
            json.dumps({"sid": sid, "to": to, "body": body, "callback_url": callback_url}).encode()
            + b"\n"
        )
        descriptor = os.open(self.path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            with os.fdopen(descriptor, "ab", closefd=False) as journal:
                journal.write(record)
                journal.flush()
                os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if self.wait_after_acceptance:
            # Acceptance survives SIGKILL, but the caller never receives the SID.
            # This models a provider receiving the request before its connection
            # drops, without adding an exit hook to the production worker.
            barrier("provider_accepted_before_result_commit")
        return SendResult(sid=sid, status="queued")


def signed_inbound(client, settings, form):
    assert settings.twilio_auth_token is not None
    assert settings.twilio_inbound_url is not None
    signature = RequestValidator(settings.twilio_auth_token.get_secret_value()).compute_signature(
        settings.twilio_inbound_url, form
    )
    public = urlsplit(settings.twilio_inbound_url)
    return client.post(
        public.path + ("?" + public.query if public.query else ""),
        content=urlencode(form),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Twilio-Signature": signature,
        },
    )


def drain(worker):
    for _ in range(8):
        if not worker.run_once():
            return
    raise RuntimeError("Subprocess worker did not become idle")


def run_http(config, settings, provider):
    with TestClient(create_app(settings)) as client:
        if config["mode"] == "accept_commit_response_lost":
            # Execute an actual PostgreSQL COMMIT before emulating a lost driver
            # acknowledgement. A before_commit exception would only test rollback.
            dialect = client.app.state.engine.dialect
            original_commit = dialect.do_commit
            acknowledgement_lost = False

            def commit_then_lose_response(connection):
                nonlocal acknowledgement_lost
                original_commit(connection)
                if not acknowledgement_lost:
                    acknowledgement_lost = True
                    raise psycopg.OperationalError("synthetic commit acknowledgement lost")

            with patch.object(dialect, "do_commit", commit_then_lose_response):
                response = signed_inbound(client, settings, config["form"])
            assert acknowledgement_lost
            assert response.status_code == 503
            barrier("accepted_commit_response_lost")
        else:
            response = signed_inbound(client, settings, config["form"])
            assert response.status_code == 200
            if config["mode"] == "accept_then_wait":
                barrier("inbound_accepted")
            drain(MessagingWorker(client.app.state.engine, settings, provider))


def run_worker(config, settings, provider):
    engine = build_engine(settings)
    worker = MessagingWorker(engine, settings, provider)
    try:
        if config["mode"] == "reply_before_commit":
            original_process = worker._process_inbound

            def process_then_wait(session, job):
                original_process(session, job)
                session.flush()
                barrier("reply_flushed_before_commit")

            with patch.object(worker, "_process_inbound", process_then_wait):
                drain(worker)
        elif config["mode"] == "reply_after_commit":
            # The real handler returned and its transaction committed, while the
            # queue receipt has not yet been settled and no dispatch has started.
            with patch.object(
                worker.queue, "complete", lambda _delivery: barrier("reply_outbox_committed")
            ):
                drain(worker)
        else:
            assert config["mode"] in {"drain", "provider_accept_then_wait"}
            drain(worker)
    finally:
        engine.dispose()


def main():
    config = json.loads(sys.stdin.readline())
    settings = Settings(_env_file=None, **config["settings"])
    assert settings.environment == "test"
    provider = JournalProvider(
        config["journal"],
        wait_after_acceptance=config["mode"] == "provider_accept_then_wait",
    )
    if config["mode"] in {"accept_then_wait", "accept_commit_response_lost", "redeliver_and_drain"}:
        run_http(config, settings, provider)
    else:
        run_worker(config, settings, provider)
    emit("done")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Never print a driver exception, payload, DSN or inherited environment.
        emit("failed", error_type=type(error).__name__)
        sys.exit(1)
