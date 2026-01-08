-- ============================================================================
-- BigBrotr Database Initialization Script
-- ============================================================================
-- File: 06_materialized_views.sql
-- Description: Materialized views for pre-computed statistics and lookups
-- Dependencies: 02_tables.sql
-- ============================================================================

-- ============================================================================
-- MATERIALIZED VIEW: relay_metadata_latest
-- ============================================================================
-- Description: Latest metadata record per relay and type (unpivoted)
-- Refresh: Once daily via cron or manual call to relay_metadata_latest_refresh()
-- Performance: Uses DISTINCT ON for efficient latest-per-group selection
--
-- Structure: One row per (relay_url, type) combination
-- Columns: relay_url, type, generated_at, metadata_id, data

CREATE MATERIALIZED VIEW IF NOT EXISTS relay_metadata_latest AS
SELECT DISTINCT ON (rm.relay_url, rm.type)
    rm.relay_url,
    rm.type,
    rm.generated_at,
    rm.metadata_id,
    m.data
FROM relay_metadata AS rm
INNER JOIN metadata AS m ON rm.metadata_id = m.id
ORDER BY rm.relay_url ASC, rm.type ASC, rm.generated_at DESC;

COMMENT ON MATERIALIZED VIEW relay_metadata_latest IS
'Latest metadata per relay and type. One row per (relay_url, type). Refresh via relay_metadata_latest_refresh().';

-- ============================================================================
-- MATERIALIZED VIEW: events_statistics
-- ============================================================================
-- Description: Global statistics about events in the database
-- Purpose: Provides key metrics about events with correct NIP-01 categories
-- Refresh: Periodically via events_statistics_refresh()
-- Performance: Fast lookups, single-row result
--
-- NIP-01 Event Categories:
--   Regular:      kind 1, 2, 4-44, 1000-9999 (stored, not replaced)
--   Replaceable:  kind 0, 3, 10000-19999 (latest only per pubkey)
--   Ephemeral:    kind 20000-29999 (not stored by relays)
--   Addressable:  kind 30000-39999 (latest only per pubkey+d-tag)

CREATE MATERIALIZED VIEW IF NOT EXISTS events_statistics AS
SELECT
    1 AS id,  -- Dummy unique key for REFRESH CONCURRENTLY
    COUNT(*) AS total_events,
    COUNT(DISTINCT pubkey) AS unique_pubkeys,
    COUNT(DISTINCT kind) AS unique_kinds,
    MIN(created_at) AS earliest_event_timestamp,
    MAX(created_at) AS latest_event_timestamp,

    -- Regular events: kind 1, 2, 4-44, 1000-9999
    COUNT(*) FILTER (
        WHERE kind = 1
        OR kind = 2
        OR (kind >= 4 AND kind <= 44)
        OR (kind >= 1000 AND kind <= 9999)
    ) AS regular_events,

    -- Replaceable events: kind 0, 3, 10000-19999
    COUNT(*) FILTER (
        WHERE kind = 0
        OR kind = 3
        OR (kind >= 10000 AND kind <= 19999)
    ) AS replaceable_events,

    -- Ephemeral events: kind 20000-29999
    COUNT(*) FILTER (
        WHERE kind >= 20000 AND kind <= 29999
    ) AS ephemeral_events,

    -- Addressable events: kind 30000-39999
    COUNT(*) FILTER (
        WHERE kind >= 30000 AND kind <= 39999
    ) AS addressable_events,

    -- Time-based metrics
    COUNT(*) FILTER (
        WHERE created_at >= EXTRACT(EPOCH FROM NOW() - INTERVAL '1 hour')
    ) AS events_last_hour,
    COUNT(*) FILTER (
        WHERE created_at >= EXTRACT(EPOCH FROM NOW() - INTERVAL '24 hours')
    ) AS events_last_24h,
    COUNT(*) FILTER (
        WHERE created_at >= EXTRACT(EPOCH FROM NOW() - INTERVAL '7 days')
    ) AS events_last_7d,
    COUNT(*) FILTER (
        WHERE created_at >= EXTRACT(EPOCH FROM NOW() - INTERVAL '30 days')
    ) AS events_last_30d

FROM events;

COMMENT ON MATERIALIZED VIEW events_statistics IS
'Global event statistics with correct NIP-01 event categories. Refresh via events_statistics_refresh().';

-- ============================================================================
-- MATERIALIZED VIEW: relays_statistics
-- ============================================================================
-- Description: Per-relay statistics with event counts and performance metrics
-- Purpose: Provides detailed metrics for each relay
-- Refresh: Periodically via relays_statistics_refresh()
-- Performance: Optimized with LATERAL joins for recent RTT measurements

CREATE MATERIALIZED VIEW IF NOT EXISTS relays_statistics AS
WITH res AS (
    SELECT
        er.relay_url,
        COUNT(DISTINCT er.event_id) AS event_count,
        COUNT(DISTINCT e.pubkey) AS unique_pubkeys,
        MIN(e.created_at) AS first_event_timestamp,
        MAX(e.created_at) AS last_event_timestamp
    FROM events_relays AS er
    LEFT JOIN events AS e ON er.event_id = e.id
    GROUP BY er.relay_url
)

SELECT
    r.url AS relay_url,
    r.network,
    r.discovered_at,
    res.first_event_timestamp,
    res.last_event_timestamp,
    rp.avg_rtt_open,
    rp.avg_rtt_read,
    rp.avg_rtt_write,
    COALESCE(res.event_count, 0) AS event_count,
    COALESCE(res.unique_pubkeys, 0) AS unique_pubkeys

FROM relays AS r

-- Event statistics per relay
LEFT JOIN res ON r.url = res.relay_url

-- Performance metrics: average of last 10 RTT measurements
LEFT JOIN LATERAL (
    SELECT
        ROUND(AVG((m.data ->> 'rtt_open')::INTEGER)::NUMERIC, 2) AS avg_rtt_open,
        ROUND(AVG((m.data ->> 'rtt_read')::INTEGER)::NUMERIC, 2) AS avg_rtt_read,
        ROUND(AVG((m.data ->> 'rtt_write')::INTEGER)::NUMERIC, 2) AS avg_rtt_write
    FROM (
        SELECT rm.metadata_id
        FROM relay_metadata AS rm
        WHERE rm.relay_url = r.url AND rm.type = 'nip66_rtt'
        ORDER BY rm.generated_at DESC
        LIMIT 10
    ) AS recent
    INNER JOIN metadata AS m ON recent.metadata_id = m.id
) AS rp ON TRUE

ORDER BY r.url;

COMMENT ON MATERIALIZED VIEW relays_statistics IS
'Per-relay statistics including event counts and avg RTT from last 10 checks. Refresh via relays_statistics_refresh().';

-- ============================================================================
-- MATERIALIZED VIEW: kind_counts_total
-- ============================================================================
-- Description: Aggregated count of events by kind across all relays
-- Purpose: Quick overview of event type distribution
-- Refresh: Periodically via kind_counts_total_refresh()
-- Performance: Fast lookups with kind index

CREATE MATERIALIZED VIEW IF NOT EXISTS kind_counts_total AS
SELECT
    kind,
    COUNT(*) AS event_count,
    COUNT(DISTINCT pubkey) AS unique_pubkeys
FROM events
GROUP BY kind
ORDER BY event_count DESC;

COMMENT ON MATERIALIZED VIEW kind_counts_total IS
'Total event counts by kind across all relays. Refresh via kind_counts_total_refresh().';

-- ============================================================================
-- MATERIALIZED VIEW: kind_counts_by_relay
-- ============================================================================
-- Description: Detailed count of events by kind and relay
-- Purpose: Analyze event type distribution per relay
-- Refresh: Periodically via kind_counts_by_relay_refresh()
-- Performance: Fast lookups with (kind, relay_url) composite index

CREATE MATERIALIZED VIEW IF NOT EXISTS kind_counts_by_relay AS
SELECT
    e.kind,
    er.relay_url,
    COUNT(*) AS event_count,
    COUNT(DISTINCT e.pubkey) AS unique_pubkeys
FROM events AS e
INNER JOIN events_relays AS er ON e.id = er.event_id
GROUP BY e.kind, er.relay_url
ORDER BY e.kind ASC, event_count DESC;

COMMENT ON MATERIALIZED VIEW kind_counts_by_relay IS
'Event counts by kind for each relay. Refresh via kind_counts_by_relay_refresh().';

-- ============================================================================
-- MATERIALIZED VIEW: pubkey_counts_total
-- ============================================================================
-- Description: Aggregated count of events by pubkey across all relays
-- Purpose: Quick overview of author activity
-- Refresh: Periodically via pubkey_counts_total_refresh()
-- Performance: Fast lookups with pubkey_hex index

CREATE MATERIALIZED VIEW IF NOT EXISTS pubkey_counts_total AS
SELECT
    ENCODE(pubkey, 'hex') AS pubkey_hex,
    COUNT(*) AS event_count,
    COUNT(DISTINCT kind) AS unique_kinds,
    MIN(created_at) AS first_event_timestamp,
    MAX(created_at) AS last_event_timestamp
FROM events
GROUP BY pubkey
ORDER BY event_count DESC;

COMMENT ON MATERIALIZED VIEW pubkey_counts_total IS
'Total event counts by public key across all relays. Refresh via pubkey_counts_total_refresh().';

-- ============================================================================
-- MATERIALIZED VIEW: pubkey_counts_by_relay
-- ============================================================================
-- Description: Detailed count of events by pubkey and relay
-- Purpose: Analyze author activity distribution per relay
-- Refresh: Periodically via pubkey_counts_by_relay_refresh()
-- Performance: Fast lookups with (pubkey_hex, relay_url) composite index
-- Note: Removed ARRAY_AGG(kinds_used) for performance - query events table if needed

CREATE MATERIALIZED VIEW IF NOT EXISTS pubkey_counts_by_relay AS
SELECT
    er.relay_url,
    ENCODE(e.pubkey, 'hex') AS pubkey_hex,
    COUNT(*) AS event_count,
    COUNT(DISTINCT e.kind) AS unique_kinds,
    MIN(e.created_at) AS first_event_timestamp,
    MAX(e.created_at) AS last_event_timestamp
FROM events AS e
INNER JOIN events_relays AS er ON e.id = er.event_id
GROUP BY e.pubkey, er.relay_url
ORDER BY e.pubkey ASC, event_count DESC;

COMMENT ON MATERIALIZED VIEW pubkey_counts_by_relay IS
'Event counts by public key for each relay. Refresh via pubkey_counts_by_relay_refresh().';

-- ============================================================================
-- MATERIALIZED VIEWS CREATED
-- ============================================================================
