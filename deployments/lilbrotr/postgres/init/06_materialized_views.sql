/*
 * Brotr - 06_materialized_views.sql
 *
 * Analytics layer: current-state tables, summary tables, and the small number
 * of bounded reporting relations that still use full refresh.
 *
 * Current-state and summary tables are regular tables maintained by stored
 * procedures in 07_functions_refresh. Materialized views are reserved only for
 * bounded reporting outputs where a full refresh is still acceptable.
 *
 * NIP-85 summary tables provide per-pubkey social metrics and per-event
 * engagement metrics for Trusted Assertions (kind 30382/30383).
 *
 * Dependencies: 02_tables.sql
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
-- CURRENT TABLES (incremental refresh)
-- **************************************************************************
-- These are regular tables maintained by stored procedures that track
-- current/latest state rather than additive aggregates.
--
-- They are facts tables, not reporting views: each row represents the current
-- winner for a logical key such as (pubkey, kind) or (pubkey, kind, d_tag).
-- **************************************************************************


-- ==========================================================================
-- relay_metadata_current: Current metadata per relay and check type
-- ==========================================================================
-- One row per (relay_url, metadata_type), containing the most recent metadata
-- snapshot selected by generated_at DESC, metadata_id DESC.
--
-- The row stores both metadata_id and the denormalized JSON payload so the
-- current-state table is self-contained for readers and downstream refreshes.
--
-- Refresh: relay_metadata_current_refresh(p_after, p_until)

CREATE TABLE IF NOT EXISTS relay_metadata_current (
    relay_url TEXT NOT NULL,
    metadata_type TEXT NOT NULL,
    generated_at BIGINT NOT NULL,
    metadata_id BYTEA NOT NULL,
    data JSONB NOT NULL,
    PRIMARY KEY (relay_url, metadata_type)
);

COMMENT ON TABLE relay_metadata_current IS
'Current metadata snapshot per (relay_url, metadata_type). Incrementally refreshed via relay_metadata_current_refresh(after, until).';


-- ==========================================================================
-- events_replaceable_current: Current replaceable event per pubkey and kind
-- ==========================================================================
-- NIP-01 replaceable events (kind 0, 3, 10000-19999) have "at most one per
-- pubkey" semantics. This table stores the current winner per (pubkey, kind)
-- incrementally, using event.created_at as the primary ordering and id as a
-- deterministic tiebreaker. first_seen_at captures the first observation time
-- of the current winning event.
--
-- tags/content/sig remain nullable here so LilBrotr can share the same schema.
--
-- Refresh: events_replaceable_current_refresh(p_after, p_until)

CREATE TABLE IF NOT EXISTS events_replaceable_current (
    pubkey BYTEA NOT NULL,
    kind INTEGER NOT NULL,
    id BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    first_seen_at BIGINT NOT NULL,
    tags JSONB,
    tagvalues TEXT[] NOT NULL,
    content TEXT,
    sig BYTEA,
    PRIMARY KEY (pubkey, kind)
);

COMMENT ON TABLE events_replaceable_current IS
'Current replaceable event per (pubkey, kind). Incrementally refreshed via events_replaceable_current_refresh(after, until).';


-- ==========================================================================
-- events_addressable_current: Current addressable event per pubkey, kind, d-tag
-- ==========================================================================
-- NIP-01 addressable events (kind 30000-39999) have "at most one per
-- pubkey + kind + d-tag" semantics. The d-tag is extracted from the first
-- `d` tag when full JSON tags are available. In LilBrotr, where `tags` are
-- not persisted, the table falls back to ordered `tagvalues` entries (`d:*`).
-- Events without any d-tag use '' as the default, per NIP-01 specification.
--
-- first_seen_at captures the first observation time of the current winning
-- event for each (pubkey, kind, d_tag) key.
--
-- Refresh: events_addressable_current_refresh(p_after, p_until)

CREATE TABLE IF NOT EXISTS events_addressable_current (
    pubkey BYTEA NOT NULL,
    kind INTEGER NOT NULL,
    d_tag TEXT NOT NULL,
    id BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    first_seen_at BIGINT NOT NULL,
    tags JSONB,
    tagvalues TEXT[] NOT NULL,
    content TEXT,
    sig BYTEA,
    PRIMARY KEY (pubkey, kind, d_tag)
);

COMMENT ON TABLE events_addressable_current IS
'Current addressable event per (pubkey, kind, d_tag). Incrementally refreshed via events_addressable_current_refresh(after, until).';


-- ==========================================================================
-- contact_lists_current: Current latest kind=3 contact list per author
-- ==========================================================================
-- One row per pubkey whose latest replaceable kind=3 event is currently active.
-- source_seen_at stores the first seen_at timestamp of the current latest
-- replaceable event, making the row stable across later duplicate observations
-- on other relays.
-- follow_count is the deduplicated number of valid followed pubkeys in that
-- current list.
--
-- Refresh: contact_lists_current_refresh(p_after, p_until)

CREATE TABLE IF NOT EXISTS contact_lists_current (
    follower_pubkey TEXT PRIMARY KEY,
    source_event_id TEXT NOT NULL,
    source_created_at BIGINT NOT NULL,
    source_seen_at BIGINT NOT NULL,
    follow_count BIGINT NOT NULL DEFAULT 0
);

COMMENT ON TABLE contact_lists_current IS
'Current latest kind=3 contact list per pubkey. Incrementally refreshed via contact_lists_current_refresh(after, until).';


-- ==========================================================================
-- contact_list_edges_current: Current deduplicated follow graph edges
-- ==========================================================================
-- One row per current (follower, followed) edge derived from the latest kind=3
-- event of that follower. The source_* columns point back to the active contact
-- list event that produced the edge.
--
-- Refresh: contact_list_edges_current_refresh(p_after, p_until)

CREATE TABLE IF NOT EXISTS contact_list_edges_current (
    follower_pubkey TEXT NOT NULL,
    followed_pubkey TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    source_created_at BIGINT NOT NULL,
    source_seen_at BIGINT NOT NULL,
    PRIMARY KEY (follower_pubkey, followed_pubkey)
);

COMMENT ON TABLE contact_list_edges_current IS
'Current deduplicated follow graph edges derived from latest kind=3 contact lists. Incrementally refreshed via contact_list_edges_current_refresh(after, until).';


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
-- MATERIALIZED VIEWS (bounded output, full refresh)
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
