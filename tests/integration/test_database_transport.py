"""Real libpq sessions verify plaintext and untrusted servers fail closed."""

from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from anoifig.db.connection_config import (
    UnsafeDatabaseTransport,
    database_connect_args,
    validate_database_url,
    verify_database_tls,
)
from anoifig.db.session import UnsafeDatabaseConfiguration, check_runtime_database

pytestmark = pytest.mark.integration


def test_production_policy_rejects_actual_plaintext_session(database):
    url = make_url(database.runtime_url).update_query_dict({"sslmode": "disable"})
    engine = create_engine(url, hide_parameters=True)
    try:
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()"))
                is False
            )
            with pytest.raises(UnsafeDatabaseTransport):
                verify_database_tls(connection, "production")
            with pytest.raises(UnsafeDatabaseConfiguration):
                check_runtime_database(connection, require_tls=True)
            # Local development is allowed only through the explicit relaxed mode.
            verify_database_tls(connection, "test")
    finally:
        engine.dispose()


@pytest.mark.parametrize("role", ["admin", "runtime"])
def test_verified_connections_reject_plaintext_or_untrusted_database(
    database, signing_key, tmp_path, role
):
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "untrusted-test-ca")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(signing_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(signing_key, hashes.SHA256())
    )
    ca_path = tmp_path / "untrusted-ca.crt"
    ca_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    source_url = database.admin_url if role == "admin" else database.runtime_url
    url = make_url(source_url).update_query_dict(
        {"sslmode": "verify-full", "sslrootcert": str(ca_path)}
    )
    validated = validate_database_url(url.render_as_string(hide_password=False), "production")
    engine = create_engine(
        validated, connect_args=database_connect_args("production"), hide_parameters=True
    )
    try:
        with pytest.raises(SQLAlchemyError), engine.connect():
            pytest.fail("A plaintext or untrusted server must never accept production connections")
    finally:
        engine.dispose()
