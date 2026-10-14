"""Owner provisioning cannot bypass production URL and session TLS checks."""

from contextlib import nullcontext
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Connection

from anoifig.db.connection_config import UnsafeDatabaseTransport

LOCAL_OWNER = "postgresql+psycopg://owner:grant-secret-sentinel@db.example.test/anoifig"
LOCAL_RUNTIME = LOCAL_OWNER.replace("//owner:", "//anoifig_app:")
VERIFIED_OPTIONS = "?sslmode=verify-full&sslrootcert=/run/secrets/db-root.crt"


@pytest.fixture
def grant_script(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "scripts" / "grant_runtime.py"
    spec = spec_from_file_location("grant_runtime_under_test", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("ANOIFIG_ENVIRONMENT", "production")
    monkeypatch.setenv("ANOIFIG_MIGRATION_DATABASE_URL", LOCAL_OWNER + VERIFIED_OPTIONS)
    monkeypatch.setenv("ANOIFIG_DATABASE_URL", LOCAL_RUNTIME + VERIFIED_OPTIONS)
    monkeypatch.setattr(module, "create_engine", MagicMock())
    return module


@pytest.mark.parametrize("variable", ["ANOIFIG_MIGRATION_DATABASE_URL", "ANOIFIG_DATABASE_URL"])
@pytest.mark.parametrize(
    "options",
    [
        "",
        "?sslmode=disable",
        "?sslmode=require",
        "?sslmode=verify-ca&sslrootcert=/root.crt",
        "?sslmode=verify-full",
        VERIFIED_OPTIONS + "&hostaddr=127.0.0.1",
        VERIFIED_OPTIONS + "&service=unverified",
        VERIFIED_OPTIONS + "&sslmode=disable",
    ],
)
def test_grant_script_rejects_either_insecure_url_before_connecting(
    grant_script, monkeypatch, variable, options
):
    base = LOCAL_OWNER if variable.endswith("MIGRATION_DATABASE_URL") else LOCAL_RUNTIME
    monkeypatch.setenv(variable, base + options)
    with pytest.raises(ValueError) as raised:
        grant_script.main()
    assert "grant-secret-sentinel" not in str(raised.value)
    grant_script.create_engine.assert_not_called()


@pytest.mark.parametrize("environment", ["prod", "staging", "Production", ""])
def test_grant_script_rejects_unknown_environment(grant_script, monkeypatch, environment):
    monkeypatch.setenv("ANOIFIG_ENVIRONMENT", environment)
    with pytest.raises(ValueError, match="environment must be"):
        grant_script.main()
    grant_script.create_engine.assert_not_called()


def test_grant_script_checks_session_tls_before_provisioning(grant_script, monkeypatch):
    connection = MagicMock(spec=Connection)
    connection.scalar.return_value = False
    engine = grant_script.create_engine.return_value
    engine.begin.return_value = nullcontext(connection)
    provision = MagicMock()
    monkeypatch.setattr(grant_script, "provision_runtime_grants", provision)
    with pytest.raises(UnsafeDatabaseTransport):
        grant_script.main()
    provision.assert_not_called()
    engine.dispose.assert_called_once()


def test_grant_script_provisions_only_after_verified_tls(grant_script, monkeypatch):
    connection = MagicMock(spec=Connection)
    connection.scalar.return_value = True
    engine = grant_script.create_engine.return_value
    engine.begin.return_value = nullcontext(connection)
    provision = MagicMock()
    order = MagicMock()
    order.attach_mock(connection.scalar, "verify_transport")
    order.attach_mock(provision, "provision")
    monkeypatch.setattr(grant_script, "provision_runtime_grants", provision)
    grant_script.main()
    assert [call[0] for call in order.mock_calls] == ["verify_transport", "provision"]
    provision.assert_called_once_with(connection, "anoifig_app")
    args = grant_script.create_engine.call_args
    assert args.args[0].query["sslmode"] == "verify-full"
    assert args.kwargs["connect_args"] == {"connect_timeout": 5, "gssencmode": "disable"}
    assert args.kwargs["hide_parameters"] is True
    engine.dispose.assert_called_once()


@pytest.mark.parametrize("environment", ["development", "test"])
def test_grant_script_keeps_plaintext_explicitly_local(grant_script, monkeypatch, environment):
    monkeypatch.setenv("ANOIFIG_ENVIRONMENT", environment)
    monkeypatch.setenv("ANOIFIG_MIGRATION_DATABASE_URL", LOCAL_OWNER)
    monkeypatch.setenv("ANOIFIG_DATABASE_URL", LOCAL_RUNTIME)
    connection = MagicMock(spec=Connection)
    grant_script.create_engine.return_value.begin.return_value = nullcontext(connection)
    provision = MagicMock()
    monkeypatch.setattr(grant_script, "provision_runtime_grants", provision)
    grant_script.main()
    connection.scalar.assert_not_called()
    provision.assert_called_once_with(connection, "anoifig_app")
