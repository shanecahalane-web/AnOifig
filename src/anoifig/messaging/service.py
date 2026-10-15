"""Authorised linking and durable inbound acceptance, independent of HTTP."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from anoifig.db.messaging_models import Conversation, Message, PhoneLink
from anoifig.db.session import set_identity_context
from anoifig.identity.auth import VerifiedIdentity
from anoifig.identity.service import AccessDenied, TenantAccess, authorise_tenant
from anoifig.messaging.webhooks import InboundPayload

TARA_RESPONSE = (
    "Hi, I'm Tara, your An Oifig assistant. Your message has been received successfully."
)


class LinkConflict(Exception):
    """A phone link cannot currently be created or activated."""


@dataclass(frozen=True)
class LinkChallenge:
    id: UUID
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class Route:
    tenant_id: UUID
    link_id: UUID
    identity: VerifiedIdentity


@dataclass(frozen=True)
class Job:
    id: UUID
    kind: str
    entity_id: UUID
    route: Route


def lookup_job(session: Session, job_id: UUID) -> Job | None:
    row = (
        session.execute(
            text("SELECT * FROM public.messaging_lookup_job(:id)"),
            {"id": job_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return Job(
        row["job_id"],
        row["kind"],
        row["entity_id"],
        Route(row["tenant_id"], row["link_id"], VerifiedIdentity(row["issuer"], row["subject"])),
    )


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_link(
    session: Session, identity: VerifiedIdentity, tenant_id: UUID, phone: str
) -> LinkChallenge:
    access = authorise_tenant(session, identity, tenant_id, write=True)
    now = datetime.now(UTC)
    pending = session.scalar(
        select(func.count())
        .select_from(PhoneLink)
        .where(
            PhoneLink.tenant_id == tenant_id,
            PhoneLink.user_id == access.user_id,
            PhoneLink.revoked_at.is_(None),
            PhoneLink.verified_at.is_(None),
            PhoneLink.expires_at > now,
        )
    )
    if pending is not None and pending >= 5:
        raise LinkConflict
    token = secrets.token_urlsafe(32)
    link = PhoneLink(
        id=uuid4(),
        tenant_id=tenant_id,
        user_id=access.user_id,
        phone=phone,
        issuer=identity.issuer,
        subject=identity.subject,
        token_hash=token_digest(token),
        expires_at=now + timedelta(minutes=10),
    )
    session.add(link)
    session.flush()
    return LinkChallenge(link.id, token, link.expires_at)


def revoke_link(
    session: Session, identity: VerifiedIdentity, tenant_id: UUID, link_id: UUID
) -> None:
    access = authorise_tenant(session, identity, tenant_id, write=True)
    link = session.scalar(
        select(PhoneLink)
        .where(
            PhoneLink.id == link_id,
            PhoneLink.tenant_id == tenant_id,
            PhoneLink.user_id == access.user_id,
        )
        .with_for_update()
    )
    if link is None:
        raise AccessDenied
    if link.revoked_at is None:
        link.revoked_at = datetime.now(UTC)
    link.token_hash = None


def resolve_phone(session: Session, phone: str, token: str | None = None) -> Route:
    if token is None:
        result = (
            session.execute(
                text("SELECT * FROM public.messaging_route_phone(:phone)"), {"phone": phone}
            )
            .mappings()
            .one_or_none()
        )
    else:
        result = (
            session.execute(
                text("SELECT * FROM public.messaging_redeem_phone(:phone, :digest)"),
                {"phone": phone, "digest": token_digest(token)},
            )
            .mappings()
            .one_or_none()
        )
    if result is None:
        raise AccessDenied
    route = Route(
        result["tenant_id"],
        result["link_id"],
        VerifiedIdentity(result["issuer"], result["subject"]),
    )
    authorise_route(session, route)
    return route


def authorise_route(session: Session, route: Route) -> tuple[TenantAccess, PhoneLink]:
    set_identity_context(session, route.identity)
    access = authorise_tenant(session, route.identity, route.tenant_id, write=True)
    link = session.scalar(
        select(PhoneLink).where(
            PhoneLink.id == route.link_id,
            PhoneLink.tenant_id == route.tenant_id,
            PhoneLink.user_id == access.user_id,
            PhoneLink.verified_at.is_not(None),
            PhoneLink.revoked_at.is_(None),
        )
    )
    if link is None:
        raise AccessDenied
    return access, link


def accept_inbound(session: Session, payload: InboundPayload) -> UUID | None:
    phone = payload.from_number.removeprefix("whatsapp:")
    # A challenge binds a verified OIDC member, a business and the expected phone.
    # Possession of the phone alone never creates a membership.
    if payload.body.startswith("LINK "):
        token = payload.body[5:].strip()
        if not 40 <= len(token) <= 100:
            raise AccessDenied
        resolve_phone(session, phone, token)
        return None
    route = resolve_phone(session, phone)
    access, link = authorise_route(session, route)
    now = datetime.now(UTC)
    conversation_id = uuid4()
    session.execute(
        insert(Conversation)
        .values(
            id=conversation_id,
            tenant_id=route.tenant_id,
            phone_link_id=link.id,
            user_id=access.user_id,
            last_inbound_at=now,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "phone_link_id"])
    )
    conversation = session.scalar(
        select(Conversation)
        .where(
            Conversation.tenant_id == route.tenant_id,
            Conversation.phone_link_id == link.id,
        )
        .with_for_update()
    )
    if conversation is None:
        raise AccessDenied
    message_id = session.scalar(
        insert(Message)
        .values(
            id=uuid4(),
            tenant_id=route.tenant_id,
            conversation_id=conversation.id,
            phone_link_id=link.id,
            user_id=access.user_id,
            direction="inbound",
            body=payload.body,
            twilio_sid=payload.message_sid,
            account_sid=payload.account_sid,
            status="received",
            received_at=now,
        )
        .on_conflict_do_nothing()
        .returning(Message.id)
    )
    # Replays must not reopen the WhatsApp service window.
    if message_id is not None:
        conversation.last_inbound_at = now
    return message_id
