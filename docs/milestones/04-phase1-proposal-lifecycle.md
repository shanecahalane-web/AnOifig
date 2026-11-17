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
