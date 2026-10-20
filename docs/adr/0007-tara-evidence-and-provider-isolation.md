# ADR 0007: Financial expressions, minimal context and isolated provider calls

Status: proposed for Milestone 3 independent review, 18 October 2026.

## Evidence and response authority

Validate proposed amounts against complete expressions in the original message,
including currency, sign/accounting notation, uncertainty and alternatives. EUR
decimal values use Decimal; unsupported syntax requests clarification and leaves
the saved notes unchanged. Currency conversion, guessed prices, general arithmetic
and automatic VAT selection remain unavailable. A proposed unit price can be
validated against one item's stated quantity and total by exact Decimal product
equality. This is a conservative supported
language grammar, not a claim to understand arbitrary financial prose or tax law.
Currency lexing commits overlapping code matches atomically so repeated currency
words cannot cause exponential regex backtracking while holding a conversation
transaction. A subprocess-bounded regression covers the ingress-sized case.
Currency annotations also apply when separated from the amount by parentheses,
prepositions or field labels. Explicit foreign symbols/codes cannot be dropped
by selecting only a numeric excerpt; qualified code syntax is case-insensitive.

Bind item patches to the application-captured version and a complete original
item clause. The clause must identify the selected item and support the changed
quantity or unit-price role. A model-selected excerpt cannot borrow a value from
another clause, omit negation or turn a preservation instruction into an update.
Item-only connector boundaries include another item's bare price, without changing
the scalar/VAT clause grammar. Numeric roles consider currency-marked and bare
price labels. Total, subtotal and overall amounts cannot become unit prices via
generic price/cost/at labels; deposits cannot supply a whole-line total. Explicit
unit prices and line totals on the same item must agree. Derivation requires one
supported, unambiguous item total and a source quantity, or the final captured
quantity in a version-bound correction. The backend verifies the proposed
quantity times unit price exactly, including quantity-only corrections. It never
divides or rounds a quotient; non-exact cents and conflicting evidence clarify.
VAT validation examines the polarity and alternatives of the full assertion;
short answers still require the application's matching pending clarification.
Questions and rejected assertions do not establish financial or VAT facts.
Shared assertion checks inspect the surrounding original sentence, including
soft comma/conjunction continuations, when proposed evidence contains only a
number or basis phrase. Hard sentence/semicolon/newline boundaries preserve
independent affirmative statements alongside unrelated questions.
Numeric-rate choices also retain textual exemption, no-VAT and zero-rating
alternatives, including cropped evidence and formatted continuations. Recognising
these terms does not map one tax treatment onto another: an explicit zero-percent
rate stays a rate, and exemption cannot supply one. Conflicting comma/and
treatment assertions also require clarification; a
numeric rate plus inclusive/exclusive basis remains a compatible pair of facts.
Treatment-replacement prose
such as "instead of" or "rather than" requires a clear single-treatment restatement
under the existing conservative historical-expression boundary. Rejections use
an application-owned clarification question and preserve the prior notes.

Customer names have bounded, single-line structure supporting Unicode personal
and business names. Application status statements never interpolate customer names
or other arbitrary model/user text. A separately labelled, JSON-quoted customer name
is displayed only after revalidation; invalid legacy names are omitted. Reviewed social speech acts, missing-field
questions and capability statements remain application-owned. Preparation notes
are not issued invoices, emails, payment requests or evidence of completed actions.

## Conversation state and privacy

Check the source's existing run before expiring state. A duplicate of a live run
does not mutate notes, timestamps, version or reservations. Expiry advances its
durable source boundary once and refreshes the state's activity timestamp. The
completion token/version checks still reject genuinely stale or expired results.
Rejecting a stale completion leaves the newer notes, pending clarification and
activity timestamp intact while finishing only the old run and its fallback.

Validated structured notes carry the task facts. Do not replay raw successful
note-edit turns, including historical `notes_merged` records and contact edits
classified as corrections. Derive `contact_notes_merged` audit metadata from
accepted `customer_details` changes, independently of model intent. This uses the
existing action column and also protects old records without a migration/backfill.
Bound and minimise remaining conversational context; omit stored contact details
from structured provider context and redact supported email, IBAN and telephone
formats. Current input is still sent for extraction. Pattern matching cannot
detect arbitrary personal information or perform physical deletion.
Telephone separators include horizontal non-breaking and narrow non-breaking
spaces; numeric boundary and currency controls still protect ordinary amounts.

## Provider lifecycle

An asyncio timeout cannot stop a blocking resolver thread, and per-call
`asyncio.run()` can wait for that thread during executor shutdown. Therefore the
synchronous worker runs each real SDK operation in a short-lived local child
process. This is process isolation inside the same modular monolith, not another
service, framework, queue or cloud resource.

The child receives only the necessary request, model configuration and key through
JSON on standard input. It has no database engine or database credentials in its
configuration/environment. Preserve approved proxy and CA settings and the SDK's
TLS verification. A validated, bounded JSON result returns through standard output
backed by an anonymous memory-only descriptor, without a temporary disk copy;
raw exceptions and child stderr never enter application logs.

The parent enforces an elapsed-time deadline and bounded termination/kill/reaping
on timeout or cancellation. Blocking DNS and executor teardown stay in the child.
Linux parent-death signalling terminates the provider child if the worker dies;
unsupported platforms fail closed instead of falling back to unbounded execution.
The parent remains the sole owner of database completion. A late child result
cannot bypass the durable run token/version fence or create a second reply.

This is an application deadline under supported Linux process semantics, not a
hard real-time guarantee during kernel/process-creation failure or host starvation.
Deployment still requires host supervision, liveness/backlog alerts and staging
failure tests. Killing local work cannot cancel a request already accepted by the
remote provider. Existing conservative reservations remain charged and model calls
are not replayed after ambiguous/committed runs. No billing or zero-retention
guarantee is claimed.

## Operations and verification

No new dependencies, tables, privileges or migration are required. Migrations
0005/0006 and existing runtime RLS/grants remain authoritative. The OpenAI worker
now requires supported Linux process controls; acknowledgement/mock modes remain
available for offline development. Production remains blocked by the separate
retention/subject-rights, monitoring, provider/privacy/tax and staging gates.

Verify the reviewed-source failures before and after, positive financial/name
cases, cross-clause/negative/alternative variants, full persisted replies and
provider payloads, duplicate expiry under real restricted-role PostgreSQL, actual
transport resolver stalls, cancellation and parent death. Retain the complete
Milestone 1/2/3 suite, migration/security checks, dependency audit and Docker/CI.
