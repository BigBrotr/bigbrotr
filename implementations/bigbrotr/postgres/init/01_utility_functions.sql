-- ============================================================================
-- BigBrotr Database Initialization Script
-- ============================================================================
-- File: 01_utility_functions.sql
-- Description: Utility functions for tag indexing and hash computation
-- Dependencies: 00_extensions.sql
-- ============================================================================

-- Function: tags_to_tagvalues
-- Description: Extracts single-character tag keys and their values from JSONB array
-- Purpose: Enables efficient GIN indexing on Nostr event tags
-- Parameters: JSONB array of tags in format [["key", "value"], ...]
-- Returns: TEXT[] of tag values where key length = 1
CREATE OR REPLACE FUNCTION tags_to_tagvalues(p_tags JSONB)
RETURNS TEXT[]
LANGUAGE plpgsql
IMMUTABLE
RETURNS NULL ON NULL INPUT
AS $$
BEGIN
    RETURN (
        SELECT array_agg(tag_element->>1)
        FROM jsonb_array_elements(p_tags) AS tag_element
        WHERE length(tag_element->>0) = 1
    );
END;
$$;

COMMENT ON FUNCTION tags_to_tagvalues(JSONB) IS 'Extracts single-character tag keys and values from JSONB array for efficient GIN indexing';

-- ============================================================================
-- UTILITY FUNCTIONS CREATED
-- ============================================================================
