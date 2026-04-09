#!/bin/bash
# Grant permissions to application roles.
# Writer:    full DML + EXECUTE on data tables/functions.
# Reader:    SELECT-only access for API, DVM, and monitoring.
# Refresher: SELECT on source tables + DML on derived tables.
# Ranker:    SELECT on canonical facts tables + DML on private rank outputs.
# Uses ALTER DEFAULT PRIVILEGES so future objects inherit the same grants.

set -euo pipefail

WRITER_ROLE="writer"
READER_ROLE="reader"
REFRESHER_ROLE="refresher"
RANKER_ROLE="ranker"

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

    -- Refresher: SELECT on source tables + EXECUTE on refresh functions
    GRANT USAGE ON SCHEMA public TO ${REFRESHER_ROLE};
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO ${REFRESHER_ROLE};
    GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO ${REFRESHER_ROLE};

    ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public
        GRANT SELECT ON TABLES TO ${REFRESHER_ROLE};
    ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public
        GRANT EXECUTE ON FUNCTIONS TO ${REFRESHER_ROLE};

    -- Ranker: read-only access to canonical follow-graph and NIP-85 facts
    GRANT USAGE ON SCHEMA public TO ${RANKER_ROLE};
    GRANT SELECT ON contact_lists_current TO ${RANKER_ROLE};
    GRANT SELECT ON contact_list_edges_current TO ${RANKER_ROLE};
    GRANT SELECT ON nip85_pubkey_stats TO ${RANKER_ROLE};
    GRANT SELECT ON nip85_event_stats TO ${RANKER_ROLE};
    GRANT SELECT ON nip85_addressable_stats TO ${RANKER_ROLE};
    GRANT SELECT ON nip85_identifier_stats TO ${RANKER_ROLE};
    GRANT SELECT, INSERT, UPDATE, DELETE ON nip85_pubkey_ranks TO ${RANKER_ROLE};

    -- Current-state tables + analytics tables: DML required for incremental refresh
    GRANT INSERT, UPDATE, DELETE ON daily_counts TO ${REFRESHER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON relay_metadata_current TO ${REFRESHER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON relay_software_counts TO ${REFRESHER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON supported_nip_counts TO ${REFRESHER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON events_replaceable_current TO ${REFRESHER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON events_addressable_current TO ${REFRESHER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON pubkey_kind_stats TO ${REFRESHER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON pubkey_relay_stats TO ${REFRESHER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON relay_kind_stats TO ${REFRESHER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON pubkey_stats TO ${REFRESHER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON kind_stats TO ${REFRESHER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON relay_stats TO ${REFRESHER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON contact_lists_current TO ${REFRESHER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON contact_list_edges_current TO ${REFRESHER_ROLE};

    -- NIP-85 tables: DML for writer, SELECT for reader (via ALL TABLES grants above)
    GRANT INSERT, UPDATE, DELETE ON nip85_pubkey_stats TO ${WRITER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON nip85_event_stats TO ${WRITER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON nip85_addressable_stats TO ${WRITER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON nip85_identifier_stats TO ${WRITER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON nip85_pubkey_stats TO ${REFRESHER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON nip85_event_stats TO ${REFRESHER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON nip85_addressable_stats TO ${REFRESHER_ROLE};
    GRANT INSERT, UPDATE, DELETE ON nip85_identifier_stats TO ${REFRESHER_ROLE};

    -- NIP-85 functions (signature-qualified for PostgreSQL correctness)
    GRANT EXECUTE ON FUNCTION nip85_pubkey_stats_refresh(BIGINT, BIGINT) TO ${WRITER_ROLE};
    GRANT EXECUTE ON FUNCTION nip85_event_stats_refresh(BIGINT, BIGINT) TO ${WRITER_ROLE};
    GRANT EXECUTE ON FUNCTION nip85_addressable_stats_refresh(BIGINT, BIGINT) TO ${WRITER_ROLE};
    GRANT EXECUTE ON FUNCTION nip85_identifier_stats_refresh(BIGINT, BIGINT) TO ${WRITER_ROLE};
    GRANT EXECUTE ON FUNCTION nip85_follower_count_refresh() TO ${WRITER_ROLE};
    GRANT EXECUTE ON FUNCTION bolt11_amount_msats(TEXT) TO ${WRITER_ROLE};
    GRANT EXECUTE ON FUNCTION daily_counts_refresh(BIGINT, BIGINT) TO ${REFRESHER_ROLE};
    GRANT EXECUTE ON FUNCTION relay_metadata_current_refresh(BIGINT, BIGINT) TO ${REFRESHER_ROLE};
    GRANT EXECUTE ON FUNCTION relay_software_counts_refresh(BIGINT, BIGINT) TO ${REFRESHER_ROLE};
    GRANT EXECUTE ON FUNCTION supported_nip_counts_refresh(BIGINT, BIGINT) TO ${REFRESHER_ROLE};
    GRANT EXECUTE ON FUNCTION events_replaceable_current_refresh(BIGINT, BIGINT) TO ${REFRESHER_ROLE};
    GRANT EXECUTE ON FUNCTION events_addressable_current_refresh(BIGINT, BIGINT) TO ${REFRESHER_ROLE};
    GRANT EXECUTE ON FUNCTION contact_lists_current_refresh(BIGINT, BIGINT) TO ${REFRESHER_ROLE};
    GRANT EXECUTE ON FUNCTION contact_list_edges_current_refresh(BIGINT, BIGINT) TO ${REFRESHER_ROLE};
    GRANT EXECUTE ON FUNCTION nip85_pubkey_stats_refresh(BIGINT, BIGINT) TO ${REFRESHER_ROLE};
    GRANT EXECUTE ON FUNCTION nip85_event_stats_refresh(BIGINT, BIGINT) TO ${REFRESHER_ROLE};
    GRANT EXECUTE ON FUNCTION nip85_addressable_stats_refresh(BIGINT, BIGINT) TO ${REFRESHER_ROLE};
    GRANT EXECUTE ON FUNCTION nip85_identifier_stats_refresh(BIGINT, BIGINT) TO ${REFRESHER_ROLE};
    GRANT EXECUTE ON FUNCTION nip85_follower_count_refresh() TO ${REFRESHER_ROLE};
    GRANT EXECUTE ON FUNCTION bolt11_amount_msats(TEXT) TO ${REFRESHER_ROLE};

    -- Monitoring: pg_monitor grants read access to system statistics (WAL, replication)
    GRANT pg_monitor TO ${READER_ROLE};

    DO \$\$ BEGIN RAISE NOTICE 'Grants applied: % (writer), % (reader), % (refresher), % (ranker)', '${WRITER_ROLE}', '${READER_ROLE}', '${REFRESHER_ROLE}', '${RANKER_ROLE}'; END \$\$;
EOSQL
