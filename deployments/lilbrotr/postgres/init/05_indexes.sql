/*
 * LilBrotr - 05_indexes.sql
 *
 * Performance indexes for tables. LilBrotr uses a simpler index set than
 * BigBrotr since it has no materialized views requiring unique indexes
 * for REFRESH CONCURRENTLY.
 *
 * Dependencies: 02_tables.sql
 */


-- ==========================================================================
-- TABLE INDEXES: event
-- ==========================================================================

-- Global timeline queries: ORDER BY created_at DESC LIMIT N
CREATE INDEX IF NOT EXISTS idx_event_created_at
ON event USING btree (created_at DESC);

-- Kind + timeline: WHERE kind = ? ORDER BY created_at DESC
-- Also covers kind-only lookups via leftmost prefix
CREATE INDEX IF NOT EXISTS idx_event_kind_created_at
ON event USING btree (kind, created_at DESC);

-- Author lookup: WHERE pubkey = ?
CREATE INDEX IF NOT EXISTS idx_event_pubkey
ON event USING btree (pubkey);

-- Tag value containment: WHERE tagvalues @> ARRAY['<value>']
-- Requires the btree_gin extension for GIN support on text arrays
CREATE INDEX IF NOT EXISTS idx_event_tagvalues
ON event USING gin (tagvalues);


-- ==========================================================================
-- TABLE INDEXES: event_relay
-- ==========================================================================

-- The composite PK (event_id, relay_url) covers event_id lookups via leftmost prefix.

-- All events from a relay: WHERE relay_url = ?
CREATE INDEX IF NOT EXISTS idx_event_relay_relay_url
ON event_relay USING btree (relay_url);


-- ==========================================================================
-- TABLE INDEXES: relay_metadata
-- ==========================================================================

-- Recent health checks: ORDER BY generated_at DESC
CREATE INDEX IF NOT EXISTS idx_relay_metadata_generated_at
ON relay_metadata USING btree (generated_at DESC);

-- Content-addressed lookups: WHERE metadata_id = ?
CREATE INDEX IF NOT EXISTS idx_relay_metadata_metadata_id
ON relay_metadata USING btree (metadata_id);

-- Latest metadata per relay and type:
-- WHERE relay_url = ? AND metadata_type = ? ORDER BY generated_at DESC LIMIT 1
CREATE INDEX IF NOT EXISTS idx_relay_metadata_relay_url_metadata_type_generated_at
ON relay_metadata USING btree (relay_url, metadata_type, generated_at DESC);


-- ==========================================================================
-- TABLE INDEXES: service_state
-- ==========================================================================
-- The PK (service_name, state_type, state_key) covers lookups on
-- (service_name) and (service_name, state_type) via leftmost prefix.

-- Candidate network filtering: WHERE state_value->>'network' = ANY($3)
-- Used by count_candidates() and fetch_candidate_chunk() in the Validator service
CREATE INDEX IF NOT EXISTS idx_service_state_candidate_network
ON service_state USING btree ((state_value ->> 'network'))
WHERE service_name = 'validator' AND state_type = 'candidate';
