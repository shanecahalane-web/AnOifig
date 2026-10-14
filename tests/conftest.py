"""Integration fixtures use disposable PostgreSQL and the real runtime role."""

import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import jwt
import pytest
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric import rsa
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from anoifig.api.main import create_app
from anoifig.config import Settings
from anoifig.db.models import Business, Customer, Membership, User
from anoifig.db.session import check_runtime_database
from anoifig.identity.auth import OIDCTokenVerifier

ISSUER = "https://identity.example.test/"
AUDIENCE = "anoifig-test-api"


@dataclass(frozen=True)
class Database:
    admin_url: str
    runtime_url: str
    admin: Engine
    runtime: Engine


@pytest.fixture(scope="session")
def database() -> Iterator[Database]:
    local = dotenv_values(".env")
    admin_url = os.environ.get("ANOIFIG_TEST_ADMIN_DATABASE_URL") or local.get(
        "ANOIFIG_TEST_ADMIN_DATABASE_URL"
    )
    runtime_url = os.environ.get("ANOIFIG_TEST_DATABASE_URL") or local.get(
        "ANOIFIG_TEST_DATABASE_URL"
    )
    if not admin_url or not runtime_url:
        pytest.fail(
            "Integration tests require ANOIFIG_TEST_ADMIN_DATABASE_URL and "
            "ANOIFIG_TEST_DATABASE_URL; use docker compose --profile test run --rm tests."
        )
    admin, runtime = make_url(admin_url), make_url(runtime_url)
    if (
        not admin.database
        or not admin.database.endswith("_test")
        or (admin.host, admin.port, admin.database)
        != (runtime.host, runtime.port, runtime.database)
        or not runtime.username
        or admin.username == runtime.username
    ):
        pytest.fail("Use the same dedicated *_test database with separate owner/runtime roles.")
    with patch.dict(os.environ, {"ANOIFIG_MIGRATION_DATABASE_URL": admin_url}):
        command.upgrade(Config("alembic.ini"), "head")
    subprocess.run(
        [sys.executable, "scripts/grant_runtime.py"],
        env={
            **os.environ,
            "ANOIFIG_MIGRATION_DATABASE_URL": admin_url,
            "ANOIFIG_DATABASE_URL": runtime_url,
        },
        check=True,
        capture_output=True,
        text=True,
    )
    owner_engine = create_engine(admin_url, hide_parameters=True)
    # A single pooled connection makes accidental context leakage observable.
    runtime_engine = create_engine(runtime_url, pool_size=1, max_overflow=0, hide_parameters=True)
    with runtime_engine.connect() as connection:
        check_runtime_database(connection)
    yield Database(admin_url, runtime_url, owner_engine, runtime_engine)
    runtime_engine.dispose()
    owner_engine.dispose()


@dataclass(frozen=True)
class Seed:
    businesses: dict[str, UUID]
    users: dict[str, UUID]
    customers: dict[str, UUID]


@pytest.fixture
def seed(database: Database) -> Seed:
    businesses = {name: uuid4() for name in ("a", "b", "disabled")}
    subjects = (
        "owner-a",
        "owner-b",
        "staff-a",
        "reader-a",
        "dual",
        "revoked",
        "disabled",
        "outsider",
    )
    users = {subject: uuid4() for subject in subjects}
    customers = {name: uuid4() for name in businesses}
    with Session(database.admin) as session, session.begin():
        session.execute(text("TRUNCATE customers, memberships, users, businesses CASCADE"))
        session.add_all(
            Business(id=identifier, legal_name=f"Business {name}", active=name != "disabled")
            for name, identifier in businesses.items()
        )
        session.add_all(
            User(
                id=identifier,
                identity_provider_issuer=ISSUER,
                identity_provider_subject=subject,
                active=subject != "disabled",
            )
            for subject, identifier in users.items()
        )
        session.flush()
        for subject, tenant, role, active in (
            ("owner-a", "a", "owner", True),
            ("owner-b", "b", "owner", True),
            ("staff-a", "a", "staff", True),
            ("reader-a", "a", "read_only", True),
            ("dual", "a", "owner", True),
            ("dual", "b", "owner", True),
            ("owner-a", "disabled", "owner", True),
            ("revoked", "a", "staff", False),
            ("disabled", "a", "owner", True),
        ):
            session.add(
                Membership(
                    tenant_id=businesses[tenant], user_id=users[subject], role=role, active=active
                )
            )
        session.add_all(
            Customer(id=customers[name], tenant_id=identifier, name=f"Customer {name}")
            for name, identifier in businesses.items()
        )
    return Seed(businesses, users, customers)


@pytest.fixture(scope="session")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def bearer(signing_key: rsa.RSAPrivateKey):
    def make(subject: str, **overrides: object) -> dict[str, str]:
        now = datetime.now(UTC)
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": subject,
            "iat": now,
            "exp": now + timedelta(minutes=5),
            **overrides,
        }
        token = jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "test-key"})
        return {"Authorization": f"Bearer {token}"}

    return make


@pytest.fixture
def client(database: Database, signing_key: rsa.RSAPrivateKey, monkeypatch) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=database.runtime_url,
        oidc_issuer=ISSUER,
        oidc_audience=AUDIENCE,
        oidc_jwks_url=ISSUER + ".well-known/jwks.json",
        database_pool_size=1,
        database_max_overflow=0,
    )
    verifier = OIDCTokenVerifier(settings)
    # Only key transport is replaced; real signatures and all JWT claims are verified.
    jwk = jwt.PyJWK.from_json(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    monkeypatch.setattr(verifier.jwks_client, "get_signing_key_from_jwt", lambda _token: jwk)
    with TestClient(create_app(settings, token_verifier=verifier)) as test_client:
        yield test_client
