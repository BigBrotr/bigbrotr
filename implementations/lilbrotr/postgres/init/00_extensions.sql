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
CREATE EXTENSION IF NOT EXISTS btree_gin;

-- ============================================================================
-- EXTENSIONS LOADED
-- ============================================================================
