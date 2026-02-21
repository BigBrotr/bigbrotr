"""
Unit tests for utils.transport module.

Tests:
- InsecureWebSocketAdapter - WebSocket adapter for insecure connections
- InsecureWebSocketTransport - Custom transport with SSL disabled
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bigbrotr.utils.transport import (
    InsecureWebSocketAdapter,
    InsecureWebSocketTransport,
)


# =============================================================================
# InsecureWebSocketAdapter Tests
# =============================================================================


class TestInsecureWebSocketAdapterSend:
    """Tests for InsecureWebSocketAdapter.send() method."""

    async def test_send_text_message(self) -> None:
        """Test sending text message via WebSocket."""
        from nostr_sdk import WebSocketMessage

        mock_ws = AsyncMock()
        mock_session = AsyncMock()
        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)

        msg = WebSocketMessage.TEXT("test message")
        await adapter.send(msg)

        mock_ws.send_str.assert_called_once_with("test message")

    async def test_send_binary_message(self) -> None:
        """Test sending binary message via WebSocket."""
        from nostr_sdk import WebSocketMessage

        mock_ws = AsyncMock()
        mock_session = AsyncMock()
        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)

        msg = WebSocketMessage.BINARY(b"binary data")
        await adapter.send(msg)

        mock_ws.send_bytes.assert_called_once_with(b"binary data")

    async def test_send_ping_message(self) -> None:
        """Test sending ping message via WebSocket."""
        from nostr_sdk import WebSocketMessage

        mock_ws = AsyncMock()
        mock_session = AsyncMock()
        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)

        msg = WebSocketMessage.PING(b"ping data")
        await adapter.send(msg)

        mock_ws.ping.assert_called_once_with(b"ping data")

    async def test_send_pong_message(self) -> None:
        """Test sending pong message via WebSocket."""
        from nostr_sdk import WebSocketMessage

        mock_ws = AsyncMock()
        mock_session = AsyncMock()
        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)

        msg = WebSocketMessage.PONG(b"pong data")
        await adapter.send(msg)

        mock_ws.pong.assert_called_once_with(b"pong data")


class TestInsecureWebSocketAdapterReceive:
    """Tests for InsecureWebSocketAdapter.recv() method."""

    async def test_recv_text_message(self) -> None:
        """Test receiving text message from WebSocket."""
        import aiohttp

        mock_ws = AsyncMock()
        mock_session = AsyncMock()

        mock_msg = MagicMock()
        mock_msg.type = aiohttp.WSMsgType.TEXT
        mock_msg.data = "received text"
        mock_ws.receive = AsyncMock(return_value=mock_msg)

        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)
        result = await adapter.recv()

        assert result is not None
        assert result.is_text()
        assert result.text == "received text"

    async def test_recv_binary_message(self) -> None:
        """Test receiving binary message from WebSocket."""
        import aiohttp

        mock_ws = AsyncMock()
        mock_session = AsyncMock()

        mock_msg = MagicMock()
        mock_msg.type = aiohttp.WSMsgType.BINARY
        mock_msg.data = b"received binary"
        mock_ws.receive = AsyncMock(return_value=mock_msg)

        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)
        result = await adapter.recv()

        assert result is not None
        assert result.is_binary()

    async def test_recv_close_returns_none(self) -> None:
        """Test close message returns None."""
        import aiohttp

        mock_ws = AsyncMock()
        mock_session = AsyncMock()

        mock_msg = MagicMock()
        mock_msg.type = aiohttp.WSMsgType.CLOSE
        mock_ws.receive = AsyncMock(return_value=mock_msg)

        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)
        result = await adapter.recv()

        assert result is None

    async def test_recv_timeout_returns_none(self) -> None:
        """Test timeout returns None."""

        mock_ws = AsyncMock()
        mock_session = AsyncMock()
        mock_ws.receive = AsyncMock(side_effect=TimeoutError())

        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)
        result = await adapter.recv()

        assert result is None


class TestInsecureWebSocketAdapterClose:
    """Tests for InsecureWebSocketAdapter.close_connection() method."""

    async def test_close_connection(self) -> None:
        """Test closing both WebSocket and session."""
        mock_ws = AsyncMock()
        mock_session = AsyncMock()
        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)

        await adapter.close_connection()

        mock_ws.close.assert_called_once()
        mock_session.close.assert_called_once()

    async def test_close_handles_ws_exception(self) -> None:
        """Test handling exception during WebSocket close."""
        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock(side_effect=Exception("close failed"))
        mock_session = AsyncMock()
        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)

        await adapter.close_connection()

        mock_session.close.assert_called_once()

    async def test_close_handles_session_exception(self) -> None:
        """Test handling exception during session close."""
        mock_ws = AsyncMock()
        mock_session = AsyncMock()
        mock_session.close = AsyncMock(side_effect=Exception("session close failed"))
        adapter = InsecureWebSocketAdapter(mock_ws, mock_session)

        await adapter.close_connection()


# =============================================================================
# InsecureWebSocketTransport Tests
# =============================================================================


class TestInsecureWebSocketTransport:
    """Tests for InsecureWebSocketTransport class."""

    def test_support_ping(self) -> None:
        """Test transport supports ping frames."""
        transport = InsecureWebSocketTransport()
        assert transport.support_ping() is True


class TestInsecureWebSocketTransportConnect:
    """Tests for InsecureWebSocketTransport.connect() method."""

    async def test_connect_creates_ssl_context(self) -> None:
        """Test connect creates an insecure SSL context."""
        from datetime import timedelta

        from bigbrotr.utils.transport import InsecureWebSocketTransport

        transport = InsecureWebSocketTransport()

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_ws = AsyncMock()
            mock_session.ws_connect = AsyncMock(return_value=mock_ws)
            mock_session_class.return_value = mock_session

            mock_mode = MagicMock()

            await transport.connect("wss://test.com", mock_mode, timedelta(seconds=10))

            mock_session_class.assert_called_once()

    async def test_connect_client_error_raises_os_error(self) -> None:
        """Test client error raises OSError."""
        from datetime import timedelta

        import aiohttp

        from bigbrotr.utils.transport import InsecureWebSocketTransport

        transport = InsecureWebSocketTransport()

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session.ws_connect = AsyncMock(
                side_effect=aiohttp.ClientError("connection failed")
            )
            mock_session.close = AsyncMock()
            mock_session_class.return_value = mock_session

            mock_mode = MagicMock()

            with pytest.raises(OSError) as exc_info:
                await transport.connect("wss://test.com", mock_mode, timedelta(seconds=10))

            assert "Connection failed" in str(exc_info.value)

    async def test_connect_timeout_raises_os_error(self) -> None:
        """Test timeout raises OSError."""
        from datetime import timedelta

        from bigbrotr.utils.transport import InsecureWebSocketTransport

        transport = InsecureWebSocketTransport()

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session.ws_connect = AsyncMock(side_effect=TimeoutError())
            mock_session.close = AsyncMock()
            mock_session_class.return_value = mock_session

            mock_mode = MagicMock()

            with pytest.raises(OSError) as exc_info:
                await transport.connect("wss://test.com", mock_mode, timedelta(seconds=10))

            assert "timeout" in str(exc_info.value).lower()
