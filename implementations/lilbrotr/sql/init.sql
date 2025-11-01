-- ============================================================================
-- Lilbrotr Database Initialization Script
-- ============================================================================
-- Description: Minimal PostgreSQL schema for lightweight Nostr network archival
-- Version: 1.0 (Lightweight - no tags, content, or redundant info)
-- Database: PostgreSQL 14+
-- Dependencies: btree_gin extension
-- 
-- Key Differences from Bigbrotr:
--   - NO event tags storage (reduces storage by ~40%)
--   - NO event content storage (reduces storage by ~50%)
--   - Minimal event metadata (id, pubkey, created_at, kind, sig only)
--   - Same relay tracking and metadata capabilities
--   - Ideal for: event indexing, relay monitoring, network analysis
-- ============================================================================

-- ============================================================================
-- EXTENSIONS
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "btree_gin";

-- ============================================================================
-- UTILITY FUNCTIONS
-- ============================================================================

-- Function: compute_nip11_hash
-- Description: Computes deterministic hash for NIP-11 data
CREATE OR REPLACE FUNCTION compute_nip11_hash(
    p_name                  TEXT,
    p_description           TEXT,
    p_banner                TEXT,
    p_icon                  TEXT,
    p_pubkey                TEXT,
    p_contact               TEXT,
    p_supported_nips        JSONB,
    p_software              TEXT,
    p_version               TEXT,
    p_privacy_policy        TEXT,
    p_terms_of_service      TEXT,
    p_limitation            JSONB,
    p_extra_fields          JSONB
)
RETURNS CHAR(64)
LANGUAGE plpgsql
IMMUTABLE
AS $$
BEGIN
    RETURN encode(
        digest(
            jsonb_build_object(
                'name', p_name,
                'description', p_description,
                'banner', p_banner,
                'icon', p_icon,
                'pubkey', p_pubkey,
                'contact', p_contact,
                'supported_nips', p_supported_nips,
                'software', p_software,
                'version', p_version,
                'privacy_policy', p_privacy_policy,
                'terms_of_service', p_terms_of_service,
                'limitation', p_limitation,
                'extra_fields', p_extra_fields
            )::text,
            'sha256'
        ),
        'hex'
    );
END;
$$;

-- Function: compute_nip66_hash
-- Description: Computes deterministic hash for NIP-66 data
CREATE OR REPLACE FUNCTION compute_nip66_hash(
    p_openable      BOOLEAN,
    p_readable      BOOLEAN,
    p_writable      BOOLEAN,
    p_rtt_open      INTEGER,
    p_rtt_read      INTEGER,
    p_rtt_write     INTEGER
)
RETURNS CHAR(64)
LANGUAGE plpgsql
IMMUTABLE
AS $$
BEGIN
    RETURN encode(
        digest(
            jsonb_build_object(
                'openable', p_openable,
                'readable', p_readable,
                'writable', p_writable,
                'rtt_open', p_rtt_open,
                'rtt_read', p_rtt_read,
                'rtt_write', p_rtt_write
            )::text,
            'sha256'
        ),
        'hex'
    );
END;
$$;

-- ============================================================================
-- TABLE DEFINITIONS
-- ============================================================================

-- Table: relays
-- Description: Registry of all known Nostr relays
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
-- Description: Minimal Nostr events storage (NO tags, NO content)
-- Purpose: Event existence tracking, relay distribution, network analysis
CREATE TABLE IF NOT EXISTS events (
    id          CHAR(64)    PRIMARY KEY,
    pubkey      CHAR(64)    NOT NULL,
    created_at  BIGINT      NOT NULL,
    kind        INTEGER     NOT NULL,
    sig         CHAR(128)   NOT NULL
);

COMMENT ON TABLE events IS 'Minimal Nostr events (no tags, no content - lightweight indexing only)';
COMMENT ON COLUMN events.id IS 'SHA-256 hash of serialized event (hex-encoded, 64 chars)';
COMMENT ON COLUMN events.pubkey IS 'Author public key (hex-encoded, 64 chars)';
COMMENT ON COLUMN events.created_at IS 'Unix timestamp when event was created';
COMMENT ON COLUMN events.kind IS 'Event kind per NIP-01 (0=metadata, 1=text, 3=contacts, etc.)';
COMMENT ON COLUMN events.sig IS 'Schnorr signature over event fields (hex-encoded, 128 chars)';

-- Table: events_relays
-- Description: Junction table tracking which events are hosted on which relays
CREATE TABLE IF NOT EXISTS events_relays (
    event_id    CHAR(64)    NOT NULL,
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
CREATE TABLE IF NOT EXISTS nip11 (
    id                      CHAR(64)    PRIMARY KEY,
    name                    TEXT,
    description             TEXT,
    banner                  TEXT,
    icon                    TEXT,
    pubkey                  TEXT,
    contact                 TEXT,
    supported_nips          JSONB,
    software                TEXT,
    version                 TEXT,
    privacy_policy          TEXT,
    terms_of_service        TEXT,
    limitation              JSONB,
    extra_fields            JSONB
);

COMMENT ON TABLE nip11 IS 'Deduplicated NIP-11 relay information documents (shared across relays)';

-- Table: nip66
-- Description: Deduplicated NIP-66 connection and performance test results
CREATE TABLE IF NOT EXISTS nip66 (
    id          CHAR(64)    PRIMARY KEY,
    openable    BOOLEAN     NOT NULL,
    readable    BOOLEAN     NOT NULL,
    writable    BOOLEAN     NOT NULL,
    rtt_open    INTEGER,
    rtt_read    INTEGER,
    rtt_write   INTEGER
);

COMMENT ON TABLE nip66 IS 'Deduplicated NIP-66 connection test results (shared across snapshots)';

-- Table: relay_metadata
-- Description: Time-series metadata snapshots linking relays to NIP-11/NIP-66 data
CREATE TABLE IF NOT EXISTS relay_metadata (
    relay_url       TEXT        NOT NULL,
    generated_at    BIGINT      NOT NULL,
    nip11_id        CHAR(64),
    nip66_id        CHAR(64),
    PRIMARY KEY (relay_url, generated_at),
    FOREIGN KEY (relay_url)  REFERENCES relays(url)   ON DELETE CASCADE,
    FOREIGN KEY (nip11_id)   REFERENCES nip11(id)     ON DELETE SET NULL,
    FOREIGN KEY (nip66_id)   REFERENCES nip66(id)     ON DELETE SET NULL
);

COMMENT ON TABLE relay_metadata IS 'Time-series relay metadata snapshots (references NIP-11 and NIP-66 data)';

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Events table indexes (minimal)
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

-- Events_relays table indexes
CREATE INDEX IF NOT EXISTS idx_events_relays_event_id
    ON events_relays USING btree (event_id);

CREATE INDEX IF NOT EXISTS idx_events_relays_relay_url
    ON events_relays USING btree (relay_url);

CREATE INDEX IF NOT EXISTS idx_events_relays_seen_at
    ON events_relays USING btree (seen_at DESC);

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

CREATE INDEX IF NOT EXISTS idx_relay_metadata_url_generated
    ON relay_metadata USING btree (relay_url, generated_at DESC);

-- ============================================================================
-- DATA INTEGRITY FUNCTIONS
-- ============================================================================

-- Function: delete_orphan_events
CREATE OR REPLACE FUNCTION delete_orphan_events()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM events
    WHERE id NOT IN (
        SELECT DISTINCT event_id
        FROM events_relays
    );
END;
$$;

COMMENT ON FUNCTION delete_orphan_events() IS 'Deletes events without relay associations (maintains 1:N relationship)';

-- Function: delete_orphan_nip11
CREATE OR REPLACE FUNCTION delete_orphan_nip11()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM nip11
    WHERE id NOT IN (
        SELECT DISTINCT nip11_id
        FROM relay_metadata
        WHERE nip11_id IS NOT NULL
    );
END;
$$;

-- Function: delete_orphan_nip66
CREATE OR REPLACE FUNCTION delete_orphan_nip66()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM nip66
    WHERE id NOT IN (
        SELECT DISTINCT nip66_id
        FROM relay_metadata
        WHERE nip66_id IS NOT NULL
    );
END;
$$;

-- ============================================================================
-- STORED PROCEDURES FOR BATCH OPERATIONS
-- ============================================================================

-- Procedure: insert_event (minimal version - no tags, no content)
CREATE OR REPLACE FUNCTION insert_event(
    p_event_id              CHAR(64),
    p_pubkey                CHAR(64),
    p_created_at            BIGINT,
    p_kind                  INTEGER,
    p_sig                   CHAR(128),
    p_relay_url             TEXT,
    p_relay_network         TEXT,
    p_relay_inserted_at     BIGINT,
    p_seen_at               BIGINT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    -- Insert event (idempotent) - NO tags, NO content
    INSERT INTO events (id, pubkey, created_at, kind, sig)
    VALUES (p_event_id, p_pubkey, p_created_at, p_kind, p_sig)
    ON CONFLICT (id) DO NOTHING;

    -- Insert relay (idempotent)
    INSERT INTO relays (url, network, inserted_at)
    VALUES (p_relay_url, p_relay_network, p_relay_inserted_at)
    ON CONFLICT (url) DO NOTHING;

    -- Insert event-relay association (idempotent)
    INSERT INTO events_relays (event_id, relay_url, seen_at)
    VALUES (p_event_id, p_relay_url, p_seen_at)
    ON CONFLICT (event_id, relay_url) DO NOTHING;

EXCEPTION
    WHEN unique_violation THEN
        RETURN;
    WHEN foreign_key_violation THEN
        RAISE EXCEPTION 'Relay % does not exist for event %', p_relay_url, p_event_id;
    WHEN OTHERS THEN
        RAISE EXCEPTION 'insert_event failed for event %: %', p_event_id, SQLERRM;
END;
$$;

COMMENT ON FUNCTION insert_event IS 'Atomically inserts event (minimal), relay, and their association';

-- Procedure: insert_relay
CREATE OR REPLACE FUNCTION insert_relay(
    p_url           TEXT,
    p_network       TEXT,
    p_inserted_at   BIGINT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO relays (url, network, inserted_at)
    VALUES (p_url, p_network, p_inserted_at)
    ON CONFLICT (url) DO NOTHING;

EXCEPTION
    WHEN unique_violation THEN
        RETURN;
    WHEN OTHERS THEN
        RAISE EXCEPTION 'insert_relay failed for %: %', p_url, SQLERRM;
END;
$$;

-- Procedure: insert_relay_metadata
CREATE OR REPLACE FUNCTION insert_relay_metadata(
    p_relay_url                 TEXT,
    p_relay_network             TEXT,
    p_relay_inserted_at         BIGINT,
    p_generated_at              BIGINT,
    p_nip66_present             BOOLEAN,
    p_nip66_openable            BOOLEAN,
    p_nip66_readable            BOOLEAN,
    p_nip66_writable            BOOLEAN,
    p_nip66_rtt_open            INTEGER,
    p_nip66_rtt_read            INTEGER,
    p_nip66_rtt_write           INTEGER,
    p_nip11_present             BOOLEAN,
    p_nip11_name                TEXT,
    p_nip11_description         TEXT,
    p_nip11_banner              TEXT,
    p_nip11_icon                TEXT,
    p_nip11_pubkey              TEXT,
    p_nip11_contact             TEXT,
    p_nip11_supported_nips      JSONB,
    p_nip11_software            TEXT,
    p_nip11_version             TEXT,
    p_nip11_privacy_policy      TEXT,
    p_nip11_terms_of_service    TEXT,
    p_nip11_limitation          JSONB,
    p_nip11_extra_fields        JSONB
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_nip11_id CHAR(64);
    v_nip66_id CHAR(64);
BEGIN
    -- Insert relay (idempotent)
    INSERT INTO relays (url, network, inserted_at)
    VALUES (p_relay_url, p_relay_network, p_relay_inserted_at)
    ON CONFLICT (url) DO NOTHING;

    -- Handle NIP-11 data if object is present
    IF p_nip11_present THEN
        v_nip11_id := compute_nip11_hash(
            p_nip11_name, p_nip11_description, p_nip11_banner, p_nip11_icon,
            p_nip11_pubkey, p_nip11_contact, p_nip11_supported_nips,
            p_nip11_software, p_nip11_version, p_nip11_privacy_policy,
            p_nip11_terms_of_service, p_nip11_limitation, p_nip11_extra_fields
        );

        INSERT INTO nip11 (
            id, name, description, banner, icon, pubkey, contact,
            supported_nips, software, version, privacy_policy,
            terms_of_service, limitation, extra_fields
        )
        VALUES (
            v_nip11_id, p_nip11_name, p_nip11_description, p_nip11_banner,
            p_nip11_icon, p_nip11_pubkey, p_nip11_contact,
            p_nip11_supported_nips, p_nip11_software, p_nip11_version,
            p_nip11_privacy_policy, p_nip11_terms_of_service,
            p_nip11_limitation, p_nip11_extra_fields
        )
        ON CONFLICT (id) DO NOTHING;
    ELSE
        v_nip11_id := NULL;
    END IF;

    -- Handle NIP-66 data if object is present
    IF p_nip66_present THEN
        v_nip66_id := compute_nip66_hash(
            COALESCE(p_nip66_openable, FALSE),
            COALESCE(p_nip66_readable, FALSE),
            COALESCE(p_nip66_writable, FALSE),
            p_nip66_rtt_open,
            p_nip66_rtt_read,
            p_nip66_rtt_write
        );

        INSERT INTO nip66 (
            id, openable, readable, writable,
            rtt_open, rtt_read, rtt_write
        )
        VALUES (
            v_nip66_id,
            COALESCE(p_nip66_openable, FALSE),
            COALESCE(p_nip66_readable, FALSE),
            COALESCE(p_nip66_writable, FALSE),
            p_nip66_rtt_open,
            p_nip66_rtt_read,
            p_nip66_rtt_write
        )
        ON CONFLICT (id) DO NOTHING;
    ELSE
        v_nip66_id := NULL;
    END IF;

    -- Insert relay metadata snapshot
    INSERT INTO relay_metadata (relay_url, generated_at, nip11_id, nip66_id)
    VALUES (p_relay_url, p_generated_at, v_nip11_id, v_nip66_id)
    ON CONFLICT (relay_url, generated_at) DO NOTHING;

EXCEPTION
    WHEN unique_violation THEN
        RETURN;
    WHEN foreign_key_violation THEN
        RAISE EXCEPTION 'Relay % does not exist for metadata insert', p_relay_url;
    WHEN OTHERS THEN
        RAISE EXCEPTION 'insert_relay_metadata failed for %: %', p_relay_url, SQLERRM;
END;
$$;

COMMENT ON FUNCTION insert_relay_metadata IS 'Inserts relay metadata with automatic NIP-11/NIP-66 deduplication';

-- ============================================================================
-- DATABASE VIEWS FOR CONVENIENT QUERIES
-- ============================================================================

-- View: relay_metadata_latest
CREATE OR REPLACE VIEW relay_metadata_latest AS
SELECT
    r.url AS relay_url,
    r.network,
    r.inserted_at,
    rm.generated_at,
    n66.id AS nip66_id,
    n66.openable AS nip66_openable,
    n66.readable AS nip66_readable,
    n66.writable AS nip66_writable,
    n66.rtt_open AS nip66_rtt_open,
    n66.rtt_read AS nip66_rtt_read,
    n66.rtt_write AS nip66_rtt_write,
    n11.id AS nip11_id,
    n11.name AS nip11_name,
    n11.description AS nip11_description,
    n11.banner AS nip11_banner,
    n11.icon AS nip11_icon,
    n11.pubkey AS nip11_pubkey,
    n11.contact AS nip11_contact,
    n11.supported_nips AS nip11_supported_nips,
    n11.software AS nip11_software,
    n11.version AS nip11_version,
    n11.privacy_policy AS nip11_privacy_policy,
    n11.terms_of_service AS nip11_terms_of_service,
    n11.limitation AS nip11_limitation,
    n11.extra_fields AS nip11_extra_fields
FROM relays r
LEFT JOIN LATERAL (
    SELECT *
    FROM relay_metadata
    WHERE relay_url = r.url
    ORDER BY generated_at DESC
    LIMIT 1
) rm ON TRUE
LEFT JOIN nip66 n66 ON rm.nip66_id = n66.id
LEFT JOIN nip11 n11 ON rm.nip11_id = n11.id;

COMMENT ON VIEW relay_metadata_latest IS 'Latest metadata per relay (combines most recent snapshot with NIP-11/NIP-66 data)';

-- View: readable_relays
CREATE OR REPLACE VIEW readable_relays AS
SELECT
    relay_url,
    network,
    generated_at,
    nip66_rtt_read
FROM relay_metadata_latest
WHERE nip66_readable = TRUE
ORDER BY nip66_rtt_read ASC NULLS LAST;

COMMENT ON VIEW readable_relays IS 'Relays with readable=TRUE in latest test (sorted by RTT)';

-- ============================================================================
-- INITIALIZATION COMPLETE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '============================================================================';
    RAISE NOTICE 'Lilbrotr database schema initialized successfully';
    RAISE NOTICE '============================================================================';
    RAISE NOTICE 'Lightweight schema features:';
    RAISE NOTICE '  - NO event tags storage (~40%% space savings)';
    RAISE NOTICE '  - NO event content storage (~50%% space savings)';
    RAISE NOTICE '  - Minimal event metadata (id, pubkey, created_at, kind, sig)';
    RAISE NOTICE '  - Full relay tracking and metadata capabilities';
    RAISE NOTICE '  - Ideal for: event indexing, relay monitoring, network analysis';
    RAISE NOTICE '============================================================================';
    RAISE NOTICE 'Core tables: relays, events (minimal), events_relays';
    RAISE NOTICE 'Metadata tables: nip11, nip66, relay_metadata';
    RAISE NOTICE 'Hash functions: compute_nip11_hash, compute_nip66_hash';
    RAISE NOTICE 'Utility functions: delete_orphan_*';
    RAISE NOTICE 'Procedures: insert_event (minimal), insert_relay, insert_relay_metadata';
    RAISE NOTICE 'Views: relay_metadata_latest, readable_relays';
    RAISE NOTICE '============================================================================';
END $$;

