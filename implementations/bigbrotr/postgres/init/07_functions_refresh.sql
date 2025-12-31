-- ============================================================================
-- BigBrotr Database Initialization Script
-- ============================================================================
-- File: 07_functions_refresh.sql
-- Description: Refresh Functions for materialized views
-- Dependencies: 06_materialized_views.sql
-- ============================================================================

-- Function: refresh_relay_metadata_latest
-- Description: Refreshes the materialized view concurrently (non-blocking)
-- Usage: SELECT refresh_relay_metadata_latest();
-- Note: Call from cron job or application scheduler once daily
CREATE OR REPLACE FUNCTION refresh_relay_metadata_latest()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY relay_metadata_latest;
END;
$$;

COMMENT ON FUNCTION refresh_relay_metadata_latest() IS
'Refreshes relay_metadata_latest materialized view concurrently. Call daily.';

-- Function: refresh_events_statistics
-- Description: Refreshes the materialized view concurrently (non-blocking)
-- Usage: SELECT refresh_events_statistics();
CREATE OR REPLACE FUNCTION refresh_events_statistics()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY events_statistics;
END;
$$;

COMMENT ON FUNCTION refresh_events_statistics() IS 'Refreshes events_statistics materialized view concurrently.';

-- Function: refresh_relays_statistics
-- Description: Refreshes the materialized view concurrently (non-blocking)
-- Usage: SELECT refresh_relays_statistics();
CREATE OR REPLACE FUNCTION refresh_relays_statistics()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY relays_statistics;
END;
$$;

COMMENT ON FUNCTION refresh_relays_statistics() IS 'Refreshes relays_statistics materialized view concurrently.';

-- Function: refresh_kind_counts_total
-- Description: Refreshes the materialized view concurrently (non-blocking)
-- Usage: SELECT refresh_kind_counts_total();
CREATE OR REPLACE FUNCTION refresh_kind_counts_total()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY kind_counts_total;
END;
$$;

COMMENT ON FUNCTION refresh_kind_counts_total() IS 'Refreshes kind_counts_total materialized view concurrently.';

-- Function: refresh_kind_counts_by_relay
-- Description: Refreshes the materialized view concurrently (non-blocking)
-- Usage: SELECT refresh_kind_counts_by_relay();
CREATE OR REPLACE FUNCTION refresh_kind_counts_by_relay()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY kind_counts_by_relay;
END;
$$;

COMMENT ON FUNCTION refresh_kind_counts_by_relay() IS 'Refreshes kind_counts_by_relay materialized view concurrently.';

-- Function: refresh_pubkey_counts_total
-- Description: Refreshes the materialized view concurrently (non-blocking)
-- Usage: SELECT refresh_pubkey_counts_total();
CREATE OR REPLACE FUNCTION refresh_pubkey_counts_total()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY pubkey_counts_total;
END;
$$;

COMMENT ON FUNCTION refresh_pubkey_counts_total() IS 'Refreshes pubkey_counts_total materialized view concurrently.';

-- Function: refresh_pubkey_counts_by_relay
-- Description: Refreshes the materialized view concurrently (non-blocking)
-- Usage: SELECT refresh_pubkey_counts_by_relay();
CREATE OR REPLACE FUNCTION refresh_pubkey_counts_by_relay()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY pubkey_counts_by_relay;
END;
$$;

COMMENT ON FUNCTION refresh_pubkey_counts_by_relay() IS 'Refreshes pubkey_counts_by_relay materialized view concurrently.';

-- ============================================================================
-- REFRESH FUNCTIONS CREATED
-- ============================================================================
