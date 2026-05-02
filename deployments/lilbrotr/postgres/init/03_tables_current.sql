/*
 * Brotr - 03_tables_current.sql
 *
 * Incremental narrow current winner tables for Brotr.
 *
 * These relations store the current winner for logical keys such as
 * (relay_url, role), (pubkey, kind), and (pubkey, kind, d_value).
 * They are maintained by refresh functions in 08_functions_refresh_current.sql.
 *
 * Dependencies: 02_tables_core.sql
 */

-- **************************************************************************
-- CURRENT TABLES (incremental refresh)
-- **************************************************************************
-- These are regular tables maintained by stored procedures that track
-- current/latest state rather than additive aggregates.
--
-- They are facts tables, not reporting views: each row represents the current
-- winner for a logical key such as (pubkey, kind) or (pubkey, kind, d_value).
-- **************************************************************************


-- ==========================================================================
-- relay_document_current: Current document per relay and role
-- ==========================================================================
-- One row per (relay_url, role), containing the most recent relay-document
-- association selected by associated_at DESC, document_id DESC.
--
-- The row stores only winner identity. Rich document payload is reconstructed
-- via joins or higher-level read surfaces.
--
-- Refresh: relay_document_current_refresh(p_after, p_until)

CREATE TABLE IF NOT EXISTS relay_document_current (
    relay_url TEXT NOT NULL REFERENCES relay (url) ON DELETE CASCADE,
    role TEXT NOT NULL,
    associated_at BIGINT NOT NULL,
    document_id BYTEA NOT NULL,
    FOREIGN KEY (document_id, role) REFERENCES document (id, type) ON DELETE CASCADE,
    PRIMARY KEY (relay_url, role)
);

COMMENT ON TABLE relay_document_current IS
'Current relay-document association per (relay_url, role). Incrementally refreshed via relay_document_current_refresh(after, until).';


-- ==========================================================================
-- replaceable_event_current: Current replaceable event per pubkey and kind
-- ==========================================================================
-- NIP-01 replaceable events (kind 0, 3, 10000-19999) have "at most one per
-- pubkey" semantics. This table stores only the current winning event_id per
-- (pubkey, kind). Winner ordering remains event.created_at DESC, event.id DESC.
--
-- Refresh: replaceable_event_current_refresh(p_after, p_until)

CREATE TABLE IF NOT EXISTS replaceable_event_current (
    pubkey BYTEA NOT NULL,
    kind INTEGER NOT NULL,
    event_id BYTEA NOT NULL REFERENCES event (id) ON DELETE CASCADE,
    PRIMARY KEY (pubkey, kind)
);

COMMENT ON TABLE replaceable_event_current IS
'Current replaceable event per (pubkey, kind). Incrementally refreshed via replaceable_event_current_refresh(after, until).';


-- ==========================================================================
-- addressable_event_current: Current addressable event per pubkey, kind, d-value
-- ==========================================================================
-- NIP-01 addressable events (kind 30000-39999) have "at most one per
-- pubkey + kind + d-value" semantics. The d-value is extracted from the first
-- `d` tag when full JSON tags are available. In LilBrotr, where `tags` are
-- not persisted, the refresh function falls back to ordered `tagvalues`
-- entries (`d:*`). Events without any d tag use '' as the default, per
-- NIP-01 specification.
--
-- Refresh: addressable_event_current_refresh(p_after, p_until)

CREATE TABLE IF NOT EXISTS addressable_event_current (
    pubkey BYTEA NOT NULL,
    kind INTEGER NOT NULL,
    d_value TEXT NOT NULL,
    event_id BYTEA NOT NULL REFERENCES event (id) ON DELETE CASCADE,
    PRIMARY KEY (pubkey, kind, d_value)
);

COMMENT ON TABLE addressable_event_current IS
'Current addressable event per (pubkey, kind, d_value). Incrementally refreshed via addressable_event_current_refresh(after, until).';
