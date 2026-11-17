# Phase 1: proposal lifecycle implementation

This milestone implements application-owned previews and exact APPLY/REJECT
confirmation for preparation-note changes. It does not implement conversation
lane scheduling or invoice issuance. See `docs/contracts/phase1-proposals-and-lanes.md`
and `docs/runbooks/tara.md` for the contract, migration and operational behavior.

## Verification

Tests used disposable PostgreSQL 17, synthetic Twilio/model data, and distinct
owner and restricted runtime roles. The seven former authority expected failures
execute through confirmation and pass. The two queue-head claim checks remain
strict expected failures and are reserved for the later queue milestone.

Final targeted run after the implementation and memory/version race corrections:

- `test_phase1_contract_regressions.py`, `test_phase2_proposals.py` and
  `test_tara_state_corrections.py`: **43 passed, 2 expected failures**.
- Focused preview, authority/assertion, database TLS and grant unit tests:
  **335 passed**.
- Historical Tara boundary and messaging claim migrations: **3 passed**, with
  pre-proposal revisions checked against their historical privilege contract.
- Ruff lint, formatting and strict mypy: passed.

Other focused runs during implementation exercised the same lifecycle before
minor later changes to version/memory rechecks and preview presentation:

- Previous independent-review persistence corpora: **227 passed**.
- Authority persistence: **128 passed**; supplemental variants: **36 passed**.
- Scope persistence: **100 passed**; assertion persistence: **92 passed**.
- Tara conversations and other Tara integration cases: **53 passed**.
- Delivery recovery: **10 passed**; shared assertion and tenant checks:
  **13 passed**; follow-up rejection checks: **37 passed**; earlier review
  correction tests: **34 passed**.
- A combined lifecycle, messaging, migration and security selection had
  **129 passed, 2 expected failures** before the later targeted changes.

An attempted full unit-suite run and a later SDK transport selection stalled
without progress in the sandbox and were interrupted; they are not counted as
passing results. The complete repository test suite was not run. Independent
review, production retention and deletion, real provider and deployment gates
remain outstanding. Do not interpret these results as permission to merge or
deploy.

## Milestone 2 independent review corrections

Reviewed commit `839175b7c7e94a93afe43e72fe1a7f0a24197879`. The final route
check read the phone link without locking it. Unlink could commit before
confirmation saved its changes. The final confirmation check now takes a
PostgreSQL `FOR SHARE` lock on the active phone link after the conversation and
preview locks. Unlink already takes `FOR UPDATE` on the link and needs no
conversation or preview locks. The second transaction waits for the first to
finish. When unlink commits first, the locked query finds no active link
and the worker parks the job. The existing tenant policies and runtime grants
apply to both transactions.

The challenge detector previously required word boundaries, and history relied
on audit actions that terminal recovery could leave null. The same sensitivity
check now applies at ingress, during processing and when reading legacy history.
Malformed confirmations receive a fixed error, and ingress stores a placeholder
in place of their bodies. Exact commands retain their original text for
verification until their processing or terminal fallback commits. History
checks the body even when there is no audit action, and model-visible notes
redact possible challenge strings. The proposal and its deliverable preview
retain the challenge for the existing confirmation flow.

### Correction verification

Tests used Python 3.13.5, frozen dependencies, synthetic webhook and model data,
and disposable PostgreSQL 17 with separate owner and restricted runtime roles.
The concurrency test uses distinct backend PIDs, an authenticated HTTP unlink,
and `pg_blocking_pids` to observe the second transaction waiting. The recovery
test forces all five reply failures before checking the fallback and next model
request.

| Command | Result |
| --- | --- |
| `uv sync --frozen` | Passed. |
| `uv run --frozen pytest -q tests/integration/test_phase2_proposals.py -k 'phone_revocation or terminal_fallback or (malformed and x)'` | Reviewed application code with the initial regressions. Seven failures reproduced both revocation orderings, four malformed model inputs and the terminal-fallback history leak. |
| `uv run --frozen pytest -q tests/integration/test_m2_baseline_probe.py` | Temporary probe on the reviewed commit reproduced the appended challenge in both the current model request and the next turn's history. |
| `uv run --frozen pytest -q tests/integration/test_phase2_proposals.py tests/integration/test_phase1_contract_regressions.py` | 43 passed, two queue checks xfailed. |
| `uv run --frozen pytest -q tests/integration/test_phase1_contract_regressions.py -k 'not blocked'` | All seven original authority cases passed. The two queue checks were deselected here. |
| `uv run --frozen pytest -q tests/integration/test_phase2_proposals.py::test_confirmation_terminal_fallback_does_not_replay_challenge` | Passed after adding the challenge to the injected exception text to verify it stays out of diagnostic logs. |
| `uv run --frozen ruff check .` | Passed. |
| `uv run --frozen ruff format --check .` | Passed after formatting the changed service. |
| `uv run --frozen mypy src` | Passed in strict mode for 40 source files. |
| `git diff --check` | Passed. |
| `uv run --frozen pytest -q tests/unit/test_tara_provider.py tests/unit/test_tara_provider_harness.py tests/unit/test_tara_provider_isolation.py` | 74 passed and two offline fixture startup timeouts in a run concurrent with the integration suite. |
| `uv run --frozen pytest -q tests/unit/test_tara_provider_isolation.py::test_isolated_sdk_result_and_complete_payload 'tests/unit/test_tara_provider_isolation.py::test_deadline_bounds_real_resolver_retry_and_uncancellable_transport[dns_ignore_term]'` | Both timeout cases passed on the reviewed commit and on the correction. |
| `uv run --frozen pytest -ra` | 3,093 passed and two queue checks xfailed across all 3,095 collected tests. Restricted-role PostgreSQL covered 1,051 cases, including tenant isolation, privilege drift, concurrency, migrations, Tara and messaging. The provider fixture timeout cases passed in this run. |

The full selection completed without skips. The strict expected failures remain
the existing blocked inbound and outbound successor claim checks, which belong
to the queue milestone. Both independent Milestone 2 blocker regressions passed.
