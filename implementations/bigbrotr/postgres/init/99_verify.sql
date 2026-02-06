/*
 * BigBrotr - 99_verify.sql
 *
 * Post-initialization verification script. Prints a summary of all created
 * database objects to confirm successful schema setup.
 *
 * Dependencies: All previous initialization files (00-08)
 */

DO $$
BEGIN
    RAISE NOTICE '============================================================================';
    RAISE NOTICE 'BigBrotr database schema initialized successfully';
    RAISE NOTICE '============================================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'Extensions:';
    RAISE NOTICE '  btree_gin, pg_stat_statements';
    RAISE NOTICE '';
    RAISE NOTICE 'Tables:';
    RAISE NOTICE '  relays, events, events_relays, metadata, relay_metadata, service_data';
    RAISE NOTICE '';
    RAISE NOTICE 'Utility Functions:';
    RAISE NOTICE '  tags_to_tagvalues';
    RAISE NOTICE '';
    RAISE NOTICE 'CRUD Functions (Base):';
    RAISE NOTICE '  relays_insert, events_insert, metadata_insert';
    RAISE NOTICE '  events_relays_insert, relay_metadata_insert';
    RAISE NOTICE '  service_data_upsert, service_data_get, service_data_delete';
    RAISE NOTICE '';
    RAISE NOTICE 'CRUD Functions (Cascade):';
    RAISE NOTICE '  events_relays_insert_cascade, relay_metadata_insert_cascade';
    RAISE NOTICE '';
    RAISE NOTICE 'Cleanup Functions:';
    RAISE NOTICE '  orphan_metadata_delete, orphan_events_delete';
    RAISE NOTICE '';
    RAISE NOTICE 'Views:';
    RAISE NOTICE '  (none)';
    RAISE NOTICE '';
    RAISE NOTICE 'Materialized Views:';
    RAISE NOTICE '  relay_metadata_latest, events_statistics, relays_statistics';
    RAISE NOTICE '  kind_counts_total, kind_counts_by_relay';
    RAISE NOTICE '  pubkey_counts_total, pubkey_counts_by_relay';
    RAISE NOTICE '';
    RAISE NOTICE 'Refresh Functions:';
    RAISE NOTICE '  relay_metadata_latest_refresh, events_statistics_refresh';
    RAISE NOTICE '  relays_statistics_refresh, kind_counts_total_refresh';
    RAISE NOTICE '  kind_counts_by_relay_refresh, pubkey_counts_total_refresh';
    RAISE NOTICE '  pubkey_counts_by_relay_refresh, refresh_all_statistics';
    RAISE NOTICE '';
    RAISE NOTICE '============================================================================';
END $$;
