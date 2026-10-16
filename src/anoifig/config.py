"""Typed, secret-safe process configuration."""

import re
from decimal import Decimal
from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from anoifig.db.connection_config import Environment, validate_database_url


class TaraBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requests: int = Field(default=100, ge=0, le=100000)
    tokens: int = Field(default=1000000, ge=0, le=1000000000)
    cost_usd: Decimal = Field(default=Decimal("5"), ge=0, le=10000, allow_inf_nan=False)


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
    twilio_enabled: bool = False
    twilio_account_sid: SecretStr | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_whatsapp_number: str | None = None
    twilio_inbound_url: str | None = None
    twilio_status_url: str | None = None
    twilio_http_timeout: int = Field(default=10, ge=1, le=30)

    # Local acknowledgement is explicit in Compose; production must select OpenAI.
    tara_mode: Literal["acknowledgement", "mock", "openai"] = "acknowledgement"
    openai_api_key: SecretStr | None = None
    tara_model: str = Field(default="gpt-4.1-mini", min_length=1, max_length=100)
    tara_timeout_seconds: int = Field(default=15, ge=1, le=30)
    tara_deadline_seconds: int = Field(default=60, ge=1, le=90)
    tara_max_retries: int = Field(default=1, ge=0, le=2)
    tara_max_input_tokens: int = Field(default=16000, ge=1000, le=64000)
    tara_max_output_tokens: int = Field(default=1200, ge=128, le=4000)
    tara_history_messages: int = Field(default=8, ge=0, le=30)
    tara_memory_days: int = Field(default=30, ge=1, le=90)
    tara_daily_budget: TaraBudget = Field(default_factory=TaraBudget)
    tara_business_budgets: dict[UUID, TaraBudget] = Field(default_factory=dict)
    # USD per million tokens. Supply reviewed current rates before live use.
    tara_input_price_usd: Decimal = Field(default=Decimal("0"), ge=0, le=1000, allow_inf_nan=False)
    tara_output_price_usd: Decimal = Field(default=Decimal("0"), ge=0, le=1000, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_tara_configuration(self) -> "Settings":
        if self.environment == "production" and self.tara_mode == "mock":
            raise ValueError("mock AI is forbidden in production")
        if self.tara_mode == "openai":
            if self.openai_api_key is None or not self.openai_api_key.get_secret_value().strip():
                raise ValueError("OpenAI mode requires a securely supplied API key")
            if self.tara_input_price_usd <= 0 or self.tara_output_price_usd <= 0:
                raise ValueError("OpenAI mode requires reviewed positive token prices")
        return self

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

    @field_validator(
        "twilio_account_sid",
        "twilio_auth_token",
        "twilio_whatsapp_number",
        "twilio_inbound_url",
        "twilio_status_url",
        mode="before",
    )
    @classmethod
    def blank_twilio_configuration_is_absent(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_twilio_configuration(self) -> "Settings":
        values = (
            self.twilio_account_sid,
            self.twilio_auth_token,
            self.twilio_whatsapp_number,
            self.twilio_inbound_url,
            self.twilio_status_url,
        )
        if (self.twilio_enabled or any(value is not None for value in values)) and not all(values):
            raise ValueError("configure all Twilio credentials, sender and public webhook URLs")
        if self.twilio_account_sid is not None and not re.fullmatch(
            r"AC[0-9a-fA-F]{32}", self.twilio_account_sid.get_secret_value()
        ):
            raise ValueError("Twilio account SID has an invalid format")
        if self.twilio_auth_token is not None:
            token = self.twilio_auth_token.get_secret_value()
            if not token.strip() or token != token.strip() or len(token) > 256:
                raise ValueError("Twilio auth token has an invalid format")
        if self.twilio_whatsapp_number is not None and not re.fullmatch(
            r"whatsapp:\+[1-9][0-9]{1,14}", self.twilio_whatsapp_number
        ):
            raise ValueError("Twilio sender must be a WhatsApp E.164 address")
        for value in (self.twilio_inbound_url, self.twilio_status_url):
            if value is None:
                continue
            parsed = urlsplit(value)
            _ = parsed.port
            if (
                len(value) > 2048
                or not value.isascii()
                or value != value.strip()
                or any(ord(character) < 33 or ord(character) == 127 for character in value)
                or "\\" in value
                or re.search(r"%(?![0-9a-fA-F]{2})", value)
                or parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or not parsed.path.startswith("/")
                or parsed.username
                or parsed.password
                or parsed.fragment
            ):
                raise ValueError("Twilio webhooks require absolute public HTTP URLs")
            if self.environment == "production" and parsed.scheme != "https":
                raise ValueError("production Twilio webhooks require HTTPS")
            try:
                query = parse_qsl(
                    parsed.query,
                    keep_blank_values=True,
                    strict_parsing=True,
                    encoding="utf-8",
                    errors="strict",
                    max_num_fields=64,
                )
            except (UnicodeError, ValueError) as error:
                raise ValueError("Twilio webhook query must be unambiguous UTF-8") from error
            names = [name for name, _ in query]
            if len(names) != len(set(names)):
                raise ValueError("Twilio webhook query keys must not repeat")
            if value == self.twilio_status_url and "attempt_id" in names:
                raise ValueError("Twilio status URL must reserve the attempt_id query key")
        return self

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
