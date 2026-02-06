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
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY relay_metadata_latest;
END;
$$;

COMMENT ON FUNCTION relay_metadata_latest_refresh() IS
'Refresh relay_metadata_latest concurrently. Schedule daily.';


/*
 * events_statistics_refresh() -> VOID
 *
 * Refreshes the events_statistics view concurrently.
 * Schedule: Hourly or as needed for dashboard accuracy.
 */
CREATE OR REPLACE FUNCTION events_statistics_refresh()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY events_statistics;
END;
$$;

COMMENT ON FUNCTION events_statistics_refresh() IS
'Refresh events_statistics concurrently.';


/*
 * relays_statistics_refresh() -> VOID
 *
 * Refreshes the relays_statistics view concurrently.
 * Schedule: Daily or as needed.
 */
CREATE OR REPLACE FUNCTION relays_statistics_refresh()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY relays_statistics;
END;
$$;

COMMENT ON FUNCTION relays_statistics_refresh() IS
'Refresh relays_statistics concurrently.';


/*
 * kind_counts_total_refresh() -> VOID
 *
 * Refreshes the kind_counts_total view concurrently.
 * Schedule: Daily or as needed.
 */
CREATE OR REPLACE FUNCTION kind_counts_total_refresh()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY kind_counts_total;
END;
$$;

COMMENT ON FUNCTION kind_counts_total_refresh() IS
'Refresh kind_counts_total concurrently.';


/*
 * kind_counts_by_relay_refresh() -> VOID
 *
 * Refreshes the kind_counts_by_relay view concurrently.
 * Schedule: Daily or as needed.
 */
CREATE OR REPLACE FUNCTION kind_counts_by_relay_refresh()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY kind_counts_by_relay;
END;
$$;

COMMENT ON FUNCTION kind_counts_by_relay_refresh() IS
'Refresh kind_counts_by_relay concurrently.';


/*
 * pubkey_counts_total_refresh() -> VOID
 *
 * Refreshes the pubkey_counts_total view concurrently.
 * Schedule: Daily or as needed.
 */
CREATE OR REPLACE FUNCTION pubkey_counts_total_refresh()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY pubkey_counts_total;
END;
$$;

COMMENT ON FUNCTION pubkey_counts_total_refresh() IS
'Refresh pubkey_counts_total concurrently.';


/*
 * pubkey_counts_by_relay_refresh() -> VOID
 *
 * Refreshes the pubkey_counts_by_relay view concurrently.
 * Schedule: Daily or as needed.
 */
CREATE OR REPLACE FUNCTION pubkey_counts_by_relay_refresh()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY pubkey_counts_by_relay;
END;
$$;

COMMENT ON FUNCTION pubkey_counts_by_relay_refresh() IS
'Refresh pubkey_counts_by_relay concurrently.';


/*
 * refresh_all_statistics() -> VOID
 *
 * Refreshes all materialized views in dependency order. The metadata view
 * is refreshed first because relays_statistics depends on it for RTT data.
 * Best run during a maintenance window due to the aggregate I/O cost.
 *
 * Schedule: Daily maintenance window.
 */
CREATE OR REPLACE FUNCTION refresh_all_statistics()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM relay_metadata_latest_refresh();
    PERFORM events_statistics_refresh();
    PERFORM relays_statistics_refresh();
    PERFORM kind_counts_total_refresh();
    PERFORM kind_counts_by_relay_refresh();
    PERFORM pubkey_counts_total_refresh();
    PERFORM pubkey_counts_by_relay_refresh();
END;
$$;

COMMENT ON FUNCTION refresh_all_statistics() IS
'Refresh all materialized views in dependency order. Run during maintenance windows.';
