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
    RAISE NOTICE 'Core tables: relays, events, events_relays';
    RAISE NOTICE 'Metadata tables: nip11, nip66, relay_metadata';
    RAISE NOTICE 'Hash functions: compute_nip11_hash, compute_nip66_hash';
    RAISE NOTICE 'Utility functions: tags_to_tagvalues, delete_orphan_*';
    RAISE NOTICE 'Procedures: insert_event, insert_relay, insert_relay_metadata';
    RAISE NOTICE 'Views: relay_metadata_latest, readable_relays, relay_last_event_timestamp';
    RAISE NOTICE '============================================================================';
END $$;