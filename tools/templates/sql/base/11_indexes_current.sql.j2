/*
 * Brotr - 11_indexes_current.sql
 *
 * Performance indexes for current-state tables.
 *
 * Dependencies: 03_tables_current.sql
 */

-- ==========================================================================
-- CURRENT TABLE INDEXES: relay_metadata_current
-- ==========================================================================

-- Filter current snapshots by check type and refresh window.
CREATE INDEX IF NOT EXISTS idx_relay_metadata_current_type_generated_at
ON relay_metadata_current USING btree (metadata_type, generated_at ASC);

-- events_replaceable_current: current-state lookups by kind and sync window
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_replaceable_current_id
ON events_replaceable_current USING btree (id);

CREATE INDEX IF NOT EXISTS idx_events_replaceable_current_kind
ON events_replaceable_current USING btree (kind);

CREATE INDEX IF NOT EXISTS idx_events_replaceable_current_kind_first_seen_at
ON events_replaceable_current USING btree (kind, first_seen_at ASC);

-- events_addressable_current: current-state lookups by kind and sync window
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_addressable_current_id
ON events_addressable_current USING btree (id);

CREATE INDEX IF NOT EXISTS idx_events_addressable_current_kind
ON events_addressable_current USING btree (kind);

CREATE INDEX IF NOT EXISTS idx_events_addressable_current_kind_first_seen_at
ON events_addressable_current USING btree (kind, first_seen_at ASC);

-- contact_lists_current: change feed for ranker sync and analytics rebuild tools
CREATE INDEX IF NOT EXISTS idx_contact_lists_current_source_seen_at_follower
ON contact_lists_current USING btree (source_seen_at ASC, follower_pubkey ASC);

-- contact_list_edges_current: reverse lookup for follower counts / inbound graph traversal
CREATE INDEX IF NOT EXISTS idx_contact_list_edges_current_followed
ON contact_list_edges_current USING btree (followed_pubkey);
