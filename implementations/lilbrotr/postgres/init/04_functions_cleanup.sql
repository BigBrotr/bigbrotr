/*
 * LilBrotr - 04_functions_cleanup.sql
 *
 * Cleanup functions that remove orphaned records to maintain data integrity.
 * These should be run periodically or after bulk deletions from parent tables.
 *
 * Dependencies: 02_tables.sql
 */


/*
 * orphan_metadata_delete() -> BIGINT
 *
 * Removes metadata records that have no references in relay_metadata.
 * This happens when old metadata snapshots are deleted but their underlying
 * content-addressed documents remain. Safe to run at any time.
 *
 * Returns: Number of deleted rows
 * Schedule: Daily, or after bulk relay_metadata deletions
 */
CREATE OR REPLACE FUNCTION orphan_metadata_delete()
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    v_deleted BIGINT;
BEGIN
    DELETE FROM metadata m
    WHERE NOT EXISTS (
        SELECT 1 FROM relay_metadata rm WHERE rm.metadata_id = m.id
    );
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$;

COMMENT ON FUNCTION orphan_metadata_delete() IS
'Delete metadata records not referenced by any relay_metadata row';


/*
 * orphan_events_delete() -> BIGINT
 *
 * Removes events that have no associated relay in events_relays. This
 * enforces the invariant that every event must be associated with at least
 * one relay. Orphans can appear when a relay is deleted via CASCADE on
 * events_relays but the event itself remains.
 *
 * Returns: Number of deleted rows
 * Schedule: Daily, or after relay deletions
 */
CREATE OR REPLACE FUNCTION orphan_events_delete()
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    v_deleted BIGINT;
BEGIN
    DELETE FROM events e
    WHERE NOT EXISTS (
        SELECT 1 FROM events_relays er WHERE er.event_id = e.id
    );
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$;

COMMENT ON FUNCTION orphan_events_delete() IS
'Delete events without any relay association (maintains 1:N invariant)';
