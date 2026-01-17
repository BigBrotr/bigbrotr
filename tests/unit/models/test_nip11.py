"""
Unit tests for models.nip11 module.

Tests:
- Nip11 construction and property accessors
- Parsing and validation of all NIP-11 fields
- Empty/invalid data handling
- to_relay_metadata() conversion
- Nip11.fetch() async HTTP client
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models import Metadata, Nip11, Relay, RelayMetadata
from models.nip11 import Nip11FetchError
from models.relay_metadata import MetadataType


@pytest.fixture
def relay():
    """Create a test relay."""
    return Relay(raw_url="wss://relay.example.com", discovered_at=1234567890)


@pytest.fixture
def complete_nip11_data():
    """Complete NIP-11 data with all standard fields.

    Includes all fields defined in NIP-11 specification:
    - Basic info: name, description, banner, icon, pubkey, self, contact
    - Software: software, version
    - Policies: privacy_policy, terms_of_service, posting_policy, payments_url
    - Technical: supported_nips, limitation, retention
    - Geographic: relay_countries, language_tags, tags
    - Payment: fees (admission, subscription, publication)
    """
    return {
        "name": "Test Relay",
        "description": "A test relay for unit tests",
        "banner": "https://example.com/banner.jpg",
        "icon": "https://example.com/icon.jpg",
        "pubkey": "a" * 64,
        "self": "b" * 64,
        "contact": "admin@example.com",
        "supported_nips": [1, 11, 42, 65],
        "software": "nostr-rs-relay",
        "version": "0.8.0",
        "privacy_policy": "https://example.com/privacy",
        "terms_of_service": "https://example.com/tos",
        "posting_policy": "https://example.com/posting",
        "payments_url": "https://example.com/pay",
        "limitation": {
            "max_message_length": 65535,
            "max_subscriptions": 20,
            "max_limit": 5000,
            "max_subid_length": 256,
            "max_event_tags": 2000,
            "max_content_length": 65535,
            "min_pow_difficulty": 0,
            "auth_required": False,
            "payment_required": True,
            "restricted_writes": True,
            "created_at_lower_limit": 0,
            "created_at_upper_limit": 2147483647,
            "default_limit": 100,
        },
        "retention": [
            {"kinds": [0, 3], "time": None},
            {"kinds": [[10000, 19999]], "time": 86400},
            {"kinds": [[30000, 39999]], "count": 100},
        ],
        "relay_countries": ["US", "CA"],
        "language_tags": ["en", "en-US"],
        "tags": ["sfw-only", "bitcoin-only"],
        "fees": {
            "admission": [{"amount": 1000, "unit": "sats"}],
            "subscription": [{"amount": 5000, "unit": "sats", "period": 2628003}],
            "publication": [{"kinds": [4], "amount": 100, "unit": "msats"}],
        },
    }


@pytest.fixture
def nip11(relay, complete_nip11_data):
    """Nip11 instance with complete data."""
    return Nip11(relay=relay, metadata=Metadata(complete_nip11_data), generated_at=1234567890)


class TestConstruction:
    """Test Nip11 construction."""

    def test_with_metadata_object(self, relay, complete_nip11_data):
        """Construct with Metadata object."""
        metadata = Metadata(complete_nip11_data)
        nip11 = Nip11(relay=relay, metadata=metadata)
        assert nip11.metadata.data["name"] == "Test Relay"
        assert nip11.relay is relay

    def test_with_dict(self, relay, complete_nip11_data):
        """Construct with raw dict (converted internally)."""
        nip11 = Nip11(relay=relay, metadata=Metadata(complete_nip11_data))
        assert nip11.metadata.data["name"] == "Test Relay"

    def test_empty_metadata_raises_error(self, relay):
        """Empty metadata raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            Nip11(relay=relay, metadata=Metadata({}))

    def test_generated_at_default(self, relay):
        """generated_at defaults to current time."""
        nip11 = Nip11(relay=relay, metadata={"name": "Test"})
        assert nip11.generated_at > 0

    def test_generated_at_explicit(self, relay):
        """Explicit generated_at is preserved."""
        nip11 = Nip11(relay=relay, metadata={"name": "Test"}, generated_at=1000)
        assert nip11.generated_at == 1000


class TestBaseFields:
    """Test base string fields via metadata.data."""

    def test_all_base_fields(self, nip11):
        """Access all base string fields."""
        data = nip11.metadata.data
        assert data["name"] == "Test Relay"
        assert data["description"] == "A test relay for unit tests"
        assert data["banner"] == "https://example.com/banner.jpg"
        assert data["icon"] == "https://example.com/icon.jpg"
        assert data["pubkey"] == "a" * 64
        assert data["self"] == "b" * 64
        assert data["contact"] == "admin@example.com"
        assert data["software"] == "nostr-rs-relay"
        assert data["version"] == "0.8.0"
        assert data["privacy_policy"] == "https://example.com/privacy"
        assert data["terms_of_service"] == "https://example.com/tos"
        assert data["posting_policy"] == "https://example.com/posting"
        assert data["payments_url"] == "https://example.com/pay"

    def test_missing_optional_fields(self, relay):
        """Missing optional fields are None."""
        # Use minimal valid metadata (just name) to test other fields are None
        nip11 = Nip11(relay=relay, metadata=Metadata({"name": "Test"}))
        data = nip11.metadata.data
        assert data["name"] == "Test"
        assert data["description"] is None
        assert data["banner"] is None
        assert data["icon"] is None
        assert data["pubkey"] is None
        assert data["self"] is None
        assert data["contact"] is None
        assert data["software"] is None
        assert data["version"] is None
        assert data["privacy_policy"] is None
        assert data["terms_of_service"] is None
        assert data["posting_policy"] is None
        assert data["payments_url"] is None


class TestSupportedNips:
    """Test supported_nips parsing."""

    def test_valid_nips(self, nip11):
        """Valid NIPs are parsed."""
        assert nip11.metadata.data["supported_nips"] == [1, 11, 42, 65]

    def test_empty_list_becomes_none(self, relay):
        """Empty list becomes None."""
        nip11 = Nip11(relay=relay, metadata=Metadata({"name": "Test", "supported_nips": []}))
        assert nip11.metadata.data["supported_nips"] is None

    def test_filters_non_integers(self, relay):
        """Non-integer values are filtered."""
        data = {"supported_nips": [1, "two", 3, None, 4]}
        nip11 = Nip11(relay=relay, metadata=Metadata(data))
        assert nip11.metadata.data["supported_nips"] == [1, 3, 4]

    def test_invalid_type_becomes_none(self, relay):
        """Invalid type becomes None."""
        nip11 = Nip11(relay=relay, metadata=Metadata({"name": "Test", "supported_nips": "1,2,3"}))
        assert nip11.metadata.data["supported_nips"] is None


class TestLimitation:
    """Test limitation field parsing."""

    def test_all_limitation_fields(self, nip11):
        """All limitation fields are parsed."""
        limitation = nip11.metadata.data["limitation"]
        assert limitation is not None
        assert limitation["max_message_length"] == 65535
        assert limitation["max_subscriptions"] == 20
        assert limitation["max_limit"] == 5000
        assert limitation["max_subid_length"] == 256
        assert limitation["max_event_tags"] == 2000
        assert limitation["max_content_length"] == 65535
        assert limitation["min_pow_difficulty"] == 0
        assert limitation["auth_required"] is False
        assert limitation["payment_required"] is True
        assert limitation["restricted_writes"] is True
        assert limitation["created_at_lower_limit"] == 0
        assert limitation["created_at_upper_limit"] == 2147483647
        assert limitation["default_limit"] == 100

    def test_empty_limitation_has_skeleton(self, relay):
        """Empty limitation dict keeps skeleton with all keys set to None."""
        nip11 = Nip11(relay=relay, metadata=Metadata({"name": "Test", "limitation": {}}))
        limitation = nip11.metadata.data["limitation"]
        assert limitation is not None
        # All keys present with None values
        assert "max_message_length" in limitation
        assert "auth_required" in limitation
        assert all(v is None for v in limitation.values())

    def test_filters_invalid_types(self, relay):
        """Invalid types in limitation become None."""
        data = {
            "limitation": {
                "max_message_length": "large",  # Invalid: should be int
                "max_subscriptions": 100,  # Valid
                "auth_required": "yes",  # Invalid: should be bool
                "payment_required": True,  # Valid
            }
        }
        nip11 = Nip11(relay=relay, metadata=Metadata(data))
        limitation = nip11.metadata.data["limitation"]
        assert limitation is not None
        assert limitation["max_message_length"] is None  # Invalid type -> None
        assert limitation["max_subscriptions"] == 100
        assert limitation["auth_required"] is None  # Invalid type -> None
        assert limitation["payment_required"] is True


class TestRetention:
    """Test retention field parsing."""

    def test_valid_retention(self, nip11):
        """Valid retention entries are parsed."""
        retention = nip11.metadata.data["retention"]
        assert retention is not None
        assert len(retention) == 3
        assert retention[0]["kinds"] == [0, 3]
        assert "time" not in retention[0]  # None values are not included
        assert retention[1]["kinds"] == [[10000, 19999]]
        assert retention[1]["time"] == 86400
        assert retention[2]["kinds"] == [[30000, 39999]]
        assert retention[2]["count"] == 100
        assert "time" not in retention[2]

    def test_empty_retention_becomes_none(self, relay):
        """Empty retention list becomes None."""
        nip11 = Nip11(relay=relay, metadata=Metadata({"name": "Test", "retention": []}))
        assert nip11.metadata.data["retention"] is None

    def test_filters_non_dict_entries(self, relay):
        """Non-dict entries in retention are filtered."""
        data = {"retention": [{"kinds": [1], "time": 3600}, "invalid", None]}
        nip11 = Nip11(relay=relay, metadata=Metadata(data))
        assert nip11.metadata.data["retention"] is not None
        assert len(nip11.metadata.data["retention"]) == 1

    def test_filters_invalid_kind_values(self, relay):
        """Invalid kind values are filtered."""
        data = {
            "retention": [
                {"kinds": [1, "two", [3, 5], [6]], "time": 3600}  # [6] invalid (not 2-element)
            ]
        }
        nip11 = Nip11(relay=relay, metadata=Metadata(data))
        retention = nip11.metadata.data["retention"]
        assert retention is not None
        assert retention[0]["kinds"] == [1, [3, 5]]


class TestRelayCountries:
    """Test relay_countries field parsing."""

    def test_valid_countries(self, nip11):
        """Valid countries are parsed."""
        assert nip11.metadata.data["relay_countries"] == ["US", "CA"]

    def test_empty_list_becomes_none(self, relay):
        """Empty list becomes None."""
        nip11 = Nip11(relay=relay, metadata=Metadata({"name": "Test", "relay_countries": []}))
        assert nip11.metadata.data["relay_countries"] is None

    def test_filters_non_strings(self, relay):
        """Non-string values are filtered."""
        data = {"relay_countries": ["US", 123, "CA", None]}
        nip11 = Nip11(relay=relay, metadata=Metadata(data))
        assert nip11.metadata.data["relay_countries"] == ["US", "CA"]


class TestLanguageTagsAndTags:
    """Test language_tags and tags fields."""

    def test_language_tags(self, nip11):
        """Language tags are parsed."""
        assert nip11.metadata.data["language_tags"] == ["en", "en-US"]

    def test_tags(self, nip11):
        """Tags are parsed."""
        assert nip11.metadata.data["tags"] == ["sfw-only", "bitcoin-only"]

    def test_empty_lists_become_none(self, relay):
        """Empty lists become None."""
        nip11 = Nip11(
            relay=relay, metadata=Metadata({"name": "Test", "language_tags": [], "tags": []})
        )
        assert nip11.metadata.data["language_tags"] is None
        assert nip11.metadata.data["tags"] is None


class TestFees:
    """Test fees field parsing."""

    def test_all_fee_categories(self, nip11):
        """All fee categories are parsed."""
        fees = nip11.metadata.data["fees"]
        assert fees is not None
        assert fees["admission"] == [{"amount": 1000, "unit": "sats"}]
        assert fees["subscription"] == [{"amount": 5000, "unit": "sats", "period": 2628003}]
        assert fees["publication"] == [{"kinds": [4], "amount": 100, "unit": "msats"}]

    def test_empty_fees_has_skeleton(self, relay):
        """Empty fees dict returns skeleton with all keys set to None."""
        nip11 = Nip11(relay=relay, metadata=Metadata({"name": "Test", "fees": {}}))
        fees = nip11.metadata.data["fees"]
        assert fees is not None
        # Should have all keys with None values
        assert "admission" in fees
        assert "subscription" in fees
        assert "publication" in fees
        assert all(v is None for v in fees.values())

    def test_partial_fees(self, relay):
        """Partial fees are preserved."""
        data = {"fees": {"admission": [{"amount": 1000, "unit": "sats"}]}}
        nip11 = Nip11(relay=relay, metadata=Metadata(data))
        fees = nip11.metadata.data["fees"]
        assert fees is not None
        assert "admission" in fees
        assert fees.get("subscription") is None

    def test_filters_invalid_fee_entries(self, relay):
        """Invalid fee entries are filtered."""
        data = {"fees": {"admission": [{"amount": "free", "unit": "sats"}, {"amount": 100}]}}
        nip11 = Nip11(relay=relay, metadata=Metadata(data))
        # Both are partially valid (have at least one valid field)
        assert nip11.metadata.data["fees"] is not None


class TestMetadataDataAccess:
    """Test direct metadata.data access."""

    def test_access_parsed_data(self, nip11):
        """Access parsed data directly."""
        assert nip11.metadata.data["name"] == "Test Relay"
        assert nip11.metadata.data["supported_nips"] == [1, 11, 42, 65]

    def test_unknown_fields_filtered(self, relay):
        """Unknown fields are filtered out, all schema keys present."""
        data = {"name": "Test", "unknown_field": "value", "another_unknown": 123}
        nip11 = Nip11(relay=relay, metadata=Metadata(data))
        # Unknown fields are not included
        assert "unknown_field" not in nip11.metadata.data
        assert "another_unknown" not in nip11.metadata.data
        # Known field is present
        assert nip11.metadata.data["name"] == "Test"
        # All schema keys are present (with None for missing)
        assert "description" in nip11.metadata.data
        assert nip11.metadata.data["description"] is None


class TestToRelayMetadata:
    """Test to_relay_metadata() method."""

    def test_returns_relay_metadata(self, nip11):
        """Returns RelayMetadata instance."""
        rm = nip11.to_relay_metadata()
        assert isinstance(rm, RelayMetadata)

    def test_metadata_type_is_nip11(self, nip11):
        """Metadata type is NIP11."""
        rm = nip11.to_relay_metadata()
        assert rm.metadata_type == MetadataType.NIP11
        assert rm.metadata_type.value == "nip11"

    def test_preserves_relay(self, nip11):
        """Preserves relay reference."""
        rm = nip11.to_relay_metadata()
        assert rm.relay is nip11.relay

    def test_preserves_metadata(self, nip11):
        """Preserves metadata reference."""
        rm = nip11.to_relay_metadata()
        assert rm.metadata is nip11.metadata

    def test_preserves_generated_at(self, nip11):
        """Preserves generated_at timestamp."""
        rm = nip11.to_relay_metadata()
        assert rm.generated_at == 1234567890


class TestFetch:
    """Test fetch() class method."""

    @pytest.mark.asyncio
    async def test_success(self, relay):
        """Successful fetch returns Nip11 instance."""
        mock_content = AsyncMock()
        mock_content.read = AsyncMock(return_value=b'{"name": "Test Relay"}')

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"Content-Type": "application/nostr+json"}
        mock_response.content = mock_content
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("models.nip11.aiohttp.ClientSession", return_value=mock_session):
            result = await Nip11.fetch(relay)

        assert result is not None
        assert result.metadata.data["name"] == "Test Relay"
        assert result.relay is relay

    @pytest.mark.asyncio
    async def test_non_200_raises_error(self, relay):
        """Non-200 status raises Nip11FetchError."""
        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("models.nip11.aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(Nip11FetchError) as exc_info:
                await Nip11.fetch(relay)
            assert "HTTP 404" in str(exc_info.value.cause)
            assert exc_info.value.relay is relay

    @pytest.mark.asyncio
    async def test_connection_error_raises_fetch_error(self, relay):
        """Connection error raises Nip11FetchError."""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(side_effect=ConnectionError("Connection refused"))
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("models.nip11.aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(Nip11FetchError) as exc_info:
                await Nip11.fetch(relay)
            assert "Connection refused" in str(exc_info.value.cause)

    @pytest.mark.asyncio
    async def test_uses_https_for_wss(self, relay):
        """Uses HTTPS protocol for wss:// relays."""
        mock_content = AsyncMock()
        mock_content.read = AsyncMock(return_value=b'{"name": "Test"}')

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.content = mock_content
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_get = MagicMock(return_value=mock_response)
        mock_session.get = mock_get
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("models.nip11.aiohttp.ClientSession", return_value=mock_session):
            await Nip11.fetch(relay)
            assert mock_get.call_args[0][0].startswith("https://")

    @pytest.mark.asyncio
    async def test_uses_http_for_ws(self):
        """Uses HTTP protocol for ws:// relays (overlay networks)."""
        # Use a Tor relay since clearnet relays are forced to wss://
        ws_relay = Relay(raw_url="ws://abc123.onion", discovered_at=0)

        mock_content = AsyncMock()
        mock_content.read = AsyncMock(return_value=b'{"name": "Test"}')

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.content = mock_content
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_get = MagicMock(return_value=mock_response)
        mock_session.get = mock_get
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("models.nip11.aiohttp.ClientSession", return_value=mock_session):
            await Nip11.fetch(ws_relay)
            assert mock_get.call_args[0][0].startswith("http://")

    @pytest.mark.asyncio
    async def test_sends_accept_header(self, relay):
        """Sends Accept: application/nostr+json header."""
        mock_content = AsyncMock()
        mock_content.read = AsyncMock(return_value=b'{"name": "Test"}')

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.content = mock_content
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_get = MagicMock(return_value=mock_response)
        mock_session.get = mock_get
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("models.nip11.aiohttp.ClientSession", return_value=mock_session):
            await Nip11.fetch(relay)
            headers = mock_get.call_args[1]["headers"]
            assert headers["Accept"] == "application/nostr+json"

    @pytest.mark.asyncio
    async def test_valid_content_types_accepted(self, relay):
        """Valid JSON content types are accepted."""
        valid_types = [
            "application/nostr+json",
            "application/json",
            "application/nostr+json; charset=utf-8",
            "application/json; charset=utf-8",
        ]

        for content_type in valid_types:
            mock_content = AsyncMock()
            mock_content.read = AsyncMock(return_value=b'{"name": "Test"}')

            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.headers = {"Content-Type": content_type}
            mock_response.content = mock_content
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session = AsyncMock()
            mock_session.get = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            with patch("models.nip11.aiohttp.ClientSession", return_value=mock_session):
                result = await Nip11.fetch(relay)
                assert result is not None, f"Should accept Content-Type: {content_type}"

    @pytest.mark.asyncio
    async def test_invalid_content_types_rejected(self, relay):
        """Invalid content types are rejected."""
        invalid_types = [
            "text/html",
            "text/plain",
            "application/xml",
            "",
        ]

        for content_type in invalid_types:
            mock_content = AsyncMock()
            mock_content.read = AsyncMock(return_value=b'{"name": "Test"}')

            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.headers = {"Content-Type": content_type}
            mock_response.content = mock_content
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session = AsyncMock()
            mock_session.get = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            with patch("models.nip11.aiohttp.ClientSession", return_value=mock_session):
                with pytest.raises(Nip11FetchError) as exc_info:
                    await Nip11.fetch(relay)
                assert "Invalid Content-Type" in str(exc_info.value.cause)

    @pytest.mark.asyncio
    async def test_response_too_large_rejected(self, relay):
        """Response exceeding max_size is rejected."""
        large_body = b"x" * 100

        mock_content = AsyncMock()
        mock_content.read = AsyncMock(return_value=large_body)

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.content = mock_content
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("models.nip11.aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(Nip11FetchError) as exc_info:
                await Nip11.fetch(relay, max_size=50)
            assert "too large" in str(exc_info.value.cause)

    @pytest.mark.asyncio
    async def test_invalid_json_rejected(self, relay):
        """Invalid JSON is rejected."""
        mock_content = AsyncMock()
        mock_content.read = AsyncMock(return_value=b"not json")

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.content = mock_content
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("models.nip11.aiohttp.ClientSession", return_value=mock_session),
            pytest.raises(Nip11FetchError),
        ):
            await Nip11.fetch(relay)

    @pytest.mark.asyncio
    async def test_non_dict_json_rejected(self, relay):
        """Non-dict JSON response is rejected."""
        mock_content = AsyncMock()
        mock_content.read = AsyncMock(return_value=b'["array", "not", "dict"]')

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.content = mock_content
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("models.nip11.aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(Nip11FetchError) as exc_info:
                await Nip11.fetch(relay)
            assert "Expected dict" in str(exc_info.value.cause)


class TestNip11FetchError:
    """Test Nip11FetchError exception."""

    def test_error_message(self, relay):
        """Error message contains relay URL and cause."""
        cause = ValueError("Test error")
        error = Nip11FetchError(relay, cause)
        assert "relay.example.com" in str(error)
        assert "Test error" in str(error)

    def test_error_attributes(self, relay):
        """Error has relay and cause attributes."""
        cause = ValueError("Test error")
        error = Nip11FetchError(relay, cause)
        assert error.relay is relay
        assert error.cause is cause
