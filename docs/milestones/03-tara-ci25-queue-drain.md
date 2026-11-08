# PR #4: CI run 25 queue-drain investigation

Investigated commit: `cce059dbc26e65b07e433f24adac71d5b19cc23f`.
No merge, deployment or live provider call is part of this correction.

## Finding

The test's 30-second drain cutoff is a throughput assumption, not the queue's
correctness contract. A valid ordered-reply backlog can keep making durable
progress and still fail that cutoff. The confirmed defect is in the test harness;
the exercised worker, claim, retry and locking paths did not lose work, duplicate
sends or remain permanently blocked. No production change is justified by this
evidence.

[Run 25, attempt 1](https://github.com/shanecahalane-web/AnOifig/actions/runs/42466962810/attempts/1)
failed at `test_messaging_queue_fairness.py:317`: 202 replies existed but only 135
provider sends completed. The suite reported **3,037 passed / 1 failed in
714.50s**. Lint, formatting and strict Mypy passed; the two security-audit steps
were skipped after the failure. The earlier local suite had passed all 3,038
tests. An unchanged-commit [second GitHub attempt](https://github.com/shanecahalane-web/AnOifig/actions/runs/42466962810/attempts/2)
passed **3,038 tests in 664.24s**, including both audits. This establishes
intermittency on GitHub itself; it is not evidence for a later correction SHA.

Attempt 1 did not retain per-round timings or pending-job snapshots. Its precise
thread interleaving cannot be reconstructed. The deterministic reproduction below
demonstrates the same failed completion criterion with live, progressing work;
it is not presented as a replay of the unavailable CI interleaving.

## Scheduling, locking and retry analysis

- `migrations/versions/0004_messaging_queue_fairness.py` claims eligible jobs by
  `GREATEST(due_at, last_claimed_at)`, then due time and UUID. Atomic
  `FOR UPDATE SKIP LOCKED` claims move a job's next turn behind waiting work.
- `MessagingWorker._has_unresolved_predecessor` orders outbound replies by their
  durable inbound `received_at` and UUID. Claim order can differ from this order,
  particularly after retries, lock contention or retained records. A claimed
  successor correctly defers until its predecessor sends.
- Source and conversation locks prevent concurrent processing/dispatch. Provider
  I/O remains outside the database transaction; dispatch intent and successful
  reconciliation remain durable. No exception was swallowed by the observer.
- Deferred work releases its opaque receipt with a one-second polling cooldown.
  This is not a provider retry and does not increment send attempts. Business
  retry times, dispatch leases and uncertain-send rules are separate.
- The old test already advanced only tokenless polling cooldowns after joining
  both workers. That removes idle waits but cannot make ordered successors
  dispatchable before their predecessors. A zero-return batch does not prove
  that the queue is empty.

The reproduction preserved real PostgreSQL claims, source triggers, receipts,
worker transactions, authorisation and RLS. At the observed cutoff, no active
receipt or database lock waiter prevented progress. The pending outboxes had
zero send attempts and no errors. Continued polling of those same records,
without changing production code, completed every send exactly once.

## Reproduction evidence

Local matching runs used Python **3.13.16**, the unchanged frozen lockfile,
PostgreSQL **17.11** and the exact CI image digest
`sha256:665dc7b37ac52a17e298511414c21d23ffa4e6a6ef6225b3e5d59c7afb35e994`.
The outer executor had a two-CPU quota and 8 GiB memory. Python affinity was two
logical CPUs; the disposable database was limited to one CPU and 1 GiB. A stress
profile reduced the database to half a CPU. These controlled profiles do not
claim to recreate GitHub's undisclosed instantaneous CPU contention.

| Before correction | Result |
| --- | --- |
| Initial Python 3.13.5 profile, one or two Python CPUs | One uninstrumented and two instrumented passes |
| Three runs matching CI's Python and database image | All passed; drain times 25.269s, 13.262s and 16.762s |
| Three matching runs with half a database CPU | All passed; drain times 15.726s, 16.010s and 15.207s |
| Deterministic source/claim order mismatch, run 1 | Original test failed: 107 sends, 95 pending outboxes, all 202 inputs processed, at 34.323s of drain time |
| Continued polling after that original failure | All 202 sent at 246.345s of drain time; 0 ready jobs, all send/input attempts exactly 1, no worker warnings or processing errors |
| Deterministic source/claim order mismatch, run 2 | Original test failed: 109 sends, 93 pending outboxes, all 202 inputs processed, at 44.699s of drain time; continued polling reached 202 sends at 265.231s, with no errors or worker warnings |

The order-mismatch probe assigns synthetic tenant A inputs a durable received
order opposite their due/UUID claim order. All original assertions and production
operations remain unchanged. Tenant B retains its ordinary order, preserving the
four initial locked-row fairness rounds. Elapsed times are measured at the failed
assertion; an already-started batch and final checks may finish after the old
30-second polling cutoff. The first failed snapshot showed 547
predecessor deferrals, 12 conversation-lock deferrals, 95 ready outbound jobs,
21 polling cooldowns, no future-due jobs and no active receipts. After continued
polling there were 5,000 predecessor deferrals and every outbox was sent once.
This is expensive ordered polling, not a claim that production latency is bounded
by 30 seconds. Backlog latency and capacity remain operational review concerns.

The external observer delegates production calls and records only aggregate
counts, fixed error codes, deferral counts, exceptions and elapsed times. It
retains the original failure even when post-failure continuation completes.
Observation overhead is included; these are not production performance claims.

## Exact correction

Only [`tests/integration/test_messaging_queue_fairness.py`](../../tests/integration/test_messaging_queue_fairness.py),
[`tests/integration/test_messaging.py`](../../tests/integration/test_messaging.py)
and this report change. Production source, migrations, dependencies, queue
priorities, retry delays, leases and provider deadlines are unchanged.

The final drain now measures **committed processed inputs plus sent outboxes**.
Claims, released receipts and worker return values cannot count as progress.
Four consecutive joined polling rounds without committed progress fail with
aggregate queue/outbox diagnostics. The finite input/send population also bounds
the total polling-round budget. Individual worker future/barrier timeouts and
the CI job timeout remain unchanged.

All **44 existing fairness assertion ASTs** remain unchanged, including the initial four
locked-row fairness rounds, expired-receipt fencing, 202-send completion,
one-attempt/SID/reply checks and tenant read/write isolation. Completion now also
requires zero ready jobs. Diagnostics contain no bodies, phone numbers, DSNs or
raw provider/driver errors.

Three new integration cases establish the drain guard's behavior:

1. Sixteen reversed-order replies require exactly sixteen real polling rounds,
   send in durable source order, and each produce one provider SID and attempt.
2. The same case with the test's diagnostic clock advancing 31 seconds at a time
   still completes. Database clocks, production deadlines and leases remain real.
3. A held conversation lock causes real claims/cooldowns to cycle with no sends.
   The guard fails after four rounds; releasing the lock permits exactly-once
   completion. This checks that the correction does not accept claim churn or
   hide a stalled queue.

The first affected-suite run exposed a second pre-existing harness edge case:
`test_concurrent_messages_and_callbacks_remain_distinct_and_tenant_isolated`
called the generic eight-batch idle helper before its own bounded ordered-drain
loop. Eight productive batches could make that preliminary helper fail before
the intended drain loop ran (**1 failed / 74 passed in 127.01s**). An isolated
baseline retry passed, confirming that this preliminary path also depends on
interleaving. Its failure snapshot was not retained, so no claim is made that
all sixteen sends had finished when that particular helper failed.

The correction removes only that redundant preliminary `drain(worker)` call.
The existing per-tenant drain loop, its bound and every callback/deduplication/RLS
assertion remain. The generic helper used by other tests is unchanged. All
**255 original assertion ASTs** in `test_messaging.py` are unchanged; the maximum
number of post-concurrency drain polls decreases rather than being extended.

## Correction validation

| Check | Result |
| --- | --- |
| Three new drain guards | 3 passed, 5 deselected, 34.27s |
| Repeated concurrent-message/callback test after removing redundant preliminary drain | Five passes; each completed all 16 sends with no ready jobs and one attempt per outbox; observed test-body times 5.873–6.564s |
| Same large deterministic reproduction after correction | Passed: all 202 sends, no ready jobs, one attempt per outbox and no worker warnings; drain 235.717s |
| Affected messaging integration tests after both scoped harness corrections | **75 passed in 99.47s**; includes claims, retries, concurrent workers, callbacks, fairness and the three new guards |
| Full unfiltered suite | 3,041 tests collected; the final exact-commit outcome is recorded in [PR #4](https://github.com/shanecahalane-web/AnOifig/pull/4) |
| Ruff lint and formatting | Passed |
| Strict Mypy | Passed, 40 source files |
| Bandit | Passed |
| Locked dependency audit | Passed; 72 packages, no known vulnerabilities or adverse project statuses |
| Existing assertion integrity | All 299 original assertions across both changed test modules unchanged |

From the repository root, with separate owner/runtime URLs for the same dedicated
disposable database ending `_test`:

```sh
uv sync --frozen --python 3.13.16
uv run --frozen pytest -q tests/integration/test_messaging_queue_fairness.py
uv run --frozen pytest -q
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy src
uv run --frozen bandit -r src -q
uv audit --locked
```

The final correction SHA, unfiltered local-suite result and GitHub Actions result
are recorded together in PR #4's validation section.
Do not infer that a new commit's CI passed from the unchanged-baseline rerun.
Independent review remains required; nothing is merged or deployed.
