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

-- ============================================================================
-- EXTENSIONS SUMMARY
-- ============================================================================
-- btree_gin  : Tag-based event filtering with GIN indexes
-- ============================================================================
