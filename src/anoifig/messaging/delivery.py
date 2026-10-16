"""Callback correlation and monotonic provider delivery states."""

from urllib.parse import urlencode
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from anoifig.db.messaging_models import Message, Outbox
from anoifig.identity.service import AccessDenied
from anoifig.messaging.service import Route, authorise_route
from anoifig.messaging.webhooks import StatusPayload

STATUS_ORDER = {
    "pending": 0,
    "accepted": 10,
    "queued": 20,
    "sending": 30,
    "sent": 40,
    "canceled": 50,
    "failed": 50,
    "undelivered": 50,
    "delivered": 60,
    "read": 70,
}


def callback_url(base_url: str, attempt_id: UUID) -> str:
    separator = "&" if "?" in base_url else "?"
    return base_url + separator + urlencode({"attempt_id": str(attempt_id)})


def advance_status(message: Message, status: str, error_code: str | None = None) -> None:
    if STATUS_ORDER.get(status, -1) > STATUS_ORDER.get(message.status, -1):
        message.status = status
        message.processing_error = f"twilio_{error_code}" if error_code else None
    elif status == message.status and error_code and message.processing_error is None:
        message.processing_error = f"twilio_{error_code}"


def apply_callback(
    session: Session,
    route: Route,
    outbox_id: UUID,
    payload: StatusPayload,
    expected_sender: str,
) -> None:
    _, link = authorise_route(session, route)
    outbox = session.scalar(
        select(Outbox)
        .where(
            Outbox.id == outbox_id,
            Outbox.tenant_id == route.tenant_id,
            Outbox.phone_link_id == link.id,
        )
        .with_for_update()
    )
    if outbox is None:
        raise AccessDenied
    message = session.scalar(
        select(Message)
        .where(
            Message.id == outbox.message_id,
            Message.tenant_id == route.tenant_id,
            Message.direction == "outbound",
        )
        .with_for_update()
    )
    if (
        message is None
        or message.account_sid != payload.account_sid
        or (payload.from_number is not None and payload.from_number != expected_sender)
        or (payload.to_number is not None and payload.to_number != "whatsapp:" + link.phone)
        or (message.twilio_sid is not None and message.twilio_sid != payload.message_sid)
        or outbox.status not in {"dispatching", "uncertain", "sent"}
    ):
        raise AccessDenied
    message.twilio_sid = payload.message_sid
    advance_status(message, payload.status, payload.error_code)
    outbox.status = "sent"
    outbox.last_error = None
    outbox.lease_until = None
