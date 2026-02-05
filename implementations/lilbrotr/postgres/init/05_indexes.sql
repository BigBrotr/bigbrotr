-- ============================================================================
-- LilBrotr Database Initialization Script
-- ============================================================================
-- File: 05_indexes.sql
-- Purpose: Performance indexes for user queries
-- Dependencies: 02_tables.sql
-- ============================================================================


-- ============================================================================
-- TABLE INDEXES: events
-- ============================================================================

-- Timeline: ORDER BY created_at DESC
CREATE INDEX IF NOT EXISTS idx_events_created_at
ON events USING btree (created_at DESC);

-- Filter: WHERE kind = ?
CREATE INDEX IF NOT EXISTS idx_events_kind
ON events USING btree (kind);

-- Filter + Timeline: WHERE kind = ? ORDER BY created_at DESC
CREATE INDEX IF NOT EXISTS idx_events_kind_created_at
ON events USING btree (kind, created_at DESC);

-- Author lookup: WHERE pubkey = ?
CREATE INDEX IF NOT EXISTS idx_events_pubkey
ON events USING btree (pubkey);

-- Tag search: WHERE tagvalues @> ARRAY['<tag-value>']
CREATE INDEX IF NOT EXISTS idx_events_tagvalues
ON events USING gin (tagvalues);


-- ============================================================================
-- TABLE INDEXES: events_relays
-- ============================================================================

-- Events per Relay: WHERE relay_url = ?
CREATE INDEX IF NOT EXISTS idx_events_relays_relay_url
ON events_relays USING btree (relay_url);

-- Relays per Event: WHERE event_id = ?
CREATE INDEX IF NOT EXISTS idx_events_relays_event_id
ON events_relays USING btree (event_id);


-- ============================================================================
-- TABLE INDEXES: relay_metadata
-- ============================================================================

-- Timeline: ORDER BY generated_at DESC
CREATE INDEX IF NOT EXISTS idx_relay_metadata_generated_at
ON relay_metadata USING btree (generated_at DESC);

-- Metadata lookup: WHERE metadata_id = ?
CREATE INDEX IF NOT EXISTS idx_relay_metadata_metadata_id
ON relay_metadata USING btree (metadata_id);

-- Latest per metadata_type: WHERE relay_url = ? AND metadata_type = ? ORDER BY generated_at DESC LIMIT 1
CREATE INDEX IF NOT EXISTS idx_relay_metadata_url_type_generated
ON relay_metadata USING btree (relay_url, metadata_type, generated_at DESC);

-- ============================================================================
-- INDEXES CREATED
-- ============================================================================
