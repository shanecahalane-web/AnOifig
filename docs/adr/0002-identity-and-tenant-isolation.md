# ADR 0002: Verified identity, database memberships and forced row policies

Status: accepted for Milestone 1, 14 October 2026.

## Context

A customer name, WhatsApp sender number, caller-provided tenant ID, or SQL filter
cannot establish permission to access a business. An API bug that omits a
filter must not expose other businesses' customer records. Provisioning and
migrations need greater privileges than the running application.

## Decision

Authenticate with a managed OIDC provider. Verify signed JWTs against a fixed
configured JWKS endpoint and check issuer, audience, expiry and required claims.
Never fetch signing keys from token-supplied URLs. Map the verified issuer and
subject to an active local user. Resolve an active membership and active
business for each selected tenant; roles are `owner`, `staff` and `read_only`.
Require role permission in the domain service. No phone-number authentication,
custom password system, implicit membership, or public provisioning endpoint is
provided. With a bearer token and no configured OIDC provider, protected
endpoints return 503; requests without tokens are rejected and health checks
remain available.

Use transaction-local identity and tenant settings with PostgreSQL row-level
security. All initial tables enable and force RLS. Users are readable only in
their verified identity context; businesses and memberships require matching
active identity/membership; customers require tenant and membership context with
write policies constrained to writing roles. Explicit tenant-scoped repository
queries remain useful for clarity and efficient plans. Transaction boundaries
ensure that pooled connections cannot retain tenant state across requests.

The runtime role has `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`,
`NOREPLICATION`, and `NOBYPASSRLS` and owns no schema objects. It receives SELECT
on businesses/users/memberships and only SELECT/INSERT/UPDATE/DELETE on customers.
The API receives only this role's URL. Schema owners apply migrations and
privileged operators provision reviewed identities/memberships outside the API.
Production must also restrict role memberships, public privileges and database
network access. Local initialization revokes PUBLIC access to the application
databases and schema.

## Trust boundary and limitations

The application is trusted to set verified identity and authorised tenant
context. PostgreSQL custom settings do not authenticate their writer. An attacker
with arbitrary SQL execution using the runtime credentials can forge context
and impersonate another database user. RLS is defence in depth against ordinary
application mistakes and unauthorised requests, not containment of a compromised
application or stolen runtime credentials. Connection secrets, deployment
identity, private network access, and SQL injection prevention remain essential.

Business/user/membership writes are intentionally privileged and outside the
customer API. Choose the managed identity provider and build audited provisioning
and revocation workflows before real users are onboarded. There is no platform
administrator bypass. Extend composite tenant foreign keys when future tenant
entities reference one another. Add audit trails, rate limits, abuse controls,
and independent penetration testing before a commercial pilot.

Tests must prove missing-context denial, cross-tenant read/write denial, inactive
users/memberships, read-only write rejection, RLS role attributes, and transaction
cleanup using the real runtime database role. Avoid testing solely as the owner,
which may have privileges that defeat RLS.
