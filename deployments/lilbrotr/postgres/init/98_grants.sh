#!/bin/bash
# Grant permissions to application roles.
# Writer: full DML + EXECUTE on all tables/functions.
# Reader: SELECT-only access for API, DVM, and monitoring.
# Uses ALTER DEFAULT PRIVILEGES so future objects inherit the same grants.

set -euo pipefail

WRITER_ROLE="${POSTGRES_DB}_writer"
READER_ROLE="${POSTGRES_DB}_reader"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Writer: full DML + function execution
    GRANT USAGE ON SCHEMA public TO ${WRITER_ROLE};
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ${WRITER_ROLE};
    GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO ${WRITER_ROLE};

    ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${WRITER_ROLE};
    ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public
        GRANT EXECUTE ON FUNCTIONS TO ${WRITER_ROLE};

    -- Reader: SELECT + EXECUTE (SECURITY INVOKER ensures no privilege escalation)
    GRANT USAGE ON SCHEMA public TO ${READER_ROLE};
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO ${READER_ROLE};
    GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO ${READER_ROLE};

    ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public
        GRANT SELECT ON TABLES TO ${READER_ROLE};
    ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public
        GRANT EXECUTE ON FUNCTIONS TO ${READER_ROLE};

    -- Monitoring: pg_monitor grants read access to system statistics (WAL, replication)
    GRANT pg_monitor TO ${READER_ROLE};

    DO \$\$ BEGIN RAISE NOTICE 'Grants applied: % (writer), % (reader)', '${WRITER_ROLE}', '${READER_ROLE}'; END \$\$;
EOSQL
