/*
 * LilBrotr - 00_extensions.sql
 *
 * PostgreSQL extensions required for LilBrotr functionality.
 * LilBrotr is a lightweight implementation that omits tags, content, and sig
 * columns from the events table for reduced disk usage (~60% savings).
 *
 * Dependencies: None
 */

-- Enables GIN index support for btree-comparable types (TEXT[], INTEGER[], etc.).
-- Used for the idx_events_tagvalues GIN index, which supports array containment
-- queries on the tagvalues column (computed at insert time in LilBrotr).
CREATE EXTENSION IF NOT EXISTS btree_gin;
