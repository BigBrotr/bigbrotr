/*
 * Brotr - 10_indexes_core.sql
 *
 * Performance indexes for core persisted tables.
 *
 * Dependencies: 02_tables_core.sql
 */

-- ==========================================================================
-- TABLE INDEXES: event
-- ==========================================================================

-- Global timeline with tie-breaking: ORDER BY created_at DESC, id DESC
-- Primary read pattern for event consumption. Covers single-column
-- created_at lookups via leftmost prefix (replaces standalone index).
-- Supports cursor pagination: WHERE (created_at, id) < ($1, $2)
CREATE INDEX IF NOT EXISTS idx_event_created_at_id
ON event USING btree (created_at DESC, id DESC);

-- Kind + timeline: WHERE kind = ? ORDER BY created_at DESC
-- Also covers kind-only lookups via leftmost prefix
CREATE INDEX IF NOT EXISTS idx_event_kind_created_at
ON event USING btree (kind, created_at DESC);

-- Author timeline: WHERE pubkey = ? ORDER BY created_at DESC
-- Also covers pubkey-only lookups via leftmost prefix
CREATE INDEX IF NOT EXISTS idx_event_pubkey_created_at
ON event USING btree (pubkey, created_at DESC);

-- Author + kind + timeline: WHERE pubkey = ? AND kind = ? ORDER BY created_at DESC
-- Supports queries like "all text notes by this author, newest first"
-- Also serves as a covering index for pubkey_kind_stats incremental
-- refresh (index-only scan: pubkey, kind, created_at are all included)
CREATE INDEX IF NOT EXISTS idx_event_pubkey_kind_created_at
ON event USING btree (pubkey, kind, created_at DESC);

-- Tag value containment: WHERE tagvalues @> ARRAY['e:<hex-id>']
-- Requires the btree_gin extension for GIN support on text arrays
CREATE INDEX IF NOT EXISTS idx_event_tagvalues
ON event USING gin (tagvalues);

-- ==========================================================================
-- TABLE INDEXES: event_relay
-- ==========================================================================
-- The composite primary key (event_id, relay_url) already provides an
-- efficient B-tree index on event_id as the leftmost column, so no
-- separate event_id index is needed.

-- Global seen_at ordering for API queries: ORDER BY seen_at DESC
CREATE INDEX IF NOT EXISTS idx_event_relay_seen_at
ON event_relay USING btree (seen_at DESC);

-- Finder cursor pagination: WHERE relay_url = $1
--   AND (seen_at, event_id) > ($2, $3) ORDER BY seen_at ASC, event_id ASC
-- Three-column covering index resolves the composite cursor entirely
-- from the index without joining to event for tie-breaking.
-- Also covers relay_url-only lookups via leftmost prefix.
CREATE INDEX IF NOT EXISTS idx_event_relay_relay_url_seen_at_event_id
ON event_relay USING btree (relay_url, seen_at ASC, event_id ASC);

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

-- Latest metadata per relay and type (powers relay_metadata_current refresh):
-- WHERE relay_url = ? AND metadata_type = ? ORDER BY generated_at DESC
-- Also covers (relay_url) and (relay_url, metadata_type) via leftmost prefix
CREATE INDEX IF NOT EXISTS idx_relay_metadata_relay_url_metadata_type_generated_at
ON relay_metadata USING btree (relay_url, metadata_type, generated_at DESC);


-- ==========================================================================
-- TABLE INDEXES: service_state
-- ==========================================================================

-- Candidate network filtering: WHERE state_value->>'network' = ANY($3)
-- Used by count_candidates() and fetch_candidates() in the Validator service.
-- Partial index: only validator checkpoint rows contain the 'network' key.
CREATE INDEX IF NOT EXISTS idx_service_state_candidate_network
ON service_state USING btree ((state_value ->> 'network'))
WHERE service_name = 'validator' AND state_type = 'checkpoint';
