-- ============================================================================
-- BigBrotr Database Initialization Script
-- ============================================================================
-- File: 04_integrity_functions.sql
-- Description: Data integrity and cleanup functions
-- Dependencies: 02_tables.sql
-- ============================================================================

-- Function: delete_orphan_events
-- Description: Removes events that have no associated relay references
-- Purpose: Maintains data integrity constraint (events must have ≥1 relay)
-- Returns: INTEGER (number of deleted rows)
-- Usage: SELECT delete_orphan_events();
-- Note: Uses NOT EXISTS instead of NOT IN for NULL safety and better performance
CREATE OR REPLACE FUNCTION delete_orphan_events()
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM events e
    WHERE NOT EXISTS (
        SELECT 1
        FROM events_relays er
        WHERE er.event_id = e.id
    );
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$;

COMMENT ON FUNCTION delete_orphan_events() IS 'Deletes events without relay associations (maintains 1:N relationship)';

-- Function: delete_orphan_nip11
-- Description: Removes NIP-11 records that are not referenced by any relay metadata
-- Purpose: Cleanup unused NIP-11 data
-- Returns: INTEGER (number of deleted rows)
-- Usage: SELECT delete_orphan_nip11();
-- Note: Uses NOT EXISTS instead of NOT IN for NULL safety and better performance
CREATE OR REPLACE FUNCTION delete_orphan_nip11()
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM nip11 n
    WHERE NOT EXISTS (
        SELECT 1
        FROM relay_metadata rm
        WHERE rm.nip11_id = n.id
    );
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$;

COMMENT ON FUNCTION delete_orphan_nip11() IS 'Deletes NIP-11 records without relay metadata references';

-- Function: delete_orphan_nip66
-- Description: Removes NIP-66 records that are not referenced by any relay metadata
-- Purpose: Cleanup unused NIP-66 data
-- Returns: INTEGER (number of deleted rows)
-- Usage: SELECT delete_orphan_nip66();
-- Note: Uses NOT EXISTS instead of NOT IN for NULL safety and better performance
CREATE OR REPLACE FUNCTION delete_orphan_nip66()
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM nip66 n
    WHERE NOT EXISTS (
        SELECT 1
        FROM relay_metadata rm
        WHERE rm.nip66_id = n.id
    );
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$;

COMMENT ON FUNCTION delete_orphan_nip66() IS 'Deletes NIP-66 records without relay metadata references';

-- ============================================================================
-- INTEGRITY FUNCTIONS CREATED
-- ============================================================================