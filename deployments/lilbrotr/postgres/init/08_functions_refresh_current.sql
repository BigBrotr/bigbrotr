/*
 * Brotr - 08_functions_refresh_current.sql
 *
 * Incremental refresh functions for current-state tables.
 *
 * These functions maintain non-additive winner-takes-latest facts derived
 * from append-only event and relay metadata streams.
 *
 * Dependencies: 03_tables_current.sql
 */

-- **************************************************************************
-- CURRENT TABLE REFRESH: latest/current state derived from append-only event data
-- **************************************************************************
-- These functions maintain non-additive "winner takes latest" facts.
-- They process only truly new events in the given seen_at range and update
-- current rows only when the candidate event outranks the stored winner.
-- **************************************************************************


/*
 * relay_metadata_current_refresh(p_after, p_until) -> INTEGER
 *
 * Maintains the current metadata row per (relay_url, metadata_type) using
 * generated_at DESC, metadata_id DESC as the winner ordering.
 */
CREATE OR REPLACE FUNCTION relay_metadata_current_refresh(
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
            rm.metadata_type,
            rm.generated_at,
            rm.metadata_id,
            m.data
        FROM relay_metadata AS rm
        INNER JOIN metadata AS m
            ON rm.metadata_id = m.id AND rm.metadata_type = m.type
        WHERE rm.generated_at > p_after
          AND rm.generated_at <= p_until
    ),
    delta AS (
        SELECT DISTINCT ON (relay_url, metadata_type)
            relay_url,
            metadata_type,
            generated_at,
            metadata_id,
            data
        FROM new_rows
        ORDER BY relay_url, metadata_type, generated_at DESC, metadata_id DESC
    )
    INSERT INTO relay_metadata_current
        (relay_url, metadata_type, generated_at, metadata_id, data)
    SELECT
        relay_url,
        metadata_type,
        generated_at,
        metadata_id,
        data
    FROM delta
    ON CONFLICT (relay_url, metadata_type) DO UPDATE SET
        generated_at = EXCLUDED.generated_at,
        metadata_id  = EXCLUDED.metadata_id,
        data         = EXCLUDED.data
    WHERE EXCLUDED.generated_at > relay_metadata_current.generated_at
       OR (
           EXCLUDED.generated_at = relay_metadata_current.generated_at
           AND ENCODE(EXCLUDED.metadata_id, 'hex')
               > ENCODE(relay_metadata_current.metadata_id, 'hex')
       );

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION relay_metadata_current_refresh(BIGINT, BIGINT) IS
'Incremental refresh of current relay metadata snapshots keyed by (relay_url, metadata_type).';


/*
 * events_replaceable_current_refresh(p_after, p_until) -> INTEGER
 *
 * Maintains the current replaceable event per (pubkey, kind) for kinds
 * 0, 3, and 10000-19999. The winner is ordered by created_at DESC, id DESC.
 */
CREATE OR REPLACE FUNCTION events_replaceable_current_refresh(
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
            e.tagvalues,
            e.content,
            e.sig
        FROM event_relay AS er
        INNER JOIN event AS e ON er.event_id = e.id
        WHERE er.seen_at > p_after
          AND er.seen_at <= p_until
          AND (
              e.kind = 0
              OR e.kind = 3
              OR (e.kind >= 10000 AND e.kind <= 19999)
          )
          AND NOT EXISTS (
              SELECT 1
              FROM event_relay AS older
              WHERE older.event_id = er.event_id
                AND older.seen_at <= p_after
          )
    ),
    delta AS (
        SELECT DISTINCT ON (e.pubkey, e.kind)
            e.pubkey,
            e.kind,
            e.id,
            e.created_at,
            seen.first_seen_at,
            e.tags,
            e.tagvalues,
            e.content,
            e.sig
        FROM new_events AS e
        INNER JOIN LATERAL (
            SELECT MIN(er.seen_at) AS first_seen_at
            FROM event_relay AS er
            WHERE er.event_id = e.id
        ) AS seen ON TRUE
        ORDER BY e.pubkey, e.kind, e.created_at DESC, e.id DESC
    )
    INSERT INTO events_replaceable_current
        (pubkey, kind, id, created_at, first_seen_at, tags, tagvalues, content, sig)
    SELECT
        pubkey,
        kind,
        id,
        created_at,
        first_seen_at,
        tags,
        tagvalues,
        content,
        sig
    FROM delta
    ON CONFLICT (pubkey, kind) DO UPDATE SET
        id            = EXCLUDED.id,
        created_at    = EXCLUDED.created_at,
        first_seen_at = EXCLUDED.first_seen_at,
        tags          = EXCLUDED.tags,
        tagvalues     = EXCLUDED.tagvalues,
        content       = EXCLUDED.content,
        sig           = EXCLUDED.sig
    WHERE EXCLUDED.created_at > events_replaceable_current.created_at
       OR (
           EXCLUDED.created_at = events_replaceable_current.created_at
           AND ENCODE(EXCLUDED.id, 'hex') > ENCODE(events_replaceable_current.id, 'hex')
       );

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION events_replaceable_current_refresh(BIGINT, BIGINT) IS
'Incremental refresh of current replaceable events for truly new kinds 0, 3, and 10000-19999.';


/*
 * events_addressable_current_refresh(p_after, p_until) -> INTEGER
 *
 * Maintains the current addressable event per (pubkey, kind, d_tag) for
 * kinds 30000-39999. The winner is ordered by created_at DESC, id DESC.
 */
CREATE OR REPLACE FUNCTION events_addressable_current_refresh(
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
            e.tagvalues,
            e.content,
            e.sig
        FROM event_relay AS er
        INNER JOIN event AS e ON er.event_id = e.id
        WHERE er.seen_at > p_after
          AND er.seen_at <= p_until
          AND e.kind >= 30000
          AND e.kind <= 39999
          AND NOT EXISTS (
              SELECT 1
              FROM event_relay AS older
              WHERE older.event_id = er.event_id
                AND older.seen_at <= p_after
          )
    ),
    extracted AS (
        SELECT
            e.id,
            e.pubkey,
            e.created_at,
            e.kind,
            e.tags,
            e.tagvalues,
            e.content,
            e.sig,
            seen.first_seen_at,
            COALESCE(d_exact.val, d_fallback.val, '') AS d_tag
        FROM new_events AS e
        INNER JOIN LATERAL (
            SELECT MIN(er.seen_at) AS first_seen_at
            FROM event_relay AS er
            WHERE er.event_id = e.id
        ) AS seen ON TRUE
        LEFT JOIN LATERAL (
            SELECT t.tag ->> 1 AS val
            FROM jsonb_array_elements(e.tags) WITH ORDINALITY AS t(tag, ord)
            WHERE t.tag ->> 0 = 'd'
            ORDER BY ord
            LIMIT 1
        ) AS d_exact ON TRUE
        LEFT JOIN LATERAL (
            SELECT substring(t.tv FROM 3) AS val
            FROM unnest(e.tagvalues) WITH ORDINALITY AS t(tv, ord)
            WHERE t.tv LIKE 'd:%'
            ORDER BY ord
            LIMIT 1
        ) AS d_fallback ON TRUE
    ),
    delta AS (
        SELECT DISTINCT ON (e.pubkey, e.kind, e.d_tag)
            e.pubkey,
            e.kind,
            e.d_tag,
            e.id,
            e.created_at,
            e.first_seen_at,
            e.tags,
            e.tagvalues,
            e.content,
            e.sig
        FROM extracted AS e
        ORDER BY e.pubkey, e.kind, e.d_tag, e.created_at DESC, e.id DESC
    )
    INSERT INTO events_addressable_current
        (pubkey, kind, d_tag, id, created_at, first_seen_at, tags, tagvalues, content, sig)
    SELECT
        pubkey,
        kind,
        d_tag,
        id,
        created_at,
        first_seen_at,
        tags,
        tagvalues,
        content,
        sig
    FROM delta
    ON CONFLICT (pubkey, kind, d_tag) DO UPDATE SET
        id            = EXCLUDED.id,
        created_at    = EXCLUDED.created_at,
        first_seen_at = EXCLUDED.first_seen_at,
        tags          = EXCLUDED.tags,
        tagvalues     = EXCLUDED.tagvalues,
        content       = EXCLUDED.content,
        sig           = EXCLUDED.sig
    WHERE EXCLUDED.created_at > events_addressable_current.created_at
       OR (
           EXCLUDED.created_at = events_addressable_current.created_at
           AND ENCODE(EXCLUDED.id, 'hex') > ENCODE(events_addressable_current.id, 'hex')
       );

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION events_addressable_current_refresh(BIGINT, BIGINT) IS
'Incremental refresh of current addressable events for truly new kinds 30000-39999.';
