import ssl

from aiohttp import ClientSession, ClientWebSocketResponse, WSMsgType
from nostr_sdk import (
    ClientWSTimeout,
    CustomWebSocketTransport,
    WebSocketAdapter,
    WebSocketAdapterWrapper,
    WebSocketMessage,
)


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
    def support_ping(self) -> bool:
        return False

    async def connect(self, url, mode, timeout) -> WebSocketAdapterWrapper:
        try:
            session = ClientSession()
            ws = await session.ws_connect(
                url, timeout=ClientWSTimeout(total=timeout.total_seconds())
            )

            adaptor = Adapter(session, ws)
            wrapper = WebSocketAdapterWrapper(adaptor)

            return wrapper
        except Exception:
            await session.close()
            return await self._connect_insecure(url, mode, timeout)

    async def _connect_insecure(self, url, mode, timeout) -> WebSocketAdapterWrapper:
        """Establish a WebSocket connection with certificate checks disabled."""
        insecure_ctx = ssl.create_default_context()
        insecure_ctx.check_hostname = False
        insecure_ctx.verify_mode = ssl.CERT_NONE

        try:
            session = ClientSession()
            ws = await session.ws_connect(
                url,
                ssl=insecure_ctx,
                timeout=ClientWSTimeout(total=timeout.total_seconds()),
            )
            adaptor = Adapter(session, ws)
            wrapper = WebSocketAdapterWrapper(adaptor)
            return wrapper
        except Exception as e:
            await session.close()
            raise e
