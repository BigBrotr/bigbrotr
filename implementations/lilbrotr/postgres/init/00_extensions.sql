-- ============================================================================
-- LilBrotr Database Initialization Script
-- ============================================================================
-- File: 00_extensions.sql
-- Description: PostgreSQL extensions required by the system
-- Note: LilBrotr is a lightweight implementation that does not store tags/content
-- Dependencies: None
-- ============================================================================

-- Extension: btree_gin
-- Purpose: Enables GIN (Generalized Inverted Index) support for btree-comparable types
-- Note: LilBrotr does not use tagvalues index, but btree_gin may be useful for future features
CREATE EXTENSION IF NOT EXISTS "btree_gin";

-- Extension: pgcrypto
-- Purpose: Provides cryptographic functions including digest() for SHA-256 hashing
-- Usage: Required for compute_nip11_hash() and compute_nip66_hash() functions
-- Note: Used for content-based deduplication of NIP-11 and NIP-66 records
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- EXTENSIONS LOADED
-- ============================================================================