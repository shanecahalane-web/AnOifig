# ADR 0004: Verified WhatsApp links and durable messaging outboxes

Status: proposed for Milestone 2 review, 15 October 2026.

## Context

Tara needs reliable two-way WhatsApp text without Power Automate. Twilio can
redeliver webhooks, callbacks can arrive before the send response or out of order,
and a worker can fail between Twilio accepting a send and committing its SID.
Neither phone possession nor a signed provider webhook establishes business
membership. PostgreSQL tenant isolation and the Milestone 1 identity boundary
must remain in force.

## Decision

Keep the shared typed modular monolith and run the API and worker as separate
processes. Add messaging services, a provider protocol with a Twilio adapter and
an explicit local simulator, and a queue protocol implemented using PostgreSQL.
No Azure provisioning or Service Bus SDK is required locally. Future AI,
invoicing, voice and Flows remain outside this change; accepted authorised text
gets the fixed Tara acknowledgement only.

### Signed ingress and explicit account linking

Use the maintained Twilio SDK to verify `X-Twilio-Signature` over all submitted
form fields and the exact configured public request URL. Status URLs include
an immutable outbound-operation `attempt_id` (the outbox UUID, retained across
definite safe retries). Configuration supplies the external
scheme, host, path and any static query; request `Host` and forwarded headers
never select the verification URL. Validate the account SID, WhatsApp addresses,
text-only payload and bounded form size/field count before domain processing.
Invalid signatures and unknown/unverified senders receive generic rejection.
Malformed or repeated form fields are rejected without including input in errors.
Production requires HTTPS. Twilio-disabled startup fails closed at these routes.

The Twilio SDK deliberately accepts URL signatures with and without an explicit
port. The configured scheme, host, path, query and submitted parameters remain
authoritative; port differences cannot isolate services sharing a Twilio token.
Use separate credentials and origins for independently trusted environments.

An authenticated active `owner` or `staff` member requests a link for their own
account and a specific E.164 phone through the tenant API. Return a cryptographic
single-use token with a ten-minute lifetime, persist only its hash, and redeem it
only when a signed inbound `LINK <token>` comes from the exact expected phone.
This proves phone control and binds it to an existing authorised membership;
it never creates membership. Permit only one active verified business route
per phone. Revocation and active user, business, membership and write-role checks
apply again during ingress, processing, dispatch and callbacks. Callbacks after
revocation are rejected; the worker parks only the content-free operational job,
leaving tenant content unchanged for trusted operator reconciliation. A phone change or route
change requires another link challenge. Confirmation bodies and tokens must not
be logged or retained as conversation text.

### Persistence and tenant boundaries

Persist tenant-owned phone links, conversations, inbound/outbound messages and
outboxes with UUIDs, UTC timestamps and composite tenant foreign keys. Store
Twilio SIDs uniquely and retain bounded processing-error codes rather than raw
provider exceptions. Content and phone-link access use forced PostgreSQL RLS
with the existing verified identity and transaction-local tenant context.

Initial webhook and worker routing necessarily starts without an OIDC bearer
request. Reviewed database gateway functions return only the routing/work
identifiers needed to establish the stored linked identity; content remains in
the ordinary RLS tables. The runtime role has narrowly reviewed function/table
permissions and remains non-owner, non-superuser and NOBYPASSRLS. Services
recheck active authorisation after resolving a route; gateways must not accept
arbitrary SQL or return message bodies. Source-table triggers maintain the content-free work index atomically.
As in ADR 0002, the application is trusted to establish context: arbitrary SQL
execution or stolen runtime credentials can forge application context. These
policies do not isolate a fully compromised runtime process.

### Durable work, outbox and retry semantics

The webhook commits the inbound message and work discovery state before its
2xx acknowledgement. PostgreSQL uniqueness deduplicates provider SIDs under
concurrent deliveries. Replays do not reopen the customer-service window. The
worker locks/rechecks state and creates at most one reply and outbox entry per
inbound message in one transaction. A polling queue can rediscover committed
work after process failure; an in-memory queue is not the durable boundary.

Migration 0003 adds content-free operational claims without rewriting migration
0002 or discarding accepted messages. Claims select ready, due jobs atomically
with `FOR UPDATE SKIP LOCKED`. Revision 0004 corrects its permanent priority for
never-claimed jobs: order by the later of due time and last claim time, then due
time and UUID, as explained in [ADR 0005](0005-queue-scheduling.md). Each receives
an opaque receipt and a two-minute lease. Receipt-bound
settlement cannot release another worker's claim. Contended work is abandoned
with a short cooldown; a batch that settles no work delays the polling loop.
Expired claims become available after a crash. Source row locks, current
authorisation and idempotency remain mandatory even with a valid claim.

Dispatch records the outbox correlation ID, attempt count and state before
calling Twilio.
Commit the send result/SID separately, reconcile signed status callbacks against
that outbound operation, and prevent duplicate callbacks or older delivery states from
repeating work or regressing known progress. Check active authorisation and the
24-hour customer-service window again immediately before dispatch. Expired
windows block free-form replies; approved-template sending is deferred.

Twilio message creation has no assumed idempotency-key guarantee. Disable SDK
HTTP retries. Retry an explicit rate-limit rejection with bounded backoff, and
record permanent client failures without retrying. A timeout, server error,
malformed success response or stale dispatch lease is `uncertain`: acceptance
may already have occurred, so do not automatically send a second copy. A signed
callback can reconcile the attempt; unresolved uncertainty requires operator
review. Local database processing failures can retry safely within bounds;
exhausted work and errors remain persisted for investigation. This guarantees
idempotent local actions, not exactly-once customer delivery across systems.

A valid late successful send response may reconcile `uncertain` for the same
persisted attempt number. Lock the outbox and message, recheck the linked
identity, and advance status monotonically. A bound provider SID cannot be
replaced; conflicting or globally duplicated SIDs are recorded without replay.
Newer callback delivery/error progress is preserved. Failed late responses do
not reopen recovered work, and stale responses cannot change a newer attempt.

### Future Service Bus adapter

Retain the queue interface and durable database pump when adding Service Bus.
Publish opaque work identifiers only after their source transaction commits;
retry publication after failure. Complete broker messages only after the domain
transaction commits; renew locks for long work, deduplicate redelivery using the
database, and monitor/dead-letter exhausted jobs. Broker duplicate detection
cannot replace the source uniqueness constraints or outbox. Managed identity,
least-privilege queue permissions, private access, lock/TTL settings and deployment
infrastructure need separate implementation and staging failure tests.

## Consequences and release gates

Development and CI use a real disposable PostgreSQL instance, synthetic signed
webhooks and mocked provider API calls. Compose starts a simulator worker that
never contacts Twilio; `--local` is forbidden in production. Local simulation
cannot establish sender approval, actual WhatsApp delivery, or proxy behavior.

Review sender/account approval, OIDC provisioning, phone reassignment policy,
secret delivery and rotation, privacy/DPA and retention obligations, inbound
abuse limits, monitoring, backup restore, uncertain-send reconciliation and
operational ownership before a real deployment. A phone association is explicit
but must still be revoked when a number is transferred or a member leaves.
There is no automatic uncertain-send replay or approved-template implementation.
The four Milestone 1 items in the technical debt register remain open. Human PR
review and an authorised staging/deployment operation are still required.
