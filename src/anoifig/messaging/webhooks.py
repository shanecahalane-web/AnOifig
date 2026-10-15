"""Bounded Twilio form parsing, SDK signature checks and text-only contracts.

The HTTP adapter supplies the configured public URL, never a Host or forwarded
header. Keep all form parameters intact until the signature has been verified.
"""

import base64
import binascii
import re
from collections.abc import Mapping
from typing import Annotated, Literal
from urllib.parse import parse_qsl

from pydantic import BaseModel, ConfigDict, Field, field_validator
from twilio.request_validator import RequestValidator  # type: ignore[import-untyped]

MAX_WEBHOOK_BYTES = 65536
MAX_FORM_FIELDS = 64
MESSAGE_SID_PATTERN = r"(?:SM|MM)[0-9a-fA-F]{32}"
WHATSAPP_ADDRESS_PATTERN = r"whatsapp:\+[1-9][0-9]{1,14}"

MessageStatus = Literal[
    "accepted",
    "queued",
    "sending",
    "sent",
    "delivered",
    "read",
    "failed",
    "undelivered",
    "canceled",
]


class WebhookValidationError(ValueError):
    """A malformed webhook; its message never includes submitted fields."""


def parse_form(content_type: str | None, body: bytes) -> dict[str, str]:
    """Parse a small, unambiguous UTF-8 form without multipart dependencies."""
    if content_type is None or len(content_type) > 256:
        raise WebhookValidationError("invalid form content type")
    parts = [part.strip().lower() for part in content_type.split(";")]
    if parts[0] != "application/x-www-form-urlencoded" or (
        len(parts) > 1 and parts[1:] not in (["charset=utf-8"], ['charset="utf-8"'])
    ):
        raise WebhookValidationError("invalid form content type")
    if not body or len(body) > MAX_WEBHOOK_BYTES:
        raise WebhookValidationError("invalid form size")
    try:
        decoded = body.decode("utf-8", errors="strict")
        if re.search(r"%(?![0-9a-fA-F]{2})", decoded):
            raise ValueError("invalid percent encoding")
        pairs = parse_qsl(
            decoded,
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
            max_num_fields=MAX_FORM_FIELDS,
        )
    except (UnicodeError, ValueError) as error:
        raise WebhookValidationError("invalid form encoding") from error
    parameters: dict[str, str] = {}
    for name, value in pairs:
        if (
            not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", name)
            or name in parameters
            or len(value) > 8192
            or "\x00" in value
        ):
            raise WebhookValidationError("invalid or repeated form field")
        parameters[name] = value
    return parameters


def verify_signature(
    *, public_url: str, parameters: Mapping[str, str], signature: str | None, auth_token: str
) -> bool:
    """Use Twilio's maintained validator against the exact configured URL."""
    if signature is None or len(signature) != 28 or not auth_token:
        return False
    try:
        if len(base64.b64decode(signature, validate=True)) != 20:
            return False
        return bool(RequestValidator(auth_token).validate(public_url, dict(parameters), signature))
    except (UnicodeError, ValueError, TypeError, binascii.Error):
        return False


class _TwilioPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)

    account_sid: Annotated[str, Field(alias="AccountSid", pattern=r"^AC[0-9a-fA-F]{32}$")]
    message_sid: Annotated[str, Field(alias="MessageSid", pattern=f"^{MESSAGE_SID_PATTERN}$")]


class InboundPayload(_TwilioPayload):
    from_number: Annotated[str, Field(alias="From", pattern=f"^{WHATSAPP_ADDRESS_PATTERN}$")]
    to_number: Annotated[str, Field(alias="To", pattern=f"^{WHATSAPP_ADDRESS_PATTERN}$")]
    body: Annotated[str, Field(alias="Body", min_length=1, max_length=1600)]
    # Require the provider field explicitly and never silently accept an attachment.
    num_media: Annotated[Literal["0"], Field(alias="NumMedia")]

    @field_validator("body")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("a nonempty text message is required")
        return value


class StatusPayload(_TwilioPayload):
    status: Annotated[MessageStatus, Field(alias="MessageStatus")]
    error_code: Annotated[str | None, Field(alias="ErrorCode", pattern=r"^[0-9]{1,10}$")] = None
    from_number: Annotated[
        str | None, Field(alias="From", pattern=f"^{WHATSAPP_ADDRESS_PATTERN}$")
    ] = None
    to_number: Annotated[str | None, Field(alias="To", pattern=f"^{WHATSAPP_ADDRESS_PATTERN}$")] = (
        None
    )

    @field_validator("error_code", mode="before")
    @classmethod
    def blank_error_is_absent(cls, value: object) -> object:
        return None if value == "" else value
