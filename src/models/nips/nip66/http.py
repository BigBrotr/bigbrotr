"""
NIP-66 HTTP metadata container with header extraction capabilities.

Captures ``Server`` and ``X-Powered-By`` HTTP headers from the WebSocket
upgrade handshake response. Supports both clearnet and overlay network
relays (overlay networks require a SOCKS5 proxy).
"""

from __future__ import annotations

import logging
import ssl
from types import SimpleNamespace
from typing import Any, Self

import aiohttp
from aiohttp_socks import ProxyConnector

from models.constants import NetworkType
from models.nips.base import DEFAULT_TIMEOUT, BaseMetadata
from models.relay import Relay

from .data import Nip66HttpData
from .logs import Nip66HttpLogs


logger = logging.getLogger("models.nip66")


class Nip66HttpMetadata(BaseMetadata):
    """Container for HTTP header data and extraction logs.

    Provides the ``http()`` class method that initiates a WebSocket
    connection and captures server identification headers from the
    upgrade response.
    """

    data: Nip66HttpData
    logs: Nip66HttpLogs

    # -------------------------------------------------------------------------
    # HTTP Header Extraction
    # -------------------------------------------------------------------------

    @staticmethod
    async def _http(
        relay: Relay,
        timeout: float,
        proxy_url: str | None = None,
    ) -> dict[str, Any]:
        """Capture Server and X-Powered-By headers from a WebSocket handshake.

        Uses aiohttp trace hooks to intercept response headers during the
        WebSocket connection upgrade.

        Args:
            relay: Relay to connect to.
            timeout: Connection timeout in seconds.
            proxy_url: Optional SOCKS5 proxy URL.

        Returns:
            Dictionary with ``http_server`` and/or ``http_powered_by``.
        """
        result: dict[str, Any] = {}
        captured_headers: dict[str, str] = {}

        async def on_request_end(
            _session: aiohttp.ClientSession,
            _ctx: SimpleNamespace,
            params: aiohttp.TraceRequestEndParams,
        ) -> None:
            if params.response and params.response.headers:
                captured_headers.update(dict(params.response.headers))

        trace_config = aiohttp.TraceConfig()
        trace_config.on_request_end.append(on_request_end)

        # Use a non-validating SSL context to connect regardless of cert status
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        connector: aiohttp.BaseConnector
        if proxy_url:
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
        """Extract HTTP headers from a relay's WebSocket handshake response.

        Args:
            relay: Relay to connect to.
            timeout: Connection timeout in seconds (default: 10.0).
            proxy_url: Optional SOCKS5 proxy URL (required for overlay networks).

        Returns:
            An ``Nip66HttpMetadata`` instance with header data and logs.

        Raises:
            ValueError: If an overlay network relay has no proxy configured.
        """
        timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        logger.debug("http_testing relay=%s timeout_s=%s proxy=%s", relay.url, timeout, proxy_url)

        overlay_networks = (NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI)
        if proxy_url is None and relay.network in overlay_networks:
            raise ValueError(f"overlay network {relay.network.value} requires proxy")

        logs: dict[str, Any] = {"success": False, "reason": None}
        data: dict[str, Any] = {}

        try:
            data = await cls._http(relay, timeout, proxy_url)
            if data:
                logs["success"] = True
                logger.debug(
                    "http_completed relay=%s server=%s", relay.url, data.get("http_server")
                )
            else:
                logs["reason"] = "no HTTP headers captured"
                logger.debug("http_no_data relay=%s", relay.url)
        except Exception as e:
            logs["reason"] = str(e)
            logger.debug("http_error relay=%s error=%s", relay.url, str(e))

        return cls(
            data=Nip66HttpData.model_validate(Nip66HttpData.parse(data)),
            logs=Nip66HttpLogs.model_validate(logs),
        )
