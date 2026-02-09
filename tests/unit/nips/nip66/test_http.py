"""
Unit tests for models.nips.nip66.http module.

Tests:
- Nip66HttpMetadata._http() - async HTTP header capture
- Nip66HttpMetadata.execute() - async HTTP check with proxy support
- Server and X-Powered-By header extraction
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bigbrotr.models import Relay
from bigbrotr.nips.nip66.http import Nip66HttpMetadata


class TestNip66HttpMetadataHttpAsync:
    """Test Nip66HttpMetadata._http() async method."""

    @pytest.mark.asyncio
    async def test_captures_server_header(self, relay: Relay) -> None:
        """Captures Server header from WebSocket handshake."""
        mock_response_headers = {"Server": "nginx/1.24.0"}

        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock()

        mock_session = MagicMock()
        mock_session.ws_connect = MagicMock(return_value=AsyncMock())

        async def mock_ws_connect_cm(*args: Any, **kwargs: Any) -> AsyncMock:
            return mock_ws

        async def mock_session_cm(*args: Any, **kwargs: Any) -> MagicMock:
            return mock_session

        with (
            patch("aiohttp.ClientSession") as mock_client_session,
            patch("aiohttp.TraceConfig") as mock_trace_config,
        ):
            # Set up the trace config to capture headers
            trace_instance = MagicMock()
            trace_instance.on_request_end = MagicMock()
            trace_instance.on_request_end.append = MagicMock()
            mock_trace_config.return_value = trace_instance

            # Create mock session with proper context managers
            async def create_mock_session(*args: Any, **kwargs: Any) -> MagicMock:
                # Get the trace config callback
                trace_configs = kwargs.get("trace_configs", [])
                if trace_configs:
                    # Extract the on_request_end callback that was appended
                    on_request_end = trace_instance.on_request_end.append.call_args[0][0]
                    # Simulate calling the callback with headers
                    mock_params = MagicMock()
                    mock_params.response = MagicMock()
                    mock_params.response.headers = mock_response_headers
                    await on_request_end(MagicMock(), MagicMock(), mock_params)

                session = MagicMock()
                session.ws_connect = MagicMock(
                    return_value=AsyncMock(__aenter__=mock_ws_connect_cm)
                )
                return session

            mock_client_session.return_value.__aenter__ = create_mock_session
            mock_client_session.return_value.__aexit__ = AsyncMock(return_value=None)

    @pytest.mark.asyncio
    async def test_captures_powered_by_header(self, relay: Relay) -> None:
        """Captures X-Powered-By header from WebSocket handshake."""
        http_result = {
            "http_server": "nginx/1.24.0",
            "http_powered_by": "Strfry",
        }

        with patch.object(Nip66HttpMetadata, "_http", return_value=http_result):
            result = await Nip66HttpMetadata.execute(relay, 10.0)

        assert result.data.http_powered_by == "Strfry"

    @pytest.mark.asyncio
    async def test_empty_headers_returns_empty_dict(self, relay: Relay) -> None:
        """Empty headers returns empty dict."""
        with patch.object(Nip66HttpMetadata, "_http", return_value={}):
            result = await Nip66HttpMetadata.execute(relay, 10.0)

        assert result.data.http_server is None
        assert result.data.http_powered_by is None


class TestNip66HttpMetadataHttp:
    """Test Nip66HttpMetadata.execute() async class method."""

    @pytest.mark.asyncio
    async def test_clearnet_returns_http_metadata(self, relay: Relay) -> None:
        """Returns Nip66HttpMetadata for clearnet relay."""
        http_result = {
            "http_server": "nginx/1.24.0",
            "http_powered_by": "Strfry",
        }

        with patch.object(Nip66HttpMetadata, "_http", return_value=http_result):
            result = await Nip66HttpMetadata.execute(relay, 10.0)

        assert isinstance(result, Nip66HttpMetadata)
        assert result.data.http_server == "nginx/1.24.0"
        assert result.data.http_powered_by == "Strfry"
        assert result.logs.success is True

    @pytest.mark.asyncio
    async def test_tor_without_proxy_raises(self, tor_relay: Relay) -> None:
        """Raises ValueError for Tor relay without proxy."""
        with pytest.raises(ValueError, match=r"overlay network tor requires proxy"):
            await Nip66HttpMetadata.execute(tor_relay, 10.0)

    @pytest.mark.asyncio
    async def test_i2p_without_proxy_raises(self, i2p_relay: Relay) -> None:
        """Raises ValueError for I2P relay without proxy."""
        with pytest.raises(ValueError, match=r"overlay network i2p requires proxy"):
            await Nip66HttpMetadata.execute(i2p_relay, 10.0)

    @pytest.mark.asyncio
    async def test_loki_without_proxy_raises(self, loki_relay: Relay) -> None:
        """Raises ValueError for Lokinet relay without proxy."""
        with pytest.raises(ValueError, match=r"overlay network loki requires proxy"):
            await Nip66HttpMetadata.execute(loki_relay, 10.0)

    @pytest.mark.asyncio
    async def test_tor_with_proxy_works(self, tor_relay: Relay) -> None:
        """Tor relay with proxy succeeds."""
        http_result = {"http_server": "nginx/1.24.0"}

        with patch.object(Nip66HttpMetadata, "_http", return_value=http_result):
            result = await Nip66HttpMetadata.execute(
                tor_relay, 10.0, proxy_url="socks5://localhost:9050"
            )

        assert isinstance(result, Nip66HttpMetadata)
        assert result.data.http_server == "nginx/1.24.0"

    @pytest.mark.asyncio
    async def test_clearnet_with_proxy_works(self, relay: Relay) -> None:
        """Clearnet relay with optional proxy works."""
        http_result = {"http_server": "nginx/1.24.0"}

        with patch.object(Nip66HttpMetadata, "_http", return_value=http_result):
            result = await Nip66HttpMetadata.execute(
                relay, 10.0, proxy_url="socks5://localhost:9050"
            )

        assert isinstance(result, Nip66HttpMetadata)

    @pytest.mark.asyncio
    async def test_no_headers_returns_failure(self, relay: Relay) -> None:
        """No HTTP headers returns failure logs."""
        with patch.object(Nip66HttpMetadata, "_http", return_value={}):
            result = await Nip66HttpMetadata.execute(relay, 10.0)

        assert isinstance(result, Nip66HttpMetadata)
        assert result.logs.success is False
        assert "no HTTP headers captured" in result.logs.reason

    @pytest.mark.asyncio
    async def test_exception_returns_failure(self, relay: Relay) -> None:
        """Exception during HTTP check returns failure logs."""
        with patch.object(Nip66HttpMetadata, "_http", side_effect=Exception("Connection timeout")):
            result = await Nip66HttpMetadata.execute(relay, 10.0)

        assert isinstance(result, Nip66HttpMetadata)
        assert result.logs.success is False
        assert "Connection timeout" in result.logs.reason

    @pytest.mark.asyncio
    async def test_uses_default_timeout(self, relay: Relay) -> None:
        """Uses default timeout when None provided."""
        http_result = {"http_server": "nginx/1.24.0"}

        with patch.object(Nip66HttpMetadata, "_http", return_value=http_result) as mock_http:
            await Nip66HttpMetadata.execute(relay, None)

        mock_http.assert_called_once()
        call_args = mock_http.call_args
        assert call_args[0][1] > 0

    @pytest.mark.asyncio
    async def test_passes_proxy_url_to_http(self, relay: Relay) -> None:
        """Passes proxy_url to _http method."""
        http_result = {"http_server": "nginx/1.24.0"}
        proxy_url = "socks5://localhost:9050"

        with patch.object(Nip66HttpMetadata, "_http", return_value=http_result) as mock_http:
            await Nip66HttpMetadata.execute(relay, 10.0, proxy_url=proxy_url)

        mock_http.assert_called_once()
        call_args = mock_http.call_args
        assert call_args[0][2] == proxy_url  # Third positional arg is proxy_url

    @pytest.mark.asyncio
    async def test_only_server_header_success(self, relay: Relay) -> None:
        """Success when only Server header is present."""
        http_result = {"http_server": "apache/2.4.41"}

        with patch.object(Nip66HttpMetadata, "_http", return_value=http_result):
            result = await Nip66HttpMetadata.execute(relay, 10.0)

        assert result.logs.success is True
        assert result.data.http_server == "apache/2.4.41"
        assert result.data.http_powered_by is None

    @pytest.mark.asyncio
    async def test_only_powered_by_header_success(self, relay: Relay) -> None:
        """Success when only X-Powered-By header is present."""
        http_result = {"http_powered_by": "Express"}

        with patch.object(Nip66HttpMetadata, "_http", return_value=http_result):
            result = await Nip66HttpMetadata.execute(relay, 10.0)

        assert result.logs.success is True
        assert result.data.http_server is None
        assert result.data.http_powered_by == "Express"

    @pytest.mark.asyncio
    async def test_ws_relay_works(self, ws_relay: Relay) -> None:
        """ws:// relay (no SSL) works for HTTP check."""
        http_result = {"http_server": "nginx/1.24.0"}

        with patch.object(Nip66HttpMetadata, "_http", return_value=http_result):
            result = await Nip66HttpMetadata.execute(ws_relay, 10.0)

        assert isinstance(result, Nip66HttpMetadata)
        assert result.logs.success is True
