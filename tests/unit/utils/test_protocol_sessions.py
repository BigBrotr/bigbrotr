"""Unit tests for the ``bigbrotr.utils.protocol_sessions`` module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from nostr_sdk import NostrSdkError

from bigbrotr.models.relay import Relay
from bigbrotr.utils.protocol_sessions import (
    ClientConnectResult,
    SharedSessionDependencies,
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

    async def test_normalizes_connected_relays_to_stable_order(self) -> None:
        """Connected relay URLs are deduplicated and sorted in the normalized result."""
        client = AsyncMock()
        output = MagicMock()
        output.success = ["wss://relay.b", "wss://relay.a", "wss://relay.b"]
        output.failed = {}
        client.try_connect = AsyncMock(return_value=output)

        result = await connect_client_relays(
            client,
            [Relay("wss://relay1.example.com"), Relay("wss://relay2.example.com")],
            timeout=15.0,
        )

        assert result == ClientConnectResult(
            connected=("wss://relay.a", "wss://relay.b"),
            failed={},
        )


class TestCreateConnectedClient:
    async def test_rejects_overlay_relays_before_client_creation(self) -> None:
        """Factory helper rejects unsupported overlay sessions before allocating a client."""
        client = AsyncMock()
        create_client_func = AsyncMock(return_value=client)

        with pytest.raises(ValueError, match="unsupported overlay networks: Tor"):
            await create_connected_client(
                [Relay(f"ws://{'a' * 56}.onion")],
                dependencies=SharedSessionDependencies(
                    create_client=create_client_func,
                    shutdown_client=AsyncMock(),
                ),
                timeout=15.0,
            )

        create_client_func.assert_not_awaited()
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
            dependencies=SharedSessionDependencies(
                create_client=create_client_func,
                shutdown_client=AsyncMock(),
            ),
            timeout=15.0,
        )

        assert result_client is client
        assert result == ClientConnectResult(
            connected=(str(relay_url),),
            failed={},
        )

    async def test_preserves_connect_error_when_shutdown_reports_expected_noise(self) -> None:
        """Shared-session helper keeps the connect failure as the public outcome."""
        client = AsyncMock()
        create_client_func = AsyncMock(return_value=client)
        shutdown_client_func = AsyncMock(side_effect=NostrSdkError("shutdown noise"))
        client.add_relay = AsyncMock(side_effect=OSError("connect boom"))

        with pytest.raises(OSError, match="connect boom"):
            await create_connected_client(
                [Relay("wss://relay.example.com")],
                dependencies=SharedSessionDependencies(
                    create_client=create_client_func,
                    shutdown_client=shutdown_client_func,
                ),
                timeout=15.0,
            )

        create_client_func.assert_awaited_once_with(keys=None, allow_insecure=False)
        shutdown_client_func.assert_awaited_once_with(client)
