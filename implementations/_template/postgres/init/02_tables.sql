-- ============================================================================
-- BigBrotr Implementation Template - Database Tables
-- ============================================================================
-- File: 02_tables.sql
-- Purpose: Core database tables for Nostr data storage
-- Dependencies: 01_functions_utility.sql (only if using generated column for tagvalues)
-- Customization: YES - events table columns can be customized
-- ============================================================================


-- ----------------------------------------------------------------------------
-- Table: relays
-- Description: Registry of all validated Nostr relays
-- Customization: None - this table structure is mandatory
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS relays (
    url TEXT PRIMARY KEY,                    -- WebSocket URL (e.g., wss://relay.example.com)
    network TEXT NOT NULL,                   -- Network type: clearnet, tor, i2p, loki
    discovered_at BIGINT NOT NULL            -- Unix timestamp when first discovered
);

COMMENT ON TABLE relays IS 'Registry of validated Nostr relays across all networks';
COMMENT ON COLUMN relays.url IS 'WebSocket URL of the relay (e.g., wss://relay.example.com)';
COMMENT ON COLUMN relays.network IS 'Network type: clearnet, tor, i2p, or loki';
COMMENT ON COLUMN relays.discovered_at IS 'Unix timestamp when relay was first discovered and validated';


-- ----------------------------------------------------------------------------
-- Table: events
-- Description: Stores Nostr events
-- Customization: YES - only 'id' column is mandatory
-- ----------------------------------------------------------------------------
--
-- MANDATORY:
--   id BYTEA PRIMARY KEY     -- Required for events_relays foreign key
--
-- OPTIONAL (add any columns you need):
--   pubkey BYTEA             -- Author public key
--   created_at BIGINT        -- Event timestamp
--   kind INTEGER             -- Event type (NIP-01)
--   tags JSONB               -- Full tag array
--   tagvalues TEXT[]         -- Computed or stored tag values for indexing
--   content TEXT             -- Event content
--   sig BYTEA                -- Event signature
--
-- EXAMPLES:
--
-- Minimal (just tracking event IDs per relay):
--   CREATE TABLE events (id BYTEA PRIMARY KEY);
--
-- Lightweight (metadata + tag filtering, ~60% disk savings):
--   CREATE TABLE events (
--       id BYTEA PRIMARY KEY,
--       pubkey BYTEA NOT NULL,
--       created_at BIGINT NOT NULL,
--       kind INTEGER NOT NULL,
--       tagvalues TEXT[]
--   );
--
-- Full storage (complete event reconstruction):
--   CREATE TABLE events (
--       id BYTEA PRIMARY KEY,
--       pubkey BYTEA NOT NULL,
--       created_at BIGINT NOT NULL,
--       kind INTEGER NOT NULL,
--       tags JSONB NOT NULL,
--       tagvalues TEXT[] GENERATED ALWAYS AS (tags_to_tagvalues(tags)) STORED,
--       content TEXT NOT NULL,
--       sig BYTEA NOT NULL
--   );
--
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    id BYTEA PRIMARY KEY,
    pubkey BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    tags JSONB NOT NULL,
    tagvalues TEXT[] GENERATED ALWAYS AS (tags_to_tagvalues(tags)) STORED,
    content TEXT NOT NULL,
    sig BYTEA NOT NULL
);

COMMENT ON TABLE events IS 'Nostr events with computed tag values for efficient querying';
COMMENT ON COLUMN events.id IS 'SHA-256 hash of serialized event (stored as bytea)';
COMMENT ON COLUMN events.pubkey IS 'Author public key (stored as bytea)';
COMMENT ON COLUMN events.created_at IS 'Unix timestamp when event was created';
COMMENT ON COLUMN events.kind IS 'Event kind per NIP-01 (0=metadata, 1=text, 3=contacts, etc.)';
COMMENT ON COLUMN events.tags IS 'JSONB array of [key, value, ...] arrays per NIP-01';
COMMENT ON COLUMN events.tagvalues IS 'Computed array of single-char tag values for GIN indexing';
COMMENT ON COLUMN events.content IS 'Event content (plaintext or encrypted depending on kind)';
COMMENT ON COLUMN events.sig IS 'Schnorr signature over event fields (stored as bytea)';


-- ----------------------------------------------------------------------------
-- Table: events_relays
-- Description: Junction table tracking which events are on which relays
-- Customization: None - this table structure is mandatory
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events_relays (
    event_id BYTEA NOT NULL,
    relay_url TEXT NOT NULL,
    seen_at BIGINT NOT NULL,
    PRIMARY KEY (event_id, relay_url),
    FOREIGN KEY (event_id) REFERENCES events (id) ON DELETE CASCADE,
    FOREIGN KEY (relay_url) REFERENCES relays (url) ON DELETE CASCADE
);

COMMENT ON TABLE events_relays IS 'Junction table tracking event-relay relationships with timestamps';
COMMENT ON COLUMN events_relays.event_id IS 'Reference to events.id';
COMMENT ON COLUMN events_relays.relay_url IS 'Reference to relays.url';
COMMENT ON COLUMN events_relays.seen_at IS 'Unix timestamp when event was first seen on this relay';


-- ----------------------------------------------------------------------------
-- Table: metadata
-- Description: Content-addressed storage for NIP-11 and NIP-66 data
-- Customization: None - this table structure is mandatory
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metadata (
    id BYTEA PRIMARY KEY,                    -- SHA-256 hash of metadata (computed in DB)
    metadata JSONB NOT NULL                  -- Complete JSON document
);

COMMENT ON TABLE metadata IS 'Unified storage for NIP-11/NIP-66 metadata (deduplicated by content hash)';
COMMENT ON COLUMN metadata.id IS 'SHA-256 hash of JSON data (content-addressed)';
COMMENT ON COLUMN metadata.metadata IS 'Complete JSON document (NIP-11 or NIP-66 data)';


-- ----------------------------------------------------------------------------
-- Table: relay_metadata
-- Description: Time-series metadata snapshots linking relays to metadata
-- Customization: None - this table structure is mandatory
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS relay_metadata (
    relay_url TEXT NOT NULL,
    generated_at BIGINT NOT NULL,
    type TEXT NOT NULL,                      -- nip11_fetch, nip66_rtt, nip66_probe, nip66_ssl, nip66_geo, nip66_net, nip66_dns, nip66_http
    metadata_id BYTEA NOT NULL,
    PRIMARY KEY (relay_url, generated_at, type),
    FOREIGN KEY (relay_url) REFERENCES relays (url) ON DELETE CASCADE,
    FOREIGN KEY (metadata_id) REFERENCES metadata (id) ON DELETE CASCADE
);

COMMENT ON TABLE relay_metadata IS 'Time-series relay metadata snapshots (references metadata records by type)';
COMMENT ON COLUMN relay_metadata.relay_url IS 'Reference to relays.url';
COMMENT ON COLUMN relay_metadata.generated_at IS 'Unix timestamp when metadata was generated/collected';
COMMENT ON COLUMN relay_metadata.type IS 'Metadata type: nip11_fetch, nip66_rtt, nip66_probe, nip66_ssl, nip66_geo, nip66_net, nip66_dns, or nip66_http';
COMMENT ON COLUMN relay_metadata.metadata_id IS 'Reference to metadata.id';


-- ----------------------------------------------------------------------------
-- Table: service_data
-- Description: Per-service operational data (candidates, cursors, state)
-- Customization: None - this table structure is mandatory
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS service_data (
    service_name TEXT NOT NULL,              -- finder, validator, synchronizer, monitor
    data_type TEXT NOT NULL,                 -- candidate, cursor, checkpoint, config
    data_key TEXT NOT NULL,                  -- Usually relay URL or entity ID
    data JSONB NOT NULL DEFAULT '{}',
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (service_name, data_type, data_key)
);

COMMENT ON TABLE service_data IS 'Per-service operational data (candidates, cursors, checkpoints)';
COMMENT ON COLUMN service_data.service_name IS 'Name of the service (finder, validator, synchronizer, monitor)';
COMMENT ON COLUMN service_data.data_type IS 'Type of data (candidate, cursor, checkpoint, config)';
COMMENT ON COLUMN service_data.data_key IS 'Unique identifier within service/data_type (usually relay URL or entity ID)';
COMMENT ON COLUMN service_data.data IS 'JSONB data specific to the service and data type';
COMMENT ON COLUMN service_data.updated_at IS 'Unix timestamp when record was last updated';


-- ============================================================================
-- TABLES SUMMARY
-- ============================================================================
-- relays         : Validated relay registry (mandatory structure)
-- events         : Nostr events (only 'id' column mandatory)
-- events_relays  : Event-relay junction (mandatory structure)
-- metadata       : Content-addressed metadata (mandatory structure)
-- relay_metadata : Time-series metadata snapshots (mandatory structure)
-- service_data   : Service operational state (mandatory structure)
-- ============================================================================
