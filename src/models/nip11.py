"""
NIP-11 Relay Information Document.

This module provides the Nip11 class for fetching and parsing relay information
documents per NIP-11 specification. Raw JSON is validated and parsed into a
clean structure containing only valid NIP-11 fields.

See: https://github.com/nostr-protocol/nips/blob/master/11.md

Complete NIP-11 metadata structure::

    {
        # Base fields (all optional strings)
        "name": "JellyFish",
        "description": "Stay Immortal!",
        "banner": "https://example.com/banner.jpg",
        "icon": "https://example.com/icon.jpg",
        "pubkey": "bf2bee5281149c7c350f5d12ae32f514c7864ff10805182f4178538c2c421007",  # pragma: allowlist secret
        "self": "aa2bee5281149c7c350f5d12ae32f514c7864ff10805182f4178538c2c421008",  # pragma: allowlist secret
        "contact": "mailto:admin@example.com",
        "software": "https://github.com/example/relay",
        "version": "1.0.0",
        "privacy_policy": "https://example.com/privacy.txt",
        "terms_of_service": "https://example.com/tos.txt",
        "posting_policy": "https://example.com/posting-policy.html",
        "payments_url": "https://example.com/payments",
        # Supported NIPs (list of integers)
        "supported_nips": [1, 9, 11, 13, 17, 40, 42, 59, 70],
        # Server limitations
        "limitation": {
            "max_message_length": 70000,
            "max_subscriptions": 350,
            "max_limit": 5000,
            "max_subid_length": 256,
            "max_event_tags": 2000,
            "max_content_length": 70000,
            "min_pow_difficulty": 0,
            "auth_required": false,
            "payment_required": true,
            "restricted_writes": true,
            "created_at_lower_limit": 0,
            "created_at_upper_limit": 2147483647,
            "default_limit": 500,
        },
        # Event retention policies
        "retention": [
            {"kinds": [0, 1, [5, 7], [40, 49]], "time": 3600},
            {"kinds": [[40000, 49999]], "time": 100},
            {"kinds": [[30000, 39999]], "count": 1000},
            {"time": 3600, "count": 10000},
        ],
        # Content limitations
        "relay_countries": ["US", "CA", "EU", "*"],
        # Community preferences
        "language_tags": ["en", "en-419", "*"],
        "tags": ["sfw-only", "bitcoin-only"],
        # Fee schedules
        "fees": {
            "admission": [{"amount": 1000000, "unit": "msats"}],
            "subscription": [
                {"amount": 3000, "unit": "sats", "period": 2628003},
                {"amount": 8000, "unit": "sats", "period": 7884009},
            ],
            "publication": [{"kinds": [4], "amount": 100, "unit": "msats"}],
        },
    }

Usage::

    # Fetch from relay
    try:
        nip11 = await Nip11.fetch(relay)
        print(f"Name: {nip11.name}")
        print(f"NIPs: {nip11.supported_nips}")
        print(f"Auth required: {nip11.limitation.get('auth_required')}")
    except Nip11FetchError as err:
        print(f"Failed: {err.cause}")

    # Access parsed metadata
    nip11.metadata.data  # dict with only valid NIP-11 fields

    # Convert for database storage
    relay_metadata = nip11.to_relay_metadata()
"""

from __future__ import annotations

import asyncio
import json
import ssl
from dataclasses import dataclass, field
from time import time
from typing import TYPE_CHECKING, Any, ClassVar, TypedDict, get_type_hints

import aiohttp
from aiohttp_socks import ProxyConnector

from .metadata import Metadata
from .utils import parse_typed_dict


if TYPE_CHECKING:
    from .relay import Relay
    from .relay_metadata import RelayMetadata


# --- TypedDicts for NIP-11 structure ---
#
# These TypedDicts define the expected schema for NIP-11 metadata.
# They are used for type validation in _parse(): fields with
# incorrect types are silently dropped to ensure data integrity.
# All fields are optional (total=False) since relay responses vary widely.


class Nip11Limitation(TypedDict, total=False):
    """Server limitations per NIP-11."""

    max_message_length: int  # Max WebSocket message size in bytes
    max_subscriptions: int  # Max concurrent subscriptions per connection
    max_limit: int  # Max events per REQ response
    max_subid_length: int  # Max subscription ID length
    max_event_tags: int  # Max tags per event
    max_content_length: int  # Max event content length
    min_pow_difficulty: int  # Minimum proof-of-work difficulty
    auth_required: bool  # NIP-42 auth required
    payment_required: bool  # Payment required
    restricted_writes: bool  # Write restrictions
    created_at_lower_limit: int  # Min allowed created_at timestamp
    created_at_upper_limit: int  # Max allowed created_at timestamp
    default_limit: int  # Default limit for REQ without limit


class Nip11RetentionEntry(TypedDict, total=False):
    """Single retention policy entry per NIP-11."""

    kinds: list[int | list[int]]  # Event kinds or ranges [start, end]
    time: int  # Retention time in seconds (null = indefinite)
    count: int  # Max events to retain per kind


class Nip11FeeEntry(TypedDict, total=False):
    """Single fee entry per NIP-11."""

    amount: int  # Fee amount in specified unit
    unit: str  # Unit: "msats", "sats", etc.
    period: int  # Subscription period in seconds
    kinds: list[int]  # Event kinds this fee applies to


class Nip11Fees(TypedDict, total=False):
    """Fee schedules per NIP-11."""

    admission: list[Nip11FeeEntry]  # One-time admission fees
    subscription: list[Nip11FeeEntry]  # Recurring subscription fees
    publication: list[Nip11FeeEntry]  # Per-event publication fees


class Nip11Data(TypedDict, total=False):
    """Complete NIP-11 document structure."""

    # Base fields - relay identification and contact
    name: str  # Relay name
    description: str  # Relay description
    banner: str  # Banner image URL
    icon: str  # Icon image URL
    pubkey: str  # Relay operator pubkey (hex)
    self: str  # Relay's own pubkey for signing (hex)
    contact: str  # Contact info (email, URI, etc.)
    supported_nips: list[int]  # List of supported NIP numbers
    software: str  # Software URL/identifier
    version: str  # Software version string
    privacy_policy: str  # Privacy policy URL
    terms_of_service: str  # Terms of service URL

    # Server limitations
    limitation: Nip11Limitation  # Server constraints

    # Event retention
    retention: list[Nip11RetentionEntry]  # Retention policies

    # Content limitations
    relay_countries: list[str]  # ISO country codes for content filtering

    # Community preferences
    language_tags: list[str]  # BCP 47 language tags
    tags: list[str]  # Community tags (e.g., "sfw-only")
    posting_policy: str  # Posting policy URL

    # Pay-to-relay
    payments_url: str  # Payments info URL
    fees: Nip11Fees  # Fee schedules


# --- Exception ---


class Nip11FetchError(Exception):
    """Error fetching NIP-11 document from relay."""

    def __init__(self, relay: Relay, cause: Exception) -> None:
        self.relay = relay
        self.cause = cause
        super().__init__(f"Failed to fetch NIP-11 from {relay.url}: {cause}")


# --- Main class ---


@dataclass(frozen=True, slots=True)
class Nip11:
    """
    Immutable NIP-11 relay information document.

    Fetches relay information via HTTP with Accept: application/nostr+json header.
    Raw JSON is parsed and validated, keeping only fields defined in NIP-11.
    Invalid fields or wrong types are silently dropped.

    Accepts dict or Metadata - parsing happens in __post_init__.

    Attributes:
        relay: The Relay this document belongs to.
        metadata: Parsed NIP-11 data (all schema keys, None for missing).
        generated_at: Unix timestamp when fetched (default: now).

    Access fields via metadata.data dict:
        nip11.metadata.data["name"]
        nip11.metadata.data["supported_nips"]
        nip11.metadata.data["limitation"]["max_message_length"]
    """

    relay: Relay
    metadata: Metadata  # Raw or parsed, validated in __post_init__
    generated_at: int = field(default_factory=lambda: int(time()))

    # --- Class-level defaults for fetch() ---
    _FETCH_TIMEOUT: ClassVar[float] = 10.0
    _FETCH_MAX_SIZE: ClassVar[int] = 65536  # 64 KB

    def __post_init__(self) -> None:
        """Parse and validate metadata.

        Creates full skeleton with all keys (None for missing values).
        Raises ValueError if all leaf values are None (empty metadata).
        """
        raw = self.metadata.data if isinstance(self.metadata, Metadata) else self.metadata
        parsed = self._parse(raw)

        # Check if all leaves are None
        if self._all_leaves_none(dict(parsed)):
            raise ValueError("NIP-11 metadata cannot be empty (all values are None)")

        object.__setattr__(self, "metadata", Metadata(dict(parsed)))

    # --- Convenience properties for common fields ---

    @property
    def supported_nips(self) -> list[int] | None:
        """List of supported NIP numbers."""
        return self.metadata.data.get("supported_nips")

    @property
    def limitation(self) -> Nip11Limitation | None:
        """Server limitations dict."""
        return self.metadata.data.get("limitation")

    @property
    def retention(self) -> list[Nip11RetentionEntry] | None:
        """Event retention policies."""
        return self.metadata.data.get("retention")

    @property
    def tags(self) -> list[str] | None:
        """Community tags (e.g., 'sfw-only')."""
        return self.metadata.data.get("tags")

    @property
    def name(self) -> str | None:
        """Relay name."""
        return self.metadata.data.get("name")

    # --- Static methods ---

    @staticmethod
    def _all_leaves_none(data: dict[str, Any]) -> bool:
        """Check if all leaf values in the dict are None.

        Handles nested dicts (limitation, fees) by checking their leaves too.
        """
        for value in data.values():
            if isinstance(value, dict):
                # Nested dict - check if any leaf is not None
                if not all(v is None for v in value.values()):
                    return False
            elif value is not None:
                return False
        return True

    @classmethod
    def _parse(cls, raw: dict[str, Any]) -> Nip11Data:
        """Parse raw JSON into validated NIP-11 structure.

        Uses parse_typed_dict for base fields (str, int, list[str], list[int]).
        Custom parsing for nested structures (limitation, retention, fees).
        """
        # Parse base fields using shared function
        result = parse_typed_dict(raw, Nip11Data)

        # Override nested types that need custom parsing
        # Always include full skeleton (all keys present, None for missing)
        limitation = raw.get("limitation")
        if isinstance(limitation, dict):
            result["limitation"] = parse_typed_dict(limitation, Nip11Limitation)
        else:
            # Empty skeleton with all keys set to None
            result["limitation"] = dict.fromkeys(get_type_hints(Nip11Limitation))

        retention = raw.get("retention")
        if isinstance(retention, list):
            parsed_retention = cls._parse_retention(retention)
            result["retention"] = parsed_retention if parsed_retention else None
        else:
            result["retention"] = None

        fees = raw.get("fees")
        if isinstance(fees, dict):
            result["fees"] = cls._parse_fees(fees)
        else:
            # Empty skeleton with all keys set to None
            result["fees"] = dict.fromkeys(get_type_hints(Nip11Fees))

        return result  # type: ignore[return-value]

    @classmethod
    def _parse_retention(cls, raw: list[Any]) -> list[Nip11RetentionEntry]:
        """Parse retention list, validating each entry."""
        result: list[Nip11RetentionEntry] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            parsed: Nip11RetentionEntry = {}

            kinds = entry.get("kinds")
            if isinstance(kinds, list):
                valid_kinds: list[int | list[int]] = []
                for k in kinds:
                    is_range = (
                        isinstance(k, list)
                        and len(k) == 2
                        and isinstance(k[0], int)
                        and isinstance(k[1], int)
                    )
                    if isinstance(k, int) or is_range:
                        valid_kinds.append(k)
                if valid_kinds:
                    parsed["kinds"] = valid_kinds

            if "time" in entry:
                time_val = entry["time"]
                if isinstance(time_val, int):
                    parsed["time"] = time_val

            count_val = entry.get("count")
            if isinstance(count_val, int):
                parsed["count"] = count_val

            if parsed:
                result.append(parsed)
        return result

    @classmethod
    def _parse_fees(cls, raw: dict[str, Any]) -> Nip11Fees:
        """Parse fees dict, validating each category.

        Always returns full skeleton with all keys (None for missing).
        """
        result: Nip11Fees = {}

        for category in ("admission", "subscription", "publication"):
            fee_list = raw.get(category)
            if isinstance(fee_list, list):
                parsed_list = cls._parse_fee_list(fee_list)
                result[category] = parsed_list if parsed_list else None  # type: ignore[literal-required, typeddict-item]
            else:
                result[category] = None  # type: ignore[literal-required, typeddict-item]

        return result

    @classmethod
    def _parse_fee_list(cls, raw: list[Any]) -> list[Nip11FeeEntry]:
        """Parse a list of fee entries."""
        result: list[Nip11FeeEntry] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            parsed: Nip11FeeEntry = {}

            # Integer fields
            for key in ("amount", "period"):
                val = entry.get(key)
                if isinstance(val, int):
                    parsed[key] = val  # type: ignore[literal-required]

            # String fields
            val = entry.get("unit")
            if isinstance(val, str):
                parsed["unit"] = val

            # kinds: list of ints
            val = entry.get("kinds")
            if isinstance(val, list):
                valid_kinds = [k for k in val if isinstance(k, int)]
                if valid_kinds:
                    parsed["kinds"] = valid_kinds

            if parsed:
                result.append(parsed)
        return result

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
        timeout: float,
        max_size: int,
        proxy_url: str | None = None,
    ) -> Metadata:
        """
        Internal fetch returning raw Metadata or raising exception.

        Args:
            relay: Relay object to fetch NIP-11 from
            timeout: Request timeout in seconds
            max_size: Maximum response size in bytes
            proxy_url: Optional SOCKS5 proxy URL

        Returns:
            Metadata with raw NIP-11 data (parsing happens in __post_init__)

        Raises:
            aiohttp.ClientError: Connection or HTTP errors
            asyncio.TimeoutError: Request timeout
            ValueError: Invalid response (status, content-type, size, JSON)
        """
        # Build HTTP URL from relay components
        protocol = "https" if relay.scheme == "wss" else "http"
        # Format host for URL (add brackets for IPv6)
        formatted_host = f"[{relay.host}]" if ":" in relay.host else relay.host
        # Include port only if non-default
        default_port = 443 if protocol == "https" else 80
        port_suffix = f":{relay.port}" if relay.port and relay.port != default_port else ""
        path_suffix = relay.path or ""
        http_url = f"{protocol}://{formatted_host}{port_suffix}{path_suffix}"

        headers = {"Accept": "application/nostr+json"}

        # SSL verification disabled (SSL check is NIP-66's job)
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

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
    ) -> Nip11:
        """
        Fetch NIP-11 document from relay.

        Connects via HTTP(S) with Accept: application/nostr+json header,
        validates the response, and parses into a validated Nip11 instance.
        SSL verification is disabled (SSL check is NIP-66's job).

        Args:
            relay: Relay object to fetch NIP-11 from
            timeout: Request timeout in seconds (default: _FETCH_TIMEOUT)
            max_size: Maximum response size in bytes (default: _FETCH_MAX_SIZE)
            proxy_url: Optional SOCKS5 proxy URL for Tor/I2P/Loki

        Returns:
            Nip11 instance with parsed data

        Raises:
            Nip11FetchError: If fetch fails (wraps the original exception)
            asyncio.CancelledError: If the task was cancelled
            KeyboardInterrupt: If interrupted by user
            SystemExit: If system exit requested

        Example:
            # Basic fetch
            nip11 = await Nip11.fetch(relay)
            print(f"Name: {nip11.metadata.data['name']}")

            # With proxy for onion relay
            nip11 = await Nip11.fetch(relay, proxy_url="socks5://localhost:9050")
        """
        timeout = timeout if timeout is not None else cls._FETCH_TIMEOUT
        max_size = max_size if max_size is not None else cls._FETCH_MAX_SIZE

        try:
            metadata = await cls._fetch(relay, timeout, max_size, proxy_url)
            return cls(relay=relay, metadata=metadata)
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            raise Nip11FetchError(relay, e) from e
