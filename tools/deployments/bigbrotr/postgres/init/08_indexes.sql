/*
 * BigBrotr - 08_indexes.sql
 *
 * Performance indexes for tables and materialized views. Organized by
 * target object. Every materialized view requires a UNIQUE index for
 * REFRESH MATERIALIZED VIEW CONCURRENTLY to work.
 *
 * Dependencies: 02_tables.sql, 06_materialized_views.sql
 */


-- ==========================================================================
-- TABLE INDEXES: event
-- ==========================================================================

-- Global timeline queries: ORDER BY created_at DESC LIMIT N
CREATE INDEX IF NOT EXISTS idx_event_created_at
ON event USING btree (created_at DESC);

-- Kind filtering: WHERE kind = ? or WHERE kind IN (...)
CREATE INDEX IF NOT EXISTS idx_event_kind
ON event USING btree (kind);

-- Kind + timeline: WHERE kind = ? ORDER BY created_at DESC
CREATE INDEX IF NOT EXISTS idx_event_kind_created_at
ON event USING btree (kind, created_at DESC);

-- Author timeline: WHERE pubkey = ? ORDER BY created_at DESC
-- Also covers pubkey-only lookups via leftmost prefix
CREATE INDEX IF NOT EXISTS idx_event_pubkey_created_at
ON event USING btree (pubkey, created_at DESC);

-- Author + kind + timeline: WHERE pubkey = ? AND kind = ? ORDER BY created_at DESC
-- Supports queries like "all text notes by this author, newest first"
CREATE INDEX IF NOT EXISTS idx_event_pubkey_kind_created_at
ON event USING btree (pubkey, kind, created_at DESC);

-- Tag value containment: WHERE tagvalues @> ARRAY['<value>']
-- Requires the btree_gin extension for GIN support on text arrays
CREATE INDEX IF NOT EXISTS idx_event_tagvalues
ON event USING gin (tagvalues);

-- Cursor-based pagination for the Finder service:
-- WHERE (created_at, id) > ($1, $2) ORDER BY created_at ASC, id ASC
CREATE INDEX IF NOT EXISTS idx_event_created_at_id
ON event USING btree (created_at ASC, id ASC);


-- ==========================================================================
-- TABLE INDEXES: event_relay
-- ==========================================================================
-- The composite primary key (event_id, relay_url) already provides an
-- efficient B-tree index on event_id as the leftmost column, so no
-- separate event_id index is needed.

-- All events from a relay: WHERE relay_url = ?
CREATE INDEX IF NOT EXISTS idx_event_relay_relay_url
ON event_relay USING btree (relay_url);

-- Recently discovered events: ORDER BY seen_at DESC
CREATE INDEX IF NOT EXISTS idx_event_relay_seen_at
ON event_relay USING btree (seen_at DESC);

-- Synchronizer progress tracking: WHERE relay_url = ? ORDER BY seen_at DESC
-- Enables index-only scans for SELECT MAX(seen_at) WHERE relay_url = ?
CREATE INDEX IF NOT EXISTS idx_event_relay_relay_url_seen_at
ON event_relay USING btree (relay_url, seen_at DESC);


-- ==========================================================================
-- TABLE INDEXES: relay_metadata
-- ==========================================================================

-- Recent health checks: ORDER BY generated_at DESC
CREATE INDEX IF NOT EXISTS idx_relay_metadata_generated_at
ON relay_metadata USING btree (generated_at DESC);

-- Compound FK lookups: WHERE metadata_id = ? AND metadata_type = ?
-- Also used by orphan_metadata_delete() to verify references
CREATE INDEX IF NOT EXISTS idx_relay_metadata_metadata_id_type
ON relay_metadata USING btree (metadata_id, metadata_type);

-- Latest metadata per relay and type (powers relay_metadata_latest view):
-- WHERE relay_url = ? AND metadata_type = ? ORDER BY generated_at DESC
-- Also covers (relay_url) and (relay_url, metadata_type) via leftmost prefix
CREATE INDEX IF NOT EXISTS idx_relay_metadata_relay_url_metadata_type_generated_at
ON relay_metadata USING btree (relay_url, metadata_type, generated_at DESC);


-- ==========================================================================
-- TABLE INDEXES: service_state
-- ==========================================================================

-- All data for a service: WHERE service_name = ?
CREATE INDEX IF NOT EXISTS idx_service_state_service_name
ON service_state USING btree (service_name);

-- Specific state type within a service: WHERE service_name = ? AND state_type = ?
CREATE INDEX IF NOT EXISTS idx_service_state_service_name_state_type
ON service_state USING btree (service_name, state_type);

-- Candidate network filtering: WHERE state_value->>'network' = ANY($3)
-- Used by count_candidates() and fetch_candidate_chunk() in the Validator service
CREATE INDEX IF NOT EXISTS idx_service_state_candidate_network
ON service_state USING btree ((state_value ->> 'network'))
WHERE service_name = 'validator' AND state_type = 'candidate';


-- ==========================================================================
-- MATERIALIZED VIEW INDEXES: relay_metadata_latest
-- ==========================================================================

-- Required for REFRESH CONCURRENTLY (unique index on natural key)
CREATE UNIQUE INDEX IF NOT EXISTS idx_relay_metadata_latest_pk
ON relay_metadata_latest USING btree (relay_url, metadata_type);

-- Filter by check type: WHERE metadata_type = 'nip11_info'
CREATE INDEX IF NOT EXISTS idx_relay_metadata_latest_type
ON relay_metadata_latest USING btree (metadata_type);


-- ==========================================================================
-- MATERIALIZED VIEW INDEXES: event_stats
-- ==========================================================================

-- Required for REFRESH CONCURRENTLY (single-row view uses singleton_key)
CREATE UNIQUE INDEX IF NOT EXISTS idx_event_stats_singleton_key
ON event_stats USING btree (singleton_key);


-- ==========================================================================
-- MATERIALIZED VIEW INDEXES: relay_stats
-- ==========================================================================

-- Required for REFRESH CONCURRENTLY
CREATE UNIQUE INDEX IF NOT EXISTS idx_relay_stats_relay_url
ON relay_stats USING btree (relay_url);

-- Filter by network: WHERE network = ?
CREATE INDEX IF NOT EXISTS idx_relay_stats_network
ON relay_stats USING btree (network);


-- ==========================================================================
-- MATERIALIZED VIEW INDEXES: kind_counts
-- ==========================================================================

-- Required for REFRESH CONCURRENTLY
CREATE UNIQUE INDEX IF NOT EXISTS idx_kind_counts_kind
ON kind_counts USING btree (kind);


-- ==========================================================================
-- MATERIALIZED VIEW INDEXES: kind_counts_by_relay
-- ==========================================================================

-- Required for REFRESH CONCURRENTLY
CREATE UNIQUE INDEX IF NOT EXISTS idx_kind_counts_by_relay_composite
ON kind_counts_by_relay USING btree (kind, relay_url);

-- Filter by relay: WHERE relay_url = ?
CREATE INDEX IF NOT EXISTS idx_kind_counts_by_relay_relay
ON kind_counts_by_relay USING btree (relay_url);


-- ==========================================================================
-- MATERIALIZED VIEW INDEXES: pubkey_counts
-- ==========================================================================

-- Required for REFRESH CONCURRENTLY
CREATE UNIQUE INDEX IF NOT EXISTS idx_pubkey_counts_pubkey
ON pubkey_counts USING btree (pubkey);


-- ==========================================================================
-- MATERIALIZED VIEW INDEXES: pubkey_counts_by_relay
-- ==========================================================================

-- Required for REFRESH CONCURRENTLY
CREATE UNIQUE INDEX IF NOT EXISTS idx_pubkey_counts_by_relay_composite
ON pubkey_counts_by_relay USING btree (pubkey, relay_url);

-- Filter by relay: WHERE relay_url = ?
CREATE INDEX IF NOT EXISTS idx_pubkey_counts_by_relay_relay
ON pubkey_counts_by_relay USING btree (relay_url);
