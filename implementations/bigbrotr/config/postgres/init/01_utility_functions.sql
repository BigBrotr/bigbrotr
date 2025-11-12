-- ============================================================================
-- BigBrotr Database Initialization Script
-- ============================================================================
-- File: 01_utility_functions.sql
-- Description: Utility functions for tag indexing and hash computation
-- Dependencies: 00_extensions.sql
-- ============================================================================

-- Function: tags_to_tagvalues
-- Description: Extracts single-character tag keys and their values from JSONB array
-- Purpose: Enables efficient GIN indexing on Nostr event tags
-- Parameters: JSONB array of tags in format [["key", "value"], ...]
-- Returns: TEXT[] of tag values where key length = 1
CREATE OR REPLACE FUNCTION tags_to_tagvalues(p_tags JSONB)
RETURNS TEXT[]
LANGUAGE plpgsql
IMMUTABLE
RETURNS NULL ON NULL INPUT
AS $$
BEGIN
    RETURN (
        SELECT array_agg(tag_element->>1)
        FROM jsonb_array_elements(p_tags) AS tag_element
        WHERE length(tag_element->>0) = 1
    );
END;
$$;

COMMENT ON FUNCTION tags_to_tagvalues(JSONB) IS 'Extracts single-character tag keys and values from JSONB array for efficient GIN indexing';

-- Function: compute_nip11_hash
-- Description: Computes deterministic hash for NIP-11 data
-- Purpose: Enables deduplication of identical NIP-11 records
-- Returns: SHA-256 hash as BYTEA (32 bytes binary)
CREATE OR REPLACE FUNCTION compute_nip11_hash(
    p_name                  TEXT,
    p_description           TEXT,
    p_banner                TEXT,
    p_icon                  TEXT,
    p_pubkey                TEXT,
    p_contact               TEXT,
    p_supported_nips        JSONB,
    p_software              TEXT,
    p_version               TEXT,
    p_privacy_policy        TEXT,
    p_terms_of_service      TEXT,
    p_limitation            JSONB,
    p_extra_fields          JSONB
)
RETURNS BYTEA
LANGUAGE plpgsql
IMMUTABLE
AS $$
BEGIN
    -- Use jsonb_build_object to avoid delimiter collision attacks
    -- Returns raw binary hash as BYTEA (will be converted from hex string in app)
    RETURN decode(
        encode(
            digest(
                jsonb_build_object(
                    'name', p_name,
                    'description', p_description,
                    'banner', p_banner,
                    'icon', p_icon,
                    'pubkey', p_pubkey,
                    'contact', p_contact,
                    'supported_nips', p_supported_nips,
                    'software', p_software,
                    'version', p_version,
                    'privacy_policy', p_privacy_policy,
                    'terms_of_service', p_terms_of_service,
                    'limitation', p_limitation,
                    'extra_fields', p_extra_fields
                )::text,
                'sha256'
            ),
            'hex'
        ),
        'hex'
    );
END;
$$;

COMMENT ON FUNCTION compute_nip11_hash(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, TEXT, TEXT, TEXT, JSONB, JSONB) IS 'Computes SHA-256 hash of NIP-11 data as BYTEA for content-based deduplication';

-- Function: compute_nip66_hash
-- Description: Computes deterministic hash for NIP-66 data
-- Purpose: Enables deduplication of identical NIP-66 records
-- Returns: SHA-256 hash as BYTEA (32 bytes binary)
CREATE OR REPLACE FUNCTION compute_nip66_hash(
    p_openable      BOOLEAN,
    p_readable      BOOLEAN,
    p_writable      BOOLEAN,
    p_rtt_open      INTEGER,
    p_rtt_read      INTEGER,
    p_rtt_write     INTEGER
)
RETURNS BYTEA
LANGUAGE plpgsql
IMMUTABLE
AS $$
BEGIN
    -- Use jsonb_build_object to avoid delimiter collision attacks
    -- Returns raw binary hash as BYTEA (will be converted from hex string in app)
    RETURN decode(
        encode(
            digest(
                jsonb_build_object(
                    'openable', p_openable,
                    'readable', p_readable,
                    'writable', p_writable,
                    'rtt_open', p_rtt_open,
                    'rtt_read', p_rtt_read,
                    'rtt_write', p_rtt_write
                )::text,
                'sha256'
            ),
            'hex'
        ),
        'hex'
    );
END;
$$;

COMMENT ON FUNCTION compute_nip66_hash(BOOLEAN, BOOLEAN, BOOLEAN, INTEGER, INTEGER, INTEGER) IS 'Computes SHA-256 hash of NIP-66 test results as BYTEA for content-based deduplication';

-- ============================================================================
-- UTILITY FUNCTIONS CREATED
-- ============================================================================