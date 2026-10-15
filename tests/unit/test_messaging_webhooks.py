"""Twilio signature, strict form validation and secret-safe configuration checks."""

import os
from urllib.parse import urlencode

import pytest
from pydantic import ValidationError
from twilio.request_validator import RequestValidator

from anoifig.config import Settings
from anoifig.messaging.webhooks import (
    MAX_WEBHOOK_BYTES,
    InboundPayload,
    StatusPayload,
    WebhookValidationError,
    parse_form,
    verify_signature,
)

ACCOUNT_SID = "AC" + "1" * 32
MESSAGE_SID = "SM" + "2" * 32
TOKEN = "unit-only-twilio-auth-secret"
PUBLIC_URL = "https://api.example.test/webhooks/twilio/inbound?deployment=staging"
STATUS_URL = "https://api.example.test/webhooks/twilio/status?deployment=staging"
FORM = {
    "AccountSid": ACCOUNT_SID,
    "MessageSid": MESSAGE_SID,
    "From": "whatsapp:+353855550100",
    "To": "whatsapp:+14155550100",
    "Body": "A chara, €10 + VAT & obair.",
    "NumMedia": "0",
}
TWILIO = {
    "twilio_enabled": True,
    "twilio_account_sid": ACCOUNT_SID,
    "twilio_auth_token": TOKEN,
    "twilio_whatsapp_number": FORM["To"],
    "twilio_inbound_url": PUBLIC_URL,
    "twilio_status_url": STATUS_URL,
}
DATABASE_URL = "postgresql+psycopg://unit:unit-only-secret@localhost:5432/anoifig_unit"


@pytest.fixture(autouse=True)
def isolate_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in os.environ:
        if name.startswith("ANOIFIG_"):
            monkeypatch.delenv(name)


def test_valid_signature_includes_exact_configured_url_query_and_all_parameters() -> None:
    parameters = {**FORM, "ProfileName": "Unit test sender"}
    signature = RequestValidator(TOKEN).compute_signature(PUBLIC_URL, parameters)
    assert verify_signature(
        public_url=PUBLIC_URL, parameters=parameters, signature=signature, auth_token=TOKEN
    )
    assert not verify_signature(
        public_url=PUBLIC_URL, parameters=FORM, signature=signature, auth_token=TOKEN
    )


@pytest.mark.parametrize(
    "public_url,parameters,token",
    [
        (PUBLIC_URL.replace("https://", "http://"), FORM, TOKEN),
        (PUBLIC_URL.replace("api.example.test", "attacker.test"), FORM, TOKEN),
        (PUBLIC_URL.replace("staging", "production"), FORM, TOKEN),
        (PUBLIC_URL.split("?")[0], FORM, TOKEN),
        (PUBLIC_URL, {**FORM, "Body": "tampered message"}, TOKEN),
        (PUBLIC_URL, FORM, "different-auth-token"),
    ],
)
def test_signature_rejects_url_body_or_secret_tampering(
    public_url: str, parameters: dict[str, str], token: str
) -> None:
    signature = RequestValidator(TOKEN).compute_signature(PUBLIC_URL, FORM)
    assert not verify_signature(
        public_url=public_url, parameters=parameters, signature=signature, auth_token=token
    )


@pytest.mark.parametrize("signature", [None, "", "invalid", "!" * 28, "é" * 28, " " * 28])
def test_invalid_signature_encoding_is_rejected_safely(signature: str | None) -> None:
    assert not verify_signature(
        public_url=PUBLIC_URL, parameters=FORM, signature=signature, auth_token=TOKEN
    )


@pytest.mark.parametrize(
    "content_type",
    [
        "application/x-www-form-urlencoded",
        "application/x-www-form-urlencoded; charset=UTF-8",
        'application/x-www-form-urlencoded; charset="UTF-8"',
    ],
)
def test_form_decodes_unicode_and_preserves_every_signature_parameter(content_type: str) -> None:
    assert parse_form(content_type, urlencode(FORM).encode()) == FORM


@pytest.mark.parametrize(
    "content_type,body",
    [
        (None, b"Body=hi"),
        ("application/json", b"{}"),
        ("multipart/form-data", b"Body=hi"),
        ("application/x-www-form-urlencoded; charset=latin1", b"Body=hi"),
        ("application/x-www-form-urlencoded; charset=utf-8; charset=utf-8", b"Body=hi"),
        ("application/x-www-form-urlencoded", b""),
        ("application/x-www-form-urlencoded", b"Body=" + b"a" * MAX_WEBHOOK_BYTES),
        ("application/x-www-form-urlencoded", b"Body=first&Body=second"),
        ("application/x-www-form-urlencoded", b"%42ody=first&Body=second"),
        ("application/x-www-form-urlencoded", b"Body=%ZZ"),
        ("application/x-www-form-urlencoded", b"Body=%"),
        ("application/x-www-form-urlencoded", b"Body=%FF"),
        ("application/x-www-form-urlencoded", b"Body=\xff"),
        ("application/x-www-form-urlencoded", b"Body=%00"),
        ("application/x-www-form-urlencoded", b"Body=ok&missing_equals"),
        ("application/x-www-form-urlencoded", b"=value"),
        ("application/x-www-form-urlencoded", b"Body=ok&bad%0Aname=bad"),
        ("application/x-www-form-urlencoded", b"Body=" + b"a" * 8193),
        (
            "application/x-www-form-urlencoded",
            urlencode({f"Field{i}": "x" for i in range(65)}).encode(),
        ),
    ],
)
def test_malformed_or_oversized_forms_are_rejected(content_type: str | None, body: bytes) -> None:
    with pytest.raises(WebhookValidationError):
        parse_form(content_type, body)


def test_inbound_text_contract_uses_provider_aliases_and_keeps_body_intact() -> None:
    message = InboundPayload.model_validate(FORM)
    assert message.account_sid == ACCOUNT_SID
    assert message.message_sid == MESSAGE_SID
    assert message.body == FORM["Body"]
    assert message.from_number == FORM["From"]
    assert message.to_number == FORM["To"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("AccountSid", "ACshort"),
        ("MessageSid", "SMshort"),
        ("From", "+353855550100"),
        ("From", "whatsapp:+0353855550100"),
        ("To", "whatsapp:+"),
        ("Body", ""),
        ("Body", " \n\t"),
        ("Body", "a" * 1601),
        ("Body", "hello\x00"),
        ("NumMedia", "1"),
        ("NumMedia", "00"),
        ("NumMedia", "unknown"),
    ],
)
def test_inbound_rejects_unsupported_or_invalid_fields(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        InboundPayload.model_validate({**FORM, field: value})


@pytest.mark.parametrize("field", list(FORM))
def test_every_core_inbound_field_is_required(field: str) -> None:
    fields = dict(FORM)
    del fields[field]
    with pytest.raises(ValidationError):
        InboundPayload.model_validate(fields)


@pytest.mark.parametrize(
    "status",
    [
        "accepted",
        "queued",
        "sending",
        "sent",
        "delivered",
        "read",
        "failed",
        "undelivered",
        "canceled",
    ],
)
def test_delivery_callback_validates_status_and_optional_error(status: str) -> None:
    callback = StatusPayload.model_validate(
        {
            "AccountSid": ACCOUNT_SID,
            "MessageSid": MESSAGE_SID,
            "MessageStatus": status,
            "ErrorCode": "63016",
        }
    )
    assert callback.status == status and callback.error_code == "63016"


def test_empty_status_error_is_absent() -> None:
    callback = StatusPayload.model_validate(
        {
            "AccountSid": ACCOUNT_SID,
            "MessageSid": MESSAGE_SID,
            "MessageStatus": "delivered",
            "ErrorCode": "",
        }
    )
    assert callback.error_code is None


@pytest.mark.parametrize(
    "status,error", [("unknown", ""), ("sent", "provider details"), ("sent", "1" * 11)]
)
def test_invalid_status_and_error_fields_are_rejected(status: str, error: str) -> None:
    with pytest.raises(ValidationError):
        StatusPayload.model_validate(
            {
                "AccountSid": ACCOUNT_SID,
                "MessageSid": MESSAGE_SID,
                "MessageStatus": status,
                "ErrorCode": error,
            }
        )


def test_twilio_is_disabled_by_default_and_blank_environment_is_supported() -> None:
    settings = Settings(
        _env_file=None,
        database_url=DATABASE_URL,
        **dict.fromkeys((name for name in TWILIO if name != "twilio_enabled"), ""),
    )
    assert not settings.twilio_enabled


def test_complete_twilio_configuration_preserves_urls_and_redacts_credentials() -> None:
    settings = Settings(_env_file=None, database_url=DATABASE_URL, **TWILIO)
    assert settings.twilio_inbound_url == PUBLIC_URL
    assert settings.twilio_status_url == STATUS_URL
    assert ACCOUNT_SID not in repr(settings)
    assert TOKEN not in repr(settings)
    assert TOKEN not in settings.model_dump_json()


@pytest.mark.parametrize("field", [name for name in TWILIO if name != "twilio_enabled"])
def test_enabled_twilio_requires_every_configuration_value(field: str) -> None:
    values = dict(TWILIO)
    del values[field]
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=DATABASE_URL, **values)


@pytest.mark.parametrize(
    "field,value",
    [
        ("twilio_account_sid", "ACinvalid"),
        ("twilio_auth_token", " invalid-token "),
        ("twilio_whatsapp_number", "+353855550100"),
        ("twilio_inbound_url", "relative/webhook"),
        ("twilio_inbound_url", "https://user:secret@example.test/webhook"),
        ("twilio_inbound_url", "https://example.test/webhook#fragment"),
        ("twilio_inbound_url", "https://example.test:bad/webhook"),
        ("twilio_inbound_url", "https://example.test/web hook"),
        ("twilio_inbound_url", "https://example.test/webhook\x00"),
        ("twilio_inbound_url", "https://example.test\\other/webhook"),
        ("twilio_inbound_url", "https://example.test/webhook?value=é"),
        ("twilio_inbound_url", "https://example.test/é"),
        ("twilio_inbound_url", "https://example.test/webhook?value=%ZZ"),
        ("twilio_inbound_url", "https://example.test/webhook?value=%FF"),
        ("twilio_inbound_url", "https://example.test/webhook?missing_equals"),
        ("twilio_inbound_url", "https://example.test/webhook?value=first&value=second"),
        ("twilio_status_url", "https://example.test/status?attempt_id=already-set"),
        ("twilio_status_url", "https://example.test/status?attempt%5fid=already-set"),
    ],
)
def test_invalid_twilio_configuration_has_secret_safe_errors(field: str, value: str) -> None:
    with pytest.raises(ValidationError) as raised:
        Settings(_env_file=None, database_url=DATABASE_URL, **{**TWILIO, field: value})
    assert TOKEN not in str(raised.value)
    assert ACCOUNT_SID not in str(raised.value)


@pytest.mark.parametrize("field", ["twilio_inbound_url", "twilio_status_url"])
def test_production_twilio_webhooks_require_https(field: str) -> None:
    with pytest.raises(ValidationError, match="production Twilio webhooks require HTTPS"):
        Settings(
            _env_file=None,
            database_url=DATABASE_URL + "?sslmode=verify-full&sslrootcert=/certs/test.crt",
            environment="production",
            oidc_issuer="https://id.example.test/",
            oidc_audience="unit-api",
            oidc_jwks_url="https://id.example.test/jwks",
            **{**TWILIO, field: "http://api.example.test/webhook"},
        )
