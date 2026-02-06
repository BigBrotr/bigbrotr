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

-- Author timeline: WHERE pubkey = ? ORDER BY created_at DESC
-- Also covers pubkey-only lookups via leftmost prefix
CREATE INDEX IF NOT EXISTS idx_events_pubkey_created_at
ON events USING btree (pubkey, created_at DESC);

-- Author + kind + timeline: WHERE pubkey = ? AND kind = ? ORDER BY created_at DESC
-- Supports queries like "all text notes by this author, newest first"
CREATE INDEX IF NOT EXISTS idx_events_pubkey_kind_created_at
ON events USING btree (pubkey, kind, created_at DESC);

-- Tag value containment: WHERE tagvalues @> ARRAY['<value>']
-- Requires the btree_gin extension for GIN support on text arrays
CREATE INDEX IF NOT EXISTS idx_events_tagvalues
ON events USING gin (tagvalues);

-- Cursor-based pagination for the Finder service:
-- WHERE (created_at, id) > ($1, $2) ORDER BY created_at ASC, id ASC
CREATE INDEX IF NOT EXISTS idx_events_created_at_id_asc
ON events USING btree (created_at ASC, id ASC);


-- ==========================================================================
-- TABLE INDEXES: events_relays
-- ==========================================================================
-- The composite primary key (event_id, relay_url) already provides an
-- efficient B-tree index on event_id as the leftmost column, so no
-- separate event_id index is needed.

-- All events from a relay: WHERE relay_url = ?
CREATE INDEX IF NOT EXISTS idx_events_relays_relay_url
ON events_relays USING btree (relay_url);

-- Recently discovered events: ORDER BY seen_at DESC
CREATE INDEX IF NOT EXISTS idx_events_relays_seen_at
ON events_relays USING btree (seen_at DESC);

-- Synchronizer progress tracking: WHERE relay_url = ? ORDER BY seen_at DESC
-- Enables index-only scans for SELECT MAX(seen_at) WHERE relay_url = ?
CREATE INDEX IF NOT EXISTS idx_events_relays_relay_seen
ON events_relays USING btree (relay_url, seen_at DESC);


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


-- ==========================================================================
-- MATERIALIZED VIEW INDEXES: relay_metadata_latest
-- ==========================================================================

-- Required for REFRESH CONCURRENTLY (unique index on natural key)
CREATE UNIQUE INDEX IF NOT EXISTS idx_relay_metadata_latest_pk
ON relay_metadata_latest USING btree (relay_url, metadata_type);

-- Filter by check type: WHERE metadata_type = 'nip11_fetch'
CREATE INDEX IF NOT EXISTS idx_relay_metadata_latest_type
ON relay_metadata_latest USING btree (metadata_type);


-- ==========================================================================
-- MATERIALIZED VIEW INDEXES: events_statistics
-- ==========================================================================

-- Required for REFRESH CONCURRENTLY (single-row view uses dummy id)
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_statistics_id
ON events_statistics USING btree (id);


-- ==========================================================================
-- MATERIALIZED VIEW INDEXES: relays_statistics
-- ==========================================================================

-- Required for REFRESH CONCURRENTLY
CREATE UNIQUE INDEX IF NOT EXISTS idx_relays_statistics_url
ON relays_statistics USING btree (relay_url);

-- Filter by network: WHERE network = ?
CREATE INDEX IF NOT EXISTS idx_relays_statistics_network
ON relays_statistics USING btree (network);


-- ==========================================================================
-- MATERIALIZED VIEW INDEXES: kind_counts_total
-- ==========================================================================

-- Required for REFRESH CONCURRENTLY
CREATE UNIQUE INDEX IF NOT EXISTS idx_kind_counts_total_kind
ON kind_counts_total USING btree (kind);


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
-- MATERIALIZED VIEW INDEXES: pubkey_counts_total
-- ==========================================================================

-- Required for REFRESH CONCURRENTLY
CREATE UNIQUE INDEX IF NOT EXISTS idx_pubkey_counts_total_pubkey
ON pubkey_counts_total USING btree (pubkey_hex);


-- ==========================================================================
-- MATERIALIZED VIEW INDEXES: pubkey_counts_by_relay
-- ==========================================================================

-- Required for REFRESH CONCURRENTLY
CREATE UNIQUE INDEX IF NOT EXISTS idx_pubkey_counts_by_relay_composite
ON pubkey_counts_by_relay USING btree (pubkey_hex, relay_url);

-- Filter by relay: WHERE relay_url = ?
CREATE INDEX IF NOT EXISTS idx_pubkey_counts_by_relay_relay
ON pubkey_counts_by_relay USING btree (relay_url);
