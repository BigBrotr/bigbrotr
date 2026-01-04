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


-- ----------------------------------------------------------------------------
-- failed_candidates_delete
-- Description: Removes validator candidates that exceeded max failed attempts
-- Purpose: Cleanup candidates that consistently fail validation
-- Parameters:
--   p_max_attempts: Maximum number of failed attempts before deletion
-- Returns: BIGINT (number of deleted rows)
-- Usage: SELECT failed_candidates_delete(10);
-- Notes:
--   - Candidates track failed_attempts in JSONB data field
--   - Called by Brotr.cleanup_failed_candidates()
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION failed_candidates_delete(
    p_max_attempts INTEGER
)
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    v_deleted BIGINT;
BEGIN
    DELETE FROM service_data s
    WHERE s.service_name = 'validator'
      AND s.data_type = 'candidate'
      AND (s.data->>'failed_attempts')::INTEGER >= p_max_attempts;
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$;

COMMENT ON FUNCTION failed_candidates_delete IS
'Deletes validator candidates with failed_attempts >= threshold';


-- ============================================================================
-- CLEANUP FUNCTIONS SUMMARY
-- ============================================================================
--
-- orphan_metadata_delete    : Remove unreferenced metadata records
-- orphan_events_delete      : Remove events without relay associations
-- failed_candidates_delete  : Remove failed validation candidates
--
-- Recommended schedule:
--   - orphan_metadata_delete: Daily or after bulk relay_metadata deletions
--   - orphan_events_delete: Daily or after relay deletions
--   - failed_candidates_delete: Weekly with p_max_attempts = 10
--
-- ============================================================================
