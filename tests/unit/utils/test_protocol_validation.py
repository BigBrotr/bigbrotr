"""Unit tests for the ``bigbrotr.utils.protocol_validation`` module."""

from __future__ import annotations

import contextlib
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
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

    async def test_sdk_connect_error_returns_false(self) -> None:
        relay = Relay("wss://relay.example.com")
        connect_relay = AsyncMock(side_effect=NostrSdkError("sdk connect failed"))
        shutdown_client = AsyncMock()

        result = await validate_relay_protocol(
            relay,
            _context(
                connect_relay=connect_relay,
                shutdown_client=shutdown_client,
            ),
            RelayValidationOptions(connect_timeout=5.0),
        )

        assert result is False
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

    async def test_fetch_sdk_error_returns_false(self) -> None:
        relay = Relay("wss://relay.example.com")
        client = MagicMock()
        client.fetch_events = AsyncMock(side_effect=NostrSdkError("sdk fetch failed"))
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


class TestRelayValidationOptions:
    @pytest.mark.parametrize("value", [True, 0, -1, float("nan")])
    def test_rejects_invalid_connect_timeout(self, value: object) -> None:
        with pytest.raises(ValueError, match="connect_timeout must be a positive finite number"):
            RelayValidationOptions(connect_timeout=value)  # type: ignore[arg-type]

    @pytest.mark.parametrize("value", [True, 0, -1, float("inf")])
    def test_rejects_invalid_overall_timeout(self, value: object) -> None:
        with pytest.raises(ValueError, match="overall_timeout must be a positive finite number"):
            RelayValidationOptions(connect_timeout=5.0, overall_timeout=value)  # type: ignore[arg-type]

    def test_rejects_non_bool_allow_insecure(self) -> None:
        with pytest.raises(ValueError, match="allow_insecure must be a bool"):
            RelayValidationOptions(connect_timeout=5.0, allow_insecure=1)  # type: ignore[arg-type]
