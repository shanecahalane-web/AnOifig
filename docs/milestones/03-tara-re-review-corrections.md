# Milestone 3 follow-up to independent re-review

Status: correction prepared for independent review of the final PR head; see the
exact-head CI status in PR #4 before treating validation as complete.
This is a correction report, not independent merge approval. PR #4 remains unmerged.

## Review baseline and reproduced defects

The reviewed baseline was `dec21d05a82f11f4ae46e55a25426bb72feca55f`.
Its six original example classes rejected correctly, but independent signed-ingress
experiments still persisted 19 unsafe proposals across five P2 findings. Tests-first
replay of the original 57 review cases on unchanged source produced **19 failed /
38 passed**. A passing existing suite was not used as evidence against these cases.

| Finding | Final boundary and regression evidence |
|---|---|
| Later withdrawal/deferment ignored | Complete statement/continuation coverage rejects unresolved operational qualifiers, including those without another number. Cancellation and named preservation still constrain the complete candidate. |
| Later denial of customer/work/contact ignored | Negative field facts constrain their targets. Text requires a direct supported imperative or explicit fact connector; reported commands and later unlabelled sentences cannot become field authority. |
| Historical/discussion language defaulted to current | Unknown statements/headings clarify. Past/reporting predicates do not supply current authority. Explicit current facts remain usable alongside independently scoped history. |
| Currency-qualified reference became an amount | Unique-currency fallback now needs supported shorthand/correction/invoice-command syntax. Reference/date prefixes cannot be recipients, and text-owned numbers cannot authorise financial fields. |
| Shared/package price became one unit price | The full selector/price phrase must use supported connectors. Unknown aggregate qualifiers remain ambiguous; exact selected-line totals and preservation of another item remain supported. |

The six earlier blockers remain covered: non-financial numeric roles, aggregate
scope, formatted VAT questions, historical/current VAT conflicts, cancellation
and preservation, and negated/historical text. This follow-up adds **131 cases**
to both pure validation and signed PostgreSQL persistence: **115 rejection cases
and 16 positive controls**. These include all 57 independent review cases, all 19
unsafe persistence cases, the independent text probes and additional combinations.
Additional probes cover captured text continuing across a semicolon into a
financial statement, and a valid contact-plus-labelled-amount control.
Counts overlap by defect class and are not counts of distinct defects.

Each persistence rejection compares the complete saved notes and unchanged
version, checks a completed run with no successful merge action and an exact
application-owned clarification, checks one reply/outbox and duplicate safety,
and excludes a false success acknowledgement. Positives compare complete expected
notes, the single version increment, merge action, controlled acknowledgement and
idempotent replay. Unrelated fields/items remain intact.

## Implementation and boundaries

See [ADR 0010](../adr/0010-tara-complete-statement-authority.md),
`src/anoifig/tara/assertions.py`, `financial.py` and `schemas.py`.
The existing service still performs the only persistent merge after validation,
reauthorisation and the conversation/version/concurrency fences. No migration,
RLS grant, tenant routing, signed-ingress, worker persistence, production provider,
dependency or response-template change is introduced.

The language is deliberately bounded. Unrecognised operational wording can
require clarification. Literal text data needs a supported field/data frame;
plain missing-work answers have a narrower whole-message form. Multi-clause text
values permit only bounded contact literals/metadata or a phone-call continuation;
a financial instruction cannot simultaneously become part of a text value. The correction
retains ordinary amount corrections, invoice recipient/work data, current VAT,
exact item products and scoped preservation. It does not promise arbitrary-prose
understanding, tax correctness or invoice issuance.

## Provider and packaging reliability

[The provider investigation](03-tara-provider-deadline.md) documents the fault-stage
preparation change. Original two-second safety thresholds, kill/reap/no-late-event
assertions and cold-start containment controls remain. Prepared transport tests
use the complete real strict SDK completion; two new controls prove preparation
makes no request and that full cold transport still succeeds with a separate
realistic positive-control budget. Production provider code/deadlines are unchanged.

An AST/multiset comparison retained all **1,384 pre-existing assertions**. Fixture
code in the provider assertion modules and shared ingress helper changed; those files are not claimed to be
byte-identical. No tests were deleted or skipped to obtain a pass.

A deterministic PostgreSQL test also reproduced a shared ingress-helper race:
an older outbound job becoming discoverable between the helper's two queries
was returned as if it were the newly accepted inbound message. The helper now
requires exactly one new **inbound** job. The new regression failed before this
fixture-only change; the production queue and ingress paths are unchanged. This
is separate from the 131 paired authority cases.

Build inspection also found host `__pycache__` artifacts in the earlier images.
Recursive Docker exclusions now remove source/test bytecode from the build context.
Final image checks verify clean source/test imports, source/lock hashes and runtime
behaviour. This is packaging hygiene; no claim is made that stale bytecode caused
an earlier intermittent test failure.

## Final validation

Validation used Python 3.13.5 on the host and Python 3.13.18 in Docker, with
disposable PostgreSQL 17 databases. Final local results recorded on 6 November 2026:

| Check | Result |
|---|---|
| Unfiltered complete pytest suite | **2,848 passed**, no skips, in 994.13 seconds |
| Packaged PostgreSQL integration selection | **239 passed** in 258.93 seconds |
| Packaged offline provider selection, DNS first | **76 passed** in 49.21 seconds, with `--network none` |
| Ruff lint / formatting | Passed; 124 files formatted |
| Strict Mypy | Passed; 40 source files |
| Bandit | Passed; no findings |
| Frozen sync / locked dependency audit | Passed; 72 audited packages, no known vulnerabilities or adverse statuses |
| Runtime/development Docker builds | Passed with verified TLS and mounted CA trust |
| Runtime smoke | UID 10001; live/ready HTTP 200; invalid launcher rejected with no output; all 41 source/lock hashes matched |
| Existing assertion integrity | All 1,384 retained; none removed or modified |

The 2,848 cases comprise the previous 2,583 plus 262 paired authority cases,
two provider controls and one deterministic ingress-helper regression. The
provider selection explicitly places the DNS case first and also collects its
module; its pass count describes that selection, not additional distinct cases.


The complete host run used the unfiltered `uv run --frozen pytest -q` command. PostgreSQL
runs used dedicated disposable databases and separate owner/runtime roles. Docker
integration used a separate disposable database; provider tests used no network.
The CI result and exact final head SHA are recorded in PR #4, avoiding a
self-referential commit SHA in this file. CI checkout tree/head identity must be
checked before merge.

The final packaged integration selection covers conversations, all new persistence
cases, raw PostgreSQL isolation, boundary migration, delivery recovery and state
corrections. Runtime smoke checks actual HTTP liveness/readiness, UID 10001, a
private rejection of invalid isolated-launcher input, and all 40 Python source
files plus `uv.lock` against the tested source.

## Reproduction and disclosed intermediate results

```sh
uv sync --frozen
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run bandit -r src -q
uv audit --locked
```

Configure `ANOIFIG_TEST_ADMIN_DATABASE_URL` and `ANOIFIG_TEST_DATABASE_URL` for a
disposable PostgreSQL database whose name ends `_test`, using separate owner and
runtime roles. Run the new cases directly with:

```sh
uv run pytest -q tests/unit/test_tara_re_review.py \
  tests/integration/test_tara_re_review_persistence.py
```

Early patches over-rejected valid requests. Existing integration assertions exposed
invoice/work data frames, ordinary amount corrections, partial initial collection
and another item's stated preserved price; these were corrected without changing
the assertions. Intermediate full runs stopped on failures or were interrupted
when a confirmed gap required a code change. They are not reported as passing.
An unmodified focused provider run was 73 passed / 1 failed at fault entry; the
first prepared replay was 74 passed. An intermediate packaged integration run
was 207 passed / 3 failed, including a VAT setup failure whose cause was not
established. Later runs also exposed contact-data compatibility failures (558 passed / 3 failed
before stopping on the host; 230 passed / 1 failed in Docker), corrected with all
existing assertions intact. A clean-image provider run was 75 passed / 1 failed
at parent-death setup, leading to the explicit readiness signal. A concurrent-build host run was interrupted after two unchanged process-recovery
tests timed out (85 passed / 2 failed); a concurrent Docker provider run was
75 passed / 1 failed at the unchanged 20-second fixture-preparation bound.
These prompted serial validation without altering their safety thresholds.
A later serial recovery selection also failed three timing checks (4 passed);
a diagnostic replay passed with stack samples showing slow FastAPI/Pydantic
imports and a database operation. This demonstrates timing variability, not a
proven single root cause. Production code and the original timing assertions
were not changed to make these recovery tests pass.
A later packaged run was 237 passed / 1 failed while establishing initial VAT;
the historical-message check itself was never reached. That case passed alone,
and investigation then reproduced the ingress-helper race above. No claim is
made that every earlier intermittent failure has the same cause.
One run was aborted by workspace disk exhaustion; unused task image/cache cleanup restored
capacity without removing database volumes. Interrupted and failed runs are not
counted as passing evidence. Only the final candidate results above establish
this validation.

## Remaining gates

No live Twilio/OpenAI provider, production deployment, infrastructure provisioning,
invoice issuance or merge was performed. Tests use synthetic data. Provider cold
startup and remote acceptance/cost remain bounded as described in the deadline
report. Production retention/deletion/subject-rights, vendor/privacy review, Irish
tax review, operational controls, staging/load and backup/restore remain separate
gates. Request a fresh independent review of the final exact SHA before merging.
