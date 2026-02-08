"""
NIP-11 metadata container with HTTP fetch capabilities.

Pairs ``Nip11FetchData`` with ``Nip11FetchLogs`` and provides the
``fetch()`` class method that performs the actual HTTP request to
retrieve a relay's NIP-11 information document.
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from http import HTTPStatus
from typing import Any, ClassVar, Self

import aiohttp
from aiohttp_socks import ProxyConnector

from models.constants import DEFAULT_TIMEOUT, NetworkType
from models.nips.base import BaseMetadata
from models.relay import Relay  # noqa: TC001

from .data import Nip11FetchData
from .logs import Nip11FetchLogs


logger = logging.getLogger("models.nip11")


class Nip11FetchMetadata(BaseMetadata):
    """Container for NIP-11 fetch data and operation logs.

    Provides the ``fetch()`` class method for retrieving a relay's NIP-11
    document over HTTP(S). The result always contains both a data object
    and a logs object -- check ``logs.success`` for the operation status.
    """

    data: Nip11FetchData
    logs: Nip11FetchLogs

    _FETCH_MAX_SIZE: ClassVar[int] = 65_536  # 64 KB

    # -------------------------------------------------------------------------
    # HTTP Fetch Implementation
    # -------------------------------------------------------------------------

    @staticmethod
    async def _fetch(  # noqa: PLR0913
        http_url: str,
        headers: dict[str, str],
        timeout: float,  # noqa: ASYNC109
        max_size: int,
        ssl_context: ssl.SSLContext | bool,
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

            body = await resp.content.read(max_size + 1)
            if len(body) > max_size:
                raise ValueError(f"Response too large: {len(body)} > {max_size}")

            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError(f"Expected dict, got {type(data).__name__}")

            return data

    @classmethod
    async def fetch(
        cls,
        relay: Relay,
        timeout: float | None = None,  # noqa: ASYNC109
        max_size: int | None = None,
        proxy_url: str | None = None,
        allow_insecure: bool = True,
    ) -> Self:
        """Fetch the NIP-11 information document from a relay.

        Connects via HTTP(S) with the ``Accept: application/nostr+json``
        header per the NIP-11 specification.

        SSL strategy:

        * **Clearnet HTTPS** -- Verify certificate first; on failure,
          fall back to insecure if *allow_insecure* is True.
        * **Overlay networks** -- Always use an insecure SSL context
          (the overlay provides encryption).
        * **HTTP** -- No SSL.

        This method never raises and never returns None. Check
        ``logs.success`` for the operation outcome.

        Args:
            relay: Relay to fetch from.
            timeout: Request timeout in seconds (default: 10.0).
            max_size: Maximum response size in bytes (default: 64 KB).
            proxy_url: Optional SOCKS5 proxy URL for overlay networks.
            allow_insecure: Fall back to unverified SSL on certificate
                errors (default: True).

        Returns:
            An ``Nip11FetchMetadata`` instance with data and logs.
        """
        timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        max_size = max_size if max_size is not None else cls._FETCH_MAX_SIZE

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
                data = await cls._fetch(http_url, headers, timeout, max_size, ctx, proxy_url)

            elif protocol == "http":
                data = await cls._fetch(http_url, headers, timeout, max_size, False, proxy_url)

            else:
                # HTTPS: try verified first, optionally fall back to insecure
                try:
                    data = await cls._fetch(http_url, headers, timeout, max_size, True, proxy_url)
                except aiohttp.ClientConnectorCertificateError:
                    if not allow_insecure:
                        raise
                    ssl_fallback = True
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    data = await cls._fetch(http_url, headers, timeout, max_size, ctx, proxy_url)

            logs["success"] = True

        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            logs["success"] = False
            logs["reason"] = str(e)

        result = cls(
            data=Nip11FetchData.model_validate(Nip11FetchData.parse(data)),
            logs=Nip11FetchLogs.model_validate(logs),
        )

        if logs["success"]:
            logger.debug(
                "nip11_fetched relay=%s name=%s ssl_fallback=%s",
                relay.url,
                result.data.name,
                ssl_fallback,
            )
        else:
            logger.debug("nip11_failed relay=%s error=%s", relay.url, logs["reason"])

        return result
