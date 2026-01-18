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
CREATE EXTENSION IF NOT EXISTS btree_gin;

-- Extension: pgcrypto
-- Purpose: Provides cryptographic functions including digest() for SHA-256 hashing
-- Usage: Required for metadata_insert() and relay_metadata_insert_cascade() functions
-- Note: Used for content-based deduplication of metadata records
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Extension: pg_stat_statements
-- Purpose: Track execution statistics of SQL statements for performance analysis
-- Usage: Query pg_stat_statements view to identify slow queries and optimization targets
-- Note: Requires shared_preload_libraries = 'pg_stat_statements' in postgresql.conf
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- ============================================================================
-- EXTENSIONS LOADED
-- ============================================================================
