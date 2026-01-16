"""
Unit tests for utils.transport module.

Tests:
- _is_ssl_error() - SSL error detection
- create_client() - Client factory
- create_insecure_client() - Insecure client factory
- connect_relay() - Relay connection with fallback
- is_nostr_relay() - Relay validation
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.relay import Relay
from utils.transport import (
    _is_ssl_error,
    create_client,
    create_insecure_client,
)


# =============================================================================
# _is_ssl_error() Tests
# =============================================================================


class TestIsSslError:
    """_is_ssl_error() function."""

    def test_ssl_keyword(self):
        assert _is_ssl_error("SSL handshake failed") is True

    def test_tls_keyword(self):
        assert _is_ssl_error("TLS connection error") is True

    def test_certificate_keyword(self):
        assert _is_ssl_error("Certificate verification failed") is True

    def test_cert_keyword(self):
        assert _is_ssl_error("Invalid cert") is True

    def test_x509_keyword(self):
        assert _is_ssl_error("X509 error occurred") is True

    def test_handshake_keyword(self):
        assert _is_ssl_error("Handshake timeout") is True

    def test_verify_keyword(self):
        assert _is_ssl_error("Could not verify server") is True

    def test_case_insensitive(self):
        assert _is_ssl_error("SSL ERROR") is True
        assert _is_ssl_error("Certificate") is True
        assert _is_ssl_error("HANDSHAKE FAILED") is True

    def test_not_ssl_error_connection_refused(self):
        assert _is_ssl_error("Connection refused") is False

    def test_not_ssl_error_timeout(self):
        assert _is_ssl_error("Connection timeout") is False

    def test_not_ssl_error_dns(self):
        assert _is_ssl_error("DNS resolution failed") is False

    def test_not_ssl_error_empty_string(self):
        assert _is_ssl_error("") is False

    def test_ssl_in_context(self):
        assert (
            _is_ssl_error("Error: ssl.SSLCertVerificationError: certificate verify failed") is True
        )


# =============================================================================
# create_client() Tests
# =============================================================================


class TestCreateClient:
    """create_client() factory function."""

    def test_creates_client_without_keys(self):
        client = create_client()
        assert client is not None

    def test_creates_client_with_keys(self):
        from nostr_sdk import Keys

        keys = Keys.generate()
        client = create_client(keys=keys)
        assert client is not None

    def test_creates_client_with_proxy_url(self):
        # Use IP address to avoid DNS resolution
        client = create_client(proxy_url="socks5://127.0.0.1:9050")
        assert client is not None

    def test_creates_client_with_keys_and_proxy(self):
        from nostr_sdk import Keys

        keys = Keys.generate()
        client = create_client(keys=keys, proxy_url="socks5://127.0.0.1:9050")
        assert client is not None

    def test_proxy_hostname_resolved(self):
        # Should not raise even with hostname (resolved to IP internally)
        with patch("socket.gethostbyname", return_value="127.0.0.1"):
            client = create_client(proxy_url="socks5://tor:9050")
            assert client is not None

    def test_proxy_ip_not_resolved(self):
        # Should not call gethostbyname for IP addresses
        with patch("socket.gethostbyname") as mock_resolve:
            client = create_client(proxy_url="socks5://127.0.0.1:9050")
            assert client is not None
            mock_resolve.assert_not_called()


# =============================================================================
# create_insecure_client() Tests
# =============================================================================


class TestCreateInsecureClient:
    """create_insecure_client() factory function."""

    def test_creates_client_without_keys(self):
        client = create_insecure_client()
        assert client is not None

    def test_creates_client_with_keys(self):
        from nostr_sdk import Keys

        keys = Keys.generate()
        client = create_insecure_client(keys=keys)
        assert client is not None


# =============================================================================
# connect_relay() Tests
# =============================================================================


class TestConnectRelayOverlay:
    """connect_relay() with overlay networks."""

    @pytest.mark.asyncio
    async def test_overlay_requires_proxy(self):
        relay = Relay("wss://example.onion")

        with pytest.raises(ValueError) as exc_info:
            from utils.transport import connect_relay

            await connect_relay(relay, proxy_url=None)

        assert "proxy_url required" in str(exc_info.value)
        assert "tor" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_i2p_requires_proxy(self):
        relay = Relay("wss://example.i2p")

        with pytest.raises(ValueError) as exc_info:
            from utils.transport import connect_relay

            await connect_relay(relay, proxy_url=None)

        assert "proxy_url required" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_loki_requires_proxy(self):
        relay = Relay("wss://example.loki")

        with pytest.raises(ValueError) as exc_info:
            from utils.transport import connect_relay

            await connect_relay(relay, proxy_url=None)

        assert "proxy_url required" in str(exc_info.value)


class TestConnectRelayClearnet:
    """connect_relay() with clearnet relays."""

    @pytest.mark.asyncio
    async def test_ssl_error_fallback_disabled_raises(self):
        """When allow_insecure=False, SSL errors should raise."""
        relay = Relay("wss://relay.example.com")

        # Mock client that fails with SSL error
        mock_output = MagicMock()
        mock_output.success = []
        mock_output.failed = {MagicMock(): "SSL certificate verify failed"}

        with (
            patch("utils.transport.create_client") as mock_create,
            patch("utils.transport.RelayUrl") as mock_relay_url,
        ):
            mock_client = AsyncMock()
            mock_client.try_connect = AsyncMock(return_value=mock_output)
            mock_client.disconnect = AsyncMock()
            mock_create.return_value = mock_client

            mock_url = MagicMock()
            mock_relay_url.parse.return_value = mock_url
            mock_output.failed = {mock_url: "SSL certificate verify failed"}

            import ssl

            from utils.transport import connect_relay

            with pytest.raises(ssl.SSLCertVerificationError):
                await connect_relay(relay, allow_insecure=False)


# =============================================================================
# is_nostr_relay() Tests
# =============================================================================


class TestIsNostrRelayMocked:
    """is_nostr_relay() with mocked connections."""

    @pytest.mark.asyncio
    async def test_valid_relay_returns_true(self):
        """Relay that responds with EOSE is valid."""
        relay = Relay("wss://relay.example.com")

        with patch("utils.transport.connect_relay") as mock_connect:
            mock_client = AsyncMock()
            mock_client.fetch_events = AsyncMock(return_value=[])
            mock_client.disconnect = AsyncMock()
            mock_connect.return_value = mock_client

            from utils.transport import is_nostr_relay

            result = await is_nostr_relay(relay)
            assert result is True

    @pytest.mark.asyncio
    async def test_auth_required_is_valid(self):
        """Relay that requires AUTH is still valid."""
        relay = Relay("wss://relay.example.com")

        with patch("utils.transport.connect_relay") as mock_connect:
            mock_connect.side_effect = Exception("auth-required: please authenticate")

            from utils.transport import is_nostr_relay

            result = await is_nostr_relay(relay)
            assert result is True

    @pytest.mark.asyncio
    async def test_connection_error_is_invalid(self):
        """Relay that fails to connect is invalid."""
        relay = Relay("wss://relay.example.com")

        with patch("utils.transport.connect_relay") as mock_connect:
            mock_connect.side_effect = Exception("Connection refused")

            from utils.transport import is_nostr_relay

            result = await is_nostr_relay(relay)
            assert result is False

    @pytest.mark.asyncio
    async def test_timeout_error_is_invalid(self):
        """Relay that times out is invalid."""
        relay = Relay("wss://relay.example.com")

        with patch("utils.transport.connect_relay") as mock_connect:
            mock_connect.side_effect = TimeoutError("Connection timed out")

            from utils.transport import is_nostr_relay

            result = await is_nostr_relay(relay)
            assert result is False

    @pytest.mark.asyncio
    async def test_passes_proxy_url(self):
        """Proxy URL is passed to connect_relay."""
        relay = Relay("wss://example.onion")

        with patch("utils.transport.connect_relay") as mock_connect:
            mock_client = AsyncMock()
            mock_client.fetch_events = AsyncMock(return_value=[])
            mock_client.disconnect = AsyncMock()
            mock_connect.return_value = mock_client

            from utils.transport import is_nostr_relay

            await is_nostr_relay(relay, proxy_url="socks5://127.0.0.1:9050")

            mock_connect.assert_called_once()
            call_kwargs = mock_connect.call_args[1]
            assert call_kwargs["proxy_url"] == "socks5://127.0.0.1:9050"

    @pytest.mark.asyncio
    async def test_uses_custom_timeout(self):
        """Custom timeout is passed to connect_relay."""
        relay = Relay("wss://relay.example.com")

        with patch("utils.transport.connect_relay") as mock_connect:
            mock_client = AsyncMock()
            mock_client.fetch_events = AsyncMock(return_value=[])
            mock_client.disconnect = AsyncMock()
            mock_connect.return_value = mock_client

            from utils.transport import is_nostr_relay

            await is_nostr_relay(relay, timeout=30.0)

            mock_connect.assert_called_once()
            call_kwargs = mock_connect.call_args[1]
            assert call_kwargs["timeout"] == 30.0


# =============================================================================
# InsecureWebSocketAdapter Tests
# =============================================================================


class TestInsecureWebSocketAdapter:
    """InsecureWebSocketAdapter class."""

    @pytest.mark.asyncio
    async def test_send_text_message(self):
        from nostr_sdk import WebSocketMessage

        from utils.transport import InsecureWebSocketAdapter

        mock_ws = AsyncMock()
        mock_session = AsyncMock()
        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)

        msg = WebSocketMessage.TEXT("test message")
        await adapter.send(msg)

        mock_ws.send_str.assert_called_once_with("test message")

    @pytest.mark.asyncio
    async def test_send_binary_message(self):
        from nostr_sdk import WebSocketMessage

        from utils.transport import InsecureWebSocketAdapter

        mock_ws = AsyncMock()
        mock_session = AsyncMock()
        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)

        msg = WebSocketMessage.BINARY(b"binary data")
        await adapter.send(msg)

        mock_ws.send_bytes.assert_called_once_with(b"binary data")

    @pytest.mark.asyncio
    async def test_close_connection(self):
        from utils.transport import InsecureWebSocketAdapter

        mock_ws = AsyncMock()
        mock_session = AsyncMock()
        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)

        await adapter.close_connection()

        mock_ws.close.assert_called_once()
        mock_session.close.assert_called_once()


# =============================================================================
# InsecureWebSocketTransport Tests
# =============================================================================


class TestInsecureWebSocketTransport:
    """InsecureWebSocketTransport class."""

    def test_support_ping(self):
        from utils.transport import InsecureWebSocketTransport

        transport = InsecureWebSocketTransport()
        assert transport.support_ping() is True
