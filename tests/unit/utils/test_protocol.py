"""
Unit tests for utils.protocol module.

Tests:
- _is_ssl_error() - SSL error detection from error messages
- create_client() - Client factory with optional proxy and SSL override
- connect_relay() - Relay connection with SSL fallback
- is_nostr_relay() - Relay validation
- broadcast_events() - Event broadcasting to relays
"""

import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nostr_sdk import Keys

from bigbrotr.models.constants import NetworkType
from bigbrotr.models.relay import Relay
from bigbrotr.utils.protocol import (
    _is_ssl_error,
    create_client,
)


# =============================================================================
# _is_ssl_error() Tests
# =============================================================================


class TestIsSslErrorPatternDetection:
    """Tests for _is_ssl_error() multi-word pattern detection."""

    def test_ssl_handshake(self) -> None:
        """Test detection of 'ssl handshake' pattern."""
        assert _is_ssl_error("SSL handshake failed") is True

    def test_tls_handshake(self) -> None:
        """Test detection of 'tls handshake failed' pattern."""
        assert _is_ssl_error("TLS handshake failed on connect") is True

    def test_certificate_verify(self) -> None:
        """Test detection of 'certificate verify' pattern."""
        assert _is_ssl_error("certificate verify failed") is True

    def test_cert_verify_failed(self) -> None:
        """Test detection of 'cert verify failed' pattern."""
        assert _is_ssl_error("cert verify failed: unable to get issuer") is True

    def test_x509(self) -> None:
        """Test detection of 'x509' pattern."""
        assert _is_ssl_error("X509 error occurred") is True

    def test_ssl_error(self) -> None:
        """Test detection of 'ssl error' pattern."""
        assert _is_ssl_error("SSL error in connection") is True

    def test_tls_error(self) -> None:
        """Test detection of 'tls error' pattern."""
        assert _is_ssl_error("TLS error: protocol mismatch") is True

    def test_ssl_certificate(self) -> None:
        """Test detection of 'ssl certificate' pattern."""
        assert _is_ssl_error("SSL certificate problem") is True

    def test_single_keyword_no_match(self) -> None:
        """Single keywords without context do not match (reduces false positives)."""
        assert _is_ssl_error("handshake timeout") is False
        assert _is_ssl_error("invalid cert") is False
        assert _is_ssl_error("could not verify server") is False


class TestIsSslErrorCaseInsensitive:
    """Tests that _is_ssl_error() is case insensitive."""

    def test_uppercase_ssl_error(self) -> None:
        """Test detection of uppercase 'SSL ERROR'."""
        assert _is_ssl_error("SSL ERROR") is True

    def test_mixed_case_certificate_verify(self) -> None:
        """Test detection of mixed case 'Certificate Verify'."""
        assert _is_ssl_error("Certificate Verify Failed") is True

    def test_uppercase_ssl_handshake(self) -> None:
        """Test detection of uppercase 'SSL HANDSHAKE'."""
        assert _is_ssl_error("SSL HANDSHAKE FAILED") is True


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

    async def test_creates_client_without_keys(self) -> None:
        """Test creating client without keys (read-only)."""
        client = await create_client()
        assert client is not None

    async def test_creates_client_with_keys(self) -> None:
        """Test creating client with keys for signing."""
        from nostr_sdk import Keys

        keys = Keys.generate()
        client = await create_client(keys=keys)
        assert client is not None


class TestCreateClientProxy:
    """Tests for create_client() with proxy configuration."""

    async def test_creates_client_with_proxy_url_ip(self) -> None:
        """Test creating client with IP address proxy."""
        client = await create_client(proxy_url="socks5://127.0.0.1:9050")
        assert client is not None

    async def test_creates_client_with_keys_and_proxy(self) -> None:
        """Test creating client with both keys and proxy."""
        from nostr_sdk import Keys

        keys = Keys.generate()
        client = await create_client(keys=keys, proxy_url="socks5://127.0.0.1:9050")
        assert client is not None

    async def test_proxy_hostname_resolved(self) -> None:
        """Test proxy hostname is resolved to IP via asyncio.to_thread."""
        with patch("asyncio.to_thread", new_callable=AsyncMock, return_value="127.0.0.1"):
            client = await create_client(proxy_url="socks5://tor:9050")
            assert client is not None

    async def test_proxy_ip_not_resolved(self) -> None:
        """Test IP address proxy does not call asyncio.to_thread for resolution."""
        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            client = await create_client(proxy_url="socks5://127.0.0.1:9050")
            assert client is not None
            mock_to_thread.assert_not_awaited()

    async def test_proxy_default_port(self) -> None:
        """Test proxy URL without explicit port uses default."""
        client = await create_client(proxy_url="socks5://127.0.0.1")
        assert client is not None


# =============================================================================
# create_client(allow_insecure=True) Tests
# =============================================================================


class TestCreateClientInsecure:
    """Tests for create_client() with allow_insecure=True."""

    async def test_creates_insecure_client_without_keys(self) -> None:
        """Test creating insecure client without keys."""
        client = await create_client(allow_insecure=True)
        assert client is not None

    async def test_creates_insecure_client_with_keys(self) -> None:
        """Test creating insecure client with keys."""
        from nostr_sdk import Keys

        keys = Keys.generate()
        client = await create_client(keys=keys, allow_insecure=True)
        assert client is not None


# =============================================================================
# connect_relay() Tests - Overlay Networks
# =============================================================================


class TestConnectRelayOverlayNetworks:
    """Tests for connect_relay() with overlay networks (Tor, I2P, Loki)."""

    async def test_tor_requires_proxy(self) -> None:
        """Test Tor relay requires proxy_url."""
        relay = Relay("wss://example.onion")

        with pytest.raises(ValueError) as exc_info:
            from bigbrotr.utils.protocol import connect_relay

            await connect_relay(relay, proxy_url=None)

        assert "proxy_url required" in str(exc_info.value)
        assert "tor" in str(exc_info.value).lower()

    async def test_i2p_requires_proxy(self) -> None:
        """Test I2P relay requires proxy_url."""
        relay = Relay("wss://example.i2p")

        with pytest.raises(ValueError) as exc_info:
            from bigbrotr.utils.protocol import connect_relay

            await connect_relay(relay, proxy_url=None)

        assert "proxy_url required" in str(exc_info.value)

    async def test_loki_requires_proxy(self) -> None:
        """Test Lokinet relay requires proxy_url."""
        relay = Relay("wss://example.loki")

        with pytest.raises(ValueError) as exc_info:
            from bigbrotr.utils.protocol import connect_relay

            await connect_relay(relay, proxy_url=None)

        assert "proxy_url required" in str(exc_info.value)


# =============================================================================
# connect_relay() Tests - Clearnet
# =============================================================================


class TestConnectRelayClearnet:
    """Tests for connect_relay() with clearnet relays."""

    async def test_ssl_error_fallback_disabled_raises(self) -> None:
        """Test SSL errors raise when allow_insecure=False."""
        relay = Relay("wss://relay.example.com")

        mock_url = MagicMock()
        mock_output = MagicMock()
        mock_output.success = []
        mock_output.failed = {mock_url: "SSL certificate verify failed"}

        with (
            patch(
                "bigbrotr.utils.protocol.create_client",
                new_callable=AsyncMock,
            ) as mock_create,
            patch("bigbrotr.utils.protocol.RelayUrl") as mock_relay_url,
        ):
            mock_client = AsyncMock()
            mock_client.try_connect = AsyncMock(return_value=mock_output)
            mock_client.disconnect = AsyncMock()
            mock_create.return_value = mock_client

            mock_relay_url.parse.return_value = mock_url

            from bigbrotr.utils.protocol import connect_relay

            with pytest.raises(ssl.SSLCertVerificationError):
                await connect_relay(relay, allow_insecure=False)

    async def test_clearnet_no_proxy_required(self) -> None:
        """Test clearnet relay does not require proxy."""
        relay = Relay("wss://relay.example.com")
        assert relay.network == NetworkType.CLEARNET

        mock_url = MagicMock()
        mock_output = MagicMock()
        mock_output.success = [mock_url]
        mock_output.failed = {}

        with (
            patch(
                "bigbrotr.utils.protocol.create_client",
                new_callable=AsyncMock,
            ) as mock_create,
            patch("bigbrotr.utils.protocol.RelayUrl") as mock_relay_url,
        ):
            mock_client = AsyncMock()
            mock_client.try_connect = AsyncMock(return_value=mock_output)
            mock_create.return_value = mock_client

            mock_relay_url.parse.return_value = mock_url

            from bigbrotr.utils.protocol import connect_relay

            client = await connect_relay(relay)
            assert client is mock_client


# =============================================================================
# is_nostr_relay() Tests
# =============================================================================


class TestIsNostrRelayMocked:
    """Tests for is_nostr_relay() with mocked connections."""

    async def test_valid_relay_returns_true(self) -> None:
        """Test relay that responds with EOSE is valid."""
        relay = Relay("wss://relay.example.com")

        with patch("bigbrotr.utils.protocol.connect_relay") as mock_connect:
            mock_client = AsyncMock()
            mock_client.fetch_events = AsyncMock(return_value=[])
            mock_client.disconnect = AsyncMock()
            mock_connect.return_value = mock_client

            from bigbrotr.utils.protocol import is_nostr_relay

            result = await is_nostr_relay(relay)
            assert result is True

    async def test_auth_required_is_valid(self) -> None:
        """Test relay that requires AUTH (NIP-42) is still valid."""
        relay = Relay("wss://relay.example.com")

        with patch("bigbrotr.utils.protocol.connect_relay") as mock_connect:
            mock_connect.side_effect = OSError("auth-required: please authenticate")

            from bigbrotr.utils.protocol import is_nostr_relay

            result = await is_nostr_relay(relay)
            assert result is True

    async def test_connection_error_is_invalid(self) -> None:
        """Test relay that fails to connect is invalid."""
        relay = Relay("wss://relay.example.com")

        with patch("bigbrotr.utils.protocol.connect_relay") as mock_connect:
            mock_connect.side_effect = OSError("Connection refused")

            from bigbrotr.utils.protocol import is_nostr_relay

            result = await is_nostr_relay(relay)
            assert result is False

    async def test_timeout_error_is_invalid(self) -> None:
        """Test relay that times out is invalid."""
        relay = Relay("wss://relay.example.com")

        with patch("bigbrotr.utils.protocol.connect_relay") as mock_connect:
            mock_connect.side_effect = TimeoutError("Connection timed out")

            from bigbrotr.utils.protocol import is_nostr_relay

            result = await is_nostr_relay(relay)
            assert result is False

    async def test_passes_proxy_url(self) -> None:
        """Test proxy URL is passed to connect_relay."""
        relay = Relay("wss://example.onion")

        with patch("bigbrotr.utils.protocol.connect_relay") as mock_connect:
            mock_client = AsyncMock()
            mock_client.fetch_events = AsyncMock(return_value=[])
            mock_client.disconnect = AsyncMock()
            mock_connect.return_value = mock_client

            from bigbrotr.utils.protocol import is_nostr_relay

            await is_nostr_relay(relay, proxy_url="socks5://127.0.0.1:9050")

            mock_connect.assert_called_once()
            call_kwargs = mock_connect.call_args[1]
            assert call_kwargs["proxy_url"] == "socks5://127.0.0.1:9050"

    async def test_uses_custom_timeout(self) -> None:
        """Test custom timeout is passed to connect_relay."""
        relay = Relay("wss://relay.example.com")

        with patch("bigbrotr.utils.protocol.connect_relay") as mock_connect:
            mock_client = AsyncMock()
            mock_client.fetch_events = AsyncMock(return_value=[])
            mock_client.disconnect = AsyncMock()
            mock_connect.return_value = mock_client

            from bigbrotr.utils.protocol import is_nostr_relay

            await is_nostr_relay(relay, timeout=30.0)

            mock_connect.assert_called_once()
            call_kwargs = mock_connect.call_args[1]
            assert call_kwargs["timeout"] == 30.0


class TestIsNostrRelayDisconnect:
    """Tests that is_nostr_relay() properly disconnects after validation."""

    async def test_disconnect_called_on_success(self) -> None:
        """Test disconnect is called after successful validation."""
        relay = Relay("wss://relay.example.com")

        with patch("bigbrotr.utils.protocol.connect_relay") as mock_connect:
            mock_client = AsyncMock()
            mock_client.fetch_events = AsyncMock(return_value=[])
            mock_client.disconnect = AsyncMock()
            mock_connect.return_value = mock_client

            from bigbrotr.utils.protocol import is_nostr_relay

            await is_nostr_relay(relay)

            mock_client.disconnect.assert_called_once()


# =============================================================================
# broadcast_events() Tests
# =============================================================================

# Valid secp256k1 test key (DO NOT USE IN PRODUCTION)
_VALID_HEX_KEY = (
    "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"  # pragma: allowlist secret
)


class TestBroadcastEvents:
    """Tests for broadcast_events().

    Accesses ``broadcast_events`` through ``sys.modules`` at test runtime
    to survive module reloading by pytest-typeguard, which can capture
    stale references to ``connect_relay`` when both functions are in the
    same module.
    """

    @staticmethod
    def _get_broadcast():
        """Get the current broadcast_events from sys.modules."""
        import sys

        return sys.modules["bigbrotr.utils.protocol"].broadcast_events

    async def test_broadcasts_to_single_relay(self) -> None:
        mock_client = AsyncMock()
        relay = Relay("wss://relay.example.com")
        mock_builder = MagicMock()
        keys = Keys.parse(_VALID_HEX_KEY)

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            await self._get_broadcast()([mock_builder], [relay], keys)

        mock_client.send_event_builder.assert_awaited_once_with(mock_builder)
        mock_client.shutdown.assert_awaited_once()

    async def test_per_relay_client(self) -> None:
        """Each relay gets its own client via connect_relay."""
        clients = [AsyncMock(), AsyncMock()]
        relays = [Relay("wss://relay1.example.com"), Relay("wss://relay2.example.com")]
        builders = [MagicMock(), MagicMock(), MagicMock()]
        keys = Keys.parse(_VALID_HEX_KEY)

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            side_effect=clients,
        ):
            await self._get_broadcast()(builders, relays, keys)

        for client in clients:
            assert client.send_event_builder.await_count == 3
            client.shutdown.assert_awaited_once()

    async def test_empty_builders(self) -> None:
        relay = Relay("wss://relay.example.com")
        keys = Keys.parse(_VALID_HEX_KEY)

        with patch("bigbrotr.utils.protocol.connect_relay") as mock_connect:
            await self._get_broadcast()([], [relay], keys)
            mock_connect.assert_not_called()

    async def test_empty_relays(self) -> None:
        keys = Keys.parse(_VALID_HEX_KEY)

        with patch("bigbrotr.utils.protocol.connect_relay") as mock_connect:
            await self._get_broadcast()([MagicMock()], [], keys)
            mock_connect.assert_not_called()

    async def test_connect_failure_skips_relay(self) -> None:
        """Connection failure on one relay does not block the others."""
        good_client = AsyncMock()
        relays = [Relay("wss://bad.example.com"), Relay("wss://good.example.com")]
        keys = Keys.parse(_VALID_HEX_KEY)

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            side_effect=[OSError("connect failed"), good_client],
        ):
            await self._get_broadcast()([MagicMock()], relays, keys)

        good_client.send_event_builder.assert_awaited_once()
        good_client.shutdown.assert_awaited_once()

    async def test_shutdown_called_on_send_error(self) -> None:
        """Client shutdown is called even when send_event_builder raises."""
        mock_client = AsyncMock()
        mock_client.send_event_builder.side_effect = OSError("send failed")
        relay = Relay("wss://relay.example.com")
        keys = Keys.parse(_VALID_HEX_KEY)

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            await self._get_broadcast()([MagicMock()], [relay], keys)

        mock_client.shutdown.assert_awaited_once()

    async def test_passes_timeout_and_allow_insecure(self) -> None:
        """Keyword args are forwarded to connect_relay."""
        mock_client = AsyncMock()
        relay = Relay("wss://relay.example.com")
        keys = Keys.parse(_VALID_HEX_KEY)

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            return_value=mock_client,
        ) as mock_connect:
            await self._get_broadcast()(
                [MagicMock()],
                [relay],
                keys,
                timeout=5.0,
                allow_insecure=False,
            )

        mock_connect.assert_awaited_once_with(
            relay,
            keys=keys,
            timeout=5.0,
            allow_insecure=False,
        )

    async def test_returns_success_count(self) -> None:
        """Returns number of relays that received all events."""
        relays = [Relay("wss://r1.example.com"), Relay("wss://r2.example.com")]
        keys = Keys.parse(_VALID_HEX_KEY)

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            side_effect=[OSError("fail"), AsyncMock()],
        ):
            result = await self._get_broadcast()([MagicMock()], relays, keys)

        assert result == 1

    async def test_returns_zero_on_empty_input(self) -> None:
        keys = Keys.parse(_VALID_HEX_KEY)
        assert await self._get_broadcast()([], [], keys) == 0
