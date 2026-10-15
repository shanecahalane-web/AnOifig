"""HTTP boundary for signed Twilio requests and OIDC-authenticated phone linking."""

from datetime import datetime
from typing import Annotated, cast
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from anoifig.api.dependencies import IdentityDependency, SessionDependency
from anoifig.config import Settings
from anoifig.db.session import check_runtime_database
from anoifig.identity.service import AccessDenied
from anoifig.messaging.delivery import apply_callback, callback_url
from anoifig.messaging.service import (
    LinkConflict,
    accept_inbound,
    create_link,
    lookup_job,
    revoke_link,
)
from anoifig.messaging.webhooks import (
    MAX_WEBHOOK_BYTES,
    InboundPayload,
    StatusPayload,
    WebhookValidationError,
    parse_form,
    verify_signature,
)

router = APIRouter(tags=["messaging"])


class LinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    phone: Annotated[str, Field(pattern=r"^\+[1-9][0-9]{6,14}$")]


class LinkResponse(BaseModel):
    id: UUID
    token: str
    expires_at: datetime


@router.post("/v1/businesses/{tenant_id}/messaging/links", status_code=201)
def link_phone(
    tenant_id: UUID,
    body: LinkRequest,
    identity: IdentityDependency,
    session: SessionDependency,
) -> LinkResponse:
    try:
        challenge = create_link(session, identity, tenant_id, body.phone)
    except (LinkConflict, IntegrityError):
        raise HTTPException(409, "Unable to create phone link") from None
    return LinkResponse(id=challenge.id, token=challenge.token, expires_at=challenge.expires_at)


@router.delete("/v1/businesses/{tenant_id}/messaging/links/{link_id}", status_code=204)
def unlink_phone(
    tenant_id: UUID,
    link_id: UUID,
    identity: IdentityDependency,
    session: SessionDependency,
) -> Response:
    revoke_link(session, identity, tenant_id, link_id)
    return Response(status_code=204)


def configured(request: Request) -> Settings:
    settings = cast(Settings, request.app.state.settings)
    if not settings.twilio_enabled:
        raise HTTPException(503, "Messaging unavailable")
    return settings


async def signed_form(request: Request, settings: Settings, public_url: str) -> dict[str, str]:
    if request.scope.get("query_string", b"") != urlsplit(public_url).query.encode("ascii"):
        raise HTTPException(403, "Request rejected")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_WEBHOOK_BYTES:
            raise HTTPException(413, "Request too large")
        body.extend(chunk)
    try:
        parameters = parse_form(request.headers.get("content-type"), bytes(body))
    except WebhookValidationError:
        raise HTTPException(400, "Invalid webhook") from None
    signatures = request.headers.getlist("x-twilio-signature")
    assert settings.twilio_auth_token is not None
    if len(signatures) != 1 or not verify_signature(
        public_url=public_url,
        parameters=parameters,
        signature=signatures[0],
        auth_token=settings.twilio_auth_token.get_secret_value(),
    ):
        raise HTTPException(403, "Request rejected")
    return parameters


def persist_inbound(engine: Engine, settings: Settings, payload: InboundPayload) -> None:
    # The commit completes before the HTTP acknowledgement, including on duplicates.
    with Session(engine) as session, session.begin():
        check_runtime_database(
            session.connection(), require_tls=settings.environment == "production"
        )
        try:
            accept_inbound(session, payload)
        except IntegrityError:
            raise AccessDenied from None


@router.post("/webhooks/twilio/inbound")
async def inbound(request: Request) -> Response:
    settings = configured(request)
    assert settings.twilio_inbound_url is not None and settings.twilio_account_sid is not None
    parameters = await signed_form(request, settings, settings.twilio_inbound_url)
    try:
        payload = InboundPayload.model_validate(parameters)
    except ValidationError:
        raise HTTPException(400, "Invalid webhook") from None
    if (
        payload.account_sid != settings.twilio_account_sid.get_secret_value()
        or payload.to_number != settings.twilio_whatsapp_number
    ):
        raise HTTPException(403, "Request rejected")
    await run_in_threadpool(
        persist_inbound, cast(Engine, request.app.state.engine), settings, payload
    )
    return Response(content="<Response/>", media_type="application/xml")


def persist_status(
    engine: Engine,
    settings: Settings,
    attempt_id: UUID,
    payload: StatusPayload,
) -> None:
    with Session(engine) as session, session.begin():
        check_runtime_database(
            session.connection(), require_tls=settings.environment == "production"
        )
        job = lookup_job(session, attempt_id)
        if job is None or job.kind != "outbound":
            raise AccessDenied
        assert settings.twilio_whatsapp_number is not None
        apply_callback(session, job.route, attempt_id, payload, settings.twilio_whatsapp_number)


@router.post("/webhooks/twilio/status")
async def status_callback(request: Request, attempt_id: UUID) -> Response:
    settings = configured(request)
    assert settings.twilio_status_url is not None and settings.twilio_account_sid is not None
    parameters = await signed_form(
        request, settings, callback_url(settings.twilio_status_url, attempt_id)
    )
    try:
        payload = StatusPayload.model_validate(parameters)
    except ValidationError:
        raise HTTPException(400, "Invalid webhook") from None
    if payload.account_sid != settings.twilio_account_sid.get_secret_value():
        raise HTTPException(403, "Request rejected")
    await run_in_threadpool(
        persist_status,
        cast(Engine, request.app.state.engine),
        settings,
        attempt_id,
        payload,
    )
    return Response(status_code=204)
