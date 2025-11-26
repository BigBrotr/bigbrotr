-- ============================================================================
-- BigBrotr Database Initialization Script
-- ============================================================================
-- File: 00_extensions.sql
-- Description: PostgreSQL extensions required by the system
-- Dependencies: None
-- ============================================================================

-- Extension: btree_gin
-- Purpose: Enables GIN (Generalized Inverted Index) support for btree-comparable types
-- Usage: Required for efficient array containment queries on events.tagvalues column
-- Note: Powers the idx_events_tagvalues index for fast tag-based event filtering
CREATE EXTENSION IF NOT EXISTS "btree_gin";

-- Extension: pgcrypto
-- Purpose: Provides cryptographic functions including digest() for SHA-256 hashing
-- Usage: Required for compute_nip11_hash() and compute_nip66_hash() functions
-- Note: Used for content-based deduplication of NIP-11 and NIP-66 records
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- EXTENSIONS LOADED
-- ============================================================================