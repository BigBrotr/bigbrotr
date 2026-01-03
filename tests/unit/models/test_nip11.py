"""
Unit tests for models.nip11 module.

Tests:
- NIP-11 property accessors (name, description, pubkey, contact)
- Limitation fields (max_message_length, auth_required, etc.)
- Fee fields (admission, subscription, publication)
- Retention and language fields
- to_relay_metadata() conversion
- Nip11.fetch() async HTTP client
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models import Metadata, Nip11, Relay, RelayMetadata


@pytest.fixture
def relay():
    return Relay("wss://relay.example.com", discovered_at=1234567890)


@pytest.fixture
def nip11(relay):
    """Nip11 with sample data."""
    data = {
        "name": "Test Relay",
        "description": "A test relay",
        "pubkey": "a" * 64,
        "contact": "admin@example.com",
        "supported_nips": [1, 11, 65],
        "software": "nostr-rs-relay",
        "version": "0.8.0",
        "limitation": {
            "max_message_length": 65535,
            "max_subscriptions": 20,
            "auth_required": False,
        },
        "fees": {
            "admission": [{"amount": 1000, "unit": "sats"}],
        },
    }
    instance = object.__new__(Nip11)
    object.__setattr__(instance, "relay", relay)
    object.__setattr__(instance, "metadata", Metadata(data))
    object.__setattr__(instance, "generated_at", 1234567890)
    return instance


class TestProperties:
    """Property accessors."""

    def test_base_fields(self, nip11):
        assert nip11.name == "Test Relay"
        assert nip11.description == "A test relay"
        assert nip11.pubkey == "a" * 64
        assert nip11.contact == "admin@example.com"
        assert nip11.supported_nips == [1, 11, 65]
        assert nip11.software == "nostr-rs-relay"
        assert nip11.version == "0.8.0"

    def test_limitation_fields(self, nip11):
        assert nip11.max_message_length == 65535
        assert nip11.max_subscriptions == 20
        assert nip11.auth_required is False

    def test_missing_optional(self, relay):
        instance = object.__new__(Nip11)
        object.__setattr__(instance, "relay", relay)
        object.__setattr__(instance, "metadata", Metadata({}))
        object.__setattr__(instance, "generated_at", 0)

        assert instance.name is None
        assert instance.banner is None
        assert instance.max_limit is None
        assert instance.supported_nips == []

    def test_fees(self, nip11):
        assert nip11.admission_fees == [{"amount": 1000, "unit": "sats"}]
        assert nip11.subscription_fees == []

    def test_data_property(self, nip11):
        assert nip11.data["name"] == "Test Relay"


class TestToRelayMetadata:
    """to_relay_metadata() method."""

    def test_returns_relay_metadata(self, nip11):
        rm = nip11.to_relay_metadata()
        assert isinstance(rm, RelayMetadata)
        assert rm.metadata_type == "nip11"
        assert rm.relay is nip11.relay
        assert rm.metadata is nip11.metadata
        assert rm.generated_at == 1234567890


class TestFetch:
    """fetch() class method."""

    @pytest.mark.asyncio
    async def test_success(self, relay):
        mock_content = AsyncMock()
        mock_content.read = AsyncMock(return_value=b'{"name": "Test"}')

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
            result = await Nip11.fetch(relay, timeout=30.0, max_size=1_048_576)

        assert result is not None
        assert result.name == "Test"

    @pytest.mark.asyncio
    async def test_non_200_returns_none(self, relay):
        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("models.nip11.aiohttp.ClientSession", return_value=mock_session):
            assert await Nip11.fetch(relay, timeout=30.0, max_size=1_048_576) is None

    @pytest.mark.asyncio
    async def test_exception_returns_none(self, relay):
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(side_effect=Exception("Error"))
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("models.nip11.aiohttp.ClientSession", return_value=mock_session):
            assert await Nip11.fetch(relay, timeout=30.0, max_size=1_048_576) is None

    @pytest.mark.asyncio
    async def test_uses_correct_protocol(self, relay):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_get = MagicMock(return_value=mock_response)
        mock_session.get = mock_get
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("models.nip11.aiohttp.ClientSession", return_value=mock_session):
            # Test wss -> https
            await Nip11.fetch(relay, timeout=30.0, max_size=1_048_576)
            assert mock_get.call_args[0][0].startswith("https://")

            # Test ws -> http
            ws_relay = Relay("ws://relay.example.com", discovered_at=0)
            await Nip11.fetch(ws_relay, timeout=30.0, max_size=1_048_576)
            assert mock_get.call_args[0][0].startswith("http://")

    @pytest.mark.asyncio
    async def test_sends_accept_header(self, relay):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_get = MagicMock(return_value=mock_response)
        mock_session.get = mock_get
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("models.nip11.aiohttp.ClientSession", return_value=mock_session):
            await Nip11.fetch(relay, timeout=30.0, max_size=1_048_576)
            headers = mock_get.call_args[1]["headers"]
            assert headers["Accept"] == "application/nostr+json"

    @pytest.mark.asyncio
    async def test_valid_content_types_accepted(self, relay):
        """Test valid JSON content types are accepted."""
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
                result = await Nip11.fetch(relay, timeout=30.0, max_size=1_048_576)
                assert result is not None, f"Should accept Content-Type: {content_type}"

    @pytest.mark.asyncio
    async def test_invalid_content_types_rejected(self, relay):
        """Test invalid content types are rejected."""
        invalid_types = [
            "text/html",
            "text/plain",
            "text/json",  # Not a standard JSON type
            "application/xml",
            "application/javascript",
            "",  # Empty
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
                result = await Nip11.fetch(relay, timeout=30.0, max_size=1_048_576)
                assert result is None, f"Should reject Content-Type: {content_type}"
