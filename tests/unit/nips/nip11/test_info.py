"""Unit tests for Nip11InfoMetadata container and execute() HTTP operations."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from bigbrotr.models.relay import Relay
from bigbrotr.nips.nip11 import (
    Nip11InfoData,
    Nip11InfoLogs,
    Nip11InfoMetadata,
)


# =============================================================================
# Nip11InfoMetadata Container Tests
# =============================================================================


class TestNip11InfoMetadataConstruction:
    """Test Nip11InfoMetadata construction."""

    def test_constructor_with_data_and_logs(
        self,
        info_data: Nip11InfoData,
        info_logs_success: Nip11InfoLogs,
    ):
        """Constructor creates container with data and logs."""
        metadata = Nip11InfoMetadata(data=info_data, logs=info_logs_success)
        assert metadata.data == info_data
        assert metadata.logs == info_logs_success

    def test_constructor_requires_data(self, info_logs_success: Nip11InfoLogs):
        """Constructor requires data field."""
        with pytest.raises(ValidationError):
            Nip11InfoMetadata(logs=info_logs_success)

    def test_constructor_requires_logs(self, info_data: Nip11InfoData):
        """Constructor requires logs field."""
        with pytest.raises(ValidationError):
            Nip11InfoMetadata(data=info_data)


class TestNip11InfoMetadataFromDict:
    """Test Nip11InfoMetadata.from_dict() method."""

    def test_from_dict_valid(self):
        """from_dict with valid data creates Nip11InfoMetadata."""
        raw = {
            "data": {"name": "Test Relay"},
            "logs": {"success": True},
        }
        metadata = Nip11InfoMetadata.from_dict(raw)
        assert metadata.data.name == "Test Relay"
        assert metadata.logs.success is True

    def test_from_dict_with_failure_logs(self):
        """from_dict with failure logs."""
        raw = {
            "data": {},
            "logs": {"success": False, "reason": "Connection timeout"},
        }
        metadata = Nip11InfoMetadata.from_dict(raw)
        assert metadata.logs.success is False
        assert metadata.logs.reason == "Connection timeout"

    def test_from_dict_missing_data_raises(self):
        """from_dict without data raises ValidationError."""
        with pytest.raises(ValidationError):
            Nip11InfoMetadata.from_dict({"logs": {"success": True}})

    def test_from_dict_missing_logs_raises(self):
        """from_dict without logs raises ValidationError."""
        with pytest.raises(ValidationError):
            Nip11InfoMetadata.from_dict({"data": {"name": "Test"}})


class TestNip11InfoMetadataToDict:
    """Test Nip11InfoMetadata.to_dict() method."""

    def test_to_dict(self, info_metadata: Nip11InfoMetadata):
        """to_dict returns dict with nested to_dict() calls."""
        d = info_metadata.to_dict()
        assert "data" in d
        assert "logs" in d
        assert isinstance(d["data"], dict)
        assert isinstance(d["logs"], dict)

    def test_to_dict_success_logs(self, info_metadata: Nip11InfoMetadata):
        """to_dict with success logs excludes reason."""
        d = info_metadata.to_dict()
        assert d["logs"]["success"] is True
        assert "reason" not in d["logs"]

    def test_to_dict_failure_logs(self, info_metadata_failed: Nip11InfoMetadata):
        """to_dict with failure logs includes reason."""
        d = info_metadata_failed.to_dict()
        assert d["logs"]["success"] is False
        assert "reason" in d["logs"]


class TestNip11InfoMetadataRoundtrip:
    """Test to_dict -> from_dict roundtrip."""

    def test_roundtrip_success(self, info_metadata: Nip11InfoMetadata):
        """Roundtrip preserves success metadata."""
        reconstructed = Nip11InfoMetadata.from_dict(info_metadata.to_dict())
        assert reconstructed.data.name == info_metadata.data.name
        assert reconstructed.logs.success == info_metadata.logs.success

    def test_roundtrip_failure(self, info_metadata_failed: Nip11InfoMetadata):
        """Roundtrip preserves failure metadata."""
        reconstructed = Nip11InfoMetadata.from_dict(info_metadata_failed.to_dict())
        assert reconstructed.logs.success is False
        assert reconstructed.logs.reason == info_metadata_failed.logs.reason


class TestNip11InfoMetadataFrozen:
    """Test Nip11InfoMetadata is frozen (immutable)."""

    def test_model_is_frozen(self, info_metadata: Nip11InfoMetadata):
        """Nip11InfoMetadata models are immutable."""
        with pytest.raises(ValidationError):
            info_metadata.data = Nip11InfoData()


# =============================================================================
# execute() Method - Success Scenarios
# =============================================================================


class TestNip11InfoMetadataSuccess:
    """Test Nip11InfoMetadata.execute() success scenarios."""

    async def test_info_success(self, relay: Relay, mock_session_factory):
        """Successful retrieval returns metadata with data."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/nostr+json"}
        response.content.read = AsyncMock(return_value=b'{"name": "Test Relay"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata.execute(relay)

        assert result.logs.success is True
        assert result.data.name == "Test Relay"

    async def test_info_with_complete_data(
        self, relay: Relay, complete_nip11_data: dict[str, Any], mock_session_factory
    ):
        """Retrieval parses complete NIP-11 data."""
        import json

        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/nostr+json"}
        response.content.read = AsyncMock(return_value=json.dumps(complete_nip11_data).encode())
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata.execute(relay)

        assert result.logs.success is True
        assert result.data.name == "Test Relay"
        assert result.data.supported_nips == [1, 11, 42, 65]
        assert result.data.limitation.max_message_length == 65535

    async def test_info_empty_json_object(self, relay: Relay, mock_session_factory):
        """Retrieval handles empty JSON object."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"{}")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata.execute(relay)

        assert result.logs.success is True
        assert result.data.name is None


# =============================================================================
# execute() Method - Content-Type Validation
# =============================================================================


class TestNip11InfoMetadataContentType:
    """Test Content-Type validation in execute()."""

    async def test_info_accepts_nostr_json(self, relay: Relay, mock_session_factory):
        """application/nostr+json is accepted."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/nostr+json"}
        response.content.read = AsyncMock(return_value=b'{"name": "Test"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata.execute(relay)

        assert result.logs.success is True

    async def test_info_accepts_json(self, relay: Relay, mock_session_factory):
        """application/json is accepted."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b'{"name": "Test"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata.execute(relay)

        assert result.logs.success is True

    async def test_info_accepts_json_with_charset(self, relay: Relay, mock_session_factory):
        """application/json with charset is accepted."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json; charset=utf-8"}
        response.content.read = AsyncMock(return_value=b'{"name": "Test"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata.execute(relay)

        assert result.logs.success is True

    async def test_info_rejects_text_html(self, relay: Relay, mock_session_factory):
        """text/html is rejected."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "text/html"}
        response.content.read = AsyncMock(return_value=b"<html></html>")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata.execute(relay)

        assert result.logs.success is False
        assert "Content-Type" in result.logs.reason

    async def test_info_rejects_text_plain(self, relay: Relay, mock_session_factory):
        """text/plain is rejected."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "text/plain"}
        response.content.read = AsyncMock(return_value=b"plain text")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata.execute(relay)

        assert result.logs.success is False
        assert "Content-Type" in result.logs.reason


# =============================================================================
# execute() Method - HTTP Error Handling
# =============================================================================


class TestNip11InfoMetadataHttpErrors:
    """Test HTTP error handling in execute()."""

    async def test_info_404_returns_failure(self, relay: Relay, mock_session_factory):
        """HTTP 404 returns failure."""
        response = AsyncMock()
        response.status = 404
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata.execute(relay)

        assert result.logs.success is False
        assert "404" in result.logs.reason

    async def test_info_500_returns_failure(self, relay: Relay, mock_session_factory):
        """HTTP 500 returns failure."""
        response = AsyncMock()
        response.status = 500
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata.execute(relay)

        assert result.logs.success is False
        assert "500" in result.logs.reason

    async def test_info_connection_error(self, relay: Relay, mock_session_factory):
        """Connection error returns failure."""
        session = MagicMock()
        session.get = MagicMock(side_effect=ConnectionError("Connection refused"))
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata.execute(relay)

        assert result.logs.success is False
        assert "Connection refused" in result.logs.reason

    async def test_info_timeout_error(self, relay: Relay, mock_session_factory):
        """Timeout error returns failure."""

        session = MagicMock()
        session.get = MagicMock(side_effect=TimeoutError())
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata.execute(relay)

        assert result.logs.success is False


# =============================================================================
# execute() Method - Response Size Limits
# =============================================================================


class TestNip11InfoMetadataResponseSize:
    """Test response size limit handling."""

    async def test_info_response_too_large(self, relay: Relay, mock_session_factory):
        """Response exceeding max_size returns failure."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"x" * 100000)
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata.execute(relay, max_size=1000)

        assert result.logs.success is False
        assert "too large" in result.logs.reason

    async def test_info_response_at_limit(self, relay: Relay, mock_session_factory):
        """Response exactly at max_size is accepted."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b'{"name": "Test"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata.execute(relay, max_size=65536)

        assert result.logs.success is True


# =============================================================================
# execute() Method - JSON Parsing Errors
# =============================================================================


class TestNip11InfoMetadataJsonParsing:
    """Test JSON parsing error handling."""

    async def test_info_invalid_json(self, relay: Relay, mock_session_factory):
        """Invalid JSON returns failure."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"not valid json")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata.execute(relay)

        assert result.logs.success is False

    async def test_info_json_array_returns_failure(self, relay: Relay, mock_session_factory):
        """JSON array (not dict) returns failure."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b'["array", "not", "dict"]')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata.execute(relay)

        assert result.logs.success is False
        assert "dict" in result.logs.reason

    async def test_info_json_string_returns_failure(self, relay: Relay, mock_session_factory):
        """JSON string (not dict) returns failure."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b'"just a string"')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata.execute(relay)

        assert result.logs.success is False
        assert "dict" in result.logs.reason

    async def test_info_json_null_returns_failure(self, relay: Relay, mock_session_factory):
        """JSON null returns failure."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"null")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata.execute(relay)

        assert result.logs.success is False


# =============================================================================
# execute() Method - URL Construction
# =============================================================================


class TestNip11InfoMetadataUrlConstruction:
    """Test URL construction in execute()."""

    async def test_info_wss_uses_https(self, relay: Relay, mock_session_factory):
        """wss:// relay uses https://."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"{}")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            await Nip11InfoMetadata.execute(relay)

        call_args = session.get.call_args
        url = call_args[0][0]
        assert url.startswith("https://")

    async def test_info_ws_uses_http(self, tor_relay: Relay, mock_session_factory):
        """ws:// relay uses http://."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"{}")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            await Nip11InfoMetadata.execute(tor_relay)

        call_args = session.get.call_args
        url = call_args[0][0]
        assert url.startswith("http://")

    async def test_info_includes_port(self, relay_with_port: Relay, mock_session_factory):
        """Non-default port is included in URL."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"{}")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            await Nip11InfoMetadata.execute(relay_with_port)

        call_args = session.get.call_args
        url = call_args[0][0]
        assert ":8080" in url

    async def test_info_includes_path(self, relay_with_path: Relay, mock_session_factory):
        """Path is included in URL."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"{}")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            await Nip11InfoMetadata.execute(relay_with_path)

        call_args = session.get.call_args
        url = call_args[0][0]
        assert "/nostr" in url

    async def test_info_ipv6_brackets(self, ipv6_relay: Relay, mock_session_factory):
        """IPv6 addresses are bracketed in URL."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"{}")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            await Nip11InfoMetadata.execute(ipv6_relay)

        call_args = session.get.call_args
        url = call_args[0][0]
        assert "[2607:f8b0:4000::1]" in url


# =============================================================================
# execute() Method - Accept Header
# =============================================================================


class TestNip11InfoMetadataAcceptHeader:
    """Test Accept header in execute()."""

    async def test_info_sends_accept_header(self, relay: Relay, mock_session_factory):
        """Request includes Accept: application/nostr+json header."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"{}")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            await Nip11InfoMetadata.execute(relay)

        call_args = session.get.call_args
        headers = call_args[1]["headers"]
        assert headers["Accept"] == "application/nostr+json"


# =============================================================================
# execute() Method - Network-Specific Behavior
# =============================================================================


class TestNip11InfoMetadataNetworkBehavior:
    """Test network-specific behavior in execute()."""

    async def test_info_tor_relay(self, tor_relay: Relay, mock_session_factory):
        """Tor relay retrieval uses http:// (overlay handles encryption)."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b'{"name": "Tor Relay"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata.execute(tor_relay)

        assert result.logs.success is True
        call_args = session.get.call_args
        url = call_args[0][0]
        assert url.startswith("http://")
        assert ".onion" in url

    async def test_info_i2p_relay(self, i2p_relay: Relay, mock_session_factory):
        """I2P relay retrieval uses http://."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b'{"name": "I2P Relay"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata.execute(i2p_relay)

        assert result.logs.success is True
        call_args = session.get.call_args
        url = call_args[0][0]
        assert url.startswith("http://")
        assert ".i2p" in url

    async def test_info_loki_relay(self, loki_relay: Relay, mock_session_factory):
        """Lokinet relay retrieval uses http://."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b'{"name": "Loki Relay"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata.execute(loki_relay)

        assert result.logs.success is True
        call_args = session.get.call_args
        url = call_args[0][0]
        assert url.startswith("http://")
        assert ".loki" in url


# =============================================================================
# execute() Method - Timeout Configuration
# =============================================================================


class TestNip11InfoMetadataTimeout:
    """Test timeout configuration in execute()."""

    async def test_info_uses_default_timeout(self, relay: Relay, mock_session_factory):
        """Retrieval uses default timeout when not specified."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"{}")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            await Nip11InfoMetadata.execute(relay)

        call_args = session.get.call_args
        timeout = call_args[1]["timeout"]
        assert timeout.total == 10.0

    async def test_info_custom_timeout(self, relay: Relay, mock_session_factory):
        """Retrieval uses custom timeout when specified."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"{}")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            await Nip11InfoMetadata.execute(relay, timeout=30.0)

        call_args = session.get.call_args
        timeout = call_args[1]["timeout"]
        assert timeout.total == 30.0


# =============================================================================
# execute() Method - Data Parsing with Invalid Fields
# =============================================================================


class TestNip11InfoMetadataDataParsing:
    """Test data parsing in execute() with invalid fields."""

    async def test_info_filters_invalid_fields(self, relay: Relay, mock_session_factory):
        """Retrieval filters invalid fields from response."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(
            return_value=b'{"name": "Test", "supported_nips": [1, true, "invalid", 11]}'
        )
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata.execute(relay)

        assert result.logs.success is True
        assert result.data.name == "Test"
        assert result.data.supported_nips == [1, 11]

    async def test_info_ignores_unknown_fields(self, relay: Relay, mock_session_factory):
        """Retrieval ignores unknown fields in response."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(
            return_value=b'{"name": "Test", "unknown_field": "ignored", "another": 123}'
        )
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata.execute(relay)

        assert result.logs.success is True
        assert result.data.name == "Test"
        assert not hasattr(result.data, "unknown_field")


# =============================================================================
# Direct _info() Method Tests
# =============================================================================


class TestNip11InfoMetadataDirectInfo:
    """Test the direct _info() static method."""

    async def test_direct_info_returns_dict(self, mock_session_factory):
        """_info() returns raw dict from relay."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b'{"name": "Direct Test"}')
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session):
            result = await Nip11InfoMetadata._info(
                http_url="https://relay.example.com",
                headers={"Accept": "application/nostr+json"},
                timeout=10.0,
                max_size=65536,
                ssl_context=True,
            )

        assert result == {"name": "Direct Test"}

    async def test_direct_info_raises_on_non_200(self, mock_session_factory):
        """_info() raises ValueError on non-200 status."""
        response = AsyncMock()
        response.status = 404
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with (
            patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session),
            pytest.raises(ValueError, match="HTTP 404"),
        ):
            await Nip11InfoMetadata._info(
                http_url="https://relay.example.com",
                headers={},
                timeout=10.0,
                max_size=65536,
                ssl_context=True,
            )

    async def test_direct_info_raises_on_invalid_content_type(self, mock_session_factory):
        """_info() raises ValueError on invalid Content-Type."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "text/html"}
        response.content.read = AsyncMock(return_value=b"<html></html>")
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with (
            patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session),
            pytest.raises(ValueError, match="Invalid Content-Type"),
        ):
            await Nip11InfoMetadata._info(
                http_url="https://relay.example.com",
                headers={},
                timeout=10.0,
                max_size=65536,
                ssl_context=True,
            )

    async def test_direct_info_raises_on_size_exceeded(self, mock_session_factory):
        """_info() raises ValueError when response exceeds max_size."""
        response = AsyncMock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.content.read = AsyncMock(return_value=b"x" * 1001)
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)

        session = mock_session_factory(response)

        with (
            patch("bigbrotr.nips.nip11.info.aiohttp.ClientSession", return_value=session),
            pytest.raises(ValueError, match="too large"),
        ):
            await Nip11InfoMetadata._info(
                http_url="https://relay.example.com",
                headers={},
                timeout=10.0,
                max_size=1000,
                ssl_context=True,
            )
