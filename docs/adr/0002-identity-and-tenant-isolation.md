# ADR 0002: Verified identity, database memberships and forced row policies

Status: accepted for Milestone 1, 14 October 2026.

## Context

A customer name, WhatsApp sender number, caller-provided tenant ID, or SQL filter
cannot establish permission to access a business. An API bug that omits a
filter must not expose other businesses' customer records. Provisioning and
migrations need greater privileges than the running application.

## Decision

Authenticate using a managed provider's JWT access tokens. Use a strict local
profile inspired by RFC 9068, without claiming full conformance or assuming a
provider has already been selected:

- The signature algorithm is RS256. Resolve the signing key by `kid` from the
  fixed configured JWKS endpoint; never fetch keys from token-supplied URLs.
- The protected `typ` header must be exactly `at+jwt` or `application/at+jwt`.
  Missing types and generic `JWT` tokens are rejected before key lookup.
- `iss` must exactly match the configured issuer. `aud` must be a single string
  exactly matching the dedicated API audience; audience lists are rejected.
- Require `exp`, `iat`, `sub`, `client_id`, and `jti`; validate the token's lifetime.
  `sub`, `client_id`, and `jti` must be nonblank strings of at most 255 characters.
- If the signed `token_use` claim is present, it must be exactly `access`.
  Reject signed `nonce`, `at_hash`, and `c_hash` claims, which belong to the
  ID-token profile. These checks supplement signature, type and audience checks;
  a claim supplied without a verified signature is never trusted.

ID tokens authenticate a client session; refresh tokens obtain new access tokens.
Neither is a credential for this API. No generic-JWT fallback or development
bypass is provided. A provider unable to issue this profile needs a separately
reviewed adapter rather than relaxed generic verification. Requiring `jti`
identifies a token; it does not create replay detection or a revocation store.

Map the verified issuer and subject to an active local user. Resolve an active
membership and active business for each selected tenant; roles are `owner`,
`staff` and `read_only`.
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

Validate effective privileges, including those inherited through PUBLIC, rather
than trusting that bootstrap grants remain unchanged. The runtime safety checks
reject extra table or column rights and grant options, including `TRUNCATE`,
`REFERENCES`, `TRIGGER` and PostgreSQL 17's `MAINTAIN`; `TRUNCATE` bypasses RLS.
They reject database CREATE/TEMP, public-schema CREATE, role memberships,
ownership, and privileges on unapproved public relations or sequences. The
allowed database/schema/table set is CONNECT, public-schema USAGE, SELECT on
businesses/users/memberships, and SELECT/INSERT/UPDATE/DELETE on customers, with
no grant options.

The provisioning helper checks for excess permissions before changing any grant.
It adds only missing allowed permissions and verifies the complete result in one
transaction. Unexpected privileges cause a safe failure; it never silently
revokes unknown grants or attempts to repair a misconfigured role automatically.
An authorised operator must review and explicitly correct the drift before
rerunning provisioning. New database objects need a reviewed privilege allowlist
change; see [the database runbook](../runbooks/database.md).

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

Provider selection is a deployment gate. Validate the provider's issuer, trusted
JWKS endpoint and CA trust, dedicated API audience, authorised clients, grant
types, scope policy, administrator MFA, token lifetime, revocation behavior, and
key-rotation behavior against this contract. The current verifier does not apply
a client allowlist, scope-based domain permissions, or remote introspection.
Keep business authorisation authoritative in active database memberships and
roles; do not infer membership or privileges from token claims. Document the
provider-specific decisions and exercise its real tokens in staging before
enabling production authentication.

The JWKS client currently caches the key set for 300 seconds and limits unknown
`kid` refreshes with a 30-second cooldown. Providers must prepublish replacement
keys and maintain an overlap that accounts for those caches and issued-token
lifetimes; a newly introduced key may be rejected during the cooldown. Validate
normal rotation, emergency revocation and outage behavior with the selected
provider in staging; local signing-key tests do not establish that integration.

Tests must prove missing-context denial, cross-tenant read/write denial, inactive
users/memberships, read-only write rejection, RLS role attributes, and transaction
cleanup using the real runtime database role. Avoid testing solely as the owner,
which may have privileges that defeat RLS.

Regression tests must also reject ID/refresh-token substitution, generic JWTs and
invalid access-token claims, and demonstrate that dangerous table/column grants,
PUBLIC grants, grant options and role/ownership drift cannot pass runtime checks.
