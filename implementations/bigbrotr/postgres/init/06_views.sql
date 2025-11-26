-- ============================================================================
-- BigBrotr Database Initialization Script
-- ============================================================================
-- File: 06_views.sql
-- Description: Convenient database views for common queries
-- Dependencies: 02_tables.sql
-- ============================================================================

-- View: relay_metadata_latest
-- Description: Latest metadata for each relay (joins with NIP-11 and NIP-66)
-- Purpose: Provides a unified view of the most recent relay information
-- Note: Uses DISTINCT ON for better performance than LATERAL subquery
CREATE OR REPLACE VIEW relay_metadata_latest AS
WITH latest_metadata AS (
    SELECT DISTINCT ON (relay_url)
        relay_url,
        generated_at,
        nip11_id,
        nip66_id
    FROM relay_metadata
    ORDER BY relay_url, generated_at DESC
)
SELECT
    r.url AS relay_url,
    r.network,
    r.inserted_at,
    lm.generated_at,

    -- NIP-66 data
    n66.id AS nip66_id,
    n66.openable AS nip66_openable,
    n66.readable AS nip66_readable,
    n66.writable AS nip66_writable,
    n66.rtt_open AS nip66_rtt_open,
    n66.rtt_read AS nip66_rtt_read,
    n66.rtt_write AS nip66_rtt_write,

    -- NIP-11 data
    n11.id AS nip11_id,
    n11.name AS nip11_name,
    n11.description AS nip11_description,
    n11.banner AS nip11_banner,
    n11.icon AS nip11_icon,
    n11.pubkey AS nip11_pubkey,
    n11.contact AS nip11_contact,
    n11.supported_nips AS nip11_supported_nips,
    n11.software AS nip11_software,
    n11.version AS nip11_version,
    n11.privacy_policy AS nip11_privacy_policy,
    n11.terms_of_service AS nip11_terms_of_service,
    n11.limitation AS nip11_limitation,
    n11.extra_fields AS nip11_extra_fields
FROM relays r
LEFT JOIN latest_metadata lm ON r.url = lm.relay_url
LEFT JOIN nip66 n66 ON lm.nip66_id = n66.id
LEFT JOIN nip11 n11 ON lm.nip11_id = n11.id;

COMMENT ON VIEW relay_metadata_latest IS 'Latest metadata per relay (combines most recent snapshot with NIP-11/NIP-66 data)';
COMMENT ON COLUMN relay_metadata_latest.relay_url IS 'WebSocket URL of the relay';
COMMENT ON COLUMN relay_metadata_latest.network IS 'Network type: clearnet or tor';
COMMENT ON COLUMN relay_metadata_latest.inserted_at IS 'Unix timestamp when relay was first discovered';
COMMENT ON COLUMN relay_metadata_latest.generated_at IS 'Unix timestamp of the most recent metadata snapshot';
COMMENT ON COLUMN relay_metadata_latest.nip66_id IS 'Foreign key to nip66 table (NULL if no NIP-66 data)';
COMMENT ON COLUMN relay_metadata_latest.nip66_openable IS 'Whether relay accepts WebSocket connections';
COMMENT ON COLUMN relay_metadata_latest.nip66_readable IS 'Whether relay responds to REQ messages';
COMMENT ON COLUMN relay_metadata_latest.nip66_writable IS 'Whether relay accepts EVENT messages';
COMMENT ON COLUMN relay_metadata_latest.nip66_rtt_open IS 'Round-trip time for connection (milliseconds)';
COMMENT ON COLUMN relay_metadata_latest.nip66_rtt_read IS 'Round-trip time for read operations (milliseconds)';
COMMENT ON COLUMN relay_metadata_latest.nip66_rtt_write IS 'Round-trip time for write operations (milliseconds)';
COMMENT ON COLUMN relay_metadata_latest.nip11_id IS 'Foreign key to nip11 table (NULL if no NIP-11 data)';
COMMENT ON COLUMN relay_metadata_latest.nip11_name IS 'Human-readable relay name';
COMMENT ON COLUMN relay_metadata_latest.nip11_description IS 'Relay description text';
COMMENT ON COLUMN relay_metadata_latest.nip11_banner IS 'URL to relay banner image';
COMMENT ON COLUMN relay_metadata_latest.nip11_icon IS 'URL to relay icon';
COMMENT ON COLUMN relay_metadata_latest.nip11_pubkey IS 'Relay operator public key (hex)';
COMMENT ON COLUMN relay_metadata_latest.nip11_contact IS 'Relay operator contact information';
COMMENT ON COLUMN relay_metadata_latest.nip11_supported_nips IS 'Array of supported NIP numbers';
COMMENT ON COLUMN relay_metadata_latest.nip11_software IS 'Relay software name and repository';
COMMENT ON COLUMN relay_metadata_latest.nip11_version IS 'Relay software version';
COMMENT ON COLUMN relay_metadata_latest.nip11_privacy_policy IS 'URL to privacy policy document';
COMMENT ON COLUMN relay_metadata_latest.nip11_terms_of_service IS 'URL to terms of service document';
COMMENT ON COLUMN relay_metadata_latest.nip11_limitation IS 'JSON object with relay limitations';
COMMENT ON COLUMN relay_metadata_latest.nip11_extra_fields IS 'Additional non-standard fields';

-- View: events_statistics
-- Description: Global statistics about events in the database
-- Purpose: Provides key metrics about events without content/tags analysis
CREATE OR REPLACE VIEW events_statistics AS
SELECT
    COUNT(*) AS total_events,
    COUNT(DISTINCT pubkey) AS unique_pubkeys,
    COUNT(DISTINCT kind) AS unique_kinds,
    MIN(created_at) AS earliest_event_timestamp,
    MAX(created_at) AS latest_event_timestamp,

    -- Event category counts according to NIP-01 specifications
    COUNT(*) FILTER (WHERE
        (kind >= 1000 AND kind < 10000) OR
        (kind >= 4 AND kind < 45) OR
        kind = 1 OR
        kind = 2
    ) AS regular_events,

    COUNT(*) FILTER (WHERE
        (kind >= 10000 AND kind < 20000) OR
        kind = 0 OR
        kind = 3
    ) AS replaceable_events,

    COUNT(*) FILTER (WHERE
        kind >= 20000 AND kind < 30000
    ) AS ephemeral_events,

    COUNT(*) FILTER (WHERE
        kind >= 30000 AND kind < 40000
    ) AS addressable_events,

    -- Time-based metrics
    COUNT(*) FILTER (WHERE created_at >= EXTRACT(EPOCH FROM NOW() - INTERVAL '1 hour')) AS events_last_hour,
    COUNT(*) FILTER (WHERE created_at >= EXTRACT(EPOCH FROM NOW() - INTERVAL '24 hours')) AS events_last_24h,
    COUNT(*) FILTER (WHERE created_at >= EXTRACT(EPOCH FROM NOW() - INTERVAL '7 days')) AS events_last_7d,
    COUNT(*) FILTER (WHERE created_at >= EXTRACT(EPOCH FROM NOW() - INTERVAL '30 days')) AS events_last_30d

FROM events;

COMMENT ON VIEW events_statistics IS 'Global event statistics with NIP-01 event categories';
COMMENT ON COLUMN events_statistics.total_events IS 'Total number of events in the database';
COMMENT ON COLUMN events_statistics.unique_pubkeys IS 'Number of unique public keys (authors)';
COMMENT ON COLUMN events_statistics.unique_kinds IS 'Number of unique event kinds';
COMMENT ON COLUMN events_statistics.earliest_event_timestamp IS 'Unix timestamp of the oldest event';
COMMENT ON COLUMN events_statistics.latest_event_timestamp IS 'Unix timestamp of the newest event';
COMMENT ON COLUMN events_statistics.regular_events IS 'Regular events (kinds: 1-2, 4-44, 1000-9999) - stored by relays';
COMMENT ON COLUMN events_statistics.replaceable_events IS 'Replaceable events (kinds: 0, 3, 10000-19999) - only latest per pubkey+kind stored';
COMMENT ON COLUMN events_statistics.ephemeral_events IS 'Ephemeral events (kinds: 20000-29999) - not expected to be stored';
COMMENT ON COLUMN events_statistics.addressable_events IS 'Addressable events (kinds: 30000-39999) - only latest per pubkey+kind+d-tag stored';
COMMENT ON COLUMN events_statistics.events_last_hour IS 'Events created in the last hour';
COMMENT ON COLUMN events_statistics.events_last_24h IS 'Events created in the last 24 hours';
COMMENT ON COLUMN events_statistics.events_last_7d IS 'Events created in the last 7 days';
COMMENT ON COLUMN events_statistics.events_last_30d IS 'Events created in the last 30 days';

-- View: relays_statistics
-- Description: Per-relay statistics with event counts and performance metrics
-- Purpose: Provides detailed metrics for each relay
CREATE OR REPLACE VIEW relays_statistics AS
WITH relay_event_stats AS (
    SELECT
        er.relay_url,
        COUNT(DISTINCT er.event_id) AS event_count,
        COUNT(DISTINCT e.pubkey) AS unique_pubkeys,
        MIN(e.created_at) AS first_event_timestamp,
        MAX(e.created_at) AS last_event_timestamp
    FROM events_relays er
    LEFT JOIN events e ON er.event_id = e.id
    GROUP BY er.relay_url
),
relay_performance AS (
    -- Get last 10 RTT measurements per relay and calculate averages
    SELECT
        relay_url,
        AVG(rtt_open) FILTER (WHERE rtt_open IS NOT NULL) AS avg_rtt_open,
        AVG(rtt_read) FILTER (WHERE rtt_read IS NOT NULL) AS avg_rtt_read,
        AVG(rtt_write) FILTER (WHERE rtt_write IS NOT NULL) AS avg_rtt_write
    FROM (
        SELECT
            rm.relay_url,
            n66.rtt_open,
            n66.rtt_read,
            n66.rtt_write,
            ROW_NUMBER() OVER (PARTITION BY rm.relay_url ORDER BY rm.generated_at DESC) AS rn
        FROM relay_metadata rm
        LEFT JOIN nip66 n66 ON rm.nip66_id = n66.id
        WHERE n66.id IS NOT NULL
    ) recent_measurements
    WHERE rn <= 10  -- Only consider last 10 measurements
    GROUP BY relay_url
)
SELECT
    r.url AS relay_url,
    r.network,
    r.inserted_at,
    COALESCE(res.event_count, 0) AS event_count,
    COALESCE(res.unique_pubkeys, 0) AS unique_pubkeys,
    res.first_event_timestamp,
    res.last_event_timestamp,
    ROUND(rp.avg_rtt_open::NUMERIC, 2) AS avg_rtt_open,
    ROUND(rp.avg_rtt_read::NUMERIC, 2) AS avg_rtt_read,
    ROUND(rp.avg_rtt_write::NUMERIC, 2) AS avg_rtt_write
FROM relays r
LEFT JOIN relay_event_stats res ON r.url = res.relay_url
LEFT JOIN relay_performance rp ON r.url = rp.relay_url
ORDER BY r.url;

COMMENT ON VIEW relays_statistics IS 'Per-relay statistics including event counts and performance metrics';
COMMENT ON COLUMN relays_statistics.relay_url IS 'WebSocket URL of the relay';
COMMENT ON COLUMN relays_statistics.network IS 'Network type: clearnet or tor';
COMMENT ON COLUMN relays_statistics.inserted_at IS 'Unix timestamp when relay was first discovered';
COMMENT ON COLUMN relays_statistics.event_count IS 'Total number of distinct events from this relay';
COMMENT ON COLUMN relays_statistics.unique_pubkeys IS 'Number of unique public keys seen on this relay';
COMMENT ON COLUMN relays_statistics.first_event_timestamp IS 'Unix timestamp of the oldest event from this relay';
COMMENT ON COLUMN relays_statistics.last_event_timestamp IS 'Unix timestamp of the newest event from this relay';
COMMENT ON COLUMN relays_statistics.avg_rtt_open IS 'Average RTT for WebSocket open (ms) - last 10 measurements';
COMMENT ON COLUMN relays_statistics.avg_rtt_read IS 'Average RTT for read operations (ms) - last 10 measurements';
COMMENT ON COLUMN relays_statistics.avg_rtt_write IS 'Average RTT for write operations (ms) - last 10 measurements';

-- View: kind_counts_total
-- Description: Aggregated count of events by kind across all relays
-- Purpose: Quick overview of event type distribution
CREATE OR REPLACE VIEW kind_counts_total AS
SELECT
    kind,
    COUNT(*) AS event_count,
    COUNT(DISTINCT pubkey) AS unique_pubkeys
FROM events
GROUP BY kind
ORDER BY event_count DESC;

COMMENT ON VIEW kind_counts_total IS 'Total event counts by kind across all relays';
COMMENT ON COLUMN kind_counts_total.kind IS 'Event kind number';
COMMENT ON COLUMN kind_counts_total.event_count IS 'Total number of events of this kind';
COMMENT ON COLUMN kind_counts_total.unique_pubkeys IS 'Number of unique authors for this kind';

-- View: kind_counts_by_relay
-- Description: Detailed count of events by kind and relay
-- Purpose: Analyze event type distribution per relay
CREATE OR REPLACE VIEW kind_counts_by_relay AS
SELECT
    e.kind,
    er.relay_url,
    COUNT(*) AS event_count,
    COUNT(DISTINCT e.pubkey) AS unique_pubkeys
FROM events e
JOIN events_relays er ON e.id = er.event_id
GROUP BY e.kind, er.relay_url
ORDER BY e.kind, event_count DESC;

COMMENT ON VIEW kind_counts_by_relay IS 'Event counts by kind for each relay';
COMMENT ON COLUMN kind_counts_by_relay.kind IS 'Event kind number';
COMMENT ON COLUMN kind_counts_by_relay.relay_url IS 'WebSocket URL of the relay';
COMMENT ON COLUMN kind_counts_by_relay.event_count IS 'Number of events of this kind on this relay';
COMMENT ON COLUMN kind_counts_by_relay.unique_pubkeys IS 'Number of unique authors for this kind on this relay';

-- View: pubkey_counts_total
-- Description: Aggregated count of events by pubkey across all relays
-- Purpose: Quick overview of author activity
CREATE OR REPLACE VIEW pubkey_counts_total AS
SELECT
    encode(pubkey, 'hex') AS pubkey_hex,
    COUNT(*) AS event_count,
    COUNT(DISTINCT kind) AS unique_kinds,
    MIN(created_at) AS first_event_timestamp,
    MAX(created_at) AS last_event_timestamp
FROM events
GROUP BY pubkey
ORDER BY event_count DESC;

COMMENT ON VIEW pubkey_counts_total IS 'Total event counts by public key across all relays';
COMMENT ON COLUMN pubkey_counts_total.pubkey_hex IS 'Public key in hexadecimal format';
COMMENT ON COLUMN pubkey_counts_total.event_count IS 'Total number of events from this public key';
COMMENT ON COLUMN pubkey_counts_total.unique_kinds IS 'Number of different event kinds used by this pubkey';
COMMENT ON COLUMN pubkey_counts_total.first_event_timestamp IS 'Unix timestamp of first event from this pubkey';
COMMENT ON COLUMN pubkey_counts_total.last_event_timestamp IS 'Unix timestamp of most recent event from this pubkey';

-- View: pubkey_counts_by_relay
-- Description: Detailed count of events by pubkey and relay
-- Purpose: Analyze author activity distribution per relay
CREATE OR REPLACE VIEW pubkey_counts_by_relay AS
SELECT
    encode(e.pubkey, 'hex') AS pubkey_hex,
    er.relay_url,
    COUNT(*) AS event_count,
    COUNT(DISTINCT e.kind) AS unique_kinds,
    MIN(e.created_at) AS first_event_timestamp,
    MAX(e.created_at) AS last_event_timestamp,
    ARRAY_AGG(DISTINCT e.kind ORDER BY e.kind) AS kinds_used
FROM events e
JOIN events_relays er ON e.id = er.event_id
GROUP BY e.pubkey, er.relay_url
ORDER BY e.pubkey, event_count DESC;

COMMENT ON VIEW pubkey_counts_by_relay IS 'Event counts by public key for each relay';
COMMENT ON COLUMN pubkey_counts_by_relay.pubkey_hex IS 'Public key in hexadecimal format';
COMMENT ON COLUMN pubkey_counts_by_relay.relay_url IS 'WebSocket URL of the relay';
COMMENT ON COLUMN pubkey_counts_by_relay.event_count IS 'Number of events from this pubkey on this relay';
COMMENT ON COLUMN pubkey_counts_by_relay.unique_kinds IS 'Number of different event kinds from this pubkey on this relay';
COMMENT ON COLUMN pubkey_counts_by_relay.first_event_timestamp IS 'Unix timestamp of first event from this pubkey';
COMMENT ON COLUMN pubkey_counts_by_relay.last_event_timestamp IS 'Unix timestamp of most recent event from this pubkey';
COMMENT ON COLUMN pubkey_counts_by_relay.kinds_used IS 'Array of event kinds used by this pubkey on this relay';

-- ============================================================================
-- VIEWS CREATED
-- ============================================================================