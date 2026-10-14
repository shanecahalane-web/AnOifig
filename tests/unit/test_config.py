"""Settings reject unsafe runtime modes without exposing connection secrets."""

import os

import pytest
from pydantic import ValidationError

from anoifig.config import Settings

LOCAL_DATABASE_URL = "postgresql+psycopg://unit:unit-only-secret@localhost:5432/anoifig_unit"
TLS_DATABASE_URL = (
    "postgresql+psycopg://unit:unit-only-secret@db.example.test:5432/anoifig_unit"
    "?sslmode=verify-full&sslrootcert=/run/secrets/postgresql-root.crt"
)
OIDC = {
    "oidc_issuer": "https://identity.example.test/",
    "oidc_audience": "anoifig-api",
    "oidc_jwks_url": "https://identity.example.test/.well-known/jwks.json",
}


@pytest.fixture(autouse=True)
def isolate_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in os.environ:
        if name.startswith("ANOIFIG_"):
            monkeypatch.delenv(name)


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANOIFIG_DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_environment_variables_configure_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANOIFIG_DATABASE_URL", LOCAL_DATABASE_URL)
    monkeypatch.setenv("ANOIFIG_ENVIRONMENT", "test")
    settings = Settings(_env_file=None)
    assert settings.environment == "test"
    assert settings.database_url.get_secret_value() == LOCAL_DATABASE_URL


def test_explicit_settings_override_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANOIFIG_DATABASE_URL", TLS_DATABASE_URL)
    settings = Settings(_env_file=None, database_url=LOCAL_DATABASE_URL, environment="test")
    assert settings.database_url.get_secret_value() == LOCAL_DATABASE_URL


def test_database_credentials_are_redacted_in_settings_representations() -> None:
    settings = Settings(_env_file=None, database_url=LOCAL_DATABASE_URL, environment="test")
    assert "unit-only-secret" not in repr(settings)
    assert "unit-only-secret" not in str(settings)
    assert "unit-only-secret" not in settings.model_dump_json()


@pytest.mark.parametrize(
    "database_url",
    ["sqlite:///./development.db", "mysql://unit:secret@localhost/db", "not-a-database-url"],
)
def test_database_requires_supported_postgresql_driver(database_url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=database_url, environment="test")


@pytest.mark.parametrize("field", list(OIDC))
def test_partial_oidc_configuration_is_rejected(field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url=LOCAL_DATABASE_URL,
            environment="test",
            **{field: OIDC[field]},
        )


def test_development_can_start_without_an_identity_provider() -> None:
    settings = Settings(_env_file=None, database_url=LOCAL_DATABASE_URL, environment="development")
    assert settings.oidc_issuer is None
    assert settings.oidc_audience is None
    assert settings.oidc_jwks_url is None


def test_production_requires_identity_configuration() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=TLS_DATABASE_URL, environment="production")


@pytest.mark.parametrize(
    "database_url",
    [
        LOCAL_DATABASE_URL,
        LOCAL_DATABASE_URL + "?sslmode=disable",
        LOCAL_DATABASE_URL + "?sslmode=require",
        LOCAL_DATABASE_URL + "?sslmode=verify-ca&sslrootcert=/run/secrets/root.crt",
        LOCAL_DATABASE_URL + "?sslmode=verify-full",
    ],
)
def test_production_requires_verified_database_tls(database_url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=database_url, environment="production", **OIDC)


@pytest.mark.parametrize("field", ["oidc_issuer", "oidc_jwks_url"])
def test_production_rejects_unencrypted_identity_endpoints(field: str) -> None:
    oidc = {**OIDC, field: "http://identity.example.test/"}
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=TLS_DATABASE_URL, environment="production", **oidc)


def test_complete_production_settings_are_accepted() -> None:
    settings = Settings(
        _env_file=None, database_url=TLS_DATABASE_URL, environment="production", **OIDC
    )
    assert settings.environment == "production"


@pytest.mark.parametrize("size", [-1, 0])
def test_connection_pool_must_have_positive_capacity(size: int) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url=LOCAL_DATABASE_URL,
            environment="test",
            database_pool_size=size,
        )


@pytest.mark.parametrize(
    ("database_url", "environment", "oidc"),
    [
        (
            "postgresql+psycopg://unit:validation-secret-sentinel@db.example.test",
            "test",
            {},
        ),
        (
            "not-a-connection-url-validation-secret-sentinel",
            "test",
            {},
        ),
        (
            TLS_DATABASE_URL.replace("unit-only-secret", "validation-secret-sentinel"),
            "production",
            {"oidc_issuer": OIDC["oidc_issuer"]},
        ),
        (
            LOCAL_DATABASE_URL.replace("unit-only-secret", "validation-secret-sentinel"),
            "production",
            OIDC,
        ),
    ],
    ids=[
        "missing-database",
        "invalid-url",
        "incomplete-production-oidc",
        "insecure-production-tls",
    ],
)
def test_configuration_errors_do_not_expose_database_credentials(
    database_url: str, environment: str, oidc: dict[str, str]
) -> None:
    with pytest.raises(ValidationError) as raised:
        Settings(_env_file=None, database_url=database_url, environment=environment, **oidc)
    error_message = str(raised.value)
    assert "validation-secret-sentinel" not in error_message
    assert database_url not in error_message


@pytest.mark.parametrize(
    "database_url",
    [
        (
            "postgresql+psycopg://unit:unit-only-secret@/anoifig_unit"
            "?sslmode=verify-full&sslrootcert=/run/secrets/postgresql-root.crt"
        ),
        TLS_DATABASE_URL + "&host=%2Fvar%2Frun%2Fpostgresql",
        TLS_DATABASE_URL + "&host=other.example.test",
        TLS_DATABASE_URL + "&hostaddr=127.0.0.1",
        TLS_DATABASE_URL + "&service=unreviewed-libpq-service",
    ],
    ids=[
        "unix-socket-default",
        "unix-socket-query",
        "host-query",
        "hostaddr-query",
        "service-query",
    ],
)
def test_production_rejects_libpq_connection_overrides_that_bypass_tls_hostname(
    database_url: str,
) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=database_url, environment="production", **OIDC)
