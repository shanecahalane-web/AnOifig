# Milestone 3 validation and readiness

Validated locally on 16 October 2026 from `main` commit `3fe5ec5`, on branch
`codex/milestone-3-tara`. Python 3.13.5, PostgreSQL 17.11, restricted non-owner
runtime role and a dedicated disposable `anoifig_test` database were used.

## Implemented

- OpenAI Python SDK 2.54.0, configurable model, strict structured replies and a
  single allowlisted preparation-note proposal tool; deterministic mock injection.
- PostgreSQL conversation notes, typed intent/corrections, evidence-backed Decimal
  money validation, missing-field questions, task reset and bounded context.
- Per-business atomic reservations, token/estimated-cost and model/prompt tracking,
  safe fallbacks, durable processing fences and content-free action audit metadata.
- Existing signed ingress, verified membership, RLS, durable queue, outbox,
  deduplication, callbacks and WhatsApp-window/uncertain-send protection preserved.
- Reviewed migration 0005, local configuration, CI security scanning, architecture,
  operator instructions and future invoice-tool contracts.

## Results

| Check | Result |
| --- | --- |
| `uv sync --frozen` | Passed |
| `uv run --frozen pytest -ra` | **614 passed**, 97.16 seconds; no skips |
| Milestone 1 and 2 regressions | Included in the complete passing suite |
| New Tara tests | 104 passing tests, including 30 multi-message scenarios |
| `uv run --frozen ruff check .` | Passed |
| `uv run --frozen ruff format --check .` | Passed, 76 Python files |
| `uv run --frozen mypy src` | Passed, 34 source files |
| `uv run --frozen bandit -r src -q` | Passed, no findings |
| `uv audit --locked` | No known vulnerabilities/adverse statuses in 72 packages |
| Compose configuration | `docker compose --env-file .env.example config --quiet` passed |
| Example settings | Parsed and validated without connecting providers |
| Migration checks | Historical upgrade/downgrade, retained messaging data, grants/RLS and Alembic metadata checks passed |

The new tests cover actual runtime-role cross-tenant/user reads, writes and source
substitution; shared business budgets under concurrency; ordered/head-blocked
messages; interruptions/corrections; malformed/refused/unknown tool results;
SDK timeout/rate-limit/server retries; revoked membership during AI I/O; expired
memory and explicit forgetting; unknown state/context limits; duplicate replies;
SIGKILL after a committed reservation; and lost reply-commit acknowledgement.

No automated test calls OpenAI or Twilio. Strict SDK serialization/parsing uses
an in-memory HTTP transport; conversation extraction uses scripted model outputs.
These tests establish application contracts and recovery, not live model quality.

## Readiness assessment

The conversational foundation is ready for human code review and further local
or approved staging evaluation. It is **not approval for production onboarding**.
No live accounts were connected, Azure deployed, paid resources provisioned,
frontend branches changed, or invoices/PDFs/financial documents generated.

Remaining gates include live model/personality/extraction evaluation with approved
data, current provider pricing and spend limits, physical erasure of dormant notes
and raw messages plus vendor/backup retention, privacy/DPA/transfer and tax review,
monitoring/alerts and ownership, abuse controls, load/failure testing, secrets and
backup/restore operations. Model interpretation can still be wrong despite source
validation; social-output filtering is a heuristic. Input token/cost bounds are
conservative application estimates, not a provider billing guarantee. Local
reservations are deliberately not refunded after uncertain calls.

Migration 0005 requires a maintenance window and new runtime grants. Downgrade
removes Tara notes/audit/usage while retaining messaging data; it must not be used
to reset a live day's budgets. Prefer a forward fix. See
[ADR 0006](../adr/0006-tara-conversations.md) and the
[Tara runbook](../runbooks/tara.md) for detailed contracts and limitations.
