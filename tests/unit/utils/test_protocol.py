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
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bigbrotr.models.constants import NetworkType
from bigbrotr.models.relay import Relay
from bigbrotr.utils.protocol import (
    ClientConnectResult,
    ClientSession,
    NostrClientManager,
    _is_ssl_error,
    create_client,
    create_connected_client,
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


class TestCreateConnectedClient:
    async def test_registers_relays_and_normalizes_connect_result(self) -> None:
        relays = [Relay("wss://relay1.example.com"), Relay("wss://relay2.example.com")]
        mock_client = MagicMock()
        mock_client.add_relay = AsyncMock()
        mock_client.try_connect = AsyncMock(
            return_value=MagicMock(
                success=("wss://relay1.example.com",),
                failed={"wss://relay2.example.com": "timeout"},
            )
        )

        with patch(
            "bigbrotr.utils.protocol.create_client", new=AsyncMock(return_value=mock_client)
        ):
            client, result = await create_connected_client(
                relays,
                timeout=12.0,
                allow_insecure=True,
            )

        assert client is mock_client
        assert result == ClientConnectResult(
            connected=("wss://relay1.example.com",),
            failed={"wss://relay2.example.com": "timeout"},
        )
        assert mock_client.add_relay.await_count == 2
        mock_client.try_connect.assert_awaited_once()


class TestNostrClientManagerRelayClients:
    async def test_connect_relay_once_uses_network_policy_without_caching(self) -> None:
        networks = MagicMock()
        network_cfg = MagicMock()
        network_cfg.timeout = 12.0
        networks.get.return_value = network_cfg
        networks.get_proxy_url.return_value = "socks5://127.0.0.1:9050"
        relay = Relay("wss://relay.example.com")
        manager = NostrClientManager(keys=MagicMock(), networks=networks, allow_insecure=True)

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
        ) as mock_connect:
            await manager.connect_relay_once(relay)
            await manager.connect_relay_once(relay)

        assert manager._relay_clients == {}
        assert manager._failed_relays == set()
        assert mock_connect.await_count == 2
        mock_connect.assert_awaited_with(
            relay,
            keys=manager._keys,
            proxy_url="socks5://127.0.0.1:9050",
            timeout=12.0,
            allow_insecure=True,
        )

    async def test_get_relay_client_caches_successful_connections(self) -> None:
        networks = MagicMock()
        network_cfg = MagicMock()
        network_cfg.timeout = 12.0
        networks.get.return_value = network_cfg
        networks.get_proxy_url.return_value = None
        relay = Relay("wss://relay.example.com")
        mock_client = MagicMock()
        manager = NostrClientManager(keys=MagicMock(), networks=networks)

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            return_value=mock_client,
        ) as mock_connect:
            first = await manager.get_relay_client(relay)
            second = await manager.get_relay_client(relay)

        assert first is mock_client
        assert second is mock_client
        mock_connect.assert_awaited_once_with(
            relay,
            keys=manager._keys,
            proxy_url=None,
            timeout=12.0,
            allow_insecure=False,
        )

    async def test_get_relay_client_caches_failures(self) -> None:
        networks = MagicMock()
        network_cfg = MagicMock()
        network_cfg.timeout = 9.0
        networks.get.return_value = network_cfg
        networks.get_proxy_url.return_value = None
        relay = Relay("wss://relay.example.com")
        manager = NostrClientManager(keys=MagicMock(), networks=networks)

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            side_effect=TimeoutError("timed out"),
        ) as mock_connect:
            first = await manager.get_relay_client(relay)
            second = await manager.get_relay_client(relay)

        assert first is None
        assert second is None
        mock_connect.assert_awaited_once()

    async def test_get_relay_client_requires_networks(self) -> None:
        manager = NostrClientManager(keys=MagicMock())

        with pytest.raises(RuntimeError, match="networks configuration required"):
            await manager.get_relay_client(Relay("wss://relay.example.com"))


class TestNostrClientManagerSessions:
    async def test_connect_session_creates_and_caches_named_session(self) -> None:
        relays = [Relay("wss://relay1.example.com"), Relay("wss://relay2.example.com")]
        mock_client = MagicMock()
        result = ClientConnectResult(
            connected=("wss://relay1.example.com",),
            failed={"wss://relay2.example.com": "timeout"},
        )
        manager = NostrClientManager(keys=MagicMock(), allow_insecure=True)

        with (
            patch(
                "bigbrotr.utils.protocol.create_client",
                new=AsyncMock(return_value=mock_client),
            ) as mock_create,
            patch(
                "bigbrotr.utils.protocol._connect_client_relays",
                new=AsyncMock(return_value=result),
            ) as mock_connect,
        ):
            first = await manager.connect_session("read-session", relays, timeout=15.0)
            second = await manager.connect_session("read-session", relays, timeout=1.0)

        assert first == ClientSession(
            session_id="read-session",
            client=mock_client,
            relay_urls=("wss://relay1.example.com", "wss://relay2.example.com"),
            connect_result=result,
        )
        assert second is first
        mock_create.assert_awaited_once_with(keys=manager._keys, allow_insecure=True)
        mock_connect.assert_awaited_once_with(mock_client, relays, timeout=15.0)
        assert manager.get_session("read-session") is first

    async def test_connect_session_rejects_same_name_with_different_relays(self) -> None:
        manager = NostrClientManager(keys=MagicMock())
        manager._sessions["read-session"] = ClientSession(
            session_id="read-session",
            client=MagicMock(),
            relay_urls=("wss://relay1.example.com",),
            connect_result=ClientConnectResult(connected=("wss://relay1.example.com",), failed={}),
        )

        with pytest.raises(ValueError, match="already exists with different relays"):
            await manager.connect_session(
                "read-session",
                [Relay("wss://relay2.example.com")],
            )

    async def test_disconnect_shuts_down_sessions_and_cached_relays_once(self) -> None:
        shared_client = MagicMock()
        cached_client = MagicMock()
        manager = NostrClientManager(keys=MagicMock())
        manager._sessions["session"] = ClientSession(
            session_id="session",
            client=shared_client,
            relay_urls=("wss://relay1.example.com",),
            connect_result=ClientConnectResult(connected=("wss://relay1.example.com",), failed={}),
        )
        manager._relay_clients["wss://relay1.example.com"] = shared_client
        manager._relay_clients["wss://relay2.example.com"] = cached_client
        manager._failed_relays.add("wss://relay3.example.com")

        with patch(
            "bigbrotr.utils.protocol.shutdown_client",
            new_callable=AsyncMock,
        ) as mock_shutdown:
            await manager.disconnect()

        assert mock_shutdown.await_count == 2
        mock_shutdown.assert_any_await(shared_client)
        mock_shutdown.assert_any_await(cached_client)
        assert manager._sessions == {}
        assert manager._relay_clients == {}
        assert manager._failed_relays == set()


# =============================================================================
# connect_relay() Tests - Overlay Networks
# =============================================================================


class TestConnectRelayOverlayNetworks:
    """Tests for connect_relay() with overlay networks (Tor, I2P, Loki)."""

    async def test_tor_requires_proxy(self) -> None:
        """Test Tor relay requires proxy_url."""
        relay = Relay(f"ws://{'a' * 56}.onion")

        with pytest.raises(ValueError) as exc_info:
            from bigbrotr.utils.protocol import connect_relay

            await connect_relay(relay, proxy_url=None)

        assert "proxy_url required" in str(exc_info.value)
        assert "tor" in str(exc_info.value).lower()

    async def test_i2p_requires_proxy(self) -> None:
        """Test I2P relay requires proxy_url."""
        relay = Relay("ws://example.i2p")

        with pytest.raises(ValueError) as exc_info:
            from bigbrotr.utils.protocol import connect_relay

            await connect_relay(relay, proxy_url=None)

        assert "proxy_url required" in str(exc_info.value)

    async def test_loki_requires_proxy(self) -> None:
        """Test Lokinet relay requires proxy_url."""
        relay = Relay(f"ws://{'d' * 52}.loki")

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
        relay = Relay(f"ws://{'a' * 56}.onion")

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


class TestIsNostrRelayShutdown:
    """Tests that is_nostr_relay() properly shuts down after validation."""

    async def test_shutdown_called_on_success(self) -> None:
        """Test shutdown is called after successful validation."""
        relay = Relay("wss://relay.example.com")

        with patch("bigbrotr.utils.protocol.connect_relay") as mock_connect:
            mock_client = AsyncMock()
            mock_client.fetch_events = AsyncMock(return_value=[])
            mock_client.shutdown = AsyncMock()
            mock_connect.return_value = mock_client

            from bigbrotr.utils.protocol import is_nostr_relay

            await is_nostr_relay(relay)

            mock_client.shutdown.assert_called_once()


# =============================================================================
# broadcast_events() Tests
# =============================================================================


class TestBroadcastEvents:
    """Tests for broadcast_events().

    Accesses ``broadcast_events`` through ``sys.modules`` at test runtime
    to survive module reloading by pytest-typeguard, which can capture
    stale references when functions are in the same module.
    """

    @staticmethod
    def _get_broadcast():
        """Get the current broadcast_events from sys.modules."""
        import sys

        return sys.modules["bigbrotr.utils.protocol"].broadcast_events

    @staticmethod
    def _get_broadcast_detailed():
        """Get the current broadcast_events_detailed from sys.modules."""
        import sys

        return sys.modules["bigbrotr.utils.protocol"].broadcast_events_detailed

    @staticmethod
    def _send_output(
        *,
        event_id: str = "event-id",
        success: tuple[str, ...] = (),
        failed: dict[str, str] | None = None,
    ) -> MagicMock:
        output = MagicMock()
        output.id = event_id
        output.success = list(success)
        output.failed = failed or {}
        return output

    async def test_sends_to_single_client(self) -> None:
        mock_client = AsyncMock()
        mock_builder = MagicMock()
        mock_client.send_event_builder.return_value = self._send_output(
            success=("wss://relay.example.com",)
        )

        result = await self._get_broadcast()([mock_builder], [mock_client])

        mock_client.send_event_builder.assert_awaited_once_with(mock_builder)
        assert result == 1

    async def test_sends_to_multiple_clients(self) -> None:
        clients = [AsyncMock(), AsyncMock()]
        builders = [MagicMock(), MagicMock(), MagicMock()]
        for index, client in enumerate(clients):
            client.send_event_builder.side_effect = [
                self._send_output(
                    event_id=f"event-{index}-{builder_index}",
                    success=(f"wss://relay-{index}.example.com",),
                )
                for builder_index, _builder in enumerate(builders)
            ]

        result = await self._get_broadcast()(builders, clients)

        for client in clients:
            assert client.send_event_builder.await_count == 3
        assert result == 2

    async def test_empty_builders(self) -> None:
        result = await self._get_broadcast()([], [AsyncMock()])
        assert result == 0

    async def test_empty_clients(self) -> None:
        result = await self._get_broadcast()([MagicMock()], [])
        assert result == 0

    async def test_send_error_skips_client(self) -> None:
        bad_client = AsyncMock()
        bad_client.send_event_builder.side_effect = OSError("send failed")
        good_client = AsyncMock()
        good_client.send_event_builder.return_value = self._send_output(
            success=("wss://relay.example.com",)
        )

        result = await self._get_broadcast()([MagicMock()], [bad_client, good_client])

        assert result == 1
        good_client.send_event_builder.assert_awaited_once()

    async def test_returns_zero_on_all_failures(self) -> None:
        client = AsyncMock()
        client.send_event_builder.return_value = self._send_output(
            failed={"wss://relay.example.com": "timeout"}
        )

        result = await self._get_broadcast()([MagicMock()], [client])
        assert result == 0

    async def test_returns_zero_on_empty_input(self) -> None:
        assert await self._get_broadcast()([], []) == 0

    async def test_detailed_results_keep_failed_relays(self) -> None:
        client = AsyncMock()
        client.send_event_builder.return_value = self._send_output(
            event_id="evt-1",
            success=("wss://relay.good",),
            failed={"wss://relay.bad": "timeout"},
        )

        results = await self._get_broadcast_detailed()([MagicMock()], [client])

        assert len(results) == 1
        assert results[0].event_ids == ("evt-1",)
        assert results[0].successful_relays == ("wss://relay.good",)
        assert results[0].failed_relays == {"wss://relay.bad": "timeout"}

    async def test_detailed_results_require_success_across_all_builders(self) -> None:
        client = AsyncMock()
        client.send_event_builder.side_effect = [
            self._send_output(
                event_id="evt-1",
                success=("wss://relay.a", "wss://relay.b"),
            ),
            self._send_output(
                event_id="evt-2",
                success=("wss://relay.b",),
                failed={"wss://relay.a": "rejected"},
            ),
        ]

        results = await self._get_broadcast_detailed()([MagicMock(), MagicMock()], [client])

        assert len(results) == 1
        assert results[0].event_ids == ("evt-1", "evt-2")
        assert results[0].successful_relays == ("wss://relay.b",)
        assert results[0].failed_relays == {"wss://relay.a": "rejected"}


# =============================================================================
# _StderrSuppressor Tests
# =============================================================================


class TestStderrSuppressor:
    """Tests for _StderrSuppressor reference-counted stderr suppression."""

    def test_single_context_restores_stderr(self) -> None:
        from bigbrotr.utils.protocol import _StderrSuppressor

        suppressor = _StderrSuppressor()
        original = sys.stderr
        with suppressor():
            assert sys.stderr is not original
        assert sys.stderr is original

    def test_nested_contexts_restore_on_last_exit(self) -> None:
        from bigbrotr.utils.protocol import _StderrSuppressor

        suppressor = _StderrSuppressor()
        original = sys.stderr
        with suppressor():
            with suppressor():
                assert suppressor._refcount == 2
            # Still suppressed (refcount=1)
            assert sys.stderr is not original
        assert sys.stderr is original
        assert suppressor._refcount == 0

    def test_refcount_starts_at_zero(self) -> None:
        from bigbrotr.utils.protocol import _StderrSuppressor

        suppressor = _StderrSuppressor()
        assert suppressor._refcount == 0


# =============================================================================
# connect_relay() Tests - Additional Branches
# =============================================================================


class TestConnectRelayClearnetAdditional:
    """Additional tests for connect_relay() clearnet branches."""

    async def test_non_ssl_error_raises_os_error(self) -> None:
        """Non-SSL connection failures raise OSError."""
        relay = Relay("wss://relay.example.com")

        mock_url = MagicMock()
        mock_output = MagicMock()
        mock_output.success = []
        mock_output.failed = {mock_url: "Connection refused"}

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

            with pytest.raises(OSError, match="Connection failed"):
                await connect_relay(relay)

    async def test_ssl_fallback_insecure_success(self) -> None:
        """SSL error with allow_insecure=True falls back to insecure transport."""
        relay = Relay("wss://relay.example.com")

        mock_url = MagicMock()
        ssl_output = MagicMock()
        ssl_output.success = []
        ssl_output.failed = {mock_url: "SSL certificate verify failed"}

        insecure_output = MagicMock()
        insecure_output.success = [mock_url]
        insecure_output.failed = {}

        with (
            patch(
                "bigbrotr.utils.protocol.create_client",
                new_callable=AsyncMock,
            ) as mock_create,
            patch("bigbrotr.utils.protocol.RelayUrl") as mock_relay_url,
            patch("bigbrotr.utils.protocol.uniffi_set_event_loop"),
        ):
            ssl_client = AsyncMock()
            ssl_client.try_connect = AsyncMock(return_value=ssl_output)
            ssl_client.disconnect = AsyncMock()

            insecure_client = AsyncMock()
            insecure_client.try_connect = AsyncMock(return_value=insecure_output)

            mock_create.side_effect = [ssl_client, insecure_client]
            mock_relay_url.parse.return_value = mock_url

            from bigbrotr.utils.protocol import connect_relay

            result = await connect_relay(relay, allow_insecure=True)
            assert result is insecure_client
            assert mock_create.call_count == 2
            # Second call should have allow_insecure=True
            assert mock_create.call_args_list[1].kwargs.get("allow_insecure") is True

    async def test_ssl_fallback_insecure_failure_raises(self) -> None:
        """Insecure fallback failure raises OSError."""
        relay = Relay("wss://relay.example.com")

        mock_url = MagicMock()
        ssl_output = MagicMock()
        ssl_output.success = []
        ssl_output.failed = {mock_url: "SSL certificate verify failed"}

        insecure_output = MagicMock()
        insecure_output.success = []
        insecure_output.failed = {mock_url: "Connection refused"}

        with (
            patch(
                "bigbrotr.utils.protocol.create_client",
                new_callable=AsyncMock,
            ) as mock_create,
            patch("bigbrotr.utils.protocol.RelayUrl") as mock_relay_url,
            patch("bigbrotr.utils.protocol.uniffi_set_event_loop"),
        ):
            ssl_client = AsyncMock()
            ssl_client.try_connect = AsyncMock(return_value=ssl_output)
            ssl_client.disconnect = AsyncMock()

            insecure_client = AsyncMock()
            insecure_client.try_connect = AsyncMock(return_value=insecure_output)
            insecure_client.disconnect = AsyncMock()

            mock_create.side_effect = [ssl_client, insecure_client]
            mock_relay_url.parse.return_value = mock_url

            from bigbrotr.utils.protocol import connect_relay

            with pytest.raises(OSError, match="Connection failed \\(insecure\\)"):
                await connect_relay(relay, allow_insecure=True)


class TestConnectRelayOverlaySuccess:
    """Tests for connect_relay() overlay network success path."""

    async def test_overlay_connects_with_proxy(self) -> None:
        """Overlay relay connects via proxy and returns client."""
        relay = Relay(f"ws://{'a' * 56}.onion")

        mock_relay_obj = MagicMock()
        mock_relay_obj.is_connected.return_value = True

        with (
            patch(
                "bigbrotr.utils.protocol.create_client",
                new_callable=AsyncMock,
            ) as mock_create,
            patch("bigbrotr.utils.protocol.RelayUrl") as mock_relay_url,
        ):
            mock_client = AsyncMock()
            mock_client.relay = AsyncMock(return_value=mock_relay_obj)
            mock_create.return_value = mock_client
            mock_relay_url.parse.return_value = MagicMock()

            from bigbrotr.utils.protocol import connect_relay

            result = await connect_relay(relay, proxy_url="socks5://127.0.0.1:9050")
            assert result is mock_client

    async def test_overlay_timeout_raises(self) -> None:
        """Overlay relay that fails to connect raises TimeoutError."""
        relay = Relay(f"ws://{'a' * 56}.onion")

        mock_relay_obj = MagicMock()
        mock_relay_obj.is_connected.return_value = False

        with (
            patch(
                "bigbrotr.utils.protocol.create_client",
                new_callable=AsyncMock,
            ) as mock_create,
            patch("bigbrotr.utils.protocol.RelayUrl") as mock_relay_url,
        ):
            mock_client = AsyncMock()
            mock_client.relay = AsyncMock(return_value=mock_relay_obj)
            mock_create.return_value = mock_client
            mock_relay_url.parse.return_value = MagicMock()

            from bigbrotr.utils.protocol import connect_relay

            with pytest.raises(TimeoutError, match="Connection timeout"):
                await connect_relay(relay, proxy_url="socks5://127.0.0.1:9050")


# =============================================================================
# create_client() Tests - IPv6 Proxy
# =============================================================================


class TestCreateClientIpv6Proxy:
    """Tests for create_client() with IPv6 proxy address."""

    async def test_ipv6_proxy_address(self) -> None:
        """IPv6 proxy address is recognized without DNS resolution."""
        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            client = await create_client(proxy_url="socks5://[::1]:9050")
            assert client is not None
            mock_to_thread.assert_not_awaited()


# =============================================================================
# is_nostr_relay() Tests - Additional Branches
# =============================================================================


class TestIsNostrRelayAdditional:
    """Additional tests for is_nostr_relay()."""

    async def test_disconnect_error_suppressed(self) -> None:
        """Disconnect errors in finally block are suppressed."""
        relay = Relay("wss://relay.example.com")

        with patch("bigbrotr.utils.protocol.connect_relay") as mock_connect:
            mock_client = AsyncMock()
            mock_client.fetch_events = AsyncMock(return_value=[])
            mock_client.disconnect = AsyncMock(side_effect=OSError("disconnect failed"))
            mock_connect.return_value = mock_client

            from bigbrotr.utils.protocol import is_nostr_relay

            result = await is_nostr_relay(relay)
            assert result is True

    async def test_overall_timeout_parameter(self) -> None:
        """Custom overall_timeout is used instead of timeout * 4."""
        relay = Relay("wss://relay.example.com")

        with patch("bigbrotr.utils.protocol.connect_relay") as mock_connect:
            mock_client = AsyncMock()
            mock_client.fetch_events = AsyncMock(return_value=[])
            mock_client.disconnect = AsyncMock()
            mock_connect.return_value = mock_client

            from bigbrotr.utils.protocol import is_nostr_relay

            result = await is_nostr_relay(relay, timeout=5.0, overall_timeout=60.0)
            assert result is True

    async def test_passes_allow_insecure(self) -> None:
        """allow_insecure is forwarded to connect_relay."""
        relay = Relay("wss://relay.example.com")

        with patch("bigbrotr.utils.protocol.connect_relay") as mock_connect:
            mock_client = AsyncMock()
            mock_client.fetch_events = AsyncMock(return_value=[])
            mock_client.disconnect = AsyncMock()
            mock_connect.return_value = mock_client

            from bigbrotr.utils.protocol import is_nostr_relay

            await is_nostr_relay(relay, allow_insecure=True)

            call_kwargs = mock_connect.call_args[1]
            assert call_kwargs["allow_insecure"] is True
