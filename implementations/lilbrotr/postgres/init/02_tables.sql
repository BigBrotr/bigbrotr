-- ============================================================================
-- LilBrotr Database Initialization Script
-- ============================================================================
-- File: 02_tables.sql
-- Description: All database tables (lightweight - no tags/content storage)
-- Dependencies: 00_extensions.sql
-- ============================================================================

-- Table: relays
-- Description: Registry of all known Nostr relays
-- Notes: Primary table - no dependencies
CREATE TABLE IF NOT EXISTS relays (
    url         TEXT        PRIMARY KEY,
    network     TEXT        NOT NULL,
    inserted_at BIGINT      NOT NULL
);

COMMENT ON TABLE relays IS 'Registry of all known Nostr relays across clearnet and Tor';
COMMENT ON COLUMN relays.url IS 'WebSocket URL of the relay (e.g., wss://relay.example.com)';
COMMENT ON COLUMN relays.network IS 'Network type: clearnet or tor';
COMMENT ON COLUMN relays.inserted_at IS 'Unix timestamp when relay was first discovered';

-- Table: events
-- Description: Stores Nostr events (lightweight - no tags/content storage)
-- Notes: Uses BYTEA for efficient storage (50% space savings vs CHAR)
--        Tags and content are NOT stored to minimize disk usage
CREATE TABLE IF NOT EXISTS events (
    id          BYTEA       PRIMARY KEY,
    pubkey      BYTEA       NOT NULL,
    created_at  BIGINT      NOT NULL,
    kind        INTEGER     NOT NULL,
    sig         BYTEA       NOT NULL
);

COMMENT ON TABLE events IS 'Nostr events (lightweight - no tags/content storage)';
COMMENT ON COLUMN events.id IS 'SHA-256 hash of serialized event (stored as bytea from hex string)';
COMMENT ON COLUMN events.pubkey IS 'Author public key (stored as bytea from hex string)';
COMMENT ON COLUMN events.created_at IS 'Unix timestamp when event was created';
COMMENT ON COLUMN events.kind IS 'Event kind per NIP-01 (0=metadata, 1=text, 3=contacts, etc.)';
COMMENT ON COLUMN events.sig IS 'Schnorr signature over event fields (stored as bytea from hex string)';

-- Table: events_relays
-- Description: Junction table tracking which events are hosted on which relays
-- Notes: Composite PK ensures uniqueness, foreign keys ensure referential integrity
CREATE TABLE IF NOT EXISTS events_relays (
    event_id    BYTEA       NOT NULL,
    relay_url   TEXT        NOT NULL,
    seen_at     BIGINT      NOT NULL,
    PRIMARY KEY (event_id, relay_url),
    FOREIGN KEY (event_id)   REFERENCES events(id)     ON DELETE CASCADE,
    FOREIGN KEY (relay_url)  REFERENCES relays(url)    ON DELETE CASCADE
);

COMMENT ON TABLE events_relays IS 'Junction table tracking event-relay relationships with timestamps';
COMMENT ON COLUMN events_relays.event_id IS 'Reference to events.id';
COMMENT ON COLUMN events_relays.relay_url IS 'Reference to relays.url';
COMMENT ON COLUMN events_relays.seen_at IS 'Unix timestamp when event was first seen on this relay';

-- Table: nip11
-- Description: Deduplicated NIP-11 relay information documents
-- Notes: Aligned with nostr-tools RelayMetadata.Nip11 class
-- Purpose: One NIP-11 record can be shared by multiple relays (normalized)
CREATE TABLE IF NOT EXISTS nip11 (
    id                      BYTEA       PRIMARY KEY,

    -- Basic information
    name                    TEXT,
    description             TEXT,
    banner                  TEXT,
    icon                    TEXT,

    -- Contact information
    pubkey                  TEXT,
    contact                 TEXT,

    -- Technical details
    supported_nips          JSONB,
    software                TEXT,
    version                 TEXT,

    -- Policies
    privacy_policy          TEXT,
    terms_of_service        TEXT,

    -- Additional metadata
    limitation              JSONB,
    extra_fields            JSONB
);

COMMENT ON TABLE nip11 IS 'Deduplicated NIP-11 relay information documents (shared across relays)';
COMMENT ON COLUMN nip11.id IS 'SHA-256 hash of NIP-11 fields (stored as bytea from hex string)';
COMMENT ON COLUMN nip11.name IS 'Relay name';
COMMENT ON COLUMN nip11.description IS 'Relay description';
COMMENT ON COLUMN nip11.banner IS 'URL to banner image';
COMMENT ON COLUMN nip11.icon IS 'URL to relay icon';
COMMENT ON COLUMN nip11.pubkey IS 'Administrative contact public key';
COMMENT ON COLUMN nip11.contact IS 'Alternative contact method (email, npub, etc.)';
COMMENT ON COLUMN nip11.supported_nips IS 'Array of supported NIP numbers (JSONB)';
COMMENT ON COLUMN nip11.software IS 'Relay software identifier';
COMMENT ON COLUMN nip11.version IS 'Software version string';
COMMENT ON COLUMN nip11.privacy_policy IS 'URL to privacy policy document';
COMMENT ON COLUMN nip11.terms_of_service IS 'URL to terms of service document';
COMMENT ON COLUMN nip11.limitation IS 'Relay limitations (JSONB per NIP-11)';
COMMENT ON COLUMN nip11.extra_fields IS 'Additional custom fields from NIP-11 document (JSONB)';

-- Table: nip66
-- Description: Deduplicated NIP-66 connection and performance test results
-- Notes: Aligned with nostr-tools RelayMetadata.Nip66 class
-- Purpose: One NIP-66 record can be referenced by multiple relay metadata snapshots
CREATE TABLE IF NOT EXISTS nip66 (
    id          BYTEA       PRIMARY KEY,

    -- Connection capabilities
    openable    BOOLEAN     NOT NULL,
    readable    BOOLEAN     NOT NULL,
    writable    BOOLEAN     NOT NULL,

    -- Round-trip time measurements (milliseconds)
    rtt_open    INTEGER,
    rtt_read    INTEGER,
    rtt_write   INTEGER
);

COMMENT ON TABLE nip66 IS 'Deduplicated NIP-66 connection test results (shared across snapshots)';
COMMENT ON COLUMN nip66.id IS 'SHA-256 hash of NIP-66 fields (stored as bytea from hex string)';
COMMENT ON COLUMN nip66.openable IS 'Whether relay accepts WebSocket connections';
COMMENT ON COLUMN nip66.readable IS 'Whether relay allows REQ subscriptions';
COMMENT ON COLUMN nip66.writable IS 'Whether relay accepts EVENT messages';
COMMENT ON COLUMN nip66.rtt_open IS 'Round-trip time for WebSocket open handshake (ms)';
COMMENT ON COLUMN nip66.rtt_read IS 'Round-trip time for REQ/EOSE cycle (ms)';
COMMENT ON COLUMN nip66.rtt_write IS 'Round-trip time for EVENT/OK cycle (ms)';

-- Table: relay_metadata
-- Description: Time-series metadata snapshots linking relays to NIP-11/NIP-66 data
-- Notes: Root table for relay metadata, references deduplicated NIP-11 and NIP-66 records
-- Purpose: Tracks metadata changes over time with minimal duplication
CREATE TABLE IF NOT EXISTS relay_metadata (
    relay_url       TEXT        NOT NULL,
    generated_at    BIGINT      NOT NULL,
    nip11_id        BYTEA,
    nip66_id        BYTEA,

    -- Constraints
    PRIMARY KEY (relay_url, generated_at),
    FOREIGN KEY (relay_url)  REFERENCES relays(url)   ON DELETE CASCADE,
    FOREIGN KEY (nip11_id)   REFERENCES nip11(id)     ON DELETE SET NULL,
    FOREIGN KEY (nip66_id)   REFERENCES nip66(id)     ON DELETE SET NULL
);

COMMENT ON TABLE relay_metadata IS 'Time-series relay metadata snapshots (references NIP-11 and NIP-66 data)';
COMMENT ON COLUMN relay_metadata.relay_url IS 'Reference to relays.url';
COMMENT ON COLUMN relay_metadata.generated_at IS 'Unix timestamp when metadata snapshot was created';
COMMENT ON COLUMN relay_metadata.nip11_id IS 'Reference to nip11.id (NULL if NIP-11 unavailable)';
COMMENT ON COLUMN relay_metadata.nip66_id IS 'Reference to nip66.id (NULL if NIP-66 test not performed)';

-- Table: service_state
-- Description: Persistent state storage for services (watermarks, checkpoints, metadata)
-- Notes: Primary table - no dependencies. Used by services like Finder to track progress.
-- Purpose: Enables services to resume from last processed position after restart
CREATE TABLE IF NOT EXISTS service_state (
    service_name    TEXT        PRIMARY KEY,
    state           JSONB       NOT NULL DEFAULT '{}',
    updated_at      BIGINT      NOT NULL
);

COMMENT ON TABLE service_state IS 'Persistent state storage for service watermarks and checkpoints';
COMMENT ON COLUMN service_state.service_name IS 'Unique identifier for the service (e.g., finder, monitor)';
COMMENT ON COLUMN service_state.state IS 'Service-specific state as JSONB (watermarks, cursors, metadata)';
COMMENT ON COLUMN service_state.updated_at IS 'Unix timestamp when state was last updated';

-- ============================================================================
-- TABLES CREATED
-- ============================================================================