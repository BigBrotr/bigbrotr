"""Unit tests for the ``bigbrotr.utils.protocol_sessions`` module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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
    async def test_rejects_empty_relay_list(self) -> None:
        """Shared client sessions reject empty relay batches."""
        client = AsyncMock()

        with pytest.raises(ValueError, match="require at least one relay"):
            await connect_client_relays(client, [], timeout=15.0)

        client.add_relay.assert_not_awaited()
        client.try_connect.assert_not_awaited()

    async def test_rejects_overlay_relays_for_shared_session(self) -> None:
        """Shared client sessions reject overlay relays that need proxy policy."""
        client = AsyncMock()

        with pytest.raises(ValueError, match="clearnet relays only"):
            await connect_client_relays(client, [Relay(f"ws://{'a' * 56}.onion")], timeout=15.0)

        client.add_relay.assert_not_awaited()
        client.try_connect.assert_not_awaited()

    @pytest.mark.parametrize("timeout", [True, 0, -1.0, float("nan")])
    async def test_rejects_invalid_timeout_before_registration(self, timeout: object) -> None:
        """Malformed timeout budgets fail fast before any relay registration."""
        client = AsyncMock()

        with pytest.raises(ValueError, match="timeout must be a positive finite number"):
            await connect_client_relays(
                client,
                [Relay("wss://relay.example.com")],
                timeout=timeout,  # type: ignore[arg-type]
            )

        client.add_relay.assert_not_awaited()
        client.try_connect.assert_not_awaited()

    async def test_normalizes_connected_relays_to_stable_order(self) -> None:
        """Connected relay URLs are deduplicated and sorted in the normalized result."""
        client = AsyncMock()
        output = MagicMock()
        output.success = ["wss://relay.b", "wss://relay.a", "wss://relay.b"]
        output.failed = {"wss://relay.z": "timeout", "wss://relay.a": "rejected"}
        client.try_connect = AsyncMock(return_value=output)

        result = await connect_client_relays(
            client,
            [Relay("wss://relay1.example.com"), Relay("wss://relay2.example.com")],
            timeout=15.0,
        )

        assert result == ClientConnectResult(
            connected=("wss://relay.a", "wss://relay.b"),
            failed={"wss://relay.a": "rejected", "wss://relay.z": "timeout"},
        )
        assert list(result.failed) == ["wss://relay.a", "wss://relay.z"]

    def test_client_connect_result_rejects_invalid_connected_relays(self) -> None:
        with pytest.raises(ValueError, match="relay output contained invalid relay URL"):
            ClientConnectResult(connected=("1",), failed={})

    def test_client_connect_result_rejects_invalid_failed_values(self) -> None:
        with pytest.raises(TypeError, match="failed values must be str"):
            ClientConnectResult(
                connected=("wss://relay.example.com",),
                failed={"wss://relay.example.com": RuntimeError("boom")},
            )

    async def test_deduplicates_duplicate_relay_urls_before_registration(self) -> None:
        """Duplicate relay URLs do not trigger duplicate add_relay calls."""
        client = AsyncMock()
        output = MagicMock()
        output.success = []
        output.failed = {}
        client.try_connect = AsyncMock(return_value=output)

        relay_a = Relay("wss://relay1.example.com")
        relay_b = Relay("wss://relay2.example.com")

        await connect_client_relays(
            client,
            [relay_a, relay_a, relay_b, relay_b],
            timeout=15.0,
        )

        assert client.add_relay.await_count == 2


class TestCreateConnectedClient:
    async def test_rejects_empty_relay_list_before_client_creation(self) -> None:
        """Factory helper rejects empty shared sessions before allocating a client."""
        client = AsyncMock()
        create_client_func = AsyncMock(return_value=client)

        with pytest.raises(ValueError, match="require at least one relay"):
            await create_connected_client(
                [],
                dependencies=SharedSessionDependencies(
                    create_client=create_client_func,
                    shutdown_client=AsyncMock(),
                ),
                timeout=15.0,
            )

        create_client_func.assert_not_awaited()
        client.add_relay.assert_not_awaited()
        client.try_connect.assert_not_awaited()

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

    @pytest.mark.parametrize("timeout", [True, 0, -1.0, float("inf")])
    async def test_rejects_invalid_timeout_before_client_creation(self, timeout: object) -> None:
        """Malformed timeout budgets fail fast before allocating a shared client."""
        client = AsyncMock()
        create_client_func = AsyncMock(return_value=client)

        with pytest.raises(ValueError, match="timeout must be a positive finite number"):
            await create_connected_client(
                [Relay("wss://relay.example.com")],
                dependencies=SharedSessionDependencies(
                    create_client=create_client_func,
                    shutdown_client=AsyncMock(),
                ),
                timeout=timeout,  # type: ignore[arg-type]
            )

        create_client_func.assert_not_awaited()
        client.add_relay.assert_not_awaited()
        client.try_connect.assert_not_awaited()

    async def test_rejects_non_bool_allow_insecure_before_client_creation(self) -> None:
        """Malformed insecure toggles fail fast before allocating a shared client."""
        client = AsyncMock()
        create_client_func = AsyncMock(return_value=client)

        with pytest.raises(ValueError, match="allow_insecure must be a bool"):
            await create_connected_client(
                [Relay("wss://relay.example.com")],
                dependencies=SharedSessionDependencies(
                    create_client=create_client_func,
                    shutdown_client=AsyncMock(),
                ),
                timeout=15.0,
                allow_insecure=1,  # type: ignore[arg-type]
            )

        create_client_func.assert_not_awaited()
        client.add_relay.assert_not_awaited()
        client.try_connect.assert_not_awaited()

    async def test_keeps_clearnet_sessions_supported(self) -> None:
        """Clearnet multi-relay sessions still normalize the connect result."""
        client = AsyncMock()
        relay_url = MagicMock()
        relay_url.__str__.return_value = "wss://relay.connected"
        failed_relay = MagicMock()
        failed_relay.__str__.return_value = "wss://relay.failed"
        output = MagicMock()
        output.success = [relay_url]
        output.failed = {failed_relay: RuntimeError("timeout")}
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
            connected=("wss://relay.connected",),
            failed={"wss://relay.failed": "timeout"},
        )
        assert list(result.failed) == ["wss://relay.failed"]

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

    async def test_releases_client_on_unexpected_connect_helper_failure(self) -> None:
        """Unexpected helper failures still release the partial shared client."""
        client = AsyncMock()
        create_client_func = AsyncMock(return_value=client)
        shutdown_client_func = AsyncMock(side_effect=NostrSdkError("shutdown noise"))
        relays = [Relay("wss://relay.example.com")]

        with (
            patch(
                "bigbrotr.utils.protocol_sessions.connect_client_relays",
                new=AsyncMock(side_effect=RuntimeError("helper boom")),
            ) as mock_connect,
            pytest.raises(RuntimeError, match="helper boom"),
        ):
            await create_connected_client(
                relays,
                dependencies=SharedSessionDependencies(
                    create_client=create_client_func,
                    shutdown_client=shutdown_client_func,
                ),
                timeout=15.0,
            )

        create_client_func.assert_awaited_once_with(keys=None, allow_insecure=False)
        mock_connect.assert_awaited_once_with(client, relays, timeout=15.0)
        shutdown_client_func.assert_awaited_once_with(client)
