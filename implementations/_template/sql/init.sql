-- ============================================================================
-- Template Brotr Database Schema
-- ============================================================================
-- 
-- Copy this file and customize for your implementation:
--   1. Modify the events table to include/exclude fields
--   2. Update the insert_event() procedure to match your schema
--   3. Add custom indexes for your use case
--   4. Add custom functions as needed
--
-- See docs/HOW_TO_CREATE_BROTR.md for detailed instructions
-- ============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gin;

-- ============================================================================
-- Core Tables
-- ============================================================================

-- Relays Table (STANDARD - keep as-is)
CREATE TABLE IF NOT EXISTS relays (
    url             TEXT        PRIMARY KEY,
    network         TEXT        DEFAULT 'clearnet',
    inserted_at     BIGINT      NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())
);

CREATE INDEX IF NOT EXISTS idx_relays_network ON relays USING btree (network);
CREATE INDEX IF NOT EXISTS idx_relays_inserted_at ON relays USING btree (inserted_at);

-- Events Table (CUSTOMIZE THIS!)
CREATE TABLE IF NOT EXISTS events (
    id              CHAR(64)    PRIMARY KEY,
    pubkey          CHAR(64)    NOT NULL,
    created_at      BIGINT      NOT NULL,
    kind            INTEGER     NOT NULL,
    
    -- CUSTOMIZE: Add/remove fields based on your needs
    -- Example options:
    -- tags        JSONB       NOT NULL,  -- For tag-based queries
    -- tagvalues   TEXT[]      GENERATED ALWAYS AS (tags_to_tagvalues(tags)) STORED,
    -- content     TEXT        NOT NULL,  -- For content storage
    -- custom_field TEXT,                 -- Your custom field
    
    sig             CHAR(128)   NOT NULL
);

-- Standard indexes (customize as needed)
CREATE INDEX IF NOT EXISTS idx_events_pubkey ON events USING btree (pubkey);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON events USING btree (created_at);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events USING btree (kind);

-- Add custom indexes for your use case:
-- CREATE INDEX IF NOT EXISTS idx_events_custom ON events USING btree (custom_field);
-- CREATE INDEX IF NOT EXISTS idx_events_tags ON events USING gin (tagvalues);

-- Junction Table (STANDARD - keep as-is)
CREATE TABLE IF NOT EXISTS events_relays (
    event_id        CHAR(64)    NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    relay_url       TEXT        NOT NULL REFERENCES relays(url) ON DELETE CASCADE,
    seen_at         BIGINT      NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW()),
    PRIMARY KEY (event_id, relay_url)
);

CREATE INDEX IF NOT EXISTS idx_events_relays_relay_url ON events_relays USING btree (relay_url);
CREATE INDEX IF NOT EXISTS idx_events_relays_seen_at ON events_relays USING btree (seen_at);

-- Relay Metadata Tables (STANDARD - keep as-is)
CREATE TABLE IF NOT EXISTS nip11 (
    url                 TEXT        PRIMARY KEY REFERENCES relays(url) ON DELETE CASCADE,
    name                TEXT        DEFAULT '',
    description         TEXT        DEFAULT '',
    pubkey              CHAR(64)    DEFAULT '',
    contact             TEXT        DEFAULT '',
    supported_nips      INTEGER[]   DEFAULT '{}',
    software            TEXT        DEFAULT '',
    version             TEXT        DEFAULT '',
    limitation          JSONB       DEFAULT '{}',
    retention           JSONB       DEFAULT '[]',
    relay_countries     TEXT[]      DEFAULT '{}',
    language_tags       TEXT[]      DEFAULT '{}',
    tags                TEXT[]      DEFAULT '{}',
    posting_policy      TEXT        DEFAULT '',
    payments_url        TEXT        DEFAULT '',
    fees                JSONB       DEFAULT '{}',
    icon                TEXT        DEFAULT '',
    relay_hash          CHAR(32),
    updated_at          BIGINT      NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())
);

CREATE TABLE IF NOT EXISTS nip66 (
    url                 TEXT        PRIMARY KEY REFERENCES relays(url) ON DELETE CASCADE,
    network             TEXT,
    dns                 TEXT,
    server              TEXT,
    timeout             INTEGER,
    ssl                 INTEGER,
    nip11               TEXT,
    rtt_open            INTEGER,
    rtt_read            INTEGER,
    rtt_write           INTEGER,
    rtt_total           INTEGER,
    check               TEXT,
    geo                 JSONB,
    info                JSONB,
    nip66_hash          CHAR(32),
    updated_at          BIGINT      NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())
);

CREATE TABLE IF NOT EXISTS relay_metadata (
    url                 TEXT        NOT NULL REFERENCES relays(url) ON DELETE CASCADE,
    inserted_at         BIGINT      NOT NULL,
    relay_hash          CHAR(32),
    nip66_hash          CHAR(32),
    PRIMARY KEY (url, inserted_at)
);

CREATE INDEX IF NOT EXISTS idx_relay_metadata_url ON relay_metadata USING btree (url);
CREATE INDEX IF NOT EXISTS idx_relay_metadata_inserted_at ON relay_metadata USING btree (inserted_at);

-- ============================================================================
-- Utility Functions
-- ============================================================================

-- Tags to tagvalues (if you use tags field)
CREATE OR REPLACE FUNCTION tags_to_tagvalues(tags JSONB)
RETURNS TEXT[]
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    result TEXT[] := '{}';
    tag JSONB;
    tagvalue TEXT;
BEGIN
    FOR tag IN SELECT jsonb_array_elements(tags)
    LOOP
        IF jsonb_array_length(tag) >= 2 THEN
            tagvalue := CONCAT(tag->>0, ':', tag->>1);
            result := array_append(result, tagvalue);
        END IF;
    END LOOP;
    RETURN result;
END;
$$;

-- Compute NIP-11 hash (STANDARD)
CREATE OR REPLACE FUNCTION compute_nip11_hash(
    name TEXT, description TEXT, pubkey CHAR(64), contact TEXT,
    supported_nips INTEGER[], software TEXT, version TEXT
)
RETURNS CHAR(32)
LANGUAGE plpgsql
IMMUTABLE
AS $$
BEGIN
    RETURN MD5(
        COALESCE(name, '') ||
        COALESCE(description, '') ||
        COALESCE(pubkey, '') ||
        COALESCE(contact, '') ||
        COALESCE(array_to_string(supported_nips, ','), '') ||
        COALESCE(software, '') ||
        COALESCE(version, '')
    );
END;
$$;

-- Compute NIP-66 hash (STANDARD)
CREATE OR REPLACE FUNCTION compute_nip66_hash(
    network TEXT, dns TEXT, server TEXT, timeout INTEGER, ssl INTEGER
)
RETURNS CHAR(32)
LANGUAGE plpgsql
IMMUTABLE
AS $$
BEGIN
    RETURN MD5(
        COALESCE(network, '') ||
        COALESCE(dns, '') ||
        COALESCE(server, '') ||
        COALESCE(timeout::TEXT, '') ||
        COALESCE(ssl::TEXT, '')
    );
END;
$$;

-- ============================================================================
-- Data Integrity Functions
-- ============================================================================

-- Delete orphan events (STANDARD)
CREATE OR REPLACE FUNCTION delete_orphan_events()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM events
    WHERE id NOT IN (SELECT DISTINCT event_id FROM events_relays);
END;
$$;

-- Delete orphan NIP-11 (STANDARD)
CREATE OR REPLACE FUNCTION delete_orphan_nip11()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM nip11
    WHERE url NOT IN (SELECT url FROM relays);
END;
$$;

-- Delete orphan NIP-66 (STANDARD)
CREATE OR REPLACE FUNCTION delete_orphan_nip66()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM nip66
    WHERE url NOT IN (SELECT url FROM relays);
END;
$$;

-- ============================================================================
-- Stored Procedures
-- ============================================================================

-- Insert event (CUSTOMIZE THIS!)
CREATE OR REPLACE FUNCTION insert_event(
    p_event_id              CHAR(64),
    p_pubkey                CHAR(64),
    p_created_at            BIGINT,
    p_kind                  INTEGER,
    -- CUSTOMIZE: Add parameters for your custom fields
    -- p_tags                  JSONB,       -- Example: if storing tags
    -- p_content               TEXT,        -- Example: if storing content
    -- p_custom_field          TEXT,        -- Example: custom field
    p_sig                   CHAR(128),
    p_relay_url             TEXT,
    p_relay_network         TEXT,
    p_relay_inserted_at     BIGINT,
    p_seen_at               BIGINT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    -- Insert event (CUSTOMIZE field list!)
    INSERT INTO events (
        id, pubkey, created_at, kind,
        -- CUSTOMIZE: Add your custom fields here
        -- tags, content, custom_field,
        sig
    )
    VALUES (
        p_event_id, p_pubkey, p_created_at, p_kind,
        -- CUSTOMIZE: Add your custom values here
        -- p_tags, p_content, p_custom_field,
        p_sig
    )
    ON CONFLICT (id) DO NOTHING;
    
    -- Insert relay (STANDARD)
    INSERT INTO relays (url, network, inserted_at)
    VALUES (p_relay_url, p_relay_network, p_relay_inserted_at)
    ON CONFLICT (url) DO NOTHING;
    
    -- Insert event-relay association (STANDARD)
    INSERT INTO events_relays (event_id, relay_url, seen_at)
    VALUES (p_event_id, p_relay_url, p_seen_at)
    ON CONFLICT (event_id, relay_url) DO NOTHING;
END;
$$;

-- Insert relay (STANDARD - keep as-is)
CREATE OR REPLACE FUNCTION insert_relay(
    p_url               TEXT,
    p_network           TEXT,
    p_inserted_at       BIGINT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO relays (url, network, inserted_at)
    VALUES (p_url, p_network, p_inserted_at)
    ON CONFLICT (url) DO NOTHING;
END;
$$;

-- Insert relay metadata (STANDARD - keep as-is)
CREATE OR REPLACE FUNCTION insert_relay_metadata(
    p_url                   TEXT,
    p_network               TEXT,
    p_dns                   TEXT,
    p_server                TEXT,
    p_timeout               INTEGER,
    p_ssl                   INTEGER,
    p_nip11                 TEXT,
    p_rtt_open              INTEGER,
    p_rtt_read              INTEGER,
    p_rtt_write             INTEGER,
    p_check                 TEXT,
    p_geo                   JSONB,
    p_info                  JSONB,
    p_name                  TEXT,
    p_description           TEXT,
    p_pubkey                CHAR(64),
    p_contact               TEXT,
    p_supported_nips        INTEGER[],
    p_software              TEXT,
    p_version               TEXT,
    p_limitation            JSONB,
    p_retention             JSONB,
    p_relay_countries       TEXT[],
    p_language_tags         TEXT[],
    p_tags                  TEXT[],
    p_posting_policy        TEXT,
    p_payments_url          TEXT,
    p_fees                  JSONB,
    p_icon                  TEXT,
    p_inserted_at           BIGINT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_relay_hash        CHAR(32);
    v_nip66_hash        CHAR(32);
    v_rtt_total         INTEGER;
BEGIN
    v_rtt_total := COALESCE(p_rtt_open, 0) + COALESCE(p_rtt_read, 0) + COALESCE(p_rtt_write, 0);
    v_relay_hash := compute_nip11_hash(p_name, p_description, p_pubkey, p_contact, p_supported_nips, p_software, p_version);
    v_nip66_hash := compute_nip66_hash(p_network, p_dns, p_server, p_timeout, p_ssl);

    INSERT INTO relays (url, network, inserted_at)
    VALUES (p_url, p_network, p_inserted_at)
    ON CONFLICT (url) DO NOTHING;

    INSERT INTO nip11 (url, name, description, pubkey, contact, supported_nips, software, version,
                       limitation, retention, relay_countries, language_tags, tags, posting_policy,
                       payments_url, fees, icon, relay_hash, updated_at)
    VALUES (p_url, p_name, p_description, p_pubkey, p_contact, p_supported_nips, p_software, p_version,
            p_limitation, p_retention, p_relay_countries, p_language_tags, p_tags, p_posting_policy,
            p_payments_url, p_fees, p_icon, v_relay_hash, p_inserted_at)
    ON CONFLICT (url) DO UPDATE SET
        name = EXCLUDED.name,
        description = EXCLUDED.description,
        pubkey = EXCLUDED.pubkey,
        contact = EXCLUDED.contact,
        supported_nips = EXCLUDED.supported_nips,
        software = EXCLUDED.software,
        version = EXCLUDED.version,
        limitation = EXCLUDED.limitation,
        retention = EXCLUDED.retention,
        relay_countries = EXCLUDED.relay_countries,
        language_tags = EXCLUDED.language_tags,
        tags = EXCLUDED.tags,
        posting_policy = EXCLUDED.posting_policy,
        payments_url = EXCLUDED.payments_url,
        fees = EXCLUDED.fees,
        icon = EXCLUDED.icon,
        relay_hash = EXCLUDED.relay_hash,
        updated_at = EXCLUDED.updated_at
    WHERE nip11.relay_hash != EXCLUDED.relay_hash;

    INSERT INTO nip66 (url, network, dns, server, timeout, ssl, nip11, rtt_open, rtt_read, rtt_write,
                       rtt_total, check, geo, info, nip66_hash, updated_at)
    VALUES (p_url, p_network, p_dns, p_server, p_timeout, p_ssl, p_nip11, p_rtt_open, p_rtt_read,
            p_rtt_write, v_rtt_total, p_check, p_geo, p_info, v_nip66_hash, p_inserted_at)
    ON CONFLICT (url) DO UPDATE SET
        network = EXCLUDED.network,
        dns = EXCLUDED.dns,
        server = EXCLUDED.server,
        timeout = EXCLUDED.timeout,
        ssl = EXCLUDED.ssl,
        nip11 = EXCLUDED.nip11,
        rtt_open = EXCLUDED.rtt_open,
        rtt_read = EXCLUDED.rtt_read,
        rtt_write = EXCLUDED.rtt_write,
        rtt_total = EXCLUDED.rtt_total,
        check = EXCLUDED.check,
        geo = EXCLUDED.geo,
        info = EXCLUDED.info,
        nip66_hash = EXCLUDED.nip66_hash,
        updated_at = EXCLUDED.updated_at
    WHERE nip66.nip66_hash != EXCLUDED.nip66_hash;

    INSERT INTO relay_metadata (url, inserted_at, relay_hash, nip66_hash)
    VALUES (p_url, p_inserted_at, v_relay_hash, v_nip66_hash)
    ON CONFLICT (url, inserted_at) DO UPDATE SET
        relay_hash = EXCLUDED.relay_hash,
        nip66_hash = EXCLUDED.nip66_hash;
END;
$$;

-- ============================================================================
-- Views
-- ============================================================================

-- Latest relay metadata view (STANDARD)
CREATE OR REPLACE VIEW relay_metadata_latest AS
SELECT DISTINCT ON (url)
    url,
    inserted_at,
    relay_hash,
    nip66_hash
FROM relay_metadata
ORDER BY url, inserted_at DESC;

-- Readable relays view (STANDARD)
CREATE OR REPLACE VIEW readable_relays AS
SELECT
    r.url,
    r.network,
    r.inserted_at,
    n11.name,
    n11.description,
    n11.software,
    n11.version,
    n11.supported_nips,
    n66.rtt_open,
    n66.rtt_read,
    n66.rtt_write,
    n66.rtt_total,
    n66.check
FROM relays r
LEFT JOIN nip11 n11 ON r.url = n11.url
LEFT JOIN nip66 n66 ON r.url = n66.url;

-- ============================================================================
-- CUSTOMIZATION CHECKLIST
-- ============================================================================
-- 
-- [ ] Customize events table fields
-- [ ] Update insert_event() procedure parameters
-- [ ] Update insert_event() procedure INSERT statement
-- [ ] Add custom indexes for your use case
-- [ ] Update repositories/event_repository.py to match
-- [ ] Test your implementation:
--       export BROTR_MODE=your_implementation_name
--       docker-compose up -d
--
-- See docs/HOW_TO_CREATE_BROTR.md for detailed instructions
-- ============================================================================

