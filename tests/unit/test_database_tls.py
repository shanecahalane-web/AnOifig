"""Every database entry point shares fail-closed production transport policy."""

import runpy
from contextlib import nullcontext
from typing import cast
from unittest.mock import MagicMock

import pytest
from alembic import context
from sqlalchemy import Connection

from anoifig.db.connection_config import (
    UnsafeDatabaseTransport,
    database_connect_args,
    validate_database_url,
    validate_environment,
    verify_database_tls,
)

LOCAL_URL = "postgresql+psycopg://unit:tls-secret-sentinel@localhost:5432/anoifig_unit"
TLS_URL = LOCAL_URL.replace("localhost", "db.example.test") + (
    "?sslmode=verify-full&sslrootcert=/run/secrets/postgresql-root.crt"
)


@pytest.mark.parametrize("environment", ["development", "test"])
def test_local_environments_allow_explicit_plaintext_database_urls(environment: str) -> None:
    assert validate_database_url(LOCAL_URL, environment).host == "localhost"
    assert database_connect_args(environment) == {"connect_timeout": 5}


@pytest.mark.parametrize("environment", ["Production", "prod", "staging", "production ", ""])
def test_unknown_environments_fail_closed(environment: str) -> None:
    with pytest.raises(ValueError, match="environment must be"):
        validate_environment(environment)
    with pytest.raises(ValueError, match="environment must be"):
        validate_database_url(LOCAL_URL, environment)
    with pytest.raises(ValueError, match="environment must be"):
        database_connect_args(environment)


@pytest.mark.parametrize(
    "url",
    [
        LOCAL_URL,
        LOCAL_URL + "?sslmode=disable",
        LOCAL_URL + "?sslmode=allow",
        LOCAL_URL + "?sslmode=prefer",
        LOCAL_URL + "?sslmode=require",
        LOCAL_URL + "?sslmode=verify-ca&sslrootcert=/root.crt",
        LOCAL_URL + "?sslmode=verify-full",
        LOCAL_URL + "?sslmode=verify-full&sslrootcert=",
        LOCAL_URL + "?sslmode=verify-full&sslrootcert=%20",
        TLS_URL + "&sslmode=disable",
        TLS_URL + "&sslrootcert=/other.crt",
        TLS_URL + "&gssencmode=prefer",
        TLS_URL + "&gssencmode=require",
    ],
)
def test_production_rejects_insecure_or_ambiguous_tls_options(url: str) -> None:
    with pytest.raises(ValueError) as raised:
        validate_database_url(url, "production")
    assert "tls-secret-sentinel" not in str(raised.value)


@pytest.mark.parametrize(
    "parameter",
    [
        "host=%2Fvar%2Frun%2Fpostgresql",
        "host=db.other.test",
        "hostaddr=127.0.0.1",
        "port=6543",
        "service=unencrypted",
        "servicefile=/etc/pg_service.conf",
        "dbname=host%3Delsewhere%20sslmode%3Ddisable",
        "database=other_database",
        "user=other_user",
        "password=other_password",
    ],
)
def test_production_rejects_query_overrides_of_connection_identity(parameter: str) -> None:
    with pytest.raises(ValueError, match="explicit TLS hostname"):
        validate_database_url(TLS_URL + "&" + parameter, "production")


@pytest.mark.parametrize(
    "host",
    ["", "%2Fvar%2Frun%2Fpostgresql", "db1.test,db2.test", "db test", "-invalid.test"],
)
def test_production_rejects_missing_socket_or_ambiguous_hosts(host: str) -> None:
    with pytest.raises(ValueError, match="explicit TLS hostname"):
        validate_database_url(TLS_URL.replace("db.example.test", host), "production")


@pytest.mark.parametrize("port", ["not-a-port", "0", "65536"])
def test_production_rejects_invalid_ports_without_exposing_credentials(port: str) -> None:
    with pytest.raises(ValueError) as raised:
        validate_database_url(TLS_URL.replace(":5432/", f":{port}/"), "production")
    assert "tls-secret-sentinel" not in str(raised.value)


@pytest.mark.parametrize("host", ["db.example.test", "127.0.0.1", "[2001:db8::1]"])
def test_verified_hostname_urls_are_accepted(host: str) -> None:
    url = validate_database_url(TLS_URL.replace("db.example.test", host), "production")
    assert url.query["sslmode"] == "verify-full"
    assert database_connect_args("production", timeout=9) == {
        "connect_timeout": 9,
        "gssencmode": "disable",
    }


@pytest.mark.parametrize("ssl", [False, None])
def test_production_rejects_sessions_not_reported_as_tls(ssl: bool | None) -> None:
    connection = MagicMock(spec=Connection)
    connection.scalar.return_value = ssl
    with pytest.raises(UnsafeDatabaseTransport, match="must use TLS"):
        verify_database_tls(cast(Connection, connection), "production")
    assert "pg_stat_ssl" in str(connection.scalar.call_args.args[0])


def test_production_requires_actual_session_tls_in_addition_to_url_validation() -> None:
    connection = MagicMock(spec=Connection)
    connection.scalar.return_value = True
    verify_database_tls(cast(Connection, connection), "production")
    connection.scalar.assert_called_once()


@pytest.mark.parametrize("environment", ["development", "test"])
def test_local_transport_check_does_not_require_database_tls(environment: str) -> None:
    connection = MagicMock(spec=Connection)
    verify_database_tls(cast(Connection, connection), environment)
    connection.scalar.assert_not_called()


@pytest.mark.parametrize("url", [LOCAL_URL, TLS_URL + "&hostaddr=127.0.0.1"])
@pytest.mark.parametrize("offline", [False, True])
def test_migrations_reject_unsafe_production_url_before_connecting_or_generating_ddl(
    monkeypatch: pytest.MonkeyPatch, url: str, offline: bool
) -> None:
    create_engine = MagicMock()
    configure = MagicMock()
    monkeypatch.setenv("ANOIFIG_ENVIRONMENT", "production")
    monkeypatch.setenv("ANOIFIG_MIGRATION_DATABASE_URL", url)
    monkeypatch.setattr("sqlalchemy.create_engine", create_engine)
    monkeypatch.setattr(context, "is_offline_mode", lambda: offline)
    monkeypatch.setattr(context, "configure", configure)
    with pytest.raises(ValueError, match="production PostgreSQL"):
        runpy.run_path("migrations/env.py")
    create_engine.assert_not_called()
    configure.assert_not_called()


def test_migrations_reject_unknown_environment_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_engine = MagicMock()
    monkeypatch.setenv("ANOIFIG_ENVIRONMENT", "prod")
    monkeypatch.setenv("ANOIFIG_MIGRATION_DATABASE_URL", TLS_URL)
    monkeypatch.setattr("sqlalchemy.create_engine", create_engine)
    monkeypatch.setattr(context, "is_offline_mode", lambda: False)
    with pytest.raises(ValueError, match="environment must be"):
        runpy.run_path("migrations/env.py")
    create_engine.assert_not_called()


def test_migrations_check_established_tls_before_any_ddl(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock(spec=Connection)
    connection.scalar.return_value = False
    engine = MagicMock()
    engine.connect.return_value = nullcontext(connection)
    configure = MagicMock()
    monkeypatch.setenv("ANOIFIG_ENVIRONMENT", "production")
    monkeypatch.setenv("ANOIFIG_MIGRATION_DATABASE_URL", TLS_URL)
    monkeypatch.setattr("sqlalchemy.create_engine", MagicMock(return_value=engine))
    monkeypatch.setattr(context, "is_offline_mode", lambda: False)
    monkeypatch.setattr(context, "configure", configure)
    with pytest.raises(UnsafeDatabaseTransport):
        runpy.run_path("migrations/env.py")
    configure.assert_not_called()
    connection.commit.assert_not_called()
    engine.dispose.assert_called_once()


def test_migrations_finish_transport_probe_before_starting_ddl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock(spec=Connection)
    connection.scalar.return_value = True
    engine = MagicMock()
    engine.connect.return_value = nullcontext(connection)
    operations = MagicMock()
    operations.attach_mock(connection.commit, "commit_probe")
    configure = MagicMock()
    operations.attach_mock(configure, "configure_migrations")
    monkeypatch.setenv("ANOIFIG_ENVIRONMENT", "production")
    monkeypatch.setenv("ANOIFIG_MIGRATION_DATABASE_URL", TLS_URL)
    monkeypatch.setattr("sqlalchemy.create_engine", MagicMock(return_value=engine))
    monkeypatch.setattr(context, "is_offline_mode", lambda: False)
    monkeypatch.setattr(context, "configure", configure)
    monkeypatch.setattr(context, "begin_transaction", nullcontext)
    monkeypatch.setattr(context, "run_migrations", MagicMock())
    runpy.run_path("migrations/env.py")
    assert [call[0] for call in operations.mock_calls] == ["commit_probe", "configure_migrations"]
