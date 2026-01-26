-- ============================================================================
-- LilBrotr Database Initialization Script
-- ============================================================================
-- File: 02_tables.sql
-- Description: All database tables (lightweight schema - no tags/content)
-- Note: Omits tags, tagvalues, and content columns (~60% disk savings)
-- Dependencies: None (tags_to_tagvalues used by CRUD functions, not table definition)
-- ============================================================================

-- Table: relays
-- Description: Registry of all validated Nostr relays
-- Notes: Primary table - contains only relays validated by the Validator service
CREATE TABLE IF NOT EXISTS relays (
    url TEXT PRIMARY KEY,
    network TEXT NOT NULL,
    discovered_at BIGINT NOT NULL
);

COMMENT ON TABLE relays IS 'Registry of validated Nostr relays across clearnet and Tor';
COMMENT ON COLUMN relays.url IS 'WebSocket URL of the relay (e.g., wss://relay.example.com)';
COMMENT ON COLUMN relays.network IS 'Network type: clearnet, tor, i2p, or loki';
COMMENT ON COLUMN relays.discovered_at IS 'Unix timestamp when relay was first discovered and validated';

-- Table: events
-- Description: Stores Nostr events with essential metadata only (no tags/content/sig)
-- Notes:
--   - Uses BYTEA for efficient storage (50% space savings vs CHAR)
--   - Stores tagvalues (computed at insert) for tag-based queries
--   - Omits tags, content, sig for lightweight storage (~60% total savings)
CREATE TABLE IF NOT EXISTS events (
    id BYTEA PRIMARY KEY,
    pubkey BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    tagvalues TEXT[]              -- Computed by insert_event from tags, NOT a generated column
    -- tags      JSONB           -- NOT STORED in LilBrotr
    -- content   TEXT            -- NOT STORED in LilBrotr
    -- sig       BYTEA           -- NOT STORED in LilBrotr
);

COMMENT ON TABLE events IS 'Nostr events (lightweight: tagvalues only, no tags/content/sig)';
COMMENT ON COLUMN events.id IS 'SHA-256 hash of serialized event (stored as bytea from hex string)';
COMMENT ON COLUMN events.pubkey IS 'Author public key (stored as bytea from hex string)';
COMMENT ON COLUMN events.created_at IS 'Unix timestamp when event was created';
COMMENT ON COLUMN events.kind IS 'Event kind per NIP-01 (0=metadata, 1=text, 3=contacts, etc.)';
COMMENT ON COLUMN events.tagvalues IS 'Computed array of single-char tag values for GIN indexing';

-- Table: events_relays
-- Description: Junction table tracking which events are hosted on which relays
-- Notes: Composite PK ensures uniqueness, foreign keys ensure referential integrity
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

-- Table: metadata
-- Description: Unified storage for NIP-11 and NIP-66 metadata documents
-- Notes: Content-addressed by SHA-256 hash of data for deduplication
-- Purpose: One metadata record can be shared by multiple relays (normalized)
CREATE TABLE IF NOT EXISTS metadata (
    id BYTEA PRIMARY KEY,
    data JSONB NOT NULL
);

COMMENT ON TABLE metadata IS 'Unified storage for NIP-11/NIP-66 metadata (deduplicated by content hash)';
COMMENT ON COLUMN metadata.id IS 'SHA-256 hash of JSON data (content-addressed)';
COMMENT ON COLUMN metadata.data IS 'Complete JSON document (NIP-11 or NIP-66 data)';

-- Table: relay_metadata
-- Description: Time-series metadata snapshots linking relays to metadata records
-- Notes: Each relay can have nip11, nip66_rtt, nip66_probe, nip66_ssl, nip66_geo, nip66_net, nip66_dns, nip66_http records per timestamp
-- Purpose: Tracks metadata changes over time with deduplication via metadata table
CREATE TABLE IF NOT EXISTS relay_metadata (
    relay_url TEXT NOT NULL,
    generated_at BIGINT NOT NULL,
    type TEXT NOT NULL,
    metadata_id BYTEA NOT NULL,

    -- Constraints
    PRIMARY KEY (relay_url, generated_at, type),
    FOREIGN KEY (relay_url) REFERENCES relays (url) ON DELETE CASCADE,
    FOREIGN KEY (metadata_id) REFERENCES metadata (id) ON DELETE CASCADE,

    -- Validate type
    CONSTRAINT relay_metadata_type_check CHECK (
        type IN ('nip11', 'nip66_rtt', 'nip66_probe', 'nip66_ssl', 'nip66_geo', 'nip66_net', 'nip66_dns', 'nip66_http')
    )
);

COMMENT ON TABLE relay_metadata IS 'Time-series relay metadata snapshots (references metadata records by type)';
COMMENT ON COLUMN relay_metadata.relay_url IS 'Reference to relays.url';
COMMENT ON COLUMN relay_metadata.generated_at IS 'Unix timestamp when metadata was generated/collected';
COMMENT ON COLUMN relay_metadata.type IS 'Metadata type: nip11, nip66_rtt, nip66_probe, nip66_ssl, nip66_geo, nip66_net, nip66_dns, or nip66_http';
COMMENT ON COLUMN relay_metadata.metadata_id IS 'Reference to metadata.id';

-- Table: service_data
-- Description: Per-service operational data storage for candidates, cursors, and checkpoints
-- Notes: Generic key-value store with JSONB for flexible data structures
-- Purpose: Finder stores candidates, Synchronizer stores cursors, Monitor stores checkpoints
CREATE TABLE IF NOT EXISTS service_data (
    service_name TEXT NOT NULL,
    data_type TEXT NOT NULL,
    data_key TEXT NOT NULL,
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
-- TABLES CREATED
-- ============================================================================
