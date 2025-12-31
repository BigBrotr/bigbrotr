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
-- Description: Latest NIP-11 and NIP-66 data per relay
-- Refresh: Once daily via cron or manual call to refresh_relay_metadata_latest()
-- Performance: O(1) lookup after refresh via unique index

CREATE MATERIALIZED VIEW IF NOT EXISTS relay_metadata_latest AS
WITH latest AS (
    SELECT DISTINCT ON (rm.relay_url, rm.type)
        rm.relay_url,
        rm.type,
        rm.metadata_id,
        rm.snapshot_at,
        m.data
    FROM relay_metadata rm
    JOIN metadata m ON rm.metadata_id = m.id
    ORDER BY rm.relay_url, rm.type, rm.snapshot_at DESC
)
SELECT
    r.url AS relay_url,
    r.network,
    r.discovered_at,

    -- NIP-11 latest
    MAX(l.snapshot_at) FILTER (WHERE l.type = 'nip11') AS nip11_at,
    MAX(l.metadata_id)  FILTER (WHERE l.type = 'nip11') AS nip11_id,
    MAX(l.data)         FILTER (WHERE l.type = 'nip11') AS nip11_data,

    -- NIP-66 RTT latest (round-trip times, network)
    MAX(l.snapshot_at) FILTER (WHERE l.type = 'nip66_rtt') AS nip66_rtt_at,
    MAX(l.metadata_id)  FILTER (WHERE l.type = 'nip66_rtt') AS nip66_rtt_id,
    MAX(l.data)         FILTER (WHERE l.type = 'nip66_rtt') AS nip66_rtt_data,

    -- NIP-66 SSL latest (SSL/TLS certificate data)
    MAX(l.snapshot_at) FILTER (WHERE l.type = 'nip66_ssl') AS nip66_ssl_at,
    MAX(l.metadata_id)  FILTER (WHERE l.type = 'nip66_ssl') AS nip66_ssl_id,
    MAX(l.data)         FILTER (WHERE l.type = 'nip66_ssl') AS nip66_ssl_data,

    -- NIP-66 GEO latest (geolocation)
    MAX(l.snapshot_at) FILTER (WHERE l.type = 'nip66_geo') AS nip66_geo_at,
    MAX(l.metadata_id)  FILTER (WHERE l.type = 'nip66_geo') AS nip66_geo_id,
    MAX(l.data)         FILTER (WHERE l.type = 'nip66_geo') AS nip66_geo_data,

    -- Extracted NIP-66 RTT fields for quick filtering (cast to proper types)
    (MAX(l.data) FILTER (WHERE l.type = 'nip66_rtt')->>'rtt_open')::INTEGER AS rtt_open,
    (MAX(l.data) FILTER (WHERE l.type = 'nip66_rtt')->>'rtt_read')::INTEGER AS rtt_read,
    (MAX(l.data) FILTER (WHERE l.type = 'nip66_rtt')->>'rtt_write')::INTEGER AS rtt_write,
    (MAX(l.data) FILTER (WHERE l.type = 'nip66_rtt')->>'rtt_open') IS NOT NULL AS is_openable,
    (MAX(l.data) FILTER (WHERE l.type = 'nip66_rtt')->>'rtt_read') IS NOT NULL AS is_readable,
    (MAX(l.data) FILTER (WHERE l.type = 'nip66_rtt')->>'rtt_write') IS NOT NULL AS is_writable,

    -- Extracted NIP-66 SSL fields for quick filtering
    (MAX(l.data) FILTER (WHERE l.type = 'nip66_ssl')->>'ssl_valid')::BOOLEAN AS ssl_valid,
    MAX(l.data) FILTER (WHERE l.type = 'nip66_ssl')->>'ssl_issuer' AS ssl_issuer,
    (MAX(l.data) FILTER (WHERE l.type = 'nip66_ssl')->>'ssl_expires')::BIGINT AS ssl_expires,

    -- Extracted NIP-66 GEO fields for quick filtering
    MAX(l.data) FILTER (WHERE l.type = 'nip66_geo')->>'geohash' AS geohash,
    MAX(l.data) FILTER (WHERE l.type = 'nip66_geo')->>'geo_country' AS geo_country,

    -- Extracted NIP-11 fields for quick filtering
    MAX(l.data) FILTER (WHERE l.type = 'nip11')->>'name' AS nip11_name,
    MAX(l.data) FILTER (WHERE l.type = 'nip11')->>'description' AS nip11_description,
    MAX(l.data) FILTER (WHERE l.type = 'nip11')->'supported_nips' AS nip11_supported_nips,
    MAX(l.data) FILTER (WHERE l.type = 'nip11')->'limitation' AS nip11_limitation

FROM relays r
LEFT JOIN latest l ON r.url = l.relay_url
GROUP BY r.url, r.network, r.discovered_at;

COMMENT ON MATERIALIZED VIEW relay_metadata_latest IS
'Latest NIP-11 and NIP-66 data per relay. Refresh daily via refresh_relay_metadata_latest().';

-- ============================================================================
-- MATERIALIZED VIEW: events_statistics
-- ============================================================================
-- Description: Global statistics about events in the database
-- Purpose: Provides key metrics about events without content/tags analysis
-- Refresh: Periodically via refresh_events_statistics()
-- Performance: Fast lookups, single-row result
CREATE MATERIALIZED VIEW IF NOT EXISTS events_statistics AS
SELECT
    1 AS id,  -- Dummy unique key for REFRESH CONCURRENTLY
    COUNT(*) AS total_events,
    COUNT(DISTINCT pubkey) AS unique_pubkeys,
    COUNT(DISTINCT kind) AS unique_kinds,
    MIN(created_at) AS earliest_event_timestamp,
    MAX(created_at) AS latest_event_timestamp,

    -- Event category counts according to NIP-01 specifications
    COUNT(*) FILTER (WHERE
        (kind >= 1000 AND kind < 10000) OR
        (kind >= 4 AND kind < 45) OR
        kind = 1 OR
        kind = 2
    ) AS regular_events,

    COUNT(*) FILTER (WHERE
        (kind >= 10000 AND kind < 20000) OR
        kind = 0 OR
        kind = 3
    ) AS replaceable_events,

    COUNT(*) FILTER (WHERE
        kind >= 20000 AND kind < 30000
    ) AS ephemeral_events,

    COUNT(*) FILTER (WHERE
        kind >= 30000 AND kind < 40000
    ) AS addressable_events,

    -- Time-based metrics
    COUNT(*) FILTER (WHERE created_at >= EXTRACT(EPOCH FROM NOW() - INTERVAL '1 hour')) AS events_last_hour,
    COUNT(*) FILTER (WHERE created_at >= EXTRACT(EPOCH FROM NOW() - INTERVAL '24 hours')) AS events_last_24h,
    COUNT(*) FILTER (WHERE created_at >= EXTRACT(EPOCH FROM NOW() - INTERVAL '7 days')) AS events_last_7d,
    COUNT(*) FILTER (WHERE created_at >= EXTRACT(EPOCH FROM NOW() - INTERVAL '30 days')) AS events_last_30d

FROM events;

COMMENT ON MATERIALIZED VIEW events_statistics IS 'Global event statistics with NIP-01 event categories. Refresh via refresh_events_statistics().';

-- ============================================================================
-- MATERIALIZED VIEW: relays_statistics
-- ============================================================================
-- Description: Per-relay statistics with event counts and performance metrics
-- Purpose: Provides detailed metrics for each relay
-- Refresh: Periodically via refresh_relays_statistics()
-- Performance: Fast lookups with relay_url index
CREATE MATERIALIZED VIEW IF NOT EXISTS relays_statistics AS
WITH relay_event_stats AS (
    SELECT
        er.relay_url,
        COUNT(DISTINCT er.event_id) AS event_count,
        COUNT(DISTINCT e.pubkey) AS unique_pubkeys,
        MIN(e.created_at) AS first_event_timestamp,
        MAX(e.created_at) AS last_event_timestamp
    FROM events_relays er
    LEFT JOIN events e ON er.event_id = e.id
    GROUP BY er.relay_url
),
relay_performance AS (
    -- Get last 10 RTT measurements per relay and calculate averages
    SELECT
        relay_url,
        AVG(rtt_open) FILTER (WHERE rtt_open IS NOT NULL) AS avg_rtt_open,
        AVG(rtt_read) FILTER (WHERE rtt_read IS NOT NULL) AS avg_rtt_read,
        AVG(rtt_write) FILTER (WHERE rtt_write IS NOT NULL) AS avg_rtt_write
    FROM (
        SELECT
            rm.relay_url,
            (m.data->>'rtt_open')::INTEGER AS rtt_open,
            (m.data->>'rtt_read')::INTEGER AS rtt_read,
            (m.data->>'rtt_write')::INTEGER AS rtt_write,
            ROW_NUMBER() OVER (PARTITION BY rm.relay_url ORDER BY rm.snapshot_at DESC) AS rn
        FROM relay_metadata rm
        JOIN metadata m ON rm.metadata_id = m.id
        WHERE rm.type = 'nip66_rtt'
    ) recent_measurements
    WHERE rn <= 10  -- Only consider last 10 measurements
    GROUP BY relay_url
)
SELECT
    r.url AS relay_url,
    r.network,
    r.discovered_at,
    COALESCE(res.event_count, 0) AS event_count,
    COALESCE(res.unique_pubkeys, 0) AS unique_pubkeys,
    res.first_event_timestamp,
    res.last_event_timestamp,
    ROUND(rp.avg_rtt_open::NUMERIC, 2) AS avg_rtt_open,
    ROUND(rp.avg_rtt_read::NUMERIC, 2) AS avg_rtt_read,
    ROUND(rp.avg_rtt_write::NUMERIC, 2) AS avg_rtt_write
FROM relays r
LEFT JOIN relay_event_stats res ON r.url = res.relay_url
LEFT JOIN relay_performance rp ON r.url = rp.relay_url
ORDER BY r.url;

COMMENT ON MATERIALIZED VIEW relays_statistics IS 'Per-relay statistics including event counts and performance metrics. Refresh via refresh_relays_statistics().';

-- ============================================================================
-- MATERIALIZED VIEW: kind_counts_total
-- ============================================================================
-- Description: Aggregated count of events by kind across all relays
-- Purpose: Quick overview of event type distribution
-- Refresh: Periodically via refresh_kind_counts_total()
-- Performance: Fast lookups with kind index
CREATE MATERIALIZED VIEW IF NOT EXISTS kind_counts_total AS
SELECT
    kind,
    COUNT(*) AS event_count,
    COUNT(DISTINCT pubkey) AS unique_pubkeys
FROM events
GROUP BY kind
ORDER BY event_count DESC;

COMMENT ON MATERIALIZED VIEW kind_counts_total IS 'Total event counts by kind across all relays. Refresh via refresh_kind_counts_total().';

-- ============================================================================
-- MATERIALIZED VIEW: kind_counts_by_relay
-- ============================================================================
-- Description: Detailed count of events by kind and relay
-- Purpose: Analyze event type distribution per relay
-- Refresh: Periodically via refresh_kind_counts_by_relay()
-- Performance: Fast lookups with (kind, relay_url) composite index
CREATE MATERIALIZED VIEW IF NOT EXISTS kind_counts_by_relay AS
SELECT
    e.kind,
    er.relay_url,
    COUNT(*) AS event_count,
    COUNT(DISTINCT e.pubkey) AS unique_pubkeys
FROM events e
JOIN events_relays er ON e.id = er.event_id
GROUP BY e.kind, er.relay_url
ORDER BY e.kind, event_count DESC;

COMMENT ON MATERIALIZED VIEW kind_counts_by_relay IS 'Event counts by kind for each relay. Refresh via refresh_kind_counts_by_relay().';

-- ============================================================================
-- MATERIALIZED VIEW: pubkey_counts_total
-- ============================================================================
-- Description: Aggregated count of events by pubkey across all relays
-- Purpose: Quick overview of author activity
-- Refresh: Periodically via refresh_pubkey_counts_total()
-- Performance: Fast lookups with pubkey_hex index
CREATE MATERIALIZED VIEW IF NOT EXISTS pubkey_counts_total AS
SELECT
    encode(pubkey, 'hex') AS pubkey_hex,
    COUNT(*) AS event_count,
    COUNT(DISTINCT kind) AS unique_kinds,
    MIN(created_at) AS first_event_timestamp,
    MAX(created_at) AS last_event_timestamp
FROM events
GROUP BY pubkey
ORDER BY event_count DESC;

COMMENT ON MATERIALIZED VIEW pubkey_counts_total IS 'Total event counts by public key across all relays. Refresh via refresh_pubkey_counts_total().';

-- ============================================================================
-- MATERIALIZED VIEW: pubkey_counts_by_relay
-- ============================================================================
-- Description: Detailed count of events by pubkey and relay
-- Purpose: Analyze author activity distribution per relay
-- Refresh: Periodically via refresh_pubkey_counts_by_relay()
-- Performance: Fast lookups with (pubkey_hex, relay_url) composite index
CREATE MATERIALIZED VIEW IF NOT EXISTS pubkey_counts_by_relay AS
SELECT
    encode(e.pubkey, 'hex') AS pubkey_hex,
    er.relay_url,
    COUNT(*) AS event_count,
    COUNT(DISTINCT e.kind) AS unique_kinds,
    MIN(e.created_at) AS first_event_timestamp,
    MAX(e.created_at) AS last_event_timestamp,
    ARRAY_AGG(DISTINCT e.kind ORDER BY e.kind) AS kinds_used
FROM events e
JOIN events_relays er ON e.id = er.event_id
GROUP BY e.pubkey, er.relay_url
ORDER BY e.pubkey, event_count DESC;

COMMENT ON MATERIALIZED VIEW pubkey_counts_by_relay IS 'Event counts by public key for each relay. Refresh via refresh_pubkey_counts_by_relay().';

-- ============================================================================
-- MATERIALIZED VIEWS CREATED
-- ============================================================================
