/*
 * Template - 01_functions_utility.sql
 *
 * Utility functions that must be created before tables. Required if the
 * events table uses a generated column referencing tags_to_tagvalues().
 * Also used at insert time in lightweight schemas.
 *
 * Dependencies: 00_extensions.sql
 * Customization: None required -- this function is mandatory.
 */

/*
 * tags_to_tagvalues(JSONB) -> TEXT[]
 *
 * Extracts tag values from a Nostr event's JSONB tag array, keeping only
 * values from single-character tag keys (per NIP-01 convention: "e", "p",
 * "t", etc.). Multi-character keys like "relay" are excluded because they
 * are non-standard for filtering purposes.
 *
 * Example:
 *   Input:  [["e", "abc123"], ["p", "def456"], ["relay", "wss://..."]]
 *   Output: ARRAY['abc123', 'def456']
 */
CREATE OR REPLACE FUNCTION tags_to_tagvalues(JSONB)
RETURNS TEXT[]
LANGUAGE SQL
IMMUTABLE
RETURNS NULL ON NULL INPUT
AS 'SELECT array_agg(t->>1) FROM (SELECT jsonb_array_elements($1) AS t)s WHERE length(t->>0) = 1;';
