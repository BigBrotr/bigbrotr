"""
NIP-11 types for BigBrotr.

Provides Nip11 class for relay information documents.
Nip11 is a factory that generates RelayMetadata objects.
"""

import json
from dataclasses import dataclass
from time import time
from typing import TYPE_CHECKING, Any, Optional, Type, TypeVar

import aiohttp
from aiohttp_socks import ProxyConnector

from .metadata import Metadata
from .relay import Relay

if TYPE_CHECKING:
    from .relay_metadata import RelayMetadata


T = TypeVar("T")


@dataclass(frozen=True)
class Nip11:
    """
    Immutable NIP-11 relay information document.

    Fetches and parses NIP-11 documents, providing type-safe property access
    and conversion to RelayMetadata for database storage.
    """

    relay: Relay
    metadata: Metadata
    generated_at: int

    # --- Type-safe helpers (delegated to Metadata) ---

    def _get(self, key: str, expected_type: Type[T], default: T) -> T:
        """Get value with type checking."""
        return self.metadata._get(key, expected_type, default)

    def _get_optional(self, key: str, expected_type: Type[T]) -> Optional[T]:
        """Get optional value with type checking."""
        return self.metadata._get_optional(key, expected_type)

    def _get_nested(self, outer: str, key: str, expected_type: Type[T], default: T) -> T:
        """Get nested value with type checking."""
        return self.metadata._get_nested(outer, key, expected_type, default)

    def _get_nested_optional(self, outer: str, key: str, expected_type: Type[T]) -> Optional[T]:
        """Get nested optional value with type checking."""
        return self.metadata._get_nested_optional(outer, key, expected_type)

    # --- Convenience properties ---

    @property
    def data(self) -> dict[str, Any]:
        """Raw metadata data."""
        return self.metadata.data

    # --- Base fields ---

    @property
    def name(self) -> Optional[str]:
        return self._get_optional("name", str)

    @property
    def description(self) -> Optional[str]:
        return self._get_optional("description", str)

    @property
    def banner(self) -> Optional[str]:
        return self._get_optional("banner", str)

    @property
    def icon(self) -> Optional[str]:
        return self._get_optional("icon", str)

    @property
    def pubkey(self) -> Optional[str]:
        return self._get_optional("pubkey", str)

    @property
    def self_pubkey(self) -> Optional[str]:
        return self._get_optional("self", str)

    @property
    def contact(self) -> Optional[str]:
        return self._get_optional("contact", str)

    @property
    def supported_nips(self) -> list[int]:
        return self._get("supported_nips", list, [])

    @property
    def software(self) -> Optional[str]:
        return self._get_optional("software", str)

    @property
    def version(self) -> Optional[str]:
        return self._get_optional("version", str)

    @property
    def privacy_policy(self) -> Optional[str]:
        return self._get_optional("privacy_policy", str)

    @property
    def terms_of_service(self) -> Optional[str]:
        return self._get_optional("terms_of_service", str)

    # --- Server limitations ---

    @property
    def limitation(self) -> dict[str, Any]:
        return self._get("limitation", dict, {})

    @property
    def max_message_length(self) -> Optional[int]:
        return self._get_nested_optional("limitation", "max_message_length", int)

    @property
    def max_subscriptions(self) -> Optional[int]:
        return self._get_nested_optional("limitation", "max_subscriptions", int)

    @property
    def max_limit(self) -> Optional[int]:
        return self._get_nested_optional("limitation", "max_limit", int)

    @property
    def max_subid_length(self) -> Optional[int]:
        return self._get_nested_optional("limitation", "max_subid_length", int)

    @property
    def max_event_tags(self) -> Optional[int]:
        return self._get_nested_optional("limitation", "max_event_tags", int)

    @property
    def max_content_length(self) -> Optional[int]:
        return self._get_nested_optional("limitation", "max_content_length", int)

    @property
    def min_pow_difficulty(self) -> Optional[int]:
        return self._get_nested_optional("limitation", "min_pow_difficulty", int)

    @property
    def auth_required(self) -> Optional[bool]:
        return self._get_nested_optional("limitation", "auth_required", bool)

    @property
    def payment_required(self) -> Optional[bool]:
        return self._get_nested_optional("limitation", "payment_required", bool)

    @property
    def restricted_writes(self) -> Optional[bool]:
        return self._get_nested_optional("limitation", "restricted_writes", bool)

    @property
    def created_at_lower_limit(self) -> Optional[int]:
        return self._get_nested_optional("limitation", "created_at_lower_limit", int)

    @property
    def created_at_upper_limit(self) -> Optional[int]:
        return self._get_nested_optional("limitation", "created_at_upper_limit", int)

    @property
    def default_limit(self) -> Optional[int]:
        return self._get_nested_optional("limitation", "default_limit", int)

    # --- Event retention ---

    @property
    def retention(self) -> list[dict[str, Any]]:
        return self._get("retention", list, [])

    # --- Content limitations ---

    @property
    def relay_countries(self) -> list[str]:
        return self._get("relay_countries", list, [])

    # --- Community preferences ---

    @property
    def language_tags(self) -> list[str]:
        return self._get("language_tags", list, [])

    @property
    def tags(self) -> list[str]:
        return self._get("tags", list, [])

    @property
    def posting_policy(self) -> Optional[str]:
        return self._get_optional("posting_policy", str)

    # --- Pay-to-relay ---

    @property
    def payments_url(self) -> Optional[str]:
        return self._get_optional("payments_url", str)

    @property
    def fees(self) -> dict[str, Any]:
        return self._get("fees", dict, {})

    @property
    def admission_fees(self) -> list[dict[str, Any]]:
        return self._get_nested("fees", "admission", list, [])

    @property
    def subscription_fees(self) -> list[dict[str, Any]]:
        return self._get_nested("fees", "subscription", list, [])

    @property
    def publication_fees(self) -> list[dict[str, Any]]:
        return self._get_nested("fees", "publication", list, [])

    # --- Factory method ---

    def to_relay_metadata(self) -> "RelayMetadata":
        """
        Convert to RelayMetadata for database storage.

        Returns:
            Single RelayMetadata with type='nip11'
        """
        from .relay_metadata import RelayMetadata

        return RelayMetadata(
            relay=self.relay,
            metadata=self.metadata,
            metadata_type="nip11",
            generated_at=self.generated_at,
        )

    # --- Fetch ---

    @classmethod
    async def fetch(
        cls,
        relay: Relay,
        timeout: float = 30.0,
        proxy_url: Optional[str] = None,
    ) -> Optional["Nip11"]:
        """
        Fetch NIP-11 document from relay.

        Args:
            relay: Relay object
            timeout: Request timeout in seconds
            proxy_url: Optional SOCKS5 proxy URL for Tor/I2P/Loki

        Returns:
            Nip11 instance if successful, None otherwise
        """
        protocol = "https" if relay.scheme == "wss" else "http"
        http_url = f"{protocol}://{relay._url_without_scheme}"

        headers = {"Accept": "application/nostr+json"}

        try:
            connector = None
            if relay.network != "clearnet" and proxy_url:
                connector = ProxyConnector.from_url(proxy_url)

            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(
                    http_url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    if resp.status != 200:
                        return None

                    # Validate Content-Type is JSON
                    content_type = resp.headers.get("Content-Type", "")
                    if "json" not in content_type.lower():
                        return None

                    # Safely parse JSON
                    try:
                        data = await resp.json()
                    except (aiohttp.ContentTypeError, json.JSONDecodeError):
                        return None

                    if not isinstance(data, dict):
                        return None

                    metadata = Metadata(data)
                    generated_at = int(time())

                    instance = object.__new__(cls)
                    object.__setattr__(instance, "relay", relay)
                    object.__setattr__(instance, "metadata", metadata)
                    object.__setattr__(instance, "generated_at", generated_at)
                    return instance

        except Exception:
            return None
