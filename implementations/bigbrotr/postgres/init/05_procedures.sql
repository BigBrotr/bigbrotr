-- ============================================================================
-- BigBrotr Database Initialization Script
-- ============================================================================
-- File: 05_procedures.sql
-- Description: Stored procedures for batch operations
-- Dependencies: 02_tables.sql, 01_utility_functions.sql
-- ============================================================================

-- Procedure: insert_event
-- Description: Atomically inserts event + relay + event-relay junction record
-- Parameters: Event fields, relay info, and seen_at timestamp
-- Returns: VOID
-- Notes: Uses ON CONFLICT DO NOTHING for idempotency
CREATE OR REPLACE FUNCTION insert_event(
    p_event_id              CHAR(64),
    p_pubkey                CHAR(64),
    p_created_at            BIGINT,
    p_kind                  INTEGER,
    p_tags                  JSONB,
    p_content               TEXT,
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
    -- Insert event (idempotent)
    INSERT INTO events (id, pubkey, created_at, kind, tags, content, sig)
    VALUES (p_event_id, p_pubkey, p_created_at, p_kind, p_tags, p_content, p_sig)
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
        -- OK, duplicate record (idempotent operation)
        RETURN;
    WHEN foreign_key_violation THEN
        -- Critical: relay doesn't exist
        RAISE EXCEPTION 'Relay % does not exist for event %', p_relay_url, p_event_id;
    WHEN OTHERS THEN
        -- Unknown error, fail loudly
        RAISE EXCEPTION 'insert_event failed for event %: %', p_event_id, SQLERRM;
END;
$$;

COMMENT ON FUNCTION insert_event IS 'Atomically inserts event, relay, and their association';

-- Procedure: insert_relay
-- Description: Inserts a relay record
-- Parameters: Relay URL, network type, insertion timestamp
-- Returns: VOID
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
        -- OK, duplicate relay (idempotent operation)
        RETURN;
    WHEN OTHERS THEN
        -- Unknown error, fail loudly
        RAISE EXCEPTION 'insert_relay failed for %: %', p_url, SQLERRM;
END;
$$;

COMMENT ON FUNCTION insert_relay IS 'Inserts relay with conflict handling';

-- Procedure: insert_relay_metadata
-- Description: Inserts relay metadata with automatic deduplication of NIP-11/NIP-66 data
-- Parameters: All fields from nostr-tools RelayMetadata structure
-- Returns: VOID
-- Notes: Computes hashes and reuses existing NIP-11/NIP-66 records when identical
--        NIP-11/NIP-66 objects are inserted even if all fields are NULL
CREATE OR REPLACE FUNCTION insert_relay_metadata(
    -- Relay identification
    p_relay_url                 TEXT,
    p_relay_network             TEXT,
    p_relay_inserted_at         BIGINT,
    p_generated_at              BIGINT,

    -- NIP-66 presence flag (TRUE if nip66 object exists, FALSE if none)
    p_nip66_present             BOOLEAN,

    -- NIP-66 connection data
    p_nip66_openable            BOOLEAN,
    p_nip66_readable            BOOLEAN,
    p_nip66_writable            BOOLEAN,
    p_nip66_rtt_open            INTEGER,
    p_nip66_rtt_read            INTEGER,
    p_nip66_rtt_write           INTEGER,

    -- NIP-11 presence flag (TRUE if nip11 object exists, FALSE if none)
    p_nip11_present             BOOLEAN,

    -- NIP-11 information document
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
        -- Compute NIP-11 hash
        v_nip11_id := compute_nip11_hash(
            p_nip11_name, p_nip11_description, p_nip11_banner, p_nip11_icon,
            p_nip11_pubkey, p_nip11_contact, p_nip11_supported_nips,
            p_nip11_software, p_nip11_version, p_nip11_privacy_policy,
            p_nip11_terms_of_service, p_nip11_limitation, p_nip11_extra_fields
        );

        -- Insert NIP-11 data (idempotent via hash-based PK)
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
        -- Compute NIP-66 hash
        v_nip66_id := compute_nip66_hash(
            COALESCE(p_nip66_openable, FALSE),
            COALESCE(p_nip66_readable, FALSE),
            COALESCE(p_nip66_writable, FALSE),
            p_nip66_rtt_open,
            p_nip66_rtt_read,
            p_nip66_rtt_write
        );

        -- Insert NIP-66 data (idempotent via hash-based PK)
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
        -- OK, duplicate metadata (idempotent operation)
        RETURN;
    WHEN foreign_key_violation THEN
        -- Critical: relay doesn't exist
        RAISE EXCEPTION 'Relay % does not exist for metadata insert', p_relay_url;
    WHEN OTHERS THEN
        -- Unknown error, fail loudly
        RAISE EXCEPTION 'insert_relay_metadata failed for %: %', p_relay_url, SQLERRM;
END;
$$;

COMMENT ON FUNCTION insert_relay_metadata IS 'Inserts relay metadata with automatic NIP-11/NIP-66 deduplication';

-- ============================================================================
-- PROCEDURES CREATED
-- ============================================================================