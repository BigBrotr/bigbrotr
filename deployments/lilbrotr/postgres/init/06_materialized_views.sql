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


-- ==========================================================================
-- event_stats: Global event counts and time-based metrics
-- ==========================================================================
-- Single-row view with aggregate statistics across all events, broken down
-- by NIP-01 event category (regular, replaceable, ephemeral, addressable),
-- time windows (1h, 24h, 7d, 30d), and average events per day.
--
-- NIP-01 event categories:
--   Regular:     kind 1, 2, 4-44, 1000-9999 (stored indefinitely)
--   Replaceable: kind 0, 3, 10000-19999 (latest per pubkey replaces older)
--   Ephemeral:   kind 20000-29999 (not persisted by relays)
--   Addressable: kind 30000-39999 (latest per pubkey+d-tag replaces older)
--
-- Note: Time-window counts (event_count_last_*) are snapshot values computed
-- at refresh time via NOW(). They become static until the next refresh.
--
-- Refresh: Hourly via event_stats_refresh()

CREATE MATERIALIZED VIEW IF NOT EXISTS event_stats AS
SELECT
    1 AS singleton_key,  -- Unique key required for REFRESH CONCURRENTLY
    COUNT(*) AS event_count,
    COUNT(DISTINCT pubkey) AS unique_pubkeys,
    COUNT(DISTINCT kind) AS unique_kinds,
    MIN(created_at) AS earliest_event_timestamp,
    MAX(created_at) AS latest_event_timestamp,

    -- NIP-01 category breakdown
    COUNT(*) FILTER (
        WHERE kind = 1
        OR kind = 2
        OR (kind >= 4 AND kind <= 44)
        OR (kind >= 1000 AND kind <= 9999)
    ) AS regular_event_count,

    COUNT(*) FILTER (
        WHERE kind = 0
        OR kind = 3
        OR (kind >= 10000 AND kind <= 19999)
    ) AS replaceable_event_count,

    COUNT(*) FILTER (
        WHERE kind >= 20000 AND kind <= 29999
    ) AS ephemeral_event_count,

    COUNT(*) FILTER (
        WHERE kind >= 30000 AND kind <= 39999
    ) AS addressable_event_count,

    -- Rolling time-window counts (snapshot at refresh time)
    COUNT(*) FILTER (
        WHERE created_at >= EXTRACT(EPOCH FROM NOW() - INTERVAL '1 hour')
    ) AS event_count_last_1h,
    COUNT(*) FILTER (
        WHERE created_at >= EXTRACT(EPOCH FROM NOW() - INTERVAL '24 hours')
    ) AS event_count_last_24h,
    COUNT(*) FILTER (
        WHERE created_at >= EXTRACT(EPOCH FROM NOW() - INTERVAL '7 days')
    ) AS event_count_last_7d,
    COUNT(*) FILTER (
        WHERE created_at >= EXTRACT(EPOCH FROM NOW() - INTERVAL '30 days')
    ) AS event_count_last_30d,

    -- Average events per day (total events / elapsed days)
    CASE WHEN MAX(created_at) > MIN(created_at)
        THEN ROUND(
            COUNT(*)::NUMERIC
            / GREATEST(((MAX(created_at) - MIN(created_at)) / 86400.0), 1),
            2
        )
        ELSE COUNT(*)::NUMERIC
    END AS events_per_day

FROM event;

COMMENT ON MATERIALIZED VIEW event_stats IS
'Global event statistics with NIP-01 category breakdowns and time windows. Refresh via event_stats_refresh().';


-- ==========================================================================
-- relay_stats: Per-relay event counts, performance, and NIP-11 info
-- ==========================================================================
-- One row per relay with event counts, unique author/kind counts, averaged
-- round-trip times from the last 10 NIP-66 RTT measurements, and the latest
-- NIP-11 relay info (name, software, version).
--
-- The RTT LATERAL subquery efficiently fetches only the 10 most recent RTT
-- records per relay. The NIP-11 LATERAL subquery fetches the single most
-- recent NIP-11 info snapshot.
--
-- Refresh: Daily via relay_stats_refresh()

CREATE MATERIALIZED VIEW IF NOT EXISTS relay_stats AS
WITH event_agg AS (
    SELECT
        er.relay_url,
        COUNT(DISTINCT er.event_id) AS event_count,
        COUNT(DISTINCT e.pubkey) AS unique_pubkeys,
        COUNT(DISTINCT e.kind) AS unique_kinds,
        MIN(e.created_at) AS first_event_timestamp,
        MAX(e.created_at) AS last_event_timestamp
    FROM event_relay AS er
    LEFT JOIN event AS e ON er.event_id = e.id
    GROUP BY er.relay_url
)

SELECT
    r.url AS relay_url,
    r.network,
    r.discovered_at,
    ea.first_event_timestamp,
    ea.last_event_timestamp,
    rp.avg_rtt_open,
    rp.avg_rtt_read,
    rp.avg_rtt_write,
    COALESCE(ea.event_count, 0) AS event_count,
    COALESCE(ea.unique_pubkeys, 0) AS unique_pubkeys,
    COALESCE(ea.unique_kinds, 0) AS unique_kinds,
    nip11.name AS nip11_name,
    nip11.software AS nip11_software,
    nip11.version AS nip11_version

FROM relay AS r

LEFT JOIN event_agg AS ea ON r.url = ea.relay_url

-- LATERAL join: compute average RTT from the 10 most recent measurements
LEFT JOIN LATERAL (
    SELECT
        ROUND(AVG((m.data -> 'data' ->> 'rtt_open')::INTEGER)::NUMERIC, 2) AS avg_rtt_open,
        ROUND(AVG((m.data -> 'data' ->> 'rtt_read')::INTEGER)::NUMERIC, 2) AS avg_rtt_read,
        ROUND(AVG((m.data -> 'data' ->> 'rtt_write')::INTEGER)::NUMERIC, 2) AS avg_rtt_write
    FROM (
        SELECT
            rm.metadata_id,
            rm.metadata_type
        FROM relay_metadata AS rm
        WHERE rm.relay_url = r.url AND rm.metadata_type = 'nip66_rtt'
        ORDER BY rm.generated_at DESC
        LIMIT 10
    ) AS recent
    INNER JOIN metadata AS m ON recent.metadata_id = m.id AND recent.metadata_type = m.metadata_type
) AS rp ON TRUE

-- LATERAL join: latest NIP-11 relay info
LEFT JOIN LATERAL (
    SELECT
        m.data -> 'data' ->> 'name' AS name,
        m.data -> 'data' ->> 'software' AS software,
        m.data -> 'data' ->> 'version' AS version
    FROM relay_metadata AS rm
    INNER JOIN metadata AS m ON rm.metadata_id = m.id AND rm.metadata_type = m.metadata_type
    WHERE rm.relay_url = r.url AND rm.metadata_type = 'nip11_info'
    ORDER BY rm.generated_at DESC
    LIMIT 1
) AS nip11 ON TRUE

ORDER BY r.url;

COMMENT ON MATERIALIZED VIEW relay_stats IS
'Per-relay statistics with event counts, avg RTT, and NIP-11 info. Refresh via relay_stats_refresh().';


-- ==========================================================================
-- kind_counts: Event count distribution by kind (global)
-- ==========================================================================
-- Aggregated event counts per NIP-01 kind across all relays with a category
-- label classifying each kind into regular/replaceable/ephemeral/addressable.
--
-- Refresh: Daily via kind_counts_refresh()

CREATE MATERIALIZED VIEW IF NOT EXISTS kind_counts AS
SELECT
    kind,
    COUNT(*) AS event_count,
    COUNT(DISTINCT pubkey) AS unique_pubkeys,
    CASE
        WHEN kind = 1
            OR kind = 2
            OR (kind >= 4 AND kind <= 44)
            OR (kind >= 1000 AND kind <= 9999) THEN 'regular'
        WHEN kind = 0
            OR kind = 3
            OR (kind >= 10000 AND kind <= 19999) THEN 'replaceable'
        WHEN kind >= 20000 AND kind <= 29999 THEN 'ephemeral'
        WHEN kind >= 30000 AND kind <= 39999 THEN 'addressable'
        ELSE 'other'
    END AS category
FROM event
GROUP BY kind
ORDER BY event_count DESC;

COMMENT ON MATERIALIZED VIEW kind_counts IS
'Total event counts by kind with NIP-01 category labels. Refresh via kind_counts_refresh().';


-- ==========================================================================
-- kind_counts_by_relay: Event count distribution by kind and relay
-- ==========================================================================
-- Per-relay breakdown of event kinds. Helps identify which relays specialize
-- in certain event types or have unusual kind distributions.
--
-- Refresh: Daily via kind_counts_by_relay_refresh()

CREATE MATERIALIZED VIEW IF NOT EXISTS kind_counts_by_relay AS
SELECT
    e.kind,
    er.relay_url,
    COUNT(*) AS event_count,
    COUNT(DISTINCT e.pubkey) AS unique_pubkeys
FROM event AS e
INNER JOIN event_relay AS er ON e.id = er.event_id
GROUP BY e.kind, er.relay_url
ORDER BY e.kind ASC, event_count DESC;

COMMENT ON MATERIALIZED VIEW kind_counts_by_relay IS
'Event counts by kind for each relay. Refresh via kind_counts_by_relay_refresh().';


-- ==========================================================================
-- pubkey_counts: Author activity counts (global)
-- ==========================================================================
-- Aggregated activity metrics per public key across all relays. The pubkey
-- is hex-encoded for easier display and joining with application data.
--
-- Refresh: Daily via pubkey_counts_refresh()

CREATE MATERIALIZED VIEW IF NOT EXISTS pubkey_counts AS
SELECT
    ENCODE(pubkey, 'hex') AS pubkey,
    COUNT(*) AS event_count,
    COUNT(DISTINCT kind) AS unique_kinds,
    MIN(created_at) AS first_event_timestamp,
    MAX(created_at) AS last_event_timestamp
FROM event
GROUP BY pubkey
ORDER BY event_count DESC;

COMMENT ON MATERIALIZED VIEW pubkey_counts IS
'Total event counts by public key across all relays. Refresh via pubkey_counts_refresh().';


-- ==========================================================================
-- pubkey_counts_by_relay: Author activity counts per relay (filtered)
-- ==========================================================================
-- Per-relay breakdown of author activity. Only includes pubkeys with 2+
-- events per relay to avoid cartesian explosion at scale.
--
-- Refresh: Daily via pubkey_counts_by_relay_refresh()

CREATE MATERIALIZED VIEW IF NOT EXISTS pubkey_counts_by_relay AS
SELECT
    er.relay_url,
    ENCODE(e.pubkey, 'hex') AS pubkey,
    COUNT(*) AS event_count,
    COUNT(DISTINCT e.kind) AS unique_kinds,
    MIN(e.created_at) AS first_event_timestamp,
    MAX(e.created_at) AS last_event_timestamp
FROM event AS e
INNER JOIN event_relay AS er ON e.id = er.event_id
GROUP BY e.pubkey, er.relay_url
HAVING COUNT(*) >= 2
ORDER BY e.pubkey ASC, event_count DESC;

COMMENT ON MATERIALIZED VIEW pubkey_counts_by_relay IS
'Event counts by public key for each relay (min 2 events). Refresh via pubkey_counts_by_relay_refresh().';


-- ==========================================================================
-- network_stats: Aggregate statistics per network type
-- ==========================================================================
-- One row per network type (clearnet, tor, i2p, loki) with relay count and
-- aggregated event metrics. Useful for comparing network adoption.
--
-- Refresh: Daily via network_stats_refresh()

CREATE MATERIALIZED VIEW IF NOT EXISTS network_stats AS
SELECT
    r.network,
    COUNT(DISTINCT r.url) AS relay_count,
    COUNT(DISTINCT er.event_id)::BIGINT AS event_count,
    COUNT(DISTINCT e.pubkey)::BIGINT AS unique_pubkeys,
    COUNT(DISTINCT e.kind)::BIGINT AS unique_kinds
FROM relay AS r
LEFT JOIN event_relay AS er ON r.url = er.relay_url
LEFT JOIN event AS e ON er.event_id = e.id
GROUP BY r.network
ORDER BY relay_count DESC;

COMMENT ON MATERIALIZED VIEW network_stats IS
'Aggregate statistics per network type (clearnet, tor, i2p, loki). Refresh via network_stats_refresh().';


-- ==========================================================================
-- relay_software_counts: NIP-11 software distribution
-- ==========================================================================
-- Count of relays by software name and version from NIP-11 info metadata.
-- Only includes relays that report a software field in their NIP-11 response.
--
-- Depends on: relay_metadata_latest (refresh relay_metadata_latest first)
-- Refresh: Daily via relay_software_counts_refresh()

CREATE MATERIALIZED VIEW IF NOT EXISTS relay_software_counts AS
SELECT
    data -> 'data' ->> 'software' AS software,
    COALESCE(data -> 'data' ->> 'version', 'unknown') AS version,
    COUNT(*) AS relay_count
FROM relay_metadata_latest
WHERE metadata_type = 'nip11_info'
    AND data -> 'data' ->> 'software' IS NOT NULL
GROUP BY data -> 'data' ->> 'software', COALESCE(data -> 'data' ->> 'version', 'unknown')
ORDER BY relay_count DESC;

COMMENT ON MATERIALIZED VIEW relay_software_counts IS
'NIP-11 software distribution across relays. Refresh relay_metadata_latest first. Refresh via relay_software_counts_refresh().';


-- ==========================================================================
-- supported_nip_counts: NIP support distribution from NIP-11
-- ==========================================================================
-- Count of relays supporting each NIP number, extracted from the
-- supported_nips array in NIP-11 info metadata.
--
-- Depends on: relay_metadata_latest (refresh relay_metadata_latest first)
-- Refresh: Daily via supported_nip_counts_refresh()

CREATE MATERIALIZED VIEW IF NOT EXISTS supported_nip_counts AS
SELECT
    nip_text::INTEGER AS nip,
    COUNT(*) AS relay_count
FROM relay_metadata_latest
CROSS JOIN LATERAL jsonb_array_elements_text(data -> 'data' -> 'supported_nips') AS nip_text
WHERE metadata_type = 'nip11_info'
    AND data -> 'data' ? 'supported_nips'
    AND jsonb_typeof(data -> 'data' -> 'supported_nips') = 'array'
    AND nip_text ~ '^\d+$'
GROUP BY nip_text::INTEGER
ORDER BY relay_count DESC;

COMMENT ON MATERIALIZED VIEW supported_nip_counts IS
'NIP support distribution across relays from NIP-11 info. Refresh relay_metadata_latest first. Refresh via supported_nip_counts_refresh().';


-- ==========================================================================
-- event_daily_counts: Daily event aggregation time-series
-- ==========================================================================
-- One row per UTC day with event counts, unique authors, and unique kinds.
-- Useful for trend analysis, growth tracking, and time-series visualization.
--
-- Refresh: Daily via event_daily_counts_refresh()

CREATE MATERIALIZED VIEW IF NOT EXISTS event_daily_counts AS
SELECT
    (to_timestamp(created_at) AT TIME ZONE 'UTC')::DATE AS day,
    COUNT(*) AS event_count,
    COUNT(DISTINCT pubkey) AS unique_pubkeys,
    COUNT(DISTINCT kind) AS unique_kinds
FROM event
GROUP BY (to_timestamp(created_at) AT TIME ZONE 'UTC')::DATE
ORDER BY day DESC;

COMMENT ON MATERIALIZED VIEW event_daily_counts IS
'Daily event counts for time-series analysis (UTC). Refresh via event_daily_counts_refresh().';
