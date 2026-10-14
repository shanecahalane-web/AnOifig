# Local database operations

This runbook applies to disposable development and CI databases. Production
requires a reviewed migration plan, backup/restore validation, separately managed
credentials, private access and certificate-verified TLS.

## Initialisation and credentials

`scripts/postgres/init-postgres.sh` is mounted into the official PostgreSQL
image's initialization directory. It runs on a new volume, creates the limited
`anoifig_app` role and dedicated `anoifig_test` database, revokes PUBLIC database
and schema access, and grants only connection/schema usage. SQL passwords are
quoted through PostgreSQL's `format(... %L ...)`; they are never interpolated
into executable SQL by the shell.

Compose's separate migration service uses the local owner account to apply
Alembic and run `scripts/grant_runtime.py`. The helper verifies that the runtime
role is distinct, unprivileged and does not own schema objects before granting
the application's table permissions. It also rejects unexpected effective
privileges, including PUBLIC grants, table/column grant options, and `TRUNCATE`.
The local PostgreSQL owner is a superuser for cluster initialization and
disposable test setup. A production migration
role should own its schema without unnecessary cluster-level privileges; the
runtime role must always remain non-owner and unable to bypass RLS.

Never grant runtime users membership in an owner, superuser or BYPASSRLS role.
Do not grant CREATE on the application schema or broad default table privileges.
Future tables need reviewed grants and RLS policies before the API can use them.

## Runtime privilege drift

The approved database/schema/table permissions are CONNECT, USAGE on `public`,
SELECT on `businesses`, `users`, and `memberships`, and
SELECT/INSERT/UPDATE/DELETE on `customers`. No grant options are allowed. The
validator rejects extra table and column rights (including `TRUNCATE`,
`REFERENCES`, `TRIGGER`, and `MAINTAIN`), database CREATE/TEMP, public-schema
CREATE, role memberships, privileged role attributes, ownership, and privileges
on unapproved public relations or sequences. Grants inherited through PUBLIC
count as effective privileges and can invalidate an otherwise limited role.

The runtime check and readiness endpoint fail closed on drift. The grant helper
first checks this complete privilege boundary while allowing missing approved
grants. Only after that succeeds does it add missing permissions and perform a
strict postcheck, within the same transaction. Any error rolls back that
transaction. It deliberately **does not revoke unknown grants automatically**;
changing an unexpected privilege can affect another deployment or mask an
unauthorised administrative change.

When provisioning or readiness reports unsafe permissions:

1. Keep the API unavailable; do not switch it to an owner role or disable checks.
2. With an authorised administrative connection, inspect the runtime role's
   attributes, memberships and object ownership, along with database, public
   schema, table and column ACLs. Include PUBLIC rights; direct role grants alone
   do not establish the effective privilege set. `psql` inspection commands
   `\du+`, `\l+`, `\dn+`, and `\dp public.*` are useful starting points.
3. Investigate the source of drift and review the narrowly scoped corrective
   revocations or ownership changes. Apply only the approved changes through
   that administrative connection; preserve unrelated grants and user data.
4. Rerun `scripts/grant_runtime.py` with the reviewed runtime and migration URLs,
   then verify API readiness and the relevant isolation tests in staging.

Missing approved permissions can be restored by rerunning the grant helper.
Adding a table or changing a privilege needs a reviewed allowlist and policy
change; do not resolve a failure with broad default privileges or `GRANT ALL`.

## Container builds on a network with a custom CA

A development proxy may issue certificates using an organisation-specific CA.
If a container dependency download fails with `UnknownIssuer`, obtain the
approved complete PEM CA bundle from your environment administrator. Do not
disable TLS verification. Supply the bundle as an optional BuildKit secret:

```sh
export ANOIFIG_BUILD_CA_FILE=/path/to/approved-complete-ca-bundle.pem
docker compose -f compose.yaml -f compose.build-ca.yaml up --build -d
docker compose -f compose.yaml -f compose.build-ca.yaml --profile test run --build --rm tests
```

The secret temporarily mounts the trusted bundle at the container system trust
path only while `uv` installs locked dependencies using system certificate
verification. It is not copied into the image or repository. Normal builds use
the base image's CA bundle. Runtime OIDC/database trust configuration is separate
and must use the production identity provider and database CA authorities.

## Apply a migration locally

```sh
docker compose up -d postgres
docker compose run --rm migrate
docker compose up -d api
```

For host execution, review and export the private `.env` values, then run:

```sh
set -a
. ./.env
set +a
uv run --frozen alembic upgrade head
uv run --frozen python scripts/grant_runtime.py
```

Review generated migrations before committing. Do not modify previously applied
migrations in a shared database. The initial migration supports downgrade for
disposable verification; downgrading removes application tables and their data.
Never execute it against customer data as an informal rollback.

## Production database transport

The commands above are for local development. A production release must supply
`ANOIFIG_ENVIRONMENT=production` explicitly to **each** application, Alembic, and
grant process. The application uses `ANOIFIG_DATABASE_URL`; Alembic uses
`ANOIFIG_MIGRATION_DATABASE_URL`; the grant helper needs both. Keep owner
credentials in the reviewed release process, never in the application container.
Migration and grant commands read exported process variables and do not load
`.env` files themselves. Production secrets belong in the approved secret-delivery
system, not shell history, committed files, logs, or command-line arguments.

Use `postgresql+psycopg` URLs with an explicit database name and a single TCP DNS
hostname or IP address. Both runtime and owner URLs must set
`sslmode=verify-full` and `sslrootcert` to the trusted CA bundle mounted for that
process. The database certificate must match the configured hostname/IP. Query
overrides for connection identity/host/service, duplicate query parameters,
Unix-socket/multi-host ambiguity and alternative GSS transport are rejected.
Production connectors force `gssencmode=disable` and verify actual TLS use through
`pg_stat_ssl` before application operations, migration DDL, or grants.

Before a release, validate the server hostname, CA source, mount permissions,
certificate rotation and private network access for both owner and runtime
processes. Exercise successful connections and rejection of untrusted or
wrong-hostname certificates in staging. A TLS failure is a release blocker;
never relax `sslmode`, disable verification, or select `development` to bypass it.
See [ADR 0003](../adr/0003-production-database-tls.md).

## Provision identity and membership

Use an authorised owner connection outside the API. Create a business and a user
mapped to the exact trusted OIDC issuer/subject, then add an active membership
using the `owner`, `staff`, or `read_only` role. SQLAlchemy UUID defaults run in
Python; direct SQL provisioning must supply UUID primary keys explicitly.
Review issuer/subject values and the selected business before granting access.
Do not infer membership from phone numbers or email matches.

This milestone intentionally lacks a public registration/admin API. An audited
provisioning workflow and its authority model are outstanding product decisions.
Deactivating a user, business, or membership removes access on subsequent
authorisation checks. Never expose migration credentials to an application user.

## Tests and troubleshooting

```sh
docker compose --profile test run --build --rm tests
docker compose logs postgres migrate api
```

Tests require distinct runtime/admin URLs for the same disposable database ending
in `_test`. Fixtures migrate and reset synthetic data in that database. Do not run
concurrent suites against the same database unless isolation has been arranged.

A connection error may mean PostgreSQL is not healthy or `.env` passwords differ
from the initialized role passwords. A migration error stops API startup; inspect
the migration logs and correct the prerequisite before retrying. RLS denials are
expected without authenticated identity and tenant transaction context. Never
resolve an RLS error by giving the API an owner URL or disabling policies.

## Destructive disposable reset

First confirm that the local Compose volume contains only expendable development
records. This command deletes both development and test databases permanently:

```sh
docker compose down --volumes
docker compose up --build -d
```

For data you need to retain, rotate role passwords through an authorised database
operation and update local configuration instead. Never treat this reset as a
production recovery procedure.
