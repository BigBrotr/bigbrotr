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
-- Returns: VOID
-- Usage: SELECT delete_orphan_events();
CREATE OR REPLACE FUNCTION delete_orphan_events()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM events
    WHERE id NOT IN (
        SELECT DISTINCT event_id
        FROM events_relays
    );
END;
$$;

COMMENT ON FUNCTION delete_orphan_events() IS 'Deletes events without relay associations (maintains 1:N relationship)';

-- Function: delete_orphan_nip11
-- Description: Removes NIP-11 records that are not referenced by any relay metadata
-- Purpose: Cleanup unused NIP-11 data
-- Returns: VOID
-- Usage: SELECT delete_orphan_nip11();
CREATE OR REPLACE FUNCTION delete_orphan_nip11()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM nip11
    WHERE id NOT IN (
        SELECT DISTINCT nip11_id
        FROM relay_metadata
        WHERE nip11_id IS NOT NULL
    );
END;
$$;

COMMENT ON FUNCTION delete_orphan_nip11() IS 'Deletes NIP-11 records without relay metadata references';

-- Function: delete_orphan_nip66
-- Description: Removes NIP-66 records that are not referenced by any relay metadata
-- Purpose: Cleanup unused NIP-66 data
-- Returns: VOID
-- Usage: SELECT delete_orphan_nip66();
CREATE OR REPLACE FUNCTION delete_orphan_nip66()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM nip66
    WHERE id NOT IN (
        SELECT DISTINCT nip66_id
        FROM relay_metadata
        WHERE nip66_id IS NOT NULL
    );
END;
$$;

COMMENT ON FUNCTION delete_orphan_nip66() IS 'Deletes NIP-66 records without relay metadata references';

-- ============================================================================
-- INTEGRITY FUNCTIONS CREATED
-- ============================================================================