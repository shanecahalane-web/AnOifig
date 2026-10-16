# Tara configuration and local verification

Tara now supports contextual conversations through the Milestone 2 messaging
worker. Read [ADR 0006](../adr/0006-tara-conversations.md) for state, ordering,
authorisation, privacy and recovery guarantees and their limits.

## Offline modes

Compose explicitly defaults to `ANOIFIG_TARA_MODE=acknowledgement` and Twilio
`--local`: the original fixed acknowledgement, no OpenAI or Twilio sends.
`ANOIFIG_TARA_MODE=mock` uses the same durable orchestration but a canned social
reply. `MockAIProvider` accepts scripted structured results/failures for realistic
offline conversations; it does not emulate language understanding.

```sh
uv sync --frozen
uv run --frozen pytest tests/unit/test_tara_provider.py -q
# Requires the dedicated *_test database and separate owner/runtime URLs:
uv run --frozen pytest tests/integration/test_tara.py -q
```

The 30 readable scripts are in `tests/scenarios/tara_conversations.json`.
They exercise signed ingress, real PostgreSQL/RLS, memory, corrections, missing
fields, interruptions, quantities, VAT, unsupported requests and injection.
Mock outputs are scripted expectations, **not evidence of a live model's extraction
accuracy**. Additional tests cover concurrent messages, head-of-conversation
ordering, duplicate delivery, budgets, invalid outputs, SDK timeouts/retries,
revocation during provider I/O, SIGKILL recovery and lost commit acknowledgement.
The SDK's real serializers/parsers run over an in-memory HTTP transport.

The complete release checks remain:

```sh
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy src
uv run --frozen pytest -ra
uv audit --locked
uv run --frozen bandit -r src -q
```

## Configuration

Every setting uses the `ANOIFIG_` prefix. Configuration is validated at startup.

| Setting | Default / meaning |
| --- | --- |
| `TARA_MODE` | `acknowledgement`; `mock` and `openai` also supported |
| `OPENAI_API_KEY` | SecretStr; no default; inject securely into the worker only |
| `TARA_MODEL` | `gpt-4.1-mini`; select a model supporting strict tools and structured output |
| `TARA_TIMEOUT_SECONDS` | 15 seconds per HTTP operation, range 1–30 |
| `TARA_DEADLINE_SECONDS` | 60 seconds overall, range 1–90; cancels HTTP and SDK retry/Retry-After waits before the 120-second run fence |
| `TARA_MAX_RETRIES` | 1 SDK retry, range 0–2 |
| `TARA_MAX_INPUT_TOKENS` | 16000; conservative UTF-8/schema/framing bound checked before calling |
| `TARA_MAX_OUTPUT_TOKENS` | 1200; passed as `max_completion_tokens` |
| `TARA_HISTORY_MESSAGES` | 8 prior inbound turns, range 0–30; at most 600 characters each, minimised contact information |
| `TARA_MEMORY_DAYS` | 30, range 1–90; history cutoff plus lazy state expiry |
| `TARA_INPUT_PRICE_USD` | 0 offline; require reviewed positive USD per million input tokens live |
| `TARA_OUTPUT_PRICE_USD` | 0 offline; require reviewed positive USD per million output tokens live |
| `TARA_DAILY_BUDGET` | JSON `{"requests":100,"tokens":1000000,"cost_usd":"5"}` |
| `TARA_BUSINESS_BUDGETS` | JSON map of actual tenant UUIDs to budget objects; defaults to `{}` |

A budget request means a reserved **possible upstream attempt**, including retries.
With one retry, each model turn reserves two attempts. Budget tokens/cost count
maximum reservations even after successful calls. This conservative choice limits
cost uncertainty after worker crashes; it can stop a business earlier than its
actual consumption. Request, token and USD limits are all enforced atomically.
Reaching a limit creates a single safe reply without calling OpenAI. A zero limit
can disable provider use for one business. UTC days define budgets; do not change
prices/model mid-day without reviewing pending reservations and ledger accuracy.
Provider-reported over-limit/invalid results are rejected; estimates are not a
provider-enforced hard billing cap. Set the provider's own account spend limits too.

Compose forwards local primitive Tara settings but intentionally does not forward
an API key, prices or budget JSON. Host workers read these from their private
process environment/`.env`; reviewed Compose overrides can inject them into only
the worker. Never forward the migration DSN or an entire `.env` to runtime.
No live account connection is authorised by these instructions. Once separately
authorised, configure key, current reviewed prices, model, tenant budgets and
`openai` mode. Do not use SDK debug logging with customer conversations.

## Instructions and conversation controls

`src/anoifig/tara/prompt.py` is the reviewed instruction source. Change the
`PROMPT_VERSION` whenever changing behavioural instructions, and rerun the scenario
suite. Each run records the configured model and prompt version. No remote prompt
editor, user-supplied system instruction or provider-hosted history is authoritative.

Invoice notes merge only supplied fields; absent fields survive interruptions.
Corrections do not reset the task. Selective item patches bind to the application-owned
notes version, exact item index/unique description and current-message selector.
Only changed values need new evidence. Stale completions fail without overwriting
newer notes. Full original financial spans validate signs, currency, precision and
numeric context; unrelated prices/dates cannot supply VAT evidence. Bare VAT
answers require the matching application-owned pending clarification.

Social replies select a reviewed speech act; model text is never rendered. Business
claims and capabilities come from application templates. No backend invoice,
email, payment or financial-delivery action exists in this milestone. Application templates request customer, work,
charges, VAT basis and then the user-supplied VAT rate when needed. No rate is
inferred from the trade. Exact `start a new invoice` / `start over` commands reset
the active task; they do not create an invoice. Exact `forget my notes` / `clear
my notes` commands also reset context. They leave raw messaging/audit records
subject to the [retention and deletion design](../retention-and-deletion.md).
Reset uses the reset message's durable `(received_at, id)` boundary, so messages
accepted afterward remain available even if already queued at processing time.
History carries processed inbound turns plus structured notes and pending question;
raw outbound prose is not replayed. Stored customer-contact turns are omitted,
and common email/phone/IBAN values are redacted from other stored context. The
current user input still goes to the provider to extract explicitly supplied facts;
this minimisation is not an arbitrary-PII detector or physical erasure.

## Operations and remaining release gates

Use restricted-role queries within an authorised business session to aggregate
`tara_runs.error_code`, processing age and provider usage, and inspect the day's
`tara_usage` reservation totals. Export content-free `tara_provider_failed` and
`tara_fallback` events to the approved telemetry stack. Alert on failure rate,
expired processing, budget denials, backlog age and existing messaging uncertainty.
Thresholds, on-call ownership and monitoring deployment still need review.

A two-minute interrupted turn becomes one fallback when rediscovered; its
reservation stays charged. SQL/preparation/completion errors use the existing
five-attempt processing ledger. Terminal recovery commits one fallback, fences
late results and advances the conversation without another model call. Recovery
also recognises an already committed reply after a lost commit acknowledgement.
Never reset its run or delete reply/outbox records to
force a replay. Reauthorise a parked route through the existing operator process;
reconcile its head turn before resuming later messages. Replies dispatch in source inbound `(received_at, id)` order. An unresolved earlier
pending/retry/dispatching/uncertain send blocks later replies. Uncertain sends are
never blindly replayed; signed callbacks or audited operator reconciliation must
resolve them. This orders application send attempts, not the mobile network's
ultimate delivery. Twilio dispatch uncertainty must still follow [the messaging runbook](messaging.md).

Before live use: approve the provider account/model and current prices; measure
extraction/personality accuracy on realistic Irish language and shorthand with
approved data; review semantic hallucination and prompt injection risks; schedule
physical erasure of dormant state/raw text and manage vendor/backups retention;
complete DPA/transfer/privacy and Irish tax review; configure secrets/rotation,
provider spend limits, abuse controls, monitoring, backups/restore and load/failure
tests. User evidence validates source tokens, not the semantic correctness of the
model's interpretation. No financial output exists, and this milestone establishes
no GDPR/tax compliance or production deployment approval.
