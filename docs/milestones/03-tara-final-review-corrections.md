# Milestone 3 correction of the four remaining authority defects

Status: prepared for independent re-review; no merge or deployment approval.
The final correction commit and this report are linked from PR #4. The rejected
review baseline is `bd24d528f248e44e1e96c3ae1189a155df341b7a`.

## Review evidence and scope

The independent review confirmed four P2 defects and 27 unsafe persisted
proposals. The original 19 failures from the earlier review were fixed in their
original forms, but these new cases still saved incorrect preparation notes and
sent a success acknowledgement. Scripted adversarial model proposals exercise
the application's trust boundary; no live model or messaging provider is used.

All 27 reviewed messages, modes, proposed values, item selections and evidence
are retained as the first 27 cases in
[`tara_final_review.json`](../../tests/scenarios/tara_final_review.json).
Tests-first replay against unchanged baseline source reproduced **54 failures**:
27 pure-validator failures and the same 27 signed-ingress PostgreSQL failures.
The replay selected those exact cases; the other 120 new checks were deselected.

Production changes are limited to `assertions.py`, `financial.py` and `schemas.py`.
There are no changes to providers, deadlines, worker transactions, tenant routing,
RLS, migrations, dependency versions, privacy filtering or invoice capabilities.
Existing tests and fixtures are unchanged; three new test/scenario files are added.

## Corrections

| Finding | Correction | Original persistence cases |
| --- | --- | ---: |
| Later repudiation or historical qualification was ignored | Recognize references to an earlier assertion before accepting a statement as text data or discarding it as history. A repudiation such as `That is wrong` or a qualification such as `That is for the previous job` invalidates the complete candidate. Explicit independent historical facts remain usable alongside current instructions. | 12 |
| Historical context hid a cancellation | A direct cancellation in its own clause remains a veto even when its inherited context refers to an old invoice. A cancellation explicitly reported within a historical clause retains that local historical scope. | 6 |
| Invoice-status reporting became monetary authority | Inspect reporting predicates and temporal markers throughout the recipient portion of the invoice phrase, including predicates preceded by adverbs. Reject reference/status prefixes before scalar role classification, covering labelled amounts and the unlabelled command fallback. Preserve explicit current-document facts and ordinary invoice commands. | 5 |
| Description patches bypassed assertion authority | Require a complete supported rename command identifying the existing item and the proposed description. Validate the proposed value's original absolute span with the shared affirmative/current-document assertion checks and reject unresolved alternative descriptions. Substring presence alone no longer authorizes a rename. | 4 |

Changed validation locations:

- [`assertions.py`](../../src/anoifig/tara/assertions.py):
  `validate_statement_coverage`, `mutation_constraints`, `invoice_command_prefix`
  and the new `item_description_evidence` helper.
- [`financial.py`](../../src/anoifig/tara/financial.py):
  `_scalar_number_evidence` checks the invoice prefix before classifying an amount.
- [`schemas.py`](../../src/anoifig/tara/schemas.py): `_patch_line_items` applies the
  shared authority helper to description changes before modifying the candidate.

The supported rename forms are `Rename <item> to <description>` and
`Change/Set/Update <item> description to <description>` or
`Change/Set/Update description of <item> to <description>`, with the bounded polite
and correction prefixes implemented by the validator. Questions, historical
reports/headings, conditions, options, negation and later repudiations cannot
supply rename authority. One invalid rename in a mixed proposal rejects the
entire candidate, including otherwise valid scalar changes.

The existing final-state boundary still validates the complete original message
before the worker assigns notes or increments the version. No new persistence
path is introduced. Rejection preserves complete notes and version, records no
successful merge action, and uses the existing application-owned clarification.

## Regression coverage

**95 scenarios** run through both pure validation and signed-ingress persistence:
**70 rejection cases and 25 positive controls**, for **190 new checks**.
The original 27 cases retain their original evidence; supplemental cases cover
full-message evidence, named and deictic qualifications, comma/conjunction/heading
cancellations, reporting modifiers, labelled reported amounts, question and
historical renames, conflicting rename targets and mixed valid/invalid proposals.

Positive controls compare complete expected notes. They cover ordinary invoice
commands, numbered addresses, confirmations, explicit current VAT, independently
scoped historical facts, reported historical cancellations, direct renames and
preserving another item. All prior positive controls remain unchanged, including
`repairs to the wrong valve` and `the invoice being prepared`.

The persistence tests use the existing signed Twilio ingress, worker and actual
restricted PostgreSQL runtime role. Rejection assertions require:

- The complete saved notes and version are unchanged.
- The completed run has no merge action and reports `invalid_model_response`.
- Exactly one application-owned clarification reply and one outbox row exist,
  without a false success acknowledgement.
- Duplicate processing adds no model call or second reply and leaves the notes
  and version unchanged.

Successful controls verify the complete expected notes, one version increment,
the expected merge action, controlled acknowledgement and idempotent replay.

## Validation evidence

Validation on 8 November 2026 uses Python 3.13.5, the unchanged frozen lockfile,
PostgreSQL 17 in a disposable local container, and separate owner/runtime roles.
The runtime role is non-owner, non-superuser and NOBYPASSRLS, with the repository's
restricted database/schema/table grants.

| Check | Result |
| --- | --- |
| Tests-first replay of the original 27 cases on `bd24d528` | **54 failed**, 120 deselected, in **31.72s**, as expected before correction |
| Complete unfiltered suite, including all PostgreSQL integration tests | **3,038 passed**, no skips or failures, in **985.52s** |
| PostgreSQL integration collection | **997 tests**, included in the full-suite command |
| Ruff lint | Passed |
| Ruff formatting | Passed |
| Strict Mypy | Passed; **40 source files** |
| Bandit | Passed; no findings |
| Locked dependency audit | Passed; **72 audited packages**, no known vulnerabilities or adverse project statuses |
| Existing test integrity | No existing test or fixture file modified or removed |

After the complete run, all 110 recorded source, test, scenario and lockfile
hashes matched the tested candidate. Only this report was updated with the final
results afterward.

Commands, from the repository root with the two test database URLs configured:

```sh
uv sync --frozen
uv run --frozen pytest -q
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy src
uv run --frozen bandit -r src -q
uv audit --locked
```

Run the correction cases independently with:

```sh
uv run --frozen pytest -q tests/unit/test_tara_final_review.py \
  tests/integration/test_tara_final_review_persistence.py
```

`ANOIFIG_TEST_ADMIN_DATABASE_URL` and `ANOIFIG_TEST_DATABASE_URL` must identify the
same dedicated disposable database ending `_test`, using distinct schema-owner
and restricted runtime users. Never run these fixtures against customer data.
The tests apply migrations and truncate synthetic fixture data.

## Disclosed intermediate results and remaining limits

An initial patch rejected three existing positive cases (two phrases involving
`the wrong valve`, and `the invoice being prepared`). Expanded new tests also
caught two reporting-modifier bypasses and one unsupported legitimate rename
form. The production checks were corrected; existing assertions were not changed.
A subsequent boundary probe exposed three variants referring to labour,
materials and a named item price. The same referential-qualification check was
extended to component fields, quantities and captured item names, with eight
additional negative/positive scenarios. The then-running full suite was
intentionally interrupted after 298 passes in 238.10 seconds; that partial run
is not counted as final validation.
Before the workspace interruption, all 87 new persistence scenarios and all 1,639
core Tara unit tests passed. Those focused runs do not substitute for the final
unfiltered suite above. The interrupted full-suite run had no retained completion
result, and its temporary logs were lost during the workspace restart; it is not
counted as passing evidence. The initial dependency-audit attempt was not executed
because automatic approval review reached a usage limit. The resumed audit passed.

The parser supports a bounded instruction grammar. Unsupported or ambiguous
wording may require clarification; this does not establish general language
understanding or tax correctness. Production retention/erasure, vendor/privacy,
tax, operational and staging/load gates remain unchanged. No invoice is issued,
no live provider is connected, and nothing is merged or deployed. Independent
review of the final exact commit is still required.
