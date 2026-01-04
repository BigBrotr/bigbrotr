-- ============================================================================
-- LilBrotr Database Initialization Script
-- ============================================================================
-- File: 01_functions_utility.sql
-- Description: Utility Functions
-- Dependencies: 00_extensions.sql
-- ============================================================================

-- Function: tags_to_tagvalues
-- Description: Extracts single-character tag keys and their values from JSONB array
-- Purpose: Enables efficient GIN indexing on Nostr event tags
-- Note: LilBrotr computes tagvalues at insert time (not a generated column)
--
-- Example Input:  [["e", "abc123"], ["p", "def456"], ["relay", "wss://..."]]
-- Example Output: ARRAY['abc123', 'def456']
-- Note: "relay" is excluded because key length > 1
CREATE OR REPLACE FUNCTION tags_to_tagvalues(JSONB)
RETURNS TEXT[]
LANGUAGE SQL
IMMUTABLE
RETURNS NULL ON NULL INPUT
AS 'SELECT array_agg(t->>1) FROM (SELECT jsonb_array_elements($1) AS t)s WHERE length(t->>0) = 1;';

-- ============================================================================
-- UTILITY FUNCTIONS CREATED
-- ============================================================================
