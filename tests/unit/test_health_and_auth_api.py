"""Unauthenticated health checks and protected routes fail safely without dependencies."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from anoifig.api.main import create_app
from anoifig.config import Settings
from anoifig.identity.auth import OIDCTokenVerifier, VerifiedIdentity


@pytest.fixture
def client() -> Iterator[TestClient]:
    # An unbound local port proves that liveness/auth failures need no database.
    settings = Settings(
        _env_file=None,
        environment="test",
        oidc_issuer=None,
        oidc_audience=None,
        oidc_jwks_url=None,
        database_url="postgresql+psycopg://unit:unit-only-secret@127.0.0.1:1/anoifig_unit",
    )
    with TestClient(create_app(settings=settings)) as test_client:
        yield test_client


def test_liveness_does_not_require_database_or_authentication(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_fails_when_database_is_unavailable(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert "unit-only-secret" not in response.text
    assert "127.0.0.1" not in response.text
    assert "psycopg" not in response.text


def test_protected_route_requires_bearer_credentials(client: TestClient) -> None:
    response = client.get("/v1/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")


@pytest.mark.parametrize("authorization", ["Basic dXNlcjpwYXNz", "Bearer", "Bearer "])
def test_invalid_authentication_scheme_is_rejected(client: TestClient, authorization: str) -> None:
    response = client.get("/v1/me", headers={"Authorization": authorization})
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")


def test_oidc_configuration_missing_fails_closed(client: TestClient) -> None:
    response = client.get("/v1/me", headers={"Authorization": "Bearer test-untrusted-token"})
    assert response.status_code == 503
    assert "test-untrusted-token" not in response.text
    assert "unit-only-secret" not in response.text


def test_user_and_tenant_headers_never_authenticate(client: TestClient) -> None:
    response = client.get(
        "/v1/me",
        headers={
            "X-User-Id": "11111111-1111-1111-1111-111111111111",
            "X-Tenant-Id": "22222222-2222-2222-2222-222222222222",
        },
    )
    assert response.status_code == 401


def test_configured_identity_rejects_malformed_tokens_without_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_remote_request(*args: object, **kwargs: object) -> None:
        pytest.fail("a malformed token must not trigger a JWKS request")

    monkeypatch.setattr("urllib.request.OpenerDirector.open", unexpected_remote_request)
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url="postgresql+psycopg://unit:unit-only-secret@127.0.0.1:1/anoifig_unit",
        oidc_issuer="https://identity.example.test/",
        oidc_audience="anoifig-api",
        oidc_jwks_url="https://identity.example.test/.well-known/jwks.json",
    )
    with TestClient(create_app(settings=settings)) as client:
        response = client.get("/v1/me", headers={"Authorization": "Bearer not-a-valid-jwt"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")
    assert "not-a-valid-jwt" not in response.text
    assert "unit-only-secret" not in response.text


@pytest.mark.parametrize(
    ("media_type", "purpose_claims"),
    [
        ("JWT", {"nonce": "same-provider-id-token"}),
        ("refresh+jwt", {"token_use": "refresh"}),
        ("at+jwt", {"token_use": "id"}),
        ("at+jwt", {"token_use": "refresh"}),
        ("at+jwt", {"nonce": "same-provider-id-token"}),
    ],
)
def test_signed_token_substitution_is_unauthenticated_before_database_access(
    signing_key: rsa.RSAPrivateKey,
    monkeypatch: pytest.MonkeyPatch,
    media_type: str,
    purpose_claims: dict[str, Any],
) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url="postgresql+psycopg://unit:unit-only-secret@127.0.0.1:1/anoifig_unit",
        oidc_issuer="https://identity.example.test/",
        oidc_audience="anoifig-api",
        oidc_jwks_url="https://identity.example.test/.well-known/jwks.json",
    )
    verifier = OIDCTokenVerifier(settings)
    trusted_key = jwt.PyJWK.from_json(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    monkeypatch.setattr(
        verifier.jwks_client, "get_signing_key_from_jwt", lambda _token: trusted_key
    )
    now = datetime.now(UTC)
    # The substituted token has the same trusted key, issuer, API audience and
    # subject as an otherwise valid access token: purpose is the only mismatch.
    claims = {
        "iss": settings.oidc_issuer,
        "aud": settings.oidc_audience,
        "sub": "owner-a",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "client_id": "anoifig-test-portal",
        "jti": "substitution-test-token",
        **purpose_claims,
    }
    token = jwt.encode(
        claims, signing_key, algorithm="RS256", headers={"kid": "test-key", "typ": media_type}
    )

    def unexpected_database_access(*args: Any, **kwargs: Any) -> None:
        pytest.fail("a substituted ID/refresh token must not reach the database")

    with TestClient(create_app(settings, token_verifier=verifier)) as client:
        monkeypatch.setattr(client.app.state.engine, "connect", unexpected_database_access)
        response = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")
    assert token not in response.text


@pytest.mark.parametrize("environment", ["development", "production"])
def test_custom_verifier_cannot_bypass_managed_authentication_outside_tests(
    environment: str,
) -> None:
    class UntrustedVerifier:
        def verify(self, token: str) -> VerifiedIdentity:
            pytest.fail("custom verification must be rejected before authentication")

    settings = Settings(
        _env_file=None,
        environment=environment,
        database_url=(
            "postgresql+psycopg://unit:unit-only-secret@db.example.test:5432/anoifig_unit"
            "?sslmode=verify-full&sslrootcert=/run/secrets/postgresql-root.crt"
        ),
        oidc_issuer="https://identity.example.test/",
        oidc_audience="anoifig-api",
        oidc_jwks_url="https://identity.example.test/.well-known/jwks.json",
    )
    with (
        pytest.raises(ValueError, match="only in the test environment"),
        TestClient(create_app(settings=settings, token_verifier=UntrustedVerifier())),
    ):
        pytest.fail("application startup must reject custom identity verification")
