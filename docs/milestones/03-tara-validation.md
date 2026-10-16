# Milestone 3 corrections: validation and readiness

Validated locally on 16 October 2026 on `codex/milestone-3-tara`, correcting the
independent review of `5cd753e7e3065d7a9c54d61686665e7bfc4fcc39` in PR #4.
Python 3.13.5, PostgreSQL 17.11 and dedicated disposable databases with separate
owner/restricted runtime roles were used. No live OpenAI/Twilio, Azure deployment,
frontend changes, invoice issuance or merge was performed.

## Corrected defects and source map

| Finding | Result | Source |
| --- | --- | --- |
| High: cropped financial/VAT evidence | Full original-message offsets preserve numeric boundaries, currency, sign and precision; ambiguous evidence fails. VAT needs explicit VAT context or matching pending clarification. Decimal values stay exact. | `tara/schemas.py` |
| Medium: selective corrections | Typed item patches bind to the application-captured notes version, exact index, unique description and current-message selector; merge only changed fields. Duplicate/stale/ambiguous patches fail. | `tara/schemas.py`, `tara/service.py` |
| Medium: queued reset loses context | Reset/expiry frontier uses source acceptance `(received_at,id)`; later accepted messages survive processing delay, earlier context stays excluded. | `tara/service.py`, `db/tara_models.py` |
| Medium: stale financial reply overtakes correction | Conversation-serialised dispatch gates later replies behind unresolved predecessors; durable source order includes UUID ties. Uncertain sends require callback/operator reconciliation. | `messaging/worker.py` |
| Medium: unbounded Tara DB failures | Existing retry ledger covers preparation/completion errors, head only. Terminal recovery produces one fallback, fences late results and preserves reservations. Lost acknowledgements reconcile committed state. | `messaging/worker.py`, `tara/service.py` |
| Medium: false business-action claims | Model text is never rendered. Reviewed speech acts, note questions and capability templates are application-controlled. No invoice/email/payment tool exists. | `tara/schemas.py`, `tara/service.py`, `tara/prompt.py` |
| Low: unnecessary contact replay | Minimal inbound history plus structured state; omit contact turns/details, redact common email/phone/IBAN patterns and do not replay outbound prose. Full payload tests include unstructured private markers. | `tara/privacy.py`, `tara/service.py` |
| Low: SDK retry deadline | Cancellable async HTTP/retry operation under one wall-clock deadline, default 60/max 90 seconds, below 120-second run fence; no detached provider task. | `tara/provider.py`, `config.py` |
| Production blocker: physical retention | Concrete proposed dormant purge, subject-rights, vendor and backup design; implementation/testing remains a release gate. | `docs/retention-and-deletion.md` |

Paths above are under `src/anoifig/` unless prefixed `docs/`. Supporting changes:
`messaging/service.py` stamps application state versions on source/reply records;
`db/messaging_models.py` and migration 0006 add nullable metadata/checks without
rewriting existing data or changing grants/RLS. `.env.example`, `compose.yaml`,
ADR 0006 and the Tara runbook describe the contracts and deadline settings.
Historical migration fixtures now explicitly insert historical columns; two
concurrency tests advance only polling cooldown after joined workers, preserving
all tenant, fairness, idempotency and delivery assertions under ordered dispatch.

## Before and after evidence

Original-source comparisons used an untouched `git archive`/`git show` of the
reviewed commit in temporary directories, the same regression code, offline
providers, and separate disposable databases. The reviewed working tree was not
rewritten to obtain baseline results.

| Regression | Reviewed source | Corrected source |
| --- | --- | --- |
| Financial/VAT adversarial selection | 149 failed, 8 passed, 32 deselected | All 189 financial unit cases pass; all six exact reported unsafe updates reject |
| State correction module (initial 10 cases) | 9 failed, 1 passed | 10 pass; UUID ordering already passed both |
| Reset followed by queued BLUEBIRD then greeting | BLUEBIRD absent | BLUEBIRD retained; pre-reset SECRET absent |
| Changed notes version during provider gap | New 700 overwritten by stale 500 | New 700 retained; one safe fallback |
| Selective item-price correction | Existing replacement required repeating unchanged evidence; patch schema absent | Three valves retained, price 25→30, elbows preserved; duplicate delivery unchanged |
| Prior contact followed by greeting | Email/private marker remains in full payload | Contact email/phone/IBAN/private marker absent from full next payload |
| Five action-claim paraphrases | Model prose returned verbatim | Application speech acts only |
| Rapid corrections plus rejected send/restart | Later reply dispatches past unresolved predecessor | Durable 450→500→550 send order |
| DB preparation failure | SQL error escapes retry accounting | Five failures then one fallback; next turn advances |
| Retry-After deadline | Existing SDK could request two 60-second waits despite per-attempt HTTP bounds | Real SDK async mock transport cancels 60-second retry wait within configured 1-second deadline; in-flight HTTP also cancels/closes |

Committed regression modules: `tests/unit/test_tara_financial.py`, updated
`tests/unit/test_tara_provider.py`, `tests/integration/test_tara_state_corrections.py`,
`test_tara_delivery_recovery.py` and `test_tara_boundary_migration.py`.
The 10 new delivery/recovery tests pass against real PostgreSQL. Two copied
outbox/failure tests both fail against the reviewed commit. Four further
PostgreSQL cases verify matching VAT pending questions and invalidation by social,
reset or unsupported interruptions. Migration tests compare every old source,
claim, notes/run/usage value across 0005→0006→0005→0006, plus RLS, table/function
owners/ACLs, legacy NULL compatibility, new constraints and Alembic metadata.

## Release checks

| Check | Result |
| --- | --- |
| Complete pytest, including all Milestone 1/2 regressions | **834 passed**, 137.19 seconds; no skips |
| Frozen dependency sync | Passed, 70 installed packages checked |
| Ruff lint / formatting | Passed, 84 Python files formatted |
| Mypy | Passed, 35 source files |
| Bandit | Passed, no findings |
| Locked dependency audit | No known vulnerabilities/adverse project statuses in 72 packages |
| Docker | Runtime image built with verified CA trust; owner migration/runtime grants, API live/ready, UID 10001 and mock/local worker `--once` passed |
| Compose configuration | `docker compose --env-file .env.example config --quiet` passed |
| GitHub Actions | Linked from PR #4 after push |

The historical fixture now inserts only columns available at its target revision.
Concurrency helpers advance only polling cooldown after workers have joined;
source retry times, receipts, delivery states and security assertions are retained.
Of the original-source failures above, 120 numeric-span cases use the unchanged
public proposal API and all fail independently of new feature/schema parameters.
The nine added word-sign cases also reject "minus €500" / "negative 500" rather
than interpreting them as a positive charge.

No automated test calls OpenAI or Twilio. SDK serializers/parsers and retry logic
use in-memory HTTP transports. Scripted conversations prove application contracts,
not live model extraction quality. Adversarial parameter matrices and multi-turn
invariants challenge validators independently of a model; PostgreSQL tests verify
locks, state persistence, authorisation, RLS and recovery with the runtime role.

## Readiness assessment

Prepared for another focused independent development review once CI is green;
this is not a merge or production approval. The full source changes and the
regressions are reviewable in PR #4.

**Production remains blocked.** Implement and test scheduled physical erasure of
dormant notes/raw messages, subject-rights workflows and vendor/backup treatment
in the [retention design](../retention-and-deletion.md). Approve real provider
terms, account spend limits, model/prices and realistic extraction evaluation;
complete privacy/DPA/transfer and Irish tax review, observability/ownership, abuse
controls, secrets rotation, load/failure and backup/restore testing. Arbitrary
free text can still contain PII beyond supported redaction patterns. Source-token
validation cannot prove all semantic interpretation correct. Cancellation does
not prove an already accepted upstream request incurred no cost; reservations are
never refunded, and estimates are not a provider billing guarantee. Uncertain
WhatsApp sends intentionally block newer replies until reconciled; application
send ordering does not guarantee mobile-network arrival order.

Pause API/workers for migrations and verify grants before resuming. Migration 0005
downgrade deletes Tara notes/audit/budgets while preserving messaging records;
never use it to reset live usage. Migration 0006 downgrade preserves all old values
but removes the new reset/clarification/version metadata and restores known 0005
behaviour. Prefer a forward fix. See [ADR 0006](../adr/0006-tara-conversations.md)
and the [Tara runbook](../runbooks/tara.md).
