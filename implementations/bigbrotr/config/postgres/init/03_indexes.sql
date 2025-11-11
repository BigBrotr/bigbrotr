-- ============================================================================
-- BigBrotr Database Initialization Script
-- ============================================================================
-- File: 03_indexes.sql
-- Description: All database indexes
-- Dependencies: 02_tables.sql
-- ============================================================================

-- ============================================================================
-- Events table indexes
-- Purpose: Optimize common query patterns for event retrieval
-- ============================================================================

-- Index: idx_events_pubkey
-- Purpose: Fast lookups by author public key (user timeline queries)
-- Usage: WHERE pubkey = ? ORDER BY created_at DESC
CREATE INDEX IF NOT EXISTS idx_events_pubkey
    ON events USING btree (pubkey);

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
CREATE INDEX IF NOT EXISTS idx_events_pubkey_created_at
    ON events USING btree (pubkey, created_at DESC);

-- Index: idx_events_tagvalues
-- Purpose: Fast tag-based queries using GIN index on computed tagvalues array
-- Usage: WHERE tagvalues @> ARRAY['value'] (finds events with specific tag values)
-- Note: Uses btree_gin extension for efficient array containment queries
CREATE INDEX IF NOT EXISTS idx_events_tagvalues
    ON events USING gin (tagvalues);

-- ============================================================================
-- Events_relays junction table indexes
-- Purpose: Optimize relay-event relationship queries
-- ============================================================================

-- Index: idx_events_relays_event_id
-- Purpose: Fast lookup of all relays hosting a specific event
-- Usage: WHERE event_id = ? (find which relays have an event)
CREATE INDEX IF NOT EXISTS idx_events_relays_event_id
    ON events_relays USING btree (event_id);

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
-- NIP-66 relay test results indexes
-- Purpose: Quickly identify relays by their capabilities
-- ============================================================================

-- Index: idx_nip66_openable
-- Purpose: Find relays that accept WebSocket connections
-- Usage: WHERE openable = TRUE (monitor service relay selection)
-- Note: Partial index only includes TRUE values for efficiency
CREATE INDEX IF NOT EXISTS idx_nip66_openable
    ON nip66 USING btree (openable)
    WHERE openable = TRUE;

-- Index: idx_nip66_readable
-- Purpose: Find relays that respond to REQ messages
-- Usage: WHERE readable = TRUE (synchronizer service relay selection)
-- Note: Partial index only includes TRUE values for efficiency
CREATE INDEX IF NOT EXISTS idx_nip66_readable
    ON nip66 USING btree (readable)
    WHERE readable = TRUE;

-- Index: idx_nip66_writable
-- Purpose: Find relays that accept EVENT messages
-- Usage: WHERE writable = TRUE (publisher service relay selection)
-- Note: Partial index only includes TRUE values for efficiency
CREATE INDEX IF NOT EXISTS idx_nip66_writable
    ON nip66 USING btree (writable)
    WHERE writable = TRUE;

-- ============================================================================
-- Relay metadata indexes
-- Purpose: Optimize metadata history and snapshot queries
-- ============================================================================

-- Index: idx_relay_metadata_relay_url
-- Purpose: Find all metadata snapshots for a specific relay
-- Usage: WHERE relay_url = ? (relay history queries)
CREATE INDEX IF NOT EXISTS idx_relay_metadata_relay_url
    ON relay_metadata USING btree (relay_url);

-- Index: idx_relay_metadata_generated_at
-- Purpose: Find most recent metadata snapshots across all relays
-- Usage: ORDER BY generated_at DESC (recent health check results)
CREATE INDEX IF NOT EXISTS idx_relay_metadata_generated_at
    ON relay_metadata USING btree (generated_at DESC);

-- Index: idx_relay_metadata_nip11_id
-- Purpose: Find all relays sharing the same NIP-11 information
-- Usage: WHERE nip11_id = ? (deduplication verification)
CREATE INDEX IF NOT EXISTS idx_relay_metadata_nip11_id
    ON relay_metadata USING btree (nip11_id);

-- Index: idx_relay_metadata_nip66_id
-- Purpose: Find all relays with identical NIP-66 test results
-- Usage: WHERE nip66_id = ? (performance clustering)
CREATE INDEX IF NOT EXISTS idx_relay_metadata_nip66_id
    ON relay_metadata USING btree (nip66_id);

-- Index: idx_relay_metadata_url_generated (CRITICAL FOR VIEWS)
-- Purpose: Efficient window functions and latest metadata lookups
-- Usage: ROW_NUMBER() OVER (PARTITION BY relay_url ORDER BY generated_at DESC)
-- Note: Powers the relay_metadata_latest view with index-only scans
CREATE INDEX IF NOT EXISTS idx_relay_metadata_url_generated
    ON relay_metadata USING btree (relay_url, generated_at DESC);

-- ============================================================================
-- INDEXES CREATED
-- ============================================================================