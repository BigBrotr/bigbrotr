-- ============================================================================
-- LilBrotr Database Initialization Script
-- ============================================================================
-- File: 99_verify.sql
-- Description: Verification and completion notice
-- Dependencies: All previous initialization files
-- ============================================================================

-- Verify installation
DO $$
BEGIN
    RAISE NOTICE '============================================================================';
    RAISE NOTICE 'LilBrotr database schema initialized successfully';
    RAISE NOTICE '============================================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'Extensions:';
    RAISE NOTICE '  btree_gin, pgcrypto';
    RAISE NOTICE '';
    RAISE NOTICE 'Tables:';
    RAISE NOTICE '  relays, events (tagvalues only), events_relays, metadata, relay_metadata, service_data';
    RAISE NOTICE '';
    RAISE NOTICE 'Utility Functions:';
    RAISE NOTICE '  tags_to_tagvalues';
    RAISE NOTICE '';
    RAISE NOTICE 'CRUD Functions:';
    RAISE NOTICE '  insert_event (tagvalues computed), insert_relay, insert_relay_metadata';
    RAISE NOTICE '  upsert_service_data, get_service_data, delete_service_data';
    RAISE NOTICE '';
    RAISE NOTICE 'Cleanup Functions:';
    RAISE NOTICE '  delete_orphan_metadata, delete_orphan_events, delete_failed_candidates';
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
    RAISE NOTICE '  refresh_relay_metadata_latest, refresh_events_statistics';
    RAISE NOTICE '  refresh_relays_statistics, refresh_kind_counts_total';
    RAISE NOTICE '  refresh_kind_counts_by_relay, refresh_pubkey_counts_total';
    RAISE NOTICE '  refresh_pubkey_counts_by_relay';
    RAISE NOTICE '';
    RAISE NOTICE 'Note: LilBrotr stores tagvalues (computed) but discards tags/content/sig.';
    RAISE NOTICE '      Tag-based queries via tagvalues GIN index are supported.';
    RAISE NOTICE '      Use BigBrotr for full event storage with all fields.';
    RAISE NOTICE '';
    RAISE NOTICE '============================================================================';
END $$;
