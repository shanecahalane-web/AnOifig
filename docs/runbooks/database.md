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
the application's table permissions. The local PostgreSQL owner is a superuser
for cluster initialization and disposable test setup. A production migration
role should own its schema without unnecessary cluster-level privileges; the
runtime role must always remain non-owner and unable to bypass RLS.

Never grant runtime users membership in an owner, superuser or BYPASSRLS role.
Do not grant CREATE on the application schema or broad default table privileges.
Future tables need reviewed grants and RLS policies before the API can use them.

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
