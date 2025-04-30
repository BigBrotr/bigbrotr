-- init.sql

-- ============================
-- TABLE DEFINITIONS
-- ============================

-- Create events table
CREATE TABLE IF NOT EXISTS events (
    id CHAR(64) PRIMARY KEY NOT NULL,                                       -- Event id, fixed length 64 characters
    pubkey CHAR(64) NOT NULL,                                               -- Public key, fixed length 64 characters
    created_at BIGINT NOT NULL,                                             -- Timestamp of when the event was created
    kind INT NOT NULL,                                                      -- Integer representing the event kind
    tags JSONB NOT NULL,                                                    -- JSONB array of tags
    content TEXT NOT NULL,                                                  -- Arbitrary string
    sig CHAR(128) NOT NULL                                                  -- 64-byte signature, fixed length 128 characters
);

-- Indexes for faster queries
CREATE INDEX IF NOT EXISTS idx_events_pubkey ON events(pubkey) USING BTREE;         -- Index on pubkey using BTREE
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind) USING BTREE;             -- Index on kind using BTREE
CREATE INDEX IF NOT EXISTS idx_events_tags ON events(tags) USING GIN;               -- Index on tags using GIN

-- Create a table for relays   
CREATE TABLE IF NOT EXISTS relays (
    url TEXT PRIMARY KEY NOT NULL                                           -- Relay URL          
);

-- Create a table for event_relay
CREATE TABLE IF NOT EXISTS event_relay (
    event_id CHAR(64) NOT NULL,                                             -- Event id, fixed length 64 characters
    relay_url TEXT NOT NULL,                                                -- Relay URL
    seen_at BIGINT NOT NULL,                                                -- Timestamp of when the event was seen at the relay
    -- constraints
    PRIMARY KEY (event_id, relay_url),                                      -- Composite primary key
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,         -- Foreign key reference to events table
    FOREIGN KEY (relay_url) REFERENCES relays(url) ON DELETE CASCADE        -- Foreign key reference to relays table
);

-- Indexes for faster queries
CREATE INDEX IF NOT EXISTS idx_event_relay_event_id ON event_relay(event_id) USING BTREE;       -- Index on event_id using BTREE
CREATE INDEX IF NOT EXISTS idx_event_relay_relay_url ON event_relay(relay_url) USING BTREE;     -- Index on relay_url using BTREE

-- Create a table for relay_metadata
CREATE TABLE IF NOT EXISTS relay_metadata (
    relay_url TEXT NOT NULL,                                                -- Relay URL
    generated_at BIGINT NOT NULL,                                           -- Timestamp of when the metadata was generated
    connection_success BOOLEAN NOT NULL,                                    -- Success of the connection to the relay
    nip11_success BOOLEAN NOT NULL,                                         -- Success of the metadata retrieval
    -- connection metadata
    readable BOOLEAN,                                                       -- read possibility on the relay (if the relay is public to read). NULL if connection_success is false
    writable BOOLEAN,                                                       -- write possibility on the relay (if the relay is public to write). NULL if connection_success is false
    rtt INT,                                                                -- Round-trip time in milliseconds. NULL if connection_success is false
    -- nip11 metadata
    name TEXT,                                                              -- Name of the relay. NOT NULL -> nip11_success is true
    description TEXT,                                                       -- Description of the relay. NOT NULL -> nip11_success is true
    banner TEXT,                                                            -- Link to an image (e.g. in .jpg, or .png format). NOT NULL -> nip11_success is true
    icon TEXT,                                                              -- Link to an icon (e.g. in .jpg, or .png format). NOT NULL -> nip11_success is true
    pubkey CHAR(64),                                                        -- Administrative contact pubkey. NOT NULL -> nip11_success is true
    contact TEXT,                                                           -- Administrative alternate contact. NOT NULL -> nip11_success is true
    supported_nips JSONB,                                                   -- List of NIP numbers supported by the relay. NOT NULL -> nip11_success is true
    software TEXT,                                                          -- Relay software URL. NOT NULL -> nip11_success is true
    version TEXT,                                                           -- Version identifier. NOT NULL -> nip11_success is true
    privacy_policy TEXT,                                                    -- Link to a text file describing the relay's privacy policy. NOT NULL -> nip11_success is true
    terms_of_service TEXT,                                                  -- Link to a text file describing the relay's terms of service. NOT NULL -> nip11_success is true
    limitations JSONB,                                                      -- Limitations of the relay. NULL if connection_success is false
    extra_fields JSONB,                                                     -- Extra fields for future use. NULL if connection_success is false
    -- constraints
    PRIMARY KEY (relay_url, generated_at),                                  -- Composite primary key
    FOREIGN KEY (relay_url) REFERENCES relays(url) ON DELETE CASCADE,       -- Foreign key reference to relays table
);

-- Indexes for faster queries
CREATE INDEX IF NOT EXISTS idx_relay_metadata_relay_url ON relay_metadata(relay_url);                       -- Index on relay_url  using BTREE
CREATE INDEX IF NOT EXISTS idx_relay_metadata_supported_nips ON relay_metadata(supported_nips) USING GIN;   -- Index on supported_nips using GIN
CREATE INDEX IF NOT EXISTS idx_relay_metadata_limitations ON relay_metadata(limitations) USING GIN;         -- Index on limitations using GIN

-- ============================
-- CONSTRAINTS
-- ============================

-- event <-(1,N)----(1,1)-> event_relay <-(1,1)----(0,N)-> relay <-(0,N)----(1,1)-> relay_metadata

CREATE OR REPLACE FUNCTION delete_orphan_events() RETURNS VOID AS $$
BEGIN
    DELETE FROM events e
    WHERE NOT EXISTS (
        SELECT 1
        FROM event_relay er
        WHERE er.event_id = e.id
    );
END;
$$ LANGUAGE plpgsql;

-- ============================
-- INSERTION FUNCTIONS
-- ============================

CREATE OR REPLACE FUNCTION insert_event(
    p_id CHAR(64),
    p_pubkey CHAR(64),
    p_created_at BIGINT,
    p_kind INT,
    p_tags JSONB,
    p_content TEXT,
    p_sig CHAR(128),
    p_relay_url TEXT,
    p_seen_at BIGINT
) RETURNS VOID AS $$
BEGIN
    -- Insert the event into the events table
    INSERT INTO events (id, pubkey, created_at, kind, tags, content, sig)
    VALUES (p_id, p_pubkey, p_created_at, p_kind, p_tags, p_content, p_sig)
    ON CONFLICT (id) DO NOTHING;
    -- Insert the relay URL into the relays table
    INSERT INTO relays (url)
    VALUES (p_relay_url)
    ON CONFLICT (url) DO NOTHING;
    -- Insert the event ID and relay URL into the event_relay table
    INSERT INTO event_relay (event_id, relay_url, seen_at)
    VALUES (p_id, p_relay_url, p_seen_at)
    ON CONFLICT (event_id, relay_url) DO NOTHING;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION insert_relay(
    p_url TEXT
) RETURNS VOID AS $$
BEGIN
    -- Insert the relay URL into the relays table
    INSERT INTO relays (url)
    VALUES (p_url)
    ON CONFLICT (url) DO NOTHING;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION insert_relay_metadata(
    p_relay_url TEXT,
    p_generated_at BIGINT,
    p_connection_success BOOLEAN,
    p_nip11_success BOOLEAN,
    p_readable BOOLEAN,
    p_writable BOOLEAN,
    p_rtt INT,
    p_name TEXT,
    p_description TEXT,
    p_banner TEXT,
    p_icon TEXT,
    p_pubkey CHAR(64),
    p_contact TEXT,
    p_supported_nips JSONB,
    p_software TEXT,
    p_version TEXT,
    p_privacy_policy TEXT,
    p_terms_of_service TEXT,
    p_limitations JSONB,
    p_extra_fields JSONB
) RETURNS VOID AS $$
BEGIN
    -- Insert the relay URL into the relays table
    INSERT INTO relays(url)
    VALUES (p_relay_url)
    ON CONFLICT (url) DO NOTHING;
    -- Insert the relay metadata into the relay_metadata table
    INSERT INTO relay_metadata (
        relay_url,
        generated_at,
        connection_success,
        nip11_success,
        readable,
        writable,
        rtt,
        name,
        description,
        banner,
        icon,
        pubkey,
        contact,
        supported_nips,
        software,
        version,
        privacy_policy,
        terms_of_service,
        limitations,
        extra_fields
    )
    VALUES (
        p_relay_url,
        p_generated_at,
        p_connection_success,
        p_nip11_success,
        p_readable,
        p_writable,
        p_rtt,
        p_name,
        p_description,
        p_banner,
        p_icon,
        p_pubkey,
        p_contact,
        p_supported_nips,
        p_software,
        p_version,
        p_privacy_policy,
        p_terms_of_service,
        p_limitations,
        p_extra_fields
    )
    ON CONFLICT (relay_url, generated_at) DO NOTHING;
END;
$$ LANGUAGE plpgsql;