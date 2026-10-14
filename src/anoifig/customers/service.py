"""Customer commands require fresh tenant authorisation and explicit scoping."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from anoifig.customers.schemas import CustomerCreate
from anoifig.db.models import Customer
from anoifig.identity.auth import VerifiedIdentity
from anoifig.identity.service import authorise_tenant


class CustomerNotFound(Exception):
    """The record is absent from the caller's authorised business."""


def list_customers(
    session: Session,
    identity: VerifiedIdentity,
    tenant_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[Customer]:
    access = authorise_tenant(session, identity, tenant_id)
    return list(
        session.scalars(
            select(Customer)
            .where(Customer.tenant_id == access.tenant_id)
            .order_by(Customer.created_at, Customer.id)
            .limit(limit)
            .offset(offset)
        )
    )


def get_customer(
    session: Session, identity: VerifiedIdentity, tenant_id: UUID, customer_id: UUID
) -> Customer:
    access = authorise_tenant(session, identity, tenant_id)
    customer = session.scalar(
        select(Customer).where(Customer.tenant_id == access.tenant_id, Customer.id == customer_id)
    )
    if customer is None:
        raise CustomerNotFound
    return customer


def create_customer(
    session: Session, identity: VerifiedIdentity, tenant_id: UUID, data: CustomerCreate
) -> Customer:
    access = authorise_tenant(session, identity, tenant_id, write=True)
    customer = Customer(
        tenant_id=access.tenant_id,
        name=data.name,
        billing_address=data.billing_address,
        email=data.email,
        phone=data.phone,
        vat_number=data.vat_number,
    )
    session.add(customer)
    session.flush()
    session.refresh(customer)
    return customer
