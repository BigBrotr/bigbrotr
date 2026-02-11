/*
 * Template - 00_extensions.sql
 *
 * PostgreSQL extensions required for BigBrotr functionality.
 * This script runs first during database initialization.
 *
 * Dependencies: None
 */

-- Enables GIN index support for btree-comparable types (TEXT[], INTEGER[], etc.).
-- Required for the idx_event_tagvalues GIN index, which powers fast
-- array containment queries (WHERE tagvalues @> ARRAY['value']) on the event table.
CREATE EXTENSION IF NOT EXISTS btree_gin;
