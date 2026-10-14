"""Typed, secret-safe process configuration."""

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ANOIFIG_",
        env_file=".env",
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: SecretStr
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    database_pool_size: int = Field(default=5, ge=1, le=20)
    database_max_overflow: int = Field(default=5, ge=0, le=20)
    database_connect_timeout: int = Field(default=5, ge=1, le=30)
    database_statement_timeout_ms: int = Field(default=5000, ge=100, le=60000)
    oidc_http_timeout: int = Field(default=5, ge=1, le=15)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
        except ArgumentError:
            raise ValueError("database_url must be a valid PostgreSQL connection URL") from None
        if url.drivername != "postgresql+psycopg" or not url.database:
            raise ValueError("database_url requires postgresql+psycopg and a database name")
        return value

    @field_validator("oidc_issuer", "oidc_audience", "oidc_jwks_url")
    @classmethod
    def normalise_optional_configuration(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                return None
        return value

    @model_validator(mode="after")
    def validate_oidc_and_production(self) -> "Settings":
        oidc_values = (self.oidc_issuer, self.oidc_audience, self.oidc_jwks_url)
        if any(oidc_values) and not all(oidc_values):
            raise ValueError("configure issuer, audience, and JWKS URL together")
        for value in (self.oidc_issuer, self.oidc_jwks_url):
            if value is None:
                continue
            parsed = urlsplit(value)
            # Accessing port validates its syntax and range; hostname alone does not.
            _ = parsed.port
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("OIDC issuer and JWKS URL must be absolute trusted HTTP URLs")
            if self.environment == "production" and parsed.scheme != "https":
                raise ValueError("production OIDC endpoints require HTTPS")
        if self.oidc_issuer is not None and len(self.oidc_issuer) > 512:
            raise ValueError("OIDC issuer exceeds the supported identity length")
        if self.environment == "production":
            if not all(oidc_values):
                raise ValueError("production requires managed OIDC configuration")
            database = make_url(self.database_url.get_secret_value())
            query = database.query
            if query.get("sslmode") != "verify-full" or not query.get("sslrootcert"):
                raise ValueError("production PostgreSQL requires verify-full TLS and sslrootcert")
            if (
                not database.host
                or database.host.startswith("/")
                or any(key in query for key in ("host", "hostaddr", "service"))
            ):
                raise ValueError("production PostgreSQL requires an explicit TLS hostname")
        return self


@lru_cache
def get_settings() -> Settings:
    # BaseSettings resolves the required DSN from the process environment at runtime.
    return Settings()  # type: ignore[call-arg]
