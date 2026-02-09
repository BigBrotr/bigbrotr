"""
Unit tests for utils.transport module.

Tests:
- _is_ssl_error() - SSL error detection from error messages
- create_client() - Client factory with optional proxy
- create_insecure_client() - Client factory with SSL verification disabled
- connect_relay() - Relay connection with SSL fallback
- is_nostr_relay() - Relay validation
- InsecureWebSocketAdapter - WebSocket adapter for insecure connections
- InsecureWebSocketTransport - Custom transport with SSL disabled
"""

import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bigbrotr.models.constants import NetworkType
from bigbrotr.models.relay import Relay
from bigbrotr.utils.transport import (
    InsecureWebSocketAdapter,
    InsecureWebSocketTransport,
    _is_ssl_error,
    create_client,
    create_insecure_client,
)


# =============================================================================
# _is_ssl_error() Tests
# =============================================================================


class TestIsSslErrorKeywordDetection:
    """Tests for _is_ssl_error() keyword detection."""

    def test_ssl_keyword(self) -> None:
        """Test detection of 'ssl' keyword."""
        assert _is_ssl_error("SSL handshake failed") is True

    def test_tls_keyword(self) -> None:
        """Test detection of 'tls' keyword."""
        assert _is_ssl_error("TLS connection error") is True

    def test_certificate_keyword(self) -> None:
        """Test detection of 'certificate' keyword."""
        assert _is_ssl_error("Certificate verification failed") is True

    def test_cert_keyword(self) -> None:
        """Test detection of 'cert' keyword."""
        assert _is_ssl_error("Invalid cert") is True

    def test_x509_keyword(self) -> None:
        """Test detection of 'x509' keyword."""
        assert _is_ssl_error("X509 error occurred") is True

    def test_handshake_keyword(self) -> None:
        """Test detection of 'handshake' keyword."""
        assert _is_ssl_error("Handshake timeout") is True

    def test_verify_keyword(self) -> None:
        """Test detection of 'verify' keyword."""
        assert _is_ssl_error("Could not verify server") is True


class TestIsSslErrorCaseInsensitive:
    """Tests that _is_ssl_error() is case insensitive."""

    def test_uppercase_ssl(self) -> None:
        """Test detection of uppercase 'SSL'."""
        assert _is_ssl_error("SSL ERROR") is True

    def test_mixed_case_certificate(self) -> None:
        """Test detection of mixed case 'Certificate'."""
        assert _is_ssl_error("Certificate") is True

    def test_uppercase_handshake(self) -> None:
        """Test detection of uppercase 'HANDSHAKE'."""
        assert _is_ssl_error("HANDSHAKE FAILED") is True

    def test_lowercase_keywords(self) -> None:
        """Test detection of all lowercase keywords."""
        assert _is_ssl_error("ssl tls certificate cert x509 handshake verify") is True


class TestIsSslErrorNonSslErrors:
    """Tests that _is_ssl_error() returns False for non-SSL errors."""

    def test_connection_refused(self) -> None:
        """Test connection refused is not an SSL error."""
        assert _is_ssl_error("Connection refused") is False

    def test_timeout(self) -> None:
        """Test timeout is not an SSL error."""
        assert _is_ssl_error("Connection timeout") is False

    def test_dns(self) -> None:
        """Test DNS error is not an SSL error."""
        assert _is_ssl_error("DNS resolution failed") is False

    def test_empty_string(self) -> None:
        """Test empty string is not an SSL error."""
        assert _is_ssl_error("") is False

    def test_generic_error(self) -> None:
        """Test generic error is not an SSL error."""
        assert _is_ssl_error("Something went wrong") is False


class TestIsSslErrorRealMessages:
    """Tests for _is_ssl_error() with realistic error messages."""

    def test_ssl_cert_verification_error(self) -> None:
        """Test detection of Python ssl.SSLCertVerificationError message."""
        msg = "Error: ssl.SSLCertVerificationError: certificate verify failed"
        assert _is_ssl_error(msg) is True

    def test_openssl_error(self) -> None:
        """Test detection of OpenSSL error message."""
        msg = "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"
        assert _is_ssl_error(msg) is True

    def test_expired_certificate(self) -> None:
        """Test detection of expired certificate message."""
        assert _is_ssl_error("certificate has expired") is True

    def test_self_signed_certificate(self) -> None:
        """Test detection of self-signed certificate message."""
        assert _is_ssl_error("self signed certificate in certificate chain") is True


# =============================================================================
# create_client() Tests
# =============================================================================


class TestCreateClientBasic:
    """Tests for create_client() basic functionality."""

    def test_creates_client_without_keys(self) -> None:
        """Test creating client without keys (read-only)."""
        client = create_client()
        assert client is not None

    def test_creates_client_with_keys(self) -> None:
        """Test creating client with keys for signing."""
        from nostr_sdk import Keys

        keys = Keys.generate()
        client = create_client(keys=keys)
        assert client is not None


class TestCreateClientProxy:
    """Tests for create_client() with proxy configuration."""

    def test_creates_client_with_proxy_url_ip(self) -> None:
        """Test creating client with IP address proxy."""
        client = create_client(proxy_url="socks5://127.0.0.1:9050")
        assert client is not None

    def test_creates_client_with_keys_and_proxy(self) -> None:
        """Test creating client with both keys and proxy."""
        from nostr_sdk import Keys

        keys = Keys.generate()
        client = create_client(keys=keys, proxy_url="socks5://127.0.0.1:9050")
        assert client is not None

    def test_proxy_hostname_resolved(self) -> None:
        """Test proxy hostname is resolved to IP."""
        with patch("socket.gethostbyname", return_value="127.0.0.1"):
            client = create_client(proxy_url="socks5://tor:9050")
            assert client is not None

    def test_proxy_ip_not_resolved(self) -> None:
        """Test IP address proxy does not call gethostbyname."""
        with patch("socket.gethostbyname") as mock_resolve:
            client = create_client(proxy_url="socks5://127.0.0.1:9050")
            assert client is not None
            mock_resolve.assert_not_called()

    def test_proxy_default_port(self) -> None:
        """Test proxy URL without explicit port uses default."""
        with patch("socket.gethostbyname", return_value="127.0.0.1"):
            client = create_client(proxy_url="socks5://127.0.0.1")
            assert client is not None


# =============================================================================
# create_insecure_client() Tests
# =============================================================================


class TestCreateInsecureClient:
    """Tests for create_insecure_client() factory function."""

    def test_creates_client_without_keys(self) -> None:
        """Test creating insecure client without keys."""
        client = create_insecure_client()
        assert client is not None

    def test_creates_client_with_keys(self) -> None:
        """Test creating insecure client with keys."""
        from nostr_sdk import Keys

        keys = Keys.generate()
        client = create_insecure_client(keys=keys)
        assert client is not None


# =============================================================================
# connect_relay() Tests - Overlay Networks
# =============================================================================


class TestConnectRelayOverlayNetworks:
    """Tests for connect_relay() with overlay networks (Tor, I2P, Loki)."""

    @pytest.mark.asyncio
    async def test_tor_requires_proxy(self) -> None:
        """Test Tor relay requires proxy_url."""
        relay = Relay("wss://example.onion")

        with pytest.raises(ValueError) as exc_info:
            from bigbrotr.utils.transport import connect_relay

            await connect_relay(relay, proxy_url=None)

        assert "proxy_url required" in str(exc_info.value)
        assert "tor" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_i2p_requires_proxy(self) -> None:
        """Test I2P relay requires proxy_url."""
        relay = Relay("wss://example.i2p")

        with pytest.raises(ValueError) as exc_info:
            from bigbrotr.utils.transport import connect_relay

            await connect_relay(relay, proxy_url=None)

        assert "proxy_url required" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_loki_requires_proxy(self) -> None:
        """Test Lokinet relay requires proxy_url."""
        relay = Relay("wss://example.loki")

        with pytest.raises(ValueError) as exc_info:
            from bigbrotr.utils.transport import connect_relay

            await connect_relay(relay, proxy_url=None)

        assert "proxy_url required" in str(exc_info.value)


# =============================================================================
# connect_relay() Tests - Clearnet
# =============================================================================


class TestConnectRelayClearnet:
    """Tests for connect_relay() with clearnet relays."""

    @pytest.mark.asyncio
    async def test_ssl_error_fallback_disabled_raises(self) -> None:
        """Test SSL errors raise when allow_insecure=False."""
        relay = Relay("wss://relay.example.com")

        mock_url = MagicMock()
        mock_output = MagicMock()
        mock_output.success = []
        mock_output.failed = {mock_url: "SSL certificate verify failed"}

        with (
            patch("bigbrotr.utils.transport.create_client") as mock_create,
            patch("bigbrotr.utils.transport.RelayUrl") as mock_relay_url,
        ):
            mock_client = AsyncMock()
            mock_client.try_connect = AsyncMock(return_value=mock_output)
            mock_client.disconnect = AsyncMock()
            mock_create.return_value = mock_client

            mock_relay_url.parse.return_value = mock_url

            from bigbrotr.utils.transport import connect_relay

            with pytest.raises(ssl.SSLCertVerificationError):
                await connect_relay(relay, allow_insecure=False)

    @pytest.mark.asyncio
    async def test_clearnet_no_proxy_required(self) -> None:
        """Test clearnet relay does not require proxy."""
        relay = Relay("wss://relay.example.com")
        assert relay.network == NetworkType.CLEARNET

        mock_url = MagicMock()
        mock_output = MagicMock()
        mock_output.success = [mock_url]
        mock_output.failed = {}

        with (
            patch("bigbrotr.utils.transport.create_client") as mock_create,
            patch("bigbrotr.utils.transport.RelayUrl") as mock_relay_url,
        ):
            mock_client = AsyncMock()
            mock_client.try_connect = AsyncMock(return_value=mock_output)
            mock_create.return_value = mock_client

            mock_relay_url.parse.return_value = mock_url

            from bigbrotr.utils.transport import connect_relay

            client = await connect_relay(relay)
            assert client is mock_client


# =============================================================================
# is_nostr_relay() Tests
# =============================================================================


class TestIsNostrRelayMocked:
    """Tests for is_nostr_relay() with mocked connections."""

    @pytest.mark.asyncio
    async def test_valid_relay_returns_true(self) -> None:
        """Test relay that responds with EOSE is valid."""
        relay = Relay("wss://relay.example.com")

        with patch("bigbrotr.utils.transport.connect_relay") as mock_connect:
            mock_client = AsyncMock()
            mock_client.fetch_events = AsyncMock(return_value=[])
            mock_client.disconnect = AsyncMock()
            mock_connect.return_value = mock_client

            from bigbrotr.utils.transport import is_nostr_relay

            result = await is_nostr_relay(relay)
            assert result is True

    @pytest.mark.asyncio
    async def test_auth_required_is_valid(self) -> None:
        """Test relay that requires AUTH (NIP-42) is still valid."""
        relay = Relay("wss://relay.example.com")

        with patch("bigbrotr.utils.transport.connect_relay") as mock_connect:
            mock_connect.side_effect = OSError("auth-required: please authenticate")

            from bigbrotr.utils.transport import is_nostr_relay

            result = await is_nostr_relay(relay)
            assert result is True

    @pytest.mark.asyncio
    async def test_connection_error_is_invalid(self) -> None:
        """Test relay that fails to connect is invalid."""
        relay = Relay("wss://relay.example.com")

        with patch("bigbrotr.utils.transport.connect_relay") as mock_connect:
            mock_connect.side_effect = OSError("Connection refused")

            from bigbrotr.utils.transport import is_nostr_relay

            result = await is_nostr_relay(relay)
            assert result is False

    @pytest.mark.asyncio
    async def test_timeout_error_is_invalid(self) -> None:
        """Test relay that times out is invalid."""
        relay = Relay("wss://relay.example.com")

        with patch("bigbrotr.utils.transport.connect_relay") as mock_connect:
            mock_connect.side_effect = TimeoutError("Connection timed out")

            from bigbrotr.utils.transport import is_nostr_relay

            result = await is_nostr_relay(relay)
            assert result is False

    @pytest.mark.asyncio
    async def test_passes_proxy_url(self) -> None:
        """Test proxy URL is passed to connect_relay."""
        relay = Relay("wss://example.onion")

        with patch("bigbrotr.utils.transport.connect_relay") as mock_connect:
            mock_client = AsyncMock()
            mock_client.fetch_events = AsyncMock(return_value=[])
            mock_client.disconnect = AsyncMock()
            mock_connect.return_value = mock_client

            from bigbrotr.utils.transport import is_nostr_relay

            await is_nostr_relay(relay, proxy_url="socks5://127.0.0.1:9050")

            mock_connect.assert_called_once()
            call_kwargs = mock_connect.call_args[1]
            assert call_kwargs["proxy_url"] == "socks5://127.0.0.1:9050"

    @pytest.mark.asyncio
    async def test_uses_custom_timeout(self) -> None:
        """Test custom timeout is passed to connect_relay."""
        relay = Relay("wss://relay.example.com")

        with patch("bigbrotr.utils.transport.connect_relay") as mock_connect:
            mock_client = AsyncMock()
            mock_client.fetch_events = AsyncMock(return_value=[])
            mock_client.disconnect = AsyncMock()
            mock_connect.return_value = mock_client

            from bigbrotr.utils.transport import is_nostr_relay

            await is_nostr_relay(relay, timeout=30.0)

            mock_connect.assert_called_once()
            call_kwargs = mock_connect.call_args[1]
            assert call_kwargs["timeout"] == 30.0


class TestIsNostrRelayDisconnect:
    """Tests that is_nostr_relay() properly disconnects after validation."""

    @pytest.mark.asyncio
    async def test_disconnect_called_on_success(self) -> None:
        """Test disconnect is called after successful validation."""
        relay = Relay("wss://relay.example.com")

        with patch("bigbrotr.utils.transport.connect_relay") as mock_connect:
            mock_client = AsyncMock()
            mock_client.fetch_events = AsyncMock(return_value=[])
            mock_client.disconnect = AsyncMock()
            mock_connect.return_value = mock_client

            from bigbrotr.utils.transport import is_nostr_relay

            await is_nostr_relay(relay)

            mock_client.disconnect.assert_called_once()


# =============================================================================
# InsecureWebSocketAdapter Tests
# =============================================================================


class TestInsecureWebSocketAdapterSend:
    """Tests for InsecureWebSocketAdapter.send() method."""

    @pytest.mark.asyncio
    async def test_send_text_message(self) -> None:
        """Test sending text message via WebSocket."""
        from nostr_sdk import WebSocketMessage

        mock_ws = AsyncMock()
        mock_session = AsyncMock()
        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)

        msg = WebSocketMessage.TEXT("test message")
        await adapter.send(msg)

        mock_ws.send_str.assert_called_once_with("test message")

    @pytest.mark.asyncio
    async def test_send_binary_message(self) -> None:
        """Test sending binary message via WebSocket."""
        from nostr_sdk import WebSocketMessage

        mock_ws = AsyncMock()
        mock_session = AsyncMock()
        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)

        msg = WebSocketMessage.BINARY(b"binary data")
        await adapter.send(msg)

        mock_ws.send_bytes.assert_called_once_with(b"binary data")

    @pytest.mark.asyncio
    async def test_send_ping_message(self) -> None:
        """Test sending ping message via WebSocket."""
        from nostr_sdk import WebSocketMessage

        mock_ws = AsyncMock()
        mock_session = AsyncMock()
        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)

        msg = WebSocketMessage.PING(b"ping data")
        await adapter.send(msg)

        mock_ws.ping.assert_called_once_with(b"ping data")

    @pytest.mark.asyncio
    async def test_send_pong_message(self) -> None:
        """Test sending pong message via WebSocket."""
        from nostr_sdk import WebSocketMessage

        mock_ws = AsyncMock()
        mock_session = AsyncMock()
        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)

        msg = WebSocketMessage.PONG(b"pong data")
        await adapter.send(msg)

        mock_ws.pong.assert_called_once_with(b"pong data")


class TestInsecureWebSocketAdapterReceive:
    """Tests for InsecureWebSocketAdapter.recv() method."""

    @pytest.mark.asyncio
    async def test_recv_text_message(self) -> None:
        """Test receiving text message from WebSocket."""
        import aiohttp

        mock_ws = AsyncMock()
        mock_session = AsyncMock()

        mock_msg = MagicMock()
        mock_msg.type = aiohttp.WSMsgType.TEXT
        mock_msg.data = "received text"
        mock_ws.receive = AsyncMock(return_value=mock_msg)

        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)
        result = await adapter.recv()

        assert result is not None
        assert result.is_text()
        assert result.text == "received text"

    @pytest.mark.asyncio
    async def test_recv_binary_message(self) -> None:
        """Test receiving binary message from WebSocket."""
        import aiohttp

        mock_ws = AsyncMock()
        mock_session = AsyncMock()

        mock_msg = MagicMock()
        mock_msg.type = aiohttp.WSMsgType.BINARY
        mock_msg.data = b"received binary"
        mock_ws.receive = AsyncMock(return_value=mock_msg)

        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)
        result = await adapter.recv()

        assert result is not None
        assert result.is_binary()

    @pytest.mark.asyncio
    async def test_recv_close_returns_none(self) -> None:
        """Test close message returns None."""
        import aiohttp

        mock_ws = AsyncMock()
        mock_session = AsyncMock()

        mock_msg = MagicMock()
        mock_msg.type = aiohttp.WSMsgType.CLOSE
        mock_ws.receive = AsyncMock(return_value=mock_msg)

        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)
        result = await adapter.recv()

        assert result is None

    @pytest.mark.asyncio
    async def test_recv_timeout_returns_none(self) -> None:
        """Test timeout returns None."""

        mock_ws = AsyncMock()
        mock_session = AsyncMock()
        mock_ws.receive = AsyncMock(side_effect=TimeoutError())

        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)
        result = await adapter.recv()

        assert result is None


class TestInsecureWebSocketAdapterClose:
    """Tests for InsecureWebSocketAdapter.close_connection() method."""

    @pytest.mark.asyncio
    async def test_close_connection(self) -> None:
        """Test closing both WebSocket and session."""
        mock_ws = AsyncMock()
        mock_session = AsyncMock()
        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)

        await adapter.close_connection()

        mock_ws.close.assert_called_once()
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_handles_ws_exception(self) -> None:
        """Test handling exception during WebSocket close."""
        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock(side_effect=Exception("close failed"))
        mock_session = AsyncMock()
        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)

        await adapter.close_connection()

        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_handles_session_exception(self) -> None:
        """Test handling exception during session close."""
        mock_ws = AsyncMock()
        mock_session = AsyncMock()
        mock_session.close = AsyncMock(side_effect=Exception("session close failed"))
        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)

        await adapter.close_connection()


# =============================================================================
# InsecureWebSocketTransport Tests
# =============================================================================


class TestInsecureWebSocketTransport:
    """Tests for InsecureWebSocketTransport class."""

    def test_support_ping(self) -> None:
        """Test transport supports ping frames."""
        transport = InsecureWebSocketTransport()
        assert transport.support_ping() is True


class TestInsecureWebSocketTransportConnect:
    """Tests for InsecureWebSocketTransport.connect() method."""

    @pytest.mark.asyncio
    async def test_connect_creates_ssl_context(self) -> None:
        """Test connect creates an insecure SSL context."""
        from datetime import timedelta

        from bigbrotr.utils.transport import InsecureWebSocketTransport

        transport = InsecureWebSocketTransport()

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_ws = AsyncMock()
            mock_session.ws_connect = AsyncMock(return_value=mock_ws)
            mock_session_class.return_value = mock_session

            mock_mode = MagicMock()

            await transport.connect("wss://test.com", mock_mode, timedelta(seconds=10))

            mock_session_class.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_client_error_raises_os_error(self) -> None:
        """Test client error raises OSError."""
        from datetime import timedelta

        import aiohttp

        from bigbrotr.utils.transport import InsecureWebSocketTransport

        transport = InsecureWebSocketTransport()

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session.ws_connect = AsyncMock(
                side_effect=aiohttp.ClientError("connection failed")
            )
            mock_session.close = AsyncMock()
            mock_session_class.return_value = mock_session

            mock_mode = MagicMock()

            with pytest.raises(OSError) as exc_info:
                await transport.connect("wss://test.com", mock_mode, timedelta(seconds=10))

            assert "Connection failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_connect_timeout_raises_os_error(self) -> None:
        """Test timeout raises OSError."""
        from datetime import timedelta

        from bigbrotr.utils.transport import InsecureWebSocketTransport

        transport = InsecureWebSocketTransport()

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session.ws_connect = AsyncMock(side_effect=TimeoutError())
            mock_session.close = AsyncMock()
            mock_session_class.return_value = mock_session

            mock_mode = MagicMock()

            with pytest.raises(OSError) as exc_info:
                await transport.connect("wss://test.com", mock_mode, timedelta(seconds=10))

            assert "timeout" in str(exc_info.value).lower()
