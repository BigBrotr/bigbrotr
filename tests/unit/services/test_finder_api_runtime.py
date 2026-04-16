"""Unit tests for Finder API runtime helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bigbrotr.models import Relay
from bigbrotr.services.common.types import ApiCheckpoint
from bigbrotr.services.finder import ApiSourceConfig
from bigbrotr.services.finder.api_runtime import (
    ApiDiscoveryPersistenceContext,
    ApiDiscoveryWorkerContext,
    find_from_api_worker,
    persist_api_discovery_results,
)


@pytest.fixture
def runtime_brotr() -> MagicMock:
    return MagicMock()


class TestFindFromApiWorker:
    async def test_loads_checkpoints_and_streams_attempts(self, runtime_brotr: MagicMock) -> None:
        source = ApiSourceConfig(url="https://api.example.com", expression="[*]")
        relay = Relay("wss://relay.example.com")
        checkpoint = ApiCheckpoint(key=source.url, timestamp=123)
        fetch_checkpoints = AsyncMock(return_value=[checkpoint])
        logger = MagicMock()

        async def fetch_api_fn(*args: object) -> list[Relay]:
            return [relay]

        class _Session:
            async def __aenter__(self) -> _Session:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

        items = [
            item
            async for item in find_from_api_worker(
                sources=[source],
                context=ApiDiscoveryWorkerContext(
                    brotr=runtime_brotr,
                    cooldown=0,
                    now=1_000,
                    max_response_size=1024,
                    request_delay=0.0,
                    is_running=lambda: True,
                    wait=AsyncMock(return_value=False),
                    fetch_api_fn=fetch_api_fn,
                    client_session_factory=_Session,
                    recoverable_errors=(TimeoutError, OSError, ValueError),
                    checkpoint_timestamp=lambda: 456,
                    logger=logger,
                    fetch_api_checkpoints_fn=fetch_checkpoints,
                ),
            )
        ]

        assert items == [([relay], ApiCheckpoint(key=source.url, timestamp=456))]
        fetch_checkpoints.assert_awaited_once_with(runtime_brotr, [source.url])

    async def test_stops_when_wait_requests_shutdown(self, runtime_brotr: MagicMock) -> None:
        sources = [
            ApiSourceConfig(url="https://api1.example.com", expression="[*]"),
            ApiSourceConfig(url="https://api2.example.com", expression="[*]"),
        ]
        relay = Relay("wss://relay.example.com")
        fetch_checkpoints = AsyncMock(
            return_value=[ApiCheckpoint(key=source.url, timestamp=0) for source in sources]
        )
        fetch_api_fn = AsyncMock(return_value=[relay])
        wait = AsyncMock(return_value=True)

        class _Session:
            async def __aenter__(self) -> _Session:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

        items = [
            item
            async for item in find_from_api_worker(
                sources=sources,
                context=ApiDiscoveryWorkerContext(
                    brotr=runtime_brotr,
                    cooldown=0,
                    now=1_000,
                    max_response_size=1024,
                    request_delay=1.0,
                    is_running=lambda: True,
                    wait=wait,
                    fetch_api_fn=fetch_api_fn,
                    client_session_factory=_Session,
                    recoverable_errors=(TimeoutError, OSError, ValueError),
                    checkpoint_timestamp=lambda: 456,
                    logger=MagicMock(),
                    fetch_api_checkpoints_fn=fetch_checkpoints,
                ),
            )
        ]

        assert len(items) == 1
        fetch_api_fn.assert_awaited_once()
        wait.assert_awaited_once_with(1.0)


class TestPersistApiDiscoveryResults:
    async def test_persists_and_clears_state(self, runtime_brotr: MagicMock) -> None:
        relay = Relay("wss://relay.example.com")
        checkpoint = ApiCheckpoint(key="https://api.example.com", timestamp=123)
        buffer = [relay]
        pending_checkpoints = [checkpoint]
        upsert = AsyncMock()
        insert_relays = AsyncMock(return_value=1)
        set_gauge = MagicMock()

        found = await persist_api_discovery_results(
            buffer=buffer,
            pending_checkpoints=pending_checkpoints,
            context=ApiDiscoveryPersistenceContext(
                brotr=runtime_brotr,
                upsert_api_checkpoints_fn=upsert,
                insert_relays_fn=insert_relays,
                set_gauge=set_gauge,
            ),
        )

        assert found == 1
        assert buffer == []
        assert pending_checkpoints == []
        upsert.assert_awaited_once_with(runtime_brotr, [checkpoint])
        insert_relays.assert_awaited_once_with(runtime_brotr, [relay])
        set_gauge.assert_called_once_with("candidates_found_from_api", 1)

    async def test_empty_checkpoints_still_inserts_relays(self, runtime_brotr: MagicMock) -> None:
        relay = Relay("wss://relay.example.com")
        upsert = AsyncMock()
        insert_relays = AsyncMock(return_value=1)

        found = await persist_api_discovery_results(
            buffer=[relay],
            pending_checkpoints=[],
            context=ApiDiscoveryPersistenceContext(
                brotr=runtime_brotr,
                upsert_api_checkpoints_fn=upsert,
                insert_relays_fn=insert_relays,
                set_gauge=MagicMock(),
            ),
        )

        assert found == 1
        upsert.assert_not_awaited()
        insert_relays.assert_awaited_once()
