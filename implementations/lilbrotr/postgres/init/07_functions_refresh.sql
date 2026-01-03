-- ============================================================================
-- LilBrotr Database Initialization Script
-- ============================================================================
-- File: 07_functions_refresh.sql
-- Description: Refresh Functions for materialized views
-- Dependencies: 06_materialized_views.sql
-- ============================================================================

-- Function: relay_metadata_latest_refresh
-- Description: Refreshes the materialized view concurrently (non-blocking)
-- Usage: SELECT relay_metadata_latest_refresh();
-- Note: Call from cron job or application scheduler once daily
CREATE OR REPLACE FUNCTION relay_metadata_latest_refresh()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY relay_metadata_latest;
END;
$$;

COMMENT ON FUNCTION relay_metadata_latest_refresh() IS
'Refreshes relay_metadata_latest materialized view concurrently. Call daily.';

-- Function: events_statistics_refresh
-- Description: Refreshes the materialized view concurrently (non-blocking)
-- Usage: SELECT events_statistics_refresh();
CREATE OR REPLACE FUNCTION events_statistics_refresh()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY events_statistics;
END;
$$;

COMMENT ON FUNCTION events_statistics_refresh() IS 'Refreshes events_statistics materialized view concurrently.';

-- Function: relays_statistics_refresh
-- Description: Refreshes the materialized view concurrently (non-blocking)
-- Usage: SELECT relays_statistics_refresh();
CREATE OR REPLACE FUNCTION relays_statistics_refresh()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY relays_statistics;
END;
$$;

COMMENT ON FUNCTION relays_statistics_refresh() IS 'Refreshes relays_statistics materialized view concurrently.';

-- Function: kind_counts_total_refresh
-- Description: Refreshes the materialized view concurrently (non-blocking)
-- Usage: SELECT kind_counts_total_refresh();
CREATE OR REPLACE FUNCTION kind_counts_total_refresh()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY kind_counts_total;
END;
$$;

COMMENT ON FUNCTION kind_counts_total_refresh() IS 'Refreshes kind_counts_total materialized view concurrently.';

-- Function: kind_counts_by_relay_refresh
-- Description: Refreshes the materialized view concurrently (non-blocking)
-- Usage: SELECT kind_counts_by_relay_refresh();
CREATE OR REPLACE FUNCTION kind_counts_by_relay_refresh()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY kind_counts_by_relay;
END;
$$;

COMMENT ON FUNCTION kind_counts_by_relay_refresh() IS 'Refreshes kind_counts_by_relay materialized view concurrently.';

-- Function: pubkey_counts_total_refresh
-- Description: Refreshes the materialized view concurrently (non-blocking)
-- Usage: SELECT pubkey_counts_total_refresh();
CREATE OR REPLACE FUNCTION pubkey_counts_total_refresh()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY pubkey_counts_total;
END;
$$;

COMMENT ON FUNCTION pubkey_counts_total_refresh() IS 'Refreshes pubkey_counts_total materialized view concurrently.';

-- Function: pubkey_counts_by_relay_refresh
-- Description: Refreshes the materialized view concurrently (non-blocking)
-- Usage: SELECT pubkey_counts_by_relay_refresh();
CREATE OR REPLACE FUNCTION pubkey_counts_by_relay_refresh()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY pubkey_counts_by_relay;
END;
$$;

COMMENT ON FUNCTION pubkey_counts_by_relay_refresh() IS 'Refreshes pubkey_counts_by_relay materialized view concurrently.';

-- ============================================================================
-- REFRESH FUNCTIONS CREATED
-- ============================================================================
