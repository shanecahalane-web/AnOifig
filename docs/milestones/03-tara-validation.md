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
| New expression/name/privacy unit cases | 148 failed, 55 passed, including seven expectations for the new labelled name display | All 203 pass |
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

## Complete validation

The full suite contains **1,080 tests**: the existing 834 plus 246 new cases.
No existing assertion or scenario was removed or weakened. The existing 57 SDK
tests now exercise the same async serializer/parser component inside the isolated
adapter; 13 additional tests verify the public synchronous process boundary.

| Check | Final local result |
| --- | --- |
| Complete pytest, real PostgreSQL, no skips | **1,080 passed**; exact final local/CI timings recorded in PR #4 |
| Ruff lint / formatting | Passed; 96 Python files formatted |
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

**Production remains blocked** by physical retention/deletion, subject-rights and
vendor/backup workflows, provider/privacy/DPA/transfer and Irish tax review,
realistic extraction evaluation, reviewed model/prices/account spend limits,
operational monitoring/on-call, secrets rotation, abuse controls, staging/load and
backup/restore validation. Uncertain WhatsApp sends require callback/operator
resolution; application send ordering does not guarantee mobile-network arrival
order. See [ADR 0007](../adr/0007-tara-evidence-and-provider-isolation.md), the
[Tara runbook](../runbooks/tara.md) and the
[retention design](../retention-and-deletion.md).
