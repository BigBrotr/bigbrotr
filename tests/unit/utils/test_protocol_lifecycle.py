"""Unit tests for the ``bigbrotr.utils.protocol_lifecycle`` module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from bigbrotr.utils.protocol_lifecycle import _await_if_needed, shutdown_client


class TestAwaitIfNeeded:
    async def test_returns_plain_values_unchanged(self) -> None:
        value = object()
        assert await _await_if_needed(value) is value

    async def test_awaits_coroutines(self) -> None:
        async def _sample() -> str:
            return "done"

        assert await _await_if_needed(_sample()) == "done"


class TestShutdownClient:
    async def test_shutdown_client_runs_full_best_effort_cleanup(self) -> None:
        database = MagicMock()
        database.wipe = AsyncMock()

        client = MagicMock()
        client.unsubscribe_all = AsyncMock()
        client.force_remove_all_relays = AsyncMock()
        client.database = AsyncMock(return_value=database)
        client.shutdown = AsyncMock()

        await shutdown_client(client)

        client.unsubscribe_all.assert_awaited_once_with()
        client.force_remove_all_relays.assert_awaited_once_with()
        client.database.assert_awaited_once_with()
        database.wipe.assert_awaited_once_with()
        client.shutdown.assert_awaited_once_with()

    async def test_shutdown_client_continues_when_steps_fail(self) -> None:
        database = MagicMock()
        database.wipe = AsyncMock(side_effect=RuntimeError("wipe failed"))

        client = MagicMock()
        client.unsubscribe_all = AsyncMock(side_effect=OSError("unsubscribe failed"))
        client.force_remove_all_relays = AsyncMock(side_effect=RuntimeError("remove failed"))
        client.database = AsyncMock(return_value=database)
        client.shutdown = AsyncMock()

        await shutdown_client(client)

        client.unsubscribe_all.assert_awaited_once_with()
        client.force_remove_all_relays.assert_awaited_once_with()
        client.database.assert_awaited_once_with()
        database.wipe.assert_awaited_once_with()
        client.shutdown.assert_awaited_once_with()

    async def test_shutdown_client_supports_sync_database_apis(self) -> None:
        database = MagicMock()
        database.wipe = MagicMock()

        client = MagicMock()
        client.unsubscribe_all = MagicMock()
        client.force_remove_all_relays = MagicMock()
        client.database = MagicMock(return_value=database)
        client.shutdown = MagicMock()

        await shutdown_client(client)

        client.unsubscribe_all.assert_called_once_with()
        client.force_remove_all_relays.assert_called_once_with()
        client.database.assert_called_once_with()
        database.wipe.assert_called_once_with()
        client.shutdown.assert_called_once_with()
