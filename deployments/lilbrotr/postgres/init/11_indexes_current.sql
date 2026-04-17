/*
 * Brotr - 11_indexes_current.sql
 *
 * Performance indexes for narrow current winner tables.
 *
 * Dependencies: 03_tables_current.sql
 */

-- ==========================================================================
-- CURRENT TABLE INDEXES: relay_document_current
-- ==========================================================================

-- Filter current snapshots by role and refresh window.
CREATE INDEX IF NOT EXISTS idx_relay_document_current_role_associated_at
ON relay_document_current USING btree (role, associated_at ASC);

-- replaceable_event_current: current-state lookups by event_id and kind
CREATE UNIQUE INDEX IF NOT EXISTS idx_replaceable_event_current_event_id
ON replaceable_event_current USING btree (event_id);

CREATE INDEX IF NOT EXISTS idx_replaceable_event_current_kind
ON replaceable_event_current USING btree (kind);

-- addressable_event_current: current-state lookups by event_id and kind
CREATE UNIQUE INDEX IF NOT EXISTS idx_addressable_event_current_event_id
ON addressable_event_current USING btree (event_id);

CREATE INDEX IF NOT EXISTS idx_addressable_event_current_kind
ON addressable_event_current USING btree (kind);
