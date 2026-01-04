"""
NIP-11 Relay Information Document model for BigBrotr.

Provides the Nip11 class for fetching and parsing relay information documents
per NIP-11 specification. Includes type-safe property access for all standard
NIP-11 fields and conversion to RelayMetadata for database storage.

See: https://github.com/nostr-protocol/nips/blob/master/11.md

Example:
    >>> nip11 = await Nip11.fetch(relay)
    >>> if nip11:
    ...     print(f"Relay: {nip11.name}, NIPs: {nip11.supported_nips}")

    >>> # For debugging, use fetch_or_raise to get error details
    >>> try:
    ...     nip11 = await Nip11.fetch_or_raise(relay)
    ... except Nip11FetchError as e:
    ...     print(f"Failed: {e.cause}")
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from time import time
from typing import TYPE_CHECKING, Any, ClassVar

import aiohttp
from aiohttp_socks import ProxyConnector

from .metadata import Metadata


if TYPE_CHECKING:
    from .relay import Relay
    from .relay_metadata import RelayMetadata


class Nip11FetchError(Exception):
    """Error fetching NIP-11 document from relay."""

    def __init__(self, relay: Relay, cause: Exception) -> None:
        self.relay = relay
        self.cause = cause
        super().__init__(f"Failed to fetch NIP-11 from {relay.url}: {cause}")


@dataclass(frozen=True, slots=True)
class Nip11:
    """
    Immutable NIP-11 relay information document.

    Fetches and parses NIP-11 documents via HTTP with the Accept: application/nostr+json
    header. Provides type-safe property access for all standard NIP-11 fields and
    conversion to RelayMetadata for content-addressed database storage.

    Attributes:
        relay: The Relay this information document belongs to.
        metadata: Parsed JSON data wrapped in a Metadata object.
        generated_at: Unix timestamp when the document was fetched.

    NIP-11 Fields (accessible as properties):
        - name, description, banner, icon: Relay display information
        - pubkey, contact: Operator contact information
        - supported_nips: List of supported NIP numbers
        - software, version: Relay software identification
        - limitation_*: Rate limits and restrictions (auth_required, payment_required, etc.)
        - retention: Data retention policies
        - relay_countries: Countries where relay operates
        - language_tags: Supported content languages
        - fees_*: Payment requirements for various operations

    Example:
        >>> nip11 = await Nip11.fetch(relay)
        >>> if nip11:
        ...     print(f"Name: {nip11.name}")
        ...     print(f"Supported NIPs: {nip11.supported_nips}")
        ...     if nip11.limitation_auth_required:
        ...         print("Authentication required")
    """

    relay: Relay
    metadata: Metadata
    generated_at: int

    # --- Class-level defaults for fetch() ---
    _FETCH_TIMEOUT: ClassVar[float] = 10.0
    _FETCH_MAX_SIZE: ClassVar[int] = 65536  # 64 KB

    # --- Convenience properties ---

    @property
    def data(self) -> dict[str, Any]:
        """Raw metadata data."""
        return self.metadata.data

    # --- Base fields ---

    @property
    def name(self) -> str | None:
        return self.metadata._get("name", expected_type=str)

    @property
    def description(self) -> str | None:
        return self.metadata._get("description", expected_type=str)

    @property
    def banner(self) -> str | None:
        return self.metadata._get("banner", expected_type=str)

    @property
    def icon(self) -> str | None:
        return self.metadata._get("icon", expected_type=str)

    @property
    def pubkey(self) -> str | None:
        return self.metadata._get("pubkey", expected_type=str)

    @property
    def self_pubkey(self) -> str | None:
        return self.metadata._get("self", expected_type=str)

    @property
    def contact(self) -> str | None:
        return self.metadata._get("contact", expected_type=str)

    @property
    def supported_nips(self) -> list[int]:
        return self.metadata._get("supported_nips", expected_type=list, default=[])

    @property
    def software(self) -> str | None:
        return self.metadata._get("software", expected_type=str)

    @property
    def version(self) -> str | None:
        return self.metadata._get("version", expected_type=str)

    @property
    def privacy_policy(self) -> str | None:
        return self.metadata._get("privacy_policy", expected_type=str)

    @property
    def terms_of_service(self) -> str | None:
        return self.metadata._get("terms_of_service", expected_type=str)

    # --- Server limitations ---

    @property
    def limitation(self) -> dict[str, Any]:
        return self.metadata._get("limitation", expected_type=dict, default={})

    @property
    def max_message_length(self) -> int | None:
        return self.metadata._get("limitation", "max_message_length", expected_type=int)

    @property
    def max_subscriptions(self) -> int | None:
        return self.metadata._get("limitation", "max_subscriptions", expected_type=int)

    @property
    def max_limit(self) -> int | None:
        return self.metadata._get("limitation", "max_limit", expected_type=int)

    @property
    def max_subid_length(self) -> int | None:
        return self.metadata._get("limitation", "max_subid_length", expected_type=int)

    @property
    def max_event_tags(self) -> int | None:
        return self.metadata._get("limitation", "max_event_tags", expected_type=int)

    @property
    def max_content_length(self) -> int | None:
        return self.metadata._get("limitation", "max_content_length", expected_type=int)

    @property
    def min_pow_difficulty(self) -> int | None:
        return self.metadata._get("limitation", "min_pow_difficulty", expected_type=int)

    @property
    def auth_required(self) -> bool | None:
        return self.metadata._get("limitation", "auth_required", expected_type=bool)

    @property
    def payment_required(self) -> bool | None:
        return self.metadata._get("limitation", "payment_required", expected_type=bool)

    @property
    def restricted_writes(self) -> bool | None:
        return self.metadata._get("limitation", "restricted_writes", expected_type=bool)

    @property
    def created_at_lower_limit(self) -> int | None:
        return self.metadata._get("limitation", "created_at_lower_limit", expected_type=int)

    @property
    def created_at_upper_limit(self) -> int | None:
        return self.metadata._get("limitation", "created_at_upper_limit", expected_type=int)

    @property
    def default_limit(self) -> int | None:
        return self.metadata._get("limitation", "default_limit", expected_type=int)

    # --- Event retention ---

    @property
    def retention(self) -> list[dict[str, Any]]:
        return self.metadata._get("retention", expected_type=list, default=[])

    # --- Content limitations ---

    @property
    def relay_countries(self) -> list[str]:
        return self.metadata._get("relay_countries", expected_type=list, default=[])

    # --- Community preferences ---

    @property
    def language_tags(self) -> list[str]:
        return self.metadata._get("language_tags", expected_type=list, default=[])

    @property
    def tags(self) -> list[str]:
        return self.metadata._get("tags", expected_type=list, default=[])

    @property
    def posting_policy(self) -> str | None:
        return self.metadata._get("posting_policy", expected_type=str)

    # --- Pay-to-relay ---

    @property
    def payments_url(self) -> str | None:
        return self.metadata._get("payments_url", expected_type=str)

    @property
    def fees(self) -> dict[str, Any]:
        return self.metadata._get("fees", expected_type=dict, default={})

    @property
    def admission_fees(self) -> list[dict[str, Any]]:
        return self.metadata._get("fees", "admission", expected_type=list, default=[])

    @property
    def subscription_fees(self) -> list[dict[str, Any]]:
        return self.metadata._get("fees", "subscription", expected_type=list, default=[])

    @property
    def publication_fees(self) -> list[dict[str, Any]]:
        return self.metadata._get("fees", "publication", expected_type=list, default=[])

    # --- Factory method ---

    def to_relay_metadata(self) -> RelayMetadata:
        """
        Convert to RelayMetadata for database storage.

        Returns:
            Single RelayMetadata with type='nip11'
        """
        from .relay_metadata import MetadataType, RelayMetadata

        return RelayMetadata(
            relay=self.relay,
            metadata=self.metadata,
            metadata_type=MetadataType.NIP11,
            generated_at=self.generated_at,
        )

    # --- Fetch ---

    @classmethod
    async def _fetch(
        cls,
        relay: Relay,
        timeout: float | None = None,
        max_size: int | None = None,
        proxy_url: str | None = None,
    ) -> Metadata:
        """
        Internal fetch that raises exceptions on failure.

        Args:
            relay: "Relay" object
            timeout: Request timeout in seconds (default: _FETCH_TIMEOUT)
            max_size: Maximum response size in bytes (default: _FETCH_MAX_SIZE)
            proxy_url: Optional SOCKS5 proxy URL

        Returns:
            Metadata instance with parsed NIP-11 data

        Raises:
            aiohttp.ClientError: Connection or HTTP errors
            asyncio.TimeoutError: Request timeout
            ValueError: Invalid response (status, content-type, size, JSON)
        """
        timeout = timeout if timeout is not None else cls._FETCH_TIMEOUT
        max_size = max_size if max_size is not None else cls._FETCH_MAX_SIZE

        protocol = "https" if relay.scheme == "wss" else "http"
        http_url = f"{protocol}://{relay.url_without_scheme}"

        headers = {"Accept": "application/nostr+json"}
        connector = ProxyConnector.from_url(proxy_url) if proxy_url else None

        async with (
            aiohttp.ClientSession(connector=connector) as session,
            session.get(
                http_url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp,
        ):
            if resp.status != 200:
                raise ValueError(f"HTTP {resp.status}")

            # Validate Content-Type per NIP-11
            content_type = resp.headers.get("Content-Type", "")
            content_type_lower = content_type.lower().split(";")[0].strip()
            valid_types = ("application/nostr+json", "application/json")
            if content_type_lower not in valid_types:
                raise ValueError(f"Invalid Content-Type: {content_type}")

            # Read response with size limit
            body = await resp.content.read(max_size + 1)
            if len(body) > max_size:
                raise ValueError(f"Response too large: {len(body)} > {max_size}")

            # Parse JSON
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError(f"Expected dict, got {type(data).__name__}")

            return Metadata(data)

    @classmethod
    async def fetch(
        cls,
        relay: Relay,
        timeout: float | None = None,
        max_size: int | None = None,
        proxy_url: str | None = None,
    ) -> Nip11 | None:
        """
        Fetch NIP-11 document from relay, returning None on failure.

        Use fetch_or_raise() if you need error details for debugging.

        Args:
            relay: "Relay" object
            timeout: Request timeout in seconds (default: _FETCH_TIMEOUT)
            max_size: Maximum response size in bytes (default: _FETCH_MAX_SIZE)
            proxy_url: Optional SOCKS5 proxy URL for Tor/I2P/Loki

        Returns:
            Nip11 instance if successful, None otherwise
        """
        try:
            return await cls.fetch_or_raise(relay, timeout, max_size, proxy_url)
        except Nip11FetchError:
            return None

    @classmethod
    async def fetch_or_raise(
        cls,
        relay: Relay,
        timeout: float | None = None,
        max_size: int | None = None,
        proxy_url: str | None = None,
    ) -> Nip11:
        """
        Fetch NIP-11 document from relay, raising Nip11FetchError on failure.

        Use this method when you need error details for debugging or logging.
        For simple "fetch or skip" patterns, use fetch() instead.

        Args:
            relay: "Relay" object
            timeout: Request timeout in seconds (default: _FETCH_TIMEOUT)
            max_size: Maximum response size in bytes (default: _FETCH_MAX_SIZE)
            proxy_url: Optional SOCKS5 proxy URL for Tor/I2P/Loki

        Returns:
            Nip11 instance

        Raises:
            Nip11FetchError: If fetch fails (wraps the original exception)
        """
        try:
            metadata = await cls._fetch(relay, timeout, max_size, proxy_url)
            return cls(
                relay=relay,
                metadata=metadata,
                generated_at=int(time()),
            )
        except asyncio.CancelledError:
            raise  # Never swallow cancellation
        except Exception as e:
            raise Nip11FetchError(relay, e) from e
