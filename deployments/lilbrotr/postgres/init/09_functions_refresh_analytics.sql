/*
 * Brotr - 09_functions_refresh_analytics.sql
 *
 * Refresh functions for analytics tables and periodic reconciliations.
 *
 * Analytics tables use pure incremental SQL functions that receive a
 * caller-managed watermark range. The Python refresher service owns
 * dependency order, checkpointing, and periodic reconciliations.
 *
 * Dependencies: 03_tables_current.sql, 04_tables_analytics.sql
 */


-- **************************************************************************
-- UTILITY: bolt11 invoice amount extraction
-- **************************************************************************


/*
 * bolt11_amount_msats(bolt11 TEXT) -> BIGINT
 *
 * Extracts the payment amount in millisatoshis from a BOLT11 Lightning
 * invoice string by parsing the human-readable prefix. Does NOT verify
 * that the invoice was actually paid -- only that the amount is valid.
 *
 * Returns NULL for "any amount" invoices (no amount in prefix) or
 * unparseable strings.
 *
 * Multipliers per BOLT11 spec:
 *   m = milli-BTC (0.001)    -> * 100,000,000 msats
 *   u = micro-BTC (0.000001) -> * 100,000 msats
 *   n = nano-BTC             -> * 100 msats
 *   p = pico-BTC             -> * 0.1 msats (truncated to integer)
 */
CREATE OR REPLACE FUNCTION bolt11_amount_msats(bolt11 TEXT)
RETURNS BIGINT
LANGUAGE sql IMMUTABLE STRICT
AS $$
    WITH parsed AS (
        SELECT (regexp_match(LOWER(bolt11), '^ln(?:bc|bcrt|tb|tbs)(\d+)([munp])?1'))[1:2] AS parts
    ),
    normalized AS (
        SELECT CASE
            WHEN parts[1] IS NULL THEN NULL::NUMERIC
            WHEN parts[2] = 'm' THEN parts[1]::NUMERIC * 100000000
            WHEN parts[2] = 'u' THEN parts[1]::NUMERIC * 100000
            WHEN parts[2] = 'n' THEN parts[1]::NUMERIC * 100
            WHEN parts[2] = 'p' THEN TRUNC(parts[1]::NUMERIC / 10)
            WHEN parts[2] IS NULL THEN parts[1]::NUMERIC * 100000000000
            ELSE NULL::NUMERIC
        END AS msats
        FROM parsed
    )
    SELECT CASE
        WHEN msats IS NULL OR msats > 9223372036854775807::NUMERIC THEN NULL
        ELSE msats::BIGINT
    END
    FROM normalized;
$$;

COMMENT ON FUNCTION bolt11_amount_msats(TEXT) IS
'Extract payment amount in millisatoshis from a BOLT11 invoice prefix. Returns NULL for any-amount invoices.';


-- **************************************************************************
-- SUMMARY TABLE REFRESH: Cross-tabulations (refresh BEFORE entity tables)
-- **************************************************************************
-- All functions are PURE: they receive a seen_at range, process the delta,
-- and return the number of rows affected. No side effects on service_state.
-- **************************************************************************


/*
 * pubkey_kind_stats_refresh(p_after, p_until) -> INTEGER
 *
 * Processes TRULY NEW events observed in the given seen_at range.
 * An event is "truly new" if it has no event_relay row with seen_at <= p_after
 * (i.e., it was not already counted in a previous refresh cycle).
 *
 * This avoids double-counting when an existing event appears on a new relay.
 */
CREATE OR REPLACE FUNCTION pubkey_kind_stats_refresh(
    p_after BIGINT,
    p_until BIGINT
) RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_rows INTEGER;
BEGIN
    WITH new_events AS (
        SELECT DISTINCT e.id, e.pubkey, e.kind, e.created_at
        FROM event_relay AS er
        INNER JOIN event AS e ON er.event_id = e.id
        WHERE er.seen_at > p_after AND er.seen_at <= p_until
          AND NOT EXISTS (
              SELECT 1 FROM event_relay AS older
              WHERE older.event_id = er.event_id
                AND older.seen_at <= p_after
          )
    ),
    delta AS (
        SELECT
            ENCODE(pubkey, 'hex') AS pubkey,
            kind,
            COUNT(*) AS event_count,
            MIN(created_at) AS first_event_at,
            MAX(created_at) AS last_event_at
        FROM new_events
        GROUP BY pubkey, kind
    )
    INSERT INTO pubkey_kind_stats (pubkey, kind, event_count, first_event_at, last_event_at)
    SELECT pubkey, kind, event_count, first_event_at, last_event_at
    FROM delta
    ON CONFLICT (pubkey, kind) DO UPDATE SET
        event_count    = pubkey_kind_stats.event_count + EXCLUDED.event_count,
        first_event_at = LEAST(pubkey_kind_stats.first_event_at, EXCLUDED.first_event_at),
        last_event_at  = GREATEST(pubkey_kind_stats.last_event_at, EXCLUDED.last_event_at);

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION pubkey_kind_stats_refresh(BIGINT, BIGINT) IS
'Incremental refresh of pubkey_kind_stats for truly new events in (p_after, p_until] seen_at range.';


/*
 * pubkey_relay_stats_refresh(p_after, p_until) -> INTEGER
 *
 * Processes ALL new event_relay rows in the given seen_at range.
 * Every new (event, relay) pair is a valid observation, even if the
 * event itself was already counted by pubkey_kind_stats.
 */
CREATE OR REPLACE FUNCTION pubkey_relay_stats_refresh(
    p_after BIGINT,
    p_until BIGINT
) RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_rows INTEGER;
BEGIN
    WITH delta AS (
        SELECT
            ENCODE(e.pubkey, 'hex') AS pubkey,
            er.relay_url,
            COUNT(*) AS event_count,
            MIN(e.created_at) AS first_event_at,
            MAX(e.created_at) AS last_event_at
        FROM event_relay AS er
        INNER JOIN event AS e ON er.event_id = e.id
        WHERE er.seen_at > p_after AND er.seen_at <= p_until
        GROUP BY e.pubkey, er.relay_url
    )
    INSERT INTO pubkey_relay_stats (pubkey, relay_url, event_count, first_event_at, last_event_at)
    SELECT pubkey, relay_url, event_count, first_event_at, last_event_at
    FROM delta
    ON CONFLICT (pubkey, relay_url) DO UPDATE SET
        event_count    = pubkey_relay_stats.event_count + EXCLUDED.event_count,
        first_event_at = LEAST(pubkey_relay_stats.first_event_at, EXCLUDED.first_event_at),
        last_event_at  = GREATEST(pubkey_relay_stats.last_event_at, EXCLUDED.last_event_at);

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION pubkey_relay_stats_refresh(BIGINT, BIGINT) IS
'Incremental refresh of pubkey_relay_stats for new event_relay rows in (p_after, p_until] seen_at range.';


/*
 * relay_kind_stats_refresh(p_after, p_until) -> INTEGER
 *
 * Processes ALL new event_relay rows in the given seen_at range.
 */
CREATE OR REPLACE FUNCTION relay_kind_stats_refresh(
    p_after BIGINT,
    p_until BIGINT
) RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_rows INTEGER;
BEGIN
    WITH delta AS (
        SELECT
            er.relay_url,
            e.kind,
            COUNT(*) AS event_count,
            MIN(e.created_at) AS first_event_at,
            MAX(e.created_at) AS last_event_at
        FROM event_relay AS er
        INNER JOIN event AS e ON er.event_id = e.id
        WHERE er.seen_at > p_after AND er.seen_at <= p_until
        GROUP BY er.relay_url, e.kind
    )
    INSERT INTO relay_kind_stats (relay_url, kind, event_count, first_event_at, last_event_at)
    SELECT relay_url, kind, event_count, first_event_at, last_event_at
    FROM delta
    ON CONFLICT (relay_url, kind) DO UPDATE SET
        event_count    = relay_kind_stats.event_count + EXCLUDED.event_count,
        first_event_at = LEAST(relay_kind_stats.first_event_at, EXCLUDED.first_event_at),
        last_event_at  = GREATEST(relay_kind_stats.last_event_at, EXCLUDED.last_event_at);

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION relay_kind_stats_refresh(BIGINT, BIGINT) IS
'Incremental refresh of relay_kind_stats for new event_relay rows in (p_after, p_until] seen_at range.';


-- **************************************************************************
-- SUMMARY TABLE REFRESH: Entity tables (refresh AFTER cross-tabulations)
-- **************************************************************************
-- Entity tables derive unique_kinds/unique_relays/unique_pubkeys from
-- cross-tab row COUNTs. Cross-tabs must be refreshed first.
-- **************************************************************************


/*
 * pubkey_stats_refresh(p_after, p_until) -> INTEGER
 *
 * Processes truly new events (same deduplication as pubkey_kind_stats).
 * Derives unique_kinds from pubkey_kind_stats row count and
 * unique_relays from pubkey_relay_stats row count.
 */
CREATE OR REPLACE FUNCTION pubkey_stats_refresh(
    p_after BIGINT,
    p_until BIGINT
) RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_rows INTEGER;
BEGIN
    WITH new_events AS (
        SELECT DISTINCT e.id, e.pubkey, e.kind, e.created_at
        FROM event_relay AS er
        INNER JOIN event AS e ON er.event_id = e.id
        WHERE er.seen_at > p_after AND er.seen_at <= p_until
          AND NOT EXISTS (
              SELECT 1 FROM event_relay AS older
              WHERE older.event_id = er.event_id
                AND older.seen_at <= p_after
          )
    ),
    impacted_pubkeys AS (
        SELECT DISTINCT ENCODE(e.pubkey, 'hex') AS pubkey
        FROM event_relay AS er
        INNER JOIN event AS e ON er.event_id = e.id
        WHERE er.seen_at > p_after AND er.seen_at <= p_until
    ),
    delta AS (
        SELECT
            ENCODE(pubkey, 'hex') AS pubkey,
            COUNT(*) AS event_count,
            MIN(created_at) AS first_event_at,
            MAX(created_at) AS last_event_at,
            COUNT(*) FILTER (
                WHERE kind = 1
                OR kind = 2
                OR (kind >= 4 AND kind <= 44)
                OR (kind >= 1000 AND kind <= 9999)
            ) AS regular_count,
            COUNT(*) FILTER (
                WHERE kind = 0
                OR kind = 3
                OR (kind >= 10000 AND kind <= 19999)
            ) AS replaceable_count,
            COUNT(*) FILTER (
                WHERE kind >= 20000 AND kind <= 29999
            ) AS ephemeral_count,
            COUNT(*) FILTER (
                WHERE kind >= 30000 AND kind <= 39999
            ) AS addressable_count
        FROM new_events
        GROUP BY pubkey
    ),
    kind_rollup AS (
        SELECT
            pks.pubkey,
            COUNT(*)::INTEGER AS unique_kinds,
            MIN(pks.first_event_at) AS first_event_at,
            MAX(pks.last_event_at) AS last_event_at
        FROM pubkey_kind_stats AS pks
        INNER JOIN impacted_pubkeys AS ip ON ip.pubkey = pks.pubkey
        GROUP BY pks.pubkey
    ),
    relay_rollup AS (
        SELECT
            prs.pubkey,
            COUNT(*)::INTEGER AS unique_relays
        FROM pubkey_relay_stats AS prs
        INNER JOIN impacted_pubkeys AS ip ON ip.pubkey = prs.pubkey
        GROUP BY prs.pubkey
    )
    INSERT INTO pubkey_stats
        (pubkey, event_count, first_event_at, last_event_at,
         regular_count, replaceable_count, ephemeral_count, addressable_count,
         unique_kinds, unique_relays)
    SELECT
        ip.pubkey,
        COALESCE(d.event_count, 0),
        COALESCE(d.first_event_at, kr.first_event_at),
        COALESCE(d.last_event_at, kr.last_event_at),
        COALESCE(d.regular_count, 0),
        COALESCE(d.replaceable_count, 0),
        COALESCE(d.ephemeral_count, 0),
        COALESCE(d.addressable_count, 0),
        COALESCE(kr.unique_kinds, 0),
        COALESCE(rr.unique_relays, 0)
    FROM impacted_pubkeys AS ip
    LEFT JOIN delta AS d ON d.pubkey = ip.pubkey
    LEFT JOIN kind_rollup AS kr ON kr.pubkey = ip.pubkey
    LEFT JOIN relay_rollup AS rr ON rr.pubkey = ip.pubkey
    ON CONFLICT (pubkey) DO UPDATE SET
        event_count       = pubkey_stats.event_count + EXCLUDED.event_count,
        first_event_at    = CASE
            WHEN EXCLUDED.first_event_at IS NULL THEN pubkey_stats.first_event_at
            WHEN pubkey_stats.first_event_at IS NULL THEN EXCLUDED.first_event_at
            ELSE LEAST(pubkey_stats.first_event_at, EXCLUDED.first_event_at)
        END,
        last_event_at     = CASE
            WHEN EXCLUDED.last_event_at IS NULL THEN pubkey_stats.last_event_at
            WHEN pubkey_stats.last_event_at IS NULL THEN EXCLUDED.last_event_at
            ELSE GREATEST(pubkey_stats.last_event_at, EXCLUDED.last_event_at)
        END,
        regular_count     = pubkey_stats.regular_count + EXCLUDED.regular_count,
        replaceable_count = pubkey_stats.replaceable_count + EXCLUDED.replaceable_count,
        ephemeral_count   = pubkey_stats.ephemeral_count + EXCLUDED.ephemeral_count,
        addressable_count = pubkey_stats.addressable_count + EXCLUDED.addressable_count,
        unique_kinds      = EXCLUDED.unique_kinds,
        unique_relays     = EXCLUDED.unique_relays;

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION pubkey_stats_refresh(BIGINT, BIGINT) IS
'Incremental refresh of pubkey_stats. Cross-tabs must be refreshed first.';


/*
 * kind_stats_refresh(p_after, p_until) -> INTEGER
 *
 * Processes truly new events.
 * Derives unique_pubkeys from pubkey_kind_stats and
 * unique_relays from relay_kind_stats.
 */
CREATE OR REPLACE FUNCTION kind_stats_refresh(
    p_after BIGINT,
    p_until BIGINT
) RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_rows INTEGER;
BEGIN
    WITH new_events AS (
        SELECT DISTINCT e.id, e.pubkey, e.kind, e.created_at
        FROM event_relay AS er
        INNER JOIN event AS e ON er.event_id = e.id
        WHERE er.seen_at > p_after AND er.seen_at <= p_until
          AND NOT EXISTS (
              SELECT 1 FROM event_relay AS older
              WHERE older.event_id = er.event_id
                AND older.seen_at <= p_after
          )
    ),
    impacted_kinds AS (
        SELECT DISTINCT e.kind
        FROM event_relay AS er
        INNER JOIN event AS e ON er.event_id = e.id
        WHERE er.seen_at > p_after AND er.seen_at <= p_until
    ),
    delta AS (
        SELECT
            kind,
            COUNT(*) AS event_count,
            MIN(created_at) AS first_event_at,
            MAX(created_at) AS last_event_at,
            CASE
                WHEN kind = 1
                    OR kind = 2
                    OR (kind >= 4 AND kind <= 44)
                    OR (kind >= 1000 AND kind <= 9999) THEN 'regular'
                WHEN kind = 0
                    OR kind = 3
                    OR (kind >= 10000 AND kind <= 19999) THEN 'replaceable'
                WHEN kind >= 20000 AND kind <= 29999 THEN 'ephemeral'
                WHEN kind >= 30000 AND kind <= 39999 THEN 'addressable'
                ELSE 'other'
            END AS category
        FROM new_events
        GROUP BY kind
    ),
    pubkey_rollup AS (
        SELECT
            pks.kind,
            COUNT(*)::INTEGER AS unique_pubkeys,
            MIN(pks.first_event_at) AS first_event_at,
            MAX(pks.last_event_at) AS last_event_at
        FROM pubkey_kind_stats AS pks
        INNER JOIN impacted_kinds AS ik ON ik.kind = pks.kind
        GROUP BY pks.kind
    ),
    relay_rollup AS (
        SELECT
            rks.kind,
            COUNT(*)::INTEGER AS unique_relays
        FROM relay_kind_stats AS rks
        INNER JOIN impacted_kinds AS ik ON ik.kind = rks.kind
        GROUP BY rks.kind
    )
    INSERT INTO kind_stats
        (kind, event_count, category, first_event_at, last_event_at,
         unique_pubkeys, unique_relays)
    SELECT
        ik.kind,
        COALESCE(d.event_count, 0),
        COALESCE(d.category, 'other'),
        COALESCE(d.first_event_at, pr.first_event_at),
        COALESCE(d.last_event_at, pr.last_event_at),
        COALESCE(pr.unique_pubkeys, 0),
        COALESCE(rr.unique_relays, 0)
    FROM impacted_kinds AS ik
    LEFT JOIN delta AS d ON d.kind = ik.kind
    LEFT JOIN pubkey_rollup AS pr ON pr.kind = ik.kind
    LEFT JOIN relay_rollup AS rr ON rr.kind = ik.kind
    ON CONFLICT (kind) DO UPDATE SET
        event_count    = kind_stats.event_count + EXCLUDED.event_count,
        first_event_at = CASE
            WHEN EXCLUDED.first_event_at IS NULL THEN kind_stats.first_event_at
            WHEN kind_stats.first_event_at IS NULL THEN EXCLUDED.first_event_at
            ELSE LEAST(kind_stats.first_event_at, EXCLUDED.first_event_at)
        END,
        last_event_at  = CASE
            WHEN EXCLUDED.last_event_at IS NULL THEN kind_stats.last_event_at
            WHEN kind_stats.last_event_at IS NULL THEN EXCLUDED.last_event_at
            ELSE GREATEST(kind_stats.last_event_at, EXCLUDED.last_event_at)
        END,
        unique_pubkeys = EXCLUDED.unique_pubkeys,
        unique_relays  = EXCLUDED.unique_relays;

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION kind_stats_refresh(BIGINT, BIGINT) IS
'Incremental refresh of kind_stats. Cross-tabs must be refreshed first.';


/*
 * relay_stats_refresh(p_after, p_until) -> INTEGER
 *
 * Processes ALL new event_relay rows (not just new events).
 * Derives unique_pubkeys from pubkey_relay_stats and
 * unique_kinds from relay_kind_stats.
 *
 * Does NOT update RTT/NIP-11/network fields — those are handled by
 * relay_stats_metadata_refresh().
 */
CREATE OR REPLACE FUNCTION relay_stats_refresh(
    p_after BIGINT,
    p_until BIGINT
) RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_rows INTEGER;
BEGIN
    WITH delta AS (
        SELECT
            er.relay_url,
            COUNT(*) AS event_count,
            MIN(e.created_at) AS first_event_at,
            MAX(e.created_at) AS last_event_at,
            COUNT(*) FILTER (
                WHERE e.kind = 1
                OR e.kind = 2
                OR (e.kind >= 4 AND e.kind <= 44)
                OR (e.kind >= 1000 AND e.kind <= 9999)
            ) AS regular_count,
            COUNT(*) FILTER (
                WHERE e.kind = 0
                OR e.kind = 3
                OR (e.kind >= 10000 AND e.kind <= 19999)
            ) AS replaceable_count,
            COUNT(*) FILTER (
                WHERE e.kind >= 20000 AND e.kind <= 29999
            ) AS ephemeral_count,
            COUNT(*) FILTER (
                WHERE e.kind >= 30000 AND e.kind <= 39999
            ) AS addressable_count
        FROM event_relay AS er
        INNER JOIN event AS e ON er.event_id = e.id
        WHERE er.seen_at > p_after AND er.seen_at <= p_until
        GROUP BY er.relay_url
    )
    INSERT INTO relay_stats
        (relay_url, event_count, first_event_at, last_event_at,
         regular_count, replaceable_count, ephemeral_count, addressable_count,
         unique_pubkeys, unique_kinds)
    SELECT
        d.relay_url, d.event_count, d.first_event_at, d.last_event_at,
        d.regular_count, d.replaceable_count, d.ephemeral_count, d.addressable_count,
        COALESCE((SELECT COUNT(*)::INTEGER FROM pubkey_relay_stats WHERE relay_url = d.relay_url), 0),
        COALESCE((SELECT COUNT(*)::INTEGER FROM relay_kind_stats WHERE relay_url = d.relay_url), 0)
    FROM delta AS d
    ON CONFLICT (relay_url) DO UPDATE SET
        event_count       = relay_stats.event_count + EXCLUDED.event_count,
        first_event_at    = LEAST(relay_stats.first_event_at, EXCLUDED.first_event_at),
        last_event_at     = GREATEST(relay_stats.last_event_at, EXCLUDED.last_event_at),
        regular_count     = relay_stats.regular_count + EXCLUDED.regular_count,
        replaceable_count = relay_stats.replaceable_count + EXCLUDED.replaceable_count,
        ephemeral_count   = relay_stats.ephemeral_count + EXCLUDED.ephemeral_count,
        addressable_count = relay_stats.addressable_count + EXCLUDED.addressable_count,
        unique_pubkeys    = COALESCE(
            (SELECT COUNT(*)::INTEGER FROM pubkey_relay_stats WHERE relay_url = relay_stats.relay_url), 0
        ),
        unique_kinds      = COALESCE(
            (SELECT COUNT(*)::INTEGER FROM relay_kind_stats WHERE relay_url = relay_stats.relay_url), 0
        );

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION relay_stats_refresh(BIGINT, BIGINT) IS
'Incremental refresh of relay_stats event counts. Cross-tabs must be refreshed first. Call relay_stats_metadata_refresh() separately for RTT/NIP-11.';


-- **************************************************************************
-- SUMMARY TABLE REFRESH: Canonical contact-list facts
-- **************************************************************************
-- These tables derive current follow-graph facts from current kind=3 events.
-- contact_lists_current captures one row per follower's current latest list;
-- contact_list_edges_current expands that into deduplicated current edges.
-- **************************************************************************


/*
 * contact_lists_current_refresh(p_after, p_until) -> INTEGER
 *
 * Tracks current latest kind=3 contact list events from
 * events_replaceable_current. A follower is impacted only when their current
 * winning kind=3 event first became visible in the given seen_at range.
 */
CREATE OR REPLACE FUNCTION contact_lists_current_refresh(
    p_after BIGINT,
    p_until BIGINT
) RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_rows INTEGER;
BEGIN
    WITH changed_current AS (
        SELECT
            erc.id,
            erc.pubkey,
            erc.created_at,
            erc.tags,
            erc.tagvalues,
            erc.first_seen_at
        FROM events_replaceable_current AS erc
        WHERE erc.kind = 3
          AND erc.first_seen_at > p_after
          AND erc.first_seen_at <= p_until
    ),
    delta AS (
        SELECT
            ENCODE(pubkey, 'hex') AS follower_pubkey,
            ENCODE(id, 'hex') AS source_event_id,
            created_at AS source_created_at,
            first_seen_at AS source_seen_at,
            COALESCE(exact_counts.cnt, fallback_counts.cnt, 0) AS follow_count
        FROM changed_current
        LEFT JOIN LATERAL (
            SELECT COUNT(*)::BIGINT AS cnt
            FROM (
                SELECT DISTINCT LOWER(t.tag ->> 1) AS followed_pubkey
                FROM jsonb_array_elements(tags) AS t(tag)
                WHERE t.tag ->> 0 = 'p'
                  AND LOWER(t.tag ->> 1) ~ '^[0-9a-f]{64}$'
            ) AS dedup
        ) AS exact_counts ON tags IS NOT NULL
        LEFT JOIN LATERAL (
            SELECT COUNT(*)::BIGINT AS cnt
            FROM (
                SELECT DISTINCT LOWER(substring(t.tv FROM 3)) AS followed_pubkey
                FROM unnest(tagvalues) WITH ORDINALITY AS t(tv, ord)
                WHERE t.tv LIKE 'p:%'
                  AND LOWER(substring(t.tv FROM 3)) ~ '^[0-9a-f]{64}$'
            ) AS dedup
        ) AS fallback_counts ON tags IS NULL
    )
    INSERT INTO contact_lists_current
        (follower_pubkey, source_event_id, source_created_at, source_seen_at, follow_count)
    SELECT
        follower_pubkey,
        source_event_id,
        source_created_at,
        source_seen_at,
        follow_count
    FROM delta
    ON CONFLICT (follower_pubkey) DO UPDATE SET
        source_event_id   = EXCLUDED.source_event_id,
        source_created_at = EXCLUDED.source_created_at,
        source_seen_at    = EXCLUDED.source_seen_at,
        follow_count      = EXCLUDED.follow_count;

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION contact_lists_current_refresh(BIGINT, BIGINT) IS
'Incremental refresh of current latest kind=3 contact lists from events_replaceable_current. Stores one row per follower with stable source_seen_at and deduplicated follow_count.';


/*
 * contact_list_edges_current_refresh(p_after, p_until) -> INTEGER
 *
 * Replaces all current follow edges for followers whose latest contact list
 * first became visible in the given seen_at range.
 */
CREATE OR REPLACE FUNCTION contact_list_edges_current_refresh(
    p_after BIGINT,
    p_until BIGINT
) RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_rows INTEGER := 0;
    v_partial INTEGER;
BEGIN
    CREATE TEMP TABLE _changed_contact_lists ON COMMIT DROP AS
    SELECT
        follower_pubkey,
        source_event_id,
        source_created_at,
        source_seen_at
    FROM contact_lists_current
    WHERE source_seen_at > p_after AND source_seen_at <= p_until;

    DELETE FROM contact_list_edges_current
    WHERE follower_pubkey IN (SELECT follower_pubkey FROM _changed_contact_lists);
    GET DIAGNOSTICS v_rows = ROW_COUNT;

    WITH current_lists AS (
        SELECT
            c.follower_pubkey,
            c.source_event_id,
            c.source_created_at,
            c.source_seen_at,
            erc.tags,
            erc.tagvalues
        FROM _changed_contact_lists AS c
        INNER JOIN events_replaceable_current AS erc
            ON ENCODE(erc.id, 'hex') = c.source_event_id
    ),
    exact_edges AS (
        SELECT
            cl.follower_pubkey,
            LOWER(t.tag ->> 1) AS followed_pubkey,
            cl.source_event_id,
            cl.source_created_at,
            cl.source_seen_at
        FROM current_lists AS cl
        CROSS JOIN LATERAL jsonb_array_elements(cl.tags) AS t(tag)
        WHERE cl.tags IS NOT NULL
          AND t.tag ->> 0 = 'p'
          AND LOWER(t.tag ->> 1) ~ '^[0-9a-f]{64}$'
    ),
    fallback_edges AS (
        SELECT
            cl.follower_pubkey,
            LOWER(substring(t.tv FROM 3)) AS followed_pubkey,
            cl.source_event_id,
            cl.source_created_at,
            cl.source_seen_at
        FROM current_lists AS cl
        CROSS JOIN LATERAL unnest(cl.tagvalues) WITH ORDINALITY AS t(tv, ord)
        WHERE cl.tags IS NULL
          AND t.tv LIKE 'p:%'
          AND LOWER(substring(t.tv FROM 3)) ~ '^[0-9a-f]{64}$'
    ),
    delta AS (
        SELECT DISTINCT
            follower_pubkey,
            followed_pubkey,
            source_event_id,
            source_created_at,
            source_seen_at
        FROM (
            SELECT * FROM exact_edges
            UNION ALL
            SELECT * FROM fallback_edges
        ) AS all_edges
    )
    INSERT INTO contact_list_edges_current
        (follower_pubkey, followed_pubkey, source_event_id, source_created_at, source_seen_at)
    SELECT
        follower_pubkey,
        followed_pubkey,
        source_event_id,
        source_created_at,
        source_seen_at
    FROM delta
    ON CONFLICT (follower_pubkey, followed_pubkey) DO UPDATE SET
        source_event_id   = EXCLUDED.source_event_id,
        source_created_at = EXCLUDED.source_created_at,
        source_seen_at    = EXCLUDED.source_seen_at;

    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    DROP TABLE IF EXISTS _changed_contact_lists;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION contact_list_edges_current_refresh(BIGINT, BIGINT) IS
'Incremental refresh of deduplicated current follow edges derived from current kind=3 contact lists.';


-- **************************************************************************
-- PERIODIC REFRESH: Rolling windows and metadata
-- **************************************************************************


/*
 * rolling_windows_refresh() -> VOID
 *
 * Recomputes events_last_24h/7d/30d for all summary entity tables.
 * Scans only the last 30 days of events (bounded by index range scan on
 * event_relay.seen_at). Designed to run every few hours.
 *
 * For pubkeys/kinds with no recent activity, windows are zeroed out by
 * checking last_event_at against the 30-day threshold.
 */
CREATE OR REPLACE FUNCTION rolling_windows_refresh()
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_now BIGINT := EXTRACT(EPOCH FROM NOW())::BIGINT;
    v_24h BIGINT := v_now - 86400;
    v_7d  BIGINT := v_now - 604800;
    v_30d BIGINT := v_now - 2592000;
BEGIN
    -- pubkey_stats
    WITH windows AS (
        SELECT
            ENCODE(pubkey, 'hex') AS pubkey,
            COUNT(*) FILTER (WHERE created_at >= v_24h) AS last_24h,
            COUNT(*) FILTER (WHERE created_at >= v_7d)  AS last_7d,
            COUNT(*) FILTER (WHERE created_at >= v_30d) AS last_30d
        FROM event
        WHERE created_at >= v_30d
        GROUP BY pubkey
    )
    UPDATE pubkey_stats ps SET
        events_last_24h = COALESCE(w.last_24h, 0),
        events_last_7d  = COALESCE(w.last_7d, 0),
        events_last_30d = COALESCE(w.last_30d, 0)
    FROM windows w
    WHERE ps.pubkey = w.pubkey;

    UPDATE pubkey_stats SET
        events_last_24h = 0, events_last_7d = 0, events_last_30d = 0
    WHERE last_event_at < v_30d
      AND (events_last_24h > 0 OR events_last_7d > 0 OR events_last_30d > 0);

    -- kind_stats
    WITH windows AS (
        SELECT
            kind,
            COUNT(*) FILTER (WHERE created_at >= v_24h) AS last_24h,
            COUNT(*) FILTER (WHERE created_at >= v_7d)  AS last_7d,
            COUNT(*) FILTER (WHERE created_at >= v_30d) AS last_30d
        FROM event
        WHERE created_at >= v_30d
        GROUP BY kind
    )
    UPDATE kind_stats ks SET
        events_last_24h = COALESCE(w.last_24h, 0),
        events_last_7d  = COALESCE(w.last_7d, 0),
        events_last_30d = COALESCE(w.last_30d, 0)
    FROM windows w
    WHERE ks.kind = w.kind;

    UPDATE kind_stats SET
        events_last_24h = 0, events_last_7d = 0, events_last_30d = 0
    WHERE last_event_at < v_30d
      AND (events_last_24h > 0 OR events_last_7d > 0 OR events_last_30d > 0);

    -- relay_stats uses event_relay.seen_at (observed activity by relay)
    WITH windows AS (
        SELECT
            er.relay_url,
            COUNT(*) FILTER (WHERE er.seen_at >= v_24h) AS last_24h,
            COUNT(*) FILTER (WHERE er.seen_at >= v_7d)  AS last_7d,
            COUNT(*) FILTER (WHERE er.seen_at >= v_30d) AS last_30d
        FROM event_relay AS er
        WHERE er.seen_at >= v_30d
        GROUP BY er.relay_url
    )
    UPDATE relay_stats rs SET
        events_last_24h = COALESCE(w.last_24h, 0),
        events_last_7d  = COALESCE(w.last_7d, 0),
        events_last_30d = COALESCE(w.last_30d, 0)
    FROM windows w
    WHERE rs.relay_url = w.relay_url;

    UPDATE relay_stats SET
        events_last_24h = 0, events_last_7d = 0, events_last_30d = 0
    WHERE NOT EXISTS (
        SELECT 1
        FROM event_relay AS er
        WHERE er.relay_url = relay_stats.relay_url
          AND er.seen_at >= v_30d
    )
      AND (events_last_24h > 0 OR events_last_7d > 0 OR events_last_30d > 0);
END;
$$;

COMMENT ON FUNCTION rolling_windows_refresh() IS
'Recompute rolling time-window columns (last 24h/7d/30d) for all entity summary tables. Scans only last 30 days.';


/*
 * relay_stats_metadata_refresh() -> VOID
 *
 * Updates RTT averages, NIP-11 info, network, and discovered_at fields
 * in relay_stats. Ensures new relays (with no events yet) get a row.
 *
 * Designed to run periodically (e.g., hourly or after monitor cycles).
 */
CREATE OR REPLACE FUNCTION relay_stats_metadata_refresh()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    -- Remove rows for relays that no longer exist in the source table.
    DELETE FROM relay_stats AS rs
    WHERE NOT EXISTS (
        SELECT 1
        FROM relay AS r
        WHERE r.url = rs.relay_url
    );

    -- Seed new relays that have no relay_stats row yet
    INSERT INTO relay_stats (relay_url, network, discovered_at)
    SELECT r.url, r.network, r.discovered_at
    FROM relay AS r
    WHERE NOT EXISTS (SELECT 1 FROM relay_stats WHERE relay_url = r.url)
    ON CONFLICT (relay_url) DO NOTHING;

    -- Update network and discovered_at from relay table
    UPDATE relay_stats rs SET
        network = r.network,
        discovered_at = r.discovered_at
    FROM relay r
    WHERE rs.relay_url = r.url
      AND (rs.network IS DISTINCT FROM r.network
           OR rs.discovered_at IS DISTINCT FROM r.discovered_at);

    -- Update RTT averages (last 10 measurements)
    WITH rtt_ranked AS (
        SELECT
            rm.relay_url,
            m.data -> 'data' ->> 'rtt_open' AS rtt_open,
            m.data -> 'data' ->> 'rtt_read' AS rtt_read,
            m.data -> 'data' ->> 'rtt_write' AS rtt_write,
            ROW_NUMBER() OVER (
                PARTITION BY rm.relay_url ORDER BY rm.generated_at DESC
            ) AS rn
        FROM relay_metadata AS rm
        INNER JOIN metadata AS m
            ON rm.metadata_id = m.id AND rm.metadata_type = m.type
        WHERE rm.metadata_type = 'nip66_rtt'
    ),
    rtt_agg AS (
        SELECT
            relay_url,
            ROUND(AVG(rtt_open::INTEGER)::NUMERIC, 2) AS avg_rtt_open,
            ROUND(AVG(rtt_read::INTEGER)::NUMERIC, 2) AS avg_rtt_read,
            ROUND(AVG(rtt_write::INTEGER)::NUMERIC, 2) AS avg_rtt_write
        FROM rtt_ranked
        WHERE rn <= 10
        GROUP BY relay_url
    )
    UPDATE relay_stats rs SET
        avg_rtt_open  = rtt.avg_rtt_open,
        avg_rtt_read  = rtt.avg_rtt_read,
        avg_rtt_write = rtt.avg_rtt_write
    FROM rtt_agg rtt
    WHERE rs.relay_url = rtt.relay_url;

    -- Update NIP-11 info from current relay metadata
    UPDATE relay_stats rs SET
        nip11_name     = rmc.data -> 'data' ->> 'name',
        nip11_software = rmc.data -> 'data' ->> 'software',
        nip11_version  = rmc.data -> 'data' ->> 'version'
    FROM relay_metadata_current AS rmc
    WHERE rmc.metadata_type = 'nip11_info'
      AND rs.relay_url = rmc.relay_url;
END;
$$;

COMMENT ON FUNCTION relay_stats_metadata_refresh() IS
'Update relay_stats RTT, NIP-11, network, and discovered_at from metadata tables. Seeds new relays.';


-- **************************************************************************
-- BOUNDED DERIVED TABLE REFRESH (relay metadata analytics)
-- **************************************************************************


/*
 * relay_software_counts_refresh(p_after, p_until) -> INTEGER
 *
 * Recomputes software distribution from relay_metadata_current only when the
 * relay metadata watermark advances.
 */
CREATE OR REPLACE FUNCTION relay_software_counts_refresh(
    p_after BIGINT,
    p_until BIGINT
) RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_rows INTEGER;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM relay_metadata_current
        WHERE metadata_type = 'nip11_info'
          AND generated_at > p_after
          AND generated_at <= p_until
    ) THEN
        RETURN 0;
    END IF;

    DELETE FROM relay_software_counts;

    INSERT INTO relay_software_counts (software, version, relay_count)
    SELECT
        data -> 'data' ->> 'software' AS software,
        COALESCE(data -> 'data' ->> 'version', 'unknown') AS version,
        COUNT(*) AS relay_count
    FROM relay_metadata_current
    WHERE metadata_type = 'nip11_info'
      AND data -> 'data' ->> 'software' IS NOT NULL
    GROUP BY data -> 'data' ->> 'software', COALESCE(data -> 'data' ->> 'version', 'unknown');

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION relay_software_counts_refresh(BIGINT, BIGINT) IS
'Refresh relay_software_counts from relay_metadata_current when current NIP-11 metadata changes.';


/*
 * supported_nip_counts_refresh(p_after, p_until) -> INTEGER
 *
 * Recomputes supported NIP distribution from relay_metadata_current only when
 * the relay metadata watermark advances.
 */
CREATE OR REPLACE FUNCTION supported_nip_counts_refresh(
    p_after BIGINT,
    p_until BIGINT
) RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_rows INTEGER;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM relay_metadata_current
        WHERE metadata_type = 'nip11_info'
          AND generated_at > p_after
          AND generated_at <= p_until
    ) THEN
        RETURN 0;
    END IF;

    DELETE FROM supported_nip_counts;

    INSERT INTO supported_nip_counts (nip, relay_count)
    SELECT
        nip_text::INTEGER AS nip,
        COUNT(*) AS relay_count
    FROM relay_metadata_current
    CROSS JOIN LATERAL jsonb_array_elements_text(data -> 'data' -> 'supported_nips') AS nip_text
    WHERE metadata_type = 'nip11_info'
      AND data -> 'data' ? 'supported_nips'
      AND jsonb_typeof(data -> 'data' -> 'supported_nips') = 'array'
      AND nip_text ~ '^\d+$'
    GROUP BY nip_text::INTEGER;

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION supported_nip_counts_refresh(BIGINT, BIGINT) IS
'Refresh supported_nip_counts from relay_metadata_current when current NIP-11 metadata changes.';


/*
 * daily_counts_refresh(p_after, p_until) -> INTEGER
 *
 * Recomputes only the UTC days impacted by truly new events in the delta
 * window. This keeps the table exact for unique_pubkeys/unique_kinds while
 * avoiding a full-table rebuild.
 */
CREATE OR REPLACE FUNCTION daily_counts_refresh(
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
            e.kind,
            e.created_at
        FROM event_relay AS er
        INNER JOIN event AS e ON er.event_id = e.id
        WHERE er.seen_at > p_after
          AND er.seen_at <= p_until
          AND NOT EXISTS (
              SELECT 1
              FROM event_relay AS older
              WHERE older.event_id = er.event_id
                AND older.seen_at <= p_after
          )
    ),
    impacted_days AS (
        SELECT DISTINCT
            '1970-01-01'::DATE + (created_at / 86400)::INTEGER AS day
        FROM new_events
    ),
    recomputed AS (
        SELECT
            '1970-01-01'::DATE + (e.created_at / 86400)::INTEGER AS day,
            COUNT(*) AS event_count,
            COUNT(DISTINCT e.pubkey) AS unique_pubkeys,
            COUNT(DISTINCT e.kind) AS unique_kinds
        FROM event AS e
        INNER JOIN impacted_days AS d
            ON d.day = '1970-01-01'::DATE + (e.created_at / 86400)::INTEGER
        GROUP BY '1970-01-01'::DATE + (e.created_at / 86400)::INTEGER
    )
    INSERT INTO daily_counts (day, event_count, unique_pubkeys, unique_kinds)
    SELECT
        day,
        event_count,
        unique_pubkeys,
        unique_kinds
    FROM recomputed
    ON CONFLICT (day) DO UPDATE SET
        event_count    = EXCLUDED.event_count,
        unique_pubkeys = EXCLUDED.unique_pubkeys,
        unique_kinds   = EXCLUDED.unique_kinds;

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION daily_counts_refresh(BIGINT, BIGINT) IS
'Incremental refresh of daily_counts by recomputing only UTC days touched by truly new events.';


-- **************************************************************************
-- NIP-85 SUMMARY TABLE REFRESH (incremental)
-- **************************************************************************
-- Both functions use the same (p_after, p_until) seen_at range pattern.
-- They extract engagement data from event tags (tagvalues for single-letter
-- tags, JSONB tags for multi-letter like "amount").
-- **************************************************************************


/*
 * nip85_pubkey_stats_refresh(p_after, p_until) -> INTEGER
 *
 * Processes truly new events in the seen_at range to update per-pubkey
 * NIP-85 social metrics. Extracts engagement from tag relationships:
 * - kind=1: post_count (author), reply_count (if has 'e' tag)
 * - kind=7: reaction_count_sent (author), reaction_count_recd (tag p target)
 * - kind=6: repost_count_recd (original event author via lookup)
 * - kind=1984: report_count_sent (author), report_count_recd (tag p target)
 * - kind=9735: zap counts/amounts (bolt11-verified when tags exist; count-only
 *   fallback from tagvalues when full tags are not stored)
 * - tag 't': topic_counts accumulation
 * - created_at hour: activity_hours heatmap
 */
CREATE OR REPLACE FUNCTION nip85_pubkey_stats_refresh(
    p_after BIGINT,
    p_until BIGINT
) RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_rows INTEGER := 0;
    v_partial INTEGER;
BEGIN
    -- Materialize truly new events into a temp table (single scan)
    CREATE TEMP TABLE _nip85_new_events ON COMMIT DROP AS
    SELECT DISTINCT e.id, e.pubkey, e.kind, e.created_at, e.tagvalues, e.tags
    FROM event_relay AS er
    INNER JOIN event AS e ON er.event_id = e.id
    WHERE er.seen_at > p_after AND er.seen_at <= p_until
      AND NOT EXISTS (
          SELECT 1 FROM event_relay AS older
          WHERE older.event_id = er.event_id
            AND older.seen_at <= p_after
      );
    CREATE INDEX idx__nip85_new_events_kind ON _nip85_new_events (kind);

    -- 1. Post count + reply count + first_created_at + activity_hours
    WITH post_delta AS (
        SELECT
            ENCODE(pubkey, 'hex') AS pubkey,
            COUNT(*) AS post_cnt,
            COUNT(*) FILTER (WHERE EXISTS (
                SELECT 1 FROM unnest(tagvalues) AS tv WHERE tv LIKE 'e:%'
            )) AS reply_cnt,
            MIN(created_at) AS first_at
        FROM _nip85_new_events WHERE kind = 1
        GROUP BY pubkey
    )
    INSERT INTO nip85_pubkey_stats (pubkey, post_count, reply_count, first_created_at)
    SELECT pubkey, post_cnt, reply_cnt, first_at FROM post_delta
    ON CONFLICT (pubkey) DO UPDATE SET
        post_count = nip85_pubkey_stats.post_count + EXCLUDED.post_count,
        reply_count = nip85_pubkey_stats.reply_count + EXCLUDED.reply_count,
        first_created_at = CASE
            WHEN nip85_pubkey_stats.first_created_at IS NULL THEN EXCLUDED.first_created_at
            WHEN EXCLUDED.first_created_at IS NULL THEN nip85_pubkey_stats.first_created_at
            ELSE LEAST(nip85_pubkey_stats.first_created_at, EXCLUDED.first_created_at)
        END;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 2. Activity hours heatmap (all event kinds by author)
    WITH hourly AS (
        SELECT
            ENCODE(pubkey, 'hex') AS pubkey,
            ((created_at % 86400) / 3600)::INTEGER AS hour_utc,
            COUNT(*)::INTEGER AS cnt
        FROM _nip85_new_events
        GROUP BY pubkey, ((created_at % 86400) / 3600)::INTEGER
    ),
    pubkeys AS (
        SELECT DISTINCT pubkey FROM hourly
    ),
    delta_arrays AS (
        SELECT
            p.pubkey,
            ARRAY(
                SELECT COALESCE(
                    (SELECT SUM(h.cnt) FROM hourly h WHERE h.pubkey = p.pubkey AND h.hour_utc = gs.hr),
                    0
                )::INTEGER
                FROM generate_series(0, 23) AS gs(hr)
            ) AS hours_delta
        FROM pubkeys p
    )
    INSERT INTO nip85_pubkey_stats (pubkey, activity_hours)
    SELECT pubkey, hours_delta FROM delta_arrays
    ON CONFLICT (pubkey) DO UPDATE SET
        activity_hours = ARRAY(
            SELECT nip85_pubkey_stats.activity_hours[i] + EXCLUDED.activity_hours[i]
            FROM generate_series(1, 24) AS i
        );
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 3. Reactions sent (kind=7, group by author)
    WITH delta AS (
        SELECT ENCODE(pubkey, 'hex') AS pubkey, COUNT(*) AS cnt
        FROM _nip85_new_events WHERE kind = 7
        GROUP BY pubkey
    )
    INSERT INTO nip85_pubkey_stats (pubkey, reaction_count_sent)
    SELECT pubkey, cnt FROM delta
    ON CONFLICT (pubkey) DO UPDATE SET
        reaction_count_sent = nip85_pubkey_stats.reaction_count_sent + EXCLUDED.reaction_count_sent;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 4. Reactions received (kind=7, first p from tags when present, else ordered fallback)
    WITH exact_targets AS (
        SELECT
            ENCODE(ne.id, 'hex') AS source_event_id,
            LOWER(p_tag.target_pubkey) AS target_pubkey
        FROM _nip85_new_events AS ne
        INNER JOIN LATERAL (
            SELECT t.tag ->> 1 AS target_pubkey
            FROM jsonb_array_elements(ne.tags) WITH ORDINALITY AS t(tag, ord)
            WHERE t.tag ->> 0 = 'p'
            ORDER BY ord
            LIMIT 1
        ) AS p_tag ON TRUE
        WHERE ne.kind = 7
          AND ne.tags IS NOT NULL
    ),
    fallback_targets AS (
        SELECT
            ENCODE(ne.id, 'hex') AS source_event_id,
            LOWER(substring(p_tag.tv FROM 3)) AS target_pubkey
        FROM _nip85_new_events AS ne
        INNER JOIN LATERAL (
            SELECT tv
            FROM unnest(ne.tagvalues) WITH ORDINALITY AS t(tv, ord)
            WHERE tv LIKE 'p:%'
            ORDER BY ord
            LIMIT 1
        ) AS p_tag ON TRUE
        WHERE ne.kind = 7
          AND ne.tags IS NULL
    ),
    delta AS (
        SELECT target_pubkey, COUNT(*) AS cnt
        FROM (
            SELECT source_event_id, target_pubkey
            FROM exact_targets
            WHERE target_pubkey ~ '^[0-9a-f]{64}$'
            UNION ALL
            SELECT source_event_id, target_pubkey
            FROM fallback_targets
            WHERE target_pubkey ~ '^[0-9a-f]{64}$'
        ) AS targets
        GROUP BY target_pubkey
    )
    INSERT INTO nip85_pubkey_stats (pubkey, reaction_count_recd)
    SELECT target_pubkey, cnt FROM delta
    ON CONFLICT (pubkey) DO UPDATE SET
        reaction_count_recd = nip85_pubkey_stats.reaction_count_recd + EXCLUDED.reaction_count_recd;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 5. Reports sent (kind=1984, group by author)
    WITH delta AS (
        SELECT ENCODE(pubkey, 'hex') AS pubkey, COUNT(*) AS cnt
        FROM _nip85_new_events WHERE kind = 1984
        GROUP BY pubkey
    )
    INSERT INTO nip85_pubkey_stats (pubkey, report_count_sent)
    SELECT pubkey, cnt FROM delta
    ON CONFLICT (pubkey) DO UPDATE SET
        report_count_sent = nip85_pubkey_stats.report_count_sent + EXCLUDED.report_count_sent;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 6. Reports received (kind=1984, first p from tags when present, else ordered fallback)
    WITH exact_targets AS (
        SELECT
            ENCODE(ne.id, 'hex') AS source_event_id,
            LOWER(p_tag.target_pubkey) AS target_pubkey
        FROM _nip85_new_events AS ne
        INNER JOIN LATERAL (
            SELECT t.tag ->> 1 AS target_pubkey
            FROM jsonb_array_elements(ne.tags) WITH ORDINALITY AS t(tag, ord)
            WHERE t.tag ->> 0 = 'p'
            ORDER BY ord
            LIMIT 1
        ) AS p_tag ON TRUE
        WHERE ne.kind = 1984
          AND ne.tags IS NOT NULL
    ),
    fallback_targets AS (
        SELECT
            ENCODE(ne.id, 'hex') AS source_event_id,
            LOWER(substring(p_tag.tv FROM 3)) AS target_pubkey
        FROM _nip85_new_events AS ne
        INNER JOIN LATERAL (
            SELECT tv
            FROM unnest(ne.tagvalues) WITH ORDINALITY AS t(tv, ord)
            WHERE tv LIKE 'p:%'
            ORDER BY ord
            LIMIT 1
        ) AS p_tag ON TRUE
        WHERE ne.kind = 1984
          AND ne.tags IS NULL
    ),
    delta AS (
        SELECT target_pubkey, COUNT(*) AS cnt
        FROM (
            SELECT source_event_id, target_pubkey
            FROM exact_targets
            WHERE target_pubkey ~ '^[0-9a-f]{64}$'
            UNION ALL
            SELECT source_event_id, target_pubkey
            FROM fallback_targets
            WHERE target_pubkey ~ '^[0-9a-f]{64}$'
        ) AS targets
        GROUP BY target_pubkey
    )
    INSERT INTO nip85_pubkey_stats (pubkey, report_count_recd)
    SELECT target_pubkey, cnt FROM delta
    ON CONFLICT (pubkey) DO UPDATE SET
        report_count_recd = nip85_pubkey_stats.report_count_recd + EXCLUDED.report_count_recd;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 7a. Reposts sent (kind=6, group by author)
    WITH delta AS (
        SELECT ENCODE(pubkey, 'hex') AS pubkey, COUNT(*) AS cnt
        FROM _nip85_new_events WHERE kind = 6
        GROUP BY pubkey
    )
    INSERT INTO nip85_pubkey_stats (pubkey, repost_count_sent)
    SELECT pubkey, cnt FROM delta
    ON CONFLICT (pubkey) DO UPDATE SET
        repost_count_sent = nip85_pubkey_stats.repost_count_sent + EXCLUDED.repost_count_sent;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 7b. Reposts received (kind=6, first e from tags when present, else ordered fallback)
    WITH exact_targets AS (
        SELECT
            ENCODE(ne.id, 'hex') AS source_event_id,
            LOWER(e_tag.target_event_hex) AS target_event_hex
        FROM _nip85_new_events AS ne
        INNER JOIN LATERAL (
            SELECT t.tag ->> 1 AS target_event_hex
            FROM jsonb_array_elements(ne.tags) WITH ORDINALITY AS t(tag, ord)
            WHERE t.tag ->> 0 = 'e'
            ORDER BY ord
            LIMIT 1
        ) AS e_tag ON TRUE
        WHERE ne.kind = 6
          AND ne.tags IS NOT NULL
    ),
    fallback_targets AS (
        SELECT
            ENCODE(ne.id, 'hex') AS source_event_id,
            LOWER(substring(e_tag.tv FROM 3)) AS target_event_hex
        FROM _nip85_new_events AS ne
        INNER JOIN LATERAL (
            SELECT tv
            FROM unnest(ne.tagvalues) WITH ORDINALITY AS t(tv, ord)
            WHERE tv LIKE 'e:%'
            ORDER BY ord
            LIMIT 1
        ) AS e_tag ON TRUE
        WHERE ne.kind = 6
          AND ne.tags IS NULL
    ),
    delta AS (
        SELECT ENCODE(e.pubkey, 'hex') AS target_pubkey, COUNT(*) AS cnt
        FROM (
            SELECT source_event_id, target_event_hex
            FROM exact_targets
            WHERE target_event_hex ~ '^[0-9a-f]{64}$'
            UNION ALL
            SELECT source_event_id, target_event_hex
            FROM fallback_targets
            WHERE target_event_hex ~ '^[0-9a-f]{64}$'
        ) AS rt
        INNER JOIN event AS e ON e.id = DECODE(rt.target_event_hex, 'hex')
        GROUP BY e.pubkey
    )
    INSERT INTO nip85_pubkey_stats (pubkey, repost_count_recd)
    SELECT target_pubkey, cnt FROM delta
    ON CONFLICT (pubkey) DO UPDATE SET
        repost_count_recd = nip85_pubkey_stats.repost_count_recd + EXCLUDED.repost_count_recd;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 8a. Zaps received (kind=9735, tags-required, bolt11-verified amount)
    WITH zap_data AS (
        SELECT
            LOWER(p_tag.target_pubkey) AS recipient_pubkey,
            amount_data.claimed_amount,
            bolt11_data.bolt11_amount
        FROM _nip85_new_events AS ne
        INNER JOIN LATERAL (
            SELECT t.tag ->> 1 AS target_pubkey
            FROM jsonb_array_elements(ne.tags) WITH ORDINALITY AS t(tag, ord)
            WHERE t.tag ->> 0 = 'p'
            ORDER BY ord
            LIMIT 1
        ) AS p_tag ON TRUE
        LEFT JOIN LATERAL (
            SELECT CASE
                WHEN (t.tag ->> 1) ~ '^[0-9]{1,19}$'
                 AND (length(t.tag ->> 1) < 19 OR (t.tag ->> 1) <= '9223372036854775807')
                    THEN (t.tag ->> 1)::BIGINT
                ELSE NULL
            END AS claimed_amount
            FROM jsonb_array_elements(ne.tags) AS t(tag)
            WHERE t.tag ->> 0 = 'amount'
            LIMIT 1
        ) AS amount_data ON TRUE
        LEFT JOIN LATERAL (
            SELECT bolt11_amount_msats(t.tag ->> 1) AS bolt11_amount
            FROM jsonb_array_elements(ne.tags) AS t(tag)
            WHERE t.tag ->> 0 = 'bolt11'
              AND length(t.tag ->> 1) > 0
            LIMIT 1
        ) AS bolt11_data ON TRUE
        WHERE ne.kind = 9735
          AND ne.tags IS NOT NULL
    ),
    recd_delta AS (
        SELECT recipient_pubkey AS pubkey, COUNT(*) AS cnt, COALESCE(SUM(claimed_amount), 0) AS amt
        FROM zap_data
        WHERE recipient_pubkey ~ '^[0-9a-f]{64}$'
          AND bolt11_amount IS NOT NULL
          AND claimed_amount = bolt11_amount
        GROUP BY recipient_pubkey
    )
    INSERT INTO nip85_pubkey_stats (pubkey, zap_count_recd, zap_amount_recd)
    SELECT pubkey, cnt, amt FROM recd_delta
    ON CONFLICT (pubkey) DO UPDATE SET
        zap_count_recd  = nip85_pubkey_stats.zap_count_recd + EXCLUDED.zap_count_recd,
        zap_amount_recd = nip85_pubkey_stats.zap_amount_recd + EXCLUDED.zap_amount_recd;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 8b. Zaps sent (kind=9735, tags-required, bolt11-verified amount)
    WITH zap_data AS (
        SELECT
            ENCODE(ne.pubkey, 'hex') AS sender_pubkey,
            amount_data.claimed_amount,
            bolt11_data.bolt11_amount
        FROM _nip85_new_events AS ne
        LEFT JOIN LATERAL (
            SELECT CASE
                WHEN (t.tag ->> 1) ~ '^[0-9]{1,19}$'
                 AND (length(t.tag ->> 1) < 19 OR (t.tag ->> 1) <= '9223372036854775807')
                    THEN (t.tag ->> 1)::BIGINT
                ELSE NULL
            END AS claimed_amount
            FROM jsonb_array_elements(ne.tags) AS t(tag)
            WHERE t.tag ->> 0 = 'amount'
            LIMIT 1
        ) AS amount_data ON TRUE
        LEFT JOIN LATERAL (
            SELECT bolt11_amount_msats(t.tag ->> 1) AS bolt11_amount
            FROM jsonb_array_elements(ne.tags) AS t(tag)
            WHERE t.tag ->> 0 = 'bolt11'
              AND length(t.tag ->> 1) > 0
            LIMIT 1
        ) AS bolt11_data ON TRUE
        WHERE ne.kind = 9735
          AND ne.tags IS NOT NULL
    ),
    sent_delta AS (
        SELECT sender_pubkey AS pubkey, COUNT(*) AS cnt, COALESCE(SUM(claimed_amount), 0) AS amt
        FROM zap_data
        WHERE bolt11_amount IS NOT NULL AND claimed_amount = bolt11_amount
        GROUP BY sender_pubkey
    )
    INSERT INTO nip85_pubkey_stats (pubkey, zap_count_sent, zap_amount_sent)
    SELECT pubkey, cnt, amt FROM sent_delta
    ON CONFLICT (pubkey) DO UPDATE SET
        zap_count_sent  = nip85_pubkey_stats.zap_count_sent + EXCLUDED.zap_count_sent,
        zap_amount_sent = nip85_pubkey_stats.zap_amount_sent + EXCLUDED.zap_amount_sent;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 8c. Zaps received fallback (kind=9735, tagvalues-only, count-only)
    WITH fallback_data AS (
        SELECT
            LOWER(substring(p_tag.tv FROM 3)) AS recipient_pubkey
        FROM _nip85_new_events AS ne
        INNER JOIN LATERAL (
            SELECT tv
            FROM unnest(ne.tagvalues) WITH ORDINALITY AS t(tv, ord)
            WHERE tv LIKE 'p:%'
            ORDER BY ord
            LIMIT 1
        ) AS p_tag ON TRUE
        WHERE ne.kind = 9735
          AND ne.tags IS NULL
    ),
    recd_delta AS (
        SELECT recipient_pubkey AS pubkey, COUNT(*) AS cnt
        FROM fallback_data
        WHERE recipient_pubkey ~ '^[0-9a-f]{64}$'
        GROUP BY recipient_pubkey
    )
    INSERT INTO nip85_pubkey_stats (pubkey, zap_count_recd)
    SELECT pubkey, cnt FROM recd_delta
    ON CONFLICT (pubkey) DO UPDATE SET
        zap_count_recd = nip85_pubkey_stats.zap_count_recd + EXCLUDED.zap_count_recd;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 8d. Zaps sent fallback (kind=9735, tagvalues-only, count-only)
    WITH fallback_data AS (
        SELECT
            ENCODE(ne.pubkey, 'hex') AS sender_pubkey
        FROM _nip85_new_events AS ne
        WHERE ne.kind = 9735
          AND ne.tags IS NULL
          AND EXISTS (
              SELECT 1
              FROM unnest(ne.tagvalues) AS tv
              WHERE tv LIKE 'p:%'
          )
    ),
    sent_delta AS (
        SELECT sender_pubkey AS pubkey, COUNT(*) AS cnt
        FROM fallback_data
        GROUP BY sender_pubkey
    )
    INSERT INTO nip85_pubkey_stats (pubkey, zap_count_sent)
    SELECT pubkey, cnt FROM sent_delta
    ON CONFLICT (pubkey) DO UPDATE SET
        zap_count_sent = nip85_pubkey_stats.zap_count_sent + EXCLUDED.zap_count_sent;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 9. Topic counts (tag 't' from all events by author)
    WITH topic_delta AS (
        SELECT
            ENCODE(ne.pubkey, 'hex') AS pubkey,
            substring(tv FROM 3) AS topic,
            COUNT(*) AS cnt
        FROM _nip85_new_events ne, unnest(ne.tagvalues) AS tv
        WHERE tv LIKE 't:%'
        GROUP BY ne.pubkey, substring(tv FROM 3)
    ),
    topic_agg AS (
        SELECT pubkey, jsonb_object_agg(topic, cnt) AS new_topics
        FROM topic_delta GROUP BY pubkey
    )
    INSERT INTO nip85_pubkey_stats (pubkey, topic_counts)
    SELECT pubkey, new_topics FROM topic_agg
    ON CONFLICT (pubkey) DO UPDATE SET
        topic_counts = (
            SELECT COALESCE(jsonb_object_agg(key, to_jsonb(val)), '{}'::JSONB)
            FROM (
                SELECT key, SUM(val) AS val
                FROM (
                    SELECT key, CASE
                        WHEN val ~ '^[0-9]{1,19}$'
                         AND (length(val) < 19 OR val <= '9223372036854775807')
                            THEN val::BIGINT
                        ELSE 0
                    END AS val
                    FROM jsonb_each_text(nip85_pubkey_stats.topic_counts) AS t(key, val)
                    UNION ALL
                    SELECT key, CASE
                        WHEN val ~ '^[0-9]{1,19}$'
                         AND (length(val) < 19 OR val <= '9223372036854775807')
                            THEN val::BIGINT
                        ELSE 0
                    END AS val
                    FROM jsonb_each_text(EXCLUDED.topic_counts) AS t(key, val)
                ) AS combined
                GROUP BY key
            ) AS merged
        );

    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    DROP TABLE IF EXISTS _nip85_new_events;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION nip85_pubkey_stats_refresh(BIGINT, BIGINT) IS
'Incremental refresh of NIP-85 per-pubkey social metrics. Uses exact tags when available and ordered tagvalues fallback when full tags are not stored.';


/*
 * nip85_event_stats_refresh(p_after, p_until) -> INTEGER
 *
 * Processes truly new events to update per-event engagement metrics.
 * Extracts engagement from tag relationships:
 * - kind=1 with tag e: comment_count on target event
 * - any kind with tag q: quote_count on target event
 * - kind=6 with tag e: repost_count on target event
 * - kind=7 with tag e: reaction_count on target event
 * - kind=9735 with tag e: zap_count/zap_amount on target event (bolt11-verified
 *   when tags exist; count-only fallback from tagvalues when full tags are not stored)
 */
CREATE OR REPLACE FUNCTION nip85_event_stats_refresh(
    p_after BIGINT,
    p_until BIGINT
) RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_rows INTEGER := 0;
    v_partial INTEGER;
BEGIN
    CREATE TEMP TABLE _nip85_new_events_eng ON COMMIT DROP AS
    SELECT DISTINCT e.id, e.pubkey, e.kind, e.tagvalues, e.tags
    FROM event_relay AS er
    INNER JOIN event AS e ON er.event_id = e.id
    WHERE er.seen_at > p_after AND er.seen_at <= p_until
      AND NOT EXISTS (
          SELECT 1 FROM event_relay AS older
          WHERE older.event_id = er.event_id
            AND older.seen_at <= p_after
      );
    CREATE INDEX idx__nip85_new_events_eng_kind ON _nip85_new_events_eng (kind);

    -- 1. Comments (reply marker if tags exist, else last e fallback via tagvalues)
    WITH exact_targets AS (
        SELECT
            ENCODE(ne.id, 'hex') AS source_event_id,
            LOWER(COALESCE(reply_tag.target_event, last_e_tag.target_event)) AS target_event
        FROM _nip85_new_events_eng AS ne
        LEFT JOIN LATERAL (
            SELECT t.tag ->> 1 AS target_event
            FROM jsonb_array_elements(ne.tags) WITH ORDINALITY AS t(tag, ord)
            WHERE t.tag ->> 0 = 'e'
              AND COALESCE(t.tag ->> 3, '') = 'reply'
            ORDER BY ord
            LIMIT 1
        ) AS reply_tag ON TRUE
        LEFT JOIN LATERAL (
            SELECT t.tag ->> 1 AS target_event
            FROM jsonb_array_elements(ne.tags) WITH ORDINALITY AS t(tag, ord)
            WHERE t.tag ->> 0 = 'e'
            ORDER BY ord DESC
            LIMIT 1
        ) AS last_e_tag ON TRUE
        WHERE ne.kind = 1
          AND ne.tags IS NOT NULL
          AND COALESCE(reply_tag.target_event, last_e_tag.target_event) IS NOT NULL
    ),
    fallback_targets AS (
        SELECT
            ENCODE(ne.id, 'hex') AS source_event_id,
            LOWER(substring(e_tag.tv FROM 3)) AS target_event
        FROM _nip85_new_events_eng AS ne
        INNER JOIN LATERAL (
            SELECT tv
            FROM unnest(ne.tagvalues) WITH ORDINALITY AS t(tv, ord)
            WHERE tv LIKE 'e:%'
            ORDER BY ord DESC
            LIMIT 1
        ) AS e_tag ON TRUE
        WHERE ne.kind = 1
          AND ne.tags IS NULL
    ),
    delta AS (
        SELECT target_event, COUNT(*) AS cnt
        FROM (
            SELECT source_event_id, target_event
            FROM exact_targets
            WHERE target_event ~ '^[0-9a-f]{64}$'
            UNION ALL
            SELECT source_event_id, target_event
            FROM fallback_targets
            WHERE target_event ~ '^[0-9a-f]{64}$'
        ) AS targets
        GROUP BY target_event
    )
    INSERT INTO nip85_event_stats (event_id, author_pubkey, comment_count)
    SELECT d.target_event, COALESCE(ENCODE(e.pubkey, 'hex'), ''), d.cnt
    FROM delta AS d
    LEFT JOIN event AS e ON e.id = DECODE(d.target_event, 'hex')
    ON CONFLICT (event_id) DO UPDATE SET
        comment_count = nip85_event_stats.comment_count + EXCLUDED.comment_count;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 2. Quotes (DISTINCT fallback via tagvalues)
    WITH targets AS (
        SELECT DISTINCT
            ENCODE(ne.id, 'hex') AS source_event_id,
            LOWER(substring(tv FROM 3)) AS target_event
        FROM _nip85_new_events_eng AS ne,
             unnest(ne.tagvalues) AS tv
        WHERE tv LIKE 'q:%'
          AND LOWER(substring(tv FROM 3)) ~ '^[0-9a-f]{64}$'
    ),
    delta AS (
        SELECT target_event, COUNT(*) AS cnt
        FROM targets
        GROUP BY target_event
    )
    INSERT INTO nip85_event_stats (event_id, author_pubkey, quote_count)
    SELECT d.target_event, COALESCE(ENCODE(e.pubkey, 'hex'), ''), d.cnt
    FROM delta AS d
    LEFT JOIN event AS e ON e.id = DECODE(d.target_event, 'hex')
    ON CONFLICT (event_id) DO UPDATE SET
        quote_count = nip85_event_stats.quote_count + EXCLUDED.quote_count;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 3. Reposts (first e from tags when present, else ordered fallback)
    WITH exact_targets AS (
        SELECT
            ENCODE(ne.id, 'hex') AS source_event_id,
            LOWER(e_tag.target_event) AS target_event
        FROM _nip85_new_events_eng AS ne
        INNER JOIN LATERAL (
            SELECT t.tag ->> 1 AS target_event
            FROM jsonb_array_elements(ne.tags) WITH ORDINALITY AS t(tag, ord)
            WHERE t.tag ->> 0 = 'e'
            ORDER BY ord
            LIMIT 1
        ) AS e_tag ON TRUE
        WHERE ne.kind = 6
          AND ne.tags IS NOT NULL
    ),
    fallback_targets AS (
        SELECT
            ENCODE(ne.id, 'hex') AS source_event_id,
            LOWER(substring(e_tag.tv FROM 3)) AS target_event
        FROM _nip85_new_events_eng AS ne
        INNER JOIN LATERAL (
            SELECT tv
            FROM unnest(ne.tagvalues) WITH ORDINALITY AS t(tv, ord)
            WHERE tv LIKE 'e:%'
            ORDER BY ord
            LIMIT 1
        ) AS e_tag ON TRUE
        WHERE ne.kind = 6
          AND ne.tags IS NULL
    ),
    delta AS (
        SELECT target_event, COUNT(*) AS cnt
        FROM (
            SELECT source_event_id, target_event
            FROM exact_targets
            WHERE target_event ~ '^[0-9a-f]{64}$'
            UNION ALL
            SELECT source_event_id, target_event
            FROM fallback_targets
            WHERE target_event ~ '^[0-9a-f]{64}$'
        ) AS targets
        GROUP BY target_event
    )
    INSERT INTO nip85_event_stats (event_id, author_pubkey, repost_count)
    SELECT d.target_event, COALESCE(ENCODE(e.pubkey, 'hex'), ''), d.cnt
    FROM delta AS d
    LEFT JOIN event AS e ON e.id = DECODE(d.target_event, 'hex')
    ON CONFLICT (event_id) DO UPDATE SET
        repost_count = nip85_event_stats.repost_count + EXCLUDED.repost_count;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 4. Reactions (last e from tags when present, else ordered fallback)
    WITH exact_targets AS (
        SELECT
            ENCODE(ne.id, 'hex') AS source_event_id,
            LOWER(e_tag.target_event) AS target_event
        FROM _nip85_new_events_eng AS ne
        INNER JOIN LATERAL (
            SELECT t.tag ->> 1 AS target_event
            FROM jsonb_array_elements(ne.tags) WITH ORDINALITY AS t(tag, ord)
            WHERE t.tag ->> 0 = 'e'
            ORDER BY ord DESC
            LIMIT 1
        ) AS e_tag ON TRUE
        WHERE ne.kind = 7
          AND ne.tags IS NOT NULL
    ),
    fallback_targets AS (
        SELECT
            ENCODE(ne.id, 'hex') AS source_event_id,
            LOWER(substring(e_tag.tv FROM 3)) AS target_event
        FROM _nip85_new_events_eng AS ne
        INNER JOIN LATERAL (
            SELECT tv
            FROM unnest(ne.tagvalues) WITH ORDINALITY AS t(tv, ord)
            WHERE tv LIKE 'e:%'
            ORDER BY ord DESC
            LIMIT 1
        ) AS e_tag ON TRUE
        WHERE ne.kind = 7
          AND ne.tags IS NULL
    ),
    delta AS (
        SELECT target_event, COUNT(*) AS cnt
        FROM (
            SELECT source_event_id, target_event
            FROM exact_targets
            WHERE target_event ~ '^[0-9a-f]{64}$'
            UNION ALL
            SELECT source_event_id, target_event
            FROM fallback_targets
            WHERE target_event ~ '^[0-9a-f]{64}$'
        ) AS targets
        GROUP BY target_event
    )
    INSERT INTO nip85_event_stats (event_id, author_pubkey, reaction_count)
    SELECT d.target_event, COALESCE(ENCODE(e.pubkey, 'hex'), ''), d.cnt
    FROM delta AS d
    LEFT JOIN event AS e ON e.id = DECODE(d.target_event, 'hex')
    ON CONFLICT (event_id) DO UPDATE SET
        reaction_count = nip85_event_stats.reaction_count + EXCLUDED.reaction_count;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 5. Zaps on events (kind=9735, tags-required, last e target, bolt11-verified)
    WITH zap_data AS (
        SELECT
            LOWER(e_tag.target_event) AS target_event,
            amount_data.claimed_amount,
            bolt11_data.bolt11_amount
        FROM _nip85_new_events_eng AS ne
        INNER JOIN LATERAL (
            SELECT t.tag ->> 1 AS target_event
            FROM jsonb_array_elements(ne.tags) WITH ORDINALITY AS t(tag, ord)
            WHERE t.tag ->> 0 = 'e'
            ORDER BY ord DESC
            LIMIT 1
        ) AS e_tag ON TRUE
        LEFT JOIN LATERAL (
            SELECT CASE
                WHEN (t.tag ->> 1) ~ '^[0-9]{1,19}$'
                 AND (length(t.tag ->> 1) < 19 OR (t.tag ->> 1) <= '9223372036854775807')
                    THEN (t.tag ->> 1)::BIGINT
                ELSE NULL
            END AS claimed_amount
            FROM jsonb_array_elements(ne.tags) AS t(tag)
            WHERE t.tag ->> 0 = 'amount'
            LIMIT 1
        ) AS amount_data ON TRUE
        LEFT JOIN LATERAL (
            SELECT bolt11_amount_msats(t.tag ->> 1) AS bolt11_amount
            FROM jsonb_array_elements(ne.tags) AS t(tag)
            WHERE t.tag ->> 0 = 'bolt11'
              AND length(t.tag ->> 1) > 0
            LIMIT 1
        ) AS bolt11_data ON TRUE
        WHERE ne.kind = 9735
          AND ne.tags IS NOT NULL
    ),
    delta AS (
        SELECT target_event, COUNT(*) AS cnt, COALESCE(SUM(claimed_amount), 0) AS amt
        FROM zap_data
        WHERE target_event ~ '^[0-9a-f]{64}$'
          AND bolt11_amount IS NOT NULL
          AND claimed_amount = bolt11_amount
        GROUP BY target_event
    )
    INSERT INTO nip85_event_stats (event_id, author_pubkey, zap_count, zap_amount)
    SELECT d.target_event, COALESCE(ENCODE(e.pubkey, 'hex'), ''), d.cnt, d.amt
    FROM delta AS d
    LEFT JOIN event AS e ON e.id = DECODE(d.target_event, 'hex')
    ON CONFLICT (event_id) DO UPDATE SET
        zap_count  = nip85_event_stats.zap_count + EXCLUDED.zap_count,
        zap_amount = nip85_event_stats.zap_amount + EXCLUDED.zap_amount;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 6. Zaps on events fallback (kind=9735, tagvalues-only, last e target, count-only)
    WITH fallback_data AS (
        SELECT
            LOWER(substring(e_tag.tv FROM 3)) AS target_event
        FROM _nip85_new_events_eng AS ne
        INNER JOIN LATERAL (
            SELECT tv
            FROM unnest(ne.tagvalues) WITH ORDINALITY AS t(tv, ord)
            WHERE tv LIKE 'e:%'
            ORDER BY ord DESC
            LIMIT 1
        ) AS e_tag ON TRUE
        WHERE ne.kind = 9735
          AND ne.tags IS NULL
    ),
    delta AS (
        SELECT target_event, COUNT(*) AS cnt
        FROM fallback_data
        WHERE target_event ~ '^[0-9a-f]{64}$'
        GROUP BY target_event
    )
    INSERT INTO nip85_event_stats (event_id, author_pubkey, zap_count)
    SELECT d.target_event, COALESCE(ENCODE(e.pubkey, 'hex'), ''), d.cnt
    FROM delta AS d
    LEFT JOIN event AS e ON e.id = DECODE(d.target_event, 'hex')
    ON CONFLICT (event_id) DO UPDATE SET
        zap_count = nip85_event_stats.zap_count + EXCLUDED.zap_count;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    DROP TABLE IF EXISTS _nip85_new_events_eng;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION nip85_event_stats_refresh(BIGINT, BIGINT) IS
'Incremental refresh of NIP-85 per-event engagement metrics. Uses exact tags when available and ordered tagvalues fallback when full tags are not stored.';


/*
 * nip85_addressable_stats_refresh(p_after, p_until) -> INTEGER
 *
 * Processes truly new events to update per-addressable-event engagement
 * metrics. Targets are canonicalized to ``kind:pubkey:d_tag``.
 *
 * Resolution strategy:
 * - kind=1 comments: prefer reply-marked ``a``/``e`` tags when full tags are
 *   available, else fall back to ordered ``a`` then ordered ``e`` tagvalues
 * - kind=6 reposts: first ordered ``a`` tagvalue, else first ordered ``e``
 *   mapped through the target event's address
 * - kind=7 reactions: last ordered ``a`` tagvalue, else last ordered ``e``
 *   mapped through the target event's address
 * - tag ``q`` quotes: each distinct ``q`` target per source event counts once;
 *   ``q`` may contain a direct address or an event id that maps to one
 * - kind=9735 zaps: last ordered ``a`` tagvalue, else last ordered ``e``
 *   mapped through the target event's address; amounts are bolt11-verified
 *   when full tags are present, and count-only otherwise
 */
CREATE OR REPLACE FUNCTION nip85_addressable_stats_refresh(
    p_after BIGINT,
    p_until BIGINT
) RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_rows INTEGER := 0;
    v_partial INTEGER;
BEGIN
    CREATE TEMP TABLE _nip85_new_events_addr ON COMMIT DROP AS
    SELECT DISTINCT e.id, e.pubkey, e.kind, e.tagvalues, e.tags
    FROM event_relay AS er
    INNER JOIN event AS e ON er.event_id = e.id
    WHERE er.seen_at > p_after AND er.seen_at <= p_until
      AND NOT EXISTS (
          SELECT 1 FROM event_relay AS older
          WHERE older.event_id = er.event_id
            AND older.seen_at <= p_after
      );
    CREATE INDEX idx__nip85_new_events_addr_kind ON _nip85_new_events_addr (kind);

    -- 1. Comments on addressable events
    WITH targets AS (
        SELECT
            ENCODE(ne.id, 'hex') AS source_event_id,
            COALESCE(
                reply_a.target_address,
                reply_e.target_address,
                last_a.target_address,
                last_e.target_address
            ) AS target_address
        FROM _nip85_new_events_addr AS ne
        LEFT JOIN LATERAL (
            SELECT normalize_event_address(t.tag ->> 1) AS target_address
            FROM jsonb_array_elements(ne.tags) WITH ORDINALITY AS t(tag, ord)
            WHERE t.tag ->> 0 = 'a'
              AND COALESCE(t.tag ->> 3, '') = 'reply'
            ORDER BY ord
            LIMIT 1
        ) AS reply_a ON TRUE
        LEFT JOIN LATERAL (
            SELECT event_address(te.kind, te.pubkey, te.tags, te.tagvalues) AS target_address
            FROM LATERAL (
                SELECT LOWER(t.tag ->> 1) AS target_event
                FROM jsonb_array_elements(ne.tags) WITH ORDINALITY AS t(tag, ord)
                WHERE t.tag ->> 0 = 'e'
                  AND COALESCE(t.tag ->> 3, '') = 'reply'
                ORDER BY ord
                LIMIT 1
            ) AS reply_e_tag
            INNER JOIN event AS te
                ON reply_e_tag.target_event ~ '^[0-9a-f]{64}$'
               AND te.id = DECODE(reply_e_tag.target_event, 'hex')
        ) AS reply_e ON TRUE
        LEFT JOIN LATERAL (
            SELECT normalize_event_address(substring(t.tv FROM 3)) AS target_address
            FROM unnest(ne.tagvalues) WITH ORDINALITY AS t(tv, ord)
            WHERE t.tv LIKE 'a:%'
            ORDER BY ord DESC
            LIMIT 1
        ) AS last_a ON TRUE
        LEFT JOIN LATERAL (
            SELECT event_address(te.kind, te.pubkey, te.tags, te.tagvalues) AS target_address
            FROM LATERAL (
                SELECT LOWER(substring(t.tv FROM 3)) AS target_event
                FROM unnest(ne.tagvalues) WITH ORDINALITY AS t(tv, ord)
                WHERE t.tv LIKE 'e:%'
                ORDER BY ord DESC
                LIMIT 1
            ) AS last_e_tag
            INNER JOIN event AS te
                ON last_e_tag.target_event ~ '^[0-9a-f]{64}$'
               AND te.id = DECODE(last_e_tag.target_event, 'hex')
        ) AS last_e ON TRUE
        WHERE ne.kind = 1
    ),
    delta AS (
        SELECT target_address, COUNT(*) AS cnt
        FROM targets
        WHERE target_address IS NOT NULL
        GROUP BY target_address
    )
    INSERT INTO nip85_addressable_stats (event_address, author_pubkey, comment_count)
    SELECT target_address, split_part(target_address, ':', 2), cnt
    FROM delta
    ON CONFLICT (event_address) DO UPDATE SET
        comment_count = nip85_addressable_stats.comment_count + EXCLUDED.comment_count;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 2. Quotes on addressable events (q-tag value may be a direct address or an event id)
    WITH direct_targets AS (
        SELECT DISTINCT
            ENCODE(ne.id, 'hex') AS source_event_id,
            normalize_event_address(substring(tv FROM 3)) AS target_address
        FROM _nip85_new_events_addr AS ne,
             unnest(ne.tagvalues) AS tv
        WHERE tv LIKE 'q:%'
    ),
    event_targets AS (
        SELECT DISTINCT
            ENCODE(ne.id, 'hex') AS source_event_id,
            event_address(te.kind, te.pubkey, te.tags, te.tagvalues) AS target_address
        FROM _nip85_new_events_addr AS ne,
             unnest(ne.tagvalues) AS tv
        INNER JOIN event AS te
            ON tv LIKE 'q:%'
           AND LOWER(substring(tv FROM 3)) ~ '^[0-9a-f]{64}$'
           AND te.id = DECODE(LOWER(substring(tv FROM 3)), 'hex')
    ),
    delta AS (
        SELECT target_address, COUNT(*) AS cnt
        FROM (
            SELECT source_event_id, target_address
            FROM direct_targets
            WHERE target_address IS NOT NULL
            UNION
            SELECT source_event_id, target_address
            FROM event_targets
            WHERE target_address IS NOT NULL
        ) AS targets
        GROUP BY target_address
    )
    INSERT INTO nip85_addressable_stats (event_address, author_pubkey, quote_count)
    SELECT target_address, split_part(target_address, ':', 2), cnt
    FROM delta
    ON CONFLICT (event_address) DO UPDATE SET
        quote_count = nip85_addressable_stats.quote_count + EXCLUDED.quote_count;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 3. Reposts on addressable events
    WITH targets AS (
        SELECT
            ENCODE(ne.id, 'hex') AS source_event_id,
            COALESCE(first_a.target_address, first_e.target_address) AS target_address
        FROM _nip85_new_events_addr AS ne
        LEFT JOIN LATERAL (
            SELECT normalize_event_address(substring(t.tv FROM 3)) AS target_address
            FROM unnest(ne.tagvalues) WITH ORDINALITY AS t(tv, ord)
            WHERE t.tv LIKE 'a:%'
            ORDER BY ord
            LIMIT 1
        ) AS first_a ON TRUE
        LEFT JOIN LATERAL (
            SELECT event_address(te.kind, te.pubkey, te.tags, te.tagvalues) AS target_address
            FROM LATERAL (
                SELECT LOWER(substring(t.tv FROM 3)) AS target_event
                FROM unnest(ne.tagvalues) WITH ORDINALITY AS t(tv, ord)
                WHERE t.tv LIKE 'e:%'
                ORDER BY ord
                LIMIT 1
            ) AS first_e_tag
            INNER JOIN event AS te
                ON first_e_tag.target_event ~ '^[0-9a-f]{64}$'
               AND te.id = DECODE(first_e_tag.target_event, 'hex')
        ) AS first_e ON TRUE
        WHERE ne.kind = 6
    ),
    delta AS (
        SELECT target_address, COUNT(*) AS cnt
        FROM targets
        WHERE target_address IS NOT NULL
        GROUP BY target_address
    )
    INSERT INTO nip85_addressable_stats (event_address, author_pubkey, repost_count)
    SELECT target_address, split_part(target_address, ':', 2), cnt
    FROM delta
    ON CONFLICT (event_address) DO UPDATE SET
        repost_count = nip85_addressable_stats.repost_count + EXCLUDED.repost_count;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 4. Reactions on addressable events
    WITH targets AS (
        SELECT
            ENCODE(ne.id, 'hex') AS source_event_id,
            COALESCE(last_a.target_address, last_e.target_address) AS target_address
        FROM _nip85_new_events_addr AS ne
        LEFT JOIN LATERAL (
            SELECT normalize_event_address(substring(t.tv FROM 3)) AS target_address
            FROM unnest(ne.tagvalues) WITH ORDINALITY AS t(tv, ord)
            WHERE t.tv LIKE 'a:%'
            ORDER BY ord DESC
            LIMIT 1
        ) AS last_a ON TRUE
        LEFT JOIN LATERAL (
            SELECT event_address(te.kind, te.pubkey, te.tags, te.tagvalues) AS target_address
            FROM LATERAL (
                SELECT LOWER(substring(t.tv FROM 3)) AS target_event
                FROM unnest(ne.tagvalues) WITH ORDINALITY AS t(tv, ord)
                WHERE t.tv LIKE 'e:%'
                ORDER BY ord DESC
                LIMIT 1
            ) AS last_e_tag
            INNER JOIN event AS te
                ON last_e_tag.target_event ~ '^[0-9a-f]{64}$'
               AND te.id = DECODE(last_e_tag.target_event, 'hex')
        ) AS last_e ON TRUE
        WHERE ne.kind = 7
    ),
    delta AS (
        SELECT target_address, COUNT(*) AS cnt
        FROM targets
        WHERE target_address IS NOT NULL
        GROUP BY target_address
    )
    INSERT INTO nip85_addressable_stats (event_address, author_pubkey, reaction_count)
    SELECT target_address, split_part(target_address, ':', 2), cnt
    FROM delta
    ON CONFLICT (event_address) DO UPDATE SET
        reaction_count = nip85_addressable_stats.reaction_count + EXCLUDED.reaction_count;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 5. Zaps on addressable events (tags-required, bolt11-verified)
    WITH zap_data AS (
        SELECT
            COALESCE(last_a.target_address, last_e.target_address) AS target_address,
            amount_data.claimed_amount,
            bolt11_data.bolt11_amount
        FROM _nip85_new_events_addr AS ne
        LEFT JOIN LATERAL (
            SELECT normalize_event_address(substring(t.tv FROM 3)) AS target_address
            FROM unnest(ne.tagvalues) WITH ORDINALITY AS t(tv, ord)
            WHERE t.tv LIKE 'a:%'
            ORDER BY ord DESC
            LIMIT 1
        ) AS last_a ON TRUE
        LEFT JOIN LATERAL (
            SELECT event_address(te.kind, te.pubkey, te.tags, te.tagvalues) AS target_address
            FROM LATERAL (
                SELECT LOWER(substring(t.tv FROM 3)) AS target_event
                FROM unnest(ne.tagvalues) WITH ORDINALITY AS t(tv, ord)
                WHERE t.tv LIKE 'e:%'
                ORDER BY ord DESC
                LIMIT 1
            ) AS last_e_tag
            INNER JOIN event AS te
                ON last_e_tag.target_event ~ '^[0-9a-f]{64}$'
               AND te.id = DECODE(last_e_tag.target_event, 'hex')
        ) AS last_e ON TRUE
        LEFT JOIN LATERAL (
            SELECT CASE
                WHEN (t.tag ->> 1) ~ '^[0-9]{1,19}$'
                 AND (length(t.tag ->> 1) < 19 OR (t.tag ->> 1) <= '9223372036854775807')
                    THEN (t.tag ->> 1)::BIGINT
                ELSE NULL
            END AS claimed_amount
            FROM jsonb_array_elements(ne.tags) AS t(tag)
            WHERE t.tag ->> 0 = 'amount'
            LIMIT 1
        ) AS amount_data ON TRUE
        LEFT JOIN LATERAL (
            SELECT bolt11_amount_msats(t.tag ->> 1) AS bolt11_amount
            FROM jsonb_array_elements(ne.tags) AS t(tag)
            WHERE t.tag ->> 0 = 'bolt11'
              AND length(t.tag ->> 1) > 0
            LIMIT 1
        ) AS bolt11_data ON TRUE
        WHERE ne.kind = 9735
          AND ne.tags IS NOT NULL
    ),
    delta AS (
        SELECT target_address, COUNT(*) AS cnt, COALESCE(SUM(claimed_amount), 0) AS amt
        FROM zap_data
        WHERE target_address IS NOT NULL
          AND bolt11_amount IS NOT NULL
          AND claimed_amount = bolt11_amount
        GROUP BY target_address
    )
    INSERT INTO nip85_addressable_stats (event_address, author_pubkey, zap_count, zap_amount)
    SELECT target_address, split_part(target_address, ':', 2), cnt, amt
    FROM delta
    ON CONFLICT (event_address) DO UPDATE SET
        zap_count  = nip85_addressable_stats.zap_count + EXCLUDED.zap_count,
        zap_amount = nip85_addressable_stats.zap_amount + EXCLUDED.zap_amount;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 6. Zaps on addressable events fallback (tagvalues-only, count-only)
    WITH fallback_data AS (
        SELECT
            COALESCE(last_a.target_address, last_e.target_address) AS target_address
        FROM _nip85_new_events_addr AS ne
        LEFT JOIN LATERAL (
            SELECT normalize_event_address(substring(t.tv FROM 3)) AS target_address
            FROM unnest(ne.tagvalues) WITH ORDINALITY AS t(tv, ord)
            WHERE t.tv LIKE 'a:%'
            ORDER BY ord DESC
            LIMIT 1
        ) AS last_a ON TRUE
        LEFT JOIN LATERAL (
            SELECT event_address(te.kind, te.pubkey, te.tags, te.tagvalues) AS target_address
            FROM LATERAL (
                SELECT LOWER(substring(t.tv FROM 3)) AS target_event
                FROM unnest(ne.tagvalues) WITH ORDINALITY AS t(tv, ord)
                WHERE t.tv LIKE 'e:%'
                ORDER BY ord DESC
                LIMIT 1
            ) AS last_e_tag
            INNER JOIN event AS te
                ON last_e_tag.target_event ~ '^[0-9a-f]{64}$'
               AND te.id = DECODE(last_e_tag.target_event, 'hex')
        ) AS last_e ON TRUE
        WHERE ne.kind = 9735
          AND ne.tags IS NULL
    ),
    delta AS (
        SELECT target_address, COUNT(*) AS cnt
        FROM fallback_data
        WHERE target_address IS NOT NULL
        GROUP BY target_address
    )
    INSERT INTO nip85_addressable_stats (event_address, author_pubkey, zap_count)
    SELECT target_address, split_part(target_address, ':', 2), cnt
    FROM delta
    ON CONFLICT (event_address) DO UPDATE SET
        zap_count = nip85_addressable_stats.zap_count + EXCLUDED.zap_count;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    DROP TABLE IF EXISTS _nip85_new_events_addr;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION nip85_addressable_stats_refresh(BIGINT, BIGINT) IS
'Incremental refresh of NIP-85 per-addressable-event engagement metrics. Uses reply-marker precision when full tags exist and otherwise falls back to ordered tagvalues.';


/*
 * nip85_identifier_stats_refresh(p_after, p_until) -> INTEGER
 *
 * Processes truly new events to update per-identifier engagement metrics for
 * NIP-73 ``i`` tags. Counts are maintained for:
 * - kind=1 comments
 * - kind=7 reactions
 *
 * ``k`` tags are collected as a sorted deduplicated set per identifier.
 */
CREATE OR REPLACE FUNCTION nip85_identifier_stats_refresh(
    p_after BIGINT,
    p_until BIGINT
) RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_rows INTEGER := 0;
BEGIN
    WITH new_events AS (
        SELECT DISTINCT e.id, e.kind, e.tagvalues
        FROM event_relay AS er
        INNER JOIN event AS e ON er.event_id = e.id
        WHERE er.seen_at > p_after AND er.seen_at <= p_until
          AND e.kind IN (1, 7)
          AND NOT EXISTS (
              SELECT 1 FROM event_relay AS older
              WHERE older.event_id = er.event_id
                AND older.seen_at <= p_after
          )
    ),
    source_identifiers AS (
        SELECT DISTINCT
            ENCODE(ne.id, 'hex') AS source_event_id,
            ne.kind,
            substring(tv FROM 3) AS identifier
        FROM new_events AS ne,
             unnest(ne.tagvalues) AS tv
        WHERE tv LIKE 'i:%'
    ),
    delta AS (
        SELECT
            identifier,
            COUNT(*) FILTER (WHERE kind = 1) AS comment_cnt,
            COUNT(*) FILTER (WHERE kind = 7) AS reaction_cnt,
            COALESCE(
                ARRAY(
                    SELECT DISTINCT substring(k_tv FROM 3)
                    FROM source_identifiers AS si2
                    INNER JOIN new_events AS ne2
                        ON ENCODE(ne2.id, 'hex') = si2.source_event_id
                    CROSS JOIN LATERAL unnest(ne2.tagvalues) AS k_tv
                    WHERE si2.identifier = si.identifier
                      AND k_tv LIKE 'k:%'
                    ORDER BY substring(k_tv FROM 3)
                ),
                '{}'::TEXT[]
            ) AS k_tags
        FROM source_identifiers AS si
        GROUP BY identifier
    )
    INSERT INTO nip85_identifier_stats (identifier, comment_count, reaction_count, k_tags)
    SELECT identifier, comment_cnt, reaction_cnt, k_tags
    FROM delta
    ON CONFLICT (identifier) DO UPDATE SET
        comment_count = nip85_identifier_stats.comment_count + EXCLUDED.comment_count,
        reaction_count = nip85_identifier_stats.reaction_count + EXCLUDED.reaction_count,
        k_tags = ARRAY(
            SELECT DISTINCT tag
            FROM unnest(nip85_identifier_stats.k_tags || EXCLUDED.k_tags) AS tag
            ORDER BY tag
        );

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION nip85_identifier_stats_refresh(BIGINT, BIGINT) IS
'Incremental refresh of NIP-85 per-identifier engagement metrics derived from NIP-73 i/k tags.';


-- **************************************************************************
-- NIP-85 PERIODIC REFRESH
-- **************************************************************************


/*
 * nip85_follower_count_refresh() -> VOID
 *
 * Recomputes follower_count and following_count for all pubkeys from the
 * canonical contact-list facts tables. Reads from contact_list_edges_current
 * and contact_lists_current, which must already be refreshed.
 */
CREATE OR REPLACE FUNCTION nip85_follower_count_refresh()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    -- Compute follower counts from current deduplicated edges
    WITH follower_counts AS (
        SELECT
            followed_pubkey,
            COUNT(*) AS cnt
        FROM contact_list_edges_current
        GROUP BY followed_pubkey
    )
    UPDATE nip85_pubkey_stats ps SET
        follower_count = fc.cnt
    FROM follower_counts fc
    WHERE ps.pubkey = fc.followed_pubkey;

    -- Zero out pubkeys no longer followed by anyone
    UPDATE nip85_pubkey_stats ps SET follower_count = 0
    WHERE ps.follower_count > 0
      AND NOT EXISTS (
          SELECT 1
          FROM contact_list_edges_current AS cle
          WHERE cle.followed_pubkey = ps.pubkey
      );

    -- Compute following counts from current latest contact lists
    WITH following_counts AS (
        SELECT
            follower_pubkey AS pubkey,
            follow_count AS cnt
        FROM contact_lists_current
    )
    UPDATE nip85_pubkey_stats ps SET
        following_count = fc.cnt
    FROM following_counts fc
    WHERE ps.pubkey = fc.pubkey;

    UPDATE nip85_pubkey_stats ps SET following_count = 0
    WHERE ps.following_count > 0
      AND NOT EXISTS (
          SELECT 1
          FROM contact_lists_current AS cl
          WHERE cl.follower_pubkey = ps.pubkey
      );
END;
$$;

COMMENT ON FUNCTION nip85_follower_count_refresh() IS
'Recompute NIP-85 follower and following counts from canonical contact-list facts tables (contact_lists_current, contact_list_edges_current).';
