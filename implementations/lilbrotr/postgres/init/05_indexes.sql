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
-- TABLE INDEXES: events
-- ==========================================================================

-- Global timeline queries: ORDER BY created_at DESC LIMIT N
CREATE INDEX IF NOT EXISTS idx_events_created_at
ON events USING btree (created_at DESC);

-- Kind filtering: WHERE kind = ? or WHERE kind IN (...)
CREATE INDEX IF NOT EXISTS idx_events_kind
ON events USING btree (kind);

-- Kind + timeline: WHERE kind = ? ORDER BY created_at DESC
CREATE INDEX IF NOT EXISTS idx_events_kind_created_at
ON events USING btree (kind, created_at DESC);

-- Author lookup: WHERE pubkey = ?
CREATE INDEX IF NOT EXISTS idx_events_pubkey
ON events USING btree (pubkey);

-- Tag value containment: WHERE tagvalues @> ARRAY['<value>']
-- Requires the btree_gin extension for GIN support on text arrays
CREATE INDEX IF NOT EXISTS idx_events_tagvalues
ON events USING gin (tagvalues);


-- ==========================================================================
-- TABLE INDEXES: events_relays
-- ==========================================================================

-- All events from a relay: WHERE relay_url = ?
CREATE INDEX IF NOT EXISTS idx_events_relays_relay_url
ON events_relays USING btree (relay_url);

-- All relays for an event: WHERE event_id = ?
CREATE INDEX IF NOT EXISTS idx_events_relays_event_id
ON events_relays USING btree (event_id);


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
CREATE INDEX IF NOT EXISTS idx_relay_metadata_url_type_generated
ON relay_metadata USING btree (relay_url, metadata_type, generated_at DESC);


-- ==========================================================================
-- TABLE INDEXES: service_data
-- ==========================================================================

-- All data for a service: WHERE service_name = ?
CREATE INDEX IF NOT EXISTS idx_service_data_service_name
ON service_data USING btree (service_name);

-- Specific data type within a service: WHERE service_name = ? AND data_type = ?
CREATE INDEX IF NOT EXISTS idx_service_data_service_type
ON service_data USING btree (service_name, data_type);

-- Candidate network filtering: WHERE data->>'network' = ANY($3)
-- Used by count_candidates() and fetch_candidate_chunk() in the Validator service
CREATE INDEX IF NOT EXISTS idx_service_data_candidate_network
ON service_data USING btree ((data->>'network'))
WHERE service_name = 'validator' AND data_type = 'candidate';
