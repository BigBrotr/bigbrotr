/*
 * Brotr - 12_indexes_analytics.sql
 *
 * Performance indexes for analytics and NIP-85 summary tables.
 *
 * Dependencies: 04_tables_analytics.sql
 */

-- ==========================================================================
-- ANALYTICS TABLE INDEXES (secondary — PKs are defined in 04)
-- ==========================================================================

-- pubkey_kind_stats: lookup by kind for kind_stats unique_pubkeys derivation
CREATE INDEX IF NOT EXISTS idx_pubkey_kind_stats_kind
ON pubkey_kind_stats USING btree (kind);

-- pubkey_relay_stats: lookup by relay for relay_stats unique_pubkeys derivation
CREATE INDEX IF NOT EXISTS idx_pubkey_relay_stats_relay
ON pubkey_relay_stats USING btree (relay_url);

-- relay_kind_stats: lookup by kind for kind_stats unique_relays derivation
CREATE INDEX IF NOT EXISTS idx_relay_kind_stats_kind
ON relay_kind_stats USING btree (kind);

-- ==========================================================================
-- NIP-85 SUMMARY TABLE INDEXES
-- ==========================================================================

-- nip85_event_stats: lookup by author for "all engagement on my events"
CREATE INDEX IF NOT EXISTS idx_nip85_event_stats_author
ON nip85_event_stats USING btree (author_pubkey);


-- ==========================================================================
-- TABLE INDEXES: relay_software_counts
-- ==========================================================================
-- Primary key on (software, version) already covers the main access path.


-- ==========================================================================
-- TABLE INDEXES: supported_nip_counts
-- ==========================================================================
-- Primary key on (nip) already covers the main access path.
