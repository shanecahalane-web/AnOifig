"""Small versioned HTTP adapter for identity and customer domain services."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import Engine

from anoifig.api.dependencies import IdentityDependency, SessionDependency
from anoifig.api.schemas import (
    CustomerCreate,
    CustomerResponse,
    MembershipResponse,
    MeResponse,
)
from anoifig.config import Settings
from anoifig.customers import service as customers
from anoifig.db.session import check_runtime_database
from anoifig.identity import service as identity_service

router = APIRouter()


@router.get("/health/live", tags=["health"])
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", tags=["health"])
def ready(request: Request) -> dict[str, str]:
    engine = cast(Engine, request.app.state.engine)
    settings = cast(Settings, request.app.state.settings)
    with engine.connect() as connection, connection.begin():
        check_runtime_database(connection, require_tls=settings.environment == "production")
    return {"status": "ok"}


@router.get("/v1/me", response_model=MeResponse, tags=["identity"])
def me(identity: IdentityDependency, session: SessionDependency) -> MeResponse:
    user = identity_service.current_user(session, identity)
    memberships = identity_service.own_memberships(session, user)
    return MeResponse(
        id=user.id,
        memberships=[MembershipResponse.model_validate(membership) for membership in memberships],
    )


@router.get(
    "/v1/businesses/{tenant_id}/customers",
    response_model=list[CustomerResponse],
    tags=["customers"],
)
def list_customers(
    tenant_id: UUID,
    identity: IdentityDependency,
    session: SessionDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
) -> list[CustomerResponse]:
    return [
        CustomerResponse.model_validate(customer)
        for customer in customers.list_customers(
            session, identity, tenant_id, limit=limit, offset=offset
        )
    ]


@router.post(
    "/v1/businesses/{tenant_id}/customers",
    response_model=CustomerResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["customers"],
)
def create_customer(
    tenant_id: UUID,
    body: CustomerCreate,
    identity: IdentityDependency,
    session: SessionDependency,
) -> CustomerResponse:
    customer = customers.create_customer(session, identity, tenant_id, body)
    return CustomerResponse.model_validate(customer)


@router.get(
    "/v1/businesses/{tenant_id}/customers/{customer_id}",
    response_model=CustomerResponse,
    tags=["customers"],
)
def get_customer(
    tenant_id: UUID,
    customer_id: UUID,
    identity: IdentityDependency,
    session: SessionDependency,
) -> CustomerResponse:
    return CustomerResponse.model_validate(
        customers.get_customer(session, identity, tenant_id, customer_id)
    )
