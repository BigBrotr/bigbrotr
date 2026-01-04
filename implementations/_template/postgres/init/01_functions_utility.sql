-- ============================================================================
-- BigBrotr Implementation Template - Utility Functions
-- ============================================================================
-- File: 01_functions_utility.sql
-- Purpose: Utility functions required before table creation
-- Dependencies: 00_extensions.sql
-- Customization: None - this function is mandatory for tagvalues column
-- ============================================================================

-- Function: tags_to_tagvalues
-- Description: Extracts single-character tag keys and their values from JSONB array
-- Purpose: Enables efficient GIN indexing on Nostr event tags
-- Note: Used by events.tagvalues generated column (if using full storage mode)
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
-- UTILITY FUNCTIONS SUMMARY
-- ============================================================================
-- tags_to_tagvalues : Extract filterable tag values from Nostr event tags
-- ============================================================================
