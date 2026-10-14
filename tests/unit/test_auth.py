"""Exercise managed identity verification using real test-only RSA signatures."""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any
from urllib.error import URLError

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from anoifig.config import Settings
from anoifig.identity.auth import (
    AuthenticationUnavailable,
    InvalidToken,
    OIDCTokenVerifier,
    VerifiedIdentity,
)

ISSUER = "https://identity.example.test/"
AUDIENCE = "anoifig-api"
KEY_ID = "unit-test-key"


@pytest.fixture(scope="module")
def signing_key() -> rsa.RSAPrivateKey:
    # Test keys are generated in memory and never committed or used by the app.
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def claims() -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "test-identity-subject",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }


def auth_settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url="postgresql+psycopg://test:local-only@localhost:5432/anoifig_unit",
        oidc_issuer=ISSUER,
        oidc_audience=AUDIENCE,
        oidc_jwks_url="https://identity.example.test/.well-known/jwks.json",
    )


def public_jwk(signing_key: rsa.RSAPrivateKey) -> dict[str, Any]:
    jwk: dict[str, Any] = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    return {**jwk, "kid": KEY_ID, "use": "sig", "alg": "RS256"}


def signed_token(signing_key: rsa.RSAPrivateKey, claims: dict[str, Any]) -> str:
    return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": KEY_ID})


@pytest.fixture
def verifier(signing_key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch) -> OIDCTokenVerifier:
    verifier = OIDCTokenVerifier(auth_settings())
    key = jwt.PyJWK.from_dict(public_jwk(signing_key))
    monkeypatch.setattr(verifier.jwks_client, "get_signing_key_from_jwt", lambda token: key)
    return verifier


def test_valid_signed_identity(
    verifier: OIDCTokenVerifier, signing_key: rsa.RSAPrivateKey, claims: dict[str, Any]
) -> None:
    assert verifier.verify(signed_token(signing_key, claims)) == VerifiedIdentity(
        issuer=ISSUER, subject="test-identity-subject"
    )


@pytest.mark.parametrize("claim", ["iss", "aud", "sub", "exp", "iat"])
def test_required_claims_cannot_be_omitted(
    verifier: OIDCTokenVerifier,
    signing_key: rsa.RSAPrivateKey,
    claims: dict[str, Any],
    claim: str,
) -> None:
    del claims[claim]
    with pytest.raises(InvalidToken):
        verifier.verify(signed_token(signing_key, claims))


@pytest.mark.parametrize(
    ("claim", "value"),
    [("iss", "https://attacker.example.test/"), ("aud", "another-api"), ("sub", "")],
)
def test_wrong_identity_claims_are_rejected(
    verifier: OIDCTokenVerifier,
    signing_key: rsa.RSAPrivateKey,
    claims: dict[str, Any],
    claim: str,
    value: str,
) -> None:
    claims[claim] = value
    with pytest.raises(InvalidToken):
        verifier.verify(signed_token(signing_key, claims))


@pytest.mark.parametrize("claim", ["iat", "nbf"])
def test_future_token_is_rejected(
    verifier: OIDCTokenVerifier,
    signing_key: rsa.RSAPrivateKey,
    claims: dict[str, Any],
    claim: str,
) -> None:
    claims[claim] = int((datetime.now(UTC) + timedelta(minutes=10)).timestamp())
    with pytest.raises(InvalidToken):
        verifier.verify(signed_token(signing_key, claims))


def test_expired_token_is_rejected(
    verifier: OIDCTokenVerifier, signing_key: rsa.RSAPrivateKey, claims: dict[str, Any]
) -> None:
    claims["exp"] = int((datetime.now(UTC) - timedelta(minutes=10)).timestamp())
    with pytest.raises(InvalidToken):
        verifier.verify(signed_token(signing_key, claims))


def test_signature_from_an_untrusted_key_is_rejected(
    verifier: OIDCTokenVerifier, claims: dict[str, Any]
) -> None:
    untrusted_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(InvalidToken):
        verifier.verify(signed_token(untrusted_key, claims))


def test_unsigned_token_is_rejected(verifier: OIDCTokenVerifier, claims: dict[str, Any]) -> None:
    token = jwt.encode(claims, key="", algorithm="none", headers={"kid": KEY_ID})
    with pytest.raises(InvalidToken):
        verifier.verify(token)


def test_public_key_cannot_be_reused_as_an_hmac_secret(
    verifier: OIDCTokenVerifier, signing_key: rsa.RSAPrivateKey, claims: dict[str, Any]
) -> None:
    public_der = signing_key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    # Build the attacker-controlled token directly: PyJWT also blocks signing
    # HMAC with RSA material, which must not hide a verifier regression here.
    header = {"alg": "HS256", "kid": KEY_ID, "typ": "JWT"}
    parts = [
        base64.urlsafe_b64encode(json.dumps(part).encode()).rstrip(b"=")
        for part in (header, claims)
    ]
    signing_input = b".".join(parts)
    signature = hmac.new(public_der, signing_input, hashlib.sha256).digest()
    token = (signing_input + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")).decode()
    with pytest.raises(InvalidToken):
        verifier.verify(token)


@pytest.mark.parametrize("token", ["", "not-a-token", "a.b.c"])
def test_malformed_tokens_are_rejected(verifier: OIDCTokenVerifier, token: str) -> None:
    with pytest.raises(InvalidToken):
        verifier.verify(token)


def test_jwks_is_loaded_from_configured_url_and_cached(
    signing_key: rsa.RSAPrivateKey, claims: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[str] = []

    def open_jwks(opener: Any, request: Any, **kwargs: Any) -> BytesIO:
        requests.append(request.full_url)
        return BytesIO(json.dumps({"keys": [public_jwk(signing_key)]}).encode())

    monkeypatch.setattr("urllib.request.OpenerDirector.open", open_jwks)
    verifier = OIDCTokenVerifier(auth_settings())
    token = jwt.encode(
        claims,
        signing_key,
        algorithm="RS256",
        headers={"kid": KEY_ID, "jku": "https://attacker.example.test/keys"},
    )
    assert verifier.verify(token).subject == claims["sub"]
    assert verifier.verify(token).subject == claims["sub"]
    assert requests == ["https://identity.example.test/.well-known/jwks.json"]


def test_jwks_outage_does_not_authenticate_and_hides_remote_details(
    signing_key: rsa.RSAPrivateKey, claims: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    sensitive_detail = "upstream request contained sensitive transport details"

    def unavailable(*args: Any, **kwargs: Any) -> Any:
        raise URLError(sensitive_detail)

    monkeypatch.setattr("urllib.request.OpenerDirector.open", unavailable)
    verifier = OIDCTokenVerifier(auth_settings())
    with pytest.raises(AuthenticationUnavailable) as raised:
        verifier.verify(signed_token(signing_key, claims))
    assert sensitive_detail not in str(raised.value)


def test_unknown_jwks_key_never_authenticates(
    signing_key: rsa.RSAPrivateKey, claims: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def open_jwks(*args: Any, **kwargs: Any) -> BytesIO:
        other_key = {**public_jwk(signing_key), "kid": "different-key"}
        return BytesIO(json.dumps({"keys": [other_key]}).encode())

    monkeypatch.setattr("urllib.request.OpenerDirector.open", open_jwks)
    verifier = OIDCTokenVerifier(auth_settings())
    with pytest.raises(InvalidToken):
        verifier.verify(signed_token(signing_key, claims))


def test_audience_list_cannot_expand_the_configured_audience(
    verifier: OIDCTokenVerifier, signing_key: rsa.RSAPrivateKey, claims: dict[str, Any]
) -> None:
    claims["aud"] = [AUDIENCE, "another-api"]
    with pytest.raises(InvalidToken):
        verifier.verify(signed_token(signing_key, claims))


@pytest.mark.parametrize("kid", [None, "", "k" * 257])
def test_signing_key_id_must_be_present_and_bounded(
    verifier: OIDCTokenVerifier,
    signing_key: rsa.RSAPrivateKey,
    claims: dict[str, Any],
    kid: str | None,
) -> None:
    headers = {"kid": kid} if kid is not None else {}
    token = jwt.encode(claims, signing_key, algorithm="RS256", headers=headers)
    with pytest.raises(InvalidToken):
        verifier.verify(token)


def test_oversized_token_is_rejected(verifier: OIDCTokenVerifier) -> None:
    with pytest.raises(InvalidToken):
        verifier.verify("a" * 16385)


@pytest.mark.parametrize("headers", [{"crit": ["custom"], "custom": "untrusted"}, {"b64": False}])
def test_unsupported_jose_extensions_are_rejected(
    verifier: OIDCTokenVerifier,
    signing_key: rsa.RSAPrivateKey,
    claims: dict[str, Any],
    headers: dict[str, Any],
) -> None:
    token = jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": KEY_ID, **headers})
    with pytest.raises(InvalidToken):
        verifier.verify(token)


def test_jwk_algorithm_must_match_the_expected_signature_algorithm(
    signing_key: rsa.RSAPrivateKey, claims: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    verifier = OIDCTokenVerifier(auth_settings())
    mismatched_key = jwt.PyJWK.from_dict({**public_jwk(signing_key), "alg": "RS512"})
    monkeypatch.setattr(
        verifier.jwks_client, "get_signing_key_from_jwt", lambda token: mismatched_key
    )
    with pytest.raises(InvalidToken):
        verifier.verify(signed_token(signing_key, claims))
