"""Signed WhatsApp ingress and workers use real PostgreSQL tenant policies.

All identities, numbers and Twilio identifiers are synthetic. Only the provider
transport and JWKS transport are replaced; signatures, transactions and RLS run
through the real adapters.
"""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Barrier, Event, Lock
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID, uuid4

import jwt
import pytest
from conftest import AUDIENCE, ISSUER
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from twilio.request_validator import RequestValidator

from anoifig.api.main import create_app
from anoifig.config import Settings
from anoifig.identity.auth import OIDCTokenVerifier
from anoifig.messaging.provider import AmbiguousFailure, PermanentFailure, SafeRetry, SendResult
from anoifig.messaging.worker import MessagingWorker

pytestmark = pytest.mark.integration

ACCOUNT_SID = "AC" + "a" * 32
AUTH_TOKEN = "synthetic-twilio-test-token"
SENDER = "whatsapp:+35315550100"
PHONE = "+353855550101"
OTHER_PHONE = "+353855550102"
INBOUND_URL = "https://messages.example.test/webhooks/twilio/inbound"
STATUS_URL = "https://messages.example.test/webhooks/twilio/status"
TARA_RESPONSE = (
    "Hi, I'm Tara, your An Oifig assistant. Your message has been received successfully."
)


@dataclass
class FakeProvider:
    failures: list[Exception] = field(default_factory=list)
    calls: list[dict[str, str]] = field(default_factory=list)
    accepted_sids: list[str] = field(default_factory=list)
    sid: str | None = None
    _lock: Lock = field(default_factory=Lock, repr=False)

    def send_text(self, *, to: str, body: str, callback_url: str) -> SendResult:
        with self._lock:
            self.calls.append({"to": to, "body": body, "callback_url": callback_url})
            if self.failures:
                raise self.failures.pop(0)
            self.sid = "SM" + uuid4().hex
            self.accepted_sids.append(self.sid)
            return SendResult(sid=self.sid, status="queued")


@pytest.fixture
def messaging_client(database, signing_key, monkeypatch) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=database.runtime_url,
        oidc_issuer=ISSUER,
        oidc_audience=AUDIENCE,
        oidc_jwks_url=ISSUER + ".well-known/jwks.json",
        database_pool_size=8,
        database_max_overflow=0,
        twilio_enabled=True,
        twilio_account_sid=ACCOUNT_SID,
        twilio_auth_token=AUTH_TOKEN,
        twilio_whatsapp_number=SENDER,
        twilio_inbound_url=INBOUND_URL,
        twilio_status_url=STATUS_URL,
    )
    verifier = OIDCTokenVerifier(settings)
    jwk = jwt.PyJWK.from_json(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    monkeypatch.setattr(verifier.jwks_client, "get_signing_key_from_jwt", lambda _token: jwk)
    with TestClient(create_app(settings, token_verifier=verifier)) as client:
        yield client


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def worker(messaging_client, provider) -> MessagingWorker:
    return MessagingWorker(
        messaging_client.app.state.engine, messaging_client.app.state.settings, provider
    )


def inbound_form(*, phone=PHONE, body="Hello Tara", sid=None, **overrides):
    return {
        "AccountSid": ACCOUNT_SID,
        "MessageSid": sid or "SM" + uuid4().hex,
        "From": "whatsapp:" + phone,
        "To": SENDER,
        "Body": body,
        "NumMedia": "0",
        **overrides,
    }


def signed_post(client, parameters, *, public_url=INBOUND_URL, path=None, **extra_headers):
    parsed = urlsplit(public_url)
    path = path or parsed.path + ("?" + parsed.query if parsed.query else "")
    signature = RequestValidator(AUTH_TOKEN).compute_signature(public_url, parameters)
    return client.post(
        path,
        content=urlencode(parameters),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Twilio-Signature": signature,
            **extra_headers,
        },
    )


def link_path(seed, tenant="a"):
    return f"/v1/businesses/{seed.businesses[tenant]}/messaging/links"


def create_link(client, seed, bearer, *, phone=PHONE, tenant="a", subject="owner-a"):
    response = client.post(link_path(seed, tenant), headers=bearer(subject), json={"phone": phone})
    assert response.status_code == 201, response.text
    result = response.json()
    assert set(result) == {"id", "token", "expires_at"}
    return result


def verify_link(client, seed, bearer, *, phone=PHONE, tenant="a", subject="owner-a"):
    challenge = create_link(client, seed, bearer, phone=phone, tenant=tenant, subject=subject)
    response = signed_post(client, inbound_form(phone=phone, body="LINK " + challenge["token"]))
    assert response.status_code == 200, response.text
    return challenge


def rows(database, table, where="", parameters=None):
    # Callers supply fixed table/where fragments, never webhook input.
    with database.admin.connect() as connection:
        return (
            connection.execute(text(f"SELECT * FROM {table} {where}"), parameters or {})
            .mappings()
            .all()
        )


def drain(worker):
    for _ in range(8):
        if not worker.run_once():
            break
    else:
        pytest.fail("Worker did not become idle after eight batches")


def set_context(connection, seed, *, tenant="a", subject="owner-a"):
    connection.execute(
        text(
            "SELECT set_config('app.issuer', :issuer, true), "
            "set_config('app.subject', :subject, true), "
            "set_config('app.tenant_id', :tenant, true)"
        ),
        {"issuer": ISSUER, "subject": subject, "tenant": str(seed.businesses[tenant])},
    )


@contextmanager
def paused_provider_send(worker, provider, monkeypatch, job_id) -> Iterator[SendResult]:
    """Pause after provider acceptance, outside the worker's DB transactions."""
    accepted, release = Event(), Event()
    results = []
    original_send = provider.send_text

    def accept_then_pause(**kwargs):
        result = original_send(**kwargs)
        results.append(result)
        accepted.set()
        assert release.wait(timeout=30), "Test did not release the provider response"
        return result

    with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=1) as executor:
        patch.setattr(provider, "send_text", accept_then_pause)
        future = executor.submit(worker.process_delivery, job_id)
        try:
            assert accepted.wait(timeout=30), "Worker never reached provider acceptance"
            yield results[0]
        finally:
            release.set()
            future.result(timeout=30)


def expire_and_recover_dispatch(database, worker, outbox_id):
    with database.admin.begin() as connection:
        connection.execute(
            text("UPDATE outbox SET lease_until = now() - interval '1 second' WHERE id = :id"),
            {"id": outbox_id},
        )
    # A second process sees only durable state, not the paused provider response.
    recovery_worker = MessagingWorker(worker.engine, worker.settings, worker.provider)
    recovery_worker.process_delivery(outbox_id)
    recovered = rows(database, "outbox", "WHERE id = :id", {"id": outbox_id})[0]
    assert recovered["status"] == "uncertain"
    assert recovered["attempts"] == 1
    assert recovered["last_error"] == "dispatch_interrupted"
    assert recovered["lease_until"] is None


def test_link_requires_oidc_writer_and_selected_tenant(messaging_client, seed, bearer):
    assert messaging_client.post(link_path(seed), json={"phone": PHONE}).status_code == 401
    for subject in ("reader-a", "owner-b", "revoked", "disabled", "outsider"):
        response = messaging_client.post(
            link_path(seed), headers=bearer(subject), json={"phone": PHONE}
        )
        assert response.status_code == 403
    assert (
        messaging_client.post(
            link_path(seed, "b"), headers=bearer("owner-a"), json={"phone": PHONE}
        ).status_code
        == 403
    )


@pytest.mark.parametrize("phone", ["0855550101", "whatsapp:" + PHONE, "x", "+123", ""])
def test_link_rejects_invalid_phone(messaging_client, seed, bearer, phone):
    response = messaging_client.post(
        link_path(seed), headers=bearer("owner-a"), json={"phone": phone}
    )
    assert response.status_code == 422


def test_number_requires_explicit_single_use_verification(messaging_client, database, seed, bearer):
    challenge = create_link(messaging_client, seed, bearer)
    link = rows(database, "phone_links")[0]
    assert link["verified_at"] is None
    assert link["token_hash"] != challenge["token"]
    assert challenge["token"] not in str(link)
    assert signed_post(messaging_client, inbound_form()).status_code == 403
    assert (
        signed_post(
            messaging_client,
            inbound_form(phone=OTHER_PHONE, body="LINK " + challenge["token"]),
        ).status_code
        == 403
    )
    verification = inbound_form(body="LINK " + challenge["token"])
    assert signed_post(messaging_client, verification).status_code == 200
    assert rows(database, "phone_links")[0]["verified_at"] is not None
    assert rows(database, "phone_links")[0]["token_hash"] is None
    assert signed_post(messaging_client, verification).status_code in {200, 403}
    assert rows(database, "messages") == []
    assert rows(database, "conversations") == []


def test_expired_challenge_and_revoked_link_fail_closed(messaging_client, database, seed, bearer):
    challenge = create_link(messaging_client, seed, bearer)
    with database.admin.begin() as connection:
        connection.execute(text("UPDATE phone_links SET expires_at = now() - interval '1 minute'"))
    assert (
        signed_post(messaging_client, inbound_form(body="LINK " + challenge["token"])).status_code
        == 403
    )
    verified = verify_link(messaging_client, seed, bearer)
    response = messaging_client.delete(
        link_path(seed) + "/" + verified["id"], headers=bearer("owner-a")
    )
    assert response.status_code == 204
    assert (
        messaging_client.delete(
            link_path(seed) + "/" + verified["id"], headers=bearer("owner-a")
        ).status_code
        == 204
    )
    assert signed_post(messaging_client, inbound_form()).status_code == 403
    assert rows(database, "messages") == []


@pytest.mark.parametrize("signature", [None, "invalid", "A" * 28])
def test_missing_or_invalid_signature_cannot_persist_message(
    messaging_client, database, seed, signature
):
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if signature is not None:
        headers["X-Twilio-Signature"] = signature
    response = messaging_client.post(
        "/webhooks/twilio/inbound", content=urlencode(inbound_form()), headers=headers
    )
    assert response.status_code == 403
    assert rows(database, "messages") == []


def test_signature_uses_public_url_and_ignores_forwarded_headers(
    messaging_client, database, seed, bearer
):
    verify_link(messaging_client, seed, bearer)
    form = inbound_form()
    # The internal HTTP test host differs from the public HTTPS webhook URL.
    assert (
        signed_post(
            messaging_client,
            form,
            **{"X-Forwarded-Host": "attacker.example", "X-Forwarded-Proto": "http"},
        ).status_code
        == 200
    )
    form["MessageSid"] = "SM" + uuid4().hex
    assert (
        signed_post(
            messaging_client,
            form,
            public_url="http://testserver/webhooks/twilio/inbound",
        ).status_code
        == 403
    )
    assert len(rows(database, "messages")) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"AccountSid": "AC" + "b" * 32},
        {"MessageSid": "invalid"},
        {"From": "sms:+353855550101"},
        {"To": "whatsapp:+35315550999"},
        {"Body": " "},
        {"Body": "x" * 1601},
        {"NumMedia": "1", "MediaUrl0": "https://example.test/attachment"},
    ],
)
def test_signed_malformed_or_misdirected_messages_are_rejected(
    messaging_client, database, seed, overrides
):
    response = signed_post(messaging_client, inbound_form(**overrides))
    assert response.status_code in {400, 403, 422}
    assert rows(database, "messages") == []


def test_signed_unknown_sender_is_not_given_business_access(messaging_client, database, seed):
    assert signed_post(messaging_client, inbound_form()).status_code == 403
    assert rows(database, "messages") == []
    assert rows(database, "phone_links") == []


def test_durable_acceptance_processing_and_outbound_persistence(
    messaging_client, database, seed, bearer, worker, provider
):
    verify_link(messaging_client, seed, bearer)
    form = inbound_form(body="Please confirm this works")
    response = signed_post(messaging_client, form)
    assert response.status_code == 200
    assert "xml" in response.headers["Content-Type"]
    assert TARA_RESPONSE not in response.text
    inbound = rows(database, "messages")[0]
    assert inbound["body"] == form["Body"]
    assert inbound["direction"] == "inbound"
    assert inbound["twilio_sid"] == form["MessageSid"]
    assert inbound["tenant_id"] == seed.businesses["a"]
    assert inbound["user_id"] == seed.users["owner-a"]
    assert inbound["received_at"].utcoffset().total_seconds() == 0
    assert len(rows(database, "message_jobs")) == 1
    assert rows(database, "outbox") == []
    assert provider.calls == []

    # A separate worker instance discovers persisted work without an in-memory handoff.
    drain(worker)
    persisted = rows(database, "messages", "ORDER BY direction")
    assert len(persisted) == 2
    inbound, outbound = persisted
    assert inbound["processed_at"] is not None
    assert outbound["direction"] == "outbound"
    assert outbound["body"] == TARA_RESPONSE
    assert outbound["reply_to_id"] == inbound["id"]
    assert outbound["twilio_sid"] == provider.sid
    assert outbound["account_sid"] == ACCOUNT_SID
    outbox = rows(database, "outbox")[0]
    assert outbox["status"] == "sent"
    assert outbox["attempts"] == 1
    assert provider.calls == [
        {
            "to": "whatsapp:" + PHONE,
            "body": TARA_RESPONSE,
            "callback_url": STATUS_URL + "?attempt_id=" + str(outbox["id"]),
        }
    ]


def test_duplicate_inbound_and_queue_redelivery_produce_one_reply(
    messaging_client, database, seed, bearer, worker, provider
):
    verify_link(messaging_client, seed, bearer)
    form = inbound_form()
    for _ in range(3):
        assert signed_post(messaging_client, form).status_code == 200
    assert len(rows(database, "messages")) == 1
    inbound_job = rows(database, "message_jobs")[0]["id"]
    worker.process_delivery(inbound_job)
    worker.process_delivery(inbound_job)
    assert len(rows(database, "outbox")) == 1
    outbound_job = rows(database, "outbox")[0]["id"]
    worker.process_delivery(outbound_job)
    worker.process_delivery(outbound_job)
    drain(worker)
    assert len(rows(database, "messages")) == 2
    assert len(provider.calls) == 1


def test_concurrent_duplicate_webhooks_are_accepted_once(
    messaging_client, database, seed, bearer, worker, provider
):
    verify_link(messaging_client, seed, bearer)
    form = inbound_form()
    with ThreadPoolExecutor(max_workers=6) as executor:
        responses = list(executor.map(lambda _: signed_post(messaging_client, form), range(6)))
    assert [response.status_code for response in responses] == [200] * 6
    assert len(rows(database, "conversations")) == 1
    assert len(rows(database, "messages")) == 1
    assert len(rows(database, "message_jobs")) == 1
    drain(worker)
    assert len(rows(database, "outbox")) == 1
    assert len(provider.calls) == 1


def test_delivery_callbacks_are_signed_correlated_and_monotonic(
    messaging_client, database, seed, bearer, worker, provider
):
    verify_link(messaging_client, seed, bearer)
    assert signed_post(messaging_client, inbound_form()).status_code == 200
    drain(worker)
    outbox = rows(database, "outbox")[0]
    callback_url = provider.calls[0]["callback_url"]
    form = {"AccountSid": ACCOUNT_SID, "MessageSid": provider.sid, "MessageStatus": "delivered"}
    assert (
        messaging_client.post(
            urlsplit(callback_url).path + "?" + urlsplit(callback_url).query,
            content=urlencode(form),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ).status_code
        == 403
    )
    for status in ("delivered", "sent", "delivered", "read", "queued"):
        form["MessageStatus"] = status
        assert signed_post(messaging_client, form, public_url=callback_url).status_code == 204
    message = rows(database, "messages", "WHERE id = :id", {"id": outbox["message_id"]})[0]
    assert message["status"] == "read"
    assert len(provider.calls) == 1

    # A valid signature cannot attach a different provider message to this attempt.
    form.update(MessageSid="SM" + "e" * 32, MessageStatus="failed")
    assert signed_post(messaging_client, form, public_url=callback_url).status_code == 403
    message = rows(database, "messages", "WHERE id = :id", {"id": outbox["message_id"]})[0]
    assert message["twilio_sid"] == provider.sid
    assert message["status"] == "read"


def test_provider_rate_limit_retries_only_after_delay_and_reuses_outbox(
    messaging_client, database, seed, bearer, worker, provider
):
    provider.failures.append(SafeRetry(retry_after=60))
    verify_link(messaging_client, seed, bearer)
    assert signed_post(messaging_client, inbound_form()).status_code == 200
    drain(worker)
    failed = rows(database, "outbox")[0]
    assert failed["status"] == "retry"
    assert failed["attempts"] == 1
    assert failed["available_at"] > datetime.now(UTC)
    assert failed["last_error"] is not None
    assert provider.sid is None
    assert provider.accepted_sids == []
    drain(worker)
    assert len(provider.calls) == 1
    with database.admin.begin() as connection:
        connection.execute(text("UPDATE outbox SET available_at = now() - interval '1 second'"))
    drain(worker)
    retried = rows(database, "outbox")[0]
    assert retried["id"] == failed["id"]
    assert retried["status"] == "sent"
    assert retried["attempts"] == 2
    assert provider.accepted_sids == [provider.sid]
    assert len(provider.calls) == 2
    assert provider.calls[0] == provider.calls[1]
    assert len(rows(database, "messages")) == 2


def test_repeated_rate_limits_stop_after_bounded_retries(
    messaging_client, database, seed, bearer, worker, provider
):
    provider.failures.extend(SafeRetry(retry_after=1) for _ in range(5))
    verify_link(messaging_client, seed, bearer)
    assert signed_post(messaging_client, inbound_form()).status_code == 200
    worker.run_once()
    for _ in range(5):
        worker.run_once()
        with database.admin.begin() as connection:
            connection.execute(text("UPDATE outbox SET available_at = now() - interval '1 second'"))
    drain(worker)
    failed = rows(database, "outbox")[0]
    assert failed["status"] == "failed"
    assert failed["attempts"] == 5
    assert failed["last_error"] == "rate_limited"
    assert rows(database, "messages", "WHERE direction = 'outbound'")[0]["status"] == "failed"
    assert len(rows(database, "messages")) == 2
    assert len(provider.calls) == 5


def test_failed_delivery_callback_records_provider_error_without_retrying(
    messaging_client, database, seed, bearer, worker, provider
):
    verify_link(messaging_client, seed, bearer)
    assert signed_post(messaging_client, inbound_form()).status_code == 200
    drain(worker)
    callback_url = provider.calls[0]["callback_url"]
    form = {
        "AccountSid": ACCOUNT_SID,
        "MessageSid": provider.sid,
        "MessageStatus": "undelivered",
        "ErrorCode": "63016",
    }
    without_code = {name: value for name, value in form.items() if name != "ErrorCode"}
    assert signed_post(messaging_client, without_code, public_url=callback_url).status_code == 204
    assert signed_post(messaging_client, form, public_url=callback_url).status_code == 204
    message = rows(database, "messages", "WHERE direction = 'outbound'")[0]
    assert message["status"] == "undelivered"
    assert message["processing_error"] == "twilio_63016"
    drain(worker)
    assert len(provider.calls) == 1


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        (AmbiguousFailure("transport_timeout"), "uncertain"),
        (PermanentFailure("twilio_63016"), "failed"),
    ],
)
def test_provider_failure_is_recorded_without_unsafe_resend(
    messaging_client, database, seed, bearer, worker, provider, failure, status
):
    provider.failures.append(failure)
    verify_link(messaging_client, seed, bearer)
    assert signed_post(messaging_client, inbound_form()).status_code == 200
    drain(worker)
    failed = rows(database, "outbox")[0]
    assert failed["status"] == status
    assert failed["last_error"] == failure.code
    assert failed["attempts"] == 1
    message = rows(database, "messages", "WHERE direction = 'outbound'")[0]
    assert message["status"] == status
    assert message["processing_error"] == failure.code
    for _ in range(3):
        worker.process_delivery(failed["id"])
        drain(worker)
    assert len(provider.calls) == 1
    assert len(rows(database, "messages")) == 2


def test_callback_reconciles_ambiguous_send_without_resending(
    messaging_client, database, seed, bearer, worker, provider
):
    provider.failures.append(AmbiguousFailure("transport_timeout"))
    verify_link(messaging_client, seed, bearer)
    assert signed_post(messaging_client, inbound_form()).status_code == 200
    drain(worker)
    callback_url = provider.calls[0]["callback_url"]
    callback_sid = "SM" + uuid4().hex
    assert provider.sid is None
    assert provider.accepted_sids == []
    form = {"AccountSid": ACCOUNT_SID, "MessageSid": callback_sid, "MessageStatus": "delivered"}
    assert signed_post(messaging_client, form, public_url=callback_url).status_code == 204
    drain(worker)
    assert rows(database, "outbox")[0]["status"] == "sent"
    outgoing = rows(database, "messages", "WHERE direction = 'outbound'")[0]
    assert outgoing["status"] == "delivered"
    assert outgoing["twilio_sid"] == callback_sid
    assert len(provider.calls) == 1


@pytest.mark.parametrize("before_processing", [True, False])
def test_membership_revocation_blocks_queued_processing_and_send(
    messaging_client, database, seed, bearer, worker, provider, before_processing
):
    verify_link(messaging_client, seed, bearer)
    assert signed_post(messaging_client, inbound_form()).status_code == 200
    if not before_processing:
        worker.run_once()
        assert len(rows(database, "outbox")) == 1
    with database.admin.begin() as connection:
        connection.execute(
            text("UPDATE memberships SET active = false WHERE user_id = :user"),
            {"user": seed.users["owner-a"]},
        )
    drain(worker)
    assert provider.calls == []
    assert signed_post(messaging_client, inbound_form()).status_code == 403


def test_expired_customer_service_window_blocks_freeform_reply(
    messaging_client, database, seed, bearer, worker, provider
):
    verify_link(messaging_client, seed, bearer)
    form = inbound_form()
    assert signed_post(messaging_client, form).status_code == 200
    worker.run_once()
    with database.admin.begin() as connection:
        connection.execute(
            text("UPDATE conversations SET last_inbound_at = now() - interval '25 hours'")
        )
    # Provider retries must not extend the messaging window.
    assert signed_post(messaging_client, form).status_code == 200
    drain(worker)
    assert provider.calls == []
    assert rows(database, "outbox")[0]["status"] == "blocked"


def test_tenant_messaging_tables_enforce_rls_without_query_filters(
    messaging_client, database, seed, bearer, worker
):
    for tenant, subject, phone in (("a", "owner-a", PHONE), ("b", "owner-b", OTHER_PHONE)):
        verify_link(messaging_client, seed, bearer, tenant=tenant, subject=subject, phone=phone)
        assert signed_post(messaging_client, inbound_form(phone=phone)).status_code == 200
    # Persist outboxes without invoking the external provider.
    worker.run_once()
    with database.runtime.begin() as connection:
        for table in ("phone_links", "conversations", "messages", "outbox"):
            assert connection.execute(text(f"SELECT * FROM {table}")).all() == []
        set_context(connection, seed)
        for table in ("phone_links", "conversations", "messages", "outbox"):
            result = connection.execute(text(f"SELECT tenant_id FROM {table}")).scalars().all()
            assert result
            assert set(result) == {seed.businesses["a"]}
    with database.runtime.begin() as connection:
        assert connection.execute(text("SELECT * FROM messages")).all() == []
        set_context(connection, seed, subject="owner-b")
        assert connection.execute(text("SELECT * FROM messages")).all() == []
    with pytest.raises(DBAPIError), database.runtime.begin() as connection:
        connection.execute(text("SELECT * FROM message_jobs"))


def test_cross_tenant_conversation_reference_rejected_by_rls_and_composite_fk(
    messaging_client, database, seed, bearer
):
    verify_link(messaging_client, seed, bearer, tenant="b", subject="owner-b", phone=OTHER_PHONE)
    assert signed_post(messaging_client, inbound_form(phone=OTHER_PHONE)).status_code == 200
    foreign = rows(database, "messages")[0]
    statement = text(
        "INSERT INTO messages "
        "(id,tenant_id,conversation_id,phone_link_id,user_id,direction,body,account_sid) "
        "VALUES (:id,:tenant,:conversation,:link,:user,'inbound','Denied',:account)"
    )
    values = {
        "id": uuid4(),
        "tenant": seed.businesses["b"],
        "conversation": foreign["conversation_id"],
        "link": foreign["phone_link_id"],
        "user": seed.users["owner-b"],
        "account": ACCOUNT_SID,
    }
    with pytest.raises(DBAPIError), database.runtime.begin() as connection:
        set_context(connection, seed)
        connection.execute(statement, values)
    # Even privileged provisioning cannot attach a conversation from another tenant.
    values.update(id=uuid4(), tenant=seed.businesses["a"])
    with pytest.raises(IntegrityError), database.admin.begin() as connection:
        connection.execute(statement, values)


def test_callback_attempt_id_is_part_of_signature(
    messaging_client, database, seed, bearer, worker, provider
):
    verify_link(messaging_client, seed, bearer)
    assert signed_post(messaging_client, inbound_form()).status_code == 200
    drain(worker)
    form = {"AccountSid": ACCOUNT_SID, "MessageSid": provider.sid, "MessageStatus": "delivered"}
    url = provider.calls[0]["callback_url"]
    attempt = parse_qs(urlsplit(url).query)["attempt_id"][0]
    assert UUID(attempt) == rows(database, "outbox")[0]["id"]
    assert (
        signed_post(
            messaging_client,
            form,
            public_url=STATUS_URL,
            path="/webhooks/twilio/status?attempt_id=" + attempt,
        ).status_code
        == 403
    )


def test_database_commit_failure_never_acknowledges_acceptance(
    messaging_client, database, seed, bearer
):
    verify_link(messaging_client, seed, bearer)

    def unavailable(_session):
        raise SQLAlchemyError("synthetic commit outage")

    event.listen(Session, "before_commit", unavailable)
    try:
        response = signed_post(messaging_client, inbound_form())
    finally:
        event.remove(Session, "before_commit", unavailable)
    assert response.status_code == 503
    assert "outage" not in response.text
    assert rows(database, "messages") == []
    assert rows(database, "message_jobs") == []


def test_processing_exception_rolls_back_and_retries_with_one_logical_reply(
    messaging_client, database, seed, bearer, worker, provider, monkeypatch
):
    verify_link(messaging_client, seed, bearer)
    assert signed_post(messaging_client, inbound_form()).status_code == 200
    original_process = worker._process_inbound

    def processing_failure(session, job):
        # Fail after creating the reply to prove partial work is rolled back.
        original_process(session, job)
        raise RuntimeError("synthetic sensitive processing details")

    with monkeypatch.context() as patch:
        patch.setattr(worker, "_process_inbound", processing_failure)
        drain(worker)
    message = rows(database, "messages")[0]
    assert message["processed_at"] is None
    assert message["processing_attempts"] == 1
    assert message["processing_error"] == "processing_failed"
    assert message["available_at"] > datetime.now(UTC)
    assert rows(database, "outbox") == []
    assert provider.calls == []
    with database.admin.begin() as connection:
        connection.execute(text("UPDATE messages SET available_at = now() - interval '1 second'"))
    drain(worker)
    assert len(rows(database, "messages")) == 2
    assert len(rows(database, "outbox")) == 1
    assert len(provider.calls) == 1
    inbound = rows(database, "messages", "WHERE direction = 'inbound'")[0]
    assert inbound["processing_error"] is None
    assert inbound["processed_at"] is not None


def test_repeated_processing_failures_are_bounded_and_recorded(
    messaging_client, database, seed, bearer, worker, provider, monkeypatch
):
    verify_link(messaging_client, seed, bearer)
    assert signed_post(messaging_client, inbound_form()).status_code == 200

    def processing_failure(_session, _job):
        raise RuntimeError("synthetic processing failure")

    monkeypatch.setattr(worker, "_process_inbound", processing_failure)
    for _ in range(5):
        worker.run_once()
        with database.admin.begin() as connection:
            connection.execute(
                text("UPDATE messages SET available_at = now() - interval '1 second'")
            )
    drain(worker)
    message = rows(database, "messages")[0]
    assert message["status"] == "failed"
    assert message["processed_at"] is not None
    assert message["processing_attempts"] == 5
    assert message["processing_error"] == "processing_failed"
    assert rows(database, "outbox") == []
    assert provider.calls == []


def test_provider_acceptance_followed_by_database_failure_is_not_resent(
    messaging_client, database, seed, bearer, worker, provider, monkeypatch
):
    verify_link(messaging_client, seed, bearer)
    assert signed_post(messaging_client, inbound_form()).status_code == 200
    worker.run_once()
    original_check = worker._check
    original_send = provider.send_text

    def unavailable(_session):
        raise SQLAlchemyError("synthetic post-send database outage")

    def accepted_then_database_fails(**kwargs):
        result = original_send(**kwargs)
        monkeypatch.setattr(worker, "_check", unavailable)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(provider, "send_text", accepted_then_database_fails)
        worker.run_once()
    monkeypatch.setattr(worker, "_check", original_check)
    interrupted = rows(database, "outbox")[0]
    assert interrupted["status"] == "dispatching"
    assert interrupted["attempts"] == 1
    with database.admin.begin() as connection:
        connection.execute(text("UPDATE outbox SET lease_until = now() - interval '1 second'"))
        # Recovery waits for both the dispatch lease and the polling cooldown.
        connection.execute(
            text("UPDATE message_jobs SET claim_until = now() - interval '1 second'")
        )
    drain(worker)
    recovered = rows(database, "outbox")[0]
    assert recovered["status"] == "uncertain"
    assert recovered["last_error"] == "dispatch_interrupted"
    assert len(provider.calls) == 1


def test_concurrent_worker_deliveries_send_one_customer_visible_message(
    messaging_client, database, seed, bearer, worker, provider
):
    verify_link(messaging_client, seed, bearer)
    assert signed_post(messaging_client, inbound_form()).status_code == 200
    inbound_id = rows(database, "messages")[0]["id"]
    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(worker.process_delivery, [inbound_id] * 6))
    outbound_id = rows(database, "outbox")[0]["id"]
    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(worker.process_delivery, [outbound_id] * 6))
    drain(worker)
    assert len(rows(database, "messages")) == 2
    assert len(rows(database, "outbox")) == 1
    assert len(provider.calls) == 1


def test_callback_during_send_is_preserved_when_provider_response_arrives(
    messaging_client, database, seed, bearer, worker, provider, monkeypatch
):
    verify_link(messaging_client, seed, bearer)
    assert signed_post(messaging_client, inbound_form()).status_code == 200
    original_send = provider.send_text

    def deliver_before_sdk_returns(**kwargs):
        result = original_send(**kwargs)
        response = signed_post(
            messaging_client,
            {"AccountSid": ACCOUNT_SID, "MessageSid": result.sid, "MessageStatus": "delivered"},
            public_url=kwargs["callback_url"],
        )
        assert response.status_code == 204
        return result

    monkeypatch.setattr(provider, "send_text", deliver_before_sdk_returns)
    drain(worker)
    assert rows(database, "outbox")[0]["status"] == "sent"
    assert rows(database, "messages", "WHERE direction = 'outbound'")[0]["status"] == "delivered"
    assert len(provider.calls) == 1


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO message_jobs SELECT * FROM message_jobs",
        "UPDATE message_jobs SET ready = true",
        "DELETE FROM message_jobs",
    ],
)
def test_runtime_cannot_forge_or_mutate_operational_jobs(database, seed, statement):
    with pytest.raises(DBAPIError), database.runtime.begin() as connection:
        set_context(connection, seed)
        connection.execute(text(statement))


def test_same_tenant_message_cannot_reference_another_phone_links_conversation(
    messaging_client, database, seed, bearer
):
    for phone in (PHONE, OTHER_PHONE):
        verify_link(messaging_client, seed, bearer, phone=phone)
        assert signed_post(messaging_client, inbound_form(phone=phone)).status_code == 200
    first, second = rows(database, "messages", "ORDER BY created_at")
    with pytest.raises(IntegrityError), database.admin.begin() as connection:
        connection.execute(
            text("UPDATE messages SET phone_link_id = :link WHERE id = :id"),
            {"id": first["id"], "link": second["phone_link_id"]},
        )


@pytest.mark.parametrize("change", ["revocation", "window_expired", "lease_expired"])
def test_worker_rechecks_authority_window_and_lease_immediately_before_provider_call(
    messaging_client, database, seed, bearer, worker, provider, monkeypatch, change
):
    verify_link(messaging_client, seed, bearer)
    assert signed_post(messaging_client, inbound_form()).status_code == 200
    worker.run_once()
    original_send = worker._send

    def change_after_prepare(command):
        with database.admin.begin() as connection:
            if change == "revocation":
                connection.execute(text("UPDATE phone_links SET revoked_at = now()"))
            elif change == "window_expired":
                connection.execute(
                    text("UPDATE conversations SET last_inbound_at = now() - interval '25 hours'")
                )
            else:
                connection.execute(
                    text("UPDATE outbox SET lease_until = now() - interval '1 second'")
                )
        original_send(command)

    monkeypatch.setattr(worker, "_send", change_after_prepare)
    drain(worker)
    assert provider.calls == []
    outbox = rows(database, "outbox")[0]
    if change == "window_expired":
        assert outbox["status"] == "blocked"
        assert outbox["last_error"] == "template_required"
    elif change == "lease_expired":
        assert outbox["status"] == "uncertain"
    else:
        job = rows(database, "message_jobs", "WHERE id = :id", {"id": outbox["id"]})[0]
        assert job["ready"] is False


def test_concurrent_messages_and_callbacks_remain_distinct_and_tenant_isolated(
    messaging_client, database, seed, bearer, worker, provider
):
    per_tenant = 8
    forms = []
    for tenant, subject, phone in (("a", "owner-a", PHONE), ("b", "owner-b", OTHER_PHONE)):
        verify_link(messaging_client, seed, bearer, tenant=tenant, subject=subject, phone=phone)
        forms.extend(inbound_form(phone=phone, body=f"Message {i}") for i in range(per_tenant))
    with ThreadPoolExecutor(max_workers=6) as executor:
        responses = list(executor.map(lambda form: signed_post(messaging_client, form), forms))
        assert [response.status_code for response in responses] == [200] * len(forms)
        inbound_ids = [message["id"] for message in rows(database, "messages")]
        list(executor.map(worker.process_delivery, inbound_ids * 2))
        outboxes = rows(database, "outbox")
        assert len(outboxes) == len(forms)
        list(executor.map(worker.process_delivery, [outbox["id"] for outbox in outboxes] * 2))
    drain(worker)
    # Ordered replies may be deferred behind another accepted turn. The direct
    # concurrent deliveries above have finished; advance only their polling
    # cooldown, preserving source retry deadlines and all delivery state.
    for _ in range(per_tenant + 1):
        if len(provider.calls) == len(forms):
            break
        with database.admin.begin() as connection:
            connection.execute(
                text(
                    "UPDATE message_jobs SET claim_until = now() - interval '1 second' "
                    "WHERE ready AND due_at <= now()"
                )
            )
        worker.run_once()
    outgoing = rows(database, "messages", "WHERE direction = 'outbound'")
    assert len(outgoing) == len(forms)
    assert len(provider.calls) == len(forms)
    assert len(provider.accepted_sids) == len(set(provider.accepted_sids)) == len(forms)
    assert {message["twilio_sid"] for message in outgoing} == set(provider.accepted_sids)
    assert provider.sid == provider.accepted_sids[-1]
    by_id = {message["id"]: message for message in outgoing}
    callbacks = [
        (
            STATUS_URL + "?attempt_id=" + str(outbox["id"]),
            {
                "AccountSid": ACCOUNT_SID,
                "MessageSid": by_id[outbox["message_id"]]["twilio_sid"],
                "MessageStatus": status,
            },
        )
        for outbox in outboxes
        for status in ("read", "queued", "delivered", "read")
    ]

    def post_callback(callback):
        url, form = callback
        return signed_post(messaging_client, form, public_url=url).status_code

    with ThreadPoolExecutor(max_workers=6) as executor:
        assert list(executor.map(post_callback, callbacks)) == [204] * len(callbacks)
    assert {
        message["status"] for message in rows(database, "messages", "WHERE direction = 'outbound'")
    } == {"read"}
    assert {outbox["status"] for outbox in rows(database, "outbox")} == {"sent"}
    for tenant, subject in (("a", "owner-a"), ("b", "owner-b")):
        with database.runtime.begin() as connection:
            assert connection.execute(text("SELECT id FROM messages")).all() == []
            set_context(connection, seed, tenant=tenant, subject=subject)
            visible = connection.execute(text("SELECT tenant_id FROM messages")).scalars().all()
            assert visible == [seed.businesses[tenant]] * (per_tenant * 2)
            for table in ("phone_links", "conversations", "outbox"):
                assert set(
                    connection.execute(text(f"SELECT tenant_id FROM {table}")).scalars()
                ) == {seed.businesses[tenant]}
            other = "b" if tenant == "a" else "a"
            assert (
                connection.execute(
                    text("UPDATE messages SET status = 'failed' WHERE tenant_id = :tenant"),
                    {"tenant": seed.businesses[other]},
                ).rowcount
                == 0
            )
    with database.runtime.begin() as connection:
        assert connection.execute(text("SELECT id FROM messages")).all() == []
        set_context(connection, seed, tenant="a", subject="owner-b")
        assert connection.execute(text("SELECT id FROM messages")).all() == []
    drain(worker)
    assert len(provider.calls) == len(forms)


@pytest.mark.parametrize("callback_status", [None, "delivered", "read"])
def test_late_provider_success_reconciles_recovered_lease_without_regressing_callbacks(
    messaging_client, database, seed, bearer, worker, provider, monkeypatch, callback_status
):
    verify_link(messaging_client, seed, bearer)
    assert signed_post(messaging_client, inbound_form()).status_code == 200
    worker.run_once()
    outbox = rows(database, "outbox")[0]
    with paused_provider_send(worker, provider, monkeypatch, outbox["id"]) as result:
        expire_and_recover_dispatch(database, worker, outbox["id"])
        if callback_status is not None:
            for status in (callback_status, "queued"):
                response = signed_post(
                    messaging_client,
                    {"AccountSid": ACCOUNT_SID, "MessageSid": result.sid, "MessageStatus": status},
                    public_url=provider.calls[0]["callback_url"],
                )
                assert response.status_code == 204
    persisted = rows(database, "outbox")[0]
    message = rows(database, "messages", "WHERE id = :id", {"id": outbox["message_id"]})[0]
    assert persisted["status"] == "sent"
    assert persisted["attempts"] == 1
    assert persisted["last_error"] is None
    assert persisted["lease_until"] is None
    assert message["twilio_sid"] == result.sid
    assert message["status"] == (callback_status or "queued")
    assert message["processing_error"] is None
    drain(worker)
    assert len(provider.calls) == 1


def test_concurrent_callbacks_and_late_provider_response_preserve_read_progress(
    messaging_client, database, seed, bearer, worker, provider, monkeypatch
):
    verify_link(messaging_client, seed, bearer)
    assert signed_post(messaging_client, inbound_form()).status_code == 200
    worker.run_once()
    outbox = rows(database, "outbox")[0]
    statuses = ("read", "delivered", "sent", "queued", "read", "failed")
    start = Barrier(len(statuses) + 1)
    with ThreadPoolExecutor(max_workers=len(statuses)) as executor:
        with paused_provider_send(worker, provider, monkeypatch, outbox["id"]) as result:
            expire_and_recover_dispatch(database, worker, outbox["id"])

            def callback(status):
                start.wait(timeout=30)
                return signed_post(
                    messaging_client,
                    {"AccountSid": ACCOUNT_SID, "MessageSid": result.sid, "MessageStatus": status},
                    public_url=provider.calls[0]["callback_url"],
                ).status_code

            futures = [executor.submit(callback, status) for status in statuses]
            # Releasing the provider response also races the committed callbacks.
            start.wait(timeout=30)
        assert [future.result(timeout=30) for future in futures] == [204] * len(statuses)
    message = rows(database, "messages", "WHERE id = :id", {"id": outbox["message_id"]})[0]
    assert message["twilio_sid"] == result.sid
    assert message["status"] == "read"
    assert message["processing_error"] is None
    assert rows(database, "outbox")[0]["status"] == "sent"
    drain(worker)
    assert len(provider.calls) == 1


@pytest.mark.parametrize("revocation", ["link", "membership"])
def test_late_provider_result_rechecks_revocation_and_parks_without_content_writes(
    messaging_client, database, seed, bearer, worker, provider, monkeypatch, revocation
):
    verify_link(messaging_client, seed, bearer)
    assert signed_post(messaging_client, inbound_form()).status_code == 200
    worker.run_once()
    outbox = rows(database, "outbox")[0]
    with paused_provider_send(worker, provider, monkeypatch, outbox["id"]) as result:
        expire_and_recover_dispatch(database, worker, outbox["id"])
        before_outbox = rows(database, "outbox")[0]
        before_message = rows(database, "messages", "WHERE id = :id", {"id": outbox["message_id"]})[
            0
        ]
        with database.admin.begin() as connection:
            if revocation == "link":
                connection.execute(text("UPDATE phone_links SET revoked_at = now()"))
            else:
                connection.execute(
                    text("UPDATE memberships SET active = false WHERE user_id = :user"),
                    {"user": seed.users["owner-a"]},
                )
        assert (
            signed_post(
                messaging_client,
                {"AccountSid": ACCOUNT_SID, "MessageSid": result.sid, "MessageStatus": "read"},
                public_url=provider.calls[0]["callback_url"],
            ).status_code
            == 403
        )
    assert rows(database, "outbox")[0] == before_outbox
    assert (
        rows(database, "messages", "WHERE id = :id", {"id": outbox["message_id"]})[0]
        == before_message
    )
    job = rows(database, "message_jobs", "WHERE id = :id", {"id": outbox["id"]})[0]
    assert job["ready"] is False
    assert job["last_error"] == "access_revoked"
    drain(worker)
    assert len(provider.calls) == 1


@pytest.mark.parametrize("recover_lease", [False, True])
def test_provider_sid_mismatch_preserves_callback_sid_and_delivery_progress(
    messaging_client, database, seed, bearer, worker, provider, monkeypatch, recover_lease
):
    verify_link(messaging_client, seed, bearer)
    assert signed_post(messaging_client, inbound_form()).status_code == 200
    worker.run_once()
    outbox = rows(database, "outbox")[0]
    callback_sid = "SM" + uuid4().hex
    with paused_provider_send(worker, provider, monkeypatch, outbox["id"]) as result:
        assert result.sid != callback_sid
        if recover_lease:
            expire_and_recover_dispatch(database, worker, outbox["id"])
        assert (
            signed_post(
                messaging_client,
                {"AccountSid": ACCOUNT_SID, "MessageSid": callback_sid, "MessageStatus": "read"},
                public_url=provider.calls[0]["callback_url"],
            ).status_code
            == 204
        )
    message = rows(database, "messages", "WHERE id = :id", {"id": outbox["message_id"]})[0]
    assert message["twilio_sid"] == callback_sid
    assert message["status"] == "read"
    assert message["processing_error"] is None
    persisted = rows(database, "outbox")[0]
    assert persisted["status"] == "sent"
    assert persisted["last_error"] == "provider_sid_mismatch"
    drain(worker)
    assert len(provider.calls) == 1


def test_provider_sid_collision_is_contained_without_modifying_another_tenants_message(
    messaging_client, database, seed, bearer, worker, provider, monkeypatch
):
    verify_link(messaging_client, seed, bearer)
    assert signed_post(messaging_client, inbound_form()).status_code == 200
    drain(worker)
    first = rows(database, "messages", "WHERE direction = 'outbound'")[0]
    verify_link(messaging_client, seed, bearer, tenant="b", subject="owner-b", phone=OTHER_PHONE)
    assert signed_post(messaging_client, inbound_form(phone=OTHER_PHONE)).status_code == 200
    worker.run_once()
    second_outbox = rows(
        database, "outbox", "WHERE tenant_id = :tenant", {"tenant": seed.businesses["b"]}
    )[0]
    original_send = provider.send_text

    def conflicting_provider_response(**kwargs):
        original_send(**kwargs)
        return SendResult(sid=first["twilio_sid"], status="queued")

    with monkeypatch.context() as patch:
        patch.setattr(provider, "send_text", conflicting_provider_response)
        worker.process_delivery(second_outbox["id"])
    persisted = rows(database, "outbox", "WHERE id = :id", {"id": second_outbox["id"]})[0]
    assert persisted["status"] == "uncertain"
    assert persisted["attempts"] == 1
    assert persisted["last_error"] == "provider_sid_conflict"
    assert persisted["lease_until"] is None
    second = rows(database, "messages", "WHERE id = :id", {"id": second_outbox["message_id"]})[0]
    assert second["twilio_sid"] is None
    assert second["status"] == "uncertain"
    assert rows(database, "messages", "WHERE id = :id", {"id": first["id"]})[0] == first
    assert len(provider.accepted_sids) == len(set(provider.accepted_sids)) == 2
    for _ in range(3):
        worker.process_delivery(second_outbox["id"])
        drain(worker)
    assert len(provider.calls) == 2


@pytest.mark.parametrize("stage", ["before_dispatch", "after_dispatch"])
def test_stale_attempt_cannot_dispatch_or_persist_over_a_newer_attempt(
    messaging_client, database, seed, bearer, worker, provider, monkeypatch, stage
):
    verify_link(messaging_client, seed, bearer)
    assert signed_post(messaging_client, inbound_form()).status_code == 200
    worker.run_once()
    outbox = rows(database, "outbox")[0]

    def advance_attempt():
        # Model a newer durable operation while an older command is still in memory.
        with database.admin.begin() as connection:
            connection.execute(
                text("UPDATE outbox SET attempts = attempts + 1 WHERE id = :id"),
                {"id": outbox["id"]},
            )

    if stage == "before_dispatch":
        original_send = worker._send

        def stale_dispatch(command):
            advance_attempt()
            original_send(command)

        with monkeypatch.context() as patch:
            patch.setattr(worker, "_send", stale_dispatch)
            worker.process_delivery(outbox["id"])
        assert provider.calls == []
    else:
        with paused_provider_send(worker, provider, monkeypatch, outbox["id"]):
            advance_attempt()
        assert len(provider.calls) == 1
    persisted = rows(database, "outbox")[0]
    message = rows(database, "messages", "WHERE id = :id", {"id": outbox["message_id"]})[0]
    assert persisted["attempts"] == 2
    assert persisted["status"] == "dispatching"
    assert message["twilio_sid"] is None
    assert message["status"] == "pending"
