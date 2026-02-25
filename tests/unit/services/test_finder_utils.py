"""
Unit tests for services.finder.utils module.

Tests:
- extract_urls_from_response: URL extraction from API JSON responses
- extract_relays_from_rows: relay URL extraction from event tagvalues
"""

from bigbrotr.services.finder.utils import extract_relays_from_rows, extract_urls_from_response


# ============================================================================
# extract_urls_from_response Tests
# ============================================================================


class TestExtractUrlsFromResponse:
    """Tests for extract_urls_from_response function (JMESPath-based)."""

    # -- Default expression: [*] (flat string list) --------------------------

    def test_flat_string_list_default(self) -> None:
        """Default expression extracts all items from a flat list."""
        data = ["wss://r1.com", "wss://r2.com"]
        assert extract_urls_from_response(data) == ["wss://r1.com", "wss://r2.com"]

    def test_empty_list(self) -> None:
        assert extract_urls_from_response([]) == []

    def test_non_string_items_filtered(self) -> None:
        """Non-string items in the JMESPath result are silently dropped."""
        data = ["wss://r.com", 42, None, True]
        assert extract_urls_from_response(data) == ["wss://r.com"]

    # -- Nested path expressions ---------------------------------------------

    def test_nested_path(self) -> None:
        data = {"data": {"relays": ["wss://r1.com", "wss://r2.com"]}}
        result = extract_urls_from_response(data, "data.relays")
        assert result == ["wss://r1.com", "wss://r2.com"]

    def test_single_key_path(self) -> None:
        data = {"relays": ["wss://r1.com"]}
        assert extract_urls_from_response(data, "relays") == ["wss://r1.com"]

    def test_nonexistent_path_returns_empty(self) -> None:
        data = {"other": ["wss://r1.com"]}
        assert extract_urls_from_response(data, "relays") == []

    # -- Object field extraction: [*].key ------------------------------------

    def test_extract_field_from_objects(self) -> None:
        data = [{"url": "wss://r1.com"}, {"url": "wss://r2.com"}]
        assert extract_urls_from_response(data, "[*].url") == ["wss://r1.com", "wss://r2.com"]

    def test_nested_path_then_field(self) -> None:
        data = {"data": [{"addr": "wss://r1.com"}, {"addr": "wss://r2.com"}]}
        result = extract_urls_from_response(data, "data[*].addr")
        assert result == ["wss://r1.com", "wss://r2.com"]

    # -- Dict keys: keys(@) -------------------------------------------------

    def test_keys_extraction(self) -> None:
        data = {"wss://r1.com": {"info": "..."}, "wss://r2.com": {}}
        result = extract_urls_from_response(data, "keys(@)")
        assert set(result) == {"wss://r1.com", "wss://r2.com"}

    def test_nested_keys_extraction(self) -> None:
        data = {"data": {"wss://r1.com": {}}}
        result = extract_urls_from_response(data, "keys(data)")
        assert result == ["wss://r1.com"]

    # -- Edge cases ----------------------------------------------------------

    def test_none_data(self) -> None:
        assert extract_urls_from_response(None) == []

    def test_scalar_data(self) -> None:
        assert extract_urls_from_response(42) == []
        assert extract_urls_from_response("wss://r1.com") == []

    def test_expression_returns_non_list(self) -> None:
        """Expression that evaluates to a scalar returns empty."""
        data = {"count": 5}
        assert extract_urls_from_response(data, "count") == []

    def test_empty_dict_keys(self) -> None:
        assert extract_urls_from_response({}, "keys(@)") == []


# ============================================================================
# extract_relays_from_rows Tests
# ============================================================================


class TestExtractRelaysFromRows:
    """Tests for extract_relays_from_rows function."""

    def test_extracts_valid_relay_urls(self) -> None:
        """Test relay URL extraction from tagvalues."""
        rows = [
            {
                "tagvalues": [
                    "wss://relay1.example.com",
                    "wss://relay2.example.com",
                ],
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_rows(rows)

        assert len(relays) == 2
        urls = set(relays.keys())
        assert any("relay1.example.com" in u for u in urls)
        assert any("relay2.example.com" in u for u in urls)

    def test_ignores_non_url_values(self) -> None:
        """Test that hex IDs, pubkeys, hashtags etc. are filtered out."""
        rows = [
            {
                "tagvalues": [
                    "a" * 64,  # hex event ID
                    "b" * 64,  # hex pubkey
                    "bitcoin",  # hashtag
                    "nostr",  # hashtag
                    "wss://valid.relay.com",
                ],
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_rows(rows)

        assert len(relays) == 1
        assert any("valid.relay.com" in u for u in relays)

    def test_empty_rows(self) -> None:
        """Test with empty input list."""
        relays = extract_relays_from_rows([])
        assert relays == {}

    def test_none_tagvalues(self) -> None:
        """Test rows with None tagvalues produce no relays."""
        rows = [{"tagvalues": None, "seen_at": 1700000000}]

        relays = extract_relays_from_rows(rows)
        assert relays == {}

    def test_empty_tagvalues(self) -> None:
        """Test rows with empty tagvalues list produce no relays."""
        rows = [{"tagvalues": [], "seen_at": 1700000000}]

        relays = extract_relays_from_rows(rows)
        assert relays == {}

    def test_missing_tagvalues_key(self) -> None:
        """Test rows missing the tagvalues key produce no relays."""
        rows = [{"seen_at": 1700000000}]

        relays = extract_relays_from_rows(rows)
        assert relays == {}

    def test_invalid_urls_skipped(self) -> None:
        """Test invalid URLs in tagvalues are skipped."""
        rows = [
            {
                "tagvalues": [
                    "not-a-valid-url",
                    "http://wrong-scheme.com",
                    "",
                ],
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_rows(rows)
        assert relays == {}

    def test_deduplication_within_row(self) -> None:
        """Test duplicate relay URLs within a row are deduplicated."""
        rows = [
            {
                "tagvalues": [
                    "wss://relay.example.com",
                    "wss://relay.example.com",
                ],
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_rows(rows)
        assert len(relays) == 1

    def test_deduplication_across_rows(self) -> None:
        """Test duplicate relay URLs across rows are deduplicated."""
        rows = [
            {"tagvalues": ["wss://relay.example.com"], "seen_at": 1700000000},
            {"tagvalues": ["wss://relay.example.com"], "seen_at": 1700000001},
        ]

        relays = extract_relays_from_rows(rows)
        assert len(relays) == 1

    def test_mixed_valid_and_invalid(self) -> None:
        """Test batch with mixed valid relay URLs and non-URL values."""
        rows = [
            {
                "tagvalues": ["wss://good.relay.com", "a" * 64],
                "seen_at": 1700000000,
            },
            {
                "tagvalues": ["bitcoin", "wss://another.relay.com"],
                "seen_at": 1700000001,
            },
            {
                "tagvalues": None,
                "seen_at": 1700000002,
            },
        ]

        relays = extract_relays_from_rows(rows)

        assert len(relays) == 2
        urls = set(relays.keys())
        assert any("good.relay.com" in u for u in urls)
        assert any("another.relay.com" in u for u in urls)

    def test_ws_scheme_accepted(self) -> None:
        """Test that ws:// relay URLs are also accepted."""
        rows = [
            {
                "tagvalues": ["ws://clearnet.relay.com"],
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_rows(rows)
        assert len(relays) == 1
