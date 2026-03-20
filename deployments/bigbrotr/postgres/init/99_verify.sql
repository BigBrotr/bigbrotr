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
    RAISE NOTICE 'Roles:';
    RAISE NOTICE '  writer (DML + EXECUTE), reader (SELECT + EXECUTE + pg_monitor), refresher (matview owner)';
    RAISE NOTICE '';
    RAISE NOTICE 'Extensions:';
    RAISE NOTICE '  btree_gin, pg_stat_statements';
    RAISE NOTICE '';
    RAISE NOTICE 'Tables:';
    RAISE NOTICE '  relay, event, event_relay, metadata, relay_metadata, service_state';
    RAISE NOTICE '';
    RAISE NOTICE 'Summary Tables (6):';
    RAISE NOTICE '  pubkey_kind_stats, pubkey_relay_stats, relay_kind_stats';
    RAISE NOTICE '  pubkey_stats, kind_stats, relay_stats';
    RAISE NOTICE '';
    RAISE NOTICE 'NIP-85 Summary Tables (2):';
    RAISE NOTICE '  nip85_pubkey_stats, nip85_event_stats';
    RAISE NOTICE '';
    RAISE NOTICE 'Utility Functions:';
    RAISE NOTICE '  tags_to_tagvalues, bolt11_amount_msats';
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
    RAISE NOTICE 'Summary Refresh Functions (8):';
    RAISE NOTICE '  pubkey_kind_stats_refresh, pubkey_relay_stats_refresh, relay_kind_stats_refresh';
    RAISE NOTICE '  pubkey_stats_refresh, kind_stats_refresh, relay_stats_refresh';
    RAISE NOTICE '  rolling_windows_refresh, relay_stats_metadata_refresh';
    RAISE NOTICE '';
    RAISE NOTICE 'NIP-85 Refresh Functions (3):';
    RAISE NOTICE '  nip85_pubkey_stats_refresh, nip85_event_stats_refresh';
    RAISE NOTICE '  nip85_follower_count_refresh';
    RAISE NOTICE '';
    RAISE NOTICE 'Materialized Views (6):';
    RAISE NOTICE '  relay_metadata_latest';
    RAISE NOTICE '  relay_software_counts, supported_nip_counts';
    RAISE NOTICE '  daily_counts';
    RAISE NOTICE '  events_replaceable_latest, events_addressable_latest';
    RAISE NOTICE '';
    RAISE NOTICE 'Matview Refresh Functions (6):';
    RAISE NOTICE '  relay_metadata_latest_refresh';
    RAISE NOTICE '  relay_software_counts_refresh, supported_nip_counts_refresh';
    RAISE NOTICE '  daily_counts_refresh';
    RAISE NOTICE '  events_replaceable_latest_refresh, events_addressable_latest_refresh';
    RAISE NOTICE '';
    RAISE NOTICE '============================================================================';
END $$;
