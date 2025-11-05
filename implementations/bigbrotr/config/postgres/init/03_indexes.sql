-- ============================================================================
-- BigBrotr Database Initialization Script
-- ============================================================================
-- File: 03_indexes.sql
-- Description: All database indexes
-- Dependencies: 02_tables.sql
-- ============================================================================

-- Events table indexes
CREATE INDEX IF NOT EXISTS idx_events_pubkey
    ON events USING btree (pubkey);

CREATE INDEX IF NOT EXISTS idx_events_created_at
    ON events USING btree (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_events_kind
    ON events USING btree (kind);

CREATE INDEX IF NOT EXISTS idx_events_kind_created_at
    ON events USING btree (kind, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_events_pubkey_created_at
    ON events USING btree (pubkey, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_events_tagvalues
    ON events USING gin (tagvalues);

-- Events_relays table indexes
CREATE INDEX IF NOT EXISTS idx_events_relays_event_id
    ON events_relays USING btree (event_id);

CREATE INDEX IF NOT EXISTS idx_events_relays_relay_url
    ON events_relays USING btree (relay_url);

CREATE INDEX IF NOT EXISTS idx_events_relays_seen_at
    ON events_relays USING btree (seen_at DESC);

-- Composite index for MAX(seen_at) WHERE relay_url queries (critical for synchronizer)
CREATE INDEX IF NOT EXISTS idx_events_relays_relay_seen
    ON events_relays USING btree (relay_url, seen_at DESC);

-- NIP-66 data indexes
CREATE INDEX IF NOT EXISTS idx_nip66_openable
    ON nip66 USING btree (openable)
    WHERE openable = TRUE;

CREATE INDEX IF NOT EXISTS idx_nip66_readable
    ON nip66 USING btree (readable)
    WHERE readable = TRUE;

CREATE INDEX IF NOT EXISTS idx_nip66_writable
    ON nip66 USING btree (writable)
    WHERE writable = TRUE;

-- Relay metadata indexes
CREATE INDEX IF NOT EXISTS idx_relay_metadata_relay_url
    ON relay_metadata USING btree (relay_url);

CREATE INDEX IF NOT EXISTS idx_relay_metadata_generated_at
    ON relay_metadata USING btree (generated_at DESC);

CREATE INDEX IF NOT EXISTS idx_relay_metadata_nip11_id
    ON relay_metadata USING btree (nip11_id);

CREATE INDEX IF NOT EXISTS idx_relay_metadata_nip66_id
    ON relay_metadata USING btree (nip66_id);

-- Composite index for ROW_NUMBER() OVER (PARTITION BY relay_url ORDER BY generated_at) queries
CREATE INDEX IF NOT EXISTS idx_relay_metadata_url_generated
    ON relay_metadata USING btree (relay_url, generated_at DESC);

-- ============================================================================
-- INDEXES CREATED
-- ============================================================================