/*
 * Template - 05_indexes.sql
 *
 * Performance indexes for tables. Based on common Nostr relay query patterns.
 * For minimal storage mode (events table with only id), remove the events
 * index section entirely since only the primary key index is needed.
 *
 * Dependencies: 02_tables.sql
 * Customization: YES -- adjust events indexes to match your table columns
 */


-- ==========================================================================
-- TABLE INDEXES: events
-- ==========================================================================

-- Author lookup: WHERE pubkey = ?
CREATE INDEX IF NOT EXISTS idx_events_pubkey
ON events USING btree (pubkey);

-- Global timeline queries: ORDER BY created_at DESC LIMIT N
CREATE INDEX IF NOT EXISTS idx_events_created_at
ON events USING btree (created_at DESC);

-- Kind filtering: WHERE kind = ? or WHERE kind IN (...)
CREATE INDEX IF NOT EXISTS idx_events_kind
ON events USING btree (kind);

-- Kind + timeline: WHERE kind = ? ORDER BY created_at DESC
CREATE INDEX IF NOT EXISTS idx_events_kind_created_at
ON events USING btree (kind, created_at DESC);

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
