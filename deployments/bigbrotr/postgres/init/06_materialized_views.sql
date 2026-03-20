/*
 * Brotr - 06_materialized_views.sql
 *
 * Analytics layer: materialized views (bounded, full refresh) and summary
 * tables (incremental refresh via stored procedures in 07_functions_refresh).
 *
 * Materialized views are used for bounded result sets where full refresh is
 * cheap. Summary tables are used for large aggregates where incremental
 * refresh is essential for performance at scale.
 *
 * NIP-85 summary tables provide per-pubkey social metrics and per-event
 * engagement metrics for Trusted Assertions (kind 30382/30383).
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


-- **************************************************************************
-- SUMMARY TABLES (incremental refresh)
-- **************************************************************************
-- These are regular tables maintained by stored procedures that process
-- only new data (delta since last checkpoint). The caller passes a
-- (p_after, p_until) range of event_relay.seen_at timestamps.
--
-- Cross-tabs are refreshed BEFORE entity tables because entity tables
-- derive unique_kinds/unique_relays from cross-tab row counts.
-- **************************************************************************


-- ==========================================================================
-- pubkey_kind_stats: Author activity per kind (cross-tabulation)
-- ==========================================================================
-- One row per (pubkey, kind). All columns are additive or monotone,
-- making incremental maintenance trivial.
--
-- Refresh: pubkey_kind_stats_refresh(p_after, p_until)

CREATE TABLE IF NOT EXISTS pubkey_kind_stats (
    pubkey TEXT NOT NULL,
    kind INTEGER NOT NULL,
    event_count BIGINT NOT NULL DEFAULT 0,
    first_event_at BIGINT,
    last_event_at BIGINT,
    PRIMARY KEY (pubkey, kind)
);

COMMENT ON TABLE pubkey_kind_stats IS
'Author event counts per kind. Incrementally refreshed via pubkey_kind_stats_refresh(after, until).';


-- ==========================================================================
-- pubkey_relay_stats: Author activity per relay (cross-tabulation)
-- ==========================================================================
-- One row per (pubkey, relay_url). All columns are additive or monotone.
--
-- Refresh: pubkey_relay_stats_refresh(p_after, p_until)

CREATE TABLE IF NOT EXISTS pubkey_relay_stats (
    pubkey TEXT NOT NULL,
    relay_url TEXT NOT NULL,
    event_count BIGINT NOT NULL DEFAULT 0,
    first_event_at BIGINT,
    last_event_at BIGINT,
    PRIMARY KEY (pubkey, relay_url)
);

COMMENT ON TABLE pubkey_relay_stats IS
'Author event distribution per relay. Incrementally refreshed via pubkey_relay_stats_refresh(after, until).';


-- ==========================================================================
-- relay_kind_stats: Kind distribution per relay (cross-tabulation)
-- ==========================================================================
-- One row per (relay_url, kind). All columns are additive or monotone.
--
-- Refresh: relay_kind_stats_refresh(p_after, p_until)

CREATE TABLE IF NOT EXISTS relay_kind_stats (
    relay_url TEXT NOT NULL,
    kind INTEGER NOT NULL,
    event_count BIGINT NOT NULL DEFAULT 0,
    first_event_at BIGINT,
    last_event_at BIGINT,
    PRIMARY KEY (relay_url, kind)
);

COMMENT ON TABLE relay_kind_stats IS
'Kind distribution per relay. Incrementally refreshed via relay_kind_stats_refresh(after, until).';


-- ==========================================================================
-- pubkey_stats: Rich per-author statistics (entity)
-- ==========================================================================
-- One row per pubkey. Additive counts maintained incrementally;
-- unique_kinds and unique_relays derived from cross-tab row counts.
-- Rolling windows (events_last_*) refreshed periodically.
--
-- Refresh: pubkey_stats_refresh(p_after, p_until)

CREATE TABLE IF NOT EXISTS pubkey_stats (
    pubkey TEXT PRIMARY KEY,
    event_count BIGINT NOT NULL DEFAULT 0,
    unique_kinds INTEGER NOT NULL DEFAULT 0,
    unique_relays INTEGER NOT NULL DEFAULT 0,
    first_event_at BIGINT,
    last_event_at BIGINT,
    events_last_24h BIGINT NOT NULL DEFAULT 0,
    events_last_7d BIGINT NOT NULL DEFAULT 0,
    events_last_30d BIGINT NOT NULL DEFAULT 0,
    regular_count BIGINT NOT NULL DEFAULT 0,
    replaceable_count BIGINT NOT NULL DEFAULT 0,
    ephemeral_count BIGINT NOT NULL DEFAULT 0,
    addressable_count BIGINT NOT NULL DEFAULT 0
);

COMMENT ON TABLE pubkey_stats IS
'Rich per-author statistics. Incrementally refreshed via pubkey_stats_refresh(after, until).';


-- ==========================================================================
-- kind_stats: Rich per-kind statistics (entity)
-- ==========================================================================
-- One row per kind. Additive counts maintained incrementally;
-- unique_pubkeys and unique_relays derived from cross-tab row counts.
--
-- Refresh: kind_stats_refresh(p_after, p_until)

CREATE TABLE IF NOT EXISTS kind_stats (
    kind INTEGER PRIMARY KEY,
    event_count BIGINT NOT NULL DEFAULT 0,
    unique_pubkeys INTEGER NOT NULL DEFAULT 0,
    unique_relays INTEGER NOT NULL DEFAULT 0,
    category TEXT NOT NULL DEFAULT 'other',
    first_event_at BIGINT,
    last_event_at BIGINT,
    events_last_24h BIGINT NOT NULL DEFAULT 0,
    events_last_7d BIGINT NOT NULL DEFAULT 0,
    events_last_30d BIGINT NOT NULL DEFAULT 0
);

COMMENT ON TABLE kind_stats IS
'Rich per-kind statistics. Incrementally refreshed via kind_stats_refresh(after, until).';


-- ==========================================================================
-- relay_stats: Rich per-relay statistics (entity)
-- ==========================================================================
-- One row per relay. Event counts maintained incrementally;
-- unique_pubkeys and unique_kinds derived from cross-tab row counts.
-- RTT averages and NIP-11 info refreshed via relay_stats_metadata_refresh().
--
-- Refresh: relay_stats_refresh(p_after, p_until)

CREATE TABLE IF NOT EXISTS relay_stats (
    relay_url TEXT PRIMARY KEY,
    network TEXT,
    discovered_at BIGINT,
    event_count BIGINT NOT NULL DEFAULT 0,
    unique_pubkeys INTEGER NOT NULL DEFAULT 0,
    unique_kinds INTEGER NOT NULL DEFAULT 0,
    first_event_at BIGINT,
    last_event_at BIGINT,
    events_last_24h BIGINT NOT NULL DEFAULT 0,
    events_last_7d BIGINT NOT NULL DEFAULT 0,
    events_last_30d BIGINT NOT NULL DEFAULT 0,
    regular_count BIGINT NOT NULL DEFAULT 0,
    replaceable_count BIGINT NOT NULL DEFAULT 0,
    ephemeral_count BIGINT NOT NULL DEFAULT 0,
    addressable_count BIGINT NOT NULL DEFAULT 0,
    avg_rtt_open NUMERIC(10,2),
    avg_rtt_read NUMERIC(10,2),
    avg_rtt_write NUMERIC(10,2),
    nip11_name TEXT,
    nip11_software TEXT,
    nip11_version TEXT
);

COMMENT ON TABLE relay_stats IS
'Rich per-relay statistics. Event counts via relay_stats_refresh(after, until). Metadata via relay_stats_metadata_refresh().';


-- **************************************************************************
-- NIP-85 SUMMARY TABLES (incremental refresh)
-- **************************************************************************
-- Trusted Assertion metrics per NIP-85. Per-pubkey social stats (kind 30382)
-- and per-event engagement stats (kind 30383). Incrementally maintained with
-- the same (p_after, p_until) pattern as the core summary tables.
--
-- follower_count requires periodic reconciliation from events_replaceable_latest
-- (kind 3 is replaceable: contact lists overwrite, not accumulate).
-- **************************************************************************


-- ==========================================================================
-- nip85_pubkey_stats: Per-pubkey social metrics (NIP-85 kind 30382)
-- ==========================================================================
-- Additive counters for posts, reactions, reposts, reports, zaps.
-- activity_hours is a 24-slot heatmap (one INTEGER per UTC hour).
-- topic_counts is a JSONB object of topic -> count.
-- Zap amounts are bolt11-verified (claimed amount must match invoice).
--
-- Refresh: nip85_pubkey_stats_refresh(p_after, p_until)

CREATE TABLE IF NOT EXISTS nip85_pubkey_stats (
    pubkey TEXT PRIMARY KEY,
    post_count BIGINT NOT NULL DEFAULT 0,
    reply_count BIGINT NOT NULL DEFAULT 0,
    reaction_count_sent BIGINT NOT NULL DEFAULT 0,
    reaction_count_recd BIGINT NOT NULL DEFAULT 0,
    repost_count_sent BIGINT NOT NULL DEFAULT 0,
    repost_count_recd BIGINT NOT NULL DEFAULT 0,
    report_count_sent BIGINT NOT NULL DEFAULT 0,
    report_count_recd BIGINT NOT NULL DEFAULT 0,
    zap_count_sent BIGINT NOT NULL DEFAULT 0,
    zap_count_recd BIGINT NOT NULL DEFAULT 0,
    zap_amount_sent BIGINT NOT NULL DEFAULT 0,
    zap_amount_recd BIGINT NOT NULL DEFAULT 0,
    first_created_at BIGINT,
    activity_hours INTEGER[24] NOT NULL DEFAULT ARRAY_FILL(0, ARRAY[24]),
    topic_counts JSONB NOT NULL DEFAULT '{}'::JSONB,
    follower_count BIGINT NOT NULL DEFAULT 0,
    following_count BIGINT NOT NULL DEFAULT 0
);

COMMENT ON TABLE nip85_pubkey_stats IS
'NIP-85 per-pubkey social metrics. Incrementally refreshed via nip85_pubkey_stats_refresh(after, until). Follower count via nip85_follower_count_refresh().';


-- ==========================================================================
-- nip85_event_stats: Per-event engagement metrics (NIP-85 kind 30383)
-- ==========================================================================
-- Tracks comments, quotes, reposts, reactions, and zaps per event.
-- author_pubkey enables reverse lookup (find engagement for a pubkey's events).
-- Zap amounts are bolt11-verified.
--
-- Refresh: nip85_event_stats_refresh(p_after, p_until)

CREATE TABLE IF NOT EXISTS nip85_event_stats (
    event_id TEXT PRIMARY KEY,
    author_pubkey TEXT NOT NULL,
    comment_count BIGINT NOT NULL DEFAULT 0,
    quote_count BIGINT NOT NULL DEFAULT 0,
    repost_count BIGINT NOT NULL DEFAULT 0,
    reaction_count BIGINT NOT NULL DEFAULT 0,
    zap_count BIGINT NOT NULL DEFAULT 0,
    zap_amount BIGINT NOT NULL DEFAULT 0
);

COMMENT ON TABLE nip85_event_stats IS
'NIP-85 per-event engagement metrics. Incrementally refreshed via nip85_event_stats_refresh(after, until).';


-- **************************************************************************
-- MATERIALIZED VIEWS (bounded output, full refresh)
-- **************************************************************************


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
-- daily_counts: Daily aggregation time-series
-- ==========================================================================
-- One row per UTC day with event counts, unique authors, and unique kinds.
-- Useful for trend analysis, growth tracking, and time-series visualization.
--
-- Uses integer arithmetic (created_at / 86400) instead of
-- to_timestamp() + timezone conversion for faster grouping.
--
-- Refresh: daily_counts_refresh()

CREATE MATERIALIZED VIEW IF NOT EXISTS daily_counts AS
SELECT
    '1970-01-01'::DATE + (created_at / 86400)::INTEGER AS day,
    COUNT(*) AS event_count,
    COUNT(DISTINCT pubkey) AS unique_pubkeys,
    COUNT(DISTINCT kind) AS unique_kinds
FROM event
GROUP BY created_at / 86400
ORDER BY day DESC;

COMMENT ON MATERIALIZED VIEW daily_counts IS
'Daily event counts for time-series analysis (UTC). Refresh via daily_counts_refresh().';


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
