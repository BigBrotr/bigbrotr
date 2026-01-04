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
from typing import TYPE_CHECKING, Any, ClassVar, TypedDict

import aiohttp
from aiohttp_socks import ProxyConnector

from .metadata import Metadata


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
    """
    Server limitations per NIP-11.

    All fields are optional - relays may omit any or all fields.
    Used for type validation: values with incorrect types are silently dropped.
    """

    max_message_length: int | None  # Max WebSocket message size in bytes
    max_subscriptions: int | None  # Max concurrent subscriptions per connection
    max_limit: int | None  # Max events per REQ response
    max_subid_length: int | None  # Max subscription ID length
    max_event_tags: int | None  # Max tags per event
    max_content_length: int | None  # Max event content length
    min_pow_difficulty: int | None  # Minimum proof-of-work difficulty
    auth_required: bool | None  # NIP-42 auth required
    payment_required: bool | None  # Payment required
    restricted_writes: bool | None  # Write restrictions
    created_at_lower_limit: int | None  # Min allowed created_at timestamp
    created_at_upper_limit: int | None  # Max allowed created_at timestamp
    default_limit: int | None  # Default limit for REQ without limit


class Nip11RetentionEntry(TypedDict, total=False):
    """
    Single retention policy entry per NIP-11.

    All fields are optional - each entry defines retention for specific kinds or all events.
    Used for type validation: values with incorrect types are silently dropped.
    """

    kinds: list[int | list[int]] | None  # Event kinds or ranges [start, end]
    time: int | None  # Retention time in seconds (null = indefinite)
    count: int | None  # Max events to retain per kind


class Nip11FeeEntry(TypedDict, total=False):
    """
    Single fee entry per NIP-11.

    All fields are optional - defines payment amounts for relay access/features.
    Used for type validation: values with incorrect types are silently dropped.
    """

    amount: int | None  # Fee amount in specified unit
    unit: str | None  # Unit: "msats", "sats", etc.
    period: int | None  # Subscription period in seconds
    kinds: list[int] | None  # Event kinds this fee applies to


class Nip11Fees(TypedDict, total=False):
    """
    Fee schedules per NIP-11.

    All fields are optional - defines admission, subscription, and publication fees.
    Used for type validation: values with incorrect types are silently dropped.
    """

    admission: list[Nip11FeeEntry] | None  # One-time admission fees
    subscription: list[Nip11FeeEntry] | None  # Recurring subscription fees
    publication: list[Nip11FeeEntry] | None  # Per-event publication fees


class Nip11Data(TypedDict, total=False):
    """
    Complete NIP-11 document structure.

    All fields are optional - relays may provide any subset of these fields.
    Used for type validation: values with incorrect types are silently dropped.
    """

    # Base fields - relay identification and contact
    name: str | None  # Relay name
    description: str | None  # Relay description
    banner: str | None  # Banner image URL
    icon: str | None  # Icon image URL
    pubkey: str | None  # Relay operator pubkey (hex)
    self: str | None  # Relay's own pubkey for signing (hex)
    contact: str | None  # Contact info (email, URI, etc.)
    supported_nips: list[int] | None  # List of supported NIP numbers
    software: str | None  # Software URL/identifier
    version: str | None  # Software version string
    privacy_policy: str | None  # Privacy policy URL
    terms_of_service: str | None  # Terms of service URL

    # Server limitations
    limitation: Nip11Limitation | None  # Server constraints

    # Event retention
    retention: list[Nip11RetentionEntry] | None  # Retention policies

    # Content limitations
    relay_countries: list[str] | None  # ISO country codes for content filtering

    # Community preferences
    language_tags: list[str] | None  # BCP 47 language tags
    tags: list[str] | None  # Community tags (e.g., "sfw-only")
    posting_policy: str | None  # Posting policy URL

    # Pay-to-relay
    payments_url: str | None  # Payments info URL
    fees: Nip11Fees | None  # Fee schedules


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
        metadata: Parsed NIP-11 data (only valid fields).
        generated_at: Unix timestamp when fetched (default: now).

    Properties (first-level access):
        name, description, banner, icon: Display information.
        pubkey, self_pubkey, contact: Operator contact.
        supported_nips: List of supported NIP numbers.
        software, version: Relay software identification.
        privacy_policy, terms_of_service, posting_policy: Policy URLs.
        limitation: Server limitations dict (Nip11Limitation).
        retention: Event retention policies list (Nip11RetentionEntry).
        relay_countries: ISO country codes list.
        language_tags, tags: Community preferences.
        payments_url, fees: Payment information (Nip11Fees).
    """

    relay: Relay
    metadata: Metadata  # Raw or parsed, validated in __post_init__
    generated_at: int = field(default_factory=lambda: int(time()))

    # --- Class-level defaults for fetch() ---
    _FETCH_TIMEOUT: ClassVar[float] = 10.0
    _FETCH_MAX_SIZE: ClassVar[int] = 65536  # 64 KB

    def __post_init__(self) -> None:
        """Parse and validate metadata."""
        raw = self.metadata.data if isinstance(self.metadata, Metadata) else self.metadata
        parsed = self._parse(raw)
        object.__setattr__(self, "metadata", Metadata(dict(parsed)))

    @classmethod
    def _parse(cls, raw: dict[str, Any]) -> Nip11Data:
        """Parse raw JSON into validated NIP-11 structure."""
        result: Nip11Data = {}

        # Base string fields
        for key in (
            "name",
            "description",
            "banner",
            "icon",
            "pubkey",
            "self",
            "contact",
            "software",
            "version",
            "privacy_policy",
            "terms_of_service",
            "posting_policy",
            "payments_url",
        ):
            val = raw.get(key)
            if isinstance(val, str):
                result[key] = val  # type: ignore[literal-required]

        # supported_nips: list of ints (only if non-empty)
        supported_nips = raw.get("supported_nips")
        if isinstance(supported_nips, list):
            parsed_nips = [n for n in supported_nips if isinstance(n, int)]
            if parsed_nips:
                result["supported_nips"] = parsed_nips

        # relay_countries: list of strings (only if non-empty)
        relay_countries = raw.get("relay_countries")
        if isinstance(relay_countries, list):
            parsed_countries = [c for c in relay_countries if isinstance(c, str)]
            if parsed_countries:
                result["relay_countries"] = parsed_countries

        # language_tags: list of strings (only if non-empty)
        language_tags = raw.get("language_tags")
        if isinstance(language_tags, list):
            parsed_langs = [t for t in language_tags if isinstance(t, str)]
            if parsed_langs:
                result["language_tags"] = parsed_langs

        # tags: list of strings (only if non-empty)
        tags = raw.get("tags")
        if isinstance(tags, list):
            parsed_tags = [t for t in tags if isinstance(t, str)]
            if parsed_tags:
                result["tags"] = parsed_tags

        # limitation: dict with specific fields (only if non-empty)
        limitation = raw.get("limitation")
        if isinstance(limitation, dict):
            parsed_limitation = cls._parse_limitation(limitation)
            if parsed_limitation:
                result["limitation"] = parsed_limitation

        # retention: list of retention entries (only if non-empty)
        retention = raw.get("retention")
        if isinstance(retention, list):
            parsed_retention = cls._parse_retention(retention)
            if parsed_retention:
                result["retention"] = parsed_retention

        # fees: dict with admission/subscription/publication (only if non-empty)
        fees = raw.get("fees")
        if isinstance(fees, dict):
            parsed_fees = cls._parse_fees(fees)
            if parsed_fees:
                result["fees"] = parsed_fees

        return result

    @classmethod
    def _parse_limitation(cls, raw: dict[str, Any]) -> Nip11Limitation:
        """Parse limitation dict, keeping only valid NIP-11 fields."""
        result: Nip11Limitation = {}

        # Integer fields
        for key in (
            "max_message_length",
            "max_subscriptions",
            "max_limit",
            "max_subid_length",
            "max_event_tags",
            "max_content_length",
            "min_pow_difficulty",
            "created_at_lower_limit",
            "created_at_upper_limit",
            "default_limit",
        ):
            val = raw.get(key)
            if isinstance(val, int):
                result[key] = val  # type: ignore[literal-required]

        # Boolean fields
        for key in ("auth_required", "payment_required", "restricted_writes"):
            val = raw.get(key)
            if isinstance(val, bool):
                result[key] = val  # type: ignore[literal-required]

        return result

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
                if time_val is None or isinstance(time_val, int):
                    parsed["time"] = time_val

            count_val = entry.get("count")
            if isinstance(count_val, int):
                parsed["count"] = count_val

            if parsed:
                result.append(parsed)
        return result

    @classmethod
    def _parse_fees(cls, raw: dict[str, Any]) -> Nip11Fees:
        """Parse fees dict, validating each category."""
        result: Nip11Fees = {}

        for category in ("admission", "subscription", "publication"):
            fee_list = raw.get(category)
            if isinstance(fee_list, list):
                parsed_list = cls._parse_fee_list(fee_list)
                if parsed_list:
                    result[category] = parsed_list  # type: ignore[literal-required]

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

    # --- Helper for metadata access ---

    def _get(self, key: str) -> Any:
        """Get metadata value by key."""
        return self.metadata.data.get(key)

    # --- Properties for first-level access ---

    @property
    def name(self) -> str | None:
        return self._get("name")

    @property
    def description(self) -> str | None:
        return self._get("description")

    @property
    def banner(self) -> str | None:
        return self._get("banner")

    @property
    def icon(self) -> str | None:
        return self._get("icon")

    @property
    def pubkey(self) -> str | None:
        return self._get("pubkey")

    @property
    def self_pubkey(self) -> str | None:
        return self._get("self")

    @property
    def contact(self) -> str | None:
        return self._get("contact")

    @property
    def supported_nips(self) -> list[int] | None:
        return self._get("supported_nips")

    @property
    def software(self) -> str | None:
        return self._get("software")

    @property
    def version(self) -> str | None:
        return self._get("version")

    @property
    def privacy_policy(self) -> str | None:
        return self._get("privacy_policy")

    @property
    def terms_of_service(self) -> str | None:
        return self._get("terms_of_service")

    @property
    def limitation(self) -> Nip11Limitation | None:
        return self._get("limitation")

    @property
    def retention(self) -> list[Nip11RetentionEntry] | None:
        return self._get("retention")

    @property
    def relay_countries(self) -> list[str] | None:
        return self._get("relay_countries")

    @property
    def language_tags(self) -> list[str] | None:
        return self._get("language_tags")

    @property
    def tags(self) -> list[str] | None:
        return self._get("tags")

    @property
    def posting_policy(self) -> str | None:
        return self._get("posting_policy")

    @property
    def payments_url(self) -> str | None:
        return self._get("payments_url")

    @property
    def fees(self) -> Nip11Fees | None:
        return self._get("fees")

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
        verify_ssl: bool = False,
    ) -> Metadata:
        """
        Internal fetch returning raw Metadata or raising exception.

        Args:
            relay: Relay object to fetch NIP-11 from
            timeout: Request timeout in seconds
            max_size: Maximum response size in bytes
            proxy_url: Optional SOCKS5 proxy URL
            verify_ssl: Verify SSL certificates (default: False, SSL check is NIP-66's job)

        Returns:
            Metadata with raw NIP-11 data (parsing happens in __post_init__)

        Raises:
            aiohttp.ClientError: Connection or HTTP errors
            asyncio.TimeoutError: Request timeout
            ValueError: Invalid response (status, content-type, size, JSON)
        """
        protocol = "https" if relay.scheme == "wss" else "http"
        http_url = f"{protocol}://{relay.url_without_scheme}"

        headers = {"Accept": "application/nostr+json"}

        # SSL context: skip verification by default (SSL check is NIP-66's job)
        ssl_context: ssl.SSLContext | bool = True
        if not verify_ssl:
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
        verify_ssl: bool = False,
    ) -> Nip11:
        """
        Fetch NIP-11 document from relay.

        Connects via HTTP(S) with Accept: application/nostr+json header,
        validates the response, and parses into a validated Nip11 instance.

        Args:
            relay: Relay object to fetch NIP-11 from
            timeout: Request timeout in seconds (default: _FETCH_TIMEOUT)
            max_size: Maximum response size in bytes (default: _FETCH_MAX_SIZE)
            proxy_url: Optional SOCKS5 proxy URL for Tor/I2P/Loki
            verify_ssl: Verify SSL certificates (default: False, SSL check is NIP-66's job)

        Returns:
            Nip11 instance with parsed data

        Raises:
            Nip11FetchError: If fetch fails (wraps the original exception)
            asyncio.CancelledError: If the task was cancelled
            KeyboardInterrupt: If interrupted by user
            SystemExit: If system exit requested

        Example:
            # Basic fetch (SSL verification disabled by default)
            nip11 = await Nip11.fetch(relay)
            print(f"Name: {nip11.name}")

            # With proxy for onion relay
            nip11 = await Nip11.fetch(relay, proxy_url="socks5://localhost:9050")

            # With SSL verification enabled
            nip11 = await Nip11.fetch(relay, verify_ssl=True)
        """
        timeout = timeout if timeout is not None else cls._FETCH_TIMEOUT
        max_size = max_size if max_size is not None else cls._FETCH_MAX_SIZE

        try:
            metadata = await cls._fetch(relay, timeout, max_size, proxy_url, verify_ssl)
            return cls(relay=relay, metadata=metadata)
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            raise Nip11FetchError(relay, e) from e
