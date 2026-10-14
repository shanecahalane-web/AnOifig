#!/bin/sh
# Used only with a fresh local/CI database cluster. PostgreSQL runs this as owner.
set -eu
: "${POSTGRES_USER:=postgres}"
: "${POSTGRES_DB:=anoifig}"
: "${ANOIFIG_APP_PASSWORD:?Set the disposable local/CI application role password}"

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    --set=ON_ERROR_STOP=1 --set=app_password="$ANOIFIG_APP_PASSWORD" <<'SQL'
SELECT format(
    'CREATE ROLE anoifig_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L',
    :'app_password'
) \gexec
REVOKE ALL ON DATABASE anoifig FROM PUBLIC;
GRANT CONNECT ON DATABASE anoifig TO anoifig_app;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO anoifig_app;
CREATE DATABASE anoifig_test;
REVOKE ALL ON DATABASE anoifig_test FROM PUBLIC;
GRANT CONNECT ON DATABASE anoifig_test TO anoifig_app;
\connect anoifig_test
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO anoifig_app;
SQL
