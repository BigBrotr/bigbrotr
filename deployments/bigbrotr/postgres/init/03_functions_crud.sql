/*
 * BigBrotr - 03_functions_crud.sql
 *
 * CRUD stored functions for bulk data operations. Organized in two levels:
 *
 *   Level 1 (Base) - Single-table operations:
 *     relay_insert, event_insert, metadata_insert,
 *     event_relay_insert, relay_metadata_insert,
 *     service_state_upsert, service_state_get, service_state_delete
 *
 *   Level 2 (Cascade) - Multi-table atomic operations that call Level 1:
 *     event_relay_insert_cascade  -> relay + event + event_relay
 *     relay_metadata_insert_cascade -> relay + metadata + relay_metadata
 *
 * All functions use array parameters for bulk operations via unnest(),
 * and ON CONFLICT DO NOTHING for idempotent inserts.
 *
 * Dependencies: 02_tables.sql
 */


-- ==========================================================================
-- LEVEL 1: BASE FUNCTIONS (single-table operations)
-- ==========================================================================


/*
 * relay_insert(TEXT[], TEXT[], BIGINT[]) -> INTEGER
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
CREATE OR REPLACE FUNCTION relay_insert(
    p_urls TEXT [],
    p_networks TEXT [],
    p_discovered_ats BIGINT []
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_row_count INTEGER;
BEGIN
    INSERT INTO relay (url, network, discovered_at)
    SELECT * FROM unnest(p_urls, p_networks, p_discovered_ats)
        AS t(url, network, discovered_at)
    ON CONFLICT (url) DO NOTHING;

    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    RETURN v_row_count;
END;
$$;

COMMENT ON FUNCTION relay_insert(TEXT [], TEXT [], BIGINT []) IS
'Bulk insert relays, returns number of rows inserted';


/*
 * event_insert(BYTEA[], BYTEA[], BIGINT[], INTEGER[], JSONB[], TEXT[], BYTEA[]) -> INTEGER
 *
 * Bulk-inserts Nostr events. Duplicate events (by id) are silently skipped.
 * Foreign key references to relays are NOT enforced here; use the cascade
 * version if relays may not exist yet.
 *
 * Parameters:
 *   p_event_ids        - Array of 32-byte event hashes
 *   p_pubkeys          - Array of 32-byte author public keys
 *   p_created_ats      - Array of Unix creation timestamps
 *   p_kinds            - Array of NIP-01 event kinds
 *   p_tags             - Array of JSONB tag arrays
 *   p_content_values   - Array of event content strings
 *   p_sigs             - Array of 64-byte Schnorr signatures
 *
 * Returns: Number of newly inserted rows
 */
CREATE OR REPLACE FUNCTION event_insert(
    p_event_ids BYTEA [],
    p_pubkeys BYTEA [],
    p_created_ats BIGINT [],
    p_kinds INTEGER [],
    p_tags JSONB [],
    p_content_values TEXT [],
    p_sigs BYTEA []
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_row_count INTEGER;
BEGIN
    INSERT INTO event (id, pubkey, created_at, kind, tags, content, sig)
    SELECT * FROM unnest(
        p_event_ids,
        p_pubkeys,
        p_created_ats,
        p_kinds,
        p_tags,
        p_content_values,
        p_sigs
    ) AS t(id, pubkey, created_at, kind, tags, content, sig)
    ON CONFLICT (id) DO NOTHING;

    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    RETURN v_row_count;
END;
$$;

COMMENT ON FUNCTION event_insert(BYTEA [], BYTEA [], BIGINT [], INTEGER [], JSONB [], TEXT [], BYTEA []) IS
'Bulk insert events, returns number of rows inserted';


/*
 * metadata_insert(BYTEA[], JSONB[]) -> INTEGER
 *
 * Bulk-inserts content-addressed metadata records. The SHA-256 hash (id) is
 * pre-computed in the application layer for deterministic deduplication.
 * Duplicate hashes are silently skipped.
 *
 * Parameters:
 *   p_ids       - Array of pre-computed SHA-256 hashes (32 bytes)
 *   p_payloads  - Array of JSON metadata documents
 *
 * Returns: Number of newly inserted rows
 */
DROP FUNCTION IF EXISTS metadata_insert(JSONB []);
CREATE OR REPLACE FUNCTION metadata_insert(
    p_ids BYTEA [],
    p_payloads JSONB []
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_row_count INTEGER;
BEGIN
    INSERT INTO metadata (id, payload)
    SELECT * FROM unnest(p_ids, p_payloads)
        AS t(id, payload)
    ON CONFLICT (id) DO NOTHING;

    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    RETURN v_row_count;
END;
$$;

COMMENT ON FUNCTION metadata_insert(BYTEA [], JSONB []) IS
'Bulk insert content-addressed metadata records, returns number of rows inserted';


/*
 * event_relay_insert(BYTEA[], TEXT[], BIGINT[]) -> INTEGER
 *
 * Bulk-inserts event-relay junction records. Both the referenced event and
 * relay MUST already exist; use event_relay_insert_cascade() if they
 * may not exist yet.
 *
 * Parameters:
 *   p_event_ids   - Array of event hashes (must exist in event table)
 *   p_relay_urls  - Array of relay URLs (must exist in relay table)
 *   p_seen_ats    - Array of Unix first-seen timestamps
 *
 * Returns: Number of newly inserted rows
 */
CREATE OR REPLACE FUNCTION event_relay_insert(
    p_event_ids BYTEA [],
    p_relay_urls TEXT [],
    p_seen_ats BIGINT []
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_row_count INTEGER;
BEGIN
    INSERT INTO event_relay (event_id, relay_url, seen_at)
    SELECT * FROM unnest(p_event_ids, p_relay_urls, p_seen_ats)
        AS t(event_id, relay_url, seen_at)
    ON CONFLICT (event_id, relay_url) DO NOTHING;

    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    RETURN v_row_count;
END;
$$;

COMMENT ON FUNCTION event_relay_insert(BYTEA [], TEXT [], BIGINT []) IS
'Bulk insert event-relay junctions, returns number of rows inserted';


/*
 * relay_metadata_insert(TEXT[], BYTEA[], TEXT[], BIGINT[]) -> INTEGER
 *
 * Bulk-inserts relay-metadata junction records. Both the referenced relay
 * and metadata MUST already exist; use relay_metadata_insert_cascade()
 * if they may not exist yet.
 *
 * Parameters:
 *   p_relay_urls       - Array of relay URLs (must exist in relay table)
 *   p_metadata_ids     - Array of metadata SHA-256 hashes (must exist in metadata table)
 *   p_metadata_types   - Array of check types (nip11_info, nip66_rtt, etc.)
 *   p_generated_ats    - Array of Unix collection timestamps
 *
 * Returns: Number of newly inserted rows
 */
DROP FUNCTION IF EXISTS relay_metadata_insert(TEXT [], JSONB [], TEXT [], BIGINT []);
DROP FUNCTION IF EXISTS relay_metadata_insert(TEXT [], BYTEA [], JSONB [], TEXT [], BIGINT []);
CREATE OR REPLACE FUNCTION relay_metadata_insert(
    p_relay_urls TEXT [],
    p_metadata_ids BYTEA [],
    p_metadata_types TEXT [],
    p_generated_ats BIGINT []
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_row_count INTEGER;
BEGIN
    INSERT INTO relay_metadata (relay_url, generated_at, metadata_type, metadata_id)
    SELECT relay_url, generated_at, metadata_type, metadata_id
    FROM unnest(p_relay_urls, p_metadata_ids, p_metadata_types, p_generated_ats)
        AS t(relay_url, metadata_id, metadata_type, generated_at)
    ON CONFLICT (relay_url, generated_at, metadata_type) DO NOTHING;

    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    RETURN v_row_count;
END;
$$;

COMMENT ON FUNCTION relay_metadata_insert(TEXT [], BYTEA [], TEXT [], BIGINT []) IS
'Bulk insert relay-metadata junctions, returns number of rows inserted';


-- ==========================================================================
-- LEVEL 2: CASCADE FUNCTIONS (multi-table atomic operations)
-- ==========================================================================


/*
 * event_relay_insert_cascade(...) -> INTEGER
 *
 * Atomically inserts relays, events, and their junction records in a single
 * transaction. Delegates to relay_insert() and event_insert() internally,
 * so customizations to those base functions automatically apply here.
 *
 * Parameters: Arrays of event fields + relay fields + seen_at timestamps
 * Returns: Number of junction rows inserted in event_relay
 */
CREATE OR REPLACE FUNCTION event_relay_insert_cascade(
    p_event_ids BYTEA [],
    p_pubkeys BYTEA [],
    p_created_ats BIGINT [],
    p_kinds INTEGER [],
    p_tags JSONB [],
    p_content_values TEXT [],
    p_sigs BYTEA [],
    p_relay_urls TEXT [],
    p_relay_networks TEXT [],
    p_relay_discovered_ats BIGINT [],
    p_seen_ats BIGINT []
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_row_count INTEGER;
BEGIN
    -- Ensure relay records exist before inserting junction rows
    PERFORM relay_insert(p_relay_urls, p_relay_networks, p_relay_discovered_ats);

    -- Ensure event records exist (customize event_insert, not this function)
    PERFORM event_insert(p_event_ids, p_pubkeys, p_created_ats, p_kinds, p_tags, p_content_values, p_sigs);

    -- Insert junction records, deduplicating within the batch via DISTINCT ON
    INSERT INTO event_relay (event_id, relay_url, seen_at)
    SELECT DISTINCT ON (event_id, relay_url) event_id, relay_url, seen_at
    FROM unnest(p_event_ids, p_relay_urls, p_seen_ats) AS t(event_id, relay_url, seen_at)
    ORDER BY event_id, relay_url, seen_at ASC
    ON CONFLICT (event_id, relay_url) DO NOTHING;

    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    RETURN v_row_count;
END;
$$;

COMMENT ON FUNCTION event_relay_insert_cascade(
    BYTEA [], BYTEA [], BIGINT [], INTEGER [], JSONB [], TEXT [], BYTEA [], TEXT [], TEXT [], BIGINT [], BIGINT []
) IS
'Atomically insert events with relays and junctions, returns junction row count';


/*
 * relay_metadata_insert_cascade(...) -> INTEGER
 *
 * Atomically inserts relays, metadata documents, and their junction records
 * in a single transaction. Delegates to relay_insert() and metadata_insert()
 * internally.
 *
 * Parameters: Arrays of relay fields + metadata fields + types + timestamps
 * Returns: Number of junction rows inserted in relay_metadata
 */
DROP FUNCTION IF EXISTS relay_metadata_insert_cascade(TEXT [], TEXT [], BIGINT [], JSONB [], TEXT [], BIGINT []);
DROP FUNCTION IF EXISTS relay_metadata_insert_cascade(
    TEXT [], TEXT [], BIGINT [], BYTEA [], JSONB [], TEXT [], BIGINT []
);
CREATE OR REPLACE FUNCTION relay_metadata_insert_cascade(
    p_relay_urls TEXT [],
    p_relay_networks TEXT [],
    p_relay_discovered_ats BIGINT [],
    p_metadata_ids BYTEA [],
    p_metadata_payloads JSONB [],
    p_metadata_types TEXT [],
    p_generated_ats BIGINT []
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_row_count INTEGER;
BEGIN
    -- Ensure relay records exist before inserting junction rows
    PERFORM relay_insert(p_relay_urls, p_relay_networks, p_relay_discovered_ats);

    -- Ensure metadata records exist (using pre-computed content hashes)
    PERFORM metadata_insert(p_metadata_ids, p_metadata_payloads);

    -- Insert junction records with full column aliases
    INSERT INTO relay_metadata (relay_url, generated_at, metadata_type, metadata_id)
    SELECT relay_url, generated_at, metadata_type, metadata_id
    FROM unnest(p_relay_urls, p_metadata_ids, p_metadata_types, p_generated_ats)
        AS t(relay_url, metadata_id, metadata_type, generated_at)
    ON CONFLICT (relay_url, generated_at, metadata_type) DO NOTHING;

    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    RETURN v_row_count;
END;
$$;

COMMENT ON FUNCTION relay_metadata_insert_cascade(
    TEXT [], TEXT [], BIGINT [], BYTEA [], JSONB [], TEXT [], BIGINT []
) IS
'Atomically insert relay metadata with relays and junctions, returns junction row count';


-- ==========================================================================
-- SERVICE STATE FUNCTIONS
-- ==========================================================================


/*
 * service_state_upsert(TEXT[], TEXT[], TEXT[], JSONB[], BIGINT[]) -> VOID
 *
 * Bulk upsert (insert or replace) service state records. When a record with
 * the same (service_name, state_type, state_key) already exists, its payload
 * and timestamp are fully replaced. DISTINCT ON deduplicates within the batch.
 *
 * Parameters:
 *   p_service_names  - Array of service identifiers
 *   p_state_types    - Array of state categories
 *   p_state_keys     - Array of unique keys within each service+type
 *   p_payloads       - Array of JSONB payloads
 *   p_updated_ats    - Array of Unix update timestamps
 */
CREATE OR REPLACE FUNCTION service_state_upsert(
    p_service_names TEXT [],
    p_state_types TEXT [],
    p_state_keys TEXT [],
    p_payloads JSONB [],
    p_updated_ats BIGINT []
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
BEGIN
    INSERT INTO service_state (service_name, state_type, state_key, payload, updated_at)
    SELECT DISTINCT ON (service_name, state_type, state_key)
        service_name, state_type, state_key, payload, updated_at
    FROM unnest(
        p_service_names,
        p_state_types,
        p_state_keys,
        p_payloads,
        p_updated_ats
    ) AS t(service_name, state_type, state_key, payload, updated_at)
    ORDER BY service_name, state_type, state_key, updated_at DESC
    ON CONFLICT (service_name, state_type, state_key)
    DO UPDATE SET
        payload = EXCLUDED.payload,
        updated_at = EXCLUDED.updated_at;
END;
$$;

COMMENT ON FUNCTION service_state_upsert(TEXT [], TEXT [], TEXT [], JSONB [], BIGINT []) IS
'Bulk upsert service state with deduplication and full replacement semantics';


/*
 * service_state_get(TEXT, TEXT, TEXT) -> TABLE(state_key, payload, updated_at)
 *
 * Retrieves service state records. When p_state_key is provided, returns the
 * single matching record. When NULL, returns all records for the given
 * service and state type, ordered by update timestamp ascending.
 *
 * Parameters:
 *   p_service_name  - Service identifier
 *   p_state_type    - State category
 *   p_state_key     - Specific key to retrieve (NULL for all records)
 *
 * Returns: Table of (state_key TEXT, payload JSONB, updated_at BIGINT)
 */
CREATE OR REPLACE FUNCTION service_state_get(
    p_service_name TEXT,
    p_state_type TEXT,
    p_state_key TEXT DEFAULT NULL
)
RETURNS TABLE (
    state_key TEXT,
    payload JSONB,
    updated_at BIGINT
)
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
BEGIN
    IF p_state_key IS NOT NULL THEN
        RETURN QUERY
        SELECT ss.state_key, ss.payload, ss.updated_at
        FROM service_state ss
        WHERE ss.service_name = p_service_name
          AND ss.state_type = p_state_type
          AND ss.state_key = p_state_key;
    ELSE
        RETURN QUERY
        SELECT ss.state_key, ss.payload, ss.updated_at
        FROM service_state ss
        WHERE ss.service_name = p_service_name
          AND ss.state_type = p_state_type
        ORDER BY ss.updated_at ASC;
    END IF;
END;
$$;

COMMENT ON FUNCTION service_state_get IS
'Retrieve service state records, optionally filtered by key';


/*
 * service_state_delete(TEXT[], TEXT[], TEXT[]) -> INTEGER
 *
 * Bulk-deletes service state records matching the given composite keys.
 *
 * Parameters:
 *   p_service_names  - Array of service identifiers
 *   p_state_types    - Array of state categories
 *   p_state_keys     - Array of unique keys
 *
 * Returns: Number of rows deleted
 */
CREATE OR REPLACE FUNCTION service_state_delete(
    p_service_names TEXT [],
    p_state_types TEXT [],
    p_state_keys TEXT []
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_row_count INTEGER;
BEGIN
    DELETE FROM service_state ss
    USING unnest(
        p_service_names,
        p_state_types,
        p_state_keys
    ) AS d(sn, st, sk)
    WHERE ss.service_name = d.sn
      AND ss.state_type = d.st
      AND ss.state_key = d.sk;

    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    RETURN v_row_count;
END;
$$;

COMMENT ON FUNCTION service_state_delete(TEXT [], TEXT [], TEXT []) IS
'Bulk delete service state records, returns number of rows deleted';
