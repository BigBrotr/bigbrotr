-- ============================================================================
-- BigBrotr Database Initialization Script
-- ============================================================================
-- File: 00_extensions.sql
-- Description: PostgreSQL extensions required by the system
-- Dependencies: None
-- ============================================================================

-- Enable GIN indexing on btree-compatible types (used for JSONB + scalar indexes)
CREATE EXTENSION IF NOT EXISTS "btree_gin";

-- ============================================================================
-- EXTENSIONS LOADED
-- ============================================================================