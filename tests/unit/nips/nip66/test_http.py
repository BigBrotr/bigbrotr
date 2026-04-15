"""
Unit tests for models.nips.nip66.http module.

Tests:
- Nip66HttpMetadata._http() - async HTTP header capture
- Nip66HttpMetadata.probe() - async HTTP check with proxy support
- Server and X-Powered-By header extraction
"""

from __future__ import annotations

import ssl
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from bigbrotr.models import Relay
from bigbrotr.nips.nip66.http import Nip66HttpMetadata


class TestNip66HttpMetadataHttpAsync:
    """Test Nip66HttpMetadata._http() async method."""

    async def test_captures_server_header(self, relay: Relay) -> None:
        """Captures Server header from WebSocket handshake."""
        http_result = {"http_server": "nginx/1.24.0"}

        with patch.object(Nip66HttpMetadata, "_http", return_value=http_result):
            result = await Nip66HttpMetadata.probe(relay, 10.0)

        assert isinstance(result, Nip66HttpMetadata)
        assert result.data.http_server == "nginx/1.24.0"
        assert result.logs.success is True

    async def test_captures_powered_by_header(self, relay: Relay) -> None:
        """Captures X-Powered-By header from WebSocket handshake."""
        http_result = {
            "http_server": "nginx/1.24.0",
            "http_powered_by": "Strfry",
        }

        with patch.object(Nip66HttpMetadata, "_http", return_value=http_result):
            result = await Nip66HttpMetadata.probe(relay, 10.0)

        assert result.data.http_powered_by == "Strfry"

    async def test_empty_headers_returns_empty_dict(self, relay: Relay) -> None:
        """Empty headers returns empty dict."""
        with patch.object(Nip66HttpMetadata, "_http", return_value={}):
            result = await Nip66HttpMetadata.probe(relay, 10.0)

        assert result.data.http_server is None
        assert result.data.http_powered_by is None


class TestNip66HttpMetadataHttp:
    """Test Nip66HttpMetadata.probe() async class method."""

    async def test_clearnet_returns_http_metadata(self, relay: Relay) -> None:
        """Returns Nip66HttpMetadata for clearnet relay."""
        http_result = {
            "http_server": "nginx/1.24.0",
            "http_powered_by": "Strfry",
        }

        with patch.object(Nip66HttpMetadata, "_http", return_value=http_result):
            result = await Nip66HttpMetadata.probe(relay, 10.0)

        assert isinstance(result, Nip66HttpMetadata)
        assert result.data.http_server == "nginx/1.24.0"
        assert result.data.http_powered_by == "Strfry"
        assert result.logs.success is True

    async def test_tor_without_proxy_returns_failure(self, tor_relay: Relay) -> None:
        """Returns failure for Tor relay without proxy."""
        result = await Nip66HttpMetadata.probe(tor_relay, 10.0)
        assert result.logs.success is False
        assert "overlay network tor requires proxy" in result.logs.reason

    async def test_i2p_without_proxy_returns_failure(self, i2p_relay: Relay) -> None:
        """Returns failure for I2P relay without proxy."""
        result = await Nip66HttpMetadata.probe(i2p_relay, 10.0)
        assert result.logs.success is False
        assert "overlay network i2p requires proxy" in result.logs.reason

    async def test_loki_without_proxy_returns_failure(self, loki_relay: Relay) -> None:
        """Returns failure for Lokinet relay without proxy."""
        result = await Nip66HttpMetadata.probe(loki_relay, 10.0)
        assert result.logs.success is False
        assert "overlay network loki requires proxy" in result.logs.reason

    async def test_tor_with_proxy_works(self, tor_relay: Relay) -> None:
        """Tor relay with proxy succeeds."""
        http_result = {"http_server": "nginx/1.24.0"}

        with patch.object(Nip66HttpMetadata, "_http", return_value=http_result):
            result = await Nip66HttpMetadata.probe(
                tor_relay, 10.0, proxy_url="socks5://localhost:9050"
            )

        assert isinstance(result, Nip66HttpMetadata)
        assert result.data.http_server == "nginx/1.24.0"

    async def test_clearnet_with_proxy_works(self, relay: Relay) -> None:
        """Clearnet relay with optional proxy works."""
        http_result = {"http_server": "nginx/1.24.0"}

        with patch.object(Nip66HttpMetadata, "_http", return_value=http_result):
            result = await Nip66HttpMetadata.probe(relay, 10.0, proxy_url="socks5://localhost:9050")

        assert isinstance(result, Nip66HttpMetadata)

    async def test_no_headers_returns_failure(self, relay: Relay) -> None:
        """No HTTP headers returns failure logs."""
        with patch.object(Nip66HttpMetadata, "_http", return_value={}):
            result = await Nip66HttpMetadata.probe(relay, 10.0)

        assert isinstance(result, Nip66HttpMetadata)
        assert result.logs.success is False
        assert "no HTTP headers captured" in result.logs.reason

    async def test_exception_returns_failure(self, relay: Relay) -> None:
        """Exception during HTTP check returns failure logs."""
        with patch.object(Nip66HttpMetadata, "_http", side_effect=OSError("Connection timeout")):
            result = await Nip66HttpMetadata.probe(relay, 10.0)

        assert isinstance(result, Nip66HttpMetadata)
        assert result.logs.success is False
        assert "Connection timeout" in result.logs.reason

    async def test_uses_default_timeout(self, relay: Relay) -> None:
        """Uses default timeout when None provided."""
        http_result = {"http_server": "nginx/1.24.0"}

        with patch.object(Nip66HttpMetadata, "_http", return_value=http_result) as mock_http:
            await Nip66HttpMetadata.probe(relay, None)

        mock_http.assert_called_once()
        call_args = mock_http.call_args
        assert call_args[0][1] > 0

    async def test_passes_proxy_url_to_http(self, relay: Relay) -> None:
        """Passes proxy_url to _http method."""
        http_result = {"http_server": "nginx/1.24.0"}
        proxy_url = "socks5://localhost:9050"

        with patch.object(Nip66HttpMetadata, "_http", return_value=http_result) as mock_http:
            await Nip66HttpMetadata.probe(relay, 10.0, proxy_url=proxy_url)

        mock_http.assert_called_once()
        call_args = mock_http.call_args
        assert call_args[0][2] == proxy_url  # Third positional arg is proxy_url

    async def test_only_server_header_success(self, relay: Relay) -> None:
        """Success when only Server header is present."""
        http_result = {"http_server": "apache/2.4.41"}

        with patch.object(Nip66HttpMetadata, "_http", return_value=http_result):
            result = await Nip66HttpMetadata.probe(relay, 10.0)

        assert result.logs.success is True
        assert result.data.http_server == "apache/2.4.41"
        assert result.data.http_powered_by is None

    async def test_only_powered_by_header_success(self, relay: Relay) -> None:
        """Success when only X-Powered-By header is present."""
        http_result = {"http_powered_by": "Express"}

        with patch.object(Nip66HttpMetadata, "_http", return_value=http_result):
            result = await Nip66HttpMetadata.probe(relay, 10.0)

        assert result.logs.success is True
        assert result.data.http_server is None
        assert result.data.http_powered_by == "Express"

    async def test_logs_parse_issues_for_invalid_headers(self, relay: Relay, caplog) -> None:
        """Invalid or unknown HTTP fields are logged instead of being dropped silently."""
        http_result = {
            "http_server": 123,
            "http_powered_by": "Express",
            "unknown_field": "ignored",
        }

        with (
            caplog.at_level("WARNING", logger="bigbrotr.nips.nip66"),
            patch.object(Nip66HttpMetadata, "_http", return_value=http_result),
        ):
            result = await Nip66HttpMetadata.probe(relay, 10.0)

        assert result.logs.success is True
        assert result.data.http_server is None
        assert result.data.http_powered_by == "Express"
        assert "nip_parse_issues" in caplog.text
        assert "http_server" in caplog.text
        assert "unknown_field" in caplog.text

    async def test_overlay_relay_with_proxy(self, tor_relay: Relay) -> None:
        """ws:// overlay relay works for HTTP check with proxy."""
        http_result = {"http_server": "nginx/1.24.0"}

        with patch.object(Nip66HttpMetadata, "_http", return_value=http_result):
            result = await Nip66HttpMetadata.probe(
                tor_relay, 10.0, proxy_url="socks5://localhost:9050"
            )

        assert isinstance(result, Nip66HttpMetadata)
        assert result.logs.success is True


class TestNip66HttpMetadataInternalHttp:
    """Test _http() internals via probe() without mocking _http itself."""

    @staticmethod
    def _make_session_mock(
        response_headers: dict[str, str] | None = None,
    ) -> tuple[MagicMock, object]:
        """Build a mock ClientSession factory that fires trace hooks during ws_connect."""
        headers = response_headers or {}
        stored_trace_configs: list[Any] = []

        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock()

        mock_session = MagicMock()

        class _WsContextManager:
            async def __aenter__(self) -> AsyncMock:
                mock_response = MagicMock()
                mock_response.headers = headers
                params = MagicMock()
                params.response = mock_response
                for tc in stored_trace_configs:
                    for cb in tc.on_request_end:
                        await cb(mock_session, SimpleNamespace(), params)
                return mock_ws

            async def __aexit__(self, *args: object) -> bool:
                return False

        mock_session.ws_connect = MagicMock(return_value=_WsContextManager())
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        def session_factory(*args: object, **kwargs: object) -> MagicMock:
            trace_configs = kwargs.get("trace_configs", [])
            stored_trace_configs.clear()
            stored_trace_configs.extend(trace_configs)
            return mock_session

        return mock_session, session_factory

    async def test_captures_server_header_from_handshake(self, relay: Relay) -> None:
        """Server header captured via trace hook produces http_server in result."""
        _, factory = self._make_session_mock({"Server": "nginx/1.24.0"})

        with patch("bigbrotr.nips.nip66.http.aiohttp.ClientSession", side_effect=factory):
            result = await Nip66HttpMetadata.probe(relay, 10.0)

        assert result.data.http_server == "nginx/1.24.0"
        assert result.logs.success is True

    async def test_captures_powered_by_header(self, relay: Relay) -> None:
        """X-Powered-By header captured via trace hook produces http_powered_by."""
        _, factory = self._make_session_mock({"X-Powered-By": "Strfry"})

        with patch("bigbrotr.nips.nip66.http.aiohttp.ClientSession", side_effect=factory):
            result = await Nip66HttpMetadata.probe(relay, 10.0)

        assert result.data.http_powered_by == "Strfry"
        assert result.logs.success is True

    async def test_no_headers_returns_empty_dict(self, relay: Relay) -> None:
        """No Server or X-Powered-By headers yields failure with empty data."""
        _, factory = self._make_session_mock({})

        with patch("bigbrotr.nips.nip66.http.aiohttp.ClientSession", side_effect=factory):
            result = await Nip66HttpMetadata.probe(relay, 10.0)

        assert result.data.http_server is None
        assert result.data.http_powered_by is None
        assert result.logs.success is False
        assert "no HTTP headers captured" in result.logs.reason

    async def test_clearnet_uses_tcp_connector(self, relay: Relay) -> None:
        """Clearnet relay creates TCPConnector, not ProxyConnector."""
        _, factory = self._make_session_mock({"Server": "nginx"})

        with (
            patch("bigbrotr.nips.nip66.http.aiohttp.ClientSession", side_effect=factory),
            patch("bigbrotr.nips.nip66.http.aiohttp.TCPConnector") as mock_tcp,
        ):
            await Nip66HttpMetadata.probe(relay, 10.0)

        mock_tcp.assert_called_once()
        ssl_ctx = mock_tcp.call_args[1]["ssl"]
        assert ssl_ctx.check_hostname is True
        assert ssl_ctx.verify_mode == ssl.CERT_REQUIRED

    async def test_overlay_uses_insecure_ssl(self, tor_relay: Relay) -> None:
        """Overlay relay sets CERT_NONE on ssl context."""
        _, factory = self._make_session_mock({"Server": "nginx"})

        with (
            patch("bigbrotr.nips.nip66.http.aiohttp.ClientSession", side_effect=factory),
            patch("bigbrotr.nips.nip66.http.ProxyConnector.from_url") as mock_proxy,
        ):
            mock_proxy.return_value = MagicMock()
            await Nip66HttpMetadata.probe(tor_relay, 10.0, proxy_url="socks5://localhost:9050")

        mock_proxy.assert_called_once()
        ssl_ctx = mock_proxy.call_args[1]["ssl"]
        assert ssl_ctx.check_hostname is False
        assert ssl_ctx.verify_mode == ssl.CERT_NONE

    async def test_proxy_uses_proxy_connector(self, relay: Relay) -> None:
        """When proxy_url provided, ProxyConnector.from_url is used."""
        _, factory = self._make_session_mock({"Server": "nginx"})

        with (
            patch("bigbrotr.nips.nip66.http.aiohttp.ClientSession", side_effect=factory),
            patch("bigbrotr.nips.nip66.http.ProxyConnector.from_url") as mock_proxy,
        ):
            mock_proxy.return_value = MagicMock()
            await Nip66HttpMetadata.probe(relay, 10.0, proxy_url="socks5://localhost:9050")

        mock_proxy.assert_called_once_with(
            "socks5://localhost:9050", ssl=mock_proxy.call_args[1]["ssl"]
        )
