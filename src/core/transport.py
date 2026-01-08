from __future__ import annotations

import ssl
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from aiohttp import ClientSession, ClientWebSocketResponse, ClientWSTimeout, WSMsgType
from nostr_sdk import (
    Client,
    ClientBuilder,
    ClientOptions,
    Connection,
    ConnectionMode,
    ConnectionTarget,
    CustomWebSocketTransport,
    NostrSigner,
    RelayUrl,
    WebSocketAdapter,
    WebSocketAdapterWrapper,
    WebSocketMessage,
)


if TYPE_CHECKING:
    from models.keys import Keys
    from models.relay import Relay


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

    def __init__(self, proxy_url: str | None = None):
        """Initialize transport with optional proxy.

        Args:
            proxy_url: Optional SOCKS5 proxy URL (e.g., "socks5://127.0.0.1:9050")
        """
        self.proxy_url = proxy_url

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


async def create_client(
    relay: Relay,
    keys: Keys,
    proxy_url: str | None = None,
) -> Client:
    """Create a Nostr client configured for the given relay.

    For overlay networks (tor/i2p/loki):
        Uses standard nostr-sdk client with SOCKS5 proxy configuration.
        Requires proxy_url to be provided.

    For clearnet relays:
        Uses standard nostr-sdk client (no custom transport needed).

    Args:
        relay: The relay to connect to
        keys: Keys for signing events
        proxy_url: SOCKS5 proxy URL for overlay networks (e.g., "socks5://127.0.0.1:9050")

    Returns:
        Configured Client instance with relay added (but not connected)

    Raises:
        ValueError: If overlay network relay is provided without proxy_url
    """
    signer = NostrSigner.keys(keys._inner)
    relay_url = RelayUrl.parse(relay.url)

    if relay.network in ("tor", "i2p", "loki"):
        if proxy_url is None:
            raise ValueError(f"Overlay network relay ({relay.network}) requires proxy_url")

        parsed = urlparse(proxy_url)
        proxy_host = parsed.hostname or "127.0.0.1"
        proxy_port = parsed.port or 9050

        # Map network to connection target
        target_map = {
            "tor": ConnectionTarget.ONION,
            "i2p": ConnectionTarget.ONION,  # I2P uses same target
            "loki": ConnectionTarget.ONION,  # Loki uses same target
        }
        target = target_map.get(relay.network, ConnectionTarget.ONION)

        proxy_mode = ConnectionMode.PROXY(proxy_host, proxy_port)
        conn = Connection().mode(proxy_mode).target(target)
        opts = ClientOptions().connection(conn)
        client = ClientBuilder().signer(signer).opts(opts).build()
    else:
        # Clearnet: use standard nostr-sdk client
        client = ClientBuilder().signer(signer).build()

    await client.add_relay(relay_url)
    return client
