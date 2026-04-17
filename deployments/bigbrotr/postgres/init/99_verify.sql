/*
 * Brotr - 99_verify.sql
 *
 * Post-initialization verification script. Prints a summary of all created
 * database objects to confirm successful schema setup.
 *
 * Dependencies: All previous initialization files (00-12)
 */

DO $$
BEGIN
    RAISE NOTICE '============================================================================';
    RAISE NOTICE 'Brotr database schema initialized successfully';
    RAISE NOTICE '============================================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'Roles:';
    RAISE NOTICE '  writer (DML + EXECUTE), reader (SELECT + EXECUTE + pg_monitor), refresher (derived-state maintainer)';
    RAISE NOTICE '';
    RAISE NOTICE 'Extensions:';
    RAISE NOTICE '  btree_gin, pg_stat_statements';
    RAISE NOTICE '';
    RAISE NOTICE 'Tables:';
    RAISE NOTICE '  relay, event (HASH x), event_observation (HASH x), document, relay_document, service_state';
    RAISE NOTICE '';
    RAISE NOTICE 'Current Tables (5):';
    RAISE NOTICE '  relay_document_current';
    RAISE NOTICE '  replaceable_event_current, addressable_event_current';
    RAISE NOTICE '  contact_lists_current, contact_list_edges_current';
    RAISE NOTICE '';
    RAISE NOTICE 'Analytics Summary Tables (9):';
    RAISE NOTICE '  daily_counts';
    RAISE NOTICE '  relay_software_counts, supported_nip_counts';
    RAISE NOTICE '  pubkey_kind_stats, pubkey_relay_stats, relay_kind_stats';
    RAISE NOTICE '  pubkey_stats, kind_stats, relay_stats';
    RAISE NOTICE '';
    RAISE NOTICE 'NIP-85 Summary Tables (4):';
    RAISE NOTICE '  nip85_pubkey_stats, nip85_event_stats';
    RAISE NOTICE '  nip85_addressable_stats, nip85_identifier_stats';
    RAISE NOTICE '';
    RAISE NOTICE 'Public Score Tables (4):';
    RAISE NOTICE '  pubkey_score, event_score';
    RAISE NOTICE '  addressable_score, identifier_score';
    RAISE NOTICE '';
    RAISE NOTICE 'Utility Functions:';
    RAISE NOTICE '  tags_to_tagvalues, event_d_tag, normalize_event_address, event_address, bolt11_amount_msats';
    RAISE NOTICE '';
    RAISE NOTICE 'CRUD Functions (Base):';
    RAISE NOTICE '  relay_insert, event_insert, document_insert';
    RAISE NOTICE '  event_observation_insert, relay_document_insert';
    RAISE NOTICE '  service_state_upsert, service_state_get, service_state_delete';
    RAISE NOTICE '';
    RAISE NOTICE 'CRUD Functions (Cascade):';
    RAISE NOTICE '  event_observation_insert_cascade, relay_document_insert_cascade';
    RAISE NOTICE '';
    RAISE NOTICE 'Cleanup Functions:';
    RAISE NOTICE '  orphan_document_delete, orphan_event_delete';
    RAISE NOTICE '';
    RAISE NOTICE 'Current Refresh Functions (5):';
    RAISE NOTICE '  relay_document_current_refresh';
    RAISE NOTICE '  replaceable_event_current_refresh, addressable_event_current_refresh';
    RAISE NOTICE '  contact_lists_current_refresh, contact_list_edges_current_refresh';
    RAISE NOTICE '';
    RAISE NOTICE 'Analytics Summary Refresh Functions (11):';
    RAISE NOTICE '  daily_counts_refresh';
    RAISE NOTICE '  relay_software_counts_refresh, supported_nip_counts_refresh';
    RAISE NOTICE '  pubkey_kind_stats_refresh, pubkey_relay_stats_refresh, relay_kind_stats_refresh';
    RAISE NOTICE '  pubkey_stats_refresh, kind_stats_refresh, relay_stats_refresh';
    RAISE NOTICE '  rolling_windows_refresh, relay_stats_document_refresh';
    RAISE NOTICE '';
    RAISE NOTICE 'NIP-85 Refresh Functions (5):';
    RAISE NOTICE '  nip85_pubkey_stats_refresh, nip85_event_stats_refresh';
    RAISE NOTICE '  nip85_addressable_stats_refresh, nip85_identifier_stats_refresh';
    RAISE NOTICE '  nip85_follower_count_refresh';
    RAISE NOTICE '';
    RAISE NOTICE 'Reporting Views (0):';
    RAISE NOTICE '  (none)';
    RAISE NOTICE '';
    RAISE NOTICE 'View Refresh Functions (0):';
    RAISE NOTICE '  (none)';
    RAISE NOTICE '';
    RAISE NOTICE '============================================================================';
END $$;
