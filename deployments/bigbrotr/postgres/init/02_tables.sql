/*
 * Brotr - 02_tables.sql
 *
 * Core database tables for Nostr relay archiving and monitoring.
 * The event table is the primary customization point: only the id column
 * is mandatory. All other tables have fixed structures.
 *
 * Dependencies: None (tags_to_tagvalues is used by CRUD functions, not table definitions)
 * Customization: event table columns (see storage modes in events_table block)
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
-- event: Nostr event storage (CUSTOMIZABLE)
-- ==========================================================================
-- Only the id column (BYTEA PRIMARY KEY) is mandatory for the event_relay
-- foreign key. All other columns are optional. Customize the event_insert()
-- function in 03_functions_crud.sql to match your chosen schema.
--
-- Storage modes:
--
--   Minimal (tracking event IDs per relay only):
--     CREATE TABLE event (id BYTEA PRIMARY KEY);
--
--   Lightweight (metadata + tag filtering, ~60% disk savings):
--     CREATE TABLE event (
--         id BYTEA PRIMARY KEY,
--         pubkey BYTEA NOT NULL,
--         created_at BIGINT NOT NULL,
--         kind INTEGER NOT NULL,
--         tagvalues TEXT[]
--     );
--
--   Full (complete event reconstruction, used below):
--     Includes all NIP-01 fields with tagvalues computed at insert time.

CREATE TABLE IF NOT EXISTS event (
    id BYTEA NOT NULL,
    pubkey BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    tags JSONB NOT NULL,
    tagvalues TEXT [] NOT NULL,    -- Computed at insert time by event_insert()
    content TEXT NOT NULL,
    sig BYTEA NOT NULL,
    PRIMARY KEY (id)
) PARTITION BY HASH (id);

CREATE TABLE IF NOT EXISTS event_p0 PARTITION OF event
    FOR VALUES WITH (MODULUS 16, REMAINDER 0);
CREATE TABLE IF NOT EXISTS event_p1 PARTITION OF event
    FOR VALUES WITH (MODULUS 16, REMAINDER 1);
CREATE TABLE IF NOT EXISTS event_p2 PARTITION OF event
    FOR VALUES WITH (MODULUS 16, REMAINDER 2);
CREATE TABLE IF NOT EXISTS event_p3 PARTITION OF event
    FOR VALUES WITH (MODULUS 16, REMAINDER 3);
CREATE TABLE IF NOT EXISTS event_p4 PARTITION OF event
    FOR VALUES WITH (MODULUS 16, REMAINDER 4);
CREATE TABLE IF NOT EXISTS event_p5 PARTITION OF event
    FOR VALUES WITH (MODULUS 16, REMAINDER 5);
CREATE TABLE IF NOT EXISTS event_p6 PARTITION OF event
    FOR VALUES WITH (MODULUS 16, REMAINDER 6);
CREATE TABLE IF NOT EXISTS event_p7 PARTITION OF event
    FOR VALUES WITH (MODULUS 16, REMAINDER 7);
CREATE TABLE IF NOT EXISTS event_p8 PARTITION OF event
    FOR VALUES WITH (MODULUS 16, REMAINDER 8);
CREATE TABLE IF NOT EXISTS event_p9 PARTITION OF event
    FOR VALUES WITH (MODULUS 16, REMAINDER 9);
CREATE TABLE IF NOT EXISTS event_p10 PARTITION OF event
    FOR VALUES WITH (MODULUS 16, REMAINDER 10);
CREATE TABLE IF NOT EXISTS event_p11 PARTITION OF event
    FOR VALUES WITH (MODULUS 16, REMAINDER 11);
CREATE TABLE IF NOT EXISTS event_p12 PARTITION OF event
    FOR VALUES WITH (MODULUS 16, REMAINDER 12);
CREATE TABLE IF NOT EXISTS event_p13 PARTITION OF event
    FOR VALUES WITH (MODULUS 16, REMAINDER 13);
CREATE TABLE IF NOT EXISTS event_p14 PARTITION OF event
    FOR VALUES WITH (MODULUS 16, REMAINDER 14);
CREATE TABLE IF NOT EXISTS event_p15 PARTITION OF event
    FOR VALUES WITH (MODULUS 16, REMAINDER 15);

COMMENT ON TABLE event IS 'Complete Nostr events with computed tag values for efficient querying';
COMMENT ON COLUMN event.id IS 'SHA-256 event hash (32 bytes, stored as bytea from hex)';
COMMENT ON COLUMN event.pubkey IS 'Author public key (32 bytes, stored as bytea from hex)';
COMMENT ON COLUMN event.created_at IS 'Unix timestamp of event creation';
COMMENT ON COLUMN event.kind IS 'Event kind per NIP-01 (0=metadata, 1=text note, 3=contacts, etc.)';
COMMENT ON COLUMN event.tags IS 'JSONB array of [key, value, ...] tag arrays per NIP-01';
COMMENT ON COLUMN event.tagvalues IS 'Single-char tag values computed at insert time by event_insert() for GIN indexing';
COMMENT ON COLUMN event.content IS 'Event content (plaintext or encrypted depending on kind)';
COMMENT ON COLUMN event.sig IS 'Schnorr signature (64 bytes, stored as bytea from hex)';


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
) PARTITION BY HASH (event_id);

CREATE TABLE IF NOT EXISTS event_relay_p0 PARTITION OF event_relay
    FOR VALUES WITH (MODULUS 16, REMAINDER 0);
CREATE TABLE IF NOT EXISTS event_relay_p1 PARTITION OF event_relay
    FOR VALUES WITH (MODULUS 16, REMAINDER 1);
CREATE TABLE IF NOT EXISTS event_relay_p2 PARTITION OF event_relay
    FOR VALUES WITH (MODULUS 16, REMAINDER 2);
CREATE TABLE IF NOT EXISTS event_relay_p3 PARTITION OF event_relay
    FOR VALUES WITH (MODULUS 16, REMAINDER 3);
CREATE TABLE IF NOT EXISTS event_relay_p4 PARTITION OF event_relay
    FOR VALUES WITH (MODULUS 16, REMAINDER 4);
CREATE TABLE IF NOT EXISTS event_relay_p5 PARTITION OF event_relay
    FOR VALUES WITH (MODULUS 16, REMAINDER 5);
CREATE TABLE IF NOT EXISTS event_relay_p6 PARTITION OF event_relay
    FOR VALUES WITH (MODULUS 16, REMAINDER 6);
CREATE TABLE IF NOT EXISTS event_relay_p7 PARTITION OF event_relay
    FOR VALUES WITH (MODULUS 16, REMAINDER 7);
CREATE TABLE IF NOT EXISTS event_relay_p8 PARTITION OF event_relay
    FOR VALUES WITH (MODULUS 16, REMAINDER 8);
CREATE TABLE IF NOT EXISTS event_relay_p9 PARTITION OF event_relay
    FOR VALUES WITH (MODULUS 16, REMAINDER 9);
CREATE TABLE IF NOT EXISTS event_relay_p10 PARTITION OF event_relay
    FOR VALUES WITH (MODULUS 16, REMAINDER 10);
CREATE TABLE IF NOT EXISTS event_relay_p11 PARTITION OF event_relay
    FOR VALUES WITH (MODULUS 16, REMAINDER 11);
CREATE TABLE IF NOT EXISTS event_relay_p12 PARTITION OF event_relay
    FOR VALUES WITH (MODULUS 16, REMAINDER 12);
CREATE TABLE IF NOT EXISTS event_relay_p13 PARTITION OF event_relay
    FOR VALUES WITH (MODULUS 16, REMAINDER 13);
CREATE TABLE IF NOT EXISTS event_relay_p14 PARTITION OF event_relay
    FOR VALUES WITH (MODULUS 16, REMAINDER 14);
CREATE TABLE IF NOT EXISTS event_relay_p15 PARTITION OF event_relay
    FOR VALUES WITH (MODULUS 16, REMAINDER 15);

ALTER TABLE event_relay_p0 SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 10000,
    autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE event_relay_p1 SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 10000,
    autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE event_relay_p2 SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 10000,
    autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE event_relay_p3 SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 10000,
    autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE event_relay_p4 SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 10000,
    autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE event_relay_p5 SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 10000,
    autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE event_relay_p6 SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 10000,
    autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE event_relay_p7 SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 10000,
    autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE event_relay_p8 SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 10000,
    autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE event_relay_p9 SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 10000,
    autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE event_relay_p10 SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 10000,
    autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE event_relay_p11 SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 10000,
    autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE event_relay_p12 SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 10000,
    autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE event_relay_p13 SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 10000,
    autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE event_relay_p14 SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 10000,
    autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE event_relay_p15 SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 10000,
    autovacuum_analyze_scale_factor = 0.01
);

COMMENT ON TABLE event_relay IS 'Tracks which events appear on which relays, with first-seen timestamps';
COMMENT ON COLUMN event_relay.event_id IS 'Foreign key to event.id';
COMMENT ON COLUMN event_relay.relay_url IS 'Foreign key to relay.url';
COMMENT ON COLUMN event_relay.seen_at IS 'Unix timestamp when event was first observed on this relay';


-- ==========================================================================
-- metadata: Content-addressed NIP-11 and NIP-66 document storage
-- ==========================================================================
-- Stores JSON metadata documents deduplicated by their SHA-256 content hash
-- and metadata type. The composite primary key (id, type) ensures
-- each document is associated with exactly one type. Content-addressed
-- deduplication still operates within a type: identical data with the same
-- type shares a single row.

CREATE TABLE IF NOT EXISTS metadata (
    id BYTEA NOT NULL,
    type TEXT NOT NULL,
    data JSONB NOT NULL,
    PRIMARY KEY (id, type)
);

COMMENT ON TABLE metadata IS 'Content-addressed storage for NIP-11/NIP-66 metadata (deduplicated by SHA-256 hash + type)';
COMMENT ON COLUMN metadata.id IS 'SHA-256 hash of the JSON data (content-addressed key, part of composite PK)';
COMMENT ON COLUMN metadata.type IS 'Check type: nip11_info, nip66_rtt, nip66_ssl, nip66_geo, nip66_net, nip66_dns, or nip66_http';
COMMENT ON COLUMN metadata.data IS 'Complete JSON document (NIP-11 relay info or NIP-66 check result)';


-- ==========================================================================
-- relay_metadata: Time-series metadata snapshots per relay
-- ==========================================================================
-- Links relays to metadata documents over time, creating a history of health
-- check results. Each row represents one metadata snapshot for one relay at
-- one point in time. The metadata_type column distinguishes between different
-- check types: nip11_info, nip66_rtt, nip66_ssl, nip66_geo, nip66_net,
-- nip66_dns, nip66_http.

CREATE TABLE IF NOT EXISTS relay_metadata (
    relay_url TEXT NOT NULL,
    metadata_id BYTEA NOT NULL,
    metadata_type TEXT NOT NULL,
    generated_at BIGINT NOT NULL,

    PRIMARY KEY (relay_url, generated_at, metadata_type),
    FOREIGN KEY (relay_url) REFERENCES relay (url) ON DELETE CASCADE,
    FOREIGN KEY (metadata_id, metadata_type) REFERENCES metadata (id, type) ON DELETE CASCADE
);

COMMENT ON TABLE relay_metadata IS 'Time-series relay metadata snapshots linking relays to metadata documents';
COMMENT ON COLUMN relay_metadata.relay_url IS 'Foreign key to relay.url';
COMMENT ON COLUMN relay_metadata.metadata_id IS 'Foreign key to metadata(id, type) (content-addressed hash)';
COMMENT ON COLUMN relay_metadata.metadata_type IS 'Check type: nip11_info, nip66_rtt, nip66_ssl, nip66_geo, nip66_net, nip66_dns, or nip66_http';
COMMENT ON COLUMN relay_metadata.generated_at IS 'Unix timestamp when the metadata was collected';


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
    state_value JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (service_name, state_type, state_key)
);

COMMENT ON TABLE service_state IS 'Per-service persistent state (cursors, checkpoints)';
COMMENT ON COLUMN service_state.service_name IS 'Service identifier (finder, validator, synchronizer, monitor)';
COMMENT ON COLUMN service_state.state_type IS 'State category (cursor, checkpoint)';
COMMENT ON COLUMN service_state.state_key IS 'Unique key within service+type (typically a relay URL or entity ID)';
COMMENT ON COLUMN service_state.state_value IS 'JSONB payload; each state type stores its own business timestamp';
