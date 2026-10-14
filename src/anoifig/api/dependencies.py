"""HTTP authentication and one authorised database transaction per request."""

from collections.abc import Iterator
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from anoifig.config import Settings
from anoifig.db.session import (
    UnsafeDatabaseConfiguration,
    check_runtime_database,
    set_identity_context,
)
from anoifig.identity.auth import (
    AuthenticationUnavailable,
    InvalidToken,
    TokenVerifier,
    VerifiedIdentity,
)

bearer = HTTPBearer(auto_error=False)


def verified_identity(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> VerifiedIdentity:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    verifier = cast(TokenVerifier, request.app.state.token_verifier)
    try:
        return verifier.verify(credentials.credentials)
    except InvalidToken:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except AuthenticationUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication unavailable",
        ) from None


IdentityDependency = Annotated[VerifiedIdentity, Depends(verified_identity)]


def identity_session(request: Request, identity: IdentityDependency) -> Iterator[Session]:
    engine = cast(Engine, request.app.state.engine)
    settings = cast(Settings, request.app.state.settings)
    try:
        with Session(engine, expire_on_commit=False) as session, session.begin():
            check_runtime_database(
                session.connection(), require_tls=settings.environment == "production"
            )
            set_identity_context(session, identity)
            yield session
    except (SQLAlchemyError, UnsafeDatabaseConfiguration):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable"
        ) from None


# Finish the transaction before a success response is sent; commit errors must not be hidden.
SessionDependency = Annotated[Session, Depends(identity_session, scope="function")]
