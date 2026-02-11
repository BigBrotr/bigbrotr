/*
 * Template - 05_indexes.sql
 *
 * Performance indexes for tables. Based on common Nostr relay query patterns.
 * For minimal storage mode (event table with only id), remove the event
 * index section entirely since only the primary key index is needed.
 *
 * Dependencies: 02_tables.sql
 * Customization: YES -- adjust event indexes to match your table columns
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

-- All events from a relay: WHERE relay_url = ?
CREATE INDEX IF NOT EXISTS idx_event_relay_relay_url
ON event_relay USING btree (relay_url);

-- All relays for an event: WHERE event_id = ?
CREATE INDEX IF NOT EXISTS idx_event_relay_event_id
ON event_relay USING btree (event_id);


-- ==========================================================================
-- TABLE INDEXES: relay_metadata
-- ==========================================================================

-- Recent health checks: ORDER BY generated_at DESC
CREATE INDEX IF NOT EXISTS idx_relay_metadata_generated_at
ON relay_metadata USING btree (generated_at DESC);

-- Content-addressed lookups: WHERE metadata_id = ?
-- Also used by orphan_metadata_delete() to verify references
CREATE INDEX IF NOT EXISTS idx_relay_metadata_metadata_id
ON relay_metadata USING btree (metadata_id);

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

-- Candidate network filtering: WHERE payload->>'network' = ANY($3)
-- Used by count_candidates() and fetch_candidate_chunk() in the Validator service
CREATE INDEX IF NOT EXISTS idx_service_state_candidate_network
ON service_state USING btree ((payload ->> 'network'))
WHERE service_name = 'validator' AND state_type = 'candidate';
