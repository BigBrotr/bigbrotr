/*
 * LilBrotr - 02_tables.sql
 *
 * Core database tables for lightweight Nostr relay archiving. LilBrotr
 * stores only essential event metadata (id, pubkey, created_at, kind) plus
 * computed tagvalues. The tags, content, and sig columns are omitted,
 * yielding approximately 60% disk savings compared to BigBrotr's full schema.
 *
 * Dependencies: None (tags_to_tagvalues is used by CRUD functions, not table definitions)
 */


-- ==========================================================================
-- relay: Registry of validated Nostr relays
-- ==========================================================================
-- Stores only relays that have passed WebSocket validation by the Validator
-- service. Each relay is identified by its unique WebSocket URL and tagged
-- with its network type for routing through the appropriate proxy.

CREATE TABLE IF NOT EXISTS relay (
    url TEXT PRIMARY KEY,
    network TEXT NOT NULL,
    discovered_at BIGINT NOT NULL
);

COMMENT ON TABLE relay IS 'Registry of validated Nostr relays across clearnet and overlay networks';
COMMENT ON COLUMN relay.url IS 'WebSocket URL (e.g., wss://relay.example.com)';
COMMENT ON COLUMN relay.network IS 'Network type: clearnet, tor, i2p, or loki';
COMMENT ON COLUMN relay.discovered_at IS 'Unix timestamp when first discovered and validated';


-- ==========================================================================
-- event: Lightweight Nostr event storage (no tags/content/sig)
-- ==========================================================================
-- Stores essential event metadata only. Binary fields (id, pubkey) use
-- BYTEA for 50% space savings vs hex CHAR(64). The tagvalues column is
-- computed at insert time by event_insert() using tags_to_tagvalues(),
-- then the original tags JSONB is discarded.
--
-- Omitted columns (compared to BigBrotr):
--   tags      JSONB  -- Full tag array (not stored)
--   content   TEXT   -- Event content (not stored)
--   sig       BYTEA  -- Schnorr signature (not stored)

CREATE TABLE IF NOT EXISTS event (
    id BYTEA PRIMARY KEY,
    pubkey BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    tagvalues TEXT []              -- Computed at insert time, not a generated column
);

COMMENT ON TABLE event IS 'Lightweight Nostr events (tagvalues only, no tags/content/sig)';
COMMENT ON COLUMN event.id IS 'SHA-256 event hash (32 bytes, stored as bytea from hex)';
COMMENT ON COLUMN event.pubkey IS 'Author public key (32 bytes, stored as bytea from hex)';
COMMENT ON COLUMN event.created_at IS 'Unix timestamp of event creation';
COMMENT ON COLUMN event.kind IS 'Event kind per NIP-01 (0=metadata, 1=text note, 3=contacts, etc.)';
COMMENT ON COLUMN event.tagvalues IS 'Tag values computed at insert time for GIN indexing';


-- ==========================================================================
-- event_relay: Event-to-relay junction table
-- ==========================================================================
-- Tracks which events were observed on which relays, with the timestamp of
-- first observation. The composite primary key prevents duplicate entries.
-- CASCADE deletes ensure cleanup when either side is removed.

CREATE TABLE IF NOT EXISTS event_relay (
    event_id BYTEA NOT NULL,
    relay_url TEXT NOT NULL,
    seen_at BIGINT NOT NULL,
    PRIMARY KEY (event_id, relay_url),
    FOREIGN KEY (event_id) REFERENCES event (id) ON DELETE CASCADE,
    FOREIGN KEY (relay_url) REFERENCES relay (url) ON DELETE CASCADE
);

COMMENT ON TABLE event_relay IS 'Tracks which events appear on which relays, with first-seen timestamps';
COMMENT ON COLUMN event_relay.event_id IS 'Foreign key to event.id';
COMMENT ON COLUMN event_relay.relay_url IS 'Foreign key to relay.url';
COMMENT ON COLUMN event_relay.seen_at IS 'Unix timestamp when event was first observed on this relay';


-- ==========================================================================
-- metadata: Content-addressed NIP-11 and NIP-66 document storage
-- ==========================================================================
-- Stores JSON metadata documents deduplicated by their SHA-256 content hash.
-- Multiple relays sharing identical metadata will reference the same row,
-- significantly reducing storage for common configurations.

CREATE TABLE IF NOT EXISTS metadata (
    id BYTEA PRIMARY KEY,
    payload JSONB NOT NULL
);

COMMENT ON TABLE metadata IS 'Content-addressed storage for NIP-11/NIP-66 metadata (deduplicated by SHA-256 hash)';
COMMENT ON COLUMN metadata.id IS 'SHA-256 hash of the JSON payload (content-addressed primary key)';
COMMENT ON COLUMN metadata.payload IS 'Complete JSON document (NIP-11 relay info or NIP-66 check result)';


-- ==========================================================================
-- relay_metadata: Time-series metadata snapshots per relay
-- ==========================================================================
-- Links relays to metadata documents over time, creating a history of health
-- check results. Each row represents one metadata snapshot for one relay at
-- one point in time. The metadata_type column distinguishes between different
-- check types (validated in application layer by MetadataType enum).

CREATE TABLE IF NOT EXISTS relay_metadata (
    relay_url TEXT NOT NULL,
    generated_at BIGINT NOT NULL,
    metadata_type TEXT NOT NULL,
    metadata_id BYTEA NOT NULL,

    PRIMARY KEY (relay_url, generated_at, metadata_type),
    FOREIGN KEY (relay_url) REFERENCES relay (url) ON DELETE CASCADE,
    FOREIGN KEY (metadata_id) REFERENCES metadata (id) ON DELETE CASCADE
);

COMMENT ON TABLE relay_metadata IS 'Time-series relay metadata snapshots linking relays to metadata documents';
COMMENT ON COLUMN relay_metadata.relay_url IS 'Foreign key to relay.url';
COMMENT ON COLUMN relay_metadata.generated_at IS 'Unix timestamp when the metadata was collected';
COMMENT ON COLUMN relay_metadata.metadata_type IS 'Check type: nip11_info, nip66_rtt, nip66_ssl, nip66_geo, nip66_net, nip66_dns, or nip66_http';
COMMENT ON COLUMN relay_metadata.metadata_id IS 'Foreign key to metadata.id (content-addressed hash)';


-- ==========================================================================
-- service_state: Persistent key-value store for service state
-- ==========================================================================
-- Generic JSONB storage for per-service operational data. Each service uses
-- this table to persist state between restarts:
--   - Finder: stores relay URL candidates awaiting validation
--   - Validator: tracks validation attempt counts per candidate
--   - Synchronizer: stores per-relay sync cursors (last synced timestamp)
--   - Monitor: stores health check scheduling state

CREATE TABLE IF NOT EXISTS service_state (
    service_name TEXT NOT NULL,
    state_type TEXT NOT NULL,
    state_key TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (service_name, state_type, state_key)
);

COMMENT ON TABLE service_state IS 'Per-service persistent state (candidates, cursors, checkpoints)';
COMMENT ON COLUMN service_state.service_name IS 'Service identifier (finder, validator, synchronizer, monitor)';
COMMENT ON COLUMN service_state.state_type IS 'State category (candidate, cursor, checkpoint, config)';
COMMENT ON COLUMN service_state.state_key IS 'Unique key within service+type (typically a relay URL or entity ID)';
COMMENT ON COLUMN service_state.payload IS 'JSONB payload specific to the service and state type';
COMMENT ON COLUMN service_state.updated_at IS 'Unix timestamp of last update';
