-- init.sql

CREATE EXTENSION IF NOT EXISTS "btree_gin";  -- For GIN indexes on JSONB

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
CREATE INDEX IF NOT EXISTS idx_events_pubkey ON events USING BTREE (pubkey);    -- Index on pubkey 
CREATE INDEX IF NOT EXISTS idx_events_kind ON events USING BTREE (kind);        -- Index on kind
CREATE INDEX IF NOT EXISTS idx_events_tags ON events USING GIN (tags);          -- Index on tags

-- Create a table for relays   
CREATE TABLE IF NOT EXISTS relays (
    url TEXT PRIMARY KEY NOT NULL,                                          -- Relay URL
    network TEXT NOT NULL                                                   -- Network name (clear, tor, etc.)
);

-- Create a table for events_relays
CREATE TABLE IF NOT EXISTS events_relays (
    event_id CHAR(64) NOT NULL,                                             -- Event id, fixed length 64 characters
    relay_url TEXT NOT NULL,                                                -- Relay URL
    seen_at BIGINT NOT NULL,                                                -- Timestamp of when the event was seen at the relay
    -- constraints
    PRIMARY KEY (event_id, relay_url),                                      -- Composite primary key
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,         -- Foreign key reference to events table
    FOREIGN KEY (relay_url) REFERENCES relays(url) ON DELETE CASCADE        -- Foreign key reference to relays table
);

-- Indexes for faster queries
CREATE INDEX IF NOT EXISTS idx_events_relays_event_id ON events_relays USING BTREE (event_id);      -- Index on event_id
CREATE INDEX IF NOT EXISTS idx_events_relays_relay_url ON events_relays USING BTREE (relay_url);    -- Index on relay_url

-- Create a table for relay_metadata
CREATE TABLE IF NOT EXISTS relay_metadata (
    relay_url TEXT NOT NULL,                                                -- Relay URL
    generated_at BIGINT NOT NULL,                                           -- Timestamp of when the metadata was generated
    connection_success BOOLEAN NOT NULL,                                    -- Success of the connection to the relay
    nip11_success BOOLEAN NOT NULL,                                         -- Success of the metadata retrieval
    -- connection metadata
    openable BOOLEAN,                                                       -- Openable status of the relay (if the relay is open to connect). NULL if connection_success is false
    readable BOOLEAN,                                                       -- read possibility on the relay (if the relay is public to read). NULL if connection_success is false
    writable BOOLEAN,                                                       -- write possibility on the relay (if the relay is public to write). NULL if connection_success is false
    rtt_open INT,                                                           -- Round trip time for open connection. NULL if connection_success is false
    rtt_read INT,                                                           -- Round trip time for read connection. NULL if connection_success is false
    rtt_write INT,                                                          -- Round trip time for write connection. NULL if connection_success is false
    -- nip11 metadata
    name TEXT,                                                              -- Name of the relay. NOT NULL -> nip11_success is true
    description TEXT,                                                       -- Description of the relay. NOT NULL -> nip11_success is true
    banner TEXT,                                                            -- Link to an image (e.g. in .jpg, or .png format). NOT NULL -> nip11_success is true
    icon TEXT,                                                              -- Link to an icon (e.g. in .jpg, or .png format). NOT NULL -> nip11_success is true
    pubkey TEXT,                                                            -- Administrative contact pubkey. NOT NULL -> nip11_success is true
    contact TEXT,                                                           -- Administrative alternate contact. NOT NULL -> nip11_success is true
    supported_nips JSONB,                                                   -- List of NIP numbers supported by the relay. NOT NULL -> nip11_success is true
    software TEXT,                                                          -- Relay software URL. NOT NULL -> nip11_success is true
    version TEXT,                                                           -- Version identifier. NOT NULL -> nip11_success is true
    privacy_policy TEXT,                                                    -- Link to a text file describing the relay's privacy policy. NOT NULL -> nip11_success is true
    terms_of_service TEXT,                                                  -- Link to a text file describing the relay's terms of service. NOT NULL -> nip11_success is true
    limitation JSONB,                                                      -- Limitations of the relay. NULL if connection_success is false
    extra_fields JSONB,                                                     -- Extra fields for future use. NULL if connection_success is false
    -- constraints
    PRIMARY KEY (relay_url, generated_at),                                  -- Composite primary key
    FOREIGN KEY (relay_url) REFERENCES relays(url) ON DELETE CASCADE        -- Foreign key reference to relays table
);

-- Indexes for faster queries
CREATE INDEX IF NOT EXISTS idx_relay_metadata_relay_url ON relay_metadata USING BTREE (relay_url);          -- Index on relay_url
CREATE INDEX IF NOT EXISTS idx_relay_metadata_supported_nips ON relay_metadata USING GIN (supported_nips);  -- Index on supported_nips
CREATE INDEX IF NOT EXISTS idx_relay_metadata_limitation ON relay_metadata USING GIN (limitation);        -- Index on limitations

-- ============================
-- CONSTRAINTS
-- ============================

-- event <-(1,N)----(1,1)-> events_relays <-(1,1)----(0,N)-> relays <-(0,N)----(1,1)-> relay_metadata

-- function to delete orphan events
-- This function deletes events that are not referenced in the events_relays table
CREATE OR REPLACE FUNCTION delete_orphan_events() RETURNS VOID AS $$
BEGIN
    DELETE FROM events e
    WHERE NOT EXISTS (
        SELECT 1
        FROM events_relays er
        WHERE er.event_id = e.id
    );
END;
$$ LANGUAGE plpgsql;

-- ============================
-- INSERTION FUNCTIONS
-- ============================

-- Function to insert an event into the database
CREATE OR REPLACE FUNCTION insert_event(
    p_id CHAR(64),
    p_pubkey CHAR(64),
    p_created_at BIGINT,
    p_kind INT,
    p_tags JSONB,
    p_content TEXT,
    p_sig CHAR(128),
    p_relay_url TEXT,
    p_relay_network TEXT,
    p_seen_at BIGINT
) RETURNS VOID AS $$
BEGIN
    -- Insert the event into the events table
    INSERT INTO events (id, pubkey, created_at, kind, tags, content, sig)
    VALUES (p_id, p_pubkey, p_created_at, p_kind, p_tags, p_content, p_sig)
    ON CONFLICT (id) DO NOTHING;
    -- Insert the relay into the relays table
    INSERT INTO relays (url, network)
    VALUES (p_relay_url, p_relay_network)
    ON CONFLICT (url) DO NOTHING;
    -- Insert the event-relay relation into the events_relays table
    INSERT INTO events_relays (event_id, relay_url, seen_at)
    VALUES (p_id, p_relay_url, p_seen_at)
    ON CONFLICT (event_id, relay_url) DO NOTHING;
END;
$$ LANGUAGE plpgsql;

-- Function to insert a relay into the database
CREATE OR REPLACE FUNCTION insert_relay(
    p_url TEXT,
    p_network TEXT
) RETURNS VOID AS $$
BEGIN
    -- Insert the relay into the relays table
    INSERT INTO relays (url, network)
    VALUES (p_url, p_network)
    ON CONFLICT (url) DO NOTHING;
END;
$$ LANGUAGE plpgsql;

-- Function to insert relay metadata into the database
CREATE OR REPLACE FUNCTION insert_relay_metadata(
    p_relay_url TEXT,
    p_relay_network TEXT,
    p_generated_at BIGINT,
    p_connection_success BOOLEAN,
    p_nip11_success BOOLEAN,
    p_openable BOOLEAN,
    p_readable BOOLEAN,
    p_writable BOOLEAN,
    p_rtt_open INT,
    p_rtt_read INT,
    p_rtt_write INT,
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
    p_limitation JSONB,
    p_extra_fields JSONB
) RETURNS VOID AS $$
BEGIN
    -- Insert the relay into the relays table
    INSERT INTO relays(url, network)
    VALUES (p_relay_url, p_relay_network)
    ON CONFLICT (url) DO NOTHING;
    -- Insert the relay metadata into the relay_metadata table
    INSERT INTO relay_metadata (
        relay_url,
        generated_at,
        connection_success,
        nip11_success,
        openable,
        readable,
        writable,
        rtt_open,
        rtt_read,
        rtt_write,
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
        limitation,
        extra_fields
    )
    VALUES (
        p_relay_url,
        p_generated_at,
        p_connection_success,
        p_nip11_success,
        p_openable,
        p_readable,
        p_writable,
        p_rtt_open,
        p_rtt_read,
        p_rtt_write,
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
        p_limitation,
        p_extra_fields
    )
    ON CONFLICT (relay_url, generated_at) DO NOTHING;
END;
$$ LANGUAGE plpgsql;