# ADR 0005: Age-based turns for new messages and retries

Status: proposed for Milestone 2 review, 15 October 2026.

## Problem

Revision 0003 orders `last_claimed_at NULLS FIRST`. Every never-claimed job has
permanent priority over every retry or expired claim. Continuously arriving
messages from one tenant can therefore starve eligible work from another.
Reversing NULL priority would create the opposite problem.

## Decision

Give each ready job a queue turn, using only existing database metadata:

```sql
ORDER BY GREATEST(due_at, COALESCE(last_claimed_at, due_at)), due_at, id
```

A new job joins at its due time. A claim sets `last_claimed_at` to the database
statement clock, moving its next turn behind work already waiting. A later
business retry due time delays that turn further. Discovery and atomic claiming
use exactly the same eligibility and order. Due time and UUID break ties
deterministically. No class, tenant, or worker receives permanent priority.

For a waiting eligible job, later arrivals and reclaims receive later turns.
Each available predecessor gets at most one turn before moving behind that job.
With a finite preceding backlog and continuing worker capacity, that job gets
a processing opportunity. This also lets fresh messages progress while retries
keep returning. This is fairness between waiting jobs across tenants, not an
equal per-tenant throughput quota or a fixed latency guarantee under overload.
A locked source gets a claim opportunity but cannot finish until its lock is
released; indefinitely held locks and unavailable workers require operations.

Use the existing `FOR UPDATE SKIP LOCKED`, two-minute leases and opaque receipt
fencing. Keep the one-second contention cooldown and idle-batch polling delay.
Domain authorisation, RLS, row locks, bounded retries and idempotent outboxes
remain mandatory. Scheduling metadata never authorises tenant content access.

A partial B-tree index on the exact turn expression, due time and UUID includes
only ready jobs. An explicit turn-at-or-before-statement-time predicate bounds
the scan before future scheduled work; all claims use that same database clock.
Selection can stop after the requested batch without sorting the ready backlog.
The index still needs maintenance on claim/source updates. Active leases and
locked metadata entries can require additional scanning; monitor backlog age,
claim latency, lock contention and index/table growth in staging.

Weighted queues, separate class quotas and per-tenant counters would add state,
coordination and batch-size edge cases without improving the required waiting-job
fairness. Age-based turns use one atomic ordered claim and work at limits 1–1000.
No changes to the queue protocol or new infrastructure are needed. A future
Service Bus database pump must preserve this fair selection and must not let
fresh publications indefinitely bypass scheduled redeliveries; broker settlement
still follows the domain commit and cannot replace database idempotency.

## Migration and rollback

Leave revision 0003 unchanged, even though the PR is unmerged and undeployed:
review and development databases have already applied it. Forward revision
`0004_messaging_queue_fairness` replaces discovery/claim function bodies with
`CREATE OR REPLACE` and replaces their supporting index. Clean installations run
0001–0004; databases on 0002 or 0003 run the remaining normal upgrades.

Pause API/workers for the owner-only upgrade and grant verification, then restart.
Index creation is transactional and blocks writes; schedule a maintenance
window proportional to queue-table size. No table reset, data backfill, claim
reset or new runtime privilege is needed. Existing function signatures, owners,
EXECUTE ACLs, forced RLS, source triggers, receipts and source data remain intact.
Downgrading 0004 preserves those records/receipts and restores 0003's original
index and scheduling behaviour, including its known starvation defect. Prefer a
forward fix; do not resume sustained traffic on that scheduler without review.

## Verification

The same PostgreSQL reproduction was run before and after the correction. An
older eligible tenant A job was present while four separately committed batches
of 100 newer tenant B jobs arrived, with statement timestamps verified to be
later than A's preceding claim. Before: A received zero turns in all four batches.
After: A received a turn in every batch; 99 B jobs progressed in each batch.
Both abandoned retries and unacknowledged expired claims are covered.

The reverse test repeatedly reclaims 400 older retry jobs while admitting new
messages from another tenant. All four newcomers receive a turn within five
batches of admission while 796 retry turns also progress. Concurrent-worker
tests hold 100 real source locks and one metadata lock across several batches,
recover an expired claim and verify one reply, outbox and provider SID per input,
then assert tenant read/write isolation with the actual runtime role.

The performance regression uses 20,002 operational rows: 16,002 retired, 2,000
future and 2,000 due. It explains the actual candidate SELECT stored in the claim
function, requiring the partial index, a bounded index condition, 100 examined
rows and no sort. Five real 100-job claims must return 500 distinct eligible jobs.
One local run measured 5.84 ms for candidate selection and a 12.44 ms median
(19.20 ms maximum) for five runtime claim batches, including runtime privilege
checks. Timings are reported rather than asserted against a hardware benchmark.
These local results do not establish production capacity or SLOs.

Retained-data upgrade/downgrade/re-upgrade tests compare complete source/claim
snapshots, RLS policies, table/function owners and ACLs, and validate runtime
grants without granting anything new. The full Milestone 1/2 security, recovery,
provider-failure and process-restart tests remain required.
