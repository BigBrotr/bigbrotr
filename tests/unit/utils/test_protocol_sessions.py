"""Unit tests for the ``bigbrotr.utils.protocol_sessions`` module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bigbrotr.models.relay import Relay
from bigbrotr.utils.protocol_sessions import (
    ClientConnectResult,
    connect_client_relays,
    create_connected_client,
)


class TestConnectClientRelays:
    async def test_rejects_overlay_relays_for_shared_session(self) -> None:
        """Shared client sessions reject overlay relays that need proxy policy."""
        client = AsyncMock()

        with pytest.raises(ValueError, match="clearnet relays only"):
            await connect_client_relays(client, [Relay(f"ws://{'a' * 56}.onion")], timeout=15.0)

        client.add_relay.assert_not_awaited()
        client.try_connect.assert_not_awaited()


class TestCreateConnectedClient:
    async def test_rejects_overlay_relays_before_connect_attempt(self) -> None:
        """Factory helper refuses overlay sessions instead of failing cryptically later."""
        client = AsyncMock()
        create_client_func = AsyncMock(return_value=client)

        with pytest.raises(ValueError, match="unsupported overlay networks: Tor"):
            await create_connected_client(
                [Relay(f"ws://{'a' * 56}.onion")],
                create_client_func=create_client_func,
                timeout=15.0,
            )

        create_client_func.assert_awaited_once_with(keys=None, allow_insecure=False)
        client.add_relay.assert_not_awaited()
        client.try_connect.assert_not_awaited()

    async def test_keeps_clearnet_sessions_supported(self) -> None:
        """Clearnet multi-relay sessions still normalize the connect result."""
        client = AsyncMock()
        relay_url = MagicMock()
        output = MagicMock()
        output.success = [relay_url]
        output.failed = {}
        client.try_connect = AsyncMock(return_value=output)
        create_client_func = AsyncMock(return_value=client)

        result_client, result = await create_connected_client(
            [Relay("wss://relay.example.com")],
            create_client_func=create_client_func,
            timeout=15.0,
        )

        assert result_client is client
        assert result == ClientConnectResult(
            connected=(str(relay_url),),
            failed={},
        )
