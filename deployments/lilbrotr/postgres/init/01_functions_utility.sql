/*
 * Brotr - 01_functions_utility.sql
 *
 * Utility functions that must be created before tables, because they are
 * called by CRUD functions in 05_functions_crud.sql.
 *
 * Dependencies: 00_extensions.sql
 */

/*
 * tags_to_tagvalues(JSONB) -> TEXT[]
 *
 * Extracts key-prefixed tag values from a Nostr event's JSONB tag array,
 * keeping only tags with single-character keys (per NIP-01 convention:
 * "e", "p", "t", etc.). Multi-character keys like "relay" are excluded
 * because they are non-standard for filtering purposes.
 *
 * Each value is prefixed with its tag key and a colon separator, enabling
 * GIN queries that discriminate between tag types (e.g., "e:abc" vs "p:abc").
 * The original tag order is preserved in the resulting array so downstream
 * analytics can reconstruct "first"/"last" semantics for single-char tags.
 *
 * Only the first tag value (tag[1]) is retained. Additional tag fields such
 * as relay hints or markers are intentionally discarded.
 *
 * Called by event_insert() to compute tagvalues at insert time. The result
 * is indexed with GIN for efficient lookups (WHERE tagvalues @> ARRAY['e:<hex-id>']).
 *
 * Example:
 *   Input:  [["e", "abc123"], ["p", "def456"], ["relay", "wss://..."]]
 *   Output: ARRAY['e:abc123', 'p:def456']
 *   Input:  [] (empty array)
 *   Output: '{}' (empty TEXT array, never NULL for non-NULL input)
 */
CREATE OR REPLACE FUNCTION tags_to_tagvalues(JSONB)
RETURNS TEXT []
LANGUAGE SQL
IMMUTABLE
RETURNS NULL ON NULL INPUT
AS $$
    SELECT COALESCE(
        array_agg((t.tag ->> 0) || ':' || (t.tag ->> 1) ORDER BY t.ord),
        '{}'::TEXT[]
    )
    FROM jsonb_array_elements($1) WITH ORDINALITY AS t(tag, ord)
    WHERE length(t.tag ->> 0) = 1
$$;


/*
 * event_d_tag(tags JSONB, tagvalues TEXT[]) -> TEXT
 *
 * Return the first ``d`` tag value for an addressable event. Prefers the
 * exact JSONB tag array when present, otherwise falls back to ordered
 * ``tagvalues``. Returns the empty string when no ``d`` tag exists.
 */
CREATE OR REPLACE FUNCTION event_d_tag(
    tags JSONB,
    tagvalues TEXT[]
)
RETURNS TEXT
LANGUAGE SQL
IMMUTABLE
AS $$
    SELECT COALESCE(
        (
            SELECT t.tag ->> 1
            FROM jsonb_array_elements(tags) WITH ORDINALITY AS t(tag, ord)
            WHERE t.tag ->> 0 = 'd'
            ORDER BY ord
            LIMIT 1
        ),
        (
            SELECT substring(t.tv FROM 3)
            FROM unnest(tagvalues) WITH ORDINALITY AS t(tv, ord)
            WHERE t.tv LIKE 'd:%'
            ORDER BY ord
            LIMIT 1
        ),
        ''
    )
$$;


/*
 * normalize_event_address(address TEXT) -> TEXT
 *
 * Canonicalize an addressable event coordinate (``kind:pubkey:d_tag``).
 * The pubkey portion is lowercased; the ``d_tag`` suffix is preserved as-is.
 *
 * Returns ``NULL`` when the input does not match the expected shape or does
 * not target an addressable kind (30000-39999).
 */
CREATE OR REPLACE FUNCTION normalize_event_address(address TEXT)
RETURNS TEXT
LANGUAGE plpgsql
IMMUTABLE
RETURNS NULL ON NULL INPUT
AS $$
DECLARE
    v_kind_text TEXT;
    v_kind INTEGER;
    v_remainder TEXT;
    v_pubkey TEXT;
    v_d_tag TEXT;
    v_pos1 INTEGER;
    v_pos2 INTEGER;
BEGIN
    v_pos1 := POSITION(':' IN address);
    IF v_pos1 = 0 THEN
        RETURN NULL;
    END IF;

    v_kind_text := substring(address FROM 1 FOR v_pos1 - 1);
    IF v_kind_text !~ '^[0-9]{1,5}$' THEN
        RETURN NULL;
    END IF;

    v_kind := v_kind_text::INTEGER;
    IF v_kind < 30000 OR v_kind > 39999 THEN
        RETURN NULL;
    END IF;

    v_remainder := substring(address FROM v_pos1 + 1);
    v_pos2 := POSITION(':' IN v_remainder);
    IF v_pos2 = 0 THEN
        RETURN NULL;
    END IF;

    v_pubkey := substring(v_remainder FROM 1 FOR v_pos2 - 1);
    IF v_pubkey !~* '^[0-9a-f]{64}$' THEN
        RETURN NULL;
    END IF;

    v_d_tag := substring(v_remainder FROM v_pos2 + 1);

    RETURN v_kind::TEXT || ':' || LOWER(v_pubkey) || ':' || v_d_tag;
END;
$$;


/*
 * event_address(kind INTEGER, pubkey BYTEA, tags JSONB, tagvalues TEXT[]) -> TEXT
 *
 * Construct the canonical addressable event coordinate for a stored event row.
 * Returns ``NULL`` when ``kind`` is not addressable.
 */
CREATE OR REPLACE FUNCTION event_address(
    kind INTEGER,
    pubkey BYTEA,
    tags JSONB,
    tagvalues TEXT[]
)
RETURNS TEXT
LANGUAGE SQL
IMMUTABLE
AS $$
    SELECT CASE
        WHEN kind BETWEEN 30000 AND 39999
            THEN kind::TEXT || ':' || LOWER(ENCODE(pubkey, 'hex')) || ':' || event_d_tag(tags, tagvalues)
        ELSE NULL
    END
$$;
