-- ============================================================================
-- LilBrotr Database Initialization Script
-- ============================================================================
-- File: 01_functions_utility.sql
-- Description: Utility Functions
-- Dependencies: 00_extensions.sql
-- ============================================================================

-- Function: tags_to_tagvalues
-- Description: Extracts tag values from single-letter tags for GIN indexing
-- Input: JSONB array of tags [[tag_name, value, ...], ...]
-- Output: TEXT[] of values from single-letter tags
-- Note: LilBrotr computes tagvalues at insert time (not a generated column)
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

COMMENT ON FUNCTION tags_to_tagvalues(JSONB) IS
'Extracts values from single-letter tags for GIN indexing';

-- ============================================================================
-- UTILITY FUNCTIONS CREATED
-- ============================================================================
