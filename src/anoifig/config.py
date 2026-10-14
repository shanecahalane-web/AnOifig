"""Typed, secret-safe process configuration."""

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from anoifig.db.connection_config import Environment, validate_database_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ANOIFIG_",
        env_file=".env",
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    environment: Environment = "development"
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
        validate_database_url(value.get_secret_value(), "development")
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
        validate_database_url(self.database_url.get_secret_value(), self.environment)
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
        if self.environment == "production" and not all(oidc_values):
            raise ValueError("production requires managed OIDC configuration")
        return self


@lru_cache
def get_settings() -> Settings:
    # BaseSettings resolves the required DSN from the process environment at runtime.
    return Settings()  # type: ignore[call-arg]
