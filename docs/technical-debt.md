# Technical debt register

These are the four low-severity findings from the independent review of PR #1.
They remain open in this revision; the medium-severity security corrections do
not establish their completion. Each item needs a reviewed change and evidence
against the acceptance criteria below.

## DEBT-001: Reproducible build dependencies

- **Severity:** Low. **Status:** Open. **Target:** Before production release.
- **Affected files:** `pyproject.toml`, `Dockerfile`, `uv.lock`.
- **Risk:** The Hatchling build backend has a version range outside the
  application lock. `uv sync --frozen` can still resolve different isolated build
  dependencies; those inputs also escape the locked-package audit.
- **Acceptance criteria:** Pin and constrain the backend and transitive build
  dependencies through a reviewed, reproducible build process. Demonstrate that
  clean CI/container builds use the same approved build inputs, preserve artifact
  verification, and include those inputs in vulnerability auditing.

## DEBT-002: Immutable image and CI action references

- **Severity:** Low. **Status:** Open. **Target:** Before production release.
- **Affected files:** `Dockerfile`, `compose.yaml`, `.github/workflows/ci.yml`.
- **Risk:** Mutable image and action tags can change build or CI execution inputs
  without a repository change.
- **Acceptance criteria:** Pin production base/tool images by digest and GitHub
  Actions by full commit SHA. Retain readable version annotations and establish
  reviewed automated update PRs. Rebuild and run the complete checks after an
  update; scan resulting container OS packages as well as Python dependencies.

## DEBT-003: Timestamp-trigger regression test

- **Severity:** Low. **Status:** Open. **Target:** Before production release.
- **Affected file:** `tests/integration/test_postgres_isolation.py`,
  `test_writer_update_sets_utc_timestamp`.
- **Risk:** `updated_at >= created_at` permits equality and can pass with an
  unchanged timestamp if the update trigger is absent.
- **Acceptance criteria:** Establish an older previous timestamp, update through
  the runtime role, and assert that `updated_at` advances while remaining UTC.
  Demonstrate that removing or disabling the trigger makes the regression fail.

## DEBT-004: Per-request security-metadata query cost

- **Severity:** Low. **Status:** Open. **Target:** Profile before production load
  acceptance; implement any needed optimisation before the commercial pilot.
- **Affected files:** `src/anoifig/api/dependencies.py`,
  `src/anoifig/db/session.py`, `src/anoifig/db/privileges.py`.
- **Risk:** Runtime catalogue/security checks add database round trips and
  connection occupancy to each authenticated operation. Expanded privilege
  validation can increase that cost; no load-related failure has been measured.
- **Acceptance criteria:** Measure query counts, connection occupancy and p50/p95
  latency under realistic tenant concurrency. Batch metadata checks or adopt a
  reviewed validation strategy if measurements require it. Retain fresh user,
  business, membership and role authorisation for every operation, and prove
  privilege drift still fails closed and tenant contexts never leak between
  concurrent or pooled requests.
