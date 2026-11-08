# ADR 0008: Source assertions and one final preparation-note boundary

Status: proposed for Milestone 3 independent review, 22 October 2026.

## Problem

Review of `97d5a24` reproduced three P2 defects. An unrecognised collective
target, such as `all the items`, fell back to a line total. A bullet between a
VAT question and its proposed answer lost question intent. An old-document
reference suppressed a later explicit current-document contradiction. Invoice
consistency also ran only for replacements and numeric item patches.

The previous classes retained numeric roles and some scope, but separate context
checks reconstructed meaning from different substrings. The correction retains
the existing numeric and treatment recognisers and gives them shared source
context. It does not add a general language parser, dependency or service.

## Decision

`assertions.py` is a pure leaf module. `AssertionContext` retains an expression's
unchanged source text, absolute expression/clause offsets, associated heading,
statement intent and document scope. Intent distinguishes affirmative, question,
option, negated, conditional and ambiguous statements. Document scope separately
distinguishes current, historical and ambiguous references; a historical question
does not become an affirmative current instruction.

Presentation markers are inspected through offset-preserving views. Newlines,
semicolons, blank lines, indentation and numeric/letter/bullet markers cannot
detach an answer from its question or option heading. An independent affirmative
instruction for the current document can end that heading. This is not a
last-statement-wins rule: all affirmative current facts still participate in
conflict checks. Unrelated prose cannot reset a VAT heading.

The nearest applicable explicit document reference owns each assertion. An
`old invoice` reference can carry through its continuation, but `this invoice`,
`current invoice`, `new invoice` or `invoice being prepared` restores current
scope for the following assertion. Historical negation cannot suppress a clear
current instruction. Unsupported replacement/conditional prose still clarifies.

`FinancialEvidence` retains Decimal value, financial role, unit/line/invoice/
partial/ambiguous scope, item identity where applicable, full source expression
and assertion context. Collective targets compose quantifier, optional `of`,
determiner and `line items`/`items`/`lines`; selected-item proximity cannot narrow
their scope. Unsupported aggregate scope remains ambiguous. Literal prices,
quantities and exact line-product evidence consume this same classification.
An explicitly item-bound overall price remains a supported line total.

`VatAssertion` retains treatment kind and numeric rate alongside shared context.
Only affirmative current evidence can establish a VAT field. Historical facts
remain available as historical facts. Exemption, zero rating, no VAT, numeric
zero percent and inclusive/exclusive pricing remain distinct; no tax treatment
or Irish tax rule is inferred.

After grounding individual changes and constructing the candidate `InvoiceNotes`,
`apply_proposal` always calls `_validate_final_state`. The same boundary validates
initial items, replacements, selective quantity/price/description patches, scalar
amounts, VAT changes, text changes and empty proposals. It checks complete source
evidence and the complete result, rather than trusting selected excerpts or the
proposal mechanism. Selective renames retain their captured old/new item identity.

The final financial validator checks current known-item facts and current invoice
totals. An item sum is provable only with no VAT and no overlapping scalar charges.
A matching scalar aggregate cannot hide inconsistent detailed items. With no
items, a literal current aggregate can establish the scalar amount. No adjustment
is allocated; no residual price is divided, rounded or inferred. Current VAT
conflicts also invalidate the proposal through this final boundary.

With no related current aggregate evidence, pre-existing overlapping scalar
charges or incomplete notes are preserved. The boundary checks safety of a
proposed result; it does not prove complete extraction of arbitrary prose.

The worker persists notes/version, run metadata and one reply only after this
boundary succeeds. A rejection retains notes and version, records no merged
action and uses the existing controlled clarification. Explicit application-owned
reset/expiry commands remain separate conversation controls, not model mutation
paths. No schema, migration, RLS/grant, provider or queue change is required.

## Verification and limits

Tests-first behavioural regressions cover all three exact failures, source
formatting and document transitions, every structured mutation path, positive
controls, complete persisted results and raw tenant isolation. Direct context
tests verify the new typed source/intent/document contract separately. Original
regression assertions remain intact. See the [validation report](../milestones/03-tara-validation.md).

The supported grammar is deliberately bounded. Unsupported wording, grouping,
arithmetic, allocation, uncertain scope and unresolved current choices require
clarification. This change does not establish tax compliance or commercial
production readiness. Staging/provider/load and production privacy, retention,
tax and operational requirements in ADRs 0006/0007 remain separate.
