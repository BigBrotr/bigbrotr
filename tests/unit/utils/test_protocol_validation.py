"""Unit tests for the ``bigbrotr.utils.protocol_validation`` module."""

from __future__ import annotations

import contextlib
import logging
from unittest.mock import AsyncMock, MagicMock

from nostr_sdk import NostrSdkError

from bigbrotr.models.relay import Relay
from bigbrotr.utils.protocol_validation import (
    RelayValidationContext,
    RelayValidationOptions,
    validate_relay_protocol,
)


def _context(
    *,
    connect_relay: AsyncMock,
    shutdown_client: AsyncMock | None = None,
) -> RelayValidationContext:
    return RelayValidationContext(
        connect_relay=connect_relay,
        shutdown_client=shutdown_client or AsyncMock(),
        suppress_stderr=contextlib.nullcontext,
        logger=logging.getLogger("test.protocol_validation"),
    )


class TestValidateRelayProtocol:
    async def test_fetch_success_returns_true_and_shuts_down_client(self) -> None:
        relay = Relay("wss://relay.example.com")
        client = AsyncMock()
        client.fetch_events = AsyncMock(return_value=[])
        shutdown_client = AsyncMock()

        result = await validate_relay_protocol(
            relay,
            _context(
                connect_relay=AsyncMock(return_value=client),
                shutdown_client=shutdown_client,
            ),
            RelayValidationOptions(connect_timeout=5.0),
        )

        assert result is True
        client.fetch_events.assert_awaited_once()
        shutdown_client.assert_awaited_once_with(client)

    async def test_auth_required_connection_is_treated_as_success(self) -> None:
        relay = Relay("wss://relay.example.com")
        connect_relay = AsyncMock(side_effect=OSError("auth-required: please authenticate"))
        shutdown_client = AsyncMock()

        result = await validate_relay_protocol(
            relay,
            _context(
                connect_relay=connect_relay,
                shutdown_client=shutdown_client,
            ),
            RelayValidationOptions(connect_timeout=5.0),
        )

        assert result is True
        connect_relay.assert_awaited_once()
        shutdown_client.assert_not_awaited()

    async def test_shutdown_timeout_is_suppressed_after_success(self) -> None:
        relay = Relay("wss://relay.example.com")
        client = AsyncMock()
        client.fetch_events = AsyncMock(return_value=[])
        shutdown_client = AsyncMock(side_effect=TimeoutError("stuck shutdown"))

        result = await validate_relay_protocol(
            relay,
            _context(
                connect_relay=AsyncMock(return_value=client),
                shutdown_client=shutdown_client,
            ),
            RelayValidationOptions(connect_timeout=5.0),
        )

        assert result is True
        client.fetch_events.assert_awaited_once()
        shutdown_client.assert_awaited_once_with(client)

    async def test_shutdown_sdk_error_is_suppressed_after_success(self) -> None:
        relay = Relay("wss://relay.example.com")
        client = AsyncMock()
        client.fetch_events = AsyncMock(return_value=[])
        shutdown_client = AsyncMock(side_effect=NostrSdkError("sdk shutdown failed"))

        result = await validate_relay_protocol(
            relay,
            _context(
                connect_relay=AsyncMock(return_value=client),
                shutdown_client=shutdown_client,
            ),
            RelayValidationOptions(connect_timeout=5.0),
        )

        assert result is True
        client.fetch_events.assert_awaited_once()
        shutdown_client.assert_awaited_once_with(client)

    async def test_fetch_timeout_returns_false(self) -> None:
        relay = Relay("wss://relay.example.com")
        client = MagicMock()
        client.fetch_events = AsyncMock(side_effect=TimeoutError("fetch timed out"))
        shutdown_client = AsyncMock()

        result = await validate_relay_protocol(
            relay,
            _context(
                connect_relay=AsyncMock(return_value=client),
                shutdown_client=shutdown_client,
            ),
            RelayValidationOptions(connect_timeout=5.0),
        )

        assert result is False
        shutdown_client.assert_awaited_once_with(client)
