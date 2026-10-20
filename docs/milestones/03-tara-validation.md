# Milestone 3: final independent-review corrections

Corrections to the review of `5adbfc6094f267c44e2ce7517cba4198a041a135`,
on the existing `codex/milestone-3-tara` branch and PR #4. Validation used Python
3.13.5 and disposable PostgreSQL 17 databases with separate schema-owner and
restricted runtime roles, on 18–19 October 2026. No live OpenAI/Twilio account,
Azure resource, marketing change, invoice issuance or merge was involved.

## Eight findings

| Finding | Correction | Source / regression |
| --- | --- | --- |
| High: financial evidence | Validate original expressions before accepting a numeric substring: currency vocabulary/symbols, signs/accounting notation, precision/grouping, alternatives, uncertainty and numeric role. Unsupported or contradictory expressions preserve saved values and request clarification. | `tara/financial.py`, `tara/schemas.py`; `test_tara_expression_safety.py`, persisted correction tests |
| Medium: line-item correction | Bind selector and changed values to one original item clause and quantity/price role. Reject preservation/negation, ambiguous or repeated descriptions, borrowed prices, historical alternatives and stale versions. Existing lists require selective patches or an explicit whole-list replacement. | `tara/schemas.py`, `tara/financial.py`; expression and PostgreSQL correction tests |
| Medium: VAT polarity | Validate full positive VAT-specific assertions, including shared negation and alternatives. Bare answers still require the matching application-owned pending question. No rate is inferred. | `tara/schemas.py`; expression and persisted VAT tests |
| Medium: false action claims | Bounded single-line customer-name validation; fixed application status statements. A revalidated customer name appears only as separately labelled, quoted data. Invalid legacy labels are omitted. No model prose or other free-text note field becomes a status assertion. | `tara/schemas.py`, `tara/service.py`, prompt v3; name and full persisted outbound tests |
| Medium: duplicate delivery during expiry | Check existing run identity before expiring state. Duplicate processing cannot advance memory/version or reserve again; accepted expiry refreshes activity time. Original completion and genuine stale-result fences remain intact. | `tara/service.py`; sequential/concurrent restricted-role PostgreSQL tests |
| Medium: DNS/provider teardown | Each SDK request runs in a fresh Linux interpreter. Parent deadline contains resolver threads, retries, cancellation and executor shutdown; bounded terminate/kill cleanup and parent-death signalling prevent intentional detached work. Child has no DB/Twilio credentials or completion authority. | `tara/provider*.py`; real HTTPX resolver, cancellation, retry, IPC and parent-death tests |
| Low: superseded contacts | Exclude raw successful structured-edit turns regardless of model intent, including legacy `notes_merged` records. Contact-bearing edits receive audit metadata based on accepted fields. Validated notes carry the current task context. | `tara/service.py`; full-payload correction and legacy-action PostgreSQL tests |
| Low: Irish telephone redaction | Numbering-area/subscriber-length matching covers domestic and +353/00353 formats with common separators. Monetary/date/reference controls protect ordinary numbers. | `tara/privacy.py`; unit and full-provider-payload tests |

Source paths above are under `src/anoifig/`; new unit modules are under
`tests/unit/`. The new PostgreSQL module is
`tests/integration/test_tara_review_corrections.py`.

All six reported merge-blocking defects are corrected within the documented
supported grammar and Linux runtime boundary. This prepares the development PR
for another independent review; it does not establish production readiness.

## Before and after evidence

An untouched `git archive` of the reviewed commit received the same new regression
files. It used a separate disposable database; the reviewed branch was not
rewritten to manufacture failures.

| Evidence | Reviewed commit | Corrected implementation |
| --- | --- | --- |
| New expression/name/privacy unit cases | 169 failed, 58 passed, including seven expectations for the new labelled name display | All 227 pass |
| New signed-ingress PostgreSQL cases | 20 failed, 9 passed; one new clarification-enum case excluded from baseline because the enum did not exist | All 30 pass |
| Actual DNS resolution / executor shutdown, configured 2-second deadline | Default SDK/HTTPX resolver stub sleeps 3.5 seconds; adapter returns after 3.892 seconds, with `dns_started` and `dns_finished` | Isolated adapter returns after 2.008 seconds; `dns_started` recorded, child stopped before `dns_finished` |
| Unsupported currency, word-negative and unresolved amount alternatives | Unsafe updates accepted | Existing amount preserved and one controlled clarification persisted |
| Cropped elbows/valves selector | Wrong item can change | Wrong item rejected; positive elbows patch preserves valves and quantities |
| VAT negation / alternatives | Unsupported rate accepted | Previous rate preserved; affirmative VAT controls pass |
| Customer-name action injection | Injected email/payment claims appear in persisted reply | Invalid name rejected; persisted reply uses controlled application text |
| Dormant memory, duplicate active delivery | State version advances and invalidates original result | Sequential/concurrent duplicates preserve original result and reservation; genuine newer state still wins |
| Corrected contact then greeting | Superseded address/private marker returns in payload | Superseded and current stored contacts absent from complete next payload, including legacy audit actions |
| Irish geographic/international phone formats | Reported values survive provider context | Reported values removed; valid €1,500.25 preserved |

The provider deadline tests use the real HTTP connection/resolver path with a
local blocking resolver stub. They do not perform external DNS or contact a live
API. Additional tests cover a resolver ignoring SIGTERM, SDK Retry-After waits,
transport cancellation resistance, KeyboardInterrupt, worker SIGKILL, malformed
and oversized IPC, fixed command arguments, and proxy/CA environment preservation.

## Complete validation at `2abd32b`

The full suite at that reviewed head contained **1,305 tests**: the existing 834, the first 270
correction cases, and 201 additional cases from the continuation review below.
No existing assertion or scenario was removed or weakened. The existing 57 SDK
tests now exercise the same async serializer/parser component inside the isolated
adapter; 13 additional tests verify the public synchronous process boundary.

| Check | Local result at the reviewed head |
| --- | --- |
| Complete pytest, real PostgreSQL, no skips | **1,305 passed**, no skips, 184.08 seconds |
| Ruff lint / formatting | Passed; 99 Python files formatted |
| Strict Mypy | Passed; 39 source files |
| Bandit | Passed; no findings |
| Frozen dependency sync | Passed; 70 installed packages checked |
| Locked OSV audit | No known vulnerabilities or adverse project statuses in 72 packages |
| Docker runtime build / smoke | Passed: owner migration/runtime grants, API live/ready, UID 10001, mock/local worker, final controlled display and packaged isolated launcher |
| Compose configuration | Passed |
| GitHub Actions | Exact uploaded-commit run and outcome recorded in PR #4's description/checks |

The initial full run exposed three legitimate-name display expectations and a
terminal-punctuation selector regression; both were corrected without weakening
tests. A Docker network change briefly interrupted local PostgreSQL connections;
affected validation was repeated after networking stabilised.
Final adversarial validation also exposed exponential backtracking in overlapping
currency-code alternatives. Atomic lexical matches correct this; an isolated
regression with 800 repetitions completes within its 3-second test bound, while
the preceding correction implementation times out. This safeguard is included
in the final full suite and image.
Scalar amounts, labour and materials also reject either operand of ASCII `x`/`X`
quantity shorthand, including when only the second operand carries a currency.
This prevents `3x25` becoming a €3 charge without removing the existing low-level
quantity-token behaviour. Twelve full-message cases cover all three scalar fields.
Foreign currency names are checked across the original message, so intervening
country qualifiers such as `500 New Zealand dollars` cannot conceal the currency.
Ambiguous currency words that could also be names or units can require clearer,
separate input; the application preserves the saved notes instead of guessing.
GitHub run 13 exposed a pre-existing fairness-test clock assumption: four fast
parallel batches could finish before one-second contention cooldowns elapsed,
yielding 35 rather than 101 sends at its intermediate assertion. The test now
advances only tokenless, non-null polling cooldowns after both workers join,
using `FOR UPDATE SKIP LOCKED` to preserve its held metadata lock. Active leases,
receipts, source retry times, ordering and delivery state remain unchanged. All
original four-batch, 101/202-send, duplication and RLS assertions remain; separate
tests still verify real cooldown exclusion and expired-receipt fencing. Three
focused repetitions and the complete suite verify the test-clock correction.

Existing migration tests retain 0005→0006→0005→0006 value comparisons, legacy NULL
compatibility, RLS, owners/ACLs, constraints and metadata checks. Existing recovery,
lost-commit acknowledgement, queue/outbox/deduplication, uncertain-send ordering,
multi-tenant and raw restricted-role isolation tests remain part of the full suite.

Reproduce against dedicated disposable test databases:

```sh
uv sync --frozen
uv run --frozen pytest -ra
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy src
uv run --frozen bandit -r src -q
uv audit --locked
```

## Continuation review, 19 October 2026

The continuation began at `fb8db2b77df68d72c34b5003931edcbac461e22c`.
Its existing GitHub Actions run 16 was independently checked: all 1,104 tests,
lint, formatting, Mypy, Bandit and locked audit passed. Further adversarial checks
found adjacent gaps in the supported grammar and stale-state metadata boundary;
the earlier passing result alone did not establish that every variation was safe.
An untouched archive of that head ran the final new test files with the archived
source path verified: 117 unit failures / 43 passes and 37 PostgreSQL failures.
Implementation files in the archive were unchanged.
The before run used the same locked dependencies and separate disposable
`baseline_review_test` database. The unit run selected the two new unit modules;
the PostgreSQL run selected the new follow-up integration module. `PYTHONPATH`
selected the archive's `src` directory and an assertion verified the imported
schema module came from that directory before invoking pytest.

- Foreign currency annotations separated from their amount by a preposition,
  parentheses or field label could be ignored. Validation now checks original-input
  foreign symbols and explicit ISO codes, including case-insensitive qualified
  syntax. Ordinary lower-case words sharing ISO codes retain positive controls.
- Financial/VAT questions, rejected assertions and contracted negatives could
  become saved facts. Shared original-sentence checks retain comma/conjunction
  continuations and reject interrogative heads and negative assessments. The same
  guard protects scalar charges and item values. Positive VAT assertions, unrelated
  sentences and work descriptions such as a wrong valve remain supported.
  Application code still owns all rules.
- Rejecting a stale completion preserved newer notes/version but cleared its
  pending VAT clarification and refreshed activity. Finishing that old run now
  leaves the entire newer state intact and preserves the usage reservation.
- Non-breaking and narrow non-breaking spaces could conceal Irish/international
  phones in provider context. Shared horizontal separators now handle these while
  preserving monetary values, dates and numeric reference controls.

| Additional regression evidence | Before correction | After correction |
| --- | --- | --- |
| 127 full-message financial/VAT unit cases, including positive controls | 102 failures / 25 passes against `fb8db2b` | All 127 pass |
| 33 Unicode phone-spacing and numeric-control unit cases | 15 failures / 18 passes against `fb8db2b` | All 33 pass |
| 37 restricted-role PostgreSQL correction/stale-state cases | All 37 fail against `fb8db2b` | All 37 pass |
| Full subsequent provider payload with phone spacing and preserved money | Four extra variants extend the existing payload scenario | All 8 variants pass |

The new modules are `test_tara_followup_financial.py`,
`test_tara_phone_spacing.py` and `test_tara_followup_corrections.py` under the
existing unit/integration test directories. The existing full-payload phone test
adds four parameters; no original test or assertion was removed or weakened.
The focused financial/name suite passed 520 cases; all 70
provider/component/isolation tests passed.
The final service boundary run passed 85 restricted-role PostgreSQL cases
(37 new and 48 existing review/state cases) in 60.78 seconds.
No further correction was needed to the existing item selector, response authority,
duplicate-expiry identity check, superseded-contact minimisation or isolated
provider lifecycle. Their original regressions remain in the complete suite.

One initial provider retry test reached its two-second deadline while importing
the child SDK under concurrent load, before its mocked request event. The isolated
rerun and complete 70-case provider rerun passed; the deadline remained enforced.
The first complete continuation run found one compatibility regression: the valid
`No VAT, not registered.` scenario was rejected (1 failed / 1,303 passed in
196.27s). A narrow affirmative-registration exception and positive regression
restore it while related questions/rejections still fail closed. The unchanged
end-to-end scenario passed afterward; the full final suite was rerun. No test was
weakened. Docker setup also needed a readable copy of the
unchanged init script because this workspace materialises it with mode 0700.
The final runtime image built after the shared assertion fix was
`sha256:daa5bb0de4b6527608564e062761f010f26e20e972cde91b00cf63f10804b3ca`.
Its smoke verified owner migrations/grants, restricted-role checks, UID 10001,
API live/ready, one real mock/local worker turn and controlled outbound, missing
context RLS, and the packaged isolated launcher. In-image hashes of all four
changed source files matched the frozen tree. BuildKit supplied the approved
complete CA bundle as a secret; TLS and proxy trust remained enabled.

## Three remaining financial merge blockers, 20 October 2026

The independent review of `2abd32bdd6e209d94d0d0ab544e5b81c7a4b053a`
reproduced three P2 defects through signed WhatsApp ingress and restricted-role
PostgreSQL: line totals could become unit prices, another item's bare price could
be borrowed, and a numeric VAT rate could hide a textual exemption alternative.
The following focused corrections address those persisted preparation-note defects.

| Original input / proposal | Reviewed implementation | Corrected implementation |
| --- | --- | --- |
| `3 valves for a total price of €75`; quantity `3`, unit price `75` | Saves an implied €225 line | Rejects; prior notes survive; controlled clarification question |
| Existing valves `3 × €25`; `Make valves total price €75`, proposed unit price `75` | Replaces €25 with €75 | Rejects; quantity, €25 price, other items and VAT survive |
| `3 valves at €25 with elbows at 10`; proposed valves unit price `10` | Borrows the elbows price | Rejects, including bare/mixed-currency-marker and conjunction variations |
| Existing VAT `exclusive / 13.5`; `VAT 23% or VAT exempt`, proposed rate `23` | Replaces 13.5 with 23 | Preserves both VAT fields and asks the controlled question |
| One bound item, quantity `3`, total `75`, proposed unit price `25` | Rejects a derived price | Validates exact Decimal product `3 × 25 = 75`; never divides/rounds |
| Quantity `3`, total `100`, proposed unit price `33.33` or `33.34` | Unsupported | Rejects both; no silently rounded quotient |

Token-specific item roles distinguish quantity, unit price and monetary total.
Generic price/cost/at markers cannot override total/subtotal/overall semantics;
deposits do not establish a whole-item total. Explicit each/apiece/per-unit prices
must agree with a separate stated line total. Final product validation also applies
to quantity-only patches, using the final quantity and unchanged price. Derived
corrections use the captured, version-bound quantity; source quantities cannot
contradict it. Unsupported precision cannot disappear from the numeric candidates.

Item-only connector boundaries keep bare prices with their own description.
All relevant price markers participate in ambiguity checks. Repeated original
clauses for the same selected item clarify, even if model evidence crops out the
other clause. A bounded numeric-list regression protects ingress-sized repeated
prices; independent 500/800-repetition probes rejected in approximately 0.05/0.12s.
The existing positive `a total of 3 valves at €25 each` remains supported: its
count-total phrase is distinct from a monetary line total.

VAT guards retain exempt/exemption, zero-rated and no-VAT alternatives across
or/vs/slash, choice syntax and formatted continuations. Independent probing added
the `VAT 23% or` + newline + `VAT exempt` case before final verification. Historical
replacement comparisons using instead-of/rather-than require a clear restatement.
An affirmative zero-percent rate remains a rate; no exemption/zero-rating mapping
or Irish tax rule is introduced. Prompt version `tara-2026-10-20-v4` describes the
same evidence boundary. Rejection text is an application-owned question, with no
successful-update acknowledgement.

### Before/after evidence and regression coverage

Tests were written before source corrections. The first combined run on pristine
`2abd32b` produced **116 failures / 63 passes**. The final three added modules
contain **294 cases**: 86 item-evidence unit cases, 148 VAT unit cases and 60 signed
ingress/PostgreSQL cases. The tests-only commit
`fa2cb9f7f47a077564ffbbd4859dfb5e7963031e` retains the reviewed implementation and
the final regression files, so the before result is reproducible independently.

A fresh untouched archive of `2abd32b` received only those three final test files.
All four implementation files were compared byte-for-byte with the reviewed Git
objects, and the imported schema path was asserted to be the archive's source.
Using a separate disposable `baseline_fixes_test` database, the final before run
produced **215 failures / 79 passes in 47.37s**. These failures include unsafe
acceptance, the newly allowed exact-product positive cases, stricter clause checks
and the required clarification-question behaviour; they are not a claim of 192
distinct defects. No reviewed implementation file or existing assertion was edited
to manufacture the before result.

The added modules are:

- `tests/unit/test_tara_item_evidence.py`
- `tests/unit/test_tara_vat_alternatives.py`
- `tests/integration/test_tara_merge_blockers.py`

Run the same focused comparison on the tests-only commit and corrected head:

```sh
uv sync --frozen
# Configure separate owner/runtime connections to a dedicated disposable *_test DB.
uv run --frozen pytest -ra tests/unit/test_tara_item_evidence.py \
  tests/unit/test_tara_vat_alternatives.py tests/integration/test_tara_merge_blockers.py
```

The integration assertions cover acceptance/rejection, complete persisted notes,
exact item quantities/prices and VAT fields, unchanged version on rejection, one
controlled reply, safe run action/error metadata, and absence of a successful
update acknowledgement. Positive controls preserve unrelated items/fields. All
original **1,305** tests remain; the complete corrected suite contains **1,599**.
Final full-suite and CI outcomes are recorded below and in PR #4.

| Final correction check | Result |
| --- | --- |
| Complete Python 3.13.5 suite, PostgreSQL 17, separate owner/runtime roles | **1,599 passed**, no skips, 198.95s |
| Frozen dependency sync | Passed; 70 installed packages checked |
| Ruff lint / formatting | Passed; 102 Python files formatted |
| Strict Mypy | Passed; 39 source files |
| Bandit | Passed; no findings |
| Locked OSV audit | No known vulnerabilities or adverse statuses in 72 packages |
| Final runtime Docker build/smoke and source hashes | Passed; details below |
| GitHub Actions | Exact published-head run and confirmation recorded in PR #4 |

The initial complete correction run exposed one compatibility regression in the
unchanged `quantities_unit_prices` scenario: a nonnumeric work-description mention
(`supply valves`) competed with the later numeric item assertion. That run ended
with 1 failed / 1,571 passed. The clause rule now counts numeric assertions while
retaining malformed numeric evidence; nonnumeric mentions do not create competing
prices. A new positive unit case first reproduced the regression, and the original
scenario/assertions remain unchanged. The complete suite and final Docker smoke
were rerun after this focused correction.
Final independent probing also added same-sentence comma/and conflicts between
numeric rates and exemption/zero-rating/no-VAT statements. Those 26 additional
checks include both proposal directions and persisted clarification controls.
Compatible numeric-rate plus inclusive/exclusive basis assertions remain valid.
The in-progress continuation run was stopped to include this guard, then the full
final suite was restarted.

The final runtime image is
`sha256:7c9ea46b3e63e4046735fec9cff750045bc0844e3b601cccb99a87e637678011`.
Its Docker smoke passed fresh migrations/grants, actual API liveness/readiness,
UID 10001, raw restricted-role RLS, signed ingress with a real mock/local worker
and outbox, the original three rejected corrections plus affirmative VAT, and the
packaged isolated launcher with offline invalid input. In-image hashes of all
four changed source files matched the frozen source. The unchanged Dockerfile
received the approved combined CA bundle as a BuildKit secret; TLS stayed enabled.
The external TestClient smoke emitted a dependency deprecation warning because
httpx2 is a development-only dependency; all assertions passed and no runtime
dependency change was required.

No migration, dependency, RLS/grant, messaging lifecycle or provider-process change
is introduced. General financial prose, ambiguous totals/selectors and historical
treatment comparisons can still require a clear restatement. The new exact-product
exception does not enable general arithmetic or tax calculations. Production gates
remain separate.

## Operational changes and limitations

No dependency, database migration, grant or RLS change is introduced by these
corrections. Migration 0006 and its rollback behaviour remain unchanged. Never
downgrade 0005 to reset usage: it deletes Tara notes/audit/budgets. Prefer forward
fixes; pause workers/API and verify grants for separately approved migrations.

OpenAI mode now requires Linux with `prctl` parent-death signalling and `memfd`.
The fixed child receives only minimal JSON request/configuration through private
stdin; proxy/CA settings survive, TLS stays enabled, DB/Twilio secrets do not.
Output uses bounded validated JSON over anonymous memory. Default deadline is
60 seconds, maximum 90, followed by at most 0.25 seconds each for terminate and
kill/reap under normal host scheduling, below the 120-second run fence.
Acknowledgement/mock development modes remain available without live accounts.

Kernel/process-creation failure, uninterruptible tasks or host starvation prevent
an absolute hard-real-time guarantee. Staging must validate host supervision and
resource/failure behaviour. Cancellation cannot undo a remotely accepted request
or guarantee zero spending. Conservative reservations remain charged; retries stay
bounded, and late results cannot commit after durable completion/version fences.

The financial grammar deliberately asks for a clear single value for unsupported
grouping, arithmetic, historical from/to expressions or ambiguous item selection.
It cannot prove every semantic interpretation of arbitrary prose. VAT checks do
not establish tax compliance. Current user input and unrecognised sensitive free
text may still reach the provider: pattern minimisation is not universal PII
detection, physical erasure or a retention policy.
Phone patterns retain ambiguous-boundary limits: a phone immediately followed by
another unlabelled numeric phrase can remain unredacted or consume that phrase.
Unicode-spacing support does not resolve arbitrary numeric ambiguity.

**Production remains blocked** by physical retention/deletion, subject-rights and
vendor/backup workflows, provider/privacy/DPA/transfer and Irish tax review,
realistic extraction evaluation, reviewed model/prices/account spend limits,
operational monitoring/on-call, secrets rotation, abuse controls, staging/load and
backup/restore validation. Uncertain WhatsApp sends require callback/operator
resolution; application send ordering does not guarantee mobile-network arrival
order. See [ADR 0007](../adr/0007-tara-evidence-and-provider-isolation.md), the
[Tara runbook](../runbooks/tara.md) and the
[retention design](../retention-and-deletion.md).
