-- ============================================================================
-- BigBrotr Database Initialization Script
-- ============================================================================
-- File: 05_integrity_functions.sql
-- Description: Data integrity and cleanup functions
-- Dependencies: 02_tables.sql
-- ============================================================================

-- Function: delete_orphan_metadata
-- Description: Removes metadata records that are not referenced by any relay_metadata
-- Purpose: Cleanup unused metadata data after old snapshots are removed
-- Returns: BIGINT (number of deleted rows)
-- Usage: SELECT delete_orphan_metadata();
-- Note: Should be called after cleanup_old_metadata_snapshots
CREATE OR REPLACE FUNCTION delete_orphan_metadata()
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

COMMENT ON FUNCTION delete_orphan_metadata() IS 'Deletes metadata records without relay_metadata references';

-- Function: delete_orphan_events
-- Description: Removes events that have no associated relay references
-- Purpose: Maintains data integrity constraint (events must have ≥1 relay)
-- Returns: BIGINT (number of deleted rows)
-- Usage: SELECT delete_orphan_events();
-- Note: Should be called after relay deletion or cleanup operations
CREATE OR REPLACE FUNCTION delete_orphan_events()
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

COMMENT ON FUNCTION delete_orphan_events() IS 'Deletes events without relay associations (maintains 1:N relationship)';

-- Function: delete_failed_candidates
-- Description: Removes validator candidates that have exceeded max failed attempts
-- Purpose: Cleanup maintenance for candidates that consistently fail validation
-- Parameters:
--   p_max_attempts: Maximum number of failed attempts before deletion (default: 10)
-- Returns: BIGINT (number of deleted rows)
-- Usage: SELECT delete_failed_candidates(10);
CREATE OR REPLACE FUNCTION delete_failed_candidates(
    p_max_attempts INTEGER DEFAULT 10
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

COMMENT ON FUNCTION delete_failed_candidates IS 'Deletes validator candidates with failed_attempts >= threshold. Default threshold: 10.';

-- ============================================================================
-- INTEGRITY FUNCTIONS CREATED
-- ============================================================================
