"""
Unit tests for models.nips.nip66.rtt module.

Tests:
- Nip66RttMetadata._validate_network() - network/proxy validation
- Nip66RttMetadata._test_open() - connection phase
- Nip66RttMetadata._test_read() - read phase
- Nip66RttMetadata._test_write() - write phase
- Nip66RttMetadata._verify_write() - write verification
- Nip66RttMetadata._cleanup() - client disconnection
- Nip66RttMetadata.rtt() - full RTT test
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models import Relay
from models.nips.nip66.rtt import Nip66RttMetadata


class TestNip66RttMetadataValidateNetwork:
    """Test Nip66RttMetadata._validate_network() method."""

    def test_clearnet_without_proxy_valid(self, relay: Relay) -> None:
        """Clearnet relay without proxy is valid."""
        # Should not raise
        Nip66RttMetadata._validate_network(relay, None)

    def test_clearnet_with_proxy_valid(self, relay: Relay) -> None:
        """Clearnet relay with proxy is valid."""
        Nip66RttMetadata._validate_network(relay, "socks5://localhost:9050")

    def test_tor_without_proxy_raises(self, tor_relay: Relay) -> None:
        """Tor relay without proxy raises ValueError."""
        with pytest.raises(ValueError, match="overlay network tor requires proxy"):
            Nip66RttMetadata._validate_network(tor_relay, None)

    def test_tor_with_proxy_valid(self, tor_relay: Relay) -> None:
        """Tor relay with proxy is valid."""
        Nip66RttMetadata._validate_network(tor_relay, "socks5://localhost:9050")

    def test_i2p_without_proxy_raises(self, i2p_relay: Relay) -> None:
        """I2P relay without proxy raises ValueError."""
        with pytest.raises(ValueError, match="overlay network i2p requires proxy"):
            Nip66RttMetadata._validate_network(i2p_relay, None)

    def test_i2p_with_proxy_valid(self, i2p_relay: Relay) -> None:
        """I2P relay with proxy is valid."""
        Nip66RttMetadata._validate_network(i2p_relay, "socks5://localhost:4447")

    def test_loki_without_proxy_raises(self, loki_relay: Relay) -> None:
        """Lokinet relay without proxy raises ValueError."""
        with pytest.raises(ValueError, match="overlay network loki requires proxy"):
            Nip66RttMetadata._validate_network(loki_relay, None)


class TestNip66RttMetadataTestOpen:
    """Test Nip66RttMetadata._test_open() phase method."""

    @pytest.mark.asyncio
    async def test_successful_connection_returns_client_and_rtt(
        self,
        relay: Relay,
        mock_keys: MagicMock,
        mock_nostr_client: MagicMock,
    ) -> None:
        """Successful connection returns (client, rtt_ms)."""
        logs: dict[str, Any] = {}

        async def mock_connect(*args: Any, **kwargs: Any) -> MagicMock:
            return mock_nostr_client

        with patch("utils.transport.connect_relay", side_effect=mock_connect):
            client, rtt_open = await Nip66RttMetadata._test_open(
                relay, mock_keys, None, 10.0, True, logs
            )

        assert client is mock_nostr_client
        assert rtt_open is not None
        assert isinstance(rtt_open, int)
        assert rtt_open >= 0
        assert "open_success" not in logs  # Success not set in logs yet by _test_open

    @pytest.mark.asyncio
    async def test_connection_failure_returns_none_and_sets_logs(
        self,
        relay: Relay,
        mock_keys: MagicMock,
    ) -> None:
        """Connection failure returns (None, None) and sets cascading failure logs."""
        logs: dict[str, Any] = {}

        async def mock_connect(*args: Any, **kwargs: Any) -> None:
            raise TimeoutError("Connection refused")

        with patch("utils.transport.connect_relay", side_effect=mock_connect):
            client, rtt_open = await Nip66RttMetadata._test_open(
                relay, mock_keys, None, 10.0, True, logs
            )

        assert client is None
        assert rtt_open is None
        assert logs["open_success"] is False
        assert "Connection refused" in logs["open_reason"]
        assert logs["read_success"] is False
        assert logs["write_success"] is False

    @pytest.mark.asyncio
    async def test_connection_with_proxy(
        self,
        relay: Relay,
        mock_keys: MagicMock,
        mock_nostr_client: MagicMock,
    ) -> None:
        """Connection with proxy passes proxy_url to connect_relay."""
        logs: dict[str, Any] = {}
        proxy_url = "socks5://localhost:9050"

        async def mock_connect(
            relay: Relay,
            keys: Any,
            proxy_url: str | None,
            timeout: float,
            allow_insecure: bool,
        ) -> MagicMock:
            assert proxy_url == "socks5://localhost:9050"
            return mock_nostr_client

        with patch("utils.transport.connect_relay", side_effect=mock_connect):
            client, _ = await Nip66RttMetadata._test_open(
                relay, mock_keys, proxy_url, 10.0, True, logs
            )

        assert client is not None


class TestNip66RttMetadataTestRead:
    """Test Nip66RttMetadata._test_read() phase method."""

    @pytest.mark.asyncio
    async def test_successful_read_returns_rtt(
        self,
        mock_nostr_client: MagicMock,
        mock_read_filter: MagicMock,
    ) -> None:
        """Successful read returns read_success=True with rtt_read."""
        result = await Nip66RttMetadata._test_read(
            mock_nostr_client, mock_read_filter, 10.0, "wss://relay.example.com"
        )

        assert result["read_success"] is True
        assert result["rtt_read"] is not None
        assert isinstance(result["rtt_read"], int)
        assert result["rtt_read"] >= 0
        assert result["read_reason"] is None

    @pytest.mark.asyncio
    async def test_no_events_returns_failure(
        self,
        mock_nostr_client: MagicMock,
        mock_read_filter: MagicMock,
    ) -> None:
        """No events returned results in read failure."""
        mock_stream = AsyncMock()
        mock_stream.next = AsyncMock(return_value=None)
        mock_nostr_client.stream_events = AsyncMock(return_value=mock_stream)

        result = await Nip66RttMetadata._test_read(
            mock_nostr_client, mock_read_filter, 10.0, "wss://relay.example.com"
        )

        assert result["read_success"] is False
        assert result["rtt_read"] is None
        assert "no events returned" in result["read_reason"]

    @pytest.mark.asyncio
    async def test_exception_returns_failure(
        self,
        mock_nostr_client: MagicMock,
        mock_read_filter: MagicMock,
    ) -> None:
        """Exception during read results in failure."""
        mock_nostr_client.stream_events = AsyncMock(side_effect=Exception("Stream error"))

        result = await Nip66RttMetadata._test_read(
            mock_nostr_client, mock_read_filter, 10.0, "wss://relay.example.com"
        )

        assert result["read_success"] is False
        assert result["rtt_read"] is None
        assert "Stream error" in result["read_reason"]

    @pytest.mark.asyncio
    async def test_uses_timeout_in_stream_events(
        self,
        mock_nostr_client: MagicMock,
        mock_read_filter: MagicMock,
    ) -> None:
        """Timeout is passed to stream_events."""
        await Nip66RttMetadata._test_read(
            mock_nostr_client, mock_read_filter, 15.0, "wss://relay.example.com"
        )

        mock_nostr_client.stream_events.assert_called_once()
        call_kwargs = mock_nostr_client.stream_events.call_args.kwargs
        assert call_kwargs["timeout"] == timedelta(seconds=15.0)


class TestNip66RttMetadataTestWrite:
    """Test Nip66RttMetadata._test_write() phase method."""

    @pytest.mark.asyncio
    async def test_successful_write_with_verification(
        self,
        mock_nostr_client: MagicMock,
        mock_event_builder: MagicMock,
    ) -> None:
        """Successful write returns write_success=True with rtt_write."""
        from nostr_sdk import RelayUrl

        relay_url = RelayUrl.parse("wss://relay.example.com")

        # Mock successful send
        mock_output = MagicMock()
        mock_output.success = [relay_url]
        mock_output.failed = {}
        mock_output.id = MagicMock()
        mock_nostr_client.send_event_builder = AsyncMock(return_value=mock_output)

        # Mock successful verification
        with patch.object(
            Nip66RttMetadata,
            "_verify_write",
            new_callable=AsyncMock,
            return_value={"verified": True, "reason": None},
        ):
            result = await Nip66RttMetadata._test_write(
                mock_nostr_client,
                mock_event_builder,
                relay_url,
                10.0,
                "wss://relay.example.com",
            )

        assert result["write_success"] is True
        assert result["rtt_write"] is not None
        assert isinstance(result["rtt_write"], int)
        assert result["write_reason"] is None

    @pytest.mark.asyncio
    async def test_write_rejected_by_relay(
        self,
        mock_nostr_client: MagicMock,
        mock_event_builder: MagicMock,
    ) -> None:
        """Write rejected by relay returns failure."""
        from nostr_sdk import RelayUrl

        relay_url = RelayUrl.parse("wss://relay.example.com")

        mock_output = MagicMock()
        mock_output.success = []
        mock_output.failed = {relay_url: "auth-required: please authenticate"}
        mock_output.id = MagicMock()
        mock_nostr_client.send_event_builder = AsyncMock(return_value=mock_output)

        result = await Nip66RttMetadata._test_write(
            mock_nostr_client,
            mock_event_builder,
            relay_url,
            10.0,
            "wss://relay.example.com",
        )

        assert result["write_success"] is False
        assert result["rtt_write"] is None
        assert "auth-required" in result["write_reason"]

    @pytest.mark.asyncio
    async def test_no_response_from_relay(
        self,
        mock_nostr_client: MagicMock,
        mock_event_builder: MagicMock,
    ) -> None:
        """No response from relay returns failure."""
        from nostr_sdk import RelayUrl

        relay_url = RelayUrl.parse("wss://relay.example.com")

        mock_output = MagicMock()
        mock_output.success = []
        mock_output.failed = {}
        mock_output.id = MagicMock()
        mock_nostr_client.send_event_builder = AsyncMock(return_value=mock_output)

        result = await Nip66RttMetadata._test_write(
            mock_nostr_client,
            mock_event_builder,
            relay_url,
            10.0,
            "wss://relay.example.com",
        )

        assert result["write_success"] is False
        assert "no response from relay" in result["write_reason"]

    @pytest.mark.asyncio
    async def test_exception_during_write(
        self,
        mock_nostr_client: MagicMock,
        mock_event_builder: MagicMock,
    ) -> None:
        """Exception during write returns failure."""
        from nostr_sdk import RelayUrl

        relay_url = RelayUrl.parse("wss://relay.example.com")
        mock_nostr_client.send_event_builder = AsyncMock(side_effect=Exception("Send error"))

        result = await Nip66RttMetadata._test_write(
            mock_nostr_client,
            mock_event_builder,
            relay_url,
            10.0,
            "wss://relay.example.com",
        )

        assert result["write_success"] is False
        assert "Send error" in result["write_reason"]

    @pytest.mark.asyncio
    async def test_verification_fails(
        self,
        mock_nostr_client: MagicMock,
        mock_event_builder: MagicMock,
    ) -> None:
        """Write accepted but verification fails."""
        from nostr_sdk import RelayUrl

        relay_url = RelayUrl.parse("wss://relay.example.com")

        mock_output = MagicMock()
        mock_output.success = [relay_url]
        mock_output.failed = {}
        mock_output.id = MagicMock()
        mock_nostr_client.send_event_builder = AsyncMock(return_value=mock_output)

        with patch.object(
            Nip66RttMetadata,
            "_verify_write",
            new_callable=AsyncMock,
            return_value={"verified": False, "reason": "unverified: accepted but not retrievable"},
        ):
            result = await Nip66RttMetadata._test_write(
                mock_nostr_client,
                mock_event_builder,
                relay_url,
                10.0,
                "wss://relay.example.com",
            )

        assert result["write_success"] is False
        assert "unverified" in result["write_reason"]


class TestNip66RttMetadataVerifyWrite:
    """Test Nip66RttMetadata._verify_write() method."""

    @pytest.mark.asyncio
    async def test_successful_verification(self, mock_nostr_client: MagicMock) -> None:
        """Successful verification returns verified=True."""
        from nostr_sdk import EventId

        # Create a proper EventId (requires 64 hex chars)
        event_id = EventId.parse("a" * 64)

        mock_stream = AsyncMock()
        mock_stream.next = AsyncMock(return_value=MagicMock())  # Event found
        mock_nostr_client.stream_events = AsyncMock(return_value=mock_stream)

        result = await Nip66RttMetadata._verify_write(
            mock_nostr_client, event_id, 10.0, "wss://relay.example.com"
        )

        assert result["verified"] is True
        assert result["reason"] is None

    @pytest.mark.asyncio
    async def test_event_not_found(self, mock_nostr_client: MagicMock) -> None:
        """Event not found returns verified=False."""
        from nostr_sdk import EventId

        event_id = EventId.parse("a" * 64)

        mock_stream = AsyncMock()
        mock_stream.next = AsyncMock(return_value=None)  # No event found
        mock_nostr_client.stream_events = AsyncMock(return_value=mock_stream)

        result = await Nip66RttMetadata._verify_write(
            mock_nostr_client, event_id, 10.0, "wss://relay.example.com"
        )

        assert result["verified"] is False
        assert "accepted but not retrievable" in result["reason"]

    @pytest.mark.asyncio
    async def test_exception_during_verification(self, mock_nostr_client: MagicMock) -> None:
        """Exception during verification returns verified=False."""
        from nostr_sdk import EventId

        event_id = EventId.parse("a" * 64)
        mock_nostr_client.stream_events = AsyncMock(side_effect=Exception("Verification error"))

        result = await Nip66RttMetadata._verify_write(
            mock_nostr_client, event_id, 10.0, "wss://relay.example.com"
        )

        assert result["verified"] is False
        assert "Verification error" in result["reason"]


class TestNip66RttMetadataCleanup:
    """Test Nip66RttMetadata._cleanup() method."""

    @pytest.mark.asyncio
    async def test_successful_disconnect(self, mock_nostr_client: MagicMock) -> None:
        """Cleanup disconnects the client."""
        await Nip66RttMetadata._cleanup(mock_nostr_client)
        mock_nostr_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_exception_suppressed(self, mock_nostr_client: MagicMock) -> None:
        """Exceptions during disconnect are suppressed."""
        mock_nostr_client.disconnect = AsyncMock(side_effect=Exception("Disconnect error"))

        # Should not raise
        await Nip66RttMetadata._cleanup(mock_nostr_client)


class TestNip66RttMetadataRtt:
    """Test Nip66RttMetadata.rtt() main entry point."""

    @pytest.mark.asyncio
    async def test_clearnet_returns_rtt_metadata(
        self,
        relay: Relay,
        mock_keys: MagicMock,
        mock_event_builder: MagicMock,
        mock_read_filter: MagicMock,
        mock_nostr_client: MagicMock,
    ) -> None:
        """Returns Nip66RttMetadata for clearnet relay."""

        async def mock_connect(*args: Any, **kwargs: Any) -> MagicMock:
            return mock_nostr_client

        with patch("utils.transport.connect_relay", side_effect=mock_connect):
            result = await Nip66RttMetadata.rtt(
                relay,
                mock_keys,
                mock_event_builder,
                mock_read_filter,
                timeout=10.0,
            )

        assert isinstance(result, Nip66RttMetadata)
        assert result.data.rtt_open is not None
        assert result.logs.open_success is True

    @pytest.mark.asyncio
    async def test_connection_failure_returns_rtt_with_failure_logs(
        self,
        relay: Relay,
        mock_keys: MagicMock,
        mock_event_builder: MagicMock,
        mock_read_filter: MagicMock,
    ) -> None:
        """Connection failure returns Nip66RttMetadata with failure logged."""

        async def mock_connect(*args: Any, **kwargs: Any) -> None:
            raise TimeoutError("Connection refused")

        with patch("utils.transport.connect_relay", side_effect=mock_connect):
            result = await Nip66RttMetadata.rtt(
                relay,
                mock_keys,
                mock_event_builder,
                mock_read_filter,
                timeout=10.0,
            )

        assert isinstance(result, Nip66RttMetadata)
        assert result.logs.open_success is False
        assert "Connection refused" in result.logs.open_reason
        assert result.data.rtt_open is None

    @pytest.mark.asyncio
    async def test_overlay_without_proxy_raises(
        self,
        tor_relay: Relay,
        mock_keys: MagicMock,
        mock_event_builder: MagicMock,
        mock_read_filter: MagicMock,
    ) -> None:
        """Overlay network without proxy raises ValueError."""
        with pytest.raises(ValueError, match="overlay network tor requires proxy"):
            await Nip66RttMetadata.rtt(
                tor_relay,
                mock_keys,
                mock_event_builder,
                mock_read_filter,
                timeout=10.0,
                proxy_url=None,
            )

    @pytest.mark.asyncio
    async def test_overlay_with_proxy_works(
        self,
        tor_relay: Relay,
        mock_keys: MagicMock,
        mock_event_builder: MagicMock,
        mock_read_filter: MagicMock,
        mock_nostr_client: MagicMock,
    ) -> None:
        """Overlay network with proxy succeeds."""

        async def mock_connect(*args: Any, **kwargs: Any) -> MagicMock:
            return mock_nostr_client

        with patch("utils.transport.connect_relay", side_effect=mock_connect):
            result = await Nip66RttMetadata.rtt(
                tor_relay,
                mock_keys,
                mock_event_builder,
                mock_read_filter,
                timeout=10.0,
                proxy_url="socks5://localhost:9050",
            )

        assert isinstance(result, Nip66RttMetadata)

    @pytest.mark.asyncio
    async def test_uses_default_timeout(
        self,
        relay: Relay,
        mock_keys: MagicMock,
        mock_event_builder: MagicMock,
        mock_read_filter: MagicMock,
        mock_nostr_client: MagicMock,
    ) -> None:
        """Uses default timeout when None provided."""

        async def mock_connect(*args: Any, **kwargs: Any) -> MagicMock:
            return mock_nostr_client

        with patch("utils.transport.connect_relay", side_effect=mock_connect):
            result = await Nip66RttMetadata.rtt(
                relay,
                mock_keys,
                mock_event_builder,
                mock_read_filter,
                timeout=None,
            )

        assert isinstance(result, Nip66RttMetadata)

    @pytest.mark.asyncio
    async def test_cleanup_called_after_phases(
        self,
        relay: Relay,
        mock_keys: MagicMock,
        mock_event_builder: MagicMock,
        mock_read_filter: MagicMock,
        mock_nostr_client: MagicMock,
    ) -> None:
        """Cleanup is called after read/write phases."""

        async def mock_connect(*args: Any, **kwargs: Any) -> MagicMock:
            return mock_nostr_client

        with (
            patch("utils.transport.connect_relay", side_effect=mock_connect),
            patch.object(Nip66RttMetadata, "_cleanup", new_callable=AsyncMock) as mock_cleanup,
        ):
            await Nip66RttMetadata.rtt(
                relay,
                mock_keys,
                mock_event_builder,
                mock_read_filter,
                timeout=10.0,
            )

        mock_cleanup.assert_called_once_with(mock_nostr_client)


class TestNip66RttMetadataHelperMethods:
    """Test Nip66RttMetadata helper methods."""

    def test_empty_rtt_data(self) -> None:
        """_empty_rtt_data returns dict with None values."""
        result = Nip66RttMetadata._empty_rtt_data()
        assert result == {"rtt_open": None, "rtt_read": None, "rtt_write": None}

    def test_empty_logs(self) -> None:
        """_empty_logs returns dict with None values."""
        result = Nip66RttMetadata._empty_logs()
        expected = {
            "open_success": None,
            "open_reason": None,
            "read_success": None,
            "read_reason": None,
            "write_success": None,
            "write_reason": None,
        }
        assert result == expected

    def test_build_result(self) -> None:
        """_build_result creates Nip66RttMetadata from dicts."""
        rtt_data = {"rtt_open": 100, "rtt_read": 150, "rtt_write": None}
        logs = {
            "open_success": True,
            "open_reason": None,
            "read_success": True,
            "read_reason": None,
            "write_success": None,
            "write_reason": None,
        }

        result = Nip66RttMetadata._build_result(rtt_data, logs)

        assert isinstance(result, Nip66RttMetadata)
        assert result.data.rtt_open == 100
        assert result.data.rtt_read == 150
        assert result.logs.open_success is True
        assert result.logs.read_success is True
