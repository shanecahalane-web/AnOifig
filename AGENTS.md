# An Oifig engineering rules

Read `An_Oifig_Production_Blueprint.md` and the architecture/security ADRs in `docs/adr/` before changing boundaries.

## Architecture

- Use Python 3.13 and a typed modular monolith under `src/anoifig/`. FastAPI is the HTTP adapter; domain modules own business rules; SQLAlchemy and Alembic own PostgreSQL persistence.
- Keep identity/tenancy, businesses, and customers separate. Future conversations, invoices, messaging, and AI modules must call domain services; an AI model must never directly write database records.
- Use UUIDs, UTC-aware timestamps, explicit constraints, and `tenant_id` on tenant-owned records. Money must eventually use Decimal/NUMERIC with documented rounding.
- Apply schema changes through reviewed Alembic migrations. Do not call `create_all` at application startup or use the schema-owner account in the application.

## Security

- Verify external OIDC JWT signatures, issuer, audience, lifetime, and required claims. Never accept a phone number, user ID, tenant header, unsigned token, or development authentication bypass as proof of identity.
- Resolve active database membership for every tenant operation. Enforce roles in domain services and PostgreSQL row-level security using transaction-local identity and tenant context. Query filters alone do not establish isolation.
- Runtime database roles must be non-superuser, non-owner, and NOBYPASSRLS with narrowly scoped grants. Keep migration/bootstrap privileges separate. Test isolation with the actual runtime role and raw SQL as well as through HTTP.
- Do not commit credentials, tokens, personal data, or `.env` files. Examples must contain obvious non-production values. Never log tokens, DSNs, request bodies, or sensitive exception details.
- Preserve TLS and artifact verification. Production requires TLS to PostgreSQL and a managed identity provider. No custom passwords, implicit tenant membership, or public provisioning endpoints.
- Never deploy production, purchase/provision infrastructure, connect live Twilio/OpenAI accounts, implement invoice issuance, or merge into main without explicit task authorisation. Invoice issuance will require explicit approval of the exact draft version.

## Coding and validation

- Use small typed functions, Pydantic input validation, dependency injection, and explicit transaction boundaries. Keep HTTP errors generic and map internal errors without leaking secrets.
- Lock dependencies with `uv.lock`; use `uv sync --frozen`. Run `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`, and `uv run pytest` before opening a pull request.
- Tests must cover health behaviour, configuration validation, signed/invalid JWTs, active/revoked users and memberships, role restrictions, tenant reads/writes, missing tenant context, pooled transaction cleanup, and PostgreSQL policies/constraints. SQLite cannot validate PostgreSQL tenant isolation.
- Integration tests require dedicated disposable PostgreSQL databases and separate owner/runtime connections. Never point tests at real customer databases. CI must run the complete suite rather than silently skipping database tests.
- Document migrations, local startup, setup changes, and unresolved production decisions. Use a separate branch and a human-reviewed pull request; do not merge automatically.
