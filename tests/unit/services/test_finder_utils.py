"""
Unit tests for services.finder.utils module.

Tests:
- extract_relays_from_rows: relay URL extraction from r-tags, kind 2 content,
  kind 3 JSON contact list, deduplication, empty/invalid input
"""

from bigbrotr.models.constants import EventKind
from bigbrotr.services.finder.utils import extract_relays_from_rows


# ============================================================================
# extract_relays_from_rows Tests
# ============================================================================


class TestExtractRelaysFromRows:
    """Tests for extract_relays_from_rows function."""

    def test_extract_from_r_tags(self) -> None:
        """Test relay extraction from r-tag entries."""
        rows = [
            {
                "kind": 1,
                "tags": [["r", "wss://relay1.example.com"], ["r", "wss://relay2.example.com"]],
                "content": "",
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_rows(rows)

        assert len(relays) == 2
        urls = set(relays.keys())
        assert any("relay1.example.com" in u for u in urls)
        assert any("relay2.example.com" in u for u in urls)

    def test_extract_from_kind2_content(self) -> None:
        """Test relay extraction from kind 2 (recommend relay) content."""
        rows = [
            {
                "kind": EventKind.RECOMMEND_RELAY,
                "tags": [],
                "content": "wss://recommended.relay.com",
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_rows(rows)

        assert len(relays) == 1
        assert any("recommended.relay.com" in u for u in relays)

    def test_extract_from_kind3_json_content(self) -> None:
        """Test relay extraction from kind 3 (contacts) JSON content."""
        import json

        relay_map = {
            "wss://contact1.relay.com": {"read": True, "write": True},
            "wss://contact2.relay.com": {"read": True, "write": False},
        }
        rows = [
            {
                "kind": EventKind.CONTACTS,
                "tags": [],
                "content": json.dumps(relay_map),
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_rows(rows)

        assert len(relays) == 2
        urls = set(relays.keys())
        assert any("contact1.relay.com" in u for u in urls)
        assert any("contact2.relay.com" in u for u in urls)

    def test_empty_rows(self) -> None:
        """Test with empty input list."""
        relays = extract_relays_from_rows([])
        assert relays == {}

    def test_no_tags_no_content(self) -> None:
        """Test rows with no tags and empty content produce no relays."""
        rows = [
            {
                "kind": 1,
                "tags": [],
                "content": "",
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_rows(rows)
        assert relays == {}

    def test_none_tags(self) -> None:
        """Test rows with None tags produce no relays."""
        rows = [
            {
                "kind": 1,
                "tags": None,
                "content": "",
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_rows(rows)
        assert relays == {}

    def test_invalid_r_tag_values(self) -> None:
        """Test invalid URLs in r-tags are skipped."""
        rows = [
            {
                "kind": 1,
                "tags": [
                    ["r", "not-a-valid-url"],
                    ["r", "http://wrong-scheme.com"],
                    ["r", ""],
                ],
                "content": "",
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_rows(rows)
        assert relays == {}

    def test_r_tag_too_short(self) -> None:
        """Test r-tags with fewer than 2 elements are skipped."""
        rows = [
            {
                "kind": 1,
                "tags": [["r"], ["p", "some_pubkey"]],
                "content": "",
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_rows(rows)
        assert relays == {}

    def test_non_r_tags_ignored(self) -> None:
        """Test that non-r tag entries are ignored."""
        rows = [
            {
                "kind": 1,
                "tags": [["p", "wss://not-an-r-tag.com"], ["e", "a" * 64]],
                "content": "",
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_rows(rows)
        assert relays == {}

    def test_deduplication(self) -> None:
        """Test that duplicate relay URLs are deduplicated."""
        rows = [
            {
                "kind": 1,
                "tags": [["r", "wss://relay.example.com"], ["r", "wss://relay.example.com"]],
                "content": "",
                "seen_at": 1700000000,
            },
            {
                "kind": 1,
                "tags": [["r", "wss://relay.example.com"]],
                "content": "",
                "seen_at": 1700000000,
            },
        ]

        relays = extract_relays_from_rows(rows)
        assert len(relays) == 1

    def test_kind2_empty_content_skipped(self) -> None:
        """Test kind 2 with empty content produces no relays."""
        rows = [
            {
                "kind": EventKind.RECOMMEND_RELAY,
                "tags": [],
                "content": "",
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_rows(rows)
        assert relays == {}

    def test_kind2_whitespace_content(self) -> None:
        """Test kind 2 with whitespace-padded content."""
        rows = [
            {
                "kind": EventKind.RECOMMEND_RELAY,
                "tags": [],
                "content": "  wss://padded.relay.com  ",
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_rows(rows)
        assert len(relays) == 1

    def test_kind3_invalid_json(self) -> None:
        """Test kind 3 with invalid JSON content is handled gracefully."""
        rows = [
            {
                "kind": EventKind.CONTACTS,
                "tags": [],
                "content": "not valid json",
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_rows(rows)
        assert relays == {}

    def test_kind3_non_dict_json(self) -> None:
        """Test kind 3 with non-dict JSON (e.g., list) produces no relays."""
        import json

        rows = [
            {
                "kind": EventKind.CONTACTS,
                "tags": [],
                "content": json.dumps(["wss://relay.example.com"]),
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_rows(rows)
        assert relays == {}

    def test_kind3_with_invalid_urls_in_keys(self) -> None:
        """Test kind 3 JSON with invalid URLs as keys skips them."""
        import json

        relay_map = {
            "not-a-url": {"read": True},
            "wss://valid.relay.com": {"read": True},
        }
        rows = [
            {
                "kind": EventKind.CONTACTS,
                "tags": [],
                "content": json.dumps(relay_map),
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_rows(rows)
        assert len(relays) == 1
        assert any("valid.relay.com" in u for u in relays)

    def test_mixed_sources(self) -> None:
        """Test extraction from multiple sources in the same batch."""
        import json

        rows = [
            {
                "kind": 1,
                "tags": [["r", "wss://from-tag.relay.com"]],
                "content": "",
                "seen_at": 1700000000,
            },
            {
                "kind": EventKind.RECOMMEND_RELAY,
                "tags": [],
                "content": "wss://from-kind2.relay.com",
                "seen_at": 1700000000,
            },
            {
                "kind": EventKind.CONTACTS,
                "tags": [],
                "content": json.dumps({"wss://from-kind3.relay.com": {}}),
                "seen_at": 1700000000,
            },
        ]

        relays = extract_relays_from_rows(rows)

        assert len(relays) == 3
        urls = set(relays.keys())
        assert any("from-tag.relay.com" in u for u in urls)
        assert any("from-kind2.relay.com" in u for u in urls)
        assert any("from-kind3.relay.com" in u for u in urls)

    def test_kind3_empty_content_skipped(self) -> None:
        """Test kind 3 with empty content produces no relays."""
        rows = [
            {
                "kind": EventKind.CONTACTS,
                "tags": [],
                "content": "",
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_rows(rows)
        assert relays == {}

    def test_tag_not_list(self) -> None:
        """Test non-list tag entries are ignored."""
        rows = [
            {
                "kind": 1,
                "tags": ["not-a-list", 42],
                "content": "",
                "seen_at": 1700000000,
            }
        ]

        relays = extract_relays_from_rows(rows)
        assert relays == {}
