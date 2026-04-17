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
-- TABLE INDEXES: event_observation
-- ==========================================================================
-- The composite primary key (event_id, relay_url) already provides an
-- efficient B-tree index on event_id as the leftmost column, so no
-- separate event_id index is needed.

-- Global observed_at ordering for API queries: ORDER BY observed_at DESC
CREATE INDEX IF NOT EXISTS idx_event_observation_observed_at
ON event_observation USING btree (observed_at DESC);

-- Finder cursor pagination: WHERE relay_url = $1
--   AND (observed_at, event_id) > ($2, $3) ORDER BY observed_at ASC, event_id ASC
-- Three-column covering index resolves the composite cursor entirely
-- from the index without joining to event for tie-breaking.
-- Also covers relay_url-only lookups via leftmost prefix.
CREATE INDEX IF NOT EXISTS idx_event_observation_relay_url_observed_at_event_id
ON event_observation USING btree (relay_url, observed_at ASC, event_id ASC);

-- ==========================================================================
-- TABLE INDEXES: relay_document
-- ==========================================================================

-- Recent relay-document associations: ORDER BY associated_at DESC
CREATE INDEX IF NOT EXISTS idx_relay_document_associated_at
ON relay_document USING btree (associated_at DESC);

-- Compound FK lookups: WHERE document_id = ? AND role = ?
-- Also used by orphan_document_delete() to verify references
CREATE INDEX IF NOT EXISTS idx_relay_document_document_id_role
ON relay_document USING btree (document_id, role);

-- Latest document per relay and role (powers relay_document_current refresh):
-- WHERE relay_url = ? AND role = ? ORDER BY associated_at DESC
-- Also covers (relay_url) and (relay_url, role) via leftmost prefix
CREATE INDEX IF NOT EXISTS idx_relay_document_relay_url_role_associated_at
ON relay_document USING btree (relay_url, role, associated_at DESC);


-- ==========================================================================
-- TABLE INDEXES: service_state
-- ==========================================================================

-- Candidate network filtering: WHERE state_value->>'network' = ANY($3)
-- Used by count_candidates() and fetch_candidates() in the Validator service.
-- Partial index: only validator checkpoint rows contain the 'network' key.
CREATE INDEX IF NOT EXISTS idx_service_state_candidate_network
ON service_state USING btree ((state_value ->> 'network'))
WHERE service_name = 'validator' AND state_type = 'checkpoint';
