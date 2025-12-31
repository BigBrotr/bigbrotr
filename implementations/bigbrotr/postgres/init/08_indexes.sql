-- ============================================================================
-- BigBrotr Database Initialization Script
-- ============================================================================
-- File: 08_indexes.sql
-- Description: All database indexes (tables and materialized views)
-- Dependencies: 02_tables.sql, 06_materialized_views.sql
-- ============================================================================

-- ============================================================================
-- TABLE INDEXES: events
-- Purpose: Optimize common query patterns for event retrieval
-- ============================================================================

-- Index: idx_events_created_at
-- Purpose: Fast retrieval of recent events (global timeline queries)
-- Usage: ORDER BY created_at DESC LIMIT ?
CREATE INDEX IF NOT EXISTS idx_events_created_at
ON events USING btree (created_at DESC);

-- Index: idx_events_kind
-- Purpose: Filter events by type (e.g., metadata, text notes, reactions)
-- Usage: WHERE kind = ? or WHERE kind IN (?, ?, ?)
CREATE INDEX IF NOT EXISTS idx_events_kind
ON events USING btree (kind);

-- Index: idx_events_kind_created_at
-- Purpose: Efficient retrieval of recent events of specific types
-- Usage: WHERE kind = ? ORDER BY created_at DESC
CREATE INDEX IF NOT EXISTS idx_events_kind_created_at
ON events USING btree (kind, created_at DESC);

-- Index: idx_events_pubkey_created_at
-- Purpose: Efficient user timeline queries with chronological ordering
-- Usage: WHERE pubkey = ? ORDER BY created_at DESC
-- Note: Also covers queries on pubkey alone (leftmost prefix)
CREATE INDEX IF NOT EXISTS idx_events_pubkey_created_at
ON events USING btree (pubkey, created_at DESC);

-- Index: idx_events_pubkey_kind_created_at
-- Purpose: Efficient queries filtering by both author and event type
-- Usage: WHERE pubkey = ? AND kind = ? ORDER BY created_at DESC
-- Note: Critical for user-specific event type queries (e.g., user's text notes only)
CREATE INDEX IF NOT EXISTS idx_events_pubkey_kind_created_at
ON events USING btree (pubkey, kind, created_at DESC);

-- Index: idx_events_tagvalues
-- Purpose: Fast tag-based queries using GIN index on computed tagvalues array
-- Usage: WHERE tagvalues @> ARRAY['value'] (finds events with specific tag values)
-- Note: Uses btree_gin extension for efficient array containment queries
CREATE INDEX IF NOT EXISTS idx_events_tagvalues
ON events USING gin (tagvalues);

-- ============================================================================
-- TABLE INDEXES: events_relays
-- Purpose: Optimize relay-event relationship queries
-- ============================================================================

-- Note: No separate index on event_id needed - the composite primary key
-- (event_id, relay_url) already supports efficient lookups on event_id alone
-- since it's the leftmost column in the B-tree index.

-- Index: idx_events_relays_relay_url
-- Purpose: Fast lookup of all events from a specific relay
-- Usage: WHERE relay_url = ? (list events from a relay)
CREATE INDEX IF NOT EXISTS idx_events_relays_relay_url
ON events_relays USING btree (relay_url);

-- Index: idx_events_relays_seen_at
-- Purpose: Find recently discovered events across all relays
-- Usage: ORDER BY seen_at DESC LIMIT ? (global recent activity)
CREATE INDEX IF NOT EXISTS idx_events_relays_seen_at
ON events_relays USING btree (seen_at DESC);

-- Index: idx_events_relays_relay_seen (CRITICAL FOR SYNCHRONIZER)
-- Purpose: Efficiently find the most recent event from each relay
-- Usage: SELECT MAX(seen_at) WHERE relay_url = ? (sync progress tracking)
-- Note: Composite index enables index-only scans for synchronization queries
CREATE INDEX IF NOT EXISTS idx_events_relays_relay_seen
ON events_relays USING btree (relay_url, seen_at DESC);

-- ============================================================================
-- TABLE INDEXES: relay_metadata
-- Purpose: Optimize metadata history and snapshot queries
-- ============================================================================

-- Index: idx_relay_metadata_snapshot_at
-- Purpose: Find most recent metadata snapshots across all relays
-- Usage: ORDER BY snapshot_at DESC (recent health check results)
CREATE INDEX IF NOT EXISTS idx_relay_metadata_snapshot_at
ON relay_metadata USING btree (snapshot_at DESC);

-- Index: idx_relay_metadata_metadata_id
-- Purpose: Find all relays sharing the same metadata document
-- Usage: WHERE metadata_id = ? (deduplication verification, content-addressed lookups)
CREATE INDEX IF NOT EXISTS idx_relay_metadata_metadata_id
ON relay_metadata USING btree (metadata_id);

-- Index: idx_relay_metadata_url_type_snapshot (CRITICAL FOR VIEWS)
-- Purpose: Efficient window functions and latest metadata lookups per type
-- Usage: ROW_NUMBER() OVER (PARTITION BY relay_url, type ORDER BY snapshot_at DESC)
-- Note: Powers the relay_metadata_latest view with index-only scans
-- Note: This index covers queries on (relay_url), (relay_url, type), and (relay_url, type, snapshot_at)
CREATE INDEX IF NOT EXISTS idx_relay_metadata_url_type_snapshot
ON relay_metadata USING btree (relay_url, type, snapshot_at DESC);

-- ============================================================================
-- TABLE INDEXES: service_data
-- Purpose: Optimize service operational data queries
-- ============================================================================

-- Index: idx_service_data_service_name
-- Purpose: Fast lookup of all data for a specific service
-- Usage: WHERE service_name = ? (list all data for a service)
CREATE INDEX IF NOT EXISTS idx_service_data_service_name
ON service_data USING btree (service_name);

-- Index: idx_service_data_service_type
-- Purpose: Fast lookup of specific data type within a service
-- Usage: WHERE service_name = ? AND data_type = ? (e.g., all finder candidates)
CREATE INDEX IF NOT EXISTS idx_service_data_service_type
ON service_data USING btree (service_name, data_type);

-- ============================================================================
-- MATERIALIZED VIEW INDEXES: relay_metadata_latest
-- Purpose: Optimize materialized view queries
-- ============================================================================

-- Index: idx_relay_metadata_latest_url (CRITICAL FOR REFRESH CONCURRENTLY)
-- Purpose: Unique index required for REFRESH MATERIALIZED VIEW CONCURRENTLY
-- Usage: REFRESH MATERIALIZED VIEW CONCURRENTLY relay_metadata_latest
-- Note: Must be unique for concurrent refresh to work
CREATE UNIQUE INDEX IF NOT EXISTS idx_relay_metadata_latest_url
ON relay_metadata_latest USING btree (relay_url);

-- Index: idx_relay_metadata_latest_network
-- Purpose: Fast filtering by network type (clearnet/tor)
-- Usage: WHERE network = ? (filter relays by network)
CREATE INDEX IF NOT EXISTS idx_relay_metadata_latest_network
ON relay_metadata_latest USING btree (network);

-- Index: idx_relay_metadata_latest_openable
-- Purpose: Fast lookup of openable relays
-- Usage: WHERE is_openable = TRUE (find working relays)
-- Note: Partial index only on TRUE values for efficiency
CREATE INDEX IF NOT EXISTS idx_relay_metadata_latest_openable
ON relay_metadata_latest USING btree (is_openable) WHERE is_openable = TRUE;

-- ============================================================================
-- MATERIALIZED VIEW INDEXES: events_statistics
-- Purpose: Optimize statistics view queries
-- ============================================================================

-- Index: idx_events_statistics_id (CRITICAL FOR REFRESH CONCURRENTLY)
-- Purpose: Unique index required for REFRESH MATERIALIZED VIEW CONCURRENTLY
-- Usage: REFRESH MATERIALIZED VIEW CONCURRENTLY events_statistics
-- Note: Single-row view uses dummy id column
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_statistics_id
ON events_statistics USING btree (id);

-- ============================================================================
-- MATERIALIZED VIEW INDEXES: relays_statistics
-- Purpose: Optimize per-relay statistics queries
-- ============================================================================

-- Index: idx_relays_statistics_url (CRITICAL FOR REFRESH CONCURRENTLY)
-- Purpose: Unique index required for REFRESH MATERIALIZED VIEW CONCURRENTLY
-- Usage: REFRESH MATERIALIZED VIEW CONCURRENTLY relays_statistics
CREATE UNIQUE INDEX IF NOT EXISTS idx_relays_statistics_url
ON relays_statistics USING btree (relay_url);

-- Index: idx_relays_statistics_network
-- Purpose: Fast filtering by network type
-- Usage: WHERE network = ?
CREATE INDEX IF NOT EXISTS idx_relays_statistics_network
ON relays_statistics USING btree (network);

-- ============================================================================
-- MATERIALIZED VIEW INDEXES: kind_counts_total
-- Purpose: Optimize event kind distribution queries
-- ============================================================================

-- Index: idx_kind_counts_total_kind (CRITICAL FOR REFRESH CONCURRENTLY)
-- Purpose: Unique index required for REFRESH MATERIALIZED VIEW CONCURRENTLY
-- Usage: REFRESH MATERIALIZED VIEW CONCURRENTLY kind_counts_total
CREATE UNIQUE INDEX IF NOT EXISTS idx_kind_counts_total_kind
ON kind_counts_total USING btree (kind);

-- ============================================================================
-- MATERIALIZED VIEW INDEXES: kind_counts_by_relay
-- Purpose: Optimize per-relay event kind distribution queries
-- ============================================================================

-- Index: idx_kind_counts_by_relay_composite (CRITICAL FOR REFRESH CONCURRENTLY)
-- Purpose: Unique index required for REFRESH MATERIALIZED VIEW CONCURRENTLY
-- Usage: REFRESH MATERIALIZED VIEW CONCURRENTLY kind_counts_by_relay
-- Note: Composite unique index on (kind, relay_url)
CREATE UNIQUE INDEX IF NOT EXISTS idx_kind_counts_by_relay_composite
ON kind_counts_by_relay USING btree (kind, relay_url);

-- Index: idx_kind_counts_by_relay_relay
-- Purpose: Fast filtering by relay
-- Usage: WHERE relay_url = ?
CREATE INDEX IF NOT EXISTS idx_kind_counts_by_relay_relay
ON kind_counts_by_relay USING btree (relay_url);

-- ============================================================================
-- MATERIALIZED VIEW INDEXES: pubkey_counts_total
-- Purpose: Optimize author activity queries
-- ============================================================================

-- Index: idx_pubkey_counts_total_pubkey (CRITICAL FOR REFRESH CONCURRENTLY)
-- Purpose: Unique index required for REFRESH MATERIALIZED VIEW CONCURRENTLY
-- Usage: REFRESH MATERIALIZED VIEW CONCURRENTLY pubkey_counts_total
CREATE UNIQUE INDEX IF NOT EXISTS idx_pubkey_counts_total_pubkey
ON pubkey_counts_total USING btree (pubkey_hex);

-- ============================================================================
-- MATERIALIZED VIEW INDEXES: pubkey_counts_by_relay
-- Purpose: Optimize per-relay author activity queries
-- ============================================================================

-- Index: idx_pubkey_counts_by_relay_composite (CRITICAL FOR REFRESH CONCURRENTLY)
-- Purpose: Unique index required for REFRESH MATERIALIZED VIEW CONCURRENTLY
-- Usage: REFRESH MATERIALIZED VIEW CONCURRENTLY pubkey_counts_by_relay
-- Note: Composite unique index on (pubkey_hex, relay_url)
CREATE UNIQUE INDEX IF NOT EXISTS idx_pubkey_counts_by_relay_composite
ON pubkey_counts_by_relay USING btree (pubkey_hex, relay_url);

-- Index: idx_pubkey_counts_by_relay_relay
-- Purpose: Fast filtering by relay
-- Usage: WHERE relay_url = ?
CREATE INDEX IF NOT EXISTS idx_pubkey_counts_by_relay_relay
ON pubkey_counts_by_relay USING btree (relay_url);

-- ============================================================================
-- INDEXES CREATED
-- ============================================================================
