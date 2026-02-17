"""
NIP-11 metadata container with HTTP info retrieval capabilities.

Pairs [Nip11InfoData][bigbrotr.nips.nip11.data.Nip11InfoData] with
[Nip11InfoLogs][bigbrotr.nips.nip11.logs.Nip11InfoLogs] and provides
the ``execute()`` class method that performs the actual HTTP request to
retrieve a relay's
[NIP-11](https://github.com/nostr-protocol/nips/blob/master/11.md)
information document.

Note:
    The HTTP request converts the relay's WebSocket URL scheme (``wss`` -> ``https``,
    ``ws`` -> ``http``) and sends the ``Accept: application/nostr+json`` header
    as required by the NIP-11 specification. Responses larger than 64 KB are
    rejected to guard against resource exhaustion.

    The SSL fallback strategy mirrors
    [connect_relay][bigbrotr.utils.transport.connect_relay]: clearnet relays
    try verified SSL first, then fall back to ``CERT_NONE`` if
    ``allow_insecure=True``. Overlay networks always use an insecure SSL
    context because the overlay provides its own encryption layer.

See Also:
    [bigbrotr.nips.nip11.nip11.Nip11][bigbrotr.nips.nip11.nip11.Nip11]:
        Top-level model that wraps this container.
    [bigbrotr.nips.base.BaseNipMetadata][bigbrotr.nips.base.BaseNipMetadata]:
        Base class providing ``from_dict()`` / ``to_dict()`` interface.
    [bigbrotr.models.metadata.MetadataType][bigbrotr.models.metadata.MetadataType]:
        The ``NIP11_INFO`` variant used when storing these results.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
from http import HTTPStatus
from typing import Any, ClassVar, Self

import aiohttp
from aiohttp_socks import ProxyConnector

from bigbrotr.models.constants import NetworkType
from bigbrotr.models.relay import Relay  # noqa: TC001
from bigbrotr.nips.base import BaseNipMetadata
from bigbrotr.utils.http import read_bounded_json
from bigbrotr.utils.transport import DEFAULT_TIMEOUT

from .data import Nip11InfoData
from .logs import Nip11InfoLogs


logger = logging.getLogger("bigbrotr.nips.nip11")


class Nip11InfoMetadata(BaseNipMetadata):
    """Container for NIP-11 info data and operation logs.

    Provides the ``execute()`` class method for retrieving a relay's NIP-11
    document over HTTP(S). The result always contains both a
    [Nip11InfoData][bigbrotr.nips.nip11.data.Nip11InfoData] object and a
    [Nip11InfoLogs][bigbrotr.nips.nip11.logs.Nip11InfoLogs] object --
    check ``logs.success`` for the operation status.

    Warning:
        The ``execute()`` method **never raises exceptions**. All errors are
        captured in the ``logs.reason`` field. Callers must always check
        ``logs.success`` before accessing data fields.

    See Also:
        [bigbrotr.nips.nip11.nip11.Nip11.create][bigbrotr.nips.nip11.nip11.Nip11.create]:
            Factory method that delegates to ``execute()``.
    """

    data: Nip11InfoData
    logs: Nip11InfoLogs

    _INFO_MAX_SIZE: ClassVar[int] = 65_536  # 64 KB

    # -------------------------------------------------------------------------
    # HTTP Info Retrieval
    # -------------------------------------------------------------------------

    @staticmethod
    async def _info(  # noqa: PLR0913
        http_url: str,
        headers: dict[str, str],
        timeout: float,  # noqa: ASYNC109
        max_size: int,
        ssl_context: ssl.SSLContext | bool,  # noqa: FBT001
        proxy_url: str | None = None,
    ) -> dict[str, Any]:
        """Execute a single HTTP GET request and return the parsed JSON body.

        Args:
            http_url: Full HTTP(S) URL to fetch.
            headers: HTTP request headers.
            timeout: Request timeout in seconds.
            max_size: Maximum allowed response body size in bytes.
            ssl_context: SSL context or boolean for TLS configuration.
            proxy_url: Optional SOCKS5 proxy URL.

        Returns:
            Parsed JSON dictionary from the relay response.

        Raises:
            ValueError: If the response status is not 200, the Content-Type
                is invalid, the body exceeds *max_size*, or the body is not
                a JSON object.
        """
        connector: aiohttp.BaseConnector
        if proxy_url:
            connector = ProxyConnector.from_url(proxy_url, ssl=ssl_context)
        else:
            connector = aiohttp.TCPConnector(ssl=ssl_context)

        async with (
            aiohttp.ClientSession(connector=connector) as session,
            session.get(
                http_url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp,
        ):
            if resp.status != HTTPStatus.OK:
                raise ValueError(f"HTTP {resp.status}")

            # NIP-11 requires application/nostr+json or application/json
            content_type = resp.headers.get("Content-Type", "")
            content_type_lower = content_type.lower().split(";")[0].strip()
            if content_type_lower not in ("application/nostr+json", "application/json"):
                raise ValueError(f"Invalid Content-Type: {content_type}")

            data = await read_bounded_json(resp, max_size)
            if not isinstance(data, dict):
                raise ValueError(f"Expected dict, got {type(data).__name__}")

            return data

    @classmethod
    async def execute(
        cls,
        relay: Relay,
        timeout: float | None = None,  # noqa: ASYNC109
        max_size: int | None = None,
        proxy_url: str | None = None,
        *,
        allow_insecure: bool = False,
    ) -> Self:
        """Fetch the NIP-11 information document from a relay.

        Connects via HTTP(S) with the ``Accept: application/nostr+json``
        header per the NIP-11 specification.

        For clearnet HTTPS, verifies the certificate first and falls back to
        insecure if *allow_insecure* is True. Overlay networks always use an
        insecure SSL context (the overlay provides encryption). Plain HTTP
        connections use no SSL.

        This method never raises and never returns None. Check
        ``logs.success`` for the operation outcome.

        Args:
            relay: Relay to fetch from.
            timeout: Request timeout in seconds (default: 10.0).
            max_size: Maximum response size in bytes (default: 64 KB).
            proxy_url: Optional SOCKS5 proxy URL for overlay networks.
            allow_insecure: Fall back to unverified SSL on certificate
                errors (default: False).

        Returns:
            An ``Nip11InfoMetadata`` instance with data and logs.
        """
        timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        max_size = max_size if max_size is not None else cls._INFO_MAX_SIZE

        # Build the HTTP URL from the relay's WebSocket URL components
        protocol = "https" if relay.scheme == "wss" else "http"
        formatted_host = f"[{relay.host}]" if ":" in relay.host else relay.host
        default_port = 443 if protocol == "https" else 80
        port_suffix = f":{relay.port}" if relay.port and relay.port != default_port else ""
        http_url = f"{protocol}://{formatted_host}{port_suffix}{relay.path or ''}"

        headers = {"Accept": "application/nostr+json"}
        is_overlay = relay.network in (NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI)

        data: dict[str, Any] = {}
        logs: dict[str, Any] = {"success": False, "reason": None}
        ssl_fallback = False

        try:
            if is_overlay:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                data = await cls._info(http_url, headers, timeout, max_size, ctx, proxy_url)

            elif protocol == "http":
                data = await cls._info(
                    http_url,
                    headers,
                    timeout,
                    max_size,
                    ssl_context=False,
                    proxy_url=proxy_url,
                )

            else:
                # HTTPS: try verified first, optionally fall back to insecure
                try:
                    data = await cls._info(
                        http_url,
                        headers,
                        timeout,
                        max_size,
                        ssl_context=True,
                        proxy_url=proxy_url,
                    )
                except aiohttp.ClientConnectorCertificateError:
                    if not allow_insecure:
                        raise
                    ssl_fallback = True
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    data = await cls._info(http_url, headers, timeout, max_size, ctx, proxy_url)

            logs["success"] = True

        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except (OSError, TimeoutError, aiohttp.ClientError, ValueError) as e:
            logs["success"] = False
            logs["reason"] = str(e) or type(e).__name__

        result = cls(
            data=Nip11InfoData.model_validate(Nip11InfoData.parse(data)),
            logs=Nip11InfoLogs.model_validate(logs),
        )

        if logs["success"]:
            logger.debug(
                "nip11_info_succeeded relay=%s name=%s ssl_fallback=%s",
                relay.url,
                result.data.name,
                ssl_fallback,
            )
        else:
            logger.debug("nip11_failed relay=%s error=%s", relay.url, logs["reason"])

        return result
