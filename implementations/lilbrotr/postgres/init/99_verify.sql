-- ============================================================================
-- LilBrotr Database Initialization Script
-- ============================================================================
-- File: 99_verify.sql
-- Description: Verification and completion notice
-- Note: LilBrotr is a lightweight implementation that does not store tags/content
-- Dependencies: All previous initialization files
-- ============================================================================

-- Verify installation
DO $$
BEGIN
    RAISE NOTICE '============================================================================';
    RAISE NOTICE 'LilBrotr database schema initialized successfully';
    RAISE NOTICE '============================================================================';
    RAISE NOTICE 'Note: LilBrotr does NOT store tags or content (lightweight mode)';
    RAISE NOTICE '============================================================================';
    RAISE NOTICE 'Core tables: relays, events (no tags/content), events_relays';
    RAISE NOTICE 'Metadata tables: nip11, nip66, relay_metadata';
    RAISE NOTICE 'Hash functions: compute_nip11_hash, compute_nip66_hash';
    RAISE NOTICE 'Utility functions: delete_orphan_events, delete_orphan_nip11';
    RAISE NOTICE '                   delete_orphan_nip66';
    RAISE NOTICE 'Procedures: insert_event (tags/content ignored), insert_relay';
    RAISE NOTICE '            insert_relay_metadata';
    RAISE NOTICE 'Views: relay_metadata_latest, events_statistics, relays_statistics';
    RAISE NOTICE '       kind_counts_total, kind_counts_by_relay';
    RAISE NOTICE '       pubkey_counts_total, pubkey_counts_by_relay';
    RAISE NOTICE '============================================================================';
END $$;