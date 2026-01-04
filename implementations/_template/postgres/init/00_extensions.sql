-- ============================================================================
-- BigBrotr Implementation Template - PostgreSQL Extensions
-- ============================================================================
-- File: 00_extensions.sql
-- Purpose: Required PostgreSQL extensions for BigBrotr functionality
-- Dependencies: None (runs first)
-- Customization: None - these extensions are mandatory
-- ============================================================================

-- Extension: btree_gin
-- Purpose: Enables GIN (Generalized Inverted Index) support for btree-comparable types
-- Usage: Required for efficient array containment queries on events.tagvalues column
-- Note: Powers the idx_events_tagvalues index for fast tag-based event filtering
CREATE EXTENSION IF NOT EXISTS btree_gin;

-- Extension: pgcrypto
-- Purpose: Provides cryptographic functions including digest() for SHA-256 hashing
-- Usage: Required for content-addressed metadata storage (hash computed in DB)
-- Note: Used by metadata_insert() and relay_metadata_insert_cascade() functions
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================================
-- EXTENSIONS SUMMARY
-- ============================================================================
-- btree_gin  : Tag-based event filtering with GIN indexes
-- pgcrypto   : Content-addressed metadata deduplication via SHA-256
-- ============================================================================
