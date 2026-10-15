"""Provider sends are mocked; ambiguous acceptance never becomes a safe retry."""

import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from twilio.base.exceptions import TwilioRestException

from anoifig.messaging.provider import (
    AmbiguousFailure,
    LocalMessagingProvider,
    PermanentFailure,
    SafeRetry,
    SendResult,
    TwilioMessagingProvider,
)

ACCOUNT_SID = "AC" + "1" * 32
MESSAGE_SID = "SM" + "2" * 32
SENDER = "whatsapp:+14155550100"
RECIPIENT = "whatsapp:+353855550100"
CALLBACK = "https://api.example.test/webhooks/twilio/status?static=1&attempt_id=opaque"
TEXT = "Hello, a chara."


def provider(creator: Mock) -> TwilioMessagingProvider:
    return TwilioMessagingProvider(
        account_sid=ACCOUNT_SID,
        auth_token="unit-only-auth-secret",
        whatsapp_number=SENDER,
        message_creator=creator,
    )


def send(subject: TwilioMessagingProvider) -> SendResult:
    return subject.send_text(to=RECIPIENT, body=TEXT, callback_url=CALLBACK)


def test_send_preserves_text_and_correlated_callback() -> None:
    creator = Mock()
    creator.create.return_value = SimpleNamespace(sid=MESSAGE_SID, status="queued")
    assert send(provider(creator)) == SendResult(sid=MESSAGE_SID, status="queued")
    creator.create.assert_called_once_with(
        to=RECIPIENT, from_=SENDER, body=TEXT, status_callback=CALLBACK
    )


@pytest.mark.parametrize("status,code", [(400, 21608), (401, 20003), (403, 20003), (404, None)])
def test_explicit_rejection_is_permanent_and_secret_safe(status: int, code: int | None) -> None:
    creator = Mock()
    creator.create.side_effect = TwilioRestException(
        status, "https://secret-provider-url.test", "unit-only-sensitive-message", code=code
    )
    with pytest.raises(PermanentFailure) as raised:
        send(provider(creator))
    assert raised.value.code == (f"twilio_{code}" if code else f"http_{status}")
    assert "sensitive" not in str(raised.value)
    creator.create.assert_called_once()


def test_rate_limit_is_a_safe_delayed_retry_without_an_sdk_retry() -> None:
    creator = Mock()
    creator.create.side_effect = TwilioRestException(429, "provider", "limited", code=20429)
    with pytest.raises(SafeRetry) as raised:
        send(provider(creator))
    assert raised.value.retry_after == 60
    creator.create.assert_called_once()


@pytest.mark.parametrize("status", [408, 500, 502, 503])
def test_uncertain_provider_http_failure_requires_reconciliation(status: int) -> None:
    creator = Mock()
    creator.create.side_effect = TwilioRestException(status, "provider", "sensitive error")
    with pytest.raises(AmbiguousFailure) as raised:
        send(provider(creator))
    assert raised.value.code == f"http_{status}"
    assert "sensitive" not in str(raised.value)
    creator.create.assert_called_once()


@pytest.mark.parametrize(
    "error",
    [
        requests.exceptions.ReadTimeout("sensitive request body"),
        requests.exceptions.ConnectionError("sensitive request URL"),
        ValueError("malformed provider response"),
    ],
)
def test_transport_failure_is_ambiguous(error: Exception) -> None:
    creator = Mock()
    creator.create.side_effect = error
    with pytest.raises(AmbiguousFailure) as raised:
        send(provider(creator))
    assert raised.value.code == "transport_or_response_error"
    assert "sensitive" not in str(raised.value)
    creator.create.assert_called_once()


@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(sid="not-a-sid", status="queued"),
        SimpleNamespace(sid=MESSAGE_SID, status="unexpected"),
        SimpleNamespace(sid=None, status="queued"),
        SimpleNamespace(sid=MESSAGE_SID, status=None),
        object(),
    ],
)
def test_malformed_acceptance_response_is_not_automatically_retried(result: object) -> None:
    creator = Mock()
    creator.create.return_value = result
    with pytest.raises(AmbiguousFailure):
        send(provider(creator))
    creator.create.assert_called_once()


@pytest.mark.parametrize(
    "to,body,callback",
    [
        ("+353855550100", TEXT, CALLBACK),
        (RECIPIENT, " ", CALLBACK),
        (RECIPIENT, "a" * 1601, CALLBACK),
        (RECIPIENT, "text\x00", CALLBACK),
        (RECIPIENT, TEXT, "javascript:bad"),
        (RECIPIENT, TEXT, "https://user:secret@example.test/status"),
        (RECIPIENT, TEXT, "https://example.test:bad/status"),
    ],
)
def test_invalid_send_is_rejected_before_calling_provider(
    to: str, body: str, callback: str
) -> None:
    creator = Mock()
    with pytest.raises(PermanentFailure):
        provider(creator).send_text(to=to, body=body, callback_url=callback)
    creator.create.assert_not_called()


def test_real_sdk_transport_disables_automatic_http_retries_and_sensitive_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls = []

    def mock_send(session: requests.Session, request: requests.PreparedRequest, **kwargs: object):
        calls.append((session, request, kwargs))
        adapter = session.get_adapter("https://api.twilio.com")
        assert adapter.max_retries.total == 0
        assert kwargs["timeout"] == 7
        response = requests.Response()
        response.status_code = 201
        response._content = json.dumps({"sid": MESSAGE_SID, "status": "queued"}).encode()
        return response

    monkeypatch.setattr(requests.Session, "send", mock_send)
    subject = TwilioMessagingProvider(
        account_sid=ACCOUNT_SID,
        auth_token="unit-only-auth-secret",
        whatsapp_number=SENDER,
        timeout=7,
    )
    with caplog.at_level(logging.DEBUG):
        assert send(subject).sid == MESSAGE_SID
    assert len(calls) == 1
    assert TEXT not in caplog.text
    assert RECIPIENT not in caplog.text
    assert "unit-only-auth-secret" not in caplog.text


def test_local_provider_never_calls_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    network = Mock(side_effect=AssertionError("local simulator must not use HTTP"))
    monkeypatch.setattr(requests.Session, "send", network)
    result = LocalMessagingProvider().send_text(to=RECIPIENT, body=TEXT, callback_url=CALLBACK)
    assert result.sid.startswith("SM") and len(result.sid) == 34
    assert result.status == "sent"
    network.assert_not_called()
