/*
 * LilBrotr - 01_functions_utility.sql
 *
 * Utility functions for tag value extraction. Unlike BigBrotr, LilBrotr
 * does not use a generated column; instead, event_insert() calls this
 * function at insert time and stores the result in the tagvalues column.
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
 * Called by event_insert() to compute tagvalues at insert time, since
 * LilBrotr does not store the full tags JSONB column.
 *
 * Example:
 *   Input:  [["e", "abc123"], ["p", "def456"], ["relay", "wss://..."]]
 *   Output: ARRAY['abc123', 'def456']
 */
CREATE OR REPLACE FUNCTION tags_to_tagvalues(JSONB)
RETURNS TEXT []
LANGUAGE SQL
IMMUTABLE
RETURNS NULL ON NULL INPUT
SECURITY INVOKER
AS 'SELECT COALESCE(array_agg(t->>1), ARRAY[]::text[]) FROM (SELECT jsonb_array_elements($1) AS t)s WHERE length(t->>0) = 1;';
