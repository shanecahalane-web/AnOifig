"""Versioned public API shapes, independent of persistence internals."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from anoifig.customers.schemas import CustomerCreate as CustomerCreate


class CustomerResponse(CustomerCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime


class MembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    role: str


class MeResponse(BaseModel):
    id: UUID
    memberships: list[MembershipResponse]
