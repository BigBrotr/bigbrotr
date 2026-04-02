/*
 * Brotr - 07_functions_refresh.sql
 *
 * Refresh functions for the analytics layer.
 *
 * Materialized views use REFRESH MATERIALIZED VIEW CONCURRENTLY (requires
 * unique indexes from 08_indexes.sql).
 *
 * Summary tables use pure incremental functions that receive a
 * (p_after, p_until) range of event_relay.seen_at timestamps from the
 * caller. The caller (Python refresher service) manages checkpoints and
 * orchestrates the refresh cycle.
 *
 * Dependencies: 06_materialized_views.sql
 */


/*
 * relay_metadata_latest_refresh() -> VOID
 *
 * Refreshes the relay_metadata_latest view concurrently.
 * Schedule: Daily via cron or application scheduler.
 */
CREATE OR REPLACE FUNCTION relay_metadata_latest_refresh()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY relay_metadata_latest;
END;
$$;

COMMENT ON FUNCTION relay_metadata_latest_refresh() IS
'Refresh relay_metadata_latest concurrently. Schedule daily.';


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
    SELECT CASE
        WHEN parts[2] = 'm' THEN parts[1]::BIGINT * 100000000
        WHEN parts[2] = 'u' THEN parts[1]::BIGINT * 100000
        WHEN parts[2] = 'n' THEN parts[1]::BIGINT * 100
        WHEN parts[2] = 'p' THEN parts[1]::BIGINT / 10
        WHEN parts[1] IS NOT NULL AND parts[2] IS NULL
            THEN parts[1]::BIGINT * 100000000000
        ELSE NULL
    END
    FROM (
        SELECT (regexp_match(bolt11, '^lntbs?(\d+)([munp])?1'))[1:2] AS parts
    ) parsed;
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
    )
    INSERT INTO pubkey_stats
        (pubkey, event_count, first_event_at, last_event_at,
         regular_count, replaceable_count, ephemeral_count, addressable_count,
         unique_kinds, unique_relays)
    SELECT
        d.pubkey, d.event_count, d.first_event_at, d.last_event_at,
        d.regular_count, d.replaceable_count, d.ephemeral_count, d.addressable_count,
        COALESCE((SELECT COUNT(*)::INTEGER FROM pubkey_kind_stats WHERE pubkey = d.pubkey), 0),
        COALESCE((SELECT COUNT(*)::INTEGER FROM pubkey_relay_stats WHERE pubkey = d.pubkey), 0)
    FROM delta AS d
    ON CONFLICT (pubkey) DO UPDATE SET
        event_count       = pubkey_stats.event_count + EXCLUDED.event_count,
        first_event_at    = LEAST(pubkey_stats.first_event_at, EXCLUDED.first_event_at),
        last_event_at     = GREATEST(pubkey_stats.last_event_at, EXCLUDED.last_event_at),
        regular_count     = pubkey_stats.regular_count + EXCLUDED.regular_count,
        replaceable_count = pubkey_stats.replaceable_count + EXCLUDED.replaceable_count,
        ephemeral_count   = pubkey_stats.ephemeral_count + EXCLUDED.ephemeral_count,
        addressable_count = pubkey_stats.addressable_count + EXCLUDED.addressable_count,
        unique_kinds  = COALESCE(
            (SELECT COUNT(*)::INTEGER FROM pubkey_kind_stats WHERE pubkey = pubkey_stats.pubkey), 0
        ),
        unique_relays = COALESCE(
            (SELECT COUNT(*)::INTEGER FROM pubkey_relay_stats WHERE pubkey = pubkey_stats.pubkey), 0
        );

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
    )
    INSERT INTO kind_stats
        (kind, event_count, category, first_event_at, last_event_at,
         unique_pubkeys, unique_relays)
    SELECT
        d.kind, d.event_count, d.category, d.first_event_at, d.last_event_at,
        COALESCE((SELECT COUNT(*)::INTEGER FROM pubkey_kind_stats WHERE kind = d.kind), 0),
        COALESCE((SELECT COUNT(*)::INTEGER FROM relay_kind_stats WHERE kind = d.kind), 0)
    FROM delta AS d
    ON CONFLICT (kind) DO UPDATE SET
        event_count    = kind_stats.event_count + EXCLUDED.event_count,
        first_event_at = LEAST(kind_stats.first_event_at, EXCLUDED.first_event_at),
        last_event_at  = GREATEST(kind_stats.last_event_at, EXCLUDED.last_event_at),
        unique_pubkeys = COALESCE(
            (SELECT COUNT(*)::INTEGER FROM pubkey_kind_stats WHERE kind = kind_stats.kind), 0
        ),
        unique_relays = COALESCE(
            (SELECT COUNT(*)::INTEGER FROM relay_kind_stats WHERE kind = kind_stats.kind), 0
        );

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

    -- relay_stats (uses event_relay.seen_at for relay-specific windows)
    WITH windows AS (
        SELECT
            er.relay_url,
            COUNT(*) FILTER (WHERE e.created_at >= v_24h) AS last_24h,
            COUNT(*) FILTER (WHERE e.created_at >= v_7d)  AS last_7d,
            COUNT(*) FILTER (WHERE e.created_at >= v_30d) AS last_30d
        FROM event_relay AS er
        INNER JOIN event AS e ON er.event_id = e.id
        WHERE e.created_at >= v_30d
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
    WHERE last_event_at < v_30d
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

    -- Update NIP-11 info from relay_metadata_latest
    UPDATE relay_stats rs SET
        nip11_name     = m.data -> 'data' ->> 'name',
        nip11_software = m.data -> 'data' ->> 'software',
        nip11_version  = m.data -> 'data' ->> 'version'
    FROM relay_metadata_latest rml
    INNER JOIN metadata m ON rml.metadata_id = m.id AND rml.metadata_type = m.type
    WHERE rml.metadata_type = 'nip11_info'
      AND rs.relay_url = rml.relay_url;
END;
$$;

COMMENT ON FUNCTION relay_stats_metadata_refresh() IS
'Update relay_stats RTT, NIP-11, network, and discovered_at from metadata tables. Seeds new relays.';


-- **************************************************************************
-- MATERIALIZED VIEW REFRESH (bounded views, full refresh)
-- **************************************************************************


/*
 * relay_software_counts_refresh() -> VOID
 *
 * Depends on relay_metadata_latest being refreshed first.
 */
CREATE OR REPLACE FUNCTION relay_software_counts_refresh()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY relay_software_counts;
END;
$$;

COMMENT ON FUNCTION relay_software_counts_refresh() IS
'Refresh relay_software_counts concurrently. Refresh relay_metadata_latest first.';


/*
 * supported_nip_counts_refresh() -> VOID
 *
 * Depends on relay_metadata_latest being refreshed first.
 */
CREATE OR REPLACE FUNCTION supported_nip_counts_refresh()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY supported_nip_counts;
END;
$$;

COMMENT ON FUNCTION supported_nip_counts_refresh() IS
'Refresh supported_nip_counts concurrently. Refresh relay_metadata_latest first.';


/*
 * daily_counts_refresh() -> VOID
 */
CREATE OR REPLACE FUNCTION daily_counts_refresh()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY daily_counts;
END;
$$;

COMMENT ON FUNCTION daily_counts_refresh() IS
'Refresh daily_counts concurrently.';


/*
 * events_replaceable_latest_refresh() -> VOID
 */
CREATE OR REPLACE FUNCTION events_replaceable_latest_refresh()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY events_replaceable_latest;
END;
$$;

COMMENT ON FUNCTION events_replaceable_latest_refresh() IS
'Refresh events_replaceable_latest concurrently.';


/*
 * events_addressable_latest_refresh() -> VOID
 */
CREATE OR REPLACE FUNCTION events_addressable_latest_refresh()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY events_addressable_latest;
END;
$$;

COMMENT ON FUNCTION events_addressable_latest_refresh() IS
'Refresh events_addressable_latest concurrently.';


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
 * - kind=9735: zap counts/amounts (bolt11-verified, tag p for recipient)
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
        first_created_at = LEAST(nip85_pubkey_stats.first_created_at, EXCLUDED.first_created_at);
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

    -- 4. Reactions received (kind=7, tag p=target)
    WITH delta AS (
        SELECT substring(tv FROM 3) AS target_pubkey, COUNT(*) AS cnt
        FROM _nip85_new_events, unnest(tagvalues) AS tv
        WHERE kind = 7 AND tv LIKE 'p:%'
        GROUP BY substring(tv FROM 3)
    )
    INSERT INTO nip85_pubkey_stats (pubkey, reaction_count_recd)
    SELECT target_pubkey, cnt FROM delta
    ON CONFLICT (pubkey) DO UPDATE SET
        reaction_count_recd = nip85_pubkey_stats.reaction_count_recd + EXCLUDED.reaction_count_recd;

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

    -- 6. Reports received (kind=1984, tag p=target)
    WITH delta AS (
        SELECT substring(tv FROM 3) AS target_pubkey, COUNT(*) AS cnt
        FROM _nip85_new_events, unnest(tagvalues) AS tv
        WHERE kind = 1984 AND tv LIKE 'p:%'
        GROUP BY substring(tv FROM 3)
    )
    INSERT INTO nip85_pubkey_stats (pubkey, report_count_recd)
    SELECT target_pubkey, cnt FROM delta
    ON CONFLICT (pubkey) DO UPDATE SET
        report_count_recd = nip85_pubkey_stats.report_count_recd + EXCLUDED.report_count_recd;

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

    -- 7b. Reposts received (kind=6, tag e → lookup original author)
    WITH repost_targets AS (
        SELECT substring(tv FROM 3) AS target_event_hex
        FROM _nip85_new_events, unnest(tagvalues) AS tv
        WHERE kind = 6 AND tv LIKE 'e:%'
    ),
    delta AS (
        SELECT ENCODE(e.pubkey, 'hex') AS target_pubkey, COUNT(*) AS cnt
        FROM repost_targets rt
        INNER JOIN event e ON e.id = DECODE(rt.target_event_hex, 'hex')
        GROUP BY e.pubkey
    )
    INSERT INTO nip85_pubkey_stats (pubkey, repost_count_recd)
    SELECT target_pubkey, cnt FROM delta
    ON CONFLICT (pubkey) DO UPDATE SET
        repost_count_recd = nip85_pubkey_stats.repost_count_recd + EXCLUDED.repost_count_recd;

    -- 8a. Zaps received (kind=9735, tag p=recipient, bolt11-verified amount)
    WITH zap_data AS (
        SELECT
            substring(tv FROM 3) AS recipient_pubkey,
            (amount_tag.tag ->> 1)::BIGINT AS claimed_amount,
            bolt11_amount_msats(bolt11_tag.tag ->> 1) AS bolt11_amount
        FROM _nip85_new_events ne,
             unnest(ne.tagvalues) AS tv,
             LATERAL (SELECT tag FROM jsonb_array_elements(ne.tags) AS t(tag) WHERE t.tag ->> 0 = 'amount' LIMIT 1) AS amount_tag,
             LATERAL (SELECT tag FROM jsonb_array_elements(ne.tags) AS t(tag) WHERE t.tag ->> 0 = 'bolt11' AND length(t.tag ->> 1) > 0 LIMIT 1) AS bolt11_tag
        WHERE ne.kind = 9735
          AND tv LIKE 'p:%'
    ),
    recd_delta AS (
        SELECT recipient_pubkey AS pubkey, COUNT(*) AS cnt, COALESCE(SUM(claimed_amount), 0) AS amt
        FROM zap_data
        WHERE bolt11_amount IS NOT NULL AND claimed_amount = bolt11_amount
        GROUP BY recipient_pubkey
    )
    INSERT INTO nip85_pubkey_stats (pubkey, zap_count_recd, zap_amount_recd)
    SELECT pubkey, cnt, amt FROM recd_delta
    ON CONFLICT (pubkey) DO UPDATE SET
        zap_count_recd  = nip85_pubkey_stats.zap_count_recd + EXCLUDED.zap_count_recd,
        zap_amount_recd = nip85_pubkey_stats.zap_amount_recd + EXCLUDED.zap_amount_recd;

    -- 8b. Zaps sent (kind=9735, group by sender, bolt11-verified amount)
    WITH zap_data AS (
        SELECT
            ENCODE(ne.pubkey, 'hex') AS sender_pubkey,
            (amount_tag.tag ->> 1)::BIGINT AS claimed_amount,
            bolt11_amount_msats(bolt11_tag.tag ->> 1) AS bolt11_amount
        FROM _nip85_new_events ne,
             LATERAL (SELECT tag FROM jsonb_array_elements(ne.tags) AS t(tag) WHERE t.tag ->> 0 = 'amount' LIMIT 1) AS amount_tag,
             LATERAL (SELECT tag FROM jsonb_array_elements(ne.tags) AS t(tag) WHERE t.tag ->> 0 = 'bolt11' AND length(t.tag ->> 1) > 0 LIMIT 1) AS bolt11_tag
        WHERE ne.kind = 9735
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
                    SELECT key, (val)::BIGINT AS val
                    FROM jsonb_each_text(nip85_pubkey_stats.topic_counts) AS t(key, val)
                    UNION ALL
                    SELECT key, (val)::BIGINT AS val
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
'Incremental refresh of NIP-85 per-pubkey social metrics. Bolt11-verified zap amounts.';


/*
 * nip85_event_stats_refresh(p_after, p_until) -> INTEGER
 *
 * Processes truly new events to update per-event engagement metrics.
 * Extracts engagement from tag relationships:
 * - kind=1 with tag e: comment_count on target event
 * - any kind with tag q: quote_count on target event
 * - kind=6 with tag e: repost_count on target event
 * - kind=7 with tag e: reaction_count on target event
 * - kind=9735 with tag e: zap_count/zap_amount on target event (bolt11-verified)
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

    -- 1. Comments (kind=1 with tag e=target)
    WITH delta AS (
        SELECT substring(tv FROM 3) AS target_event, COUNT(*) AS cnt
        FROM _nip85_new_events_eng, unnest(tagvalues) AS tv
        WHERE kind = 1 AND tv LIKE 'e:%'
        GROUP BY substring(tv FROM 3)
    )
    INSERT INTO nip85_event_stats (event_id, author_pubkey, comment_count)
    SELECT d.target_event, COALESCE(ENCODE(e.pubkey, 'hex'), ''), d.cnt
    FROM delta d LEFT JOIN event e ON e.id = DECODE(d.target_event, 'hex')
    ON CONFLICT (event_id) DO UPDATE SET
        comment_count = nip85_event_stats.comment_count + EXCLUDED.comment_count;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 2. Quotes (any kind with tag q=target)
    WITH delta AS (
        SELECT substring(tv FROM 3) AS target_event, COUNT(*) AS cnt
        FROM _nip85_new_events_eng, unnest(tagvalues) AS tv
        WHERE tv LIKE 'q:%'
        GROUP BY substring(tv FROM 3)
    )
    INSERT INTO nip85_event_stats (event_id, author_pubkey, quote_count)
    SELECT d.target_event, COALESCE(ENCODE(e.pubkey, 'hex'), ''), d.cnt
    FROM delta d LEFT JOIN event e ON e.id = DECODE(d.target_event, 'hex')
    ON CONFLICT (event_id) DO UPDATE SET
        quote_count = nip85_event_stats.quote_count + EXCLUDED.quote_count;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 3. Reposts (kind=6 with tag e=target)
    WITH delta AS (
        SELECT substring(tv FROM 3) AS target_event, COUNT(*) AS cnt
        FROM _nip85_new_events_eng, unnest(tagvalues) AS tv
        WHERE kind = 6 AND tv LIKE 'e:%'
        GROUP BY substring(tv FROM 3)
    )
    INSERT INTO nip85_event_stats (event_id, author_pubkey, repost_count)
    SELECT d.target_event, COALESCE(ENCODE(e.pubkey, 'hex'), ''), d.cnt
    FROM delta d LEFT JOIN event e ON e.id = DECODE(d.target_event, 'hex')
    ON CONFLICT (event_id) DO UPDATE SET
        repost_count = nip85_event_stats.repost_count + EXCLUDED.repost_count;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 4. Reactions (kind=7 with tag e=target)
    WITH delta AS (
        SELECT substring(tv FROM 3) AS target_event, COUNT(*) AS cnt
        FROM _nip85_new_events_eng, unnest(tagvalues) AS tv
        WHERE kind = 7 AND tv LIKE 'e:%'
        GROUP BY substring(tv FROM 3)
    )
    INSERT INTO nip85_event_stats (event_id, author_pubkey, reaction_count)
    SELECT d.target_event, COALESCE(ENCODE(e.pubkey, 'hex'), ''), d.cnt
    FROM delta d LEFT JOIN event e ON e.id = DECODE(d.target_event, 'hex')
    ON CONFLICT (event_id) DO UPDATE SET
        reaction_count = nip85_event_stats.reaction_count + EXCLUDED.reaction_count;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    -- 5. Zaps on events (kind=9735 with tag e=target, bolt11-verified)
    WITH zap_data AS (
        SELECT
            substring(tv FROM 3) AS target_event,
            (amount_tag.tag ->> 1)::BIGINT AS claimed_amount,
            bolt11_amount_msats(bolt11_tag.tag ->> 1) AS bolt11_amount
        FROM _nip85_new_events_eng ne,
             unnest(ne.tagvalues) AS tv,
             LATERAL (SELECT tag FROM jsonb_array_elements(ne.tags) AS t(tag) WHERE t.tag ->> 0 = 'amount' LIMIT 1) AS amount_tag,
             LATERAL (SELECT tag FROM jsonb_array_elements(ne.tags) AS t(tag) WHERE t.tag ->> 0 = 'bolt11' AND length(t.tag ->> 1) > 0 LIMIT 1) AS bolt11_tag
        WHERE ne.kind = 9735
          AND tv LIKE 'e:%'
    ),
    delta AS (
        SELECT target_event, COUNT(*) AS cnt, COALESCE(SUM(claimed_amount), 0) AS amt
        FROM zap_data
        WHERE bolt11_amount IS NOT NULL AND claimed_amount = bolt11_amount
        GROUP BY target_event
    )
    INSERT INTO nip85_event_stats (event_id, author_pubkey, zap_count, zap_amount)
    SELECT d.target_event, COALESCE(ENCODE(e.pubkey, 'hex'), ''), d.cnt, d.amt
    FROM delta d LEFT JOIN event e ON e.id = DECODE(d.target_event, 'hex')
    ON CONFLICT (event_id) DO UPDATE SET
        zap_count  = nip85_event_stats.zap_count + EXCLUDED.zap_count,
        zap_amount = nip85_event_stats.zap_amount + EXCLUDED.zap_amount;
    GET DIAGNOSTICS v_partial = ROW_COUNT;
    v_rows := v_rows + v_partial;

    DROP TABLE IF EXISTS _nip85_new_events_eng;
    RETURN v_rows;
END;
$$;

COMMENT ON FUNCTION nip85_event_stats_refresh(BIGINT, BIGINT) IS
'Incremental refresh of NIP-85 per-event engagement metrics. Bolt11-verified zap amounts.';


-- **************************************************************************
-- NIP-85 PERIODIC REFRESH
-- **************************************************************************


/*
 * nip85_follower_count_refresh() -> VOID
 *
 * Recomputes follower_count for all pubkeys from current contact lists
 * (kind 3, replaceable). Reads from events_replaceable_latest which must
 * be refreshed first.
 *
 * Follower count is non-incremental because kind=3 overwrites the full
 * contact list on each update (follow/unfollow cannot be detected as delta).
 */
CREATE OR REPLACE FUNCTION nip85_follower_count_refresh()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    -- Compute follower counts from latest contact lists
    WITH follower_counts AS (
        SELECT
            substring(tv FROM 3) AS followed_pubkey,
            COUNT(DISTINCT ENCODE(pubkey, 'hex')) AS cnt
        FROM events_replaceable_latest, unnest(tagvalues) AS tv
        WHERE kind = 3 AND tv LIKE 'p:%'
        GROUP BY substring(tv FROM 3)
    )
    UPDATE nip85_pubkey_stats ps SET
        follower_count = fc.cnt
    FROM follower_counts fc
    WHERE ps.pubkey = fc.followed_pubkey;

    -- Zero out pubkeys no longer followed by anyone
    UPDATE nip85_pubkey_stats SET follower_count = 0
    WHERE follower_count > 0
      AND pubkey NOT IN (
          SELECT DISTINCT substring(tv FROM 3)
          FROM events_replaceable_latest, unnest(tagvalues) AS tv
          WHERE kind = 3 AND tv LIKE 'p:%'
      );

    -- Compute following counts (how many p-tags in each pubkey's own kind=3)
    WITH following_counts AS (
        SELECT
            ENCODE(pubkey, 'hex') AS pubkey,
            COUNT(*) FILTER (WHERE tv LIKE 'p:%') AS cnt
        FROM events_replaceable_latest, unnest(tagvalues) AS tv
        WHERE kind = 3
        GROUP BY pubkey
    )
    UPDATE nip85_pubkey_stats ps SET
        following_count = fc.cnt
    FROM following_counts fc
    WHERE ps.pubkey = fc.pubkey;

    UPDATE nip85_pubkey_stats SET following_count = 0
    WHERE following_count > 0
      AND pubkey NOT IN (
          SELECT ENCODE(pubkey, 'hex')
          FROM events_replaceable_latest
          WHERE kind = 3
      );
END;
$$;

COMMENT ON FUNCTION nip85_follower_count_refresh() IS
'Recompute NIP-85 follower and following counts from latest contact lists (events_replaceable_latest). Non-incremental.';
