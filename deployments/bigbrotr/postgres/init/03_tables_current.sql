/*
 * Brotr - 03_tables_current.sql
 *
 * Incremental current-state tables for Brotr.
 *
 * These relations store the current winner for logical keys such as
 * (relay_url, metadata_type), (pubkey, kind), and (pubkey, kind, d_tag).
 * They are maintained by refresh functions in 08_functions_refresh_current.sql.
 *
 * Dependencies: 02_tables_core.sql
 */

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
