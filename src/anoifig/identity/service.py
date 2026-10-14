"""Resolve current database authorisation for every request."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from anoifig.db.models import Business, Membership, User
from anoifig.db.session import set_tenant_context
from anoifig.identity.auth import VerifiedIdentity


class AccessDenied(Exception):
    """An identity is inactive, unmapped, or not authorised for this operation."""


@dataclass(frozen=True, slots=True)
class TenantAccess:
    tenant_id: UUID
    user_id: UUID
    role: str


def current_user(session: Session, identity: VerifiedIdentity) -> User:
    user = session.scalar(
        select(User).where(
            User.identity_provider_issuer == identity.issuer,
            User.identity_provider_subject == identity.subject,
            User.active.is_(True),
        )
    )
    if user is None:
        raise AccessDenied
    return user


def own_memberships(session: Session, user: User) -> list[Membership]:
    return list(
        session.scalars(
            select(Membership)
            .join(Business, Business.id == Membership.tenant_id)
            .where(
                Membership.user_id == user.id,
                Membership.active.is_(True),
                Business.active.is_(True),
            )
            .order_by(Membership.tenant_id)
        )
    )


def authorise_tenant(
    session: Session, identity: VerifiedIdentity, tenant_id: UUID, *, write: bool = False
) -> TenantAccess:
    set_tenant_context(session, tenant_id)
    user = current_user(session, identity)
    membership = session.scalar(
        select(Membership)
        .join(Business, Business.id == Membership.tenant_id)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.user_id == user.id,
            Membership.active.is_(True),
            Business.active.is_(True),
        )
    )
    if membership is None or (write and membership.role not in {"owner", "staff"}):
        raise AccessDenied
    return TenantAccess(tenant_id=tenant_id, user_id=user.id, role=membership.role)
