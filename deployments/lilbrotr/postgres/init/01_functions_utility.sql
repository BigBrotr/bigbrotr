/*
 * LilBrotr - 01_functions_utility.sql
 *
 * Utility functions that must be created before tables, because they are
 * called by CRUD functions in 03_functions_crud.sql.
 *
 * Dependencies: 00_extensions.sql
 */

/*
 * tags_to_tagvalues(JSONB) -> TEXT[]
 *
 * Extracts tag values from a Nostr event's JSONB tag array, keeping only
 * values from single-character tag keys (per NIP-01 convention: "e", "p",
 * "t", etc.). Multi-character keys like "relay" are excluded because they
 * are non-standard for filtering purposes.
 *
 * Called by event_insert() to compute tagvalues at insert time. The result
 * is indexed with GIN for efficient lookups (WHERE tagvalues @> ARRAY['<hex-id>']).
 *
 * Example:
 *   Input:  [["e", "abc123"], ["p", "def456"], ["relay", "wss://..."]]
 *   Output: ARRAY['abc123', 'def456']
 *   Input:  [] (empty array)
 *   Output: '{}' (empty TEXT array, never NULL for non-NULL input)
 */
CREATE OR REPLACE FUNCTION tags_to_tagvalues(JSONB)
RETURNS TEXT []
LANGUAGE SQL
IMMUTABLE
RETURNS NULL ON NULL INPUT
AS 'SELECT COALESCE(array_agg(t->>1), ''{}''::TEXT[]) FROM (SELECT jsonb_array_elements($1) AS t)s WHERE length(t->>0) = 1;';
