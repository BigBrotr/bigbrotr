-- ============================================================================
-- LilBrotr Database Initialization Script
-- ============================================================================
-- File: 03_functions_crud.sql
-- Description: CRUD Functions organized by table (base + cascade)
-- Note: events_insert discards tags/content/sig but stores computed tagvalues
-- Dependencies: 02_tables.sql
-- ============================================================================
--
-- STRUCTURE:
--   Level 1 (Base): Single-table operations
--     - relays_insert()
--     - events_insert()             (LilBrotr: computes tagvalues, discards tags/content/sig)
--     - metadata_insert()
--     - events_relays_insert()      (requires FK to exist)
--     - relay_metadata_insert()     (requires FK to exist)
--     - service_data_upsert/get/delete()
--
--   Level 2 (Cascade): Multi-table operations (call base functions internally)
--     - events_relays_insert_cascade()   → relays + events + events_relays
--     - relay_metadata_insert_cascade()  → relays + metadata + relay_metadata
--
-- ============================================================================


-- ============================================================================
-- LEVEL 1: BASE FUNCTIONS (single table)
-- ============================================================================

-- ----------------------------------------------------------------------------
-- relays_insert
-- ----------------------------------------------------------------------------
-- Description: Bulk insert relay records
-- Parameters: Arrays of relay URL, network type, discovery timestamp
-- Returns: Number of rows inserted
CREATE OR REPLACE FUNCTION relays_insert(
    p_urls TEXT[],
    p_networks TEXT[],
    p_discovered_ats BIGINT[]
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    row_count INTEGER;
BEGIN
    INSERT INTO relays (url, network, discovered_at)
    SELECT * FROM unnest(p_urls, p_networks, p_discovered_ats)
    ON CONFLICT (url) DO NOTHING;

    GET DIAGNOSTICS row_count = ROW_COUNT;
    RETURN row_count;
END;
$$;

COMMENT ON FUNCTION relays_insert(TEXT[], TEXT[], BIGINT[]) IS
'Bulk insert relays, returns number of rows inserted';


-- ----------------------------------------------------------------------------
-- events_insert
-- ----------------------------------------------------------------------------
-- Description: Bulk insert event records (LilBrotr: computes tagvalues, discards tags/content/sig)
-- Parameters: Arrays of event fields (same interface as BigBrotr for compatibility)
-- Returns: Number of rows inserted
-- Notes:
--   - LilBrotr: Same interface as BigBrotr but only stores tagvalues (computed)
--   - Discards: tags (JSONB), content (TEXT), sig (BYTEA) - ~60% disk savings
CREATE OR REPLACE FUNCTION events_insert(
    p_event_ids BYTEA[],
    p_pubkeys BYTEA[],
    p_created_ats BIGINT[],
    p_kinds INTEGER[],
    p_tags JSONB[],           -- Used to compute tagvalues, NOT stored
    p_contents TEXT[],        -- Accepted but NOT stored in LilBrotr
    p_sigs BYTEA[]            -- Accepted but NOT stored in LilBrotr
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    row_count INTEGER;
BEGIN
    -- Bulk insert events (compute tagvalues, discard tags/content/sig)
    INSERT INTO events (id, pubkey, created_at, kind, tagvalues)
    SELECT id, pubkey, created_at, kind, tags_to_tagvalues(tags)
    FROM unnest(p_event_ids, p_pubkeys, p_created_ats, p_kinds, p_tags)
        AS t(id, pubkey, created_at, kind, tags)
    ON CONFLICT (id) DO NOTHING;

    GET DIAGNOSTICS row_count = ROW_COUNT;
    RETURN row_count;
END;
$$;

COMMENT ON FUNCTION events_insert(BYTEA[], BYTEA[], BIGINT[], INTEGER[], JSONB[], TEXT[], BYTEA[]) IS
'Bulk insert events (LilBrotr: tagvalues computed), returns number of rows inserted';


-- ----------------------------------------------------------------------------
-- metadata_insert
-- ----------------------------------------------------------------------------
-- Description: Bulk insert metadata records (content-addressed by hash)
-- Parameters: Array of data (hash computed in DB)
-- Returns: Number of rows inserted
CREATE OR REPLACE FUNCTION metadata_insert(
    p_datas JSONB[]
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    row_count INTEGER;
BEGIN
    INSERT INTO metadata (id, data)
    SELECT digest(d::TEXT, 'sha256'), d
    FROM unnest(p_datas) AS d
    ON CONFLICT (id) DO NOTHING;

    GET DIAGNOSTICS row_count = ROW_COUNT;
    RETURN row_count;
END;
$$;

COMMENT ON FUNCTION metadata_insert(JSONB[]) IS
'Bulk insert metadata records (content-addressed), returns number of rows inserted';


-- ----------------------------------------------------------------------------
-- events_relays_insert
-- ----------------------------------------------------------------------------
-- Description: Bulk insert event-relay junction records (FK must exist)
-- Parameters: Arrays of event_id, relay_url, seen_at
-- Returns: Number of rows inserted
-- Notes: Will fail if FK references don't exist - use cascade version if needed
CREATE OR REPLACE FUNCTION events_relays_insert(
    p_event_ids BYTEA[],
    p_relay_urls TEXT[],
    p_seen_ats BIGINT[]
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    row_count INTEGER;
BEGIN
    INSERT INTO events_relays (event_id, relay_url, seen_at)
    SELECT * FROM unnest(p_event_ids, p_relay_urls, p_seen_ats)
    ON CONFLICT (event_id, relay_url) DO NOTHING;

    GET DIAGNOSTICS row_count = ROW_COUNT;
    RETURN row_count;
END;
$$;

COMMENT ON FUNCTION events_relays_insert(BYTEA[], TEXT[], BIGINT[]) IS
'Bulk insert event-relay junctions, returns number of rows inserted';


-- ----------------------------------------------------------------------------
-- relay_metadata_insert
-- ----------------------------------------------------------------------------
-- Description: Bulk insert relay-metadata junction records (FK must exist)
-- Parameters: Arrays of relay_url, metadata_data, type, generated_at (hash computed in DB)
-- Returns: Number of rows inserted
-- Notes: Will fail if FK references don't exist - use cascade version if needed
CREATE OR REPLACE FUNCTION relay_metadata_insert(
    p_relay_urls TEXT[],
    p_metadata_datas JSONB[],
    p_types TEXT[],
    p_generated_ats BIGINT[]
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    row_count INTEGER;
BEGIN
    INSERT INTO relay_metadata (relay_url, generated_at, type, metadata_id)
    SELECT u, g, t, digest(m::TEXT, 'sha256')
    FROM unnest(p_relay_urls, p_metadata_datas, p_types, p_generated_ats) AS x(u, m, t, g)
    ON CONFLICT (relay_url, generated_at, type) DO NOTHING;

    GET DIAGNOSTICS row_count = ROW_COUNT;
    RETURN row_count;
END;
$$;

COMMENT ON FUNCTION relay_metadata_insert(TEXT[], JSONB[], TEXT[], BIGINT[]) IS
'Bulk insert relay-metadata junctions, returns number of rows inserted';


-- ============================================================================
-- LEVEL 2: CASCADE FUNCTIONS (multi-table, call base functions)
-- ============================================================================

-- ----------------------------------------------------------------------------
-- events_relays_insert_cascade
-- ----------------------------------------------------------------------------
-- Description: Bulk insert events with relays and junctions atomically
-- Parameters: Arrays of event fields, relay info, and seen_at timestamps
-- Returns: Number of junction rows inserted (events_relays)
-- Notes:
--   - Inserts into: relays → events → events_relays
--   - LilBrotr: events_insert computes tagvalues and discards tags/content/sig
--   - Returns only junction count (last INSERT)
CREATE OR REPLACE FUNCTION events_relays_insert_cascade(
    p_event_ids BYTEA[],
    p_pubkeys BYTEA[],
    p_created_ats BIGINT[],
    p_kinds INTEGER[],
    p_tags JSONB[],           -- Used to compute tagvalues, NOT stored
    p_contents TEXT[],        -- Accepted but NOT stored in LilBrotr
    p_sigs BYTEA[],           -- Accepted but NOT stored in LilBrotr
    p_relay_urls TEXT[],
    p_relay_networks TEXT[],
    p_relay_discovered_ats BIGINT[],
    p_seen_ats BIGINT[]
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    row_count INTEGER;
BEGIN
    -- Single statement with chained CTEs for optimal performance
    WITH
    -- CTE 1: Unnest relay data and dedupe
    relay_data AS (
        SELECT DISTINCT ON (u) u AS url, n AS network, d AS discovered_at
        FROM unnest(p_relay_urls, p_relay_networks, p_relay_discovered_ats) AS t(u, n, d)
    ),
    -- CTE 2: Insert relays (deduplicated before insert)
    insert_relays AS (
        INSERT INTO relays (url, network, discovered_at)
        SELECT url, network, discovered_at FROM relay_data
        ON CONFLICT (url) DO NOTHING
        RETURNING url
    ),
    -- CTE 3: Insert events (LilBrotr: compute tagvalues, discard tags/content/sig)
    insert_events AS (
        INSERT INTO events (id, pubkey, created_at, kind, tagvalues)
        SELECT DISTINCT ON (id) id, pubkey, created_at, kind, tags_to_tagvalues(tags)
        FROM unnest(p_event_ids, p_pubkeys, p_created_ats, p_kinds, p_tags)
            AS t(id, pubkey, created_at, kind, tags)
        ON CONFLICT (id) DO NOTHING
        RETURNING id
    )
    -- Final: Insert junctions
    INSERT INTO events_relays (event_id, relay_url, seen_at)
    SELECT DISTINCT ON (event_id, relay_url) event_id, relay_url, seen_at
    FROM unnest(p_event_ids, p_relay_urls, p_seen_ats) AS t(event_id, relay_url, seen_at)
    ON CONFLICT (event_id, relay_url) DO NOTHING;

    GET DIAGNOSTICS row_count = ROW_COUNT;
    RETURN row_count;
END;
$$;

COMMENT ON FUNCTION events_relays_insert_cascade(BYTEA[], BYTEA[], BIGINT[], INTEGER[], JSONB[], TEXT[], BYTEA[], TEXT[], TEXT[], BIGINT[], BIGINT[]) IS
'Bulk insert events with relays and junctions atomically (LilBrotr), returns junction count';


-- ----------------------------------------------------------------------------
-- relay_metadata_insert_cascade
-- ----------------------------------------------------------------------------
-- Description: Bulk insert relay metadata with relays and junctions atomically
-- Parameters:
--   p_relay_urls: Array of relay WebSocket URLs
--   p_relay_networks: Array of network types (clearnet/tor)
--   p_relay_discovered_ats: Array of relay discovery timestamps
--   p_metadata_datas: Array of complete metadata as JSONB
--   p_types: Array of metadata types ('nip11', 'nip66_rtt', 'nip66_ssl', 'nip66_geo')
--   p_generated_ats: Array of metadata generation timestamps
-- Returns: Number of junction rows inserted (relay_metadata)
-- Notes:
--   - Inserts into: relays → metadata → relay_metadata
--   - Hash is computed ONCE in PostgreSQL using sha256 (via CTE)
--   - Returns only junction count (last INSERT)
CREATE OR REPLACE FUNCTION relay_metadata_insert_cascade(
    p_relay_urls TEXT[],
    p_relay_networks TEXT[],
    p_relay_discovered_ats BIGINT[],
    p_metadata_datas JSONB[],
    p_types TEXT[],
    p_generated_ats BIGINT[]
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    row_count INTEGER;
BEGIN
    -- Single statement with chained CTEs for optimal performance
    WITH
    -- CTE 1: Unnest arrays and compute hash ONCE per row
    input_data AS (
        SELECT
            u AS relay_url,
            n AS network,
            d_at AS discovered_at,
            m AS metadata_data,
            t AS type,
            g AS generated_at,
            digest(m::TEXT, 'sha256') AS metadata_hash
        FROM unnest(
            p_relay_urls,
            p_relay_networks,
            p_relay_discovered_ats,
            p_metadata_datas,
            p_types,
            p_generated_ats
        ) AS x(u, n, d_at, m, t, g)
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
    INSERT INTO relay_metadata (relay_url, generated_at, type, metadata_id)
    SELECT relay_url, generated_at, type, metadata_hash
    FROM input_data
    ON CONFLICT (relay_url, generated_at, type) DO NOTHING;

    GET DIAGNOSTICS row_count = ROW_COUNT;
    RETURN row_count;
END;
$$;

COMMENT ON FUNCTION relay_metadata_insert_cascade(TEXT[], TEXT[], BIGINT[], JSONB[], TEXT[], BIGINT[]) IS
'Bulk insert relay metadata atomically, returns junction count';


-- ============================================================================
-- SERVICE DATA FUNCTIONS
-- ============================================================================

-- ----------------------------------------------------------------------------
-- service_data_upsert
-- ----------------------------------------------------------------------------
-- Description: Bulk upsert service data records (for candidates, cursors, state, etc.)
-- Parameters: Arrays of service_name, data_type, data_key, data (JSONB), updated_at
-- Returns: VOID (upsert always succeeds)
CREATE OR REPLACE FUNCTION service_data_upsert(
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

COMMENT ON FUNCTION service_data_upsert(TEXT[], TEXT[], TEXT[], JSONB[], BIGINT[]) IS
'Bulk upsert service data records (candidates, cursors, state)';


-- ----------------------------------------------------------------------------
-- service_data_get
-- ----------------------------------------------------------------------------
-- Description: Retrieves service data records with optional key filter
-- Parameters: service_name, data_type, optional data_key
-- Returns: TABLE of (data_key, data, updated_at)
CREATE OR REPLACE FUNCTION service_data_get(
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

COMMENT ON FUNCTION service_data_get IS 'Retrieves service data records with optional key filter';


-- ----------------------------------------------------------------------------
-- service_data_delete
-- ----------------------------------------------------------------------------
-- Description: Bulk delete service data records
-- Parameters: Arrays of service_name, data_type, data_key
-- Returns: Number of rows deleted
CREATE OR REPLACE FUNCTION service_data_delete(
    p_service_names TEXT[],
    p_data_types TEXT[],
    p_data_keys TEXT[]
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    row_count INTEGER;
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

    GET DIAGNOSTICS row_count = ROW_COUNT;
    RETURN row_count;
END;
$$;

COMMENT ON FUNCTION service_data_delete(TEXT[], TEXT[], TEXT[]) IS
'Bulk delete service data records, returns number of rows deleted';


-- ============================================================================
-- CRUD FUNCTIONS CREATED
-- ============================================================================
-- Level 1 (Base):
--   - relays_insert
--   - events_insert              (LilBrotr: computes tagvalues, discards tags/content/sig)
--   - metadata_insert
--   - events_relays_insert
--   - relay_metadata_insert
--   - service_data_upsert
--   - service_data_get
--   - service_data_delete
--
-- Level 2 (Cascade):
--   - events_relays_insert_cascade
--   - relay_metadata_insert_cascade
-- ============================================================================
