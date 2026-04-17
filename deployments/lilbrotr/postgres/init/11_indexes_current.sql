/*
 * Brotr - 11_indexes_current.sql
 *
 * Performance indexes for current-state tables.
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

-- contact_lists_current: change feed for ranker sync and analytics rebuild tools
CREATE INDEX IF NOT EXISTS idx_contact_lists_current_source_seen_at_follower
ON contact_lists_current USING btree (source_seen_at ASC, follower_pubkey ASC);

-- contact_list_edges_current: reverse lookup for follower counts / inbound graph traversal
CREATE INDEX IF NOT EXISTS idx_contact_list_edges_current_followed
ON contact_list_edges_current USING btree (followed_pubkey);
