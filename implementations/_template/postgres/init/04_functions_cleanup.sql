-- ============================================================================
-- BigBrotr Implementation Template - Cleanup Functions
-- ============================================================================
-- File: 04_functions_cleanup.sql
-- Purpose: Database cleanup functions for data integrity and maintenance
-- Dependencies: 02_tables.sql
-- Customization: None - these functions are mandatory
-- ============================================================================
--
-- These functions maintain data integrity by removing orphaned records.
-- Called by Brotr.cleanup_orphan_*() methods and scheduled maintenance jobs.
--
-- ============================================================================


-- ----------------------------------------------------------------------------
-- orphan_metadata_delete
-- Description: Removes metadata records not referenced by any relay_metadata
-- Purpose: Cleanup unused metadata after old snapshots are deleted
-- Returns: BIGINT (number of deleted rows)
-- Usage: SELECT orphan_metadata_delete();
-- Notes:
--   - Safe to run anytime (no side effects on valid data)
--   - Should be called periodically or after bulk deletions
--   - Called by Brotr.cleanup_orphan_metadata()
-- ----------------------------------------------------------------------------
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
'Deletes metadata records without relay_metadata references';


-- ----------------------------------------------------------------------------
-- orphan_events_delete
-- Description: Removes events that have no associated relay references
-- Purpose: Maintains data integrity (events must have >= 1 relay association)
-- Returns: BIGINT (number of deleted rows)
-- Usage: SELECT orphan_events_delete();
-- Notes:
--   - Ensures every event is associated with at least one relay
--   - Should be called after relay deletions
--   - Called by Brotr.cleanup_orphan_events()
-- ----------------------------------------------------------------------------
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
'Deletes events without relay associations (maintains 1:N relationship)';


-- ============================================================================
-- CLEANUP FUNCTIONS SUMMARY
-- ============================================================================
--
-- orphan_metadata_delete    : Remove unreferenced metadata records
-- orphan_events_delete      : Remove events without relay associations
--
-- Recommended schedule:
--   - orphan_metadata_delete: Daily or after bulk relay_metadata deletions
--   - orphan_events_delete: Daily or after relay deletions
--
-- ============================================================================
