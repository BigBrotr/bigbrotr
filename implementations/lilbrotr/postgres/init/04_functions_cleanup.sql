-- ============================================================================
-- LilBrotr Database Initialization Script
-- ============================================================================
-- File: 04_functions_cleanup.sql
-- Description: Cleanup Functions for data integrity and maintenance
-- Dependencies: 02_tables.sql
-- ============================================================================

-- Function: orphan_metadata_delete
-- Description: Removes metadata records that are not referenced by any relay_metadata
-- Purpose: Cleanup unused metadata data after old snapshots are removed
-- Returns: BIGINT (number of deleted rows)
-- Usage: SELECT orphan_metadata_delete();
-- Note: Should be called after cleanup_old_metadata_snapshots
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

COMMENT ON FUNCTION orphan_metadata_delete() IS 'Deletes metadata records without relay_metadata references';

-- Function: orphan_events_delete
-- Description: Removes events that have no associated relay references
-- Purpose: Maintains data integrity constraint (events must have >=1 relay)
-- Returns: BIGINT (number of deleted rows)
-- Usage: SELECT orphan_events_delete();
-- Note: Should be called after relay deletion or cleanup operations
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

COMMENT ON FUNCTION orphan_events_delete() IS 'Deletes events without relay associations (maintains 1:N relationship)';

-- Function: failed_candidates_delete
-- Description: Removes validator candidates that have exceeded max failed attempts
-- Purpose: Cleanup maintenance for candidates that consistently fail validation
-- Parameters:
--   p_max_attempts: Maximum number of failed attempts before deletion
-- Returns: BIGINT (number of deleted rows)
-- Usage: SELECT failed_candidates_delete(10);
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

COMMENT ON FUNCTION failed_candidates_delete IS 'Deletes validator candidates with failed_attempts >= threshold.';

-- ============================================================================
-- CLEANUP FUNCTIONS CREATED
-- ============================================================================
