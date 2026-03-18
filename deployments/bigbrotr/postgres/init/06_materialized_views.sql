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
-- Refresh: relay_metadata_latest_refresh()

CREATE MATERIALIZED VIEW IF NOT EXISTS relay_metadata_latest AS
SELECT DISTINCT ON (rm.relay_url, rm.metadata_type)
    rm.relay_url,
    rm.metadata_type,
    rm.generated_at,
    rm.metadata_id,
    m.data
FROM relay_metadata AS rm
INNER JOIN metadata AS m ON rm.metadata_id = m.id AND rm.metadata_type = m.type
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
-- Refresh: event_stats_refresh()

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
-- RTT uses a CTE with ROW_NUMBER() instead of LATERAL to compute averages
-- in a single pass over relay_metadata. NIP-11 info joins the
-- relay_metadata_latest materialized view directly.
--
-- Refresh: relay_stats_refresh()

CREATE MATERIALIZED VIEW IF NOT EXISTS relay_stats AS
WITH event_agg AS (
    SELECT
        er.relay_url,
        COUNT(*) AS event_count,
        COUNT(DISTINCT e.pubkey) AS unique_pubkeys,
        COUNT(DISTINCT e.kind) AS unique_kinds,
        MIN(e.created_at) AS first_event_timestamp,
        MAX(e.created_at) AS last_event_timestamp
    FROM event_relay AS er
    INNER JOIN event AS e ON er.event_id = e.id
    GROUP BY er.relay_url
),
rtt_ranked AS (
    SELECT
        rm.relay_url,
        m.data -> 'data' ->> 'rtt_open' AS rtt_open,
        m.data -> 'data' ->> 'rtt_read' AS rtt_read,
        m.data -> 'data' ->> 'rtt_write' AS rtt_write,
        ROW_NUMBER() OVER (
            PARTITION BY rm.relay_url ORDER BY rm.generated_at DESC
        ) AS rn
    FROM relay_metadata AS rm
    INNER JOIN metadata AS m
        ON rm.metadata_id = m.id AND rm.metadata_type = m.type
    WHERE rm.metadata_type = 'nip66_rtt'
),
rtt_agg AS (
    SELECT
        relay_url,
        ROUND(AVG(rtt_open::INTEGER)::NUMERIC, 2) AS avg_rtt_open,
        ROUND(AVG(rtt_read::INTEGER)::NUMERIC, 2) AS avg_rtt_read,
        ROUND(AVG(rtt_write::INTEGER)::NUMERIC, 2) AS avg_rtt_write
    FROM rtt_ranked
    WHERE rn <= 10
    GROUP BY relay_url
)

SELECT
    r.url AS relay_url,
    r.network,
    r.discovered_at,
    ea.first_event_timestamp,
    ea.last_event_timestamp,
    rtt.avg_rtt_open,
    rtt.avg_rtt_read,
    rtt.avg_rtt_write,
    COALESCE(ea.event_count, 0) AS event_count,
    COALESCE(ea.unique_pubkeys, 0) AS unique_pubkeys,
    COALESCE(ea.unique_kinds, 0) AS unique_kinds,
    nip11m.data -> 'data' ->> 'name' AS nip11_name,
    nip11m.data -> 'data' ->> 'software' AS nip11_software,
    nip11m.data -> 'data' ->> 'version' AS nip11_version

FROM relay AS r
LEFT JOIN event_agg AS ea ON r.url = ea.relay_url
LEFT JOIN rtt_agg AS rtt ON r.url = rtt.relay_url
LEFT JOIN relay_metadata_latest AS nip11l
    ON r.url = nip11l.relay_url AND nip11l.metadata_type = 'nip11_info'
LEFT JOIN metadata AS nip11m
    ON nip11l.metadata_id = nip11m.id AND nip11l.metadata_type = nip11m.type
ORDER BY r.url;

COMMENT ON MATERIALIZED VIEW relay_stats IS
'Per-relay statistics with event counts, avg RTT, and NIP-11 info. Refresh via relay_stats_refresh().';


-- ==========================================================================
-- kind_counts: Event count distribution by kind (global)
-- ==========================================================================
-- Aggregated event counts per NIP-01 kind across all relays with a category
-- label classifying each kind into regular/replaceable/ephemeral/addressable.
--
-- Refresh: kind_counts_refresh()

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
-- Refresh: kind_counts_by_relay_refresh()

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
-- Refresh: pubkey_counts_refresh()

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
-- Refresh: pubkey_counts_by_relay_refresh()

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
-- relay_counts CTE avoids COUNT(DISTINCT url) on the full join result.
-- network_events CTE deduplicates (network, event_id) before joining event,
-- so events seen on multiple relays in the same network are counted once.
--
-- Refresh: network_stats_refresh()

CREATE MATERIALIZED VIEW IF NOT EXISTS network_stats AS
WITH relay_counts AS (
    SELECT network, COUNT(*) AS relay_count
    FROM relay
    GROUP BY network
),
network_events AS (
    SELECT DISTINCT r.network, er.event_id
    FROM relay AS r
    INNER JOIN event_relay AS er ON r.url = er.relay_url
),
event_agg AS (
    SELECT
        ne.network,
        COUNT(*)::BIGINT AS event_count,
        COUNT(DISTINCT e.pubkey)::BIGINT AS unique_pubkeys,
        COUNT(DISTINCT e.kind)::BIGINT AS unique_kinds
    FROM network_events AS ne
    INNER JOIN event AS e ON ne.event_id = e.id
    GROUP BY ne.network
)

SELECT
    rc.network,
    rc.relay_count,
    COALESCE(ea.event_count, 0)::BIGINT AS event_count,
    COALESCE(ea.unique_pubkeys, 0)::BIGINT AS unique_pubkeys,
    COALESCE(ea.unique_kinds, 0)::BIGINT AS unique_kinds
FROM relay_counts AS rc
LEFT JOIN event_agg AS ea ON rc.network = ea.network
ORDER BY rc.relay_count DESC;

COMMENT ON MATERIALIZED VIEW network_stats IS
'Aggregate statistics per network type (clearnet, tor, i2p, loki). Refresh via network_stats_refresh().';


-- ==========================================================================
-- relay_software_counts: NIP-11 software distribution
-- ==========================================================================
-- Count of relays by software name and version from NIP-11 info metadata.
-- Only includes relays that report a software field in their NIP-11 response.
--
-- Depends on: relay_metadata_latest (refresh relay_metadata_latest first)
-- Refresh: relay_software_counts_refresh()

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
-- Refresh: supported_nip_counts_refresh()

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
-- Uses integer arithmetic (created_at / 86400) instead of
-- to_timestamp() + timezone conversion for faster grouping.
--
-- Refresh: event_daily_counts_refresh()

CREATE MATERIALIZED VIEW IF NOT EXISTS event_daily_counts AS
SELECT
    '1970-01-01'::DATE + (created_at / 86400)::INTEGER AS day,
    COUNT(*) AS event_count,
    COUNT(DISTINCT pubkey) AS unique_pubkeys,
    COUNT(DISTINCT kind) AS unique_kinds
FROM event
GROUP BY created_at / 86400
ORDER BY day DESC;

COMMENT ON MATERIALIZED VIEW event_daily_counts IS
'Daily event counts for time-series analysis (UTC). Refresh via event_daily_counts_refresh().';


-- ==========================================================================
-- events_replaceable_latest: Latest replaceable event per pubkey and kind
-- ==========================================================================
-- NIP-01 replaceable events (kind 0, 3, 10000-19999) have "at most one per
-- pubkey" semantics: only the event with the highest created_at is current.
-- This view materializes that latest snapshot for efficient lookups of
-- profiles (kind 0), contact lists (kind 3), relay lists (kind 10002), etc.
--
-- All event columns are included so consumers can read the full event
-- without joining back to the event table.
--
-- Refresh: events_replaceable_latest_refresh()

CREATE MATERIALIZED VIEW IF NOT EXISTS events_replaceable_latest AS
SELECT DISTINCT ON (pubkey, kind)
    id,
    pubkey,
    created_at,
    kind,
    tags,
    tagvalues,
    content,
    sig
FROM event
WHERE kind = 0
    OR kind = 3
    OR (kind >= 10000 AND kind <= 19999)
ORDER BY pubkey, kind, created_at DESC;

COMMENT ON MATERIALIZED VIEW events_replaceable_latest IS
'Latest replaceable event per (pubkey, kind). Covers kind 0, 3, 10000-19999. Refresh via events_replaceable_latest_refresh().';


-- ==========================================================================
-- events_addressable_latest: Latest addressable event per pubkey, kind, d-tag
-- ==========================================================================
-- NIP-01 addressable events (kind 30000-39999) have "at most one per
-- pubkey + kind + d-tag" semantics. The d-tag is extracted from the tags
-- JSONB array (first element where tag[0] = 'd'). Events without a d-tag
-- element use '' as the default, per NIP-01 specification.
--
-- Uses a LEFT JOIN LATERAL to extract the d-tag so that events without an
-- explicit d-tag are still included (with d_tag = '').
--
-- All event columns are included so consumers can read the full event
-- without joining back to the event table.
--
-- Refresh: events_addressable_latest_refresh()

CREATE MATERIALIZED VIEW IF NOT EXISTS events_addressable_latest AS
SELECT DISTINCT ON (e.pubkey, e.kind, d_tag)
    e.id,
    e.pubkey,
    e.created_at,
    e.kind,
    e.tags,
    e.tagvalues,
    e.content,
    e.sig,
    COALESCE(d.val, '') AS d_tag
FROM event AS e
LEFT JOIN LATERAL (
    SELECT elem ->> 1 AS val
    FROM jsonb_array_elements(e.tags) AS elem
    WHERE elem ->> 0 = 'd'
    LIMIT 1
) AS d ON TRUE
WHERE e.kind >= 30000 AND e.kind <= 39999
ORDER BY e.pubkey, e.kind, d_tag, e.created_at DESC;

COMMENT ON MATERIALIZED VIEW events_addressable_latest IS
'Latest addressable event per (pubkey, kind, d_tag). Covers kind 30000-39999. Refresh via events_addressable_latest_refresh().';
