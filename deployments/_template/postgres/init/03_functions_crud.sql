/*
 * Template - 03_functions_crud.sql
 *
 * CRUD stored functions for bulk data operations. Organized in two levels:
 *
 *   Level 1 (Base) - Single-table operations:
 *     relays_insert, events_insert, metadata_insert,
 *     events_relays_insert, relay_metadata_insert,
 *     service_data_upsert, service_data_get, service_data_delete
 *
 *   Level 2 (Cascade) - Multi-table atomic operations that call Level 1:
 *     events_relays_insert_cascade  -> relays + events + events_relays
 *     relay_metadata_insert_cascade -> relays + metadata + relay_metadata
 *
 * IMPORTANT: Function signatures are fixed and called by src/core/brotr.py.
 * All parameters must be accepted even if not stored. To customize event
 * storage, modify only the INSERT statement inside events_insert().
 *
 * Dependencies: 02_tables.sql
 * Customization: YES -- events_insert() INSERT statement (see examples)
 */


-- ==========================================================================
-- LEVEL 1: BASE FUNCTIONS (single-table operations)
-- ==========================================================================


/*
 * relays_insert(TEXT[], TEXT[], BIGINT[]) -> INTEGER
 *
 * Bulk-inserts relay records. Existing relays (by URL) are silently skipped.
 *
 * Parameters:
 *   p_urls            - Array of relay WebSocket URLs
 *   p_networks        - Array of network types (clearnet, tor, i2p, loki)
 *   p_discovered_ats  - Array of Unix discovery timestamps
 *
 * Returns: Number of newly inserted rows
 */
CREATE OR REPLACE FUNCTION relays_insert(
    p_urls TEXT [],
    p_networks TEXT [],
    p_discovered_ats BIGINT []
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

COMMENT ON FUNCTION relays_insert(TEXT [], TEXT [], BIGINT []) IS
'Bulk insert relays, returns number of rows inserted';


/*
 * events_insert(BYTEA[], BYTEA[], BIGINT[], INTEGER[], JSONB[], TEXT[], BYTEA[]) -> INTEGER
 *
 * Bulk-inserts Nostr events. The function signature is fixed for interface
 * compatibility, but the INSERT statement should be customized to match
 * your events table schema.
 *
 * Customization examples:
 *
 *   Minimal table (only id):
 *     INSERT INTO events (id)
 *     SELECT id FROM unnest(p_event_ids) AS t(id)
 *
 *   Lightweight table (id, pubkey, created_at, kind, tagvalues):
 *     INSERT INTO events (id, pubkey, created_at, kind, tagvalues)
 *     SELECT id, pubkey, created_at, kind, tags_to_tagvalues(tags)
 *     FROM unnest(p_event_ids, p_pubkeys, p_created_ats, p_kinds, p_tags)
 *         AS t(id, pubkey, created_at, kind, tags)
 *
 *   Full table (all columns, used below):
 *     INSERT INTO events (id, pubkey, created_at, kind, tags, content, sig)
 *     SELECT * FROM unnest(p_event_ids, p_pubkeys, ...)
 *
 * Returns: Number of newly inserted rows
 */
CREATE OR REPLACE FUNCTION events_insert(
    p_event_ids BYTEA [],
    p_pubkeys BYTEA [],
    p_created_ats BIGINT [],
    p_kinds INTEGER [],
    p_tags JSONB [],
    p_contents TEXT [],
    p_sigs BYTEA []
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    row_count INTEGER;
BEGIN
    -- CUSTOMIZE: Modify this INSERT to match your events table columns
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

    GET DIAGNOSTICS row_count = ROW_COUNT;
    RETURN row_count;
END;
$$;

COMMENT ON FUNCTION events_insert(BYTEA [], BYTEA [], BIGINT [], INTEGER [], JSONB [], TEXT [], BYTEA []) IS
'Bulk insert events, returns number of rows inserted';


/*
 * metadata_insert(BYTEA[], JSONB[]) -> INTEGER
 *
 * Bulk-inserts content-addressed metadata records. The SHA-256 hash (id) is
 * pre-computed in the application layer for deterministic deduplication.
 * Duplicate hashes are silently skipped.
 *
 * Parameters:
 *   p_ids     - Array of pre-computed SHA-256 hashes (32 bytes)
 *   p_values  - Array of JSON metadata documents
 *
 * Returns: Number of newly inserted rows
 */
DROP FUNCTION IF EXISTS metadata_insert(JSONB []);
CREATE OR REPLACE FUNCTION metadata_insert(
    p_ids BYTEA [],
    p_values JSONB []
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    row_count INTEGER;
BEGIN
    INSERT INTO metadata (id, value)
    SELECT * FROM unnest(p_ids, p_values)
    ON CONFLICT (id) DO NOTHING;

    GET DIAGNOSTICS row_count = ROW_COUNT;
    RETURN row_count;
END;
$$;

COMMENT ON FUNCTION metadata_insert(BYTEA [], JSONB []) IS
'Bulk insert content-addressed metadata records, returns number of rows inserted';


/*
 * events_relays_insert(BYTEA[], TEXT[], BIGINT[]) -> INTEGER
 *
 * Bulk-inserts event-relay junction records. Both the referenced event and
 * relay MUST already exist; use events_relays_insert_cascade() if they
 * may not exist yet.
 *
 * Returns: Number of newly inserted rows
 */
CREATE OR REPLACE FUNCTION events_relays_insert(
    p_event_ids BYTEA [],
    p_relay_urls TEXT [],
    p_seen_ats BIGINT []
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

COMMENT ON FUNCTION events_relays_insert(BYTEA [], TEXT [], BIGINT []) IS
'Bulk insert event-relay junctions, returns number of rows inserted';


/*
 * relay_metadata_insert(TEXT[], BYTEA[], JSONB[], TEXT[], BIGINT[]) -> INTEGER
 *
 * Bulk-inserts relay-metadata junction records. Both the referenced relay
 * and metadata MUST already exist; use relay_metadata_insert_cascade()
 * if they may not exist yet.
 *
 * The p_metadata_values parameter is accepted for interface compatibility
 * but is not used in the INSERT (metadata rows are inserted separately).
 *
 * Returns: Number of newly inserted rows
 */
DROP FUNCTION IF EXISTS relay_metadata_insert(TEXT [], JSONB [], TEXT [], BIGINT []);
CREATE OR REPLACE FUNCTION relay_metadata_insert(
    p_relay_urls TEXT [],
    p_metadata_ids BYTEA [],
    p_metadata_values JSONB [],
    p_metadata_types TEXT [],
    p_generated_ats BIGINT []
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    row_count INTEGER;
BEGIN
    -- Unnest aliases: u=relay_url, id=metadata_id, t=metadata_type, g=generated_at
    INSERT INTO relay_metadata (relay_url, generated_at, metadata_type, metadata_id)
    SELECT u, g, t, id
    FROM unnest(p_relay_urls, p_metadata_ids, p_metadata_types, p_generated_ats) AS x(u, id, t, g)
    ON CONFLICT (relay_url, generated_at, metadata_type) DO NOTHING;

    GET DIAGNOSTICS row_count = ROW_COUNT;
    RETURN row_count;
END;
$$;

COMMENT ON FUNCTION relay_metadata_insert(TEXT [], BYTEA [], JSONB [], TEXT [], BIGINT []) IS
'Bulk insert relay-metadata junctions, returns number of rows inserted';


-- ==========================================================================
-- LEVEL 2: CASCADE FUNCTIONS (multi-table atomic operations)
-- ==========================================================================


/*
 * events_relays_insert_cascade(...) -> INTEGER
 *
 * Atomically inserts relays, events, and their junction records in a single
 * transaction. Delegates to relays_insert() and events_insert() internally,
 * so customizations to those base functions automatically apply here.
 *
 * The function signature is fixed. All parameters must be accepted.
 *
 * Parameters: Arrays of event fields + relay fields + seen_at timestamps
 * Returns: Number of junction rows inserted in events_relays
 */
CREATE OR REPLACE FUNCTION events_relays_insert_cascade(
    p_event_ids BYTEA [],
    p_pubkeys BYTEA [],
    p_created_ats BIGINT [],
    p_kinds INTEGER [],
    p_tags JSONB [],
    p_contents TEXT [],
    p_sigs BYTEA [],
    p_relay_urls TEXT [],
    p_relay_networks TEXT [],
    p_relay_discovered_ats BIGINT [],
    p_seen_ats BIGINT []
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    row_count INTEGER;
BEGIN
    -- Ensure relay records exist before inserting junction rows
    PERFORM relays_insert(p_relay_urls, p_relay_networks, p_relay_discovered_ats);

    -- Ensure event records exist (customize events_insert, not this function)
    PERFORM events_insert(p_event_ids, p_pubkeys, p_created_ats, p_kinds, p_tags, p_contents, p_sigs);

    -- Insert junction records, deduplicating within the batch via DISTINCT ON
    INSERT INTO events_relays (event_id, relay_url, seen_at)
    SELECT DISTINCT ON (event_id, relay_url) event_id, relay_url, seen_at
    FROM unnest(p_event_ids, p_relay_urls, p_seen_ats) AS t(event_id, relay_url, seen_at)
    ON CONFLICT (event_id, relay_url) DO NOTHING;

    GET DIAGNOSTICS row_count = ROW_COUNT;
    RETURN row_count;
END;
$$;

COMMENT ON FUNCTION events_relays_insert_cascade(
    BYTEA [], BYTEA [], BIGINT [], INTEGER [], JSONB [], TEXT [], BYTEA [], TEXT [], TEXT [], BIGINT [], BIGINT []
) IS
'Atomically insert events with relays and junctions, returns junction row count';


/*
 * relay_metadata_insert_cascade(...) -> INTEGER
 *
 * Atomically inserts relays, metadata documents, and their junction records
 * in a single transaction. Delegates to relays_insert() and metadata_insert()
 * internally.
 *
 * Parameters: Arrays of relay fields + metadata fields + types + timestamps
 * Returns: Number of junction rows inserted in relay_metadata
 */
DROP FUNCTION IF EXISTS relay_metadata_insert_cascade(TEXT [], TEXT [], BIGINT [], JSONB [], TEXT [], BIGINT []);
CREATE OR REPLACE FUNCTION relay_metadata_insert_cascade(
    p_relay_urls TEXT [],
    p_relay_networks TEXT [],
    p_relay_discovered_ats BIGINT [],
    p_metadata_ids BYTEA [],
    p_metadata_values JSONB [],
    p_metadata_types TEXT [],
    p_generated_ats BIGINT []
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    row_count INTEGER;
BEGIN
    -- Ensure relay records exist before inserting junction rows
    PERFORM relays_insert(p_relay_urls, p_relay_networks, p_relay_discovered_ats);

    -- Ensure metadata records exist (using pre-computed content hashes)
    PERFORM metadata_insert(p_metadata_ids, p_metadata_values);

    -- Insert junction records with unnest aliases: u=url, id=hash, t=type, g=timestamp
    INSERT INTO relay_metadata (relay_url, generated_at, metadata_type, metadata_id)
    SELECT u, g, t, id
    FROM unnest(p_relay_urls, p_metadata_ids, p_metadata_types, p_generated_ats) AS x(u, id, t, g)
    ON CONFLICT (relay_url, generated_at, metadata_type) DO NOTHING;

    GET DIAGNOSTICS row_count = ROW_COUNT;
    RETURN row_count;
END;
$$;

COMMENT ON FUNCTION relay_metadata_insert_cascade(
    TEXT [], TEXT [], BIGINT [], BYTEA [], JSONB [], TEXT [], BIGINT []
) IS
'Atomically insert relay metadata with relays and junctions, returns junction row count';


-- ==========================================================================
-- SERVICE DATA FUNCTIONS
-- ==========================================================================


/*
 * service_data_upsert(TEXT[], TEXT[], TEXT[], JSONB[], BIGINT[]) -> VOID
 *
 * Bulk upsert (insert or replace) service state records. When a record with
 * the same (service_name, data_type, data_key) already exists, its data and
 * timestamp are fully replaced. DISTINCT ON deduplicates within the batch.
 */
CREATE OR REPLACE FUNCTION service_data_upsert(
    p_service_names TEXT [],
    p_data_types TEXT [],
    p_data_keys TEXT [],
    p_datas JSONB [],
    p_updated_ats BIGINT []
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO service_data (service_name, data_type, data_key, data, updated_at)
    SELECT DISTINCT ON (service_name, data_type, data_key)
        service_name, data_type, data_key, data, updated_at
    FROM unnest(
        p_service_names,
        p_data_types,
        p_data_keys,
        p_datas,
        p_updated_ats
    ) AS t(service_name, data_type, data_key, data, updated_at)
    ON CONFLICT (service_name, data_type, data_key)
    DO UPDATE SET
        data = EXCLUDED.data,
        updated_at = EXCLUDED.updated_at;
END;
$$;

COMMENT ON FUNCTION service_data_upsert(TEXT [], TEXT [], TEXT [], JSONB [], BIGINT []) IS
'Bulk upsert service data with deduplication and full replacement semantics';


/*
 * service_data_get(TEXT, TEXT, TEXT) -> TABLE(data_key, data, updated_at)
 *
 * Retrieves service data records. When p_data_key is provided, returns the
 * single matching record. When NULL, returns all records for the given
 * service and data type, ordered by update timestamp ascending.
 */
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

COMMENT ON FUNCTION service_data_get IS
'Retrieve service data records, optionally filtered by key';


/*
 * service_data_delete(TEXT[], TEXT[], TEXT[]) -> INTEGER
 *
 * Bulk-deletes service data records matching the given composite keys.
 *
 * Returns: Number of rows deleted
 */
CREATE OR REPLACE FUNCTION service_data_delete(
    p_service_names TEXT [],
    p_data_types TEXT [],
    p_data_keys TEXT []
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

COMMENT ON FUNCTION service_data_delete(TEXT [], TEXT [], TEXT []) IS
'Bulk delete service data records, returns number of rows deleted';
