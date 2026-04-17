/*
 * Brotr - 08_functions_refresh_current.sql
 *
 * Incremental refresh functions for narrow current winner tables.
 *
 * These functions maintain non-additive winner-takes-latest facts derived
 * from append-only event and relay-document streams.
 *
 * Dependencies: 03_tables_current.sql
 */

-- **************************************************************************
-- CURRENT TABLE REFRESH: latest/current state derived from append-only event data
-- **************************************************************************
-- These functions maintain non-additive "winner takes latest" facts.
-- They process only truly new events in the given observed_at range and update
-- current rows only when the candidate event outranks the stored winner.
-- **************************************************************************


/*
 * relay_document_current_refresh(p_after, p_until) -> INTEGER
 *
 * Maintains the current relay-document row per (relay_url, role) using
 * associated_at DESC, document_id DESC as the winner ordering.
 */
CREATE OR REPLACE FUNCTION relay_document_current_refresh(
    p_after BIGINT,
    p_until BIGINT
) RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_rows INTEGER;
BEGIN
    WITH new_rows AS (
        SELECT DISTINCT
            rm.relay_url,
            rm.role,
            rm.associated_at,
            rm.document_id
        FROM relay_document AS rm
        WHERE rm.associated_at > p_after
          AND rm.associated_at <= p_until
    ),
    delta AS (
        SELECT DISTINCT ON (relay_url, role)
            relay_url,
            role,
            associated_at,
            document_id
        FROM new_rows
        ORDER BY relay_url, role, associated_at DESC, document_id DESC
    )
    INSERT INTO relay_document_current
        (relay_url, role, associated_at, document_id)
    SELECT
        relay_url,
        role,
        associated_at,
        document_id
    FROM delta
    ON CONFLICT (relay_url, role) DO UPDATE SET
        associated_at = EXCLUDED.associated_at,
        document_id   = EXCLUDED.document_id
    WHERE EXCLUDED.associated_at > relay_document_current.associated_at
       OR (
           EXCLUDED.associated_at = relay_document_current.associated_at
           AND ENCODE(EXCLUDED.document_id, 'hex')
               > ENCODE(relay_document_current.document_id, 'hex')
       );

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION relay_document_current_refresh(BIGINT, BIGINT) IS
'Incremental refresh of current relay-document rows keyed by (relay_url, role).';


/*
 * replaceable_event_current_refresh(p_after, p_until) -> INTEGER
 *
 * Maintains the current replaceable event per (pubkey, kind) for kinds
 * 0, 3, and 10000-19999. The winner is ordered by created_at DESC, id DESC.
 */
CREATE OR REPLACE FUNCTION replaceable_event_current_refresh(
    p_after BIGINT,
    p_until BIGINT
) RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_rows INTEGER;
BEGIN
    WITH new_events AS (
        SELECT DISTINCT
            e.id,
            e.pubkey,
            e.created_at,
            e.kind
        FROM event_observation AS er
        INNER JOIN event AS e ON er.event_id = e.id
        WHERE er.observed_at > p_after
          AND er.observed_at <= p_until
          AND (
              e.kind = 0
              OR e.kind = 3
              OR (e.kind >= 10000 AND e.kind <= 19999)
          )
          AND NOT EXISTS (
              SELECT 1
              FROM event_observation AS older
              WHERE older.event_id = er.event_id
                AND older.observed_at <= p_after
          )
    ),
    delta AS (
        SELECT DISTINCT ON (e.pubkey, e.kind)
            e.pubkey,
            e.kind,
            e.id AS event_id,
            e.created_at
        FROM new_events AS e
        ORDER BY e.pubkey, e.kind, e.created_at DESC, e.id DESC
    )
    INSERT INTO replaceable_event_current (pubkey, kind, event_id)
    SELECT
        pubkey,
        kind,
        event_id
    FROM delta
    ON CONFLICT (pubkey, kind) DO UPDATE SET
        event_id = EXCLUDED.event_id
    WHERE (
            SELECT e.created_at
            FROM event AS e
            WHERE e.id = EXCLUDED.event_id
        ) > (
            SELECT e.created_at
            FROM event AS e
            WHERE e.id = replaceable_event_current.event_id
        )
       OR (
           (
               SELECT e.created_at
               FROM event AS e
               WHERE e.id = EXCLUDED.event_id
           ) = (
               SELECT e.created_at
               FROM event AS e
               WHERE e.id = replaceable_event_current.event_id
           )
           AND ENCODE(EXCLUDED.event_id, 'hex')
               > ENCODE(replaceable_event_current.event_id, 'hex')
       );

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION replaceable_event_current_refresh(BIGINT, BIGINT) IS
'Incremental refresh of current replaceable events for truly new kinds 0, 3, and 10000-19999.';


/*
 * addressable_event_current_refresh(p_after, p_until) -> INTEGER
 *
 * Maintains the current addressable event per (pubkey, kind, d_value) for
 * kinds 30000-39999. The winner is ordered by created_at DESC, id DESC.
 */
CREATE OR REPLACE FUNCTION addressable_event_current_refresh(
    p_after BIGINT,
    p_until BIGINT
) RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_rows INTEGER;
BEGIN
    WITH new_events AS (
        SELECT DISTINCT
            e.id,
            e.pubkey,
            e.created_at,
            e.kind,
            e.tags,
            e.tagvalues
        FROM event_observation AS er
        INNER JOIN event AS e ON er.event_id = e.id
        WHERE er.observed_at > p_after
          AND er.observed_at <= p_until
          AND e.kind >= 30000
          AND e.kind <= 39999
          AND NOT EXISTS (
              SELECT 1
              FROM event_observation AS older
              WHERE older.event_id = er.event_id
                AND older.observed_at <= p_after
          )
    ),
    extracted AS (
        SELECT
            e.id,
            e.pubkey,
            e.created_at,
            e.kind,
            event_d_tag(e.tags, e.tagvalues) AS d_value
        FROM new_events AS e
    ),
    delta AS (
        SELECT DISTINCT ON (e.pubkey, e.kind, e.d_value)
            e.pubkey,
            e.kind,
            e.d_value,
            e.id AS event_id,
            e.created_at
        FROM extracted AS e
        ORDER BY e.pubkey, e.kind, e.d_value, e.created_at DESC, e.id DESC
    )
    INSERT INTO addressable_event_current (pubkey, kind, d_value, event_id)
    SELECT
        pubkey,
        kind,
        d_value,
        event_id
    FROM delta
    ON CONFLICT (pubkey, kind, d_value) DO UPDATE SET
        event_id = EXCLUDED.event_id
    WHERE (
            SELECT e.created_at
            FROM event AS e
            WHERE e.id = EXCLUDED.event_id
        ) > (
            SELECT e.created_at
            FROM event AS e
            WHERE e.id = addressable_event_current.event_id
        )
       OR (
           (
               SELECT e.created_at
               FROM event AS e
               WHERE e.id = EXCLUDED.event_id
           ) = (
               SELECT e.created_at
               FROM event AS e
               WHERE e.id = addressable_event_current.event_id
           )
           AND ENCODE(EXCLUDED.event_id, 'hex')
               > ENCODE(addressable_event_current.event_id, 'hex')
       );

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION addressable_event_current_refresh(BIGINT, BIGINT) IS
'Incremental refresh of current addressable events for truly new kinds 30000-39999.';
