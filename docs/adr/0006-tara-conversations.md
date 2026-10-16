# ADR 0006: Tara proposals, durable notes and fenced model calls

Status: proposed for Milestone 3 review, 16 October 2026.

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
provider; user-supplied text/history can still contain personal information.

Use structured `Reply` output and one strict function tool,
`propose_invoice_notes`. Unknown/multiple tools, extra properties, refusals,
truncated results and invalid output fail closed. The tool proposes evidence-backed
field changes; application code reauthorises, validates and persists them. No model
has a database handle or accepts tenant IDs, SQL, paths, code or invoice approval.
Application templates ask missing invoice questions and describe unsupported
features. Social responses remain model-generated with a conservative action/link
filter; this is not a proof of semantic correctness.

`InvoiceNotes` are **preparation notes**, not an invoice or financial draft. EUR
amounts are decimal strings with at most two places and a maximum of €1,000,000.
Deterministic Decimal validation rejects non-finite/negative/exponent values and
excess precision without rounding. Quantity and unit price must be positive;
line products are bounded but no final VAT or invoice total is calculated.
Money updates must match complete numeric tokens in verbatim current-message
evidence. Text updates must also be grounded in that evidence. Currency conversion,
inferred arithmetic and inferred VAT rates are unsupported. The model still
interprets the semantic meaning of a field/VAT statement; evidence checks cannot
prove that interpretation is correct.

## Transactions and recovery

1. Recheck restricted runtime privileges, the verified route, active user/business
   and write membership. Lock the conversation, then its source message. Only the
   earliest unprocessed inbound by `(received_at, id)` can proceed. Ingress records
   its acceptance timestamp after acquiring the same conversation lock. This is
   application acceptance order; Twilio provides no authoritative sender sequence
   for reconstructing messages delayed before ingress.
2. Load per-conversation, per-user notes under forced RLS. Expire old notes and
   bound history by age/count/content size. Insert a unique `tara_runs` processing
   record, opaque token, two-minute deadline and conservative daily business
   reservation. Commit before provider I/O, releasing all locks/connections.
3. Make a bounded SDK call. Default timeout is 15 seconds and one SDK retry;
   maximum configuration is three 30-second attempts, below the two-minute fence.
4. In a fresh transaction recheck authorisation, lock the conversation/message,
   and require the same active run token. Validate the outcome, apply the sole
   allowed action, record content-free action/usage metadata, and create a single
   reply/outbox while marking the input processed. All commit atomically.
5. Expired runs recover with one fallback and **no second model invocation**.
   Reservations remain charged on failures, crashes and lost acknowledgements.
   Late results cannot replace a completed reply. Existing reply/outbox uniqueness
   also protects local idempotency after an uncertain commit acknowledgement.

Concurrent messages defer behind the conversation head. Existing queue receipts,
leases, contention cooldown and fair scheduling still apply. A revoked identity
cannot save AI results; the existing content-free job is parked for operator
reconciliation. A parked head intentionally prevents later messages bypassing an
unresolved turn; operators must investigate rather than silently skip it.

The existing outbox owns actual WhatsApp sends, callbacks, 24-hour eligibility,
retries and uncertain-delivery protection. AI never sends directly. Exactly-once
external delivery is not claimed.

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
source substitution. Historical migrations remain unchanged.

Stop workers/API for migration and grant verification, then restart. Index and
constraint creation can block writes; plan a maintenance window. The downgrade
preserves messaging records but **deletes Tara notes, audit and usage records**.
After usage counters have been used, do not downgrade/re-upgrade and resume live
traffic on the same day: the budget ledger would reset. Prefer a forward fix.

Memory is bounded to 1–90 days (default 30), including an absolute age check, and
lazily erased on the next turn. Exact commands `forget my notes`, `clear my notes`,
`start a new invoice` and `start over` clear preparation notes and stop replaying
older history without a model call. These are conversation controls, not deletion
of raw WhatsApp messages, provider copies or backups. Physical erasure of dormant
notes and raw messages needs an approved scheduled retention/subject-rights
workflow before production. No GDPR compliance claim is made.

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
