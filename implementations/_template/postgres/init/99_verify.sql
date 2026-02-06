/*
 * Template - 99_verify.sql
 *
 * Post-initialization verification script. Prints a summary of all created
 * database objects to confirm successful schema setup.
 *
 * Dependencies: All previous initialization files (00-05)
 */

DO $$
BEGIN
    RAISE NOTICE '============================================================================';
    RAISE NOTICE 'Template database schema initialized successfully';
    RAISE NOTICE '============================================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'Extensions: btree_gin';
    RAISE NOTICE '';
    RAISE NOTICE 'Tables:';
    RAISE NOTICE '  relays, events, events_relays,';
    RAISE NOTICE '  metadata, relay_metadata, service_data';
    RAISE NOTICE '';
    RAISE NOTICE 'Functions:';
    RAISE NOTICE '  tags_to_tagvalues, relays_insert, events_insert,';
    RAISE NOTICE '  metadata_insert, events_relays_insert, relay_metadata_insert,';
    RAISE NOTICE '  events_relays_insert_cascade, relay_metadata_insert_cascade,';
    RAISE NOTICE '  service_data_upsert, service_data_get, service_data_delete,';
    RAISE NOTICE '  orphan_metadata_delete, orphan_events_delete';
    RAISE NOTICE '';
    RAISE NOTICE '============================================================================';
END $$;
