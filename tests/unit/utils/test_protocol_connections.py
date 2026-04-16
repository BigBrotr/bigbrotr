"""Unit tests for protocol connection helpers."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

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

    async def test_ssl_failure_falls_back_to_insecure_client(self) -> None:
        relay = Relay("wss://relay.example.com")
        relay_url = MagicMock()
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
