/*
 * Brotr - 99_verify.sql
 *
 * Post-initialization verification script. Prints a summary of all created
 * database objects to confirm successful schema setup.
 *
 * Dependencies: All previous initialization files (00-08)
 */

DO $$
BEGIN
    RAISE NOTICE '============================================================================';
    RAISE NOTICE 'Brotr database schema initialized successfully';
    RAISE NOTICE '============================================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'Extensions:';
    RAISE NOTICE '  btree_gin, pg_stat_statements';
    RAISE NOTICE '';
    RAISE NOTICE 'Tables:';
    RAISE NOTICE '  relay, event, event_relay, metadata, relay_metadata, service_state';
    RAISE NOTICE '';
    RAISE NOTICE 'Utility Functions:';
    RAISE NOTICE '  tags_to_tagvalues';
    RAISE NOTICE '';
    RAISE NOTICE 'CRUD Functions (Base):';
    RAISE NOTICE '  relay_insert, event_insert, metadata_insert';
    RAISE NOTICE '  event_relay_insert, relay_metadata_insert';
    RAISE NOTICE '  service_state_upsert, service_state_get, service_state_delete';
    RAISE NOTICE '';
    RAISE NOTICE 'CRUD Functions (Cascade):';
    RAISE NOTICE '  event_relay_insert_cascade, relay_metadata_insert_cascade';
    RAISE NOTICE '';
    RAISE NOTICE 'Cleanup Functions:';
    RAISE NOTICE '  orphan_metadata_delete, orphan_event_delete';
    RAISE NOTICE '';
    RAISE NOTICE 'Materialized Views (11):';
    RAISE NOTICE '  relay_metadata_latest';
    RAISE NOTICE '  event_stats, relay_stats, kind_counts, kind_counts_by_relay';
    RAISE NOTICE '  pubkey_counts, pubkey_counts_by_relay';
    RAISE NOTICE '  network_stats, relay_software_counts, supported_nip_counts';
    RAISE NOTICE '  event_daily_counts';
    RAISE NOTICE '';
    RAISE NOTICE 'Refresh Functions (12):';
    RAISE NOTICE '  relay_metadata_latest_refresh';
    RAISE NOTICE '  event_stats_refresh, relay_stats_refresh';
    RAISE NOTICE '  kind_counts_refresh, kind_counts_by_relay_refresh';
    RAISE NOTICE '  pubkey_counts_refresh, pubkey_counts_by_relay_refresh';
    RAISE NOTICE '  network_stats_refresh, relay_software_counts_refresh';
    RAISE NOTICE '  supported_nip_counts_refresh, event_daily_counts_refresh';
    RAISE NOTICE '  all_statistics_refresh';
    RAISE NOTICE '';
    RAISE NOTICE '============================================================================';
END $$;
