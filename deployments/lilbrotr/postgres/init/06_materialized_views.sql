/*
 * Brotr - 06_materialized_views.sql
 *
 * Materialized views for pre-computed lookups. Each view has a corresponding
 * refresh function in 07_functions_refresh.sql and a unique index for
 * REFRESH CONCURRENTLY in 08_indexes.sql.
 *
 * Dependencies: 02_tables.sql
 */


-- ==========================================================================
-- relay_metadata_latest: Most recent metadata per relay and check type
-- ==========================================================================
-- Returns one row per (relay_url, metadata_type) combination, containing
-- the latest snapshot. Uses DISTINCT ON with descending generated_at to
-- efficiently select the most recent record per group.
--
-- Refresh: Daily via relay_metadata_latest_refresh()

CREATE MATERIALIZED VIEW IF NOT EXISTS relay_metadata_latest AS
SELECT DISTINCT ON (rm.relay_url, rm.metadata_type)
    rm.relay_url,
    rm.metadata_type,
    rm.generated_at,
    rm.metadata_id,
    m.data
FROM relay_metadata AS rm
INNER JOIN metadata AS m ON rm.metadata_id = m.id AND rm.metadata_type = m.metadata_type
ORDER BY rm.relay_url ASC, rm.metadata_type ASC, rm.generated_at DESC;

COMMENT ON MATERIALIZED VIEW relay_metadata_latest IS
'Latest metadata per relay and check type. Refresh via relay_metadata_latest_refresh().';
