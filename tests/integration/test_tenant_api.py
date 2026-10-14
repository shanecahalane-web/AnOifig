"""HTTP authorisation tests use signed tokens and the restricted PostgreSQL login."""

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


def customer_path(seed, tenant="a"):
    return f"/v1/businesses/{seed.businesses[tenant]}/customers"


def test_live_and_ready_with_restricted_role(client, seed):
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200


def test_me_only_exposes_current_identity_memberships(client, seed, bearer):
    response = client.get("/v1/me", headers=bearer("owner-a"))
    assert response.status_code == 200
    assert response.json() == {
        "id": str(seed.users["owner-a"]),
        "memberships": [{"tenant_id": str(seed.businesses["a"]), "role": "owner"}],
    }


@pytest.mark.parametrize("subject", ["owner-a", "staff-a", "reader-a"])
def test_members_can_read_only_their_business(client, seed, bearer, subject):
    response = client.get(customer_path(seed), headers=bearer(subject))
    assert response.status_code == 200
    assert [customer["id"] for customer in response.json()] == [str(seed.customers["a"])]
    assert client.get(customer_path(seed, "b"), headers=bearer(subject)).status_code == 403


@pytest.mark.parametrize("subject", ["owner-a", "staff-a"])
def test_writers_create_customers_in_authorised_business(client, seed, bearer, subject):
    response = client.post(
        customer_path(seed),
        headers=bearer(subject),
        json={"name": "  Synthetic customer  ", "billing_address": "Dublin"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["tenant_id"] == str(seed.businesses["a"])
    assert data["name"] == "Synthetic customer"
    assert data["created_at"].endswith("Z") or data["created_at"].endswith("+00:00")
    assert (
        client.get(customer_path(seed) + "/" + data["id"], headers=bearer(subject)).json() == data
    )


@pytest.mark.parametrize("subject", ["reader-a", "owner-b", "revoked", "disabled", "outsider"])
def test_unauthorised_writes_rejected(client, seed, bearer, subject):
    assert (
        client.post(
            customer_path(seed), headers=bearer(subject), json={"name": "Denied"}
        ).status_code
        == 403
    )


def test_request_cannot_supply_customer_tenant_or_unknown_fields(client, seed, bearer):
    assert (
        client.post(
            customer_path(seed),
            headers=bearer("owner-a"),
            json={"name": "Denied", "tenant_id": str(seed.businesses["b"])},
        ).status_code
        == 422
    )


def test_untrusted_token_tenant_and_role_claims_do_not_grant_membership(client, seed, bearer):
    headers = bearer("owner-b", tenant_id=str(seed.businesses["a"]), role="owner")
    headers["X-Business-ID"] = str(seed.businesses["a"])
    assert client.get(customer_path(seed), headers=headers).status_code == 403


def test_cross_business_customer_identifier_is_not_disclosed(client, seed, bearer):
    path = customer_path(seed) + "/" + str(seed.customers["b"])
    response = client.get(path, headers=bearer("owner-a"))
    assert response.status_code == 404
    assert str(seed.customers["b"]) not in response.text


@pytest.mark.parametrize("subject", ["revoked", "disabled", "outsider", "unknown-subject"])
def test_inactive_or_unmapped_identity_cannot_access_business(client, seed, bearer, subject):
    assert client.get(customer_path(seed), headers=bearer(subject)).status_code == 403


def test_membership_revocation_takes_effect_without_waiting_for_token_expiry(
    client, database, seed, bearer
):
    headers = bearer("owner-a")
    assert client.get(customer_path(seed), headers=headers).status_code == 200
    with database.admin.begin() as connection:
        connection.execute(
            text("UPDATE memberships SET active = false WHERE user_id = :id"),
            {"id": seed.users["owner-a"]},
        )
    assert client.get(customer_path(seed), headers=headers).status_code == 403


def test_inactive_business_is_not_available(client, seed, bearer):
    assert client.get(customer_path(seed, "disabled"), headers=bearer("owner-a")).status_code == 403


def test_sequential_requests_do_not_reuse_tenant_or_identity(client, seed, bearer):
    for subject, tenant in (("owner-a", "a"), ("owner-b", "b"), ("owner-a", "a")):
        response = client.get(customer_path(seed, tenant), headers=bearer(subject))
        assert response.status_code == 200
        assert [row["id"] for row in response.json()] == [str(seed.customers[tenant])]
    assert client.get(customer_path(seed), headers=bearer("owner-b")).status_code == 403


def test_multi_business_user_must_select_each_business(client, seed, bearer):
    for tenant in ("a", "b"):
        response = client.get(customer_path(seed, tenant), headers=bearer("dual"))
        assert response.status_code == 200
        assert [row["id"] for row in response.json()] == [str(seed.customers[tenant])]


@pytest.mark.parametrize(
    "body", [{"name": "  "}, {"name": "x" * 256}, {"name": "X", "email": "x" * 321}]
)
def test_customer_input_constraints(client, seed, bearer, body):
    assert client.post(customer_path(seed), headers=bearer("owner-a"), json=body).status_code == 422


def test_database_owner_is_rejected_by_readiness(database):
    from fastapi.testclient import TestClient

    from anoifig.api.main import create_app
    from anoifig.config import Settings

    settings = Settings(_env_file=None, environment="test", database_url=database.admin_url)
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert "password" not in response.text.lower()
        assert client.get("/health/live").status_code == 200
