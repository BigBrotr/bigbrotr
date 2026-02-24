/*
 * LilBrotr - 08_indexes.sql
 *
 * Performance indexes for tables and materialized views. LilBrotr uses
 * a simpler event/event_relay index set than BigBrotr since the event
 * table has fewer columns.
 *
 * Dependencies: 02_tables.sql
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
CREATE INDEX IF NOT EXISTS idx_relay_metadata_metadata_id
ON relay_metadata USING btree (metadata_id);

-- Latest metadata per relay and type:
-- WHERE relay_url = ? AND metadata_type = ? ORDER BY generated_at DESC LIMIT 1
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


-- ==========================================================================
-- MATERIALIZED VIEW INDEXES: network_stats
-- ==========================================================================

-- Required for REFRESH CONCURRENTLY
CREATE UNIQUE INDEX IF NOT EXISTS idx_network_stats_network
ON network_stats USING btree (network);


-- ==========================================================================
-- MATERIALIZED VIEW INDEXES: relay_software_counts
-- ==========================================================================

-- Required for REFRESH CONCURRENTLY
CREATE UNIQUE INDEX IF NOT EXISTS idx_relay_software_counts_composite
ON relay_software_counts USING btree (software, version);


-- ==========================================================================
-- MATERIALIZED VIEW INDEXES: supported_nip_counts
-- ==========================================================================

-- Required for REFRESH CONCURRENTLY
CREATE UNIQUE INDEX IF NOT EXISTS idx_supported_nip_counts_nip
ON supported_nip_counts USING btree (nip);


-- ==========================================================================
-- MATERIALIZED VIEW INDEXES: event_daily_counts
-- ==========================================================================

-- Required for REFRESH CONCURRENTLY
CREATE UNIQUE INDEX IF NOT EXISTS idx_event_daily_counts_day
ON event_daily_counts USING btree (day);
