# Retention and deletion design — production blocker

Status: proposed implementation contract, 16 October 2026. No scheduled purge or
subject-rights workflow is implemented. Documentation is not GDPR compliance or
production approval. Product, privacy counsel and the operations owner must approve
the periods and vendor terms before implementation and launch.

## Data inventory and proposed periods

| Data | Proposed maximum | Required erasure behaviour |
| --- | --- | --- |
| Tara preparation notes and pending clarification | Configured memory period, default 30 days, absolute age and inactivity | Daily sweeper clears dormant `tara_states.notes` and pending question, increments version and advances the accepted-turn boundary; next-turn lazy expiry remains defence in depth |
| Raw inbound/outbound text, customer details embedded in messages | 30 days from acceptance | Daily privileged retention job deletes eligible conversation records in bounded batches; pending sends/runs become a visible operational hold requiring resolution within 7 days, never an unbounded silent exception |
| Content-free Tara run audit and daily cost reservations | 90 days, subject to finance/security approval | Remove completed runs after message deletion; retain only aggregate non-personal spend counters needed for billing reconciliation; never delete today's reservations while traffic can continue |
| Phone links, identity and memberships | Active relationship plus approved offboarding window | Revocation immediately denies access; subject erasure removes/pseudonymises mappings after resolving operational holds and lawful retention obligations |
| Application logs | 30 days maximum | Content-free event codes only; configure exporter expiry, prohibit request/body/SDK debug logs and DSNs; include incident exports in deletion scope |
| Backups | Rolling 35-day maximum, subject to restore/RPO review | Encrypted restricted backups expire on schedule; restored environments must apply the deletion ledger before API/workers resume |

Preparation notes are not issued invoices and have no assumed statutory invoice
retention requirement. A future invoice domain needs a separately approved lawful
retention schedule; it must not silently extend retention of conversational text.

## Purge implementation contract

Use a dedicated audited retention role, never broaden the runtime role's grants.
Select tenant/conversation batches with explicit scope and acquire the conversation
lock before message/outbox locks. Recheck active run tokens and send state under
lock. Cancel/fence eligible runs, preserve charged reservations for the current UTC
day, and reconcile dispatching/uncertain sends before deletion. Delete dependent
outbox and queue records, replies before source messages, completed run records,
and expired state in a transaction respecting existing composite foreign keys.
Delete callbacks/vendor identifiers only after provider reconciliation. Do not
disable RLS or FK constraints in application traffic to achieve erasure.

`memory_after_id` is ordering metadata, not a foreign key: deletion of the source
must not reopen older context. Keep the `(memory_since, memory_after_id)` frontier
until all earlier context is deleted, or advance it monotonically under lock.
The sweeper must operate without waiting for a new customer message, support
restartable checkpoints/idempotent batches, and publish content-free counts,
oldest overdue age and hold reasons. Alert on missed daily runs and holds older
than seven days; an accountable operator must resolve them before launch.

## Subject rights and vendor copies

Verify the requester through the managed identity/onboarding process; a WhatsApp
number alone is insufficient. Resolve authorised businesses and third-party rights
before exporting or deleting data. Produce a tenant-scoped inventory/export of
notes, raw messages, routing/identity records, run metadata, support exports and
vendors. Record the lawful basis and any narrowly scoped hold with expiry and
review owner. Provide correction, restriction, access, portability and erasure
procedures with tracked deadlines and an audited outcome. No public unauthenticated
subject-rights endpoint or model tool may initiate bulk exports/deletions.

OpenAI requests set `store=false`, which is not a zero-retention guarantee. Approve
the actual account's processing/abuse-monitoring retention and eligibility for
retention controls, DPA, subprocessors and transfers before live calls. Twilio and
WhatsApp may retain message bodies and metadata independently; document each
vendor's actual terms and deletion APIs, submit scoped requests, track failures,
and explain limits to the requester. Include telemetry, support systems, exports,
developer datasets and any future Azure resources in the inventory. No live
vendor policies or deletion endpoints were exercised in this milestone.

Maintain a restricted deletion ledger containing only identifiers/time/scope needed
to prevent restoration of erased data. Encrypt and expire that ledger under a
separate approved schedule. Backups normally expire rather than being rewritten;
document the maximum residual period and prevent customer access after restoration
until tombstones have been replayed. Where deletion is legally restricted, isolate
the minimum retained data, prohibit further model processing and communicate the
reason and retention period.

## Required evidence before production

Implement and test dormant expiry without inbound activity, tenant-scoped erasure,
concurrent processing/send races, uncertain-send holds, current-day budget
preservation, FK-safe batch deletion, interrupted/restarted purge, subject export
isolation, vendor failures/retries, backup expiry and restored-data tombstone
replay. Verify no PII in logs, monitor purge lag, restore a backup and demonstrate
that erased data cannot reappear. Obtain privacy/security sign-off, approved
vendor terms and named operational ownership. Until these controls exist and pass,
**production deployment and customer onboarding remain blocked**.
