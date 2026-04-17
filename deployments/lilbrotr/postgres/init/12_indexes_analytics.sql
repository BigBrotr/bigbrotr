/*
 * Brotr - 12_indexes_analytics.sql
 *
 * Performance indexes for analytics, operational-fact, and NIP-85 summary tables.
 *
 * Dependencies: 04_tables_analytics.sql
 */

-- ==========================================================================
-- ANALYTICS TABLE INDEXES (secondary — PKs are defined in 04)
-- ==========================================================================

-- pubkey_kind_stats: lookup by kind for kind_stats pubkey_count derivation
CREATE INDEX IF NOT EXISTS idx_pubkey_kind_stats_kind
ON pubkey_kind_stats USING btree (kind);

-- pubkey_relay_stats: lookup by relay for relay_stats pubkey_count derivation
CREATE INDEX IF NOT EXISTS idx_pubkey_relay_stats_relay
ON pubkey_relay_stats USING btree (relay_url);

-- relay_kind_stats: lookup by kind for kind_stats relay_count derivation
CREATE INDEX IF NOT EXISTS idx_relay_kind_stats_kind
ON relay_kind_stats USING btree (kind);

-- contact_lists_current: change feed for ranker sync and follower reconciliation
CREATE INDEX IF NOT EXISTS idx_contact_lists_current_source_seen_at_follower
ON contact_lists_current USING btree (source_seen_at ASC, follower_pubkey ASC);

-- contact_list_edges_current: reverse lookup for follower counts / inbound graph traversal
CREATE INDEX IF NOT EXISTS idx_contact_list_edges_current_followed
ON contact_list_edges_current USING btree (followed_pubkey);

-- ==========================================================================
-- NIP-85 SUMMARY TABLE INDEXES
-- ==========================================================================

-- nip85_event_stats: lookup by author for "all engagement on my events"
CREATE INDEX IF NOT EXISTS idx_nip85_event_stats_author
ON nip85_event_stats USING btree (author_pubkey);

-- nip85_addressable_stats: lookup by author for "all engagement on my addressable events"
CREATE INDEX IF NOT EXISTS idx_nip85_addressable_stats_author
ON nip85_addressable_stats USING btree (author_pubkey);

-- pubkey_score: lookup by algorithm and descending score for publish/join paths
CREATE INDEX IF NOT EXISTS idx_pubkey_score_algorithm_score_pubkey
ON pubkey_score USING btree (algorithm_id, score DESC, pubkey ASC);

-- event_score: lookup by algorithm and descending score for publish/join paths
CREATE INDEX IF NOT EXISTS idx_event_score_algorithm_score_event
ON event_score USING btree (algorithm_id, score DESC, event_id ASC);

-- addressable_score: lookup by algorithm and descending score for publish/join paths
CREATE INDEX IF NOT EXISTS idx_addressable_score_algorithm_score_address
ON addressable_score USING btree (algorithm_id, score DESC, event_address ASC);

-- identifier_score: lookup by algorithm and descending score for publish/join paths
CREATE INDEX IF NOT EXISTS idx_identifier_score_algorithm_score_identifier
ON identifier_score USING btree (algorithm_id, score DESC, identifier ASC);


-- ==========================================================================
-- TABLE INDEXES: relay_software_counts
-- ==========================================================================
-- Primary key on (software, version) already covers the main access path.


-- ==========================================================================
-- TABLE INDEXES: supported_nip_counts
-- ==========================================================================
-- Primary key on (nip) already covers the main access path.
