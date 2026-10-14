# ADR 0001: Typed modular monolith with a PostgreSQL foundation

Status: accepted for Milestone 1, 14 October 2026.

## Context

The production blueprint proposes an API and worker sharing business rules.
Milestone 1 needs a maintainable backend, deterministic local startup, and real
PostgreSQL tests before messaging, AI, and invoice functionality are introduced.

## Decision

Use Python 3.13 with a `src/anoifig` package and explicit module boundaries.
FastAPI adapts HTTP; identity code verifies authentication; customer domain
services authorise operations; repositories handle SQLAlchemy persistence.
Database infrastructure owns connections and transaction context. Businesses,
users, memberships and customers are the initial entities. UUIDs identify
records, timestamps are timezone-aware UTC, and constraints enforce required
names and valid membership roles.

The blueprint's `apps/` and `packages/` layout is deferred until there are
independently runnable API/worker/web components. The single package preserves
their intended boundaries while avoiding duplicate packaging and import paths.
New modules for invoices, conversations, messaging, and AI must depend on domain
service contracts rather than API handlers or unrestricted database sessions.

Use SQLAlchemy 2 and reviewed Alembic migrations. Application startup never
creates tables or applies migrations. Local Compose runs migration/grant setup
as a separate one-shot service, and the API waits for success. Production
migrations must run through an explicitly reviewed release operation with a
separate owner role. Docker uses a non-root API user. `uv.lock` fixes application
dependency resolution; development and production share the locked runtime
dependencies, with developer tools excluded from the runtime image. Isolated
build dependencies and mutable image/action references remain open
[technical debt](../technical-debt.md); they are not covered by that lock.

CI uses PostgreSQL 17 with separate owner and application identities. Unit tests
exercise pure behaviour; integration tests apply actual migrations and policies.
SQLite cannot establish the correctness of PostgreSQL RLS and is not used as an
integration substitute.

## Consequences

The initial backend can evolve into the planned shared API/worker system without
network boundaries between domain services. Database upgrades and policy changes
remain reviewable. Owner credentials are needed for migration/provisioning but
never enter the API container. Disposable local/CI passwords are documented and
have no access outside their local instance.

This milestone does not implement worker processes, invoices, messaging, AI,
Azure provisioning, or deployment. Dependency and container versions should be
updated through reviewed changes that rerun the full test suite.
