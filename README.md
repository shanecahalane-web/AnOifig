# An Oifig

An Oifig is a multi-tenant SaaS backend for Irish tradespeople. Tara communicates through WhatsApp. Milestone 2 adds signed Twilio text-message webhooks,
explicit phone/account linking, durable PostgreSQL queues and an outbound outbox,
a separate worker, and delivery callbacks to the Python 3.13/FastAPI backend.
Authorised text messages receive this deterministic response:

> Hi, I'm Tara, your An Oifig assistant. Your message has been received successfully.

There is no OpenAI integration, voice processing, invoicing, WhatsApp Flow,
Power Automate, or SharePoint dependency. This implementation has not been
deployed or connected to production Twilio settings.

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
runtime permissions, then starts the API and worker as unprivileged container
users. The worker uses a local deterministic messaging simulator by default; it
does not contact Twilio. The API and worker receive only the application database
URL. The migration service alone receives the schema-owner URL. Local ports bind to loopback; this Compose file is
for development and must not be exposed as a production deployment.

`.env.example` contains conspicuous disposable passwords. Keep `.env` private and
use URL-safe passwords with this local Compose configuration. PostgreSQL init
scripts run only when its volume is empty; changing a password in `.env` does not
rotate an existing database role. See [the database runbook](docs/runbooks/database.md).
If your development network uses an approved HTTPS inspection proxy, see the
runbook's optional build CA configuration; certificate verification stays enabled.

```sh
docker compose logs api worker migrate
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

Run the local worker in a second shell with the same exported environment:

```sh
uv run --frozen python -m anoifig.messaging.worker --local
```

`--local` records deterministic simulator results and never delivers a WhatsApp
message. It is rejected in production. Add `--once` to process one batch and exit.
Twilio webhooks are disabled by default; linking requires configured OIDC and
pre-provisioned users/memberships. Automated tests exercise the full flow with
synthetic credentials and a mocked provider.

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
- `POST /v1/businesses/{tenant_id}/messaging/links`
- `DELETE /v1/businesses/{tenant_id}/messaging/links/{link_id}`

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

## WhatsApp configuration and account linking

No live credentials are needed to build, start locally, or run tests. The default
`ANOIFIG_TWILIO_ENABLED=false` makes Twilio ingress fail closed. To configure a
future approved development sender, supply all settings below through private
environment configuration or an approved secret store. Never commit them.

| Environment variable | Purpose |
| --- | --- |
| `ANOIFIG_TWILIO_ENABLED` | Explicitly enables Twilio ingress and configuration validation; defaults to `false`. |
| `ANOIFIG_TWILIO_ACCOUNT_SID` | The expected Twilio account; webhooks from other accounts are rejected. |
| `ANOIFIG_TWILIO_AUTH_TOKEN` | Secret used for webhook signatures and the Twilio API. |
| `ANOIFIG_TWILIO_WHATSAPP_NUMBER` | Approved sender address, such as `whatsapp:+353...`, in E.164 format. |
| `ANOIFIG_TWILIO_INBOUND_URL` | Exact public inbound URL, for example `https://messaging.example.invalid/webhooks/twilio/inbound`. |
| `ANOIFIG_TWILIO_STATUS_URL` | Public status URL before the worker adds `attempt_id`, for example `https://messaging.example.invalid/webhooks/twilio/status`. |
| `ANOIFIG_TWILIO_HTTP_TIMEOUT` | Optional API timeout in seconds; defaults to 10, allowed range 1–30. |

Existing database, OIDC, environment, and test database settings are described
above and in [`.env.example`](.env.example). HTTPS is mandatory for production
webhook URLs. Configure Twilio's incoming-message method as **POST** to the exact
inbound URL. Each outbound operation supplies its own status callback URL, with an
opaque immutable `attempt_id` query parameter (the outbox ID, retained across
definite safe retries); Twilio must preserve that URL.
The public host, scheme, path and any static query must match configuration
exactly. Signature verification uses these configured URLs and validated form
parameters, including the status attempt query, without trusting proxy-supplied
host or forwarding headers. An ingress proxy must preserve the configured path
and query. Do not append unsolicited query parameters or rewrite these URLs.

Endpoints are:

- `POST /webhooks/twilio/inbound` — signed, validated inbound text and phone-link confirmation.
- `POST /webhooks/twilio/status?attempt_id=<uuid>` — signed delivery updates bound to an outbound operation.

A phone number does not grant business access. An active `owner` or `staff` user
must first authenticate with the existing OIDC API and request a link for their
own account using `POST /v1/businesses/{tenant_id}/messaging/links` with JSON
`{"phone": "+353..."}`. The response contains a single-use verification token.
Within ten minutes, that exact phone must send `LINK <token>` to the configured
WhatsApp sender. Only its hash is persisted; keep the returned token private and
do not log the confirmation body. There can be only one active business route
per phone. Revocation uses the authenticated `DELETE` route above and is
rechecked on subsequent ingress, processing and sends. Inactive businesses,
users, memberships, and read-only users cannot gain messaging write access.
Unknown or unverified senders receive a generic rejection and no Tara reply.
See [the messaging runbook](docs/runbooks/messaging.md) for the complete workflow.

The ingress commits accepted messages and processing work before returning a
prompt 2xx response. The worker generates one Tara response per accepted inbound
message and sends from a committed outbox. PostgreSQL uniqueness, transaction
locks and idempotent handlers protect against concurrent webhook replays.
Definite pre-send failures can retry within bounds; an ambiguous timeout, server
failure or worker crash after dispatch is marked `uncertain` and is not
blindly sent again. This trades automatic recovery for duplicate-send safety.
Signed status callbacks can reconcile those operations while the linked identity
remains authorised. After revocation callbacks are rejected and work is parked
for trusted operator reconciliation. The implementation does not claim
exactly-once delivery across Twilio and PostgreSQL.

An authorised late successful response can also reconcile the same dispatch
attempt after lease recovery, retaining its SID without regressing callback
progress. Conflicting SIDs are retained as diagnostics and never cause a resend.
The local queue uses receipt-bound, two-minute operational claims and gives the
least recently claimed ready jobs priority. Locked source rows are deferred;
workers pause when a batch cannot advance. Expired claims survive process
restarts through PostgreSQL, while domain locks still prevent duplicate actions.

Existing Milestone 2 databases upgrade through migration `0003_messaging_queue_claims`
without resetting messages or outboxes. Apply Alembic and runtime grants before
restarting both API and worker; see the [database runbook](docs/runbooks/database.md).

Free-form replies are allowed only within WhatsApp's 24-hour customer-service
window, which is checked again at dispatch. Outside that window the outbox is
blocked. Approved template sending is not implemented in this milestone; do not
work around the block by sending free-form text. Non-text/media messages and
interactive Flows are unsupported.

Compose always runs the worker with `--local`, even if Twilio ingress is enabled.
For an explicitly approved development account, change the worker command to
`["uv", "run", "--no-sync", "python", "-m", "anoifig.messaging.worker"]` in a
private Compose override, or run that module on the host without `--local`.
Using the real adapter sends chargeable messages; this task does not authorise
connecting an account or changing Twilio production settings.

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
policies and constraints, and connection-pool context cleanup. Messaging tests
cover signature rejection, verified account linking, duplicate/concurrent
webhooks, persistence, status callbacks, provider failures, bounded retries and
ambiguous-send handling. Twilio API calls are mocked; no live credentials or
paid service is required. CI runs on pull requests and pushes to `main`, with
read-only repository permissions and disposable PostgreSQL credentials.

## Project layout

```text
src/anoifig/
  api/          HTTP entrypoint and dependency wiring
  identity/     OIDC verification and tenant authorisation
  businesses/   Business boundary
  customers/    Customer schemas, repository and service boundary
  messaging/    Phone links, conversations, durable queues, worker and Twilio adapter
  db/           SQLAlchemy models and transaction/session infrastructure
  config.py     Validated environment configuration
migrations/     Reviewed Alembic schema and RLS changes
tests/          Unit and real-PostgreSQL integration tests
scripts/        Local/CI role setup and post-migration grants
docs/adr/       Architecture/security decisions
docs/runbooks/  Operational development instructions
```

The API and messaging worker share domain services in this package. Future AI,
invoice, voice and Flow modules must call authorised domain services rather than
write database records directly. The queue contract can later be adapted to
Azure Service Bus; the current implementation uses PostgreSQL locally. See
[ADR 0004](docs/adr/0004-whatsapp-messaging.md).

## Future Azure deployment

No Azure resources are created and no deployment is included. A future reviewed
release can run this same runtime image as separate API and worker Container
Apps, with private PostgreSQL, certificate-verified TLS, secrets from Key Vault,
and managed identities. A Service Bus adapter must implement the queue contract
and preserve the database as the durable acceptance and outbox boundary: a
database pump must republish unpublished work after failures, consumers must
complete messages only after their database commit, renew processing locks, and
route exhausted work to a monitored dead-letter queue. Broker duplicate detection
is supplementary; database uniqueness and handler idempotency remain required.
The adapter, deployment definitions and failure tests still need implementation.
See [the deployment checklist](docs/runbooks/messaging.md#future-azure-deployment).

## Production decisions still required

This is a foundation for further implementation, not approval to onboard paying
customers. Choose and configure the managed OIDC provider and MFA policies;
design audited identity/membership provisioning; choose production infrastructure
and secret delivery; add rate limiting, telemetry, audit retention and backups
with restore tests. Production database roles, network/TLS controls, and staging
deployment require review. The blueprint's staging deployment and broader
hardening exit criteria are deferred because this task authorises local
development and CI without paid Azure resources.

For **every** production API, worker, migration, and grant-script process,
explicitly set `ANOIFIG_ENVIRONMENT=production` and supply the appropriate private
database URL. All these paths require `postgresql+psycopg`, a single TCP hostname,
`sslmode=verify-full`, and an explicit trusted `sslrootcert` path; they also verify
that the established PostgreSQL session uses TLS. Mount the CA in each process's
filesystem. Plain local example URLs are intentionally unsuitable for production.
See [ADR 0003](docs/adr/0003-production-database-tls.md) and the runbook for the
release requirements; migration/grant commands do not load `.env` themselves.

The four low-severity review findings remain open in the
[technical debt register](docs/technical-debt.md), with completion criteria and
target gates. Passing the current test suite does not close those items.

Before real WhatsApp delivery, approve Twilio/Meta onboarding and the sender,
credential rotation and webhook exposure, rate limits, retention/deletion policy,
vendor DPAs and privacy/transfer review, callback monitoring, uncertain-send
reconciliation and operational ownership. Test proxy URL/signature handling,
delivery failures, revocation, recovery and load in staging with approved test
accounts. The [messaging runbook](docs/runbooks/messaging.md) records these gates.
OpenAI access, invoice issuance and Irish tax review remain later milestones.
Work through reviewed branches and pull requests; do not merge or deploy
automatically.
