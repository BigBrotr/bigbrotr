"""
NIP-66 HTTP metadata container with header extraction capabilities.

Captures ``Server`` and ``X-Powered-By`` HTTP headers from the WebSocket
upgrade handshake response as part of
[NIP-66](https://github.com/nostr-protocol/nips/blob/master/66.md)
monitoring. Supports both clearnet and overlay network relays (overlay
networks require a SOCKS5 proxy).

Note:
    Headers are captured using aiohttp's ``TraceConfig`` hooks during the
    WebSocket upgrade handshake, not from a separate HTTP request. This
    ensures the captured headers reflect the actual relay WebSocket endpoint
    rather than a potentially different HTTP endpoint.

    For clearnet relays, SSL verification is enabled by default. When
    ``allow_insecure=True``, a non-validating SSL context (``CERT_NONE``)
    is used instead. Overlay networks always use ``CERT_NONE`` because
    the proxy provides encryption. This is the only NIP-66 test that
    supports **both** clearnet and overlay networks.

See Also:
    [bigbrotr.nips.nip66.data.Nip66HttpData][bigbrotr.nips.nip66.data.Nip66HttpData]:
        Data model for HTTP header fields.
    [bigbrotr.nips.nip66.logs.Nip66HttpLogs][bigbrotr.nips.nip66.logs.Nip66HttpLogs]:
        Log model for HTTP extraction results.
    [bigbrotr.nips.nip11.info.Nip11InfoMetadata][bigbrotr.nips.nip11.info.Nip11InfoMetadata]:
        NIP-11 info retrieval that also makes HTTP requests to relays (but uses
        ``Accept: application/nostr+json`` for JSON document retrieval).
"""

from __future__ import annotations

import logging
import ssl
from types import SimpleNamespace  # noqa: TC003
from typing import Any, Self

import aiohttp
from aiohttp_socks import ProxyConnector

from bigbrotr.models.constants import DEFAULT_TIMEOUT, NetworkType
from bigbrotr.models.relay import Relay  # noqa: TC001
from bigbrotr.nips.base import BaseNipMetadata

from .data import Nip66HttpData
from .logs import Nip66HttpLogs


logger = logging.getLogger("bigbrotr.nips.nip66")


class Nip66HttpMetadata(BaseNipMetadata):
    """Container for HTTP header data and extraction logs.

    Provides the ``execute()`` class method that initiates a WebSocket
    connection and captures server identification headers from the
    upgrade response.

    See Also:
        [bigbrotr.nips.nip66.nip66.Nip66][bigbrotr.nips.nip66.nip66.Nip66]:
            Top-level model that orchestrates this alongside other tests.
        [bigbrotr.models.metadata.MetadataType][bigbrotr.models.metadata.MetadataType]:
            The ``NIP66_HTTP`` variant used when storing these results.
    """

    data: Nip66HttpData
    logs: Nip66HttpLogs

    # -------------------------------------------------------------------------
    # HTTP Header Extraction
    # -------------------------------------------------------------------------

    @staticmethod
    async def _http(
        relay: Relay,
        timeout: float,  # noqa: ASYNC109
        proxy_url: str | None = None,
        *,
        allow_insecure: bool = False,
    ) -> dict[str, Any]:
        """Capture Server and X-Powered-By headers from a WebSocket handshake.

        Uses aiohttp trace hooks to intercept response headers during the
        WebSocket connection upgrade.

        Args:
            relay: Relay to connect to.
            timeout: Connection timeout in seconds.
            proxy_url: Optional SOCKS5 proxy URL.
            allow_insecure: Use non-validating SSL context for clearnet relays.

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

        is_overlay = relay.network in (NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI)
        ssl_context = ssl.create_default_context()
        if is_overlay or allow_insecure:
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
    async def execute(
        cls,
        relay: Relay,
        timeout: float | None = None,  # noqa: ASYNC109
        proxy_url: str | None = None,
        *,
        allow_insecure: bool = False,
    ) -> Self:
        """Extract HTTP headers from a relay's WebSocket handshake response.

        Args:
            relay: Relay to connect to.
            timeout: Connection timeout in seconds (default: 10.0).
            proxy_url: Optional SOCKS5 proxy URL (required for overlay networks).
            allow_insecure: Use non-validating SSL for clearnet relays.

        Returns:
            An ``Nip66HttpMetadata`` instance with header data and logs.
        """
        timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        logger.debug("http_testing relay=%s timeout_s=%s proxy=%s", relay.url, timeout, proxy_url)

        overlay_networks = (NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI)
        if proxy_url is None and relay.network in overlay_networks:
            return cls(
                data=Nip66HttpData(),
                logs=Nip66HttpLogs(
                    success=False,
                    reason=f"overlay network {relay.network.value} requires proxy",
                ),
            )

        logs: dict[str, Any] = {"success": False, "reason": None}
        data: dict[str, Any] = {}

        try:
            data = await cls._http(relay, timeout, proxy_url, allow_insecure=allow_insecure)
            if data:
                logs["success"] = True
                logger.debug(
                    "http_completed relay=%s server=%s", relay.url, data.get("http_server")
                )
            else:
                logs["reason"] = "no HTTP headers captured"
                logger.debug("http_no_data relay=%s", relay.url)
        except (OSError, TimeoutError, aiohttp.ClientError) as e:
            logs["reason"] = str(e)
            logger.debug("http_error relay=%s error=%s", relay.url, str(e))

        return cls(
            data=Nip66HttpData.model_validate(Nip66HttpData.parse(data)),
            logs=Nip66HttpLogs.model_validate(logs),
        )
