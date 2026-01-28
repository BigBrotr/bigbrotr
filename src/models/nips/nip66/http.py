"""NIP-66 HTTP metadata container with check capabilities."""

from __future__ import annotations

import ssl
from typing import Any, ClassVar, Self

from core.logger import Logger
from models.nips.base import DEFAULT_TIMEOUT, BaseMetadata
from models.relay import NetworkType, Relay

from .data import Nip66HttpData
from .logs import Nip66HttpLogs


logger = Logger("models.nip66")


class Nip66HttpMetadata(BaseMetadata):
    """Container for HTTP data and logs with check capabilities."""

    data: Nip66HttpData
    logs: Nip66HttpLogs

    # -------------------------------------------------------------------------
    # HTTP Check
    # -------------------------------------------------------------------------

    @staticmethod
    async def _http(
        relay: Relay,
        timeout: float,
        proxy_url: str | None = None,
    ) -> dict[str, Any]:
        """Capture Server and X-Powered-By headers from WebSocket handshake."""
        import aiohttp

        result: dict[str, Any] = {}
        captured_headers: dict[str, str] = {}

        async def on_request_end(
            _session: aiohttp.ClientSession,
            _ctx: aiohttp.tracing.SimpleNamespace,
            params: aiohttp.TraceRequestEndParams,
        ) -> None:
            if params.response and params.response.headers:
                captured_headers.update(dict(params.response.headers))

        trace_config = aiohttp.TraceConfig()
        trace_config.on_request_end.append(on_request_end)

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        connector: aiohttp.BaseConnector
        if proxy_url:
            from aiohttp_socks import ProxyConnector

            connector = ProxyConnector.from_url(proxy_url, ssl=ssl_context)
        else:
            connector = aiohttp.TCPConnector(ssl=ssl_context)

        client_timeout = aiohttp.ClientTimeout(total=timeout)

        async with (
            aiohttp.ClientSession(
                connector=connector,
                timeout=client_timeout,
                trace_configs=[trace_config],
            ) as session,
            session.ws_connect(relay.url) as ws,
        ):
            await ws.close()

        server = captured_headers.get("Server")
        if server:
            result["http_server"] = server

        powered_by = captured_headers.get("X-Powered-By")
        if powered_by:
            result["http_powered_by"] = powered_by

        return result

    @classmethod
    async def http(
        cls,
        relay: Relay,
        timeout: float | None = None,
        proxy_url: str | None = None,
    ) -> Self:
        """Extract HTTP headers from WebSocket handshake.

        Raises:
            ValueError: If overlay network without proxy.
        """
        timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        logger.debug("http_testing", relay=relay.url, timeout_s=timeout, proxy=proxy_url)

        # Overlay networks require proxy
        overlay_networks = (NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI)
        if proxy_url is None and relay.network in overlay_networks:
            raise ValueError(f"overlay network {relay.network.value} requires proxy")

        logs: dict[str, Any] = {"success": False, "reason": None}
        data: dict[str, Any] = {}

        try:
            data = await cls._http(relay, timeout, proxy_url)
            if data:
                logs["success"] = True
                logger.debug("http_completed", relay=relay.url, server=data.get("http_server"))
            else:
                logs["reason"] = "no HTTP headers captured"
                logger.debug("http_no_data", relay=relay.url)
        except Exception as e:
            logs["reason"] = str(e)
            logger.debug("http_error", relay=relay.url, error=str(e))

        return cls(
            data=Nip66HttpData.model_validate(Nip66HttpData.parse(data)),
            logs=Nip66HttpLogs.model_validate(logs),
        )
