"""NIP-11 metadata container with HTTP operations."""

from __future__ import annotations

import asyncio
import json
import ssl
from http import HTTPStatus
from typing import Any, ClassVar, Self

import aiohttp
from aiohttp_socks import ProxyConnector

from utils.network import NetworkType
from logger import Logger
from models.nips.base import DEFAULT_TIMEOUT, BaseMetadata
from models.relay import Relay

from .data import Nip11FetchData
from .logs import Nip11FetchLogs


logger = Logger("models.nip11")


class Nip11FetchMetadata(BaseMetadata):
    """Container for NIP-11 data and fetch logs with HTTP fetch capabilities."""

    data: Nip11FetchData
    logs: Nip11FetchLogs

    # Fetch defaults
    _FETCH_MAX_SIZE: ClassVar[int] = 65536  # 64 KB

    # -------------------------------------------------------------------------
    # Fetch - HTTP Operations
    # -------------------------------------------------------------------------

    @staticmethod
    async def _fetch(
        http_url: str,
        headers: dict[str, str],
        timeout: float,
        max_size: int,
        ssl_context: ssl.SSLContext | bool,
        proxy_url: str | None = None,
    ) -> dict[str, Any]:
        """Execute HTTP fetch with given SSL context.

        Returns raw dict from relay.
        Raises on failure (caught by caller).
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

            # Validate Content-Type per NIP-11
            content_type = resp.headers.get("Content-Type", "")
            content_type_lower = content_type.lower().split(";")[0].strip()
            if content_type_lower not in ("application/nostr+json", "application/json"):
                raise ValueError(f"Invalid Content-Type: {content_type}")

            # Read with size limit
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
        timeout: float | None = None,
        max_size: int | None = None,
        proxy_url: str | None = None,
        allow_insecure: bool = True,
    ) -> Self:
        """
        Fetch NIP-11 document and return metadata.

        Connects via HTTP(S) with Accept: application/nostr+json header,
        validates the response, and parses into Nip11FetchMetadata.

        Always returns Nip11FetchMetadata - never raises, never None.
        Check .logs.success for fetch status.

        SSL handling:
            - Clearnet HTTPS: Verify first, fallback if allow_insecure=True
            - Overlay (Tor/I2P/Loki): Always insecure (encryption via overlay)
            - HTTP: No SSL

        Args:
            relay: Relay to fetch from
            timeout: Request timeout in seconds (default: 10.0)
            max_size: Max response size in bytes (default: 64KB)
            proxy_url: Optional SOCKS5 proxy URL
            allow_insecure: Fallback to insecure on cert errors (default: True)

        Returns:
            Nip11FetchMetadata - check .logs.success for status

        Example::

            metadata = await Nip11FetchMetadata.fetch(relay)
            if metadata.logs.success:
                print(f"Name: {metadata.data.name}")
            else:
                print(f"Failed: {metadata.logs.reason}")
        """
        timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        max_size = max_size if max_size is not None else cls._FETCH_MAX_SIZE

        # Build HTTP URL
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
                "nip11_fetched", relay=relay.url, name=result.data.name, ssl_fallback=ssl_fallback
            )
        else:
            logger.debug("nip11_failed", relay=relay.url, error=logs["reason"])

        return result
