#!/bin/bash
# Create application database roles (writer + reader + refresher).
# Idempotent: skips creation if roles already exist.

set -euo pipefail

WRITER_ROLE="writer"
READER_ROLE="reader"
REFRESHER_ROLE="refresher"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${WRITER_ROLE}') THEN
            CREATE ROLE ${WRITER_ROLE} LOGIN PASSWORD '${DB_WRITER_PASSWORD}';
            RAISE NOTICE 'Created role: ${WRITER_ROLE}';
        ELSE
            RAISE NOTICE 'Role already exists: ${WRITER_ROLE}';
        END IF;

        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${READER_ROLE}') THEN
            CREATE ROLE ${READER_ROLE} LOGIN PASSWORD '${DB_READER_PASSWORD}';
            RAISE NOTICE 'Created role: ${READER_ROLE}';
        ELSE
            RAISE NOTICE 'Role already exists: ${READER_ROLE}';
        END IF;

        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${REFRESHER_ROLE}') THEN
            CREATE ROLE ${REFRESHER_ROLE} LOGIN PASSWORD '${DB_REFRESHER_PASSWORD}';
            RAISE NOTICE 'Created role: ${REFRESHER_ROLE}';
        ELSE
            RAISE NOTICE 'Role already exists: ${REFRESHER_ROLE}';
        END IF;
    END \$\$;
EOSQL
