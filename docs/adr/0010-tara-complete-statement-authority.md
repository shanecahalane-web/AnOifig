# ADR 0010: Reject unresolved preparation statements

Status: proposed for independent review; supplements ADR 0009.

## Problem

Independent re-review of `dec21d05a82f11f4ae46e55a25426bb72feca55f`
reproduced 19 unsafe persisted changes across five P2 findings. Earlier explicit
instructions survived later deferment or repudiation. Unsupported historical or
discussion language defaulted to current authority. Currency-qualified reference
prose still became an amount, and a shared/package price became one unit price.
All six earlier example classes rejected, but their broader authority boundaries
were incomplete. The existing green suite did not establish correctness.

## Decision

The final candidate boundary requires coverage of the complete preparation
message. It accepts supported commands, field-owned text, explicitly scoped
historical facts, named preservation clauses and bounded unrelated conversation.
An unknown statement or operational qualifier requires clarification, including
one that contains no replacement number or text value. Soft continuations are
checked before treating a statement as historical or as a customer prefix. An
earlier valid statement cannot hide a later unresolved statement.

Operational financial phrases use a closed vocabulary after consuming captured
item selectors and numeric expressions. This check establishes coverage only;
the existing typed role, polarity, document, total and conflict checks still prove
the proposed values. An arbitrary prefix or suffix does not become affirmative
because the field/value was recognised. Explicit text payloads remain data;
unconsumed clauses outside captured payloads are checked independently.
Multi-clause text values accept only bounded contact literals/metadata or a
phone-call continuation. A model cannot capture a following financial statement
as contact/work text and also reuse it to change a financial field. Explicitly
labelled contact data and a separate labelled amount remain supported together.

Past/reporting predicates cannot supply current authority. Later negative facts
about a named text field and `stay`/`stays` preservation constrain that field or
item, even without another proposed value. Numbers inside explicitly owned text
payloads cannot authorise financial or VAT changes. The source spans remain
absolute and refer to the original message.

Text field selectors require a direct supported imperative or an explicit fact
connector such as a colon or `is`. A reported command embedded in another
person's narrative is not a direct imperative. Bare missing-field replies cannot
relabel a later sentence as work: supported plain work answers occupy the whole
message and exclude negation, historical predicates, uncertainty and independent
continuations. Explicit `For <customer>: <work>` and comma forms retain their
captured data slots. Ordinary correction forms and explicit current facts remain
positive controls. `Invoice from <year>` is a document reference, not an invoice
command naming a recipient.

Unlabelled amount shorthand requires an empty supported currency/presentation
prefix, a supported correction, or a direct invoice command. A reference sentence
cannot fall through to a unique-currency heuristic. Unit-price evidence requires
the entire selector/price phrase to use supported connectors. Unparsed collective
qualifiers remain ambiguous. A following independently validated total keeps its
own label and does not change the preceding price's role.

The existing atomic worker boundary remains unchanged. Rejection preserves all
notes and the version, records no successful merge action, and sends one
application-owned clarification through the durable outbox. One invalid part of
a mixed proposal rejects the whole candidate. No invoice is issued or sent.

## Verification and limits

The original independent persistence messages and subsequent boundary probes run
through both pure validation and signed ingress with the actual restricted
PostgreSQL role. They include complete-state positive controls and duplicate
processing. Existing assertions are retained. See the
[follow-up validation](../milestones/03-tara-re-review-corrections.md).

This deliberately bounds availability: unsupported wording, unfamiliar operational
qualifiers and unparsed headings can require clarification even when a person
would understand them. Explicit text fields accept literal data; they do not
provide unrestricted natural-language understanding. Rejection of every update
would be a regression, so positive controls remain required.

No RLS, tenant routing, ingress signature, database schema, worker concurrency,
provider implementation, dependency or live integration changes are made. Provider
test preparation is separately described in the
[deadline investigation](../milestones/03-tara-provider-deadline.md). Production
privacy, tax, operational and deployment gates remain open. Another independent
review must assess the new exact commit before merge.
