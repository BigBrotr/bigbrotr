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


-- ----------------------------------------------------------------------------
-- Table: metadata
-- Description: Content-addressed storage for NIP-11 and NIP-66 data
-- Customization: None - this table structure is mandatory
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metadata (
    id BYTEA PRIMARY KEY,                    -- SHA-256 hash of data (computed in DB)
    data JSONB NOT NULL                      -- Complete JSON document
);


-- ----------------------------------------------------------------------------
-- Table: relay_metadata
-- Description: Time-series metadata snapshots linking relays to metadata
-- Customization: None - this table structure is mandatory
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS relay_metadata (
    relay_url TEXT NOT NULL,
    generated_at BIGINT NOT NULL,
    type TEXT NOT NULL,                      -- nip11, nip66_rtt, nip66_ssl, nip66_geo
    metadata_id BYTEA NOT NULL,
    PRIMARY KEY (relay_url, generated_at, type),
    FOREIGN KEY (relay_url) REFERENCES relays (url) ON DELETE CASCADE,
    FOREIGN KEY (metadata_id) REFERENCES metadata (id) ON DELETE CASCADE
);


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
