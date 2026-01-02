-- ============================================================================
-- BigBrotr Database Initialization Script
-- ============================================================================
-- File: 03_functions_crud.sql
-- Description: CRUD Functions for data operations (bulk optimized with unnest)
-- Dependencies: 02_tables.sql
-- ============================================================================

-- Function: insert_event
-- Description: Bulk insert events + relays + event-relay junction records
-- Parameters: Arrays of event fields, relay info, and seen_at timestamps
-- Returns: VOID
-- Notes:
--   - Uses unnest for single-roundtrip bulk insert
--   - Uses ON CONFLICT DO NOTHING for idempotency
--   - All three inserts happen atomically in one transaction
CREATE OR REPLACE FUNCTION insert_event(
    p_event_ids BYTEA[],
    p_pubkeys BYTEA[],
    p_created_ats BIGINT[],
    p_kinds INTEGER[],
    p_tags JSONB[],
    p_contents TEXT[],
    p_sigs BYTEA[],
    p_relay_urls TEXT[],
    p_relay_networks TEXT[],
    p_relay_discovered_ats BIGINT[],
    p_seen_ats BIGINT[]
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    -- Bulk insert events (idempotent)
    INSERT INTO events (id, pubkey, created_at, kind, tags, content, sig)
    SELECT * FROM unnest(
        p_event_ids,
        p_pubkeys,
        p_created_ats,
        p_kinds,
        p_tags,
        p_contents,
        p_sigs
    )
    ON CONFLICT (id) DO NOTHING;

    -- Bulk insert relays (idempotent, deduplicated)
    INSERT INTO relays (url, network, discovered_at)
    SELECT DISTINCT * FROM unnest(
        p_relay_urls,
        p_relay_networks,
        p_relay_discovered_ats
    )
    ON CONFLICT (url) DO NOTHING;

    -- Bulk insert event-relay associations (idempotent)
    INSERT INTO events_relays (event_id, relay_url, seen_at)
    SELECT * FROM unnest(
        p_event_ids,
        p_relay_urls,
        p_seen_ats
    )
    ON CONFLICT (event_id, relay_url) DO NOTHING;
END;
$$;

COMMENT ON FUNCTION insert_event(BYTEA[], BYTEA[], BIGINT[], INTEGER[], JSONB[], TEXT[], BYTEA[], TEXT[], TEXT[], BIGINT[], BIGINT[]) IS
'Bulk insert events, relays, and their associations atomically using unnest';

-- Function: insert_relay
-- Description: Bulk insert validated relay records
-- Parameters: Arrays of relay URL, network type, discovery timestamp
-- Returns: VOID
CREATE OR REPLACE FUNCTION insert_relay(
    p_urls TEXT[],
    p_networks TEXT[],
    p_discovered_ats BIGINT[]
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO relays (url, network, discovered_at)
    SELECT * FROM unnest(p_urls, p_networks, p_discovered_ats)
    ON CONFLICT (url) DO NOTHING;
END;
$$;

COMMENT ON FUNCTION insert_relay(TEXT[], TEXT[], BIGINT[]) IS
'Bulk insert validated relays with conflict handling';

-- Function: insert_relay_metadata
-- Description: Bulk insert relay metadata with automatic deduplication
-- Parameters:
--   p_relay_urls: Array of relay WebSocket URLs
--   p_relay_networks: Array of network types (clearnet/tor)
--   p_relay_discovered_ats: Array of relay discovery timestamps
--   p_snapshot_ats: Array of metadata snapshot timestamps
--   p_types: Array of metadata types ('nip11', 'nip66_rtt', 'nip66_ssl', 'nip66_geo')
--   p_metadata_datas: Array of complete metadata as JSONB
-- Returns: VOID
-- Notes:
--   - Hash is computed ONCE in PostgreSQL using sha256 (via CTE)
--   - Content-addressed storage for deduplication
--   - Uses ON CONFLICT for idempotent operations
--   - Single statement with chained CTEs for optimal performance
CREATE OR REPLACE FUNCTION insert_relay_metadata(
    p_relay_urls TEXT[],
    p_relay_networks TEXT[],
    p_relay_discovered_ats BIGINT[],
    p_snapshot_ats BIGINT[],
    p_types TEXT[],
    p_metadata_datas JSONB[]
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    -- Single statement with chained CTEs:
    -- 1. Compute hash ONCE and prepare all data
    -- 2. Insert relays (idempotent)
    -- 3. Insert metadata (deduplicated by content hash)
    -- 4. Insert relay_metadata junction (idempotent)
    WITH
    -- CTE 1: Unnest arrays and compute hash ONCE per row
    input_data AS (
        SELECT
            u AS relay_url,
            n AS network,
            d_at AS discovered_at,
            s AS snapshot_at,
            t AS type,
            m AS metadata_data,
            digest(m::TEXT, 'sha256') AS metadata_hash
        FROM unnest(
            p_relay_urls,
            p_relay_networks,
            p_relay_discovered_ats,
            p_snapshot_ats,
            p_types,
            p_metadata_datas
        ) AS x(u, n, d_at, s, t, m)
    ),
    -- CTE 2: Insert relays (deduplicated)
    insert_relays AS (
        INSERT INTO relays (url, network, discovered_at)
        SELECT DISTINCT relay_url, network, discovered_at
        FROM input_data
        ON CONFLICT (url) DO NOTHING
        RETURNING url
    ),
    -- CTE 3: Insert metadata (deduplicated by hash)
    insert_metadata AS (
        INSERT INTO metadata (id, data)
        SELECT DISTINCT metadata_hash, metadata_data
        FROM input_data
        ON CONFLICT (id) DO NOTHING
        RETURNING id
    )
    -- Final: Insert relay_metadata junction (uses pre-computed hash)
    INSERT INTO relay_metadata (relay_url, snapshot_at, type, metadata_id)
    SELECT relay_url, snapshot_at, type, metadata_hash
    FROM input_data
    ON CONFLICT (relay_url, snapshot_at, type) DO NOTHING;
END;
$$;

COMMENT ON FUNCTION insert_relay_metadata(TEXT[], TEXT[], BIGINT[], BIGINT[], TEXT[], JSONB[]) IS
'Bulk insert relay metadata with automatic deduplication (hash computed in DB)';

-- Function: upsert_service_data
-- Description: Bulk upsert service data records (for candidates, cursors, state, etc.)
-- Parameters: Arrays of service_name, data_type, data_key, data (JSONB), updated_at
-- Returns: VOID
CREATE OR REPLACE FUNCTION upsert_service_data(
    p_service_names TEXT[],
    p_data_types TEXT[],
    p_data_keys TEXT[],
    p_datas JSONB[],
    p_updated_ats BIGINT[]
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO service_data (service_name, data_type, data_key, data, updated_at)
    SELECT * FROM unnest(
        p_service_names,
        p_data_types,
        p_data_keys,
        p_datas,
        p_updated_ats
    )
    ON CONFLICT (service_name, data_type, data_key)
    DO UPDATE SET
        data = EXCLUDED.data,
        updated_at = EXCLUDED.updated_at;
END;
$$;

COMMENT ON FUNCTION upsert_service_data(TEXT[], TEXT[], TEXT[], JSONB[], BIGINT[]) IS
'Bulk upsert service data records (candidates, cursors, state)';

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
-- Description: Bulk delete service data records
-- Parameters: Arrays of service_name, data_type, data_key
-- Returns: VOID
CREATE OR REPLACE FUNCTION delete_service_data(
    p_service_names TEXT[],
    p_data_types TEXT[],
    p_data_keys TEXT[]
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM service_data sd
    USING unnest(
        p_service_names,
        p_data_types,
        p_data_keys
    ) AS d(sn, dt, dk)
    WHERE sd.service_name = d.sn
      AND sd.data_type = d.dt
      AND sd.data_key = d.dk;
END;
$$;

COMMENT ON FUNCTION delete_service_data(TEXT[], TEXT[], TEXT[]) IS
'Bulk delete service data records';

-- ============================================================================
-- CRUD FUNCTIONS CREATED (bulk optimized)
-- ============================================================================
