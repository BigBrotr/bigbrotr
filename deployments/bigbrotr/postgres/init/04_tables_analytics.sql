/*
 * Brotr - 04_tables_analytics.sql
 *
 * Analytics layer: derived tables and reporting abstractions built on
 * top of the core and current-state schema.
 *
 * Derived analytics tables are regular tables maintained by the
 * refresh functions in 09_functions_refresh_analytics.sql.
 *
 * NIP-85 summary tables provide per-pubkey social metrics and per-event
 * engagement metrics for Trusted Assertions (kind 30382/30383).
 *
 * Dependencies: 02_tables_core.sql, 03_tables_current.sql
 */


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
-- ANALYTICS SUMMARY TABLES (incremental refresh)
-- **************************************************************************
-- Trusted Assertion metrics per NIP-85, plus canonical facts derived from
-- current kind=3 contact-list tables. Incrementally maintained with the same
-- (p_after, p_until) pattern as the core analytics summary tables.
--
-- follower_count/following_count are periodically reconciled from the
-- canonical contact-list facts tables because kind=3 is replaceable.
-- **************************************************************************


-- ==========================================================================
-- nip85_pubkey_stats: Per-pubkey social metrics (NIP-85 kind 30382)
-- ==========================================================================
-- Additive counters for posts, reactions, reposts, reports, zaps.
-- activity_hours is a 24-slot heatmap (one INTEGER per UTC hour).
-- topic_counts is a JSONB object of topic -> count.
-- Zap amounts are bolt11-verified (claimed amount must match invoice).
-- follower_count and following_count are periodically reconciled from the
-- canonical contact-list facts tables, not accumulated incrementally.
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
'NIP-85 per-pubkey social metrics. Incrementally refreshed via nip85_pubkey_stats_refresh(after, until). Follower and following counts via nip85_follower_count_refresh().';


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


-- ==========================================================================
-- nip85_addressable_stats: Per-addressable-event engagement metrics (30384)
-- ==========================================================================
-- Tracks comments, quotes, reposts, reactions, and zaps aggregated by the
-- canonical addressable event coordinate ``kind:pubkey:d_tag`` across all
-- versions of that addressable event.
--
-- Refresh: nip85_addressable_stats_refresh(p_after, p_until)

CREATE TABLE IF NOT EXISTS nip85_addressable_stats (
    event_address TEXT PRIMARY KEY,
    author_pubkey TEXT NOT NULL,
    comment_count BIGINT NOT NULL DEFAULT 0,
    quote_count BIGINT NOT NULL DEFAULT 0,
    repost_count BIGINT NOT NULL DEFAULT 0,
    reaction_count BIGINT NOT NULL DEFAULT 0,
    zap_count BIGINT NOT NULL DEFAULT 0,
    zap_amount BIGINT NOT NULL DEFAULT 0
);

COMMENT ON TABLE nip85_addressable_stats IS
'NIP-85 per-addressable-event engagement metrics. Incrementally refreshed via nip85_addressable_stats_refresh(after, until).';


-- ==========================================================================
-- nip85_identifier_stats: Per-identifier engagement metrics (30385)
-- ==========================================================================
-- Tracks comments and reactions for NIP-73 identifiers (``i`` tags).
-- ``k_tags`` stores the deduplicated sorted set of accompanying NIP-73 ``k``
-- tags observed on source events so downstream publishers can re-emit them.
--
-- Refresh: nip85_identifier_stats_refresh(p_after, p_until)

CREATE TABLE IF NOT EXISTS nip85_identifier_stats (
    identifier TEXT PRIMARY KEY,
    comment_count BIGINT NOT NULL DEFAULT 0,
    reaction_count BIGINT NOT NULL DEFAULT 0,
    k_tags TEXT[] NOT NULL DEFAULT '{}'::TEXT[]
);

COMMENT ON TABLE nip85_identifier_stats IS
'NIP-85 per-identifier engagement metrics. Incrementally refreshed via nip85_identifier_stats_refresh(after, until).';


-- ==========================================================================
-- nip85_pubkey_ranks: Per-pubkey rank outputs (30382)
-- ==========================================================================
-- Snapshot-exported by the ranker after a successful DuckDB PageRank run.
-- ``subject_id`` is the asserted pubkey. ``raw_score`` is the unnormalized
-- PageRank value; ``rank`` is the final 0-100 score for publication.
--
-- Refresh: external snapshot export by the ranker service

CREATE TABLE IF NOT EXISTS nip85_pubkey_ranks (
    algorithm_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    raw_score DOUBLE PRECISION NOT NULL,
    rank INTEGER NOT NULL,
    computed_at BIGINT NOT NULL,
    PRIMARY KEY (algorithm_id, subject_id)
);

COMMENT ON TABLE nip85_pubkey_ranks IS
'NIP-85 per-pubkey rank outputs (kind 30382). Snapshot-exported by the ranker per algorithm_id after a successful DuckDB PageRank run.';


-- ==========================================================================
-- relay_software_counts: NIP-11 software distribution
-- ==========================================================================
-- Count of relays by software name and version from current NIP-11 metadata.
-- Recomputed from relay_metadata_current when the metadata watermark advances.
--
-- Refresh: relay_software_counts_refresh(p_after, p_until)

CREATE TABLE IF NOT EXISTS relay_software_counts (
    software TEXT NOT NULL,
    version TEXT NOT NULL,
    relay_count BIGINT NOT NULL,
    PRIMARY KEY (software, version)
);

COMMENT ON TABLE relay_software_counts IS
'NIP-11 software distribution across relays. Refreshed from relay_metadata_current via relay_software_counts_refresh(after, until).';


-- ==========================================================================
-- supported_nip_counts: NIP support distribution from NIP-11
-- ==========================================================================
-- Count of relays supporting each NIP number, derived from the current NIP-11
-- snapshot of each relay.
--
-- Refresh: supported_nip_counts_refresh(p_after, p_until)

CREATE TABLE IF NOT EXISTS supported_nip_counts (
    nip INTEGER PRIMARY KEY,
    relay_count BIGINT NOT NULL
);

COMMENT ON TABLE supported_nip_counts IS
'NIP support distribution across relays from current NIP-11 metadata. Refreshed via supported_nip_counts_refresh(after, until).';


-- **************************************************************************
-- ANALYTICS TABLES (incremental refresh)
-- **************************************************************************


-- ==========================================================================
-- daily_counts: Daily aggregation time-series
-- ==========================================================================
-- One row per UTC day with event counts, unique authors, and unique kinds.
-- Useful for trend analysis, growth tracking, and time-series visualization.
--
-- Uses integer arithmetic (created_at / 86400) instead of
-- to_timestamp() + timezone conversion for faster grouping.
--
-- Refresh: daily_counts_refresh(p_after, p_until)

CREATE TABLE IF NOT EXISTS daily_counts (
    day DATE PRIMARY KEY,
    event_count BIGINT NOT NULL,
    unique_pubkeys BIGINT NOT NULL,
    unique_kinds BIGINT NOT NULL
);

COMMENT ON TABLE daily_counts IS
'Daily event counts for time-series analysis (UTC). Incrementally refreshed via daily_counts_refresh(after, until).';
