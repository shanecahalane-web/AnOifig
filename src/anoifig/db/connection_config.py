"""Connection policy shared by application, migration and provisioning processes.

Validate the URL before opening a connection. Production callers must additionally
check the established session before running application queries or privileged DDL.
"""

import ipaddress
import re
from typing import Literal, cast

from sqlalchemy import Connection, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

Environment = Literal["development", "test", "production"]
_ENVIRONMENTS = frozenset({"development", "test", "production"})
_DNS_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
_CONNECTION_OVERRIDES = frozenset(
    {"host", "hostaddr", "port", "service", "servicefile", "dbname", "database", "user", "password"}
)


class UnsafeDatabaseTransport(RuntimeError):
    """The established production database session is not protected by TLS."""


def validate_environment(value: str) -> Environment:
    """Unknown environments must not silently select the relaxed local policy."""
    if value not in _ENVIRONMENTS:
        raise ValueError("environment must be development, test, or production")
    return cast(Environment, value)


def _is_explicit_hostname(host: str | None) -> bool:
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        try:
            hostname = host.encode("idna").decode("ascii").removesuffix(".")
        except UnicodeError:
            return False
        return len(hostname) <= 253 and all(
            _DNS_LABEL.fullmatch(label) for label in hostname.split(".")
        )
    return True


def validate_database_url(value: str, environment: str) -> URL:
    """Reject ambiguous or insecure production URLs without including their secrets."""
    deployment = validate_environment(environment)
    try:
        url = make_url(value)
    except (ArgumentError, ValueError):
        raise ValueError("database URL must be a valid PostgreSQL connection URL") from None
    if url.drivername != "postgresql+psycopg" or not url.database:
        raise ValueError("database URL requires postgresql+psycopg and a database name")
    if deployment != "production":
        return url

    query = url.query
    if any(isinstance(parameter, tuple) for parameter in query.values()):
        raise ValueError("production PostgreSQL URL cannot repeat connection parameters")
    if query.get("sslmode") != "verify-full" or not query.get("sslrootcert"):
        raise ValueError("production PostgreSQL requires verify-full TLS and sslrootcert")
    root_certificate = query["sslrootcert"]
    if not isinstance(root_certificate, str) or not root_certificate.strip():
        raise ValueError("production PostgreSQL requires an explicit trusted root certificate")
    if (
        not _is_explicit_hostname(url.host)
        or (url.port is not None and not 1 <= url.port <= 65535)
        or _CONNECTION_OVERRIDES.intersection(query)
    ):
        raise ValueError("production PostgreSQL requires an unambiguous explicit TLS hostname")
    # GSS encryption can take precedence over sslmode. Require TLS specifically,
    # and set this explicitly on every production connector even when omitted.
    if query.get("gssencmode", "disable") != "disable":
        raise ValueError("production PostgreSQL requires gssencmode=disable to enforce TLS")
    return url


def database_connect_args(environment: str, *, timeout: int = 5) -> dict[str, str | int]:
    """Supply bounded connection attempts and prevent GSS from replacing TLS."""
    deployment = validate_environment(environment)
    options: dict[str, str | int] = {"connect_timeout": timeout}
    if deployment == "production":
        options["gssencmode"] = "disable"
    return options


def verify_database_tls(connection: Connection, environment: str) -> None:
    """Confirm transport before production DDL, grants or application operations."""
    if (
        validate_environment(environment) == "production"
        and connection.scalar(text("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()"))
        is not True
    ):
        raise UnsafeDatabaseTransport("production PostgreSQL session must use TLS")
