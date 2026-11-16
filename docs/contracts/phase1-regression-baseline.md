# Phase 1 regression baseline

Reference: `d0152dfb06b67ad88c470df3a6f8d42cb3d2e90c`. This milestone adds
contracts and tests only; no proposal implementation or scheduling change exists.

The new tests use signed WhatsApp ingress, synthetic messages/model outputs,
PostgreSQL source triggers and the application's restricted runtime role. They
seed a complete synthetic `InvoiceNotes` object with amount `600` and version
`7` using the disposable test owner, avoiding dependence on the future proposal
implementation to establish pre-existing state.

- Four strict expected failures cover two status messages with full and cropped
  evidence. Each persists amount `700` and advances the version without a user
  confirmation on the reference implementation.
- Three strict expected failures describe stale, replayed and cross-tenant
  confirmations. Currently each stops at the same prerequisite: a normal
  proposal mutates saved notes immediately instead of creating a pending
  proposal. The downstream confirmation assertions are **not yet exercised**;
  they require the new lifecycle. Existing tests for stale model completions,
  ordinary message replay and tenant RLS remain passing controls, not substitutes.
- Two strict expected failures arrange a future-due head for tenant A, an earlier
  due blocked successor, and an eligible head for tenant B. Real queue claims
  select A's blocked successor rather than B's runnable job, for both inbound and
  outbound lanes. This demonstrates a wasted claim opportunity, not by itself
  proof of indefinite starvation. The prior outbound conversation-lock race has
  already been corrected at this commit; its existing regression remains a
  passing control.

`xfail(strict=True, raises=AssertionError)` makes a fully passing test an error
until the marker is deliberately removed; other exception types remain failures.
Because assertions before the target assertion could also be interpreted as an
expected failure, qualification includes an explicit `--runxfail --tb=short` run
and inspection of the nine failure locations. Do not treat expected failures as
safety evidence. Convert them to passing checks during the implementation
milestone and ensure the confirmation tests reach their final assertions.

Recorded 16 November 2026 using Python 3.13.5, disposable PostgreSQL 17, and
separate owner/non-owner runtime roles:

- Queue, fairness, delivery recovery, state correction, two isolation/replay
  controls and the new regression module: **46 passed, 9 xfailed**. This run used
  the pre-existing compatible Python environment and the PR source tree.
- Final new regression module, with the branch's frozen dependencies and complete
  synthetic saved-note fixture: **9 xfailed**.
- The three existing focused authority/assertion unit modules: **255 passed**
  with the branch's frozen dependencies.
- Ruff lint, Ruff formatting and strict mypy: passed with the branch's frozen
  dependencies. An earlier mypy attempt using the older environment failed for a
  missing `openai` package; frozen sync provided the required dependency.
- With expected-failure markers disabled using frozen dependencies and the final
  complete-note fixture: **9 failed** at the intended assertions, including all
  four persisted mutations, the three proposal prerequisites and both blocked
  claims.

To reproduce with the project's dedicated disposable database and separate
owner/runtime URLs configured as described in `AGENTS.md`:

```sh
uv sync --frozen
uv run --frozen pytest -q -rx tests/integration/test_phase1_contract_regressions.py
uv run --frozen pytest -q --runxfail --tb=short tests/integration/test_phase1_contract_regressions.py
uv run --frozen pytest -q tests/unit/test_tara_final_review.py tests/unit/test_tara_re_review.py tests/unit/test_tara_assertion_context.py
```

The second command is expected to fail on this baseline. Review the failure
locations rather than interpreting its exit code as a healthy production system.
No live provider, merge or deployment is involved.
