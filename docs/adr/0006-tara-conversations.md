# ADR 0006: Tara proposals, durable notes and fenced model calls

Status: proposed for Milestone 3 review, 16 October 2026.

The final review corrections in [ADR 0007](0007-tara-evidence-and-provider-isolation.md)
refine financial-expression validation, response rendering, expiry, context replay
and the provider execution boundary described here.

## Decision

Use the supported OpenAI Python SDK through a small `AIProvider` protocol. Keep
the modular monolith and existing PostgreSQL messaging queue. No agent framework,
external conversation store, new cloud resource or live account is required.

The worker selects `acknowledgement`, `mock`, or `openai` through configuration.
The first two modes are for local development; production workers require OpenAI.
The API can run without AI configuration because it only durably accepts messages.
OpenAI receives one bounded request with a versioned system instruction, validated
preparation notes, a bounded history and the current message. Phone-link routing,
tenant/user IDs, credentials and customer database records are never sent. Stored
customer contact details are omitted from the structured notes supplied to the
provider. Prior inbound context omits successful structured-edit turns, including
legacy contact corrections regardless of intent, removes the stored contact-detail
literal, and redacts common email/phone/IBAN patterns; outbound raw
prose is not replayed. Current input still contains explicitly supplied user data,
and arbitrary free text may contain PII these rules cannot recognise.

Use structured `Reply` output and one strict function tool,
`propose_invoice_notes`. Unknown/multiple tools, extra properties, refusals,
truncated results and invalid output fail closed. The tool proposes evidence-backed
field changes; application code reauthorises, validates and persists them. No model
has a database handle or accepts tenant IDs, SQL, paths, code or invoice approval.
Application templates ask missing invoice questions and describe unsupported
features. Social replies select one reviewed speech act; application templates
render it.
Raw model prose and free-text note fields are never interpolated into assistant
status assertions. Customer names receive structural validation and a separately
labelled, quoted display; the preparation acknowledgement is fixed text. No invoice/email/payment action exists
to report as completed.

`InvoiceNotes` are **preparation notes**, not an invoice or financial draft. EUR
amounts are decimal strings with at most two places and a maximum of €1,000,000.
Deterministic Decimal validation rejects non-finite/negative/exponent values and
excess precision without rounding. Quantity and unit price must be positive;
line products are bounded but no final VAT or invoice total is calculated.
Money updates must match full original-message numeric tokens inside verbatim
current-message evidence, retaining currency/sign/precision context. Cropped,
negative, non-EUR, exponent, excess-precision and unsupported arithmetic evidence
fails closed. Text updates must also be grounded in that evidence. Currency
conversion, inferred arithmetic and inferred VAT rates are unsupported. VAT
requires explicit VAT-specific text or a complete short answer to the matching
application-owned pending question. Unrelated prices/dates cannot ground VAT.
The model still interprets customer/work semantics; token checks cannot prove all
semantic interpretation correct. Selective line patches bind to the application's
captured notes version and exact unique item selector. Only changed fields require
new evidence; unchanged values survive. Full replacements and patches are mutually
exclusive; duplicate item/field changes and ambiguous selection are rejected.

## Transactions and recovery

1. Recheck restricted runtime privileges, the verified route, active user/business
   and write membership. Lock the conversation, then its source message. Only the
   earliest unprocessed inbound by `(received_at, id)` can proceed. Ingress records
   its acceptance timestamp after acquiring the same conversation lock. This is
   application acceptance order; Twilio provides no authoritative sender sequence
   for reconstructing messages delayed before ingress.
2. Check the existing run before changing memory on duplicate delivery. Load
   per-conversation, per-user notes under forced RLS. Expire old notes and
   bound history by age/count/content size. Insert a unique `tara_runs` processing
   record, opaque token, two-minute deadline and conservative daily business
   reservation. Commit before provider I/O, releasing all locks/connections.
3. Run the async SDK in a fresh Linux child interpreter behind the synchronous
   provider adapter. The parent bounds the complete operation (default 60 seconds,
   maximum 90), then uses bounded terminate/kill cleanup. This contains blocking
   resolver threads and SDK teardown as well as HTTP, retries and Retry-After
   delays. Linux parent-death signalling kills the child if its worker dies.
   Per-HTTP timeout remains 15 seconds by default. See ADR 0007 for the environment
   boundary and operating-system limits; asyncio cancellation alone does not bound
   DNS teardown. OpenAI mode fails closed outside Linux.
4. In a fresh transaction recheck authorisation, lock the conversation/message,
   and require the same active run token and application-captured state version.
   A stale completion leaves the newer notes intact. Validate the outcome, apply
   the sole
   allowed action, record content-free action/usage metadata, and create a single
   reply/outbox while marking the input processed. All commit atomically.
5. Expired runs recover with one fallback and **no second model invocation**.
   Reservations remain charged on failures, crashes and lost acknowledgements.
   Late results cannot replace a completed reply. Existing reply/outbox uniqueness
   also protects local idempotency after an uncertain commit acknowledgement.

SQL/preparation/completion failures enter the existing bounded five-attempt inbound
ledger. Only the conversation head may accrue failures. Terminal recovery fences
any run, preserves reservations, creates one fallback atomically and lets later
messages advance. A lost commit acknowledgement is reconciled from the processed
source without another model call. Failure recording itself requires a healthy
database; persistent database outages need operational recovery.

Concurrent messages defer behind the conversation head. Existing queue receipts,
leases, contention cooldown and fair scheduling still apply. A revoked identity
cannot save AI results; the existing content-free job is parked for operator
reconciliation. A parked head intentionally prevents later messages bypassing an
unresolved turn; operators must investigate rather than silently skip it.

The existing outbox owns actual WhatsApp sends, callbacks, 24-hour eligibility,
retries and uncertain-delivery protection. AI never sends directly. Replies
dispatch in durable source inbound `(received_at, id)` order. A pending,
retry, dispatching or uncertain predecessor blocks newer replies until resolved;
there is no age-based suppression. Conversation -> outbox -> message locks serialise
preparation and result persistence. Callback locks remain outbox -> message and do
not acquire a conversation lock. No transaction is held during provider I/O.
Uncertain sends need callback/operator resolution, never automatic replay.
Exactly-once external delivery or mobile-network arrival order is not claimed.

## Budget and audit semantics

`tara_usage` is shared by active writing members of a business and locked during
reservation. Daily boundaries are UTC. Global defaults and per-business UUID JSON
overrides limit request attempts, reserved tokens and estimated USD. Reservations
cover maximum input/output times all SDK attempts; they are deliberately not
refunded. `tara_runs` separately tracks successful provider-reported usage and
estimated cost, configured model, prompt version, intent, permitted action, timing
and safe error code. Failure usage is unknown and remains conservatively reserved.
Estimated costs use configured reviewed prices; they are not billing statements.

No conversation text, tool arguments, keys or raw SDK exceptions are logged.
Structured fallback/failure events and the RLS-protected run/usage tables support
operator monitoring. There is no external telemetry backend or automated alert
routing in this milestone.

## Migration and retention

Migration 0005 adds three forced-RLS tables, a composite source-message constraint
and a pending-conversation index. New tables have only SELECT/INSERT/UPDATE runtime
grants; no privileged gateway or broad function grant is added. State/run access
requires the same authorised conversation user; usage exposes business aggregates
only to active writing members. Composite foreign keys prevent cross-tenant/user
source substitution. Historical migrations remain unchanged. Forward migration 0006 adds nullable reset
frontier UUID, pending VAT clarification, captured run version and message version
metadata with checks. Existing values, RLS, owners and grants are preserved; no new
runtime privileges or data backfill is needed. Downgrading 0006 discards only this
metadata and restores 0005's known defects; prefer a forward fix.

Stop workers/API for migration and grant verification, then restart. Index and
constraint creation can block writes; plan a maintenance window. The downgrade
preserves messaging records but **deletes Tara notes, audit and usage records**.
After usage counters have been used, do not downgrade/re-upgrade and resume live
traffic on the same day: the budget ledger would reset. Prefer a forward fix.

Memory is bounded to 1–90 days (default 30), including an absolute age check, and
lazily erased on the next turn. Exact commands `forget my notes`, `clear my notes`,
`start a new invoice` and `start over` clear preparation notes and stop replaying
older history without a model call. The frontier is the reset source message's
accepted `(received_at, id)`, not processing time. Already queued later messages
remain in context. Reset frontier UUIDs are ordering metadata without a foreign key,
so future erasure cannot accidentally reopen older history. These are conversation controls, not deletion
of raw WhatsApp messages, provider copies or backups. Physical erasure of dormant
notes and raw messages needs an approved scheduled retention/subject-rights
workflow before production. The concrete [retention/deletion design](../retention-and-deletion.md)
sets proposed periods, dormant sweeper semantics, dependency-safe deletion,
operational holds, vendor/backup treatment and subject-rights evidence. It is not
implemented: production remains blocked until implementation and testing.
No GDPR compliance claim is made.

## Future invoice tools

A future domain service must own `create_invoice_draft` / `update_invoice_draft`
with tenant/user access, a validated EUR money schema, explicit draft version,
expected prior version and message-bound idempotency key. Its preview must compute
prices and VAT deterministically. An `approve_invoice` contract must bind an
explicit user action to the exact draft/version; model text is never approval.
`issue_invoice` then needs atomic numbering, immutable records and audit/outbox
semantics. None of these tools, PDFs, issuance or financial delivery is implemented
or allowlisted here. Adding a tool requires a separate reviewed domain contract,
authorisation, schema, idempotency and adversarial tests.
