"""Text messaging providers with deliberately conservative send retries.

Twilio message creation has no documented deduplication key. A transport timeout
or server error can occur after acceptance, so those outcomes must be reconciled
with a callback/operator rather than blindly sending the customer another copy.
The caller also owns the WhatsApp customer-service window policy.
"""

import logging
import re
from dataclasses import dataclass
from typing import Protocol, cast
from urllib.parse import urlsplit
from uuid import uuid4

from twilio.base.exceptions import TwilioRestException  # type: ignore[import-untyped]
from twilio.http.http_client import TwilioHttpClient  # type: ignore[import-untyped]
from twilio.rest import Client  # type: ignore[import-untyped]

from anoifig.messaging.webhooks import MESSAGE_SID_PATTERN, WHATSAPP_ADDRESS_PATTERN


@dataclass(frozen=True)
class SendResult:
    sid: str
    status: str


class SafeRetry(Exception):
    """The provider explicitly rejected the request without creating a message."""

    def __init__(self, retry_after: int = 60) -> None:
        super().__init__("provider rate limit")
        self.retry_after = max(1, min(retry_after, 3600))


class PermanentFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__("provider rejected message")
        self.code = code


class AmbiguousFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__("provider acceptance is unknown")
        self.code = code


class MessagingProvider(Protocol):
    def send_text(self, *, to: str, body: str, callback_url: str) -> SendResult: ...


class _CreatedMessage(Protocol):
    sid: object
    status: object


class MessageCreator(Protocol):
    """Small SDK seam so tests never need credentials or a live network."""

    def create(
        self, *, to: str, from_: str, body: str, status_callback: str
    ) -> _CreatedMessage: ...


def _validate_send(to: str, body: str, callback_url: str) -> None:
    if (
        not re.fullmatch(WHATSAPP_ADDRESS_PATTERN, to)
        or not body.strip()
        or len(body) > 1600
        or "\x00" in body
    ):
        raise PermanentFailure("invalid_text_request")
    try:
        parsed = urlsplit(callback_url)
        _ = parsed.port
    except ValueError as error:
        raise PermanentFailure("invalid_callback_url") from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or any(character.isspace() for character in callback_url)
    ):
        raise PermanentFailure("invalid_callback_url")


class TwilioMessagingProvider:
    def __init__(
        self,
        *,
        account_sid: str,
        auth_token: str,
        whatsapp_number: str,
        timeout: int = 10,
        message_creator: MessageCreator | None = None,
    ) -> None:
        self._whatsapp_number = whatsapp_number
        if message_creator is None:
            # SDK HTTP logs can contain text, phone numbers and auth headers.
            # This dedicated logger has no handlers and never propagates them.
            silent_logger = logging.Logger("anoifig.twilio.transport", level=logging.CRITICAL + 1)
            silent_logger.propagate = False
            transport = TwilioHttpClient(timeout=timeout, max_retries=0, logger=silent_logger)
            client = Client(account_sid, auth_token, http_client=transport)
            message_creator = cast(MessageCreator, client.messages)
        self._messages = message_creator

    def send_text(self, *, to: str, body: str, callback_url: str) -> SendResult:
        _validate_send(to, body, callback_url)
        try:
            message = self._messages.create(
                to=to, from_=self._whatsapp_number, body=body, status_callback=callback_url
            )
            sid, status = message.sid, message.status
        except TwilioRestException as error:
            if error.status == 429:
                # SDK exceptions do not expose Retry-After; use a conservative
                # minimum delay and let the outbox apply bounded backoff.
                raise SafeRetry(retry_after=60) from None
            code = f"twilio_{error.code}" if isinstance(error.code, int) else f"http_{error.status}"
            if 400 <= error.status < 500 and error.status != 408:
                raise PermanentFailure(code) from None
            raise AmbiguousFailure(code) from None
        except Exception:
            # Includes network timeouts, connection resets and malformed SDK
            # responses. None prove that the provider did not accept the send.
            raise AmbiguousFailure("transport_or_response_error") from None
        if (
            not isinstance(sid, str)
            or not re.fullmatch(MESSAGE_SID_PATTERN, sid)
            or not isinstance(status, str)
            or status not in {"accepted", "queued", "sending", "sent", "delivered", "read"}
        ):
            raise AmbiguousFailure("invalid_provider_response")
        return SendResult(sid=sid, status=status)


class LocalMessagingProvider:
    """Explicit local simulator; never makes HTTP requests or delivers a text."""

    def send_text(self, *, to: str, body: str, callback_url: str) -> SendResult:
        _validate_send(to, body, callback_url)
        return SendResult(sid=f"SM{uuid4().hex}", status="sent")
