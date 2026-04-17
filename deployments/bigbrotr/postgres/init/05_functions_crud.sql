/*
 * Brotr - 05_functions_crud.sql
 *
 * CRUD stored functions for bulk data operations. Organized in two levels:
 *
 *   Level 1 (Base) - Single-table operations:
 *     relay_insert, event_insert, document_insert,
 *     event_observation_insert, relay_document_insert,
 *     service_state_upsert, service_state_get, service_state_delete
 *
 *   Level 2 (Cascade) - Multi-table atomic operations that call Level 1:
 *     event_observation_insert_cascade  -> relay + event + event_observation
 *     relay_document_insert_cascade -> relay + document + relay_document
 *
 * IMPORTANT: Function signatures are fixed and called by src/bigbrotr/core/brotr.py.
 * All parameters must be accepted even if not stored. To customize event
 * storage, modify only the INSERT statement inside event_insert().
 *
 * Dependencies: 02_tables_core.sql
 * Customization: event_insert() INSERT statement (see events_insert_comment block)
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
 *   p_stored_ats  - Array of Unix archive-entry timestamps for canonical relay rows
 *
 * Returns: Number of newly inserted rows
 */
CREATE OR REPLACE FUNCTION relay_insert(
    p_urls TEXT [],
    p_networks TEXT [],
    p_stored_ats BIGINT []
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_row_count INTEGER;
BEGIN
    INSERT INTO relay (url, network, stored_at)
    SELECT * FROM unnest(p_urls, p_networks, p_stored_ats)
        AS t(url, network, stored_at)
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
 * Bulk-inserts Nostr events. The function signature is fixed for interface
 * compatibility, but the INSERT statement should be customized to match
 * your event table schema.
 *
 * Customization examples:
 *
 *   Minimal table (only id):
 *     INSERT INTO event (id)
 *     SELECT id FROM unnest(p_event_ids) AS t(id)
 *
 *   Lightweight table (id, pubkey, created_at, kind, tagvalues):
 *     INSERT INTO event (id, pubkey, created_at, kind, tagvalues)
 *     SELECT id, pubkey, created_at, kind, tags_to_tagvalues(tags)
 *     FROM unnest(p_event_ids, p_pubkeys, p_created_ats, p_kinds, p_tags)
 *         AS t(id, pubkey, created_at, kind, tags)
 *
 *   Full table (all columns, used below):
 *     INSERT INTO event (id, pubkey, created_at, kind, tags, tagvalues, content, sig)
 *     SELECT id, pubkey, created_at, kind, tags, tags_to_tagvalues(tags), content, sig
 *     FROM unnest(p_event_ids, p_pubkeys, p_created_ats, p_kinds, p_tags, ...)
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
AS $$
DECLARE
    v_row_count INTEGER;
BEGIN
    INSERT INTO event (id, pubkey, created_at, kind, tags, tagvalues, content, sig)
    SELECT id, pubkey, created_at, kind, tags, tags_to_tagvalues(tags), content, sig
    FROM unnest(
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
'Bulk insert events with tagvalues computed at insert time, returns number of rows inserted';


/*
 * document_insert(BYTEA[], TEXT[], JSONB[]) -> INTEGER
 *
 * Bulk-inserts content-addressed document records. The SHA-256 hash (id) is
 * pre-computed in the application layer for deterministic deduplication.
 * Duplicates (same hash + same type) are silently skipped.
 *
 * Parameters:
 *   p_ids             - Array of pre-computed SHA-256 hashes (32 bytes)
 *   p_document_types  - Array of document types (nip11_info, nip66_rtt, etc.)
 *   p_data            - Array of JSON documents
 *
 * Returns: Number of newly inserted rows
 */
DROP FUNCTION IF EXISTS document_insert(JSONB []);
DROP FUNCTION IF EXISTS document_insert(BYTEA [], JSONB []);
DROP FUNCTION IF EXISTS document_insert(BYTEA [], JSONB [], TEXT []);
CREATE OR REPLACE FUNCTION document_insert(
    p_ids BYTEA [],
    p_document_types TEXT [],
    p_data JSONB []
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_row_count INTEGER;
BEGIN
    INSERT INTO document (id, type, data)
    SELECT * FROM unnest(p_ids, p_document_types, p_data)
        AS t(id, type, data)
    ON CONFLICT (id, type) DO NOTHING;

    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    RETURN v_row_count;
END;
$$;

COMMENT ON FUNCTION document_insert(BYTEA [], TEXT [], JSONB []) IS
'Bulk insert content-addressed document records, returns number of rows inserted';


/*
 * event_observation_insert(BYTEA[], TEXT[], BIGINT[]) -> INTEGER
 *
 * Bulk-inserts event-observation junction records. Both the referenced event and
 * relay MUST already exist; use event_observation_insert_cascade() if they
 * may not exist yet.
 *
 * Parameters:
 *   p_event_ids   - Array of event hashes (must exist in event table)
 *   p_relay_urls  - Array of relay URLs (must exist in relay table)
 *   p_observed_ats - Array of Unix first-observed timestamps
 *
 * Returns: Number of newly inserted rows
 */
CREATE OR REPLACE FUNCTION event_observation_insert(
    p_event_ids BYTEA [],
    p_relay_urls TEXT [],
    p_observed_ats BIGINT []
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_row_count INTEGER;
BEGIN
    INSERT INTO event_observation (event_id, relay_url, observed_at)
    SELECT * FROM unnest(p_event_ids, p_relay_urls, p_observed_ats)
        AS t(event_id, relay_url, observed_at)
    ON CONFLICT (event_id, relay_url) DO NOTHING;

    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    RETURN v_row_count;
END;
$$;

COMMENT ON FUNCTION event_observation_insert(BYTEA [], TEXT [], BIGINT []) IS
'Bulk insert event-observation junctions, returns number of rows inserted';


/*
 * relay_document_insert(TEXT[], BYTEA[], TEXT[], BIGINT[]) -> INTEGER
 *
 * Bulk-inserts relay-document junction records. Both the referenced relay
 * and document MUST already exist; use relay_document_insert_cascade()
 * if they may not exist yet.
 *
 * Parameters:
 *   p_relay_urls       - Array of relay URLs (must exist in relay table)
 *   p_document_ids     - Array of document SHA-256 hashes (must exist in document table)
 *   p_roles            - Array of document roles (nip11_info, nip66_rtt, etc.)
 *   p_associated_ats   - Array of Unix association timestamps
 *
 * Returns: Number of newly inserted rows
 */
DROP FUNCTION IF EXISTS relay_document_insert(TEXT [], JSONB [], TEXT [], BIGINT []);
DROP FUNCTION IF EXISTS relay_document_insert(TEXT [], BYTEA [], JSONB [], TEXT [], BIGINT []);
CREATE OR REPLACE FUNCTION relay_document_insert(
    p_relay_urls TEXT [],
    p_document_ids BYTEA [],
    p_roles TEXT [],
    p_associated_ats BIGINT []
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_row_count INTEGER;
BEGIN
    INSERT INTO relay_document (relay_url, document_id, role, associated_at)
    SELECT relay_url, document_id, role, associated_at
    FROM unnest(p_relay_urls, p_document_ids, p_roles, p_associated_ats)
        AS t(relay_url, document_id, role, associated_at)
    ON CONFLICT (relay_url, associated_at, role) DO NOTHING;

    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    RETURN v_row_count;
END;
$$;

COMMENT ON FUNCTION relay_document_insert(TEXT [], BYTEA [], TEXT [], BIGINT []) IS
'Bulk insert relay-document junctions, returns number of rows inserted';


-- ==========================================================================
-- LEVEL 2: CASCADE FUNCTIONS (multi-table atomic operations)
-- ==========================================================================


/*
 * event_observation_insert_cascade(...) -> INTEGER
 *
 * Atomically inserts relays, events, and their junction records in a single
 * transaction. Delegates to relay_insert() and event_insert() internally,
 * so customizations to those base functions automatically apply here.
 *
 * Parameters: Arrays of event fields + relay fields + observed-at timestamps
 * Returns: Number of junction rows inserted in event_observation
 */
CREATE OR REPLACE FUNCTION event_observation_insert_cascade(
    p_event_ids BYTEA [],
    p_pubkeys BYTEA [],
    p_created_ats BIGINT [],
    p_kinds INTEGER [],
    p_tags JSONB [],
    p_content_values TEXT [],
    p_sigs BYTEA [],
    p_relay_urls TEXT [],
    p_relay_networks TEXT [],
    p_relay_stored_ats BIGINT [],
    p_observed_ats BIGINT []
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_row_count INTEGER;
BEGIN
    -- Ensure relay records exist before inserting junction rows
    PERFORM relay_insert(p_relay_urls, p_relay_networks, p_relay_stored_ats);

    -- Ensure event records exist (customize event_insert, not this function)
    PERFORM event_insert(p_event_ids, p_pubkeys, p_created_ats, p_kinds, p_tags, p_content_values, p_sigs);

    -- Insert junction records, deduplicating within the batch via DISTINCT ON
    INSERT INTO event_observation (event_id, relay_url, observed_at)
    SELECT DISTINCT ON (event_id, relay_url) event_id, relay_url, observed_at
    FROM unnest(p_event_ids, p_relay_urls, p_observed_ats) AS t(event_id, relay_url, observed_at)
    ON CONFLICT (event_id, relay_url) DO NOTHING;

    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    RETURN v_row_count;
END;
$$;

COMMENT ON FUNCTION event_observation_insert_cascade(
    BYTEA [], BYTEA [], BIGINT [], INTEGER [], JSONB [], TEXT [], BYTEA [],
    TEXT [], TEXT [], BIGINT [], BIGINT []
) IS
'Atomically insert events with relays and junctions, returns junction row count';


/*
 * relay_document_insert_cascade(...) -> INTEGER
 *
 * Atomically inserts relays, document rows, and their junction records
 * in a single transaction. Delegates to relay_insert() and document_insert()
 * internally.
 *
 * Parameters: Arrays of relay fields + document fields + roles + timestamps
 * Returns: Number of junction rows inserted in relay_document
 */
DROP FUNCTION IF EXISTS relay_document_insert_cascade(TEXT [], TEXT [], BIGINT [], JSONB [], TEXT [], BIGINT []);
DROP FUNCTION IF EXISTS relay_document_insert_cascade(TEXT [], TEXT [], BIGINT [], BYTEA [], JSONB [], TEXT [], BIGINT []);
CREATE OR REPLACE FUNCTION relay_document_insert_cascade(
    p_relay_urls TEXT [],
    p_relay_networks TEXT [],
    p_relay_stored_ats BIGINT [],
    p_document_ids BYTEA [],
    p_roles TEXT [],
    p_document_data JSONB [],
    p_associated_ats BIGINT []
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_row_count INTEGER;
BEGIN
    -- Ensure relay records exist before inserting junction rows
    PERFORM relay_insert(p_relay_urls, p_relay_networks, p_relay_stored_ats);

    -- Ensure document rows exist (using pre-computed content hashes)
    PERFORM document_insert(p_document_ids, p_roles, p_document_data);

    -- Insert junction records with full column aliases
    INSERT INTO relay_document (relay_url, document_id, role, associated_at)
    SELECT relay_url, document_id, role, associated_at
    FROM unnest(p_relay_urls, p_document_ids, p_roles, p_associated_ats)
        AS t(relay_url, document_id, role, associated_at)
    ON CONFLICT (relay_url, associated_at, role) DO NOTHING;

    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    RETURN v_row_count;
END;
$$;

COMMENT ON FUNCTION relay_document_insert_cascade(TEXT [], TEXT [], BIGINT [], BYTEA [], TEXT [], JSONB [], BIGINT []) IS
'Atomically insert relay documents with relays and junctions, returns junction row count';


-- ==========================================================================
-- SERVICE STATE FUNCTIONS
-- ==========================================================================


/*
 * service_state_upsert(TEXT[], TEXT[], TEXT[], JSONB[]) -> INTEGER
 *
 * Bulk upsert (insert or replace) service state records. When a record with
 * the same (service_name, state_type, state_key) already exists, its
 * state_value is fully replaced. DISTINCT ON deduplicates within the batch.
 *
 * Parameters:
 *   p_service_names   - Array of service identifiers
 *   p_state_types     - Array of state categories
 *   p_state_keys      - Array of unique keys within each service+type
 *   p_state_values    - Array of JSONB values
 */
CREATE OR REPLACE FUNCTION service_state_upsert(
    p_service_names TEXT [],
    p_state_types TEXT [],
    p_state_keys TEXT [],
    p_state_values JSONB []
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_row_count INTEGER;
BEGIN
    INSERT INTO service_state (service_name, state_type, state_key, state_value)
    SELECT DISTINCT ON (service_name, state_type, state_key)
        service_name, state_type, state_key, state_value
    FROM unnest(
        p_service_names,
        p_state_types,
        p_state_keys,
        p_state_values
    ) AS t(service_name, state_type, state_key, state_value)
    ON CONFLICT (service_name, state_type, state_key)
    DO UPDATE SET
        state_value = EXCLUDED.state_value;

    GET DIAGNOSTICS v_row_count = ROW_COUNT;
    RETURN v_row_count;
END;
$$;

COMMENT ON FUNCTION service_state_upsert(TEXT [], TEXT [], TEXT [], JSONB []) IS
'Bulk upsert service state with deduplication and full replacement semantics, returns number of rows affected';


/*
 * service_state_get(TEXT, TEXT, TEXT) -> TABLE(state_key, state_value)
 *
 * Retrieves service state records. When p_state_key is provided, returns the
 * single matching record. When NULL, returns all records for the given
 * service and state type, ordered by state_key ascending.
 *
 * Parameters:
 *   p_service_name  - Service identifier
 *   p_state_type    - State category
 *   p_state_key     - Specific key to retrieve (NULL for all records)
 *
 * Returns: Table of (state_key TEXT, state_value JSONB)
 */
CREATE OR REPLACE FUNCTION service_state_get(
    p_service_name TEXT,
    p_state_type TEXT,
    p_state_key TEXT DEFAULT NULL
)
RETURNS TABLE (
    state_key TEXT,
    state_value JSONB
)
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_state_key IS NOT NULL THEN
        RETURN QUERY
        SELECT ss.state_key, ss.state_value
        FROM service_state ss
        WHERE ss.service_name = p_service_name
          AND ss.state_type = p_state_type
          AND ss.state_key = p_state_key;
    ELSE
        RETURN QUERY
        SELECT ss.state_key, ss.state_value
        FROM service_state ss
        WHERE ss.service_name = p_service_name
          AND ss.state_type = p_state_type
        ORDER BY ss.state_key ASC;
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
