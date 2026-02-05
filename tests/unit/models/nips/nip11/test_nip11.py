"""Tests for the main Nip11 class and RelayNip11MetadataTuple.

Tests cover:
- Nip11 construction
  - With fetch_metadata
  - With fetch_metadata=None
  - With default generated_at
  - With explicit generated_at
  - Validation (negative generated_at, invalid relay)
- Nip11 data access
  - Accessing fetch_metadata fields
  - Accessing nested data
- Nip11 serialization
  - to_relay_metadata_tuple() method
- Nip11.create() factory method
  - Success scenarios
  - Error handling
  - URL scheme handling
  - Accept header verification
  - Content-Type validation
- RelayNip11MetadataTuple NamedTuple
  - Construction
  - Field access
  - Tuple unpacking
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from models.metadata import Metadata, MetadataType
from models.nips.nip11 import (
    Nip11,
    Nip11FetchData,
    Nip11FetchLogs,
    Nip11FetchMetadata,
)
from models.nips.nip11.nip11 import RelayNip11MetadataTuple
from models.relay import Relay


# =============================================================================
# Nip11 Construction Tests
# =============================================================================


class TestNip11Construction:
    """Test Nip11 construction."""

    def test_constructor_with_fetch_metadata(
        self,
        relay: Relay,
        fetch_metadata: Nip11FetchMetadata,
    ):
        """Constructor creates Nip11 with fetch_metadata."""
        nip11 = Nip11(
            relay=relay,
            fetch_metadata=fetch_metadata,
            generated_at=1234567890,
        )
        assert nip11.relay == relay
        assert nip11.fetch_metadata == fetch_metadata
        assert nip11.generated_at == 1234567890

    def test_constructor_with_fetch_metadata_none(self, relay: Relay):
        """Constructor accepts fetch_metadata=None."""
        nip11 = Nip11(
            relay=relay,
            fetch_metadata=None,
            generated_at=1234567890,
        )
        assert nip11.relay == relay
        assert nip11.fetch_metadata is None
        assert nip11.generated_at == 1234567890

    def test_default_generated_at(self, relay: Relay, fetch_metadata: Nip11FetchMetadata):
        """Default generated_at is current timestamp."""
        import time

        before = int(time.time())
        nip11 = Nip11(relay=relay, fetch_metadata=fetch_metadata)
        after = int(time.time())

        assert before <= nip11.generated_at <= after

    def test_explicit_generated_at(self, relay: Relay, fetch_metadata: Nip11FetchMetadata):
        """Explicit generated_at is preserved."""
        nip11 = Nip11(
            relay=relay,
            fetch_metadata=fetch_metadata,
            generated_at=1000,
        )
        assert nip11.generated_at == 1000

    def test_generated_at_zero(self, relay: Relay, fetch_metadata: Nip11FetchMetadata):
        """generated_at=0 is valid."""
        nip11 = Nip11(
            relay=relay,
            fetch_metadata=fetch_metadata,
            generated_at=0,
        )
        assert nip11.generated_at == 0

    def test_negative_generated_at_raises(self, relay: Relay, fetch_metadata: Nip11FetchMetadata):
        """Negative generated_at raises ValidationError."""
        with pytest.raises(ValidationError):
            Nip11(
                relay=relay,
                fetch_metadata=fetch_metadata,
                generated_at=-1,
            )

    def test_constructor_requires_relay(self, fetch_metadata: Nip11FetchMetadata):
        """Constructor requires relay field."""
        with pytest.raises(ValidationError):
            Nip11(fetch_metadata=fetch_metadata)


class TestNip11Frozen:
    """Test Nip11 is frozen (immutable)."""

    def test_model_is_frozen(self, nip11: Nip11):
        """Nip11 models are immutable."""
        with pytest.raises(ValidationError):
            nip11.generated_at = 9999999999

    def test_cannot_modify_relay(self, nip11: Nip11):
        """Cannot modify relay field."""
        with pytest.raises(ValidationError):
            nip11.relay = Relay("wss://other.example.com")

    def test_cannot_modify_fetch_metadata(
        self, nip11: Nip11, fetch_metadata_failed: Nip11FetchMetadata
    ):
        """Cannot modify fetch_metadata field."""
        with pytest.raises(ValidationError):
            nip11.fetch_metadata = fetch_metadata_failed


# =============================================================================
# Nip11 Data Access Tests
# =============================================================================


class TestNip11DataAccess:
    """Test Nip11 data access."""

    def test_fetch_metadata_data_access(self, nip11: Nip11):
        """Data accessible via fetch_metadata.data."""
        assert nip11.fetch_metadata.data.name == "Test Relay"
        assert nip11.fetch_metadata.data.description is not None

    def test_fetch_metadata_logs_access(self, nip11: Nip11):
        """Logs accessible via fetch_metadata.logs."""
        assert nip11.fetch_metadata.logs.success is True
        assert nip11.fetch_metadata.logs.reason is None

    def test_fetch_metadata_none_access(self, nip11_no_fetch_metadata: Nip11):
        """Accessing fetch_metadata when None returns None."""
        assert nip11_no_fetch_metadata.fetch_metadata is None

    def test_limitation_access(self, nip11: Nip11):
        """Limitation accessible via fetch_metadata.data.limitation."""
        limitation = nip11.fetch_metadata.data.limitation
        assert limitation.max_message_length == 65535
        assert limitation.auth_required is False

    def test_retention_access(self, nip11: Nip11):
        """Retention accessible via fetch_metadata.data.retention."""
        retention = nip11.fetch_metadata.data.retention
        assert retention is not None
        assert len(retention) == 3

    def test_fees_access(self, nip11: Nip11):
        """Fees accessible via fetch_metadata.data.fees."""
        fees = nip11.fetch_metadata.data.fees
        assert fees.admission is not None

    def test_supported_nips_access(self, nip11: Nip11):
        """supported_nips accessible via fetch_metadata.data."""
        assert nip11.fetch_metadata.data.supported_nips == [1, 11, 42, 65]

    def test_self_property_access(self, nip11: Nip11):
        """self property accessible via fetch_metadata.data."""
        assert nip11.fetch_metadata.data.self == "b" * 64


class TestNip11DataAccessFailed:
    """Test Nip11 data access with failed fetch."""

    def test_failed_fetch_logs(self, nip11_failed: Nip11):
        """Failed fetch has success=False and reason."""
        assert nip11_failed.fetch_metadata.logs.success is False
        assert nip11_failed.fetch_metadata.logs.reason is not None

    def test_failed_fetch_empty_data(self, nip11_failed: Nip11):
        """Failed fetch has empty data."""
        assert nip11_failed.fetch_metadata.data.name is None


# =============================================================================
# Nip11 Serialization Tests
# =============================================================================


class TestNip11Serialization:
    """Test Nip11 serialization."""

    def test_to_relay_metadata_tuple(self, nip11: Nip11):
        """to_relay_metadata_tuple returns RelayNip11MetadataTuple."""
        result = nip11.to_relay_metadata_tuple()
        assert isinstance(result, RelayNip11MetadataTuple)

    def test_to_relay_metadata_tuple_nip11_fetch(self, nip11: Nip11):
        """to_relay_metadata_tuple returns RelayMetadata for nip11_fetch."""
        result = nip11.to_relay_metadata_tuple()
        assert result.nip11_fetch is not None
        assert result.nip11_fetch.metadata.type == MetadataType.NIP11_FETCH
        assert result.nip11_fetch.relay is nip11.relay
        assert result.nip11_fetch.generated_at == nip11.generated_at

    def test_to_relay_metadata_tuple_contains_metadata(self, nip11: Nip11):
        """RelayMetadata contains Metadata with fetch data."""
        result = nip11.to_relay_metadata_tuple()
        metadata = result.nip11_fetch.metadata
        assert isinstance(metadata, Metadata)
        assert metadata.value["data"]["name"] == "Test Relay"
        assert metadata.value["logs"]["success"] is True

    def test_to_relay_metadata_tuple_none_fetch_metadata(self, nip11_no_fetch_metadata: Nip11):
        """to_relay_metadata_tuple returns None for nip11_fetch when fetch_metadata is None."""
        result = nip11_no_fetch_metadata.to_relay_metadata_tuple()
        assert result.nip11_fetch is None


# =============================================================================
# RelayNip11MetadataTuple Tests
# =============================================================================


class TestRelayNip11MetadataTuple:
    """Test RelayNip11MetadataTuple NamedTuple."""

    def test_is_named_tuple(self):
        """RelayNip11MetadataTuple is a NamedTuple."""
        assert hasattr(RelayNip11MetadataTuple, "_fields")
        assert "nip11_fetch" in RelayNip11MetadataTuple._fields

    def test_construction(self, nip11: Nip11):
        """RelayNip11MetadataTuple can be constructed directly."""
        result = nip11.to_relay_metadata_tuple()
        tuple_direct = RelayNip11MetadataTuple(nip11_fetch=result.nip11_fetch)
        assert tuple_direct.nip11_fetch == result.nip11_fetch

    def test_construction_with_none(self):
        """RelayNip11MetadataTuple can be constructed with None."""
        tuple_none = RelayNip11MetadataTuple(nip11_fetch=None)
        assert tuple_none.nip11_fetch is None

    def test_tuple_unpacking(self, nip11: Nip11):
        """RelayNip11MetadataTuple can be unpacked."""
        result = nip11.to_relay_metadata_tuple()
        (nip11_fetch,) = result
        assert nip11_fetch == result.nip11_fetch

    def test_field_access_by_index(self, nip11: Nip11):
        """RelayNip11MetadataTuple fields accessible by index."""
        result = nip11.to_relay_metadata_tuple()
        assert result[0] == result.nip11_fetch

    def test_immutable(self, nip11: Nip11):
        """RelayNip11MetadataTuple is immutable."""
        result = nip11.to_relay_metadata_tuple()
        with pytest.raises((TypeError, AttributeError)):
            result.nip11_fetch = None


# =============================================================================
# Nip11.create() Tests - Success Scenarios
# =============================================================================


class TestNip11CreateSuccess:
    """Test Nip11.create() success scenarios."""

    @pytest.mark.asyncio
    async def test_create_success(self, relay: Relay, mock_session_factory):
        """Successful create returns Nip11 with data."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/nostr+json"}
        response.content.read = AsyncMock(return_value=b'{"name": "Test Relay"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay)

        assert isinstance(result, Nip11)
        assert result.relay == relay
        assert result.fetch_metadata.logs.success is True
        assert result.fetch_metadata.data.name == "Test Relay"
        assert result.generated_at > 0

    @pytest.mark.asyncio
    async def test_create_with_complete_data(
        self,
        relay: Relay,
        complete_nip11_data: dict[str, Any],
        mock_session_factory,
    ):
        """Create parses complete NIP-11 data."""
        import json

        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/nostr+json"}
        response.content.read = AsyncMock(return_value=json.dumps(complete_nip11_data).encode())
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay)

        assert result.fetch_metadata.logs.success is True
        assert result.fetch_metadata.data.name == "Test Relay"
        assert result.fetch_metadata.data.supported_nips == [1, 11, 42, 65]
        assert result.fetch_metadata.data.limitation.max_message_length == 65535


# =============================================================================
# Nip11.create() Tests - Error Handling
# =============================================================================


class TestNip11CreateErrors:
    """Test Nip11.create() error handling."""

    @pytest.mark.asyncio
    async def test_create_404_returns_failure(self, relay: Relay, mock_session_factory):
        """HTTP 404 returns Nip11 with success=False."""
        response = AsyncMock()
        response.status = 404
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay)

        assert isinstance(result, Nip11)
        assert result.fetch_metadata.logs.success is False
        assert "404" in result.fetch_metadata.logs.reason

    @pytest.mark.asyncio
    async def test_create_connection_error_returns_failure(self, relay: Relay):
        """Connection error returns Nip11 with success=False."""
        session = MagicMock()
        session.get = MagicMock(side_effect=ConnectionError("Connection refused"))
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay)

        assert isinstance(result, Nip11)
        assert result.fetch_metadata.logs.success is False
        assert "Connection refused" in result.fetch_metadata.logs.reason

    @pytest.mark.asyncio
    async def test_create_invalid_content_type(self, relay: Relay, mock_session_factory):
        """Invalid Content-Type returns Nip11 with success=False."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "text/html"}
        response.content.read = AsyncMock(return_value=b"<html></html>")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay)

        assert result.fetch_metadata.logs.success is False
        assert "Content-Type" in result.fetch_metadata.logs.reason

    @pytest.mark.asyncio
    async def test_create_response_too_large(self, relay: Relay, mock_session_factory):
        """Response exceeding max_size returns failure."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"x" * 100000)
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay, max_size=1000)

        assert result.fetch_metadata.logs.success is False
        assert "too large" in result.fetch_metadata.logs.reason

    @pytest.mark.asyncio
    async def test_create_invalid_json(self, relay: Relay, mock_session_factory):
        """Invalid JSON returns failure."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"not valid json")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay)

        assert result.fetch_metadata.logs.success is False

    @pytest.mark.asyncio
    async def test_create_non_dict_json(self, relay: Relay, mock_session_factory):
        """JSON that's not a dict returns failure."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b'["array"]')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay)

        assert result.fetch_metadata.logs.success is False
        assert "dict" in result.fetch_metadata.logs.reason


# =============================================================================
# Nip11.create() Tests - URL Scheme Handling
# =============================================================================


class TestNip11CreateUrlScheme:
    """Test URL scheme handling in Nip11.create()."""

    @pytest.mark.asyncio
    async def test_create_wss_uses_https(self, relay: Relay, mock_session_factory):
        """wss:// relay uses https://."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"{}")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=session):
            await Nip11.create(relay)

        call_args = session.get.call_args
        url = call_args[0][0]
        assert url.startswith("https://")

    @pytest.mark.asyncio
    async def test_create_ws_uses_http(self, tor_relay: Relay, mock_session_factory):
        """ws:// relay (Tor) uses http://."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"{}")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=session):
            await Nip11.create(tor_relay)

        call_args = session.get.call_args
        url = call_args[0][0]
        assert url.startswith("http://")


# =============================================================================
# Nip11.create() Tests - Accept Header
# =============================================================================


class TestNip11CreateAcceptHeader:
    """Test Accept header in Nip11.create()."""

    @pytest.mark.asyncio
    async def test_create_sends_accept_header(self, relay: Relay, mock_session_factory):
        """Request includes Accept: application/nostr+json header."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"{}")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=session):
            await Nip11.create(relay)

        call_args = session.get.call_args
        headers = call_args[1]["headers"]
        assert headers["Accept"] == "application/nostr+json"


# =============================================================================
# Nip11.create() Tests - Content-Type Validation
# =============================================================================


class TestNip11CreateContentType:
    """Test Content-Type validation in Nip11.create()."""

    @pytest.mark.asyncio
    async def test_create_accepts_nostr_json(self, relay: Relay, mock_session_factory):
        """application/nostr+json is accepted."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/nostr+json"}
        response.content.read = AsyncMock(return_value=b'{"name": "Test"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay)

        assert result.fetch_metadata.logs.success is True

    @pytest.mark.asyncio
    async def test_create_accepts_json(self, relay: Relay, mock_session_factory):
        """application/json is accepted."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b'{"name": "Test"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay)

        assert result.fetch_metadata.logs.success is True

    @pytest.mark.asyncio
    async def test_create_accepts_json_with_charset(self, relay: Relay, mock_session_factory):
        """application/json; charset=utf-8 is accepted."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json; charset=utf-8"}
        response.content.read = AsyncMock(return_value=b'{"name": "Test"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay)

        assert result.fetch_metadata.logs.success is True


# =============================================================================
# Nip11.create() Tests - Network Types
# =============================================================================


class TestNip11CreateNetworkTypes:
    """Test Nip11.create() with different network types."""

    @pytest.mark.asyncio
    async def test_create_tor_relay(self, tor_relay: Relay, mock_session_factory):
        """Create works with Tor relay."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b'{"name": "Tor Relay"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(tor_relay)

        assert result.relay == tor_relay
        assert result.fetch_metadata.logs.success is True

    @pytest.mark.asyncio
    async def test_create_i2p_relay(self, i2p_relay: Relay, mock_session_factory):
        """Create works with I2P relay."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b'{"name": "I2P Relay"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(i2p_relay)

        assert result.relay == i2p_relay
        assert result.fetch_metadata.logs.success is True

    @pytest.mark.asyncio
    async def test_create_loki_relay(self, loki_relay: Relay, mock_session_factory):
        """Create works with Lokinet relay."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b'{"name": "Loki Relay"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(loki_relay)

        assert result.relay == loki_relay
        assert result.fetch_metadata.logs.success is True


# =============================================================================
# Nip11.create() Tests - Parameters
# =============================================================================


class TestNip11CreateParameters:
    """Test Nip11.create() parameter handling."""

    @pytest.mark.asyncio
    async def test_create_custom_timeout(self, relay: Relay, mock_session_factory):
        """Create with custom timeout uses specified value."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"{}")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=session):
            await Nip11.create(relay, timeout=30.0)

        call_args = session.get.call_args
        timeout = call_args[1]["timeout"]
        assert timeout.total == 30.0

    @pytest.mark.asyncio
    async def test_create_custom_max_size(self, relay: Relay, mock_session_factory):
        """Create with custom max_size applies limit."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        # Return data larger than custom limit
        response.content.read = AsyncMock(return_value=b"x" * 2000)
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay, max_size=1000)

        assert result.fetch_metadata.logs.success is False
        assert "too large" in result.fetch_metadata.logs.reason


# =============================================================================
# Integration Tests
# =============================================================================


class TestNip11Integration:
    """Integration tests for Nip11."""

    def test_full_workflow_success(
        self,
        relay: Relay,
        complete_nip11_data: dict[str, Any],
    ):
        """Full workflow: construct -> access data -> serialize."""
        # Construct
        fetch_data = Nip11FetchData.from_dict(complete_nip11_data)
        fetch_logs = Nip11FetchLogs(success=True)
        fetch_metadata = Nip11FetchMetadata(data=fetch_data, logs=fetch_logs)
        nip11 = Nip11(relay=relay, fetch_metadata=fetch_metadata, generated_at=1234567890)

        # Access data
        assert nip11.fetch_metadata.data.name == "Test Relay"
        assert nip11.fetch_metadata.data.supported_nips == [1, 11, 42, 65]

        # Serialize
        result = nip11.to_relay_metadata_tuple()
        assert result.nip11_fetch is not None
        assert result.nip11_fetch.metadata.value["data"]["name"] == "Test Relay"

    def test_full_workflow_failure(self, relay: Relay):
        """Full workflow with failed fetch."""
        # Construct failed result
        fetch_data = Nip11FetchData()
        fetch_logs = Nip11FetchLogs(success=False, reason="Connection timeout")
        fetch_metadata = Nip11FetchMetadata(data=fetch_data, logs=fetch_logs)
        nip11 = Nip11(relay=relay, fetch_metadata=fetch_metadata, generated_at=1234567890)

        # Access data
        assert nip11.fetch_metadata.logs.success is False
        assert nip11.fetch_metadata.data.name is None

        # Serialize
        result = nip11.to_relay_metadata_tuple()
        assert result.nip11_fetch is not None
        assert result.nip11_fetch.metadata.value["logs"]["success"] is False

    def test_roundtrip_through_metadata(
        self,
        relay: Relay,
        complete_nip11_data: dict[str, Any],
    ):
        """Verify data survives roundtrip through Metadata."""
        # Create original
        fetch_data = Nip11FetchData.from_dict(complete_nip11_data)
        fetch_logs = Nip11FetchLogs(success=True)
        fetch_metadata = Nip11FetchMetadata(data=fetch_data, logs=fetch_logs)
        nip11 = Nip11(relay=relay, fetch_metadata=fetch_metadata)

        # Serialize to RelayMetadata
        result = nip11.to_relay_metadata_tuple()
        metadata_dict = result.nip11_fetch.metadata.value

        # Reconstruct fetch_metadata from dict
        reconstructed = Nip11FetchMetadata.from_dict(metadata_dict)

        # Verify key fields
        assert reconstructed.data.name == fetch_data.name
        assert reconstructed.data.supported_nips == fetch_data.supported_nips
        assert reconstructed.logs.success == fetch_logs.success
