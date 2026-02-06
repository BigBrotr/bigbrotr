/*
 * BigBrotr - 02_tables.sql
 *
 * Core database tables for Nostr relay archiving and monitoring.
 * BigBrotr uses full event storage: all NIP-01 fields are preserved,
 * enabling complete event reconstruction and tag-based queries.
 *
 * Dependencies: 01_functions_utility.sql (tags_to_tagvalues for generated column)
 */


-- ==========================================================================
-- relays: Registry of validated Nostr relays
-- ==========================================================================
-- Stores only relays that have passed WebSocket validation by the Validator
-- service. Each relay is identified by its unique WebSocket URL and tagged
-- with its network type for routing through the appropriate proxy.

CREATE TABLE IF NOT EXISTS relays (
    url TEXT PRIMARY KEY,
    network TEXT NOT NULL,
    discovered_at BIGINT NOT NULL
);

COMMENT ON TABLE relays IS 'Registry of validated Nostr relays across clearnet and overlay networks';
COMMENT ON COLUMN relays.url IS 'WebSocket URL (e.g., wss://relay.example.com)';
COMMENT ON COLUMN relays.network IS 'Network type: clearnet, tor, i2p, or loki';
COMMENT ON COLUMN relays.discovered_at IS 'Unix timestamp when first discovered and validated';


-- ==========================================================================
-- events: Full Nostr event storage with computed tag index
-- ==========================================================================
-- Stores complete NIP-01 events. Binary fields (id, pubkey, sig) use BYTEA
-- for 50% space savings compared to hex CHAR(64). The tagvalues column is
-- automatically computed from the tags JSONB via a generated column, enabling
-- efficient GIN index lookups without manual maintenance.

CREATE TABLE IF NOT EXISTS events (
    id BYTEA PRIMARY KEY,
    pubkey BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    tags JSONB NOT NULL,
    tagvalues TEXT [] GENERATED ALWAYS AS (tags_to_tagvalues(tags)) STORED,
    content TEXT NOT NULL,
    sig BYTEA NOT NULL
);

COMMENT ON TABLE events IS 'Complete Nostr events with computed tag values for efficient querying';
COMMENT ON COLUMN events.id IS 'SHA-256 event hash (32 bytes, stored as bytea from hex)';
COMMENT ON COLUMN events.pubkey IS 'Author public key (32 bytes, stored as bytea from hex)';
COMMENT ON COLUMN events.created_at IS 'Unix timestamp of event creation';
COMMENT ON COLUMN events.kind IS 'Event kind per NIP-01 (0=metadata, 1=text note, 3=contacts, etc.)';
COMMENT ON COLUMN events.tags IS 'JSONB array of [key, value, ...] tag arrays per NIP-01';
COMMENT ON COLUMN events.tagvalues IS 'Auto-computed array of single-char tag values for GIN indexing';
COMMENT ON COLUMN events.content IS 'Event content (plaintext or encrypted depending on kind)';
COMMENT ON COLUMN events.sig IS 'Schnorr signature (64 bytes, stored as bytea from hex)';


-- ==========================================================================
-- events_relays: Event-to-relay junction table
-- ==========================================================================
-- Tracks which events were observed on which relays, with the timestamp of
-- first observation. The composite primary key prevents duplicate entries.
-- CASCADE deletes ensure cleanup when either side is removed.

CREATE TABLE IF NOT EXISTS events_relays (
    event_id BYTEA NOT NULL,
    relay_url TEXT NOT NULL,
    seen_at BIGINT NOT NULL,
    PRIMARY KEY (event_id, relay_url),
    FOREIGN KEY (event_id) REFERENCES events (id) ON DELETE CASCADE,
    FOREIGN KEY (relay_url) REFERENCES relays (url) ON DELETE CASCADE
);

COMMENT ON TABLE events_relays IS 'Tracks which events appear on which relays, with first-seen timestamps';
COMMENT ON COLUMN events_relays.event_id IS 'Foreign key to events.id';
COMMENT ON COLUMN events_relays.relay_url IS 'Foreign key to relays.url';
COMMENT ON COLUMN events_relays.seen_at IS 'Unix timestamp when event was first observed on this relay';


-- ==========================================================================
-- metadata: Content-addressed NIP-11 and NIP-66 document storage
-- ==========================================================================
-- Stores JSON metadata documents deduplicated by their SHA-256 content hash.
-- Multiple relays sharing identical metadata will reference the same row,
-- significantly reducing storage for common configurations.

CREATE TABLE IF NOT EXISTS metadata (
    id BYTEA PRIMARY KEY,
    value JSONB NOT NULL
);

COMMENT ON TABLE metadata IS 'Content-addressed storage for NIP-11/NIP-66 metadata (deduplicated by SHA-256 hash)';
COMMENT ON COLUMN metadata.id IS 'SHA-256 hash of the JSON value (content-addressed primary key)';
COMMENT ON COLUMN metadata.value IS 'Complete JSON document (NIP-11 relay info or NIP-66 check result)';


-- ==========================================================================
-- relay_metadata: Time-series metadata snapshots per relay
-- ==========================================================================
-- Links relays to metadata documents over time, creating a history of health
-- check results. Each row represents one metadata snapshot for one relay at
-- one point in time. The metadata_type column distinguishes between different
-- check types: nip11_fetch, nip66_rtt, nip66_ssl, nip66_geo, nip66_net,
-- nip66_dns, nip66_http.

CREATE TABLE IF NOT EXISTS relay_metadata (
    relay_url TEXT NOT NULL,
    generated_at BIGINT NOT NULL,
    metadata_type TEXT NOT NULL,
    metadata_id BYTEA NOT NULL,

    PRIMARY KEY (relay_url, generated_at, metadata_type),
    FOREIGN KEY (relay_url) REFERENCES relays (url) ON DELETE CASCADE,
    FOREIGN KEY (metadata_id) REFERENCES metadata (id) ON DELETE CASCADE
);

COMMENT ON TABLE relay_metadata IS 'Time-series relay metadata snapshots linking relays to metadata documents';
COMMENT ON COLUMN relay_metadata.relay_url IS 'Foreign key to relays.url';
COMMENT ON COLUMN relay_metadata.generated_at IS 'Unix timestamp when the metadata was collected';
COMMENT ON COLUMN relay_metadata.metadata_type IS 'Check type: nip11_fetch, nip66_rtt, nip66_ssl, nip66_geo, nip66_net, nip66_dns, or nip66_http';
COMMENT ON COLUMN relay_metadata.metadata_id IS 'Foreign key to metadata.id (content-addressed hash)';


-- ==========================================================================
-- service_data: Persistent key-value store for service state
-- ==========================================================================
-- Generic JSONB storage for per-service operational data. Each service uses
-- this table to persist state between restarts:
--   - Finder: stores relay URL candidates awaiting validation
--   - Validator: tracks validation attempt counts per candidate
--   - Synchronizer: stores per-relay sync cursors (last synced timestamp)
--   - Monitor: stores health check scheduling state

CREATE TABLE IF NOT EXISTS service_data (
    service_name TEXT NOT NULL,
    data_type TEXT NOT NULL,
    data_key TEXT NOT NULL,
    data JSONB NOT NULL DEFAULT '{}',
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (service_name, data_type, data_key)
);

COMMENT ON TABLE service_data IS 'Per-service persistent state (candidates, cursors, checkpoints)';
COMMENT ON COLUMN service_data.service_name IS 'Service identifier (finder, validator, synchronizer, monitor)';
COMMENT ON COLUMN service_data.data_type IS 'Data category (candidate, cursor, checkpoint, config)';
COMMENT ON COLUMN service_data.data_key IS 'Unique key within service+type (typically a relay URL or entity ID)';
COMMENT ON COLUMN service_data.data IS 'JSONB payload specific to the service and data type';
COMMENT ON COLUMN service_data.updated_at IS 'Unix timestamp of last update';
