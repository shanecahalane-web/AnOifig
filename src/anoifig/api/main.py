"""FastAPI application factory; importing the module has no network side effects."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import SQLAlchemyError

from anoifig.api.routes import router
from anoifig.config import Settings, get_settings
from anoifig.customers.service import CustomerNotFound
from anoifig.db.session import UnsafeDatabaseConfiguration, build_engine
from anoifig.identity.auth import OIDCTokenVerifier, TokenVerifier
from anoifig.identity.service import AccessDenied
from anoifig.messaging.routes import router as messaging_router


def create_app(
    settings: Settings | None = None, token_verifier: TokenVerifier | None = None
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configured = settings if settings is not None else get_settings()
        if token_verifier is not None and configured.environment != "test":
            raise ValueError("custom token verification is allowed only in the test environment")
        engine = build_engine(configured)
        application.state.settings = configured
        application.state.engine = engine
        application.state.token_verifier = (
            token_verifier if token_verifier is not None else OIDCTokenVerifier(configured)
        )
        try:
            yield
        finally:
            engine.dispose()

    application = FastAPI(
        title="An Oifig API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    application.include_router(router)
    application.include_router(messaging_router)

    @application.exception_handler(AccessDenied)
    async def access_denied(request: Request, exc: AccessDenied) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": "Access denied"})

    @application.exception_handler(CustomerNotFound)
    async def customer_not_found(request: Request, exc: CustomerNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Customer not found"})

    @application.exception_handler(SQLAlchemyError)
    @application.exception_handler(UnsafeDatabaseConfiguration)
    async def database_unavailable(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "Database unavailable"})

    @application.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    return application


app = create_app()
