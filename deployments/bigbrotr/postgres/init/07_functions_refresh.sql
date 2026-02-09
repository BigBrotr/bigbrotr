/*
 * BigBrotr - 07_functions_refresh.sql
 *
 * Refresh functions for materialized views. Each function wraps
 * REFRESH MATERIALIZED VIEW CONCURRENTLY, which rebuilds the view data
 * without blocking concurrent reads. Requires a unique index on each
 * materialized view (created in 08_indexes.sql).
 *
 * Dependencies: 06_materialized_views.sql
 */


/*
 * relay_metadata_latest_refresh() -> VOID
 *
 * Refreshes the relay_metadata_latest view concurrently.
 * Schedule: Daily via cron or application scheduler.
 */
CREATE OR REPLACE FUNCTION relay_metadata_latest_refresh()
RETURNS VOID
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY relay_metadata_latest;
END;
$$;

COMMENT ON FUNCTION relay_metadata_latest_refresh() IS
'Refresh relay_metadata_latest concurrently. Schedule daily.';


/*
 * event_stats_refresh() -> VOID
 *
 * Refreshes the event_stats view concurrently.
 * Schedule: Hourly or as needed for dashboard accuracy.
 */
CREATE OR REPLACE FUNCTION event_stats_refresh()
RETURNS VOID
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY event_stats;
END;
$$;

COMMENT ON FUNCTION event_stats_refresh() IS
'Refresh event_stats concurrently.';


/*
 * relay_stats_refresh() -> VOID
 *
 * Refreshes the relay_stats view concurrently.
 * Schedule: Daily or as needed.
 */
CREATE OR REPLACE FUNCTION relay_stats_refresh()
RETURNS VOID
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY relay_stats;
END;
$$;

COMMENT ON FUNCTION relay_stats_refresh() IS
'Refresh relay_stats concurrently.';


/*
 * kind_counts_refresh() -> VOID
 *
 * Refreshes the kind_counts view concurrently.
 * Schedule: Daily or as needed.
 */
CREATE OR REPLACE FUNCTION kind_counts_refresh()
RETURNS VOID
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY kind_counts;
END;
$$;

COMMENT ON FUNCTION kind_counts_refresh() IS
'Refresh kind_counts concurrently.';


/*
 * kind_counts_by_relay_refresh() -> VOID
 *
 * Refreshes the kind_counts_by_relay view concurrently.
 * Schedule: Daily or as needed.
 */
CREATE OR REPLACE FUNCTION kind_counts_by_relay_refresh()
RETURNS VOID
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY kind_counts_by_relay;
END;
$$;

COMMENT ON FUNCTION kind_counts_by_relay_refresh() IS
'Refresh kind_counts_by_relay concurrently.';


/*
 * pubkey_counts_refresh() -> VOID
 *
 * Refreshes the pubkey_counts view concurrently.
 * Schedule: Daily or as needed.
 */
CREATE OR REPLACE FUNCTION pubkey_counts_refresh()
RETURNS VOID
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY pubkey_counts;
END;
$$;

COMMENT ON FUNCTION pubkey_counts_refresh() IS
'Refresh pubkey_counts concurrently.';


/*
 * pubkey_counts_by_relay_refresh() -> VOID
 *
 * Refreshes the pubkey_counts_by_relay view concurrently.
 * Schedule: Daily or as needed.
 */
CREATE OR REPLACE FUNCTION pubkey_counts_by_relay_refresh()
RETURNS VOID
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY pubkey_counts_by_relay;
END;
$$;

COMMENT ON FUNCTION pubkey_counts_by_relay_refresh() IS
'Refresh pubkey_counts_by_relay concurrently.';


/*
 * all_statistics_refresh() -> VOID
 *
 * Refreshes all materialized views in dependency order. The metadata view
 * is refreshed first because relay_stats depends on it for RTT data.
 * Best run during a maintenance window due to the aggregate I/O cost.
 *
 * Schedule: Daily maintenance window.
 */
CREATE OR REPLACE FUNCTION all_statistics_refresh()
RETURNS VOID
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
BEGIN
    PERFORM relay_metadata_latest_refresh();
    PERFORM event_stats_refresh();
    PERFORM relay_stats_refresh();
    PERFORM kind_counts_refresh();
    PERFORM kind_counts_by_relay_refresh();
    PERFORM pubkey_counts_refresh();
    PERFORM pubkey_counts_by_relay_refresh();
END;
$$;

COMMENT ON FUNCTION all_statistics_refresh() IS
'Refresh all materialized views in dependency order. Run during maintenance windows.';
