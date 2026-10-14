"""Verify the API's RFC 9068 JWT access-token contract against trusted OIDC keys."""

from dataclasses import dataclass
from typing import Protocol

import jwt
from jwt import PyJWKClient

from anoifig.config import Settings


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    issuer: str
    subject: str


class InvalidToken(Exception):
    """An untrusted bearer token could not be authenticated."""


class AuthenticationUnavailable(Exception):
    """The trusted identity provider is unconfigured or unavailable."""


class TokenVerifier(Protocol):
    def verify(self, token: str) -> VerifiedIdentity: ...


class OIDCTokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self.issuer = settings.oidc_issuer
        self.audience = settings.oidc_audience
        self.jwks_client = (
            PyJWKClient(
                settings.oidc_jwks_url,
                cache_jwk_set=True,
                lifespan=300,
                timeout=settings.oidc_http_timeout,
            )
            if settings.oidc_jwks_url
            else None
        )

    def verify(self, token: str) -> VerifiedIdentity:
        if self.jwks_client is None or self.issuer is None or self.audience is None:
            raise AuthenticationUnavailable
        if len(token) > 16384:
            raise InvalidToken
        try:
            header = jwt.get_unverified_header(token)
            if (
                header.get("alg") != "RS256"
                or header.get("typ") not in ("at+jwt", "application/at+jwt")
                or not isinstance(header.get("kid"), str)
                or not 1 <= len(header["kid"]) <= 256
                or "crit" in header
                or "b64" in header
            ):
                raise InvalidToken
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
            if signing_key.algorithm_name != "RS256":
                raise InvalidToken
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.audience,
                options={
                    "require": ["exp", "iat", "iss", "aud", "sub", "client_id", "jti"],
                    "strict_aud": True,
                },
            )
            # Check purpose claims only after verifying the signature. A matching
            # issuer/audience alone must not allow an ID or refresh token to be
            # substituted for the API's explicitly typed access-token profile.
            if claims.get("token_use", "access") != "access" or any(
                claim in claims for claim in ("nonce", "at_hash", "c_hash")
            ):
                raise InvalidToken
            for claim in ("sub", "client_id", "jti"):
                value = claims[claim]
                if not isinstance(value, str) or not value.strip() or len(value) > 255:
                    raise InvalidToken
            subject = claims["sub"]
            return VerifiedIdentity(issuer=self.issuer, subject=subject)
        except jwt.PyJWKClientConnectionError:
            raise AuthenticationUnavailable from None
        except (jwt.PyJWTError, TypeError, ValueError, KeyError):
            raise InvalidToken from None
