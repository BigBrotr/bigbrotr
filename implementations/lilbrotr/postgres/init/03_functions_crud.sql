-- ============================================================================
-- LilBrotr Database Initialization Script
-- ============================================================================
-- File: 03_functions_crud.sql
-- Description: CRUD Functions for data operations (lightweight version)
-- Note: insert_event omits tags and content parameters
-- Dependencies: 02_tables.sql
-- ============================================================================

-- Function: insert_event
-- Description: Atomically inserts event + relay + event-relay junction record
-- Parameters: Event fields, relay info, and seen_at timestamp
-- Returns: VOID
-- Notes:
--   - Uses ON CONFLICT DO NOTHING for idempotency
--   - LilBrotr: Same interface as BigBrotr but ignores p_tags and p_content
--   - This ensures Python code works identically with both implementations
CREATE OR REPLACE FUNCTION insert_event(
    p_event_id BYTEA,
    p_pubkey BYTEA,
    p_created_at BIGINT,
    p_kind INTEGER,
    p_tags JSONB,      -- Accepted but NOT stored in LilBrotr
    p_content TEXT,       -- Accepted but NOT stored in LilBrotr
    p_sig BYTEA,
    p_relay_url TEXT,
    p_relay_network TEXT,
    p_relay_discovered_at BIGINT,
    p_seen_at BIGINT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    -- Insert event (idempotent)
    -- Note: LilBrotr ignores p_tags and p_content - they are NOT stored
    INSERT INTO events (id, pubkey, created_at, kind, sig)
    VALUES (p_event_id, p_pubkey, p_created_at, p_kind, p_sig)
    ON CONFLICT (id) DO NOTHING;

    -- Insert relay (idempotent) - relay must already exist (validated by Validator)
    INSERT INTO relays (url, network, discovered_at)
    VALUES (p_relay_url, p_relay_network, p_relay_discovered_at)
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

COMMENT ON FUNCTION insert_event IS 'Atomically inserts event, relay, and their association. LilBrotr: accepts tags/content but does NOT store them.';

-- Function: insert_relay
-- Description: Inserts a validated relay record
-- Parameters: Relay URL, network type, insertion timestamp
-- Returns: VOID
CREATE OR REPLACE FUNCTION insert_relay(
    p_url TEXT,
    p_network TEXT,
    p_discovered_at BIGINT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO relays (url, network, discovered_at)
    VALUES (p_url, p_network, p_discovered_at)
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

COMMENT ON FUNCTION insert_relay IS 'Inserts validated relay with conflict handling';

-- Function: insert_relay_metadata
-- Description: Inserts relay metadata with automatic deduplication
-- Parameters:
--   p_relay_url: Relay WebSocket URL
--   p_relay_network: Network type (clearnet/tor)
--   p_relay_discovered_at: Relay discovery timestamp
--   p_snapshot_at: Metadata snapshot timestamp
--   p_type: Metadata type ('nip11', 'nip66_rtt', 'nip66_geo')
--   p_metadata_data: Complete metadata as JSONB
-- Returns: VOID
-- Notes:
--   - Hash is computed in PostgreSQL using sha256
--   - Content-addressed storage for deduplication
--   - Uses ON CONFLICT for idempotent operations
CREATE OR REPLACE FUNCTION insert_relay_metadata(
    p_relay_url TEXT,
    p_relay_network TEXT,
    p_relay_discovered_at BIGINT,
    p_snapshot_at BIGINT,
    p_type TEXT,
    p_metadata_data JSONB
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_metadata_id BYTEA;
BEGIN
    -- Compute content-addressed hash from JSONB data
    -- Uses canonical JSON representation for consistent hashing
    v_metadata_id := digest(p_metadata_data::TEXT, 'sha256');

    -- Ensure relay exists (idempotent)
    INSERT INTO relays (url, network, discovered_at)
    VALUES (p_relay_url, p_relay_network, p_relay_discovered_at)
    ON CONFLICT (url) DO NOTHING;

    -- Upsert metadata (deduplicated by content hash)
    INSERT INTO metadata (id, data)
    VALUES (v_metadata_id, p_metadata_data)
    ON CONFLICT (id) DO NOTHING;

    -- Insert relay_metadata junction (idempotent)
    INSERT INTO relay_metadata (relay_url, snapshot_at, type, metadata_id)
    VALUES (p_relay_url, p_snapshot_at, p_type, v_metadata_id)
    ON CONFLICT (relay_url, snapshot_at, type) DO NOTHING;

EXCEPTION
    WHEN check_violation THEN
        -- Invalid type value
        RAISE EXCEPTION 'Invalid metadata type % for relay %', p_type, p_relay_url;
    WHEN foreign_key_violation THEN
        -- Should not happen due to insert order, but handle gracefully
        RAISE EXCEPTION 'Foreign key violation for relay %', p_relay_url;
    WHEN OTHERS THEN
        RAISE EXCEPTION 'insert_relay_metadata failed for %: %', p_relay_url, SQLERRM;
END;
$$;

COMMENT ON FUNCTION insert_relay_metadata IS 'Inserts relay metadata with automatic deduplication (6 params, hash computed in DB)';

-- Function: upsert_service_data
-- Description: Upserts a service data record (for candidates, cursors, state, etc.)
-- Parameters: service_name, data_type, data_key, data (JSONB), updated_at
-- Returns: VOID
CREATE OR REPLACE FUNCTION upsert_service_data(
    p_service_name TEXT,
    p_data_type TEXT,
    p_data_key TEXT,
    p_data JSONB,
    p_updated_at BIGINT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO service_data (service_name, data_type, data_key, data, updated_at)
    VALUES (p_service_name, p_data_type, p_data_key, p_data, p_updated_at)
    ON CONFLICT (service_name, data_type, data_key)
    DO UPDATE SET data = p_data, updated_at = p_updated_at;

EXCEPTION
    WHEN OTHERS THEN
        RAISE EXCEPTION 'upsert_service_data failed for %/%/%: %', p_service_name, p_data_type, p_data_key, SQLERRM;
END;
$$;

COMMENT ON FUNCTION upsert_service_data IS 'Upserts service data record (candidates, cursors, state)';

-- Function: get_service_data
-- Description: Retrieves service data records with optional key filter
-- Parameters: service_name, data_type, optional data_key
-- Returns: TABLE of (data_key, data, updated_at)
CREATE OR REPLACE FUNCTION get_service_data(
    p_service_name TEXT,
    p_data_type TEXT,
    p_data_key TEXT DEFAULT NULL
)
RETURNS TABLE (
    data_key TEXT,
    data JSONB,
    updated_at BIGINT
)
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_data_key IS NOT NULL THEN
        RETURN QUERY
        SELECT sd.data_key, sd.data, sd.updated_at
        FROM service_data sd
        WHERE sd.service_name = p_service_name
          AND sd.data_type = p_data_type
          AND sd.data_key = p_data_key;
    ELSE
        RETURN QUERY
        SELECT sd.data_key, sd.data, sd.updated_at
        FROM service_data sd
        WHERE sd.service_name = p_service_name
          AND sd.data_type = p_data_type
        ORDER BY sd.updated_at ASC;
    END IF;
END;
$$;

COMMENT ON FUNCTION get_service_data IS 'Retrieves service data records with optional key filter';

-- Function: delete_service_data
-- Description: Deletes a service data record
-- Parameters: service_name, data_type, data_key
-- Returns: VOID
CREATE OR REPLACE FUNCTION delete_service_data(
    p_service_name TEXT,
    p_data_type TEXT,
    p_data_key TEXT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM service_data
    WHERE service_name = p_service_name
      AND data_type = p_data_type
      AND data_key = p_data_key;
END;
$$;

COMMENT ON FUNCTION delete_service_data IS 'Deletes a service data record';

-- ============================================================================
-- CRUD FUNCTIONS CREATED
-- ============================================================================
