# ADR 0003: One production PostgreSQL transport policy

Status: accepted for Milestone 1, 14 October 2026.

## Context

Migration and grant operations use more privileged database credentials than the
API. Requiring verified TLS only for runtime settings leaves those credentials
and operations dependent on separately remembered deployment conventions. A
connection URL can also contain overrides that undermine an apparent hostname or
allow another transport to take precedence.

## Decision

Use the shared `db.connection_config` policy for application, Alembic, and grant
helper connections. Each production process must explicitly receive
`ANOIFIG_ENVIRONMENT=production` in its process environment. Only `development`,
`test`, and `production` are valid; unknown values fail validation. Defaults
remain suitable for local development, so release configuration must explicitly
select production for every process rather than relying on a default.

Every production database URL must:

- Use `postgresql+psycopg`, specify a database name, and identify a single TCP DNS
  hostname or IP address with a valid port when supplied. The server certificate
  must match that hostname or IP address.
- Set `sslmode=verify-full` and an explicit nonblank `sslrootcert` path. The
  trusted CA bundle must be mounted in the process that opens the connection;
  certificate and hostname verification remain the driver's responsibility and
  must succeed before database operations run.
- Avoid repeated URL query keys and query overrides for `host`, `hostaddr`,
  `port`, `service`, `servicefile`, `dbname`, `database`, `user`, or `password`.
  Ambiguous multi-host and Unix-socket configurations are rejected.
- Omit `gssencmode` or set it to `disable`. Production connectors explicitly send
  `gssencmode=disable`, preventing GSS encryption from replacing the required TLS
  transport.

After connecting and before application operations, migration DDL, or grants,
verify `pg_stat_ssl.ssl` for the current backend. A false or absent result fails
closed. This check confirms actual TLS use; the validated `verify-full` setting
and trusted CA establish server authentication.

The API receives `ANOIFIG_DATABASE_URL` for the restricted runtime role. The
reviewed release/migration process separately receives
`ANOIFIG_MIGRATION_DATABASE_URL` for the owner role. The grant helper additionally
needs the runtime URL to identify the intended role. Never give the application
the owner secret. Alembic and the grant helper read exported process environment
variables; neither loads `.env` files on its own.

## Consequences and deployment gate

Disposable local development and CI remain plaintext on their isolated database
networks. `.env.example` contains local-only credentials and must not become a
production configuration. Compose is not a production release procedure.

Before production, review both owner and runtime URLs, the database hostname,
trusted server CA, mounted certificate paths, rotation, private access, and secret
delivery. Confirm successful certificate-verified connections from each process
and rejection of untrusted certificates or mismatched hostnames in staging.
Do not work around failures by selecting `development`, relaxing `sslmode`, or
disabling certificate verification. No cloud database or paid service is created
by this decision.

Regression tests must cover insecure production URL modes, missing/ambiguous
hostnames, CA configuration, parameter overrides, unknown environments, and the
established-session check in the application, migration, and grant paths.
