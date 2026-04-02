#!/bin/bash
# Grant permissions to application roles.
# Writer:    full DML + EXECUTE on data tables/functions.
# Reader:    SELECT-only access for API, DVM, and monitoring.
# Refresher: SELECT on base tables + ownership of materialized views.
# Uses ALTER DEFAULT PRIVILEGES so future objects inherit the same grants.

set -euo pipefail

WRITER_ROLE="writer"
READER_ROLE="reader"
REFRESHER_ROLE="refresher"

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

    -- Refresher: SELECT on base tables + EXECUTE on refresh functions
    -- Ownership of materialized views is required for REFRESH CONCURRENTLY
    GRANT USAGE ON SCHEMA public TO ${REFRESHER_ROLE};
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO ${REFRESHER_ROLE};
    GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO ${REFRESHER_ROLE};

    ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public
        GRANT SELECT ON TABLES TO ${REFRESHER_ROLE};
    ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public
        GRANT EXECUTE ON FUNCTIONS TO ${REFRESHER_ROLE};

    -- Materialized views: ownership required for REFRESH CONCURRENTLY
    ALTER MATERIALIZED VIEW relay_metadata_latest OWNER TO ${REFRESHER_ROLE};
    ALTER MATERIALIZED VIEW relay_software_counts OWNER TO ${REFRESHER_ROLE};
    ALTER MATERIALIZED VIEW supported_nip_counts OWNER TO ${REFRESHER_ROLE};
    ALTER MATERIALIZED VIEW daily_counts OWNER TO ${REFRESHER_ROLE};
    ALTER MATERIALIZED VIEW events_replaceable_latest OWNER TO ${REFRESHER_ROLE};
    ALTER MATERIALIZED VIEW events_addressable_latest OWNER TO ${REFRESHER_ROLE};

    -- Summary tables: DML required for incremental refresh
    GRANT INSERT, UPDATE, DELETE ON pubkey_kind_stats TO ${REFRESHER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON pubkey_relay_stats TO ${REFRESHER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON relay_kind_stats TO ${REFRESHER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON pubkey_stats TO ${REFRESHER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON kind_stats TO ${REFRESHER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON relay_stats TO ${REFRESHER_ROLE};

    -- NIP-85 tables: DML for writer, SELECT for reader (via ALL TABLES grants above)
    GRANT INSERT, UPDATE, DELETE ON nip85_pubkey_stats TO ${WRITER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON nip85_event_stats TO ${WRITER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON nip85_pubkey_stats TO ${REFRESHER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON nip85_event_stats TO ${REFRESHER_ROLE};

    -- NIP-85 functions (signature-qualified for PostgreSQL correctness)
    GRANT EXECUTE ON FUNCTION nip85_pubkey_stats_refresh(BIGINT, BIGINT) TO ${WRITER_ROLE};
    GRANT EXECUTE ON FUNCTION nip85_event_stats_refresh(BIGINT, BIGINT) TO ${WRITER_ROLE};
    GRANT EXECUTE ON FUNCTION nip85_follower_count_refresh() TO ${WRITER_ROLE};
    GRANT EXECUTE ON FUNCTION bolt11_amount_msats(TEXT) TO ${WRITER_ROLE};
    GRANT EXECUTE ON FUNCTION nip85_pubkey_stats_refresh(BIGINT, BIGINT) TO ${REFRESHER_ROLE};
    GRANT EXECUTE ON FUNCTION nip85_event_stats_refresh(BIGINT, BIGINT) TO ${REFRESHER_ROLE};
    GRANT EXECUTE ON FUNCTION nip85_follower_count_refresh() TO ${REFRESHER_ROLE};
    GRANT EXECUTE ON FUNCTION bolt11_amount_msats(TEXT) TO ${REFRESHER_ROLE};

    -- Monitoring: pg_monitor grants read access to system statistics (WAL, replication)
    GRANT pg_monitor TO ${READER_ROLE};

    DO \$\$ BEGIN RAISE NOTICE 'Grants applied: % (writer), % (reader), % (refresher)', '${WRITER_ROLE}', '${READER_ROLE}', '${REFRESHER_ROLE}'; END \$\$;
EOSQL
