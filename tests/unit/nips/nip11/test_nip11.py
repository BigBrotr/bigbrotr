"""Unit tests for Nip11 class, Nip11.create() factory, and RelayNip11MetadataTuple."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from bigbrotr.models.metadata import Metadata, MetadataType
from bigbrotr.models.relay import Relay
from bigbrotr.nips.nip11 import (
    Nip11,
    Nip11Dependencies,
    Nip11InfoData,
    Nip11InfoLogs,
    Nip11InfoMetadata,
    Nip11Options,
    Nip11Selection,
)
from bigbrotr.nips.nip11.nip11 import RelayNip11MetadataTuple


# =============================================================================
# Nip11 Construction Tests
# =============================================================================


class TestNip11Construction:
    """Test Nip11 construction."""

    def test_constructor_with_info(
        self,
        relay: Relay,
        info_metadata: Nip11InfoMetadata,
    ):
        """Constructor creates Nip11 with info."""
        nip11 = Nip11(
            relay=relay,
            info=info_metadata,
            generated_at=1234567890,
        )
        assert nip11.relay == relay
        assert nip11.info == info_metadata
        assert nip11.generated_at == 1234567890

    def test_constructor_with_info_none(self, relay: Relay):
        """Constructor accepts info=None."""
        nip11 = Nip11(
            relay=relay,
            info=None,
            generated_at=1234567890,
        )
        assert nip11.relay == relay
        assert nip11.info is None
        assert nip11.generated_at == 1234567890

    def test_default_generated_at(self, relay: Relay, info_metadata: Nip11InfoMetadata):
        """Default generated_at is current timestamp."""
        import time

        before = int(time.time())
        nip11 = Nip11(relay=relay, info=info_metadata)
        after = int(time.time())

        assert before <= nip11.generated_at <= after

    def test_explicit_generated_at(self, relay: Relay, info_metadata: Nip11InfoMetadata):
        """Explicit generated_at is preserved."""
        nip11 = Nip11(
            relay=relay,
            info=info_metadata,
            generated_at=1000,
        )
        assert nip11.generated_at == 1000

    def test_generated_at_zero(self, relay: Relay, info_metadata: Nip11InfoMetadata):
        """generated_at=0 is valid."""
        nip11 = Nip11(
            relay=relay,
            info=info_metadata,
            generated_at=0,
        )
        assert nip11.generated_at == 0

    def test_negative_generated_at_raises(self, relay: Relay, info_metadata: Nip11InfoMetadata):
        """Negative generated_at raises ValidationError."""
        with pytest.raises(ValidationError):
            Nip11(
                relay=relay,
                info=info_metadata,
                generated_at=-1,
            )

    def test_constructor_requires_relay(self, info_metadata: Nip11InfoMetadata):
        """Constructor requires relay field."""
        with pytest.raises(ValidationError):
            Nip11(info=info_metadata)


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

    def test_cannot_modify_info(self, nip11: Nip11, info_metadata_failed: Nip11InfoMetadata):
        """Cannot modify info field."""
        with pytest.raises(ValidationError):
            nip11.info = info_metadata_failed


# =============================================================================
# Nip11 Data Access Tests
# =============================================================================


class TestNip11DataAccess:
    """Test Nip11 data access."""

    def test_info_data_access(self, nip11: Nip11):
        """Data accessible via info.data."""
        assert nip11.info.data.name == "Test Relay"
        assert nip11.info.data.description is not None

    def test_info_logs_access(self, nip11: Nip11):
        """Logs accessible via info.logs."""
        assert nip11.info.logs.success is True
        assert nip11.info.logs.reason is None

    def test_info_none_access(self, nip11_no_info: Nip11):
        """Accessing info when None returns None."""
        assert nip11_no_info.info is None

    def test_limitation_access(self, nip11: Nip11):
        """Limitation accessible via info.data.limitation."""
        limitation = nip11.info.data.limitation
        assert limitation.max_message_length == 65535
        assert limitation.auth_required is False

    def test_retention_access(self, nip11: Nip11):
        """Retention accessible via info.data.retention."""
        retention = nip11.info.data.retention
        assert retention is not None
        assert len(retention) == 3

    def test_fees_access(self, nip11: Nip11):
        """Fees accessible via info.data.fees."""
        fees = nip11.info.data.fees
        assert fees.admission is not None

    def test_supported_nips_access(self, nip11: Nip11):
        """supported_nips accessible via info.data."""
        assert nip11.info.data.supported_nips == [1, 11, 42, 65]

    def test_self_property_access(self, nip11: Nip11):
        """self property accessible via info.data."""
        assert nip11.info.data.self == "b" * 64


class TestNip11DataAccessFailed:
    """Test Nip11 data access with failed info retrieval."""

    def test_failed_info_logs(self, nip11_failed: Nip11):
        """Failed info retrieval has success=False and reason."""
        assert nip11_failed.info.logs.success is False
        assert nip11_failed.info.logs.reason is not None

    def test_failed_info_empty_data(self, nip11_failed: Nip11):
        """Failed info retrieval has empty data."""
        assert nip11_failed.info.data.name is None


# =============================================================================
# Nip11 Serialization Tests
# =============================================================================


class TestNip11Serialization:
    """Test Nip11 serialization."""

    def test_to_relay_metadata_tuple(self, nip11: Nip11):
        """to_relay_metadata_tuple returns RelayNip11MetadataTuple."""
        result = nip11.to_relay_metadata_tuple()
        assert isinstance(result, RelayNip11MetadataTuple)

    def test_to_relay_metadata_tuple_nip11_info(self, nip11: Nip11):
        """to_relay_metadata_tuple returns RelayMetadata for nip11_info."""
        result = nip11.to_relay_metadata_tuple()
        assert result.nip11_info is not None
        assert result.nip11_info.metadata.type == MetadataType.NIP11_INFO
        assert result.nip11_info.relay is nip11.relay
        assert result.nip11_info.generated_at == nip11.generated_at

    def test_to_relay_metadata_tuple_contains_metadata(self, nip11: Nip11):
        """RelayMetadata contains Metadata with info data."""
        result = nip11.to_relay_metadata_tuple()
        metadata = result.nip11_info.metadata
        assert isinstance(metadata, Metadata)
        assert metadata.data["data"]["name"] == "Test Relay"
        assert metadata.data["logs"]["success"] is True

    def test_to_relay_metadata_tuple_none_info(self, nip11_no_info: Nip11):
        """to_relay_metadata_tuple returns None for nip11_info when info is None."""
        result = nip11_no_info.to_relay_metadata_tuple()
        assert result.nip11_info is None


# =============================================================================
# RelayNip11MetadataTuple Tests
# =============================================================================


class TestRelayNip11MetadataTuple:
    """Test RelayNip11MetadataTuple NamedTuple."""

    def test_is_named_tuple(self):
        """RelayNip11MetadataTuple is a NamedTuple."""
        assert hasattr(RelayNip11MetadataTuple, "_fields")
        assert "nip11_info" in RelayNip11MetadataTuple._fields

    def test_construction(self, nip11: Nip11):
        """RelayNip11MetadataTuple can be constructed directly."""
        result = nip11.to_relay_metadata_tuple()
        tuple_direct = RelayNip11MetadataTuple(nip11_info=result.nip11_info)
        assert tuple_direct.nip11_info == result.nip11_info

    def test_construction_with_none(self):
        """RelayNip11MetadataTuple can be constructed with None."""
        tuple_none = RelayNip11MetadataTuple(nip11_info=None)
        assert tuple_none.nip11_info is None

    def test_tuple_unpacking(self, nip11: Nip11):
        """RelayNip11MetadataTuple can be unpacked."""
        result = nip11.to_relay_metadata_tuple()
        (nip11_info,) = result
        assert nip11_info == result.nip11_info

    def test_field_access_by_index(self, nip11: Nip11):
        """RelayNip11MetadataTuple fields accessible by index."""
        result = nip11.to_relay_metadata_tuple()
        assert result[0] == result.nip11_info

    def test_immutable(self, nip11: Nip11):
        """RelayNip11MetadataTuple is immutable."""
        result = nip11.to_relay_metadata_tuple()
        with pytest.raises((TypeError, AttributeError)):
            result.nip11_info = None


# =============================================================================
# Nip11.create() Tests - Success Scenarios
# =============================================================================


class TestNip11CreateSuccess:
    """Test Nip11.create() success scenarios."""

    async def test_create_success(self, relay: Relay, mock_session_factory):
        """Successful create returns Nip11 with data."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/nostr+json"}
        response.content.read = AsyncMock(return_value=b'{"name": "Test Relay"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay)

        assert isinstance(result, Nip11)
        assert result.relay == relay
        assert result.info.logs.success is True
        assert result.info.data.name == "Test Relay"
        assert result.generated_at > 0

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

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay)

        assert result.info.logs.success is True
        assert result.info.data.name == "Test Relay"
        assert result.info.data.supported_nips == [1, 11, 42, 65]
        assert result.info.data.limitation.max_message_length == 65535


# =============================================================================
# Nip11.create() Tests - Error Handling
# =============================================================================


class TestNip11CreateErrors:
    """Test Nip11.create() error handling."""

    async def test_create_404_returns_failure(self, relay: Relay, mock_session_factory):
        """HTTP 404 returns Nip11 with success=False."""
        response = AsyncMock()
        response.status = 404
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay)

        assert isinstance(result, Nip11)
        assert result.info.logs.success is False
        assert "404" in result.info.logs.reason

    async def test_create_connection_error_returns_failure(self, relay: Relay):
        """Connection error returns Nip11 with success=False."""
        session = MagicMock()
        session.get = MagicMock(side_effect=ConnectionError("Connection refused"))
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay)

        assert isinstance(result, Nip11)
        assert result.info.logs.success is False
        assert "Connection refused" in result.info.logs.reason

    async def test_create_invalid_content_type(self, relay: Relay, mock_session_factory):
        """Invalid Content-Type returns Nip11 with success=False."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "text/html"}
        response.content.read = AsyncMock(return_value=b"<html></html>")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay)

        assert result.info.logs.success is False
        assert "Content-Type" in result.info.logs.reason

    async def test_create_response_too_large(self, relay: Relay, mock_session_factory):
        """Response exceeding max_size returns failure."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"x" * 100000)
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay, options=Nip11Options(max_size=1000))

        assert result.info.logs.success is False
        assert "too large" in result.info.logs.reason

    async def test_create_invalid_json(self, relay: Relay, mock_session_factory):
        """Invalid JSON returns failure."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"not valid json")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay)

        assert result.info.logs.success is False

    async def test_create_non_dict_json(self, relay: Relay, mock_session_factory):
        """JSON that's not a dict returns failure."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b'["array"]')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay)

        assert result.info.logs.success is False
        assert "dict" in result.info.logs.reason


# =============================================================================
# Nip11.create() Tests - URL Scheme Handling
# =============================================================================


class TestNip11CreateUrlScheme:
    """Test URL scheme handling in Nip11.create()."""

    async def test_create_wss_uses_https(self, relay: Relay, mock_session_factory):
        """wss:// relay uses https://."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"{}")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            await Nip11.create(relay)

        call_args = session.get.call_args
        url = call_args[0][0]
        assert url.startswith("https://")

    async def test_create_ws_uses_http(self, tor_relay: Relay, mock_session_factory):
        """ws:// relay (Tor) uses http://."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"{}")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            await Nip11.create(tor_relay)

        call_args = session.get.call_args
        url = call_args[0][0]
        assert url.startswith("http://")


# =============================================================================
# Nip11.create() Tests - Accept Header
# =============================================================================


class TestNip11CreateAcceptHeader:
    """Test Accept header in Nip11.create()."""

    async def test_create_sends_accept_header(self, relay: Relay, mock_session_factory):
        """Request includes Accept: application/nostr+json header."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"{}")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            await Nip11.create(relay)

        call_args = session.get.call_args
        headers = call_args[1]["headers"]
        assert headers["Accept"] == "application/nostr+json"


# =============================================================================
# Nip11.create() Tests - Content-Type Validation
# =============================================================================


class TestNip11CreateContentType:
    """Test Content-Type validation in Nip11.create()."""

    async def test_create_accepts_nostr_json(self, relay: Relay, mock_session_factory):
        """application/nostr+json is accepted."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/nostr+json"}
        response.content.read = AsyncMock(return_value=b'{"name": "Test"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay)

        assert result.info.logs.success is True

    async def test_create_accepts_json(self, relay: Relay, mock_session_factory):
        """application/json is accepted."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b'{"name": "Test"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay)

        assert result.info.logs.success is True

    async def test_create_accepts_json_with_charset(self, relay: Relay, mock_session_factory):
        """application/json; charset=utf-8 is accepted."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json; charset=utf-8"}
        response.content.read = AsyncMock(return_value=b'{"name": "Test"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay)

        assert result.info.logs.success is True


# =============================================================================
# Nip11.create() Tests - Network Types
# =============================================================================


class TestNip11CreateNetworkTypes:
    """Test Nip11.create() with different network types."""

    async def test_create_tor_relay(self, tor_relay: Relay, mock_session_factory):
        """Create works with Tor relay."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b'{"name": "Tor Relay"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(tor_relay)

        assert result.relay == tor_relay
        assert result.info.logs.success is True

    async def test_create_i2p_relay(self, i2p_relay: Relay, mock_session_factory):
        """Create works with I2P relay."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b'{"name": "I2P Relay"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(i2p_relay)

        assert result.relay == i2p_relay
        assert result.info.logs.success is True

    async def test_create_loki_relay(self, loki_relay: Relay, mock_session_factory):
        """Create works with Lokinet relay."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b'{"name": "Loki Relay"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(loki_relay)

        assert result.relay == loki_relay
        assert result.info.logs.success is True


# =============================================================================
# Nip11.create() Tests - Parameters
# =============================================================================


class TestNip11CreateParameters:
    """Test Nip11.create() parameter handling."""

    async def test_create_custom_timeout(self, relay: Relay, mock_session_factory):
        """Create with custom timeout uses specified value."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"{}")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            await Nip11.create(relay, timeout=30.0)

        call_args = session.get.call_args
        timeout = call_args[1]["timeout"]
        assert timeout.total == 30.0

    async def test_create_custom_max_size_via_options(self, relay: Relay, mock_session_factory):
        """Create with Nip11Options max_size applies limit."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"x" * 2000)
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay, options=Nip11Options(max_size=1000))

        assert result.info.logs.success is False
        assert "too large" in result.info.logs.reason

    async def test_create_default_timeout(self, relay: Relay, mock_session_factory):
        """Create without timeout uses DEFAULT_TIMEOUT."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"{}")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            await Nip11.create(relay)

        call_args = session.get.call_args
        timeout = call_args[1]["timeout"]
        assert timeout.total == 10.0


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
        info_data = Nip11InfoData.from_dict(complete_nip11_data)
        info_logs = Nip11InfoLogs(success=True)
        info_metadata = Nip11InfoMetadata(data=info_data, logs=info_logs)
        nip11 = Nip11(relay=relay, info=info_metadata, generated_at=1234567890)

        assert nip11.info.data.name == "Test Relay"
        assert nip11.info.data.supported_nips == [1, 11, 42, 65]

        result = nip11.to_relay_metadata_tuple()
        assert result.nip11_info is not None
        assert result.nip11_info.metadata.data["data"]["name"] == "Test Relay"

    def test_full_workflow_failure(self, relay: Relay):
        """Full workflow with failed info retrieval."""
        info_data = Nip11InfoData()
        info_logs = Nip11InfoLogs(success=False, reason="Connection timeout")
        info_metadata = Nip11InfoMetadata(data=info_data, logs=info_logs)
        nip11 = Nip11(relay=relay, info=info_metadata, generated_at=1234567890)

        assert nip11.info.logs.success is False
        assert nip11.info.data.name is None

        result = nip11.to_relay_metadata_tuple()
        assert result.nip11_info is not None
        assert result.nip11_info.metadata.data["logs"]["success"] is False

    def test_roundtrip_through_metadata(
        self,
        relay: Relay,
        complete_nip11_data: dict[str, Any],
    ):
        """Verify data survives roundtrip through Metadata."""
        info_data = Nip11InfoData.from_dict(complete_nip11_data)
        info_logs = Nip11InfoLogs(success=True)
        info_metadata = Nip11InfoMetadata(data=info_data, logs=info_logs)
        nip11 = Nip11(relay=relay, info=info_metadata)

        result = nip11.to_relay_metadata_tuple()
        metadata_dict = result.nip11_info.metadata.data
        reconstructed = Nip11InfoMetadata.from_dict(metadata_dict)

        assert reconstructed.data.name == info_data.name
        assert reconstructed.data.supported_nips == info_data.supported_nips
        assert reconstructed.logs.success == info_logs.success


# =============================================================================
# Nip11Selection Tests
# =============================================================================


class TestNip11Selection:
    """Test Nip11Selection configuration model."""

    def test_default_all_enabled(self):
        """Default selection enables all retrievals."""
        selection = Nip11Selection()
        assert selection.info is True

    def test_disable_info(self):
        """info=False disables info retrieval."""
        selection = Nip11Selection(info=False)
        assert selection.info is False

    def test_frozen(self):
        """Nip11Selection is a Pydantic model."""
        selection = Nip11Selection()
        assert selection.model_fields_set == set()


# =============================================================================
# Nip11Options Tests
# =============================================================================


class TestNip11Options:
    """Test Nip11Options configuration model."""

    def test_defaults(self):
        """Default options have secure defaults."""
        options = Nip11Options()
        assert options.allow_insecure is False
        assert options.max_size == 65_536

    def test_custom_allow_insecure(self):
        """Custom allow_insecure is preserved."""
        options = Nip11Options(allow_insecure=True)
        assert options.allow_insecure is True

    def test_custom_max_size(self):
        """Custom max_size is preserved."""
        options = Nip11Options(max_size=1024)
        assert options.max_size == 1024

    def test_combined_options(self):
        """Multiple options can be set together."""
        options = Nip11Options(allow_insecure=True, max_size=2048)
        assert options.allow_insecure is True
        assert options.max_size == 2048


# =============================================================================
# Nip11Dependencies Tests
# =============================================================================


class TestNip11Dependencies:
    """Test Nip11Dependencies frozen dataclass."""

    def test_is_dataclass(self):
        """Nip11Dependencies is a frozen dataclass."""
        from dataclasses import fields, is_dataclass

        assert is_dataclass(Nip11Dependencies)
        assert len(fields(Nip11Dependencies)) == 0

    def test_construction(self):
        """Nip11Dependencies can be constructed."""
        deps = Nip11Dependencies()
        assert isinstance(deps, Nip11Dependencies)

    def test_is_base_nip_dependencies(self):
        """Nip11Dependencies inherits from BaseNipDependencies."""
        from bigbrotr.nips.base import BaseNipDependencies

        assert issubclass(Nip11Dependencies, BaseNipDependencies)
        assert isinstance(Nip11Dependencies(), BaseNipDependencies)


# =============================================================================
# Nip11.create() Tests - Selection
# =============================================================================


class TestNip11CreateSelection:
    """Test Nip11.create() with Nip11Selection."""

    async def test_info_disabled_returns_none(self, relay: Relay):
        """selection=Nip11Selection(info=False) returns info=None."""
        result = await Nip11.create(relay, selection=Nip11Selection(info=False))
        assert isinstance(result, Nip11)
        assert result.info is None
        assert result.relay == relay

    async def test_info_enabled_calls_execute(self, relay: Relay, mock_session_factory):
        """selection=Nip11Selection(info=True) calls execute."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b'{"name": "Test"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay, selection=Nip11Selection(info=True))

        assert result.info is not None
        assert result.info.logs.success is True

    async def test_default_selection_fetches_info(self, relay: Relay, mock_session_factory):
        """Default selection (no selection param) fetches info."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b'{"name": "Test"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay)

        assert result.info is not None


# =============================================================================
# Nip11.create() Tests - Options
# =============================================================================


class TestNip11CreateOptions:
    """Test Nip11.create() with Nip11Options."""

    async def test_options_max_size_passed_to_execute(self, relay: Relay, mock_session_factory):
        """Nip11Options.max_size is passed to execute."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"x" * 2000)
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11.create(relay, options=Nip11Options(max_size=1000))

        assert result.info.logs.success is False
        assert "too large" in result.info.logs.reason

    async def test_options_allow_insecure_passed_to_execute(self, relay: Relay):
        """Nip11Options.allow_insecure is passed to execute."""
        with patch(
            "bigbrotr.nips.nip11.info.Nip11InfoMetadata.execute",
            new_callable=AsyncMock,
        ) as mock_execute:
            mock_execute.return_value = Nip11InfoMetadata(
                data=Nip11InfoData(),
                logs=Nip11InfoLogs(success=True),
            )
            await Nip11.create(relay, options=Nip11Options(allow_insecure=True))

        mock_execute.assert_called_once()
        call_kwargs = mock_execute.call_args
        assert call_kwargs[1]["allow_insecure"] is True

    async def test_default_options_secure(self, relay: Relay):
        """Default options use secure mode."""
        with patch(
            "bigbrotr.nips.nip11.info.Nip11InfoMetadata.execute",
            new_callable=AsyncMock,
        ) as mock_execute:
            mock_execute.return_value = Nip11InfoMetadata(
                data=Nip11InfoData(),
                logs=Nip11InfoLogs(success=True),
            )
            await Nip11.create(relay)

        call_kwargs = mock_execute.call_args
        assert call_kwargs[1]["allow_insecure"] is False
