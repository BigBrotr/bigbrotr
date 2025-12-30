-- ============================================================================
-- BigBrotr Database Initialization Script
-- ============================================================================
-- File: 99_verify.sql
-- Description: Verification and completion notice
-- Dependencies: All previous initialization files
-- ============================================================================

-- Verify installation
DO $$
BEGIN
    RAISE NOTICE '============================================================================';
    RAISE NOTICE 'BigBrotr database schema initialized successfully';
    RAISE NOTICE '============================================================================';
    RAISE NOTICE 'Core tables: relays, events, events_relays, metadata, relay_metadata';
    RAISE NOTICE 'Service table: service_data';
    RAISE NOTICE 'Utility functions: tags_to_tagvalues';
    RAISE NOTICE 'Integrity functions: delete_orphan_metadata, delete_orphan_events';
    RAISE NOTICE '                     delete_failed_candidates';
    RAISE NOTICE 'Procedures: insert_event, insert_relay, insert_relay_metadata';
    RAISE NOTICE '            upsert_service_data, delete_service_data';
    RAISE NOTICE 'Materialized views: relay_metadata_latest, events_statistics';
    RAISE NOTICE '                    relays_statistics, kind_counts_total';
    RAISE NOTICE '                    kind_counts_by_relay, pubkey_counts_total';
    RAISE NOTICE '                    pubkey_counts_by_relay';
    RAISE NOTICE 'Extensions: btree_gin, pgcrypto';
    RAISE NOTICE '============================================================================';
END $$;