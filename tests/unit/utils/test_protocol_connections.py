"""Unit tests for the ``bigbrotr.utils.protocol_connections`` module."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from nostr_sdk import NostrSdkError

from bigbrotr.models.relay import Relay
from bigbrotr.utils.protocol_connections import (
    RelayConnectContext,
    RelayConnectOptions,
    connect_relay,
)


def _context(
    *,
    create_client: AsyncMock,
    shutdown_client: AsyncMock | None = None,
    parse_relay_url: MagicMock | None = None,
    set_event_loop: MagicMock | None = None,
    is_ssl_error: MagicMock | None = None,
) -> RelayConnectContext:
    return RelayConnectContext(
        create_client=create_client,
        shutdown_client=shutdown_client or AsyncMock(),
        parse_relay_url=parse_relay_url or MagicMock(return_value=MagicMock()),
        set_event_loop=set_event_loop or MagicMock(),
        is_ssl_error=is_ssl_error or MagicMock(return_value=True),
        logger=logging.getLogger("test.protocol_connections"),
    )


class TestRelayConnectOptions:
    @pytest.mark.parametrize("proxy_url", [True, "", "   ", "garbage", "socks5://:9050"])
    def test_rejects_invalid_proxy_url(self, proxy_url: object) -> None:
        with pytest.raises(
            ValueError, match="proxy_url must be a valid proxy URL with scheme and hostname"
        ):
            RelayConnectOptions(
                keys=None,
                proxy_url=proxy_url,  # type: ignore[arg-type]
                timeout=5.0,
                allow_insecure=False,
            )

    @pytest.mark.parametrize("timeout", [True, 0, -1.0, float("nan"), float("inf")])
    def test_rejects_invalid_timeout(self, timeout: object) -> None:
        with pytest.raises(ValueError, match="timeout must be a positive finite number"):
            RelayConnectOptions(
                keys=None,
                proxy_url=None,
                timeout=timeout,  # type: ignore[arg-type]
                allow_insecure=False,
            )

    def test_rejects_non_bool_allow_insecure(self) -> None:
        with pytest.raises(ValueError, match="allow_insecure must be a bool"):
            RelayConnectOptions(
                keys=None,
                proxy_url=None,
                timeout=5.0,
                allow_insecure=1,  # type: ignore[arg-type]
            )


class TestProtocolConnections:
    async def test_overlay_connection_uses_proxy_client(self) -> None:
        relay = Relay(f"ws://{'a' * 56}.onion")
        relay_url = MagicMock()
        relay_obj = MagicMock()
        relay_obj.is_connected.return_value = True
        client = AsyncMock()
        client.relay = AsyncMock(return_value=relay_obj)
        create_client = AsyncMock(return_value=client)
        context = _context(
            create_client=create_client,
            parse_relay_url=MagicMock(return_value=relay_url),
        )

        result = await connect_relay(
            relay,
            context,
            RelayConnectOptions(
                keys=None,
                proxy_url="socks5://127.0.0.1:9050",
                timeout=12.0,
                allow_insecure=False,
            ),
        )

        assert result is client
        create_client.assert_awaited_once_with(None, "socks5://127.0.0.1:9050")
        client.add_relay.assert_awaited_once_with(relay_url)
        client.connect.assert_awaited_once()
        client.wait_for_connection.assert_awaited_once()

    async def test_overlay_connect_failure_shuts_down_partial_client(self) -> None:
        relay = Relay(f"ws://{'a' * 56}.onion")
        relay_url = MagicMock()
        client = AsyncMock()
        client.connect.side_effect = OSError("proxy connect failed")
        shutdown_client = AsyncMock()
        context = _context(
            create_client=AsyncMock(return_value=client),
            shutdown_client=shutdown_client,
            parse_relay_url=MagicMock(return_value=relay_url),
        )

        with pytest.raises(OSError, match="proxy connect failed"):
            await connect_relay(
                relay,
                context,
                RelayConnectOptions(
                    keys=None,
                    proxy_url="socks5://127.0.0.1:9050",
                    timeout=12.0,
                    allow_insecure=False,
                ),
            )

        client.add_relay.assert_awaited_once_with(relay_url)
        client.connect.assert_awaited_once()
        shutdown_client.assert_awaited_once_with(client)

    async def test_overlay_wait_timeout_shuts_down_partial_client(self) -> None:
        relay = Relay(f"ws://{'a' * 56}.onion")
        relay_url = MagicMock()
        client = AsyncMock()
        client.wait_for_connection.side_effect = TimeoutError("handshake timed out")
        shutdown_client = AsyncMock()
        context = _context(
            create_client=AsyncMock(return_value=client),
            shutdown_client=shutdown_client,
            parse_relay_url=MagicMock(return_value=relay_url),
        )

        with pytest.raises(TimeoutError, match="handshake timed out"):
            await connect_relay(
                relay,
                context,
                RelayConnectOptions(
                    keys=None,
                    proxy_url="socks5://127.0.0.1:9050",
                    timeout=12.0,
                    allow_insecure=False,
                ),
            )

        client.add_relay.assert_awaited_once_with(relay_url)
        client.connect.assert_awaited_once()
        client.wait_for_connection.assert_awaited_once()
        shutdown_client.assert_awaited_once_with(client)

    async def test_overlay_unexpected_error_shuts_down_partial_client(self) -> None:
        relay = Relay(f"ws://{'a' * 56}.onion")
        relay_url = MagicMock()
        client = AsyncMock()
        client.relay.side_effect = RuntimeError("relay lookup failed")
        shutdown_client = AsyncMock()
        context = _context(
            create_client=AsyncMock(return_value=client),
            shutdown_client=shutdown_client,
            parse_relay_url=MagicMock(return_value=relay_url),
        )

        with pytest.raises(RuntimeError, match="relay lookup failed"):
            await connect_relay(
                relay,
                context,
                RelayConnectOptions(
                    keys=None,
                    proxy_url="socks5://127.0.0.1:9050",
                    timeout=12.0,
                    allow_insecure=False,
                ),
            )

        client.add_relay.assert_awaited_once_with(relay_url)
        client.connect.assert_awaited_once()
        client.wait_for_connection.assert_awaited_once()
        client.relay.assert_awaited_once_with(relay_url)
        shutdown_client.assert_awaited_once_with(client)

    async def test_ssl_failure_falls_back_to_insecure_client(self) -> None:
        relay = Relay("wss://relay.example.com")
        relay_url = MagicMock()
        relay_url.__str__.return_value = relay.url
        ssl_output = MagicMock()
        ssl_output.success = []
        ssl_output.failed = {relay_url: "SSL certificate verify failed"}
        insecure_output = MagicMock()
        insecure_output.success = [relay_url]
        insecure_output.failed = {}

        ssl_client = AsyncMock()
        ssl_client.try_connect = AsyncMock(return_value=ssl_output)
        insecure_client = AsyncMock()
        insecure_client.try_connect = AsyncMock(return_value=insecure_output)

        create_client = AsyncMock(side_effect=[ssl_client, insecure_client])
        shutdown_client = AsyncMock()
        set_event_loop = MagicMock()
        context = _context(
            create_client=create_client,
            shutdown_client=shutdown_client,
            parse_relay_url=MagicMock(return_value=relay_url),
            set_event_loop=set_event_loop,
            is_ssl_error=MagicMock(return_value=True),
        )

        result = await connect_relay(
            relay,
            context,
            RelayConnectOptions(
                keys=None,
                proxy_url=None,
                timeout=9.0,
                allow_insecure=True,
            ),
        )

        assert result is insecure_client
        shutdown_client.assert_awaited_once_with(ssl_client)
        create_client.assert_any_await(None)
        create_client.assert_any_await(None, allow_insecure=True)
        set_event_loop.assert_called_once_with(asyncio.get_running_loop())

    async def test_non_ssl_failure_raises_os_error(self) -> None:
        relay = Relay("wss://relay.example.com")
        relay_url = MagicMock()
        relay_url.__str__.return_value = relay.url
        output = MagicMock()
        output.success = []
        output.failed = {relay_url: "Connection refused"}
        client = AsyncMock()
        client.try_connect = AsyncMock(return_value=output)
        shutdown_client = AsyncMock()
        context = _context(
            create_client=AsyncMock(return_value=client),
            shutdown_client=shutdown_client,
            parse_relay_url=MagicMock(return_value=relay_url),
            is_ssl_error=MagicMock(return_value=False),
        )

        with pytest.raises(OSError, match="Connection failed"):
            await connect_relay(
                relay,
                context,
                RelayConnectOptions(
                    keys=None,
                    proxy_url=None,
                    timeout=7.0,
                    allow_insecure=False,
                ),
            )

        shutdown_client.assert_awaited_once_with(client)

    async def test_non_ssl_failure_preserves_primary_error_when_shutdown_reports_expected_noise(
        self,
    ) -> None:
        relay = Relay("wss://relay.example.com")
        relay_url = MagicMock()
        relay_url.__str__.return_value = relay.url
        output = MagicMock()
        output.success = []
        output.failed = {relay_url: "Connection refused"}
        client = AsyncMock()
        client.try_connect = AsyncMock(return_value=output)
        shutdown_client = AsyncMock(side_effect=NostrSdkError("shutdown noise"))
        context = _context(
            create_client=AsyncMock(return_value=client),
            shutdown_client=shutdown_client,
            parse_relay_url=MagicMock(return_value=relay_url),
            is_ssl_error=MagicMock(return_value=False),
        )

        with pytest.raises(OSError, match=r"Connection failed: wss://relay\.example\.com"):
            await connect_relay(
                relay,
                context,
                RelayConnectOptions(
                    keys=None,
                    proxy_url=None,
                    timeout=7.0,
                    allow_insecure=False,
                ),
            )

        shutdown_client.assert_awaited_once_with(client)

    async def test_insecure_fallback_failure_preserves_primary_error_when_shutdown_reports_expected_noise(
        self,
    ) -> None:
        relay = Relay("wss://relay.example.com")
        relay_url = MagicMock()
        relay_url.__str__.return_value = relay.url
        ssl_output = MagicMock()
        ssl_output.success = []
        ssl_output.failed = {relay_url: "SSL certificate verify failed"}
        insecure_output = MagicMock()
        insecure_output.success = []
        insecure_output.failed = {relay_url: "Connection refused"}

        ssl_client = AsyncMock()
        ssl_client.try_connect = AsyncMock(return_value=ssl_output)
        insecure_client = AsyncMock()
        insecure_client.try_connect = AsyncMock(return_value=insecure_output)

        shutdown_client = AsyncMock(side_effect=[None, NostrSdkError("shutdown noise")])
        context = _context(
            create_client=AsyncMock(side_effect=[ssl_client, insecure_client]),
            shutdown_client=shutdown_client,
            parse_relay_url=MagicMock(return_value=relay_url),
            set_event_loop=MagicMock(),
            is_ssl_error=MagicMock(return_value=True),
        )

        with pytest.raises(
            OSError,
            match=r"Connection failed \(insecure\): wss://relay\.example\.com",
        ):
            await connect_relay(
                relay,
                context,
                RelayConnectOptions(
                    keys=None,
                    proxy_url=None,
                    timeout=7.0,
                    allow_insecure=True,
                ),
            )

        shutdown_client.assert_has_awaits([call(ssl_client), call(insecure_client)])

    async def test_malformed_connect_output_shuts_down_partial_client(self) -> None:
        relay = Relay("wss://relay.example.com")
        relay_url = MagicMock()
        client = AsyncMock()
        output = MagicMock()
        output.success = [1]
        output.failed = {}
        client.try_connect = AsyncMock(return_value=output)
        shutdown_client = AsyncMock()
        context = _context(
            create_client=AsyncMock(return_value=client),
            shutdown_client=shutdown_client,
            parse_relay_url=MagicMock(return_value=relay_url),
        )

        with pytest.raises(ValueError, match="relay output contained invalid relay URL"):
            await connect_relay(
                relay,
                context,
                RelayConnectOptions(
                    keys=None,
                    proxy_url=None,
                    timeout=7.0,
                    allow_insecure=False,
                ),
            )

        shutdown_client.assert_awaited_once_with(client)
