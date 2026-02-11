/*
 * BigBrotr - 04_functions_cleanup.sql
 *
 * Cleanup functions that remove orphaned records to maintain data integrity.
 * These should be run periodically or after bulk deletions from parent tables.
 *
 * Dependencies: 02_tables.sql
 */


/*
 * orphan_metadata_delete(p_batch_size) -> INTEGER
 *
 * Removes metadata records that have no references in relay_metadata,
 * processing in configurable batches to limit lock duration and WAL volume.
 * This happens when old metadata snapshots are deleted but their underlying
 * content-addressed documents remain. Safe to run at any time.
 *
 * Parameters:
 *   p_batch_size  Maximum rows to delete per iteration (default 10,000)
 *
 * Returns: Total number of deleted rows across all batches
 * Schedule: Daily, or after bulk relay_metadata deletions
 */
CREATE OR REPLACE FUNCTION orphan_metadata_delete(p_batch_size INTEGER DEFAULT 10000)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_deleted INTEGER := 0;
    v_batch INTEGER;
BEGIN
    LOOP
        DELETE FROM metadata m WHERE (m.id, m.metadata_type) IN (
            SELECT m2.id, m2.metadata_type FROM metadata m2
            WHERE NOT EXISTS (
                SELECT 1 FROM relay_metadata rm
                WHERE rm.metadata_id = m2.id AND rm.metadata_type = m2.metadata_type
            )
            LIMIT p_batch_size
        );
        GET DIAGNOSTICS v_batch = ROW_COUNT;
        v_deleted := v_deleted + v_batch;
        EXIT WHEN v_batch < p_batch_size;
    END LOOP;
    RETURN v_deleted;
END;
$$;

COMMENT ON FUNCTION orphan_metadata_delete(INTEGER) IS
'Delete unreferenced metadata in batches to limit lock duration';


/*
 * orphan_event_delete() -> INTEGER
 *
 * Removes events that have no associated relay in event_relay. This
 * enforces the invariant that every event must be associated with at least
 * one relay. Orphans can appear when a relay is deleted via CASCADE on
 * event_relay but the event itself remains.
 *
 * Returns: Number of deleted rows
 * Schedule: Daily, or after relay deletions
 */
CREATE OR REPLACE FUNCTION orphan_event_delete()
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_deleted INTEGER;
BEGIN
    DELETE FROM event e
    WHERE NOT EXISTS (
        SELECT 1 FROM event_relay er WHERE er.event_id = e.id
    );
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$;

COMMENT ON FUNCTION orphan_event_delete() IS
'Delete events without any relay association (maintains 1:N invariant)';


/*
 * relay_metadata_delete_expired(p_max_age_seconds, p_batch_size) -> INTEGER
 *
 * Retention policy for relay_metadata: deletes snapshots older than
 * the specified age in batches to limit lock duration and WAL volume.
 * Run orphan_metadata_delete() afterward to clean up dereferenced metadata.
 *
 * Parameters:
 *   p_max_age_seconds  Maximum age in seconds (default 2,592,000 = 30 days)
 *   p_batch_size       Maximum rows to delete per iteration (default 10,000)
 *
 * Returns: Total number of deleted rows across all batches
 * Schedule: Weekly, or as retention policy requires
 */
CREATE OR REPLACE FUNCTION relay_metadata_delete_expired(
    p_max_age_seconds INTEGER DEFAULT 2592000,
    p_batch_size INTEGER DEFAULT 10000
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_cutoff BIGINT;
    v_deleted INTEGER := 0;
    v_batch INTEGER;
BEGIN
    v_cutoff := EXTRACT(EPOCH FROM NOW())::BIGINT - p_max_age_seconds;
    LOOP
        DELETE FROM relay_metadata
        WHERE (relay_url, generated_at, metadata_type) IN (
            SELECT relay_url, generated_at, metadata_type
            FROM relay_metadata
            WHERE generated_at < v_cutoff LIMIT p_batch_size
        );
        GET DIAGNOSTICS v_batch = ROW_COUNT;
        v_deleted := v_deleted + v_batch;
        EXIT WHEN v_batch < p_batch_size;
    END LOOP;
    RETURN v_deleted;
END;
$$;

COMMENT ON FUNCTION relay_metadata_delete_expired(INTEGER, INTEGER) IS
'Delete relay_metadata older than max age in batches (default 30 days)';
