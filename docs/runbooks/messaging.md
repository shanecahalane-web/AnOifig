# WhatsApp messaging operations

This runbook describes Milestone 2 local development and requirements for a
future reviewed deployment. It does not provision Azure, connect live accounts,
change production Twilio settings or authorise chargeable sends. There is no
OpenAI, voice, invoice or interactive Flow implementation.

## Local API and worker

Use the database setup and OIDC instructions in the [README](../../README.md) and
[database runbook](database.md). No cloud account or live Twilio credential is
needed for local startup or the automated suite.

```sh
cp .env.example .env
docker compose up --build -d
docker compose ps -a
docker compose logs api worker migrate
curl --fail http://127.0.0.1:8000/health/ready
```

The migration service applies Alembic and reviewed runtime grants before API and
worker startup. Both runtime processes use the restricted application role and
an unprivileged container user, with capabilities dropped. The schema-owner URL
is supplied only to migration/grant setup. Preserve these boundaries in a future
release. Apply migrations and grants before restarting both API and worker.

Compose starts `python -m anoifig.messaging.worker --local`. This explicit
simulator returns synthetic message SIDs and never calls Twilio; a simulated
`sent` status is not evidence of actual delivery. It is forbidden in production.
Twilio ingress remains disabled unless configured. To run the worker on the host,
export the reviewed local `.env` settings, then use:

```sh
uv run --frozen python -m anoifig.messaging.worker --local
uv run --frozen python -m anoifig.messaging.worker --local --once
```

The first command polls continuously; `--once` processes one discovery batch.
A newly created outbound job is discovered in a subsequent batch. PostgreSQL
is the durable work source, so stopping the worker does not discard accepted
messages. Stop the first process before using the second for manual diagnosis.
Only source private environment files you trust. Never point this setup or the
test suite at a real customer database.

## Public webhook and Twilio configuration

Keep `ANOIFIG_TWILIO_ENABLED=false` until an account/environment is approved.
To enable ingress, supply these settings together through private environment
configuration or an approved secret store:

- `ANOIFIG_TWILIO_ACCOUNT_SID`: expected `AC...` account identifier.
- `ANOIFIG_TWILIO_AUTH_TOKEN`: secret signature/API credential.
- `ANOIFIG_TWILIO_WHATSAPP_NUMBER`: approved `whatsapp:+...` sender address.
- `ANOIFIG_TWILIO_INBOUND_URL`: exact public URL for `POST /webhooks/twilio/inbound`.
- `ANOIFIG_TWILIO_STATUS_URL`: public base URL for `POST /webhooks/twilio/status`.
- `ANOIFIG_TWILIO_ENABLED=true`: explicitly enable the adapter.

`ANOIFIG_TWILIO_HTTP_TIMEOUT` optionally selects the API timeout in seconds
(default 10, range 1–30). All URLs require HTTPS in production. Keep credentials
out of command arguments, shell history, logs, committed files and PR text.
Secret rotation must update every API and worker process consistently and be
validated in an approved environment. A rotated token changes signature checks.

Configure Twilio's inbound WhatsApp webhook with method **POST** to the exact
inbound URL. The worker supplies an operation-specific status URL such as
`https://messaging.example.invalid/webhooks/twilio/status?attempt_id=<uuid>`.
The `attempt_id` is the stable outbox UUID, reused only across definite safe
retries. Do not remove or alter that query. If configuration includes a static query,
Twilio must preserve it as well. Forward proxies must preserve paths and queries.
The signature is checked against configured URLs, not an internal container URL
or untrusted forwarding headers. Configure a stable approved public HTTPS URL
before any actual sandbox/staging smoke test; local loopback alone cannot be
reached by Twilio. There is no automatic tunnel or cloud resource creation.

Requests require `application/x-www-form-urlencoded`. Inbound fields include
`AccountSid`, `MessageSid`, `From`, `To`, `Body` and `NumMedia=0`. Text must be
nonblank and within the supported 1,600-character limit. Media and interactive
payloads are outside this milestone. Invalid signatures, wrong accounts/senders
and unknown/unverified users fail closed; errors never echo the message body or
phone/token values. The accepted response contains no inline TwiML reply: the
worker sends only after database acceptance.

Compose always uses the simulator. Only for an explicitly approved account,
replace its worker command using a private Compose override with:

```yaml
services:
  worker:
    command: ["uv", "run", "--no-sync", "python", "-m", "anoifig.messaging.worker"]
```

The corresponding host command omits `--local`. This uses the real Twilio API
and can incur charges. Do not alter production Twilio settings or run a real
sender as part of ordinary automated verification.

## Link a phone to an existing authorised account

A trusted provisioning operator must already have created the business, mapped
OIDC user and active `owner` or `staff` membership. Phone possession cannot
create these records, infer a tenant or escalate a read-only membership.

1. Authenticate to the API with the existing verified OIDC access-token contract.
2. Request `POST /v1/businesses/{tenant_id}/messaging/links` with JSON
   `{"phone": "+353..."}` and the bearer token. The phone is bare E.164 here;
   Twilio webhook addresses include the `whatsapp:` prefix.
3. Handle the returned link ID, token and expiry privately. Only the token hash
   is stored. The challenge expires after ten minutes and can be redeemed once.
4. From that exact phone, send `LINK <token>` to the configured WhatsApp sender.
   Redemption requires a valid Twilio signature and current write membership.
   The confirmation body is not stored as a conversation message or passed to Tara.
5. Send ordinary text from the verified number. The worker persists a single
   deterministic Tara response per accepted inbound message.

There is one active verified business route per phone. A shared phone cannot
implicitly select among businesses. Revoke the old link before linking a new
business/account. Expired, reused or wrong-phone tokens cannot confirm a link.
The API limits outstanding challenges per user; distributed rate limits remain
a production gate.

Revoke a user's own link using the authenticated
`DELETE /v1/businesses/{tenant_id}/messaging/links/{link_id}` route. Deactivating
the business, user or membership also removes messaging authority on subsequent
checks. Revocation is checked again on queued processing and dispatch; it cannot
recall a message already accepted by Twilio. Establish an audited administrator
process for leavers, number loss/reassignment and forced revocation before launch.
There is no public provisioning or administrative bypass endpoint.

Signed delivery callbacks also require the current active linked identity and
membership. Callbacks after revocation return 403 under the same tenant RLS
boundary. The worker parks the content-free job as `access_revoked`; outbound
content can remain `dispatching` or `uncertain`. A trusted operator must reconcile
provider acceptance without automatically resending or relaxing database policies.

## Failure handling and safe recovery

The API acknowledges only after the accepted message and work state commit.
If persistence fails, Twilio can redeliver. A unique inbound SID prevents a
replay or concurrent delivery from creating another accepted action. Replays do
not refresh the WhatsApp window. The worker commits reply/outbox creation before
sending; a provider failure cannot lose the intent to send.

Outbox states distinguish pending/retry work, dispatch in progress, sent,
blocked, failed and uncertain outcomes. Processing errors are bounded codes;
retain these for diagnosis without dumping payloads or provider exceptions.

| Outcome | Automatic behavior | Operator action |
| --- | --- | --- |
| Duplicate webhook/job/callback | Reuses or ignores persisted state. | Investigate only if volume suggests a provider/proxy issue. |
| Database failure before inbound commit | No success acknowledgement. | Restore database readiness; allow Twilio redelivery. |
| Worker failure before dispatch | Durable work is rediscovered/retried within bounds. | Inspect persisted error codes and queue age. |
| Explicit Twilio 429 rejection | Bounded delayed retry, with a minimum delay. | Monitor sustained throttling and capacity; do not bypass limits. |
| Permanent provider client rejection | Failed; no automatic resend. | Correct sender/configuration or destination after reviewing the error code. |
| Timeout, server error, invalid response, expired dispatch lease | Uncertain; no automatic resend. | Reconcile the original attempt before deciding any further action. |
| Revoked authority | Operational job parked with `access_revoked`; tenant content is unchanged. | Use the proper authorisation workflow; parked jobs have no automatic replay. |
| Expired 24-hour window | Outbox blocked with `template_required`; no free-form send. | A fresh authorised inbound message creates a new reply; older blocked work is not automatically revived. Approved templates require future implementation. |
| Exhausted processing/retry limit | Failure retained. | Diagnose root cause; review a recovery change with idempotency intact. |

Do not bulk-reset `dispatching`, `uncertain`, `sent`, or terminal failure rows to
`pending`. Twilio may already have accepted the message. Match a signed callback
to the immutable outbox correlation ID and expected account/SID, or have an authorised operator
review provider records using that attempt's metadata. Keep a record of the
review. This milestone does not include an operator replay API or a safe
provider-side message-creation idempotency key; an intentional new send requires
a separately reviewed action. A callback may resolve uncertainty, but absence of
a callback never proves that nothing was sent. Avoid restoring an old backup and
blindly replaying its outbox without provider reconciliation.

The free-form WhatsApp window is 24 hours after the accepted inbound message and
is rechecked at dispatch. Approved templates and opt-in/template management are
not implemented. Do not send free-form text outside the window. Delivery states
must come from provider results/callbacks; API acceptance is not delivery.

## Tests and migration verification

```sh
uv sync --frozen
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy src
uv audit --locked
docker compose --profile test run --build --rm tests
```

The full suite requires dedicated runtime/admin PostgreSQL URLs for a disposable
database ending `_test`. It validates forced RLS with the restricted runtime role,
linking/revocation, signed/invalid requests, replay/concurrency, message/outbox
persistence, callbacks, provider failures and retry safety. Twilio API calls are
mocked; no live credentials are used. Follow the database runbook for host test
execution and approved custom CA configuration.

Review migration SQL and runtime grants together. Never use `create_all`, run
migrations automatically in the API/worker, or fix RLS/grant failures by using
the schema owner at runtime. Messaging downgrade removes its persisted data and
must be limited to disposable verification or an explicitly reviewed release
plan. Backups and rollback/forward-fix strategy are required before production.

## Future Azure deployment

This is a design target, not a completed deployment. Before enabling any cloud
service, obtain the required infrastructure, region, account, budget and release
approval. Do not create paid resources through this runbook.

- Run API and worker as separate Container Apps using the same reviewed image;
  enforce HTTPS, private database access, trusted certificates and restricted
  runtime credentials. Explicitly set `ANOIFIG_ENVIRONMENT=production` for API,
  worker, migration and grant processes. Retain separate owner secret delivery.
- Implement and test a Service Bus queue adapter using managed identity and
  least-privilege send/receive permissions. The current PostgreSQL queue remains
  the local implementation; a production broker adapter is not included.
- Keep durable database publication discovery/pumping. Publish committed opaque
  work identifiers; repeat publication after crashes and tolerate duplicates.
  Never replace the database commit with a volatile publish call.
- Complete a broker message after the domain transaction commits. Renew locks
  for long work; configure retry delays, lock duration, TTL, maximum deliveries
  and a monitored dead-letter queue. Test crash before/after commit, lease loss,
  duplicate broker messages and broker/database outages.
- Keep the outbound outbox and conservative uncertain-send policy. Broker
  duplicate detection cannot deduplicate Twilio API side effects. Do not route
  ambiguous sends through an automatic DLQ replay.
- Use Key Vault/approved secret delivery, managed identities for Azure access,
  encryption, network restrictions, rotation and independent environments.
  Health/readiness, worker liveness and queue backlog need distinct monitoring.

## Remaining production gates

Select and verify the managed OIDC provider, provisioning authority and MFA
policies. Approve Twilio/Meta sender registration, account access, opt-in behavior,
customer-service/template policy and credential rotation. Exercise real proxy
signature handling, status callbacks, rate limits, membership revocation and
failure recovery in staging with approved synthetic test users.

Set numeric service targets after measurement. Alert on acceptance failures,
worker heartbeat loss, oldest queued work, pending/retry depth, uncertain and
failed/blocked and parked-job counts, Twilio throttling, missing callbacks, DLQ growth and
cross-tenant/RLS errors. Correlate internal UUIDs and redacted codes; do not log
phone numbers, link tokens, message bodies, signatures, credentials or DSNs.
Review reverse-proxy/access logs and tracing libraries as well as application
logs. Apply distributed request limits and ingress body limits, with allowlisted
administrative observability access.

Approve message/link retention, deletion/export workflows, privacy notices,
vendor DPAs, international transfers, data access audit and incident response.
Messages contain personal data; the schema does not implement an automatic
retention/deletion scheduler. Establish encrypted backups, restore tests, RPO/RTO
and a post-restore provider reconciliation procedure. Add an audited leaver and
phone-reassignment process with clear operational ownership.

The four open Milestone 1 findings in the [technical debt register](../technical-debt.md)
remain deployment gates. Conduct load, security and independent tenant-isolation
review; preserve certificate and artifact verification. Merge and deploy only
through human-reviewed, explicitly authorised operations.
