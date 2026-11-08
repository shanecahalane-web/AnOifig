# ADR 0009: Field authority and complete-message mutation constraints

Status: proposed for Milestone 3 independent re-review.

The subsequent review of `dec21d05` found five remaining P2 authority defects.
[ADR 0010](0010-tara-complete-statement-authority.md) records the follow-up
correction; the original verification below describes the earlier implementation.

## Problem

Independent review of `daded2df3e3e0cc2004d1e4aa385955e368d5a76`
confirmed six P2 defects. A unique non-financial number could acquire a charge
role; unrecognised collective totals fell back to a selected line; formatting
could hide a VAT question; historical scope could hide a current instruction;
non-numeric cancellation clauses did not constrain changes; and text changes
required only substring grounding.

These failures share an authority gap. Finding a literal in the message, or
failing to recognise a wider scope, does not establish permission to change a
particular field. The correction remains inside Tara's existing preparation-note
boundary. It adds no invoice operation, migration, grant, provider or queue design.

## Decision

Preserve unchanged source text and offsets in typed assertions. Presentation is
an inspection view, so WhatsApp emphasis, Markdown headings, blockquotes and lists
cannot detach facts from question/option headings. Intent and document scope stay
independent. Explicit temporal/current clauses participate in current-fact
conflict checks. Instructions quoted or reported inside an old-document clause
retain historical scope; unsupported transitions clarify rather than disappear.

Financial evidence must establish its role. Address/reference/count/duration
syntax cannot become money, including with a currency annotation. An explicit
labour/material component retains its own role through amount/price/total labels.
Unlabelled supported monetary shorthand can establish an amount, not another
component. Unsupported rate denominators do not establish whole charges.

Line totals require affirmative selected-item binding. Collective and combined
totals retain wider scope, including postfix targets. Unresolved targets remain
ambiguous. Literal prices and exact Decimal-product validation consume the same
scope. No division, rounding or allocation is added; supported explicit units,
line totals and item-bound overall prices remain available.

`TextAssertion` retains the field, source value and assertion context. Customer,
work and contact changes require affirmative current-document evidence for their
own field. Supported implicit Invoice/For/name-correction forms participate in
the same conflict checks as explicit labels. Field labels own their payload:
words such as `customer` or `name` inside a company, address or work description
do not create additional selectors. Application-owned missing-field answers remain
bounded by the captured notes; arbitrary text cannot supply a different field.

`MutationTarget` binds proposed fields to captured item aliases.
`MutationConstraint` retains cancellation/preservation clauses even when they
contain no new number. A named field or item constrains its own mutations; an
unresolved or document-wide veto constrains the entire proposal. An instruction
to keep a different item unchanged remains compatible with a selected-item
correction. Renames retain old/new selectors. Field-owned text remains data;
independent cancellation clauses are still checked.
Application-owned targets also retain whether their field applies to all items:
preserving one item's VAT therefore constrains the shared invoice VAT fields.

Every proposal still constructs a local candidate and passes the existing single
final-state boundary before persistence. The boundary now checks mutation
constraints as well as complete financial/VAT evidence. Initial lists,
replacements, quantity/price/description patches and scalar/text changes share
this path. One unsupported change rejects the entire candidate. The worker's
existing transaction persists notes/version/action/reply only after validation;
its controlled rejection path remains authoritative.

## Verification and limits

Tests-first signed-ingress regressions compare complete notes, versions, actions,
one controlled clarification, outbox uniqueness and duplicate behaviour under the
actual restricted PostgreSQL role. Positive controls retain financial shorthand,
component labels, exact item products, customer names/contact payloads and
preservation of another item. Supplemental adversarial cases run against a
byte-verified pristine archive of the reviewed source before correction.

The separate two-second DNS test issue was a test-harness fault-stage dependency,
not a confirmed production deadline defect. The test-only correction preserves
the deadline and every original assertion, isolates real SDK/HTTPX DNS from
unrelated strict-schema setup, and separately checks startup stalls. See the
[provider investigation](../milestones/03-tara-provider-deadline.md).

This remains a bounded language grammar, not complete semantic extraction or tax
validation. Unsupported interpretations require clarification. Production
retention, privacy/vendor, tax, operational, staging and load gates in ADRs
0006–0008 remain open. Readiness here means ready for independent development
re-review; it does not authorise a merge or deployment.
