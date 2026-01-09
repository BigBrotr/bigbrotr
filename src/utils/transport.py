from __future__ import annotations

import ssl
from typing import TYPE_CHECKING

from aiohttp import ClientSession, ClientWebSocketResponse, ClientWSTimeout, WSMsgType
from nostr_sdk import (
    Client,
    ClientBuilder,
    CustomWebSocketTransport,
    NostrSigner,
    WebSocketAdapter,
    WebSocketAdapterWrapper,
    WebSocketMessage,
)


if TYPE_CHECKING:
    from nostr_sdk import Keys


class Adapter(WebSocketAdapter):
    def __init__(self, session: ClientSession, ws: ClientWebSocketResponse):
        self.session = session
        self.websocket = ws

    async def send(self, msg: WebSocketMessage):
        try:
            if msg.is_text():
                await self.websocket.send_str(msg[0])
            elif msg.is_binary():
                await self.websocket.send_bytes(msg[0])
        except Exception as e:
            # Handle clean closure gracefully
            raise e

    async def recv(self) -> WebSocketMessage | None:
        try:
            # Receive message
            raw_msg = await self.websocket.receive()

            if raw_msg.type == WSMsgType.TEXT:
                return WebSocketMessage.TEXT(raw_msg.data)
            elif raw_msg.type == WSMsgType.BINARY:
                return WebSocketMessage.BINARY(raw_msg.data)
            elif raw_msg.type == WSMsgType.PING:
                return WebSocketMessage.PING(raw_msg.data)
            elif raw_msg.type == WSMsgType.PONG:
                return WebSocketMessage.PONG(raw_msg.data)
            else:
                raise ValueError("unknown message type")
        except Exception as e:
            raise e

    async def close_connection(self):
        await self.websocket.close()
        await self.session.close()


class WebSocketClient(CustomWebSocketTransport):
    """Custom WebSocket transport with optional SOCKS5 proxy support."""

    def __init__(self, proxy_url: str | None = None, verify_ssl: bool = False):
        """Initialize transport with optional proxy.

        Args:
            proxy_url: Optional SOCKS5 proxy URL (e.g., "socks5://127.0.0.1:9050")
            verify_ssl: If True, enforce SSL certificate verification.
                If False (default), retry with SSL verification disabled on errors.
        """
        self.proxy_url = proxy_url
        self.verify_ssl = verify_ssl

    def support_ping(self) -> bool:
        return False

    async def connect(self, url, mode, timeout) -> WebSocketAdapterWrapper:
        try:
            session = await self._create_session()
            ws = await session.ws_connect(
                url, timeout=ClientWSTimeout(ws_close=timeout.total_seconds())
            )

            adaptor = Adapter(session, ws)
            wrapper = WebSocketAdapterWrapper(adaptor)

            return wrapper
        except Exception:
            await session.close()
            if self.verify_ssl:
                raise
            return await self._connect_insecure(url, mode, timeout)

    async def _create_session(self, ssl_context: ssl.SSLContext | None = None) -> ClientSession:
        """Create aiohttp session, with proxy connector if configured."""
        if self.proxy_url:
            from aiohttp_socks import ProxyConnector  # noqa: PLC0415

            connector = ProxyConnector.from_url(self.proxy_url, ssl=ssl_context)
            return ClientSession(connector=connector)
        return ClientSession()

    async def _connect_insecure(self, url, mode, timeout) -> WebSocketAdapterWrapper:
        """Establish a WebSocket connection with certificate checks disabled."""
        insecure_ctx = ssl.create_default_context()
        insecure_ctx.check_hostname = False
        insecure_ctx.verify_mode = ssl.CERT_NONE

        try:
            session = await self._create_session(ssl_context=insecure_ctx)
            ws = await session.ws_connect(
                url,
                ssl=insecure_ctx,
                timeout=ClientWSTimeout(ws_close=timeout.total_seconds()),
            )
            adaptor = Adapter(session, ws)
            wrapper = WebSocketAdapterWrapper(adaptor)
            return wrapper
        except Exception as e:
            await session.close()
            raise e


def create_client(
    keys: Keys | None = None,
    proxy_url: str | None = None,
    verify_ssl: bool = False,
) -> Client:
    """Create a Nostr client.

    Args:
        keys: Optional keys for signing events. If None, client will be read-only.
        proxy_url: Optional SOCKS5 proxy URL (e.g., "socks5://127.0.0.1:9050")
        verify_ssl: If True, enforce SSL certificate verification.
            If False (default), retry with SSL verification disabled on errors.

    Returns:
        Configured Client instance (no relays added)
    """
    builder = ClientBuilder()

    if keys is not None:
        signer = NostrSigner.keys(keys)
        builder = builder.signer(signer)

    transport = WebSocketClient(proxy_url=proxy_url, verify_ssl=verify_ssl)
    builder = builder.custom_websocket_transport(transport)

    return builder.build()
