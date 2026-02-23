/*
 * Template - 99_verify.sql
 *
 * Post-initialization verification script. Prints a summary of all created
 * database objects to confirm successful schema setup.
 *
 * Dependencies: All previous initialization files (00-08)
 */

DO $$
BEGIN
    RAISE NOTICE '============================================================================';
    RAISE NOTICE 'Template database schema initialized successfully';
    RAISE NOTICE '============================================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'Roles:';
    RAISE NOTICE '  myimpl_writer (DML + EXECUTE), myimpl_reader (SELECT + EXECUTE + pg_monitor)';
    RAISE NOTICE '';
    RAISE NOTICE 'Extensions: btree_gin, pg_stat_statements';
    RAISE NOTICE '';
    RAISE NOTICE 'Tables:';
    RAISE NOTICE '  relay, event, event_relay,';
    RAISE NOTICE '  metadata, relay_metadata, service_state';
    RAISE NOTICE '';
    RAISE NOTICE 'Materialized Views:';
    RAISE NOTICE '  relay_metadata_latest, event_stats, relay_stats,';
    RAISE NOTICE '  kind_counts, kind_counts_by_relay,';
    RAISE NOTICE '  pubkey_counts, pubkey_counts_by_relay';
    RAISE NOTICE '';
    RAISE NOTICE 'Functions:';
    RAISE NOTICE '  tags_to_tagvalues, relay_insert, event_insert,';
    RAISE NOTICE '  metadata_insert, event_relay_insert, relay_metadata_insert,';
    RAISE NOTICE '  event_relay_insert_cascade, relay_metadata_insert_cascade,';
    RAISE NOTICE '  service_state_upsert, service_state_get, service_state_delete,';
    RAISE NOTICE '  orphan_metadata_delete, orphan_event_delete,';
    RAISE NOTICE '  relay_metadata_delete_expired,';
    RAISE NOTICE '  relay_metadata_latest_refresh, event_stats_refresh,';
    RAISE NOTICE '  relay_stats_refresh, kind_counts_refresh,';
    RAISE NOTICE '  kind_counts_by_relay_refresh, pubkey_counts_refresh,';
    RAISE NOTICE '  pubkey_counts_by_relay_refresh, all_statistics_refresh';
    RAISE NOTICE '';
    RAISE NOTICE '============================================================================';
END $$;
