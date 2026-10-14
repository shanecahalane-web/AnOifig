# An Oifig

An Oifig is a multi-tenant SaaS backend for Irish tradespeople. Tara will eventually
operate through WhatsApp. This milestone provides a Python 3.13/FastAPI modular
monolith, PostgreSQL models and migrations, tenant authorisation, and automated
checks. It does not connect Twilio/OpenAI, generate invoices, or deploy cloud resources.

Read [the production blueprint](An_Oifig_Production_Blueprint.md),
[engineering rules](AGENTS.md), and [architecture decisions](docs/adr/0001-backend-foundation.md)
before changing the application boundaries.

## Run locally with Docker

Prerequisites: Docker Engine/Desktop with Compose v2, Git, and an available local
port 8000 and 5432. No cloud account, paid resource, or API credential is required.

```sh
cp .env.example .env
docker compose up --build -d
docker compose ps -a
curl --fail http://127.0.0.1:8000/health/live
curl --fail http://127.0.0.1:8000/health/ready
```

Both health endpoints return JSON. `/health/live` checks the process;
`/health/ready` checks PostgreSQL connectivity and readiness of the runtime
connection. A failed readiness check returns 503 without internal error details.
OpenAPI is available at <http://127.0.0.1:8000/docs>.

Compose starts PostgreSQL 17, runs the Alembic migration once, grants the limited
runtime permissions, then starts the API as an unprivileged container user.
The API receives only the application database URL. The migration service alone
receives the schema-owner URL. Local ports bind to loopback; this Compose file is
for development and must not be exposed as a production deployment.

`.env.example` contains conspicuous disposable passwords. Keep `.env` private and
use URL-safe passwords with this local Compose configuration. PostgreSQL init
scripts run only when its volume is empty; changing a password in `.env` does not
rotate an existing database role. See [the database runbook](docs/runbooks/database.md).
If your development network uses an approved HTTPS inspection proxy, see the
runbook's optional build CA configuration; certificate verification stays enabled.

```sh
docker compose logs api migrate
docker compose down
```

`docker compose down` retains the database volume. The runbook describes an
explicit destructive reset for disposable development data.

## Run the API on the host

Install Python 3.13 and [uv](https://docs.astral.sh/uv/) 0.12.23. The Python version
is pinned in `.python-version`; dependencies are resolved in `uv.lock`.

```sh
cp .env.example .env
uv sync --frozen
docker compose up -d postgres
```

Review and export the values from your private `.env`, then start the app:

```sh
set -a
. ./.env
set +a
uv run --frozen alembic upgrade head
uv run --frozen python scripts/grant_runtime.py
uv run --frozen uvicorn anoifig.api.main:app --reload --host 127.0.0.1 --port 8000
```

Only source a file you trust. Alembic uses `ANOIFIG_MIGRATION_DATABASE_URL`; the
API uses `ANOIFIG_DATABASE_URL`. The grant script reads process environment
variables. The example URLs point at loopback for host use; Compose overrides
the database hostname to its private service name.

## Authentication and tenant isolation

There is no public registration endpoint and no development authentication
bypass. Protected endpoints reject requests without a bearer token. With a
bearer token but no configured OIDC provider they fail closed with 503. The
production configuration requires HTTPS OIDC endpoints and PostgreSQL
`sslmode=verify-full` with an explicit CA certificate path.

Configure `ANOIFIG_OIDC_ISSUER`, `ANOIFIG_OIDC_AUDIENCE`, and
`ANOIFIG_OIDC_JWKS_URL` together for an approved identity provider. The API accepts
the strict access-token profile in [ADR 0002](docs/adr/0002-identity-and-tenant-isolation.md):
RS256 signatures from the configured JWKS, protected `typ` of `at+jwt` or
`application/at+jwt`, the exact issuer and a single dedicated API audience,
and required `exp`, `iat`, `sub`, `client_id`, and `jti` claims. A signed
`token_use`, when present, must be `access`; ID-token-only claims are rejected.
ID tokens, refresh tokens, and generic JWTs are not accepted as API credentials.
A trusted provisioning operator must create the business, local user mapped to the exact
issuer/subject, and active membership before that user can access a tenant. The
runtime role cannot provision or modify those records. See
[the security decision](docs/adr/0002-identity-and-tenant-isolation.md).

No identity provider has been selected or approved. Deployment must verify that
its access tokens meet this contract, configure a separate API audience and
approved client/grant/scope policies, and validate MFA, signing-key rotation,
revocation and session lifetimes. Providers with a different token format require
a separately reviewed adapter; there is no permissive fallback. `jti` is an
identifier and does not by itself prevent bearer-token replay.

Initial authenticated routes are:

- `GET /v1/me`
- `GET /v1/businesses/{tenant_id}/customers`
- `POST /v1/businesses/{tenant_id}/customers`
- `GET /v1/businesses/{tenant_id}/customers/{customer_id}`

Send a verified bearer token using `Authorization: Bearer <token>`. The tenant
UUID in the path selects a business; it does not authorise access. Access also
requires an active business/user/membership, role authorisation, and
transaction-local PostgreSQL row-level security (RLS) context. Customer queries
explicitly scope tenant IDs. RLS is tested using the restricted application role
and raw SQL. The `owner` and `staff` roles may create customers; `read_only` may
read. Platform administration is not implemented.

RLS protects against accidental missing query filters and unauthorised requests
within the trusted application boundary. A holder of arbitrary SQL access with
the runtime credentials can set that application's transaction context; RLS is
not a defence against a compromised application/database credential. Protect the
runtime credentials and limit database network access.

Runtime checks also reject unexpected database privileges, including `TRUNCATE`,
which bypasses row policies. The grant helper fails before changing grants when
it detects excess privileges; it adds only missing approved permissions and
verifies the result in one transaction. Review and repair privilege drift using
[the database runbook](docs/runbooks/database.md), rather than bypassing the checks.

## Automated checks

```sh
uv sync --frozen
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy src
uv audit --locked
docker compose --profile test run --build --rm tests
```

The Compose test service runs the full suite with the dedicated `anoifig_test`
database. Integration fixtures apply migrations as owner, then exercise the
separate `anoifig_app` role. They delete synthetic test records and must never
point at a database containing customer data. For host execution, export the
`ANOIFIG_TEST_DATABASE_URL` and `ANOIFIG_TEST_ADMIN_DATABASE_URL` values from the
private `.env` and run `uv run --frozen pytest -ra`. Database names must end in
`_test`. Run unit checks alone with `uv run --frozen pytest tests/unit -q`.
GitHub Actions always provides PostgreSQL and runs the complete suite.

Coverage includes configuration and health behaviour, signed and rejected tokens,
roles and revoked memberships, cross-tenant reads and writes, PostgreSQL RLS
policies and constraints, and connection-pool context cleanup. There are no live
external service calls. CI runs on pull requests and pushes to `main`, with
read-only repository permissions and disposable PostgreSQL credentials.

## Project layout

```text
src/anoifig/
  api/          HTTP entrypoint and dependency wiring
  identity/     OIDC verification and tenant authorisation
  businesses/   Business boundary
  customers/    Customer schemas, repository and service boundary
  db/           SQLAlchemy models and transaction/session infrastructure
  config.py     Validated environment configuration
migrations/     Reviewed Alembic schema and RLS changes
tests/          Unit and real-PostgreSQL integration tests
scripts/        Local/CI role setup and post-migration grants
docs/adr/       Architecture/security decisions
docs/runbooks/  Operational development instructions
```

Future invoice, conversation, messaging, and AI modules belong in the shared
package and must call authorised domain services. A future worker can use the
same package through its own process entrypoint. No empty integration SDKs or
invoice generation code are included in this milestone.

## Production decisions still required

This is a foundation for further implementation, not approval to onboard paying
customers. Choose and configure the managed OIDC provider and MFA policies;
design audited identity/membership provisioning; choose production infrastructure
and secret delivery; add rate limiting, telemetry, audit retention and backups
with restore tests. Production database roles, network/TLS controls, and staging
deployment require review. The blueprint's staging deployment and broader
hardening exit criteria are deferred because this task authorises local
development and CI without paid Azure resources.

For **every** production application, migration, and grant-script process,
explicitly set `ANOIFIG_ENVIRONMENT=production` and supply the appropriate private
database URL. All three paths require `postgresql+psycopg`, a single TCP hostname,
`sslmode=verify-full`, and an explicit trusted `sslrootcert` path; they also verify
that the established PostgreSQL session uses TLS. Mount the CA in each process's
filesystem. Plain local example URLs are intentionally unsuitable for production.
See [ADR 0003](docs/adr/0003-production-database-tls.md) and the runbook for the
release requirements; migration/grant commands do not load `.env` themselves.

The four low-severity review findings remain open in the
[technical debt register](docs/technical-debt.md), with completion criteria and
target gates. Passing the current test suite does not close those items.

Twilio/OpenAI accounts, invoice issuance and Irish tax/privacy review remain later
milestones. Work through reviewed branches and pull requests; do not merge or
deploy automatically.
