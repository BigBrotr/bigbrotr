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
CREATE OR REPLACE VIEW relay_metadata_latest AS
SELECT
    r.url AS relay_url,
    r.network,
    r.inserted_at,
    rm.generated_at,

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
LEFT JOIN LATERAL (
    SELECT *
    FROM relay_metadata
    WHERE relay_url = r.url
    ORDER BY generated_at DESC
    LIMIT 1
) rm ON TRUE
LEFT JOIN nip66 n66 ON rm.nip66_id = n66.id
LEFT JOIN nip11 n11 ON rm.nip11_id = n11.id;

COMMENT ON VIEW relay_metadata_latest IS 'Latest metadata per relay (combines most recent snapshot with NIP-11/NIP-66 data)';

-- View: readable_relays
-- Description: Relays that are currently readable (based on latest NIP-66 test)
-- Purpose: Quick access to relays available for synchronization
CREATE OR REPLACE VIEW readable_relays AS
SELECT
    relay_url,
    network,
    generated_at,
    nip66_rtt_read
FROM relay_metadata_latest
WHERE nip66_readable = TRUE
ORDER BY nip66_rtt_read ASC NULLS LAST;

COMMENT ON VIEW readable_relays IS 'Relays with readable=TRUE in latest test (sorted by RTT)';

-- ============================================================================
-- VIEWS CREATED
-- ============================================================================