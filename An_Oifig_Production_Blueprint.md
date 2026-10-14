# An Oifig — Production Architecture and Codex Development Blueprint
Version 1.0 | 14 October 2026 | Proposed, not deployed

## 1. Goals and constraints
Build a production-capable, multi-tenant SaaS for Irish tradespeople. Tara is the WhatsApp AI assistant; An Oifig owns identity, business rules, records, invoices, and integrations. First release must reproduce the working prototype: WhatsApp text request -> structured invoice draft -> user confirmation -> numbered PDF -> secure document delivery. Quotes, voice, payments, jobs, and interactive WhatsApp Flows are later increments. Retain the Power Automate prototype as reference until acceptance tests pass. Twilio production sender approval remains a dependency.

Non-goals for first release: full accounting ledger, automatic tax filing, autonomous sending without confirmation, advanced CRM, payment processing, missed-call answering, multi-agent orchestration.

## 2. Architecture
WhatsApp -> Twilio webhook -> FastAPI ingress (Azure Container Apps) -> authenticate signature, deduplicate, persist message -> Azure Service Bus -> Python worker (Container Apps) -> conversation orchestration -> OpenAI structured tool calls -> domain services -> PostgreSQL; invoice PDF rendered in isolated worker and stored in private Azure Blob Storage -> outbound messaging via Twilio. Web app: Next.js TypeScript -> authenticated API -> domain services. Monitoring: Azure Monitor/Application Insights. Secrets: managed identities and Azure Key Vault. Infrastructure as code: Bicep or Terraform (choose one and standardise).

Use a modular monolith with separate API and worker processes from a shared Python package, not microservices. Container Apps can scale with demand; define minimum replicas and queue scaling after testing latency/cost. Do not add Azure Functions unless a specific use case justifies them.

### Stack
- Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL
- Azure Container Apps, Service Bus, Azure Database for PostgreSQL Flexible Server, Blob Storage, Key Vault, Application Insights
- OpenAI API, version-pinned models, structured tool calling; never let model write directly to DB
- Twilio WhatsApp API initially; isolate behind a messaging provider interface
- HTML/CSS templates and WeasyPrint for PDF; verify its OS dependencies in container
- Next.js + TypeScript for internal/business portal, using managed OIDC identity provider; no custom password handling
- pytest, Ruff, mypy/pyright, Playwright, GitHub Actions, Dependabot and security scanning

## 3. Core boundaries
Modules: identity_and_tenancy, businesses, contacts, conversations, invoices, documents, messaging, ai_orchestration, audit, subscriptions (later), reminders (later), jobs (later).

API responsibilities: receive and validate signed webhooks, authenticate portal requests, authorise resource access, create idempotent commands, expose versioned APIs. Worker responsibilities: process queued messages, call AI, generate PDFs, send messages, retry transient failures, handle dead-letter queues.

Never trust WhatsApp sender number as sufficient proof of business ownership. During onboarding, verify phone number ownership, map numbers to authorised tenant users, support revocation, and step-up verification for sensitive changes. All resource queries must scope by tenant_id and authorisation; enforce with tests and consider PostgreSQL row-level security as defence in depth.

## 4. Core data model
Use UUID primary keys, UTC timestamps, tenant_id on tenant-owned tables, constraints, foreign keys, and appropriate indexes.
- tenants: id, legal_name, trading_name, locale, timezone, VAT configuration, subscription status
- users: id, identity_provider_subject, status
- tenant_memberships: tenant_id, user_id, role
- messaging_identities: tenant_id, user_id, provider, verified_phone_e164, verification_status
- customers: tenant_id, id, name, billing_address, email, phone, VAT number optional
- conversations: tenant_id, id, provider, participant, state, last_activity
- messages: tenant_id, id, conversation_id, provider_message_id unique, direction, content metadata, delivery state
- invoice_drafts: tenant_id, id, customer_id, JSON snapshot, status, version, expiry
- invoices: tenant_id, id, invoice_number, customer snapshot, issue/due dates, currency, VAT details, totals, status, immutable issued snapshot
- invoice_lines: tenant_id, invoice_id, description, quantity, unit price, VAT rate, amounts
- documents: tenant_id, id, invoice_id, blob key, SHA-256, content type, generation version
- approvals: tenant_id, id, draft_id, actor_id, approved_version, timestamp, channel
- audit_events: tenant_id, id, actor, action, entity, metadata, timestamp
- webhook_events: provider, provider_event_id unique, receipt timestamp, processing state
- outbound_messages: tenant_id, id, dedupe key, status, provider SID, attempts

Use Decimal/NUMERIC for currency and explicit rounding rules. Invoice numbers must be unique per tenant and allocated atomically at issuance, never by the AI. Issued invoices are immutable; corrections use compliant credit/cancellation/reissue workflows after accountant/legal review. VAT applicability, reverse-charge scenarios and invoice legal fields require Irish tax review before launch.

## 5. Tara orchestration
Pipeline: classify intent -> load authorised tenant context -> extract structured fields -> validate with Pydantic -> ask for missing fields -> present draft and totals computed by backend -> explicit approval of exact draft version -> idempotent issue_invoice command -> render PDF -> deliver secure access. Use short-lived conversational state in DB; do not depend on model chat history as source of truth.

Tool interface (examples): find_customer, create_customer_draft, create_invoice_draft, update_invoice_draft, preview_invoice, approve_invoice, list_invoices. Only domain services can commit transactions. Tools must enforce authorisation and input validation. The approval command must check user identity, draft version, status and idempotency key. Never accept model text as approval by itself; bind approval to a specific draft/version and user-confirmed message or action.

Prompt injection: treat WhatsApp messages, images, customer names, receipt text, and retrieved data as untrusted; never permit these to override system policy or call unrestricted tools. Store minimal model context; redact secrets and sensitive details from logs. Implement provider timeouts, cost budgets, retry rules, and a graceful fallback for AI outages.

## 6. Webhook and delivery reliability
Validate Twilio X-Twilio-Signature against exact public URL and raw/form request parameters according to Twilio's current SDK documentation; reject invalid requests. Return 2xx quickly after durable enqueue. Persist inbound provider SID with uniqueness constraint to handle retries. Use an outbox table for messages/documents that must be sent after DB commit. Ensure at-least-once processing with idempotent handlers. Retry with exponential backoff, dead-letter after bounded attempts, and alert on DLQ growth. Reconcile Twilio delivery callbacks asynchronously. Never mark an invoice as sent just because an API request was attempted.

## 7. Security and compliance
- HTTPS everywhere, private blob containers, least-privilege RBAC, managed identities, Key Vault, encryption at rest and in transit.
- Authenticated portal with MFA for admins; roles: platform_admin, tenant_owner, tenant_staff, read_only (initially limit scope).
- Audit invoice issuance, approvals, customer edits, downloads, role changes, and payment-state changes.
- GDPR: controller/processor mapping, privacy notice, retention/deletion policy, subject rights workflow, DPA review with vendors, international transfer assessment, and breach response plan.
- Irish invoicing: obtain professional review of VAT, mandatory invoice fields, record retention, invoice sequencing and credit-note handling. Do not claim tax compliance without validation.
- Limit PII in prompts and logs. Explicitly document where customer data is stored and processed.
- Rate-limit and abuse-protect inbound endpoints; anti-enumeration, file type/size restrictions, malware scanning if accepting attachments.
- Restore-test backups and define RPO/RTO. Run tenant isolation, authorisation, penetration, load and failure tests before onboarding paying customers.

## 8. API outline
POST /webhooks/twilio/inbound; POST /webhooks/twilio/status; GET /health/live; GET /health/ready; GET /v1/me; GET /v1/customers; POST /v1/customers; GET /v1/invoices; POST /v1/invoice-drafts; PATCH /v1/invoice-drafts/{id}; POST /v1/invoice-drafts/{id}/approve; GET /v1/invoices/{id}; GET /v1/invoices/{id}/document (short-lived authorised access). Document OpenAPI contracts and error formats. No public access to raw blob URLs.

## 9. Repository structure
anoifig/
  apps/api/                 # FastAPI entrypoint
  apps/worker/              # queue consumer
  apps/web/                 # Next.js
  packages/core/            # Python domain modules
  packages/integrations/    # Twilio/OpenAI/Azure adapters
  packages/pdf_templates/   # invoice templates
  migrations/               # Alembic
  infra/                    # Bicep or Terraform
  tests/unit/
  tests/integration/
  tests/e2e/
  docs/adr/                 # architecture decision records
  docs/runbooks/
  .github/workflows/
  AGENTS.md
  README.md

## 10. Delivery stages and exit criteria
**0. Product specification (2–4 days)**: document invoice example, approval sequence, VAT assumptions, tenant roles, threat model, non-functional targets. Exit: signed-off acceptance tests and architecture decisions.
**1. Foundation (1–2 weeks)**: GitHub private repo, Docker, CI, dev/staging/prod isolation, IaC, PostgreSQL migrations, authentication, tenant scoping, secrets and telemetry. Exit: deployment from main to staging and cross-tenant access tests passing.
**2. Messaging (1 week)**: signed Twilio webhook, queue, dedupe, worker, outbound message/status callbacks. Exit: replaying a webhook never duplicates an action.
**3. Invoice domain (1–2 weeks)**: customer records, deterministic pricing/VAT, drafts, versioned approvals, atomic numbering, PDF and secure storage. Exit: golden invoice tests, rounding tests, concurrency tests and audit trail passing.
**4. Tara AI (1–2 weeks)**: conversation state, extraction, corrections, tool permissions, model fallbacks. Exit: at least 30 scripted and adversarial conversations passing with no unapproved invoice issuance.
**5. Portal and onboarding (1–2 weeks)**: tenant registration, phone verification, customer/invoice listing, role management. Exit: two test tenants operate independently.
**6. Hardening and pilot (2–4 weeks)**: load testing, backup restore, incident runbooks, security/privacy review, sender approval, 5–10 user pilot. Exit: defined SLOs, measured accuracy, documented support process, zero critical findings.

Timings are rough planning estimates, not delivery commitments. Codex can accelerate coding but cannot replace product decisions or independent verification.

## 11. Definition of done for every feature
- Acceptance criteria and threat considerations documented.
- Typed implementation with tests for happy paths, edge cases, retries and tenant boundaries.
- Database migration reversible or safely forward-only with documented rollback.
- API contract documented; secrets absent from repo/logs.
- CI passes lint, type check, unit/integration tests, dependency scan.
- PR reviewed by human; staging smoke test and observability verified.
- No automatic production deployment of unreviewed Codex changes.

## 12. Codex working method
Create a GitHub repo and connect Codex to it. Put project rules in AGENTS.md: Python/TypeScript versions, architecture boundaries, tests, no secrets, tenant scoping, no direct AI DB access, explicit approval required for issuance, no infrastructure spending or production deployment without authorisation. Give Codex one scoped issue at a time, request tests and docs, review diffs and merge via pull requests. Separate development branches per contributor. Use staging test credentials and synthetic data.

### Starter Codex prompt
"You are implementing An Oifig, a multi-tenant WhatsApp SaaS for Irish tradespeople. Read docs/architecture.md, docs/security.md and AGENTS.md first. Do not deploy or purchase resources. Build only milestone 1: a FastAPI modular monolith scaffold with SQLAlchemy/Alembic, PostgreSQL, Docker Compose for local development, typed configuration, health endpoints, pytest, Ruff, mypy, GitHub Actions and a documented tenant-aware repository abstraction. Include unit/integration tests for tenant isolation. Add ADRs for major decisions. Do not implement AI, Twilio, invoices, authentication shortcuts, or fake production secrets. Show all changed files, tests executed and unresolved risks in your final summary."

### Subsequent scoped prompts
1. "Implement Twilio webhook signature verification and idempotent durable enqueue with unit tests for valid/invalid signatures, duplicates and retries. No outgoing sends yet."
2. "Implement deterministic invoice draft domain with Decimal currency, VAT rule configuration, versioned approvals, atomic invoice numbers and tests; no AI integration."
3. "Implement Tara's structured extraction and tool-call adapter, allowing draft creation/update only; no issuing without explicit version-bound approval. Include adversarial tests."
4. "Implement secure PDF generation, blob upload, outbox delivery and failure recovery with integration tests."
5. "Implement the minimum authenticated portal and tenant onboarding with role and cross-tenant tests."

## 13. Pilot operating metrics
Measure: message processing p50/p95, Twilio send success, failed/duplicate actions, draft completion rate, invoice correction rate, unapproved issuance (must be zero), AI cost per completed invoice, support tickets per tenant, monthly infrastructure cost, customer retention, and backup restore results. Set numeric SLO targets after baseline testing, not by guessing.

## 14. Immediate decisions and dependencies
1. Twilio production WhatsApp sender approval; maintain simulator for development.
2. Azure subscription owner, budgets, region and billing alerts.
3. GitHub private organisation/repository and access for both founders; branch protection.
4. Business identity/onboarding flow and who may authorise invoice issuance.
5. Irish VAT rules, invoice fields, retention and privacy review with qualified advisers.
6. Choose managed identity provider for portal (e.g. Microsoft Entra External ID or another managed OIDC provider) after comparing pricing and complexity.
7. Decide whether the first release includes customer delivery directly or only a link returned to the tradesperson; prototype currently confirms link returned via WhatsApp.
8. Plan migration only after data mapping, checksums, reconciliations and rollback have been tested; don't copy old SharePoint data into production blindly.

## 15. Cost control
Use one region, budgets/alerts, lower-cost non-production tiers and scheduled non-prod shutdown where feasible. Model fixed managed database costs separately from usage-driven AI, Twilio/Meta, storage, queue and compute. Get live region-specific pricing before provisioning; do not rely on an unverified 50-user estimate. Keep environments separate, but use local Docker for most development to avoid always-on cloud spend.
