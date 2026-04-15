"""
Validated Nostr relay URL with network type detection.

Parses, normalizes, and validates WebSocket relay URLs (``ws://`` or ``wss://``),
automatically detecting the [NetworkType][bigbrotr.models.constants.NetworkType]
(clearnet, Tor, I2P, Lokinet) and enforcing the correct scheme for each network.
Local and private IP addresses are rejected.

See Also:
    [bigbrotr.models.constants][]: Defines the
        [NetworkType][bigbrotr.models.constants.NetworkType] enum used for classification.
    [bigbrotr.models.event_relay][]: Links a [Relay][bigbrotr.models.relay.Relay] to an
        [Event][bigbrotr.models.event.Event] via the ``event_relay`` junction table.
    [bigbrotr.models.relay_metadata][]: Links a [Relay][bigbrotr.models.relay.Relay] to a
        [Metadata][bigbrotr.models.metadata.Metadata] record via the ``relay_metadata``
        junction table.
    [bigbrotr.utils.transport][]: Uses [Relay][bigbrotr.models.relay.Relay] URLs for
        WebSocket connectivity checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import TYPE_CHECKING, NamedTuple

from ._validation import validate_str_no_null, validate_timestamp
from .relay_url import normalize_relay_url, parse_canonical_relay_url


if TYPE_CHECKING:
    from .constants import NetworkType


class RelayDbParams(NamedTuple):
    """Positional parameters for the relay database insert procedure.

    Produced by [Relay.to_db_params()][bigbrotr.models.relay.Relay.to_db_params]
    and consumed by the ``relay_insert`` stored procedure in PostgreSQL.

    Attributes:
        url: Fully normalized WebSocket URL including scheme.
        network: Network type string (e.g., ``"clearnet"``, ``"tor"``).
        discovered_at: Unix timestamp when the relay was first discovered.

    See Also:
        [Relay][bigbrotr.models.relay.Relay]: The model that produces these parameters.
    """

    url: str
    network: str
    discovered_at: int


@dataclass(frozen=True, slots=True)
class Relay:
    """Immutable representation of a Nostr relay.

    Accepts only URLs already in canonical form.  If the input may be
    dirty (from Nostr events, relay lists, external APIs), pass it through
    [normalize_relay_url][bigbrotr.models.relay_url.normalize_relay_url] or
    [Relay.parse][bigbrotr.models.relay.Relay.parse] first.

    The canonical form enforces:

    * **scheme** -- ``wss://`` for clearnet, ``ws://`` for overlay networks
    * **no query string or fragment**
    * **no garbage path** (control characters, whitespace, embedded URI schemes)
    * **default ports omitted** (443 for ``wss``, 80 for ``ws``)
    * **lowercase host**, collapsed path slashes, no trailing slash

    Attributes:
        url: Canonical normalized URL (init field and primary identity).
        network: Detected [NetworkType][bigbrotr.models.constants.NetworkType] enum value.
        scheme: URL scheme (``ws`` or ``wss``).
        host: Hostname or IP address (brackets stripped for IPv6).
        port: Explicit port number, or ``None`` when using the default.
        path: URL path component, or ``None``.
        discovered_at: Unix timestamp when the relay was first discovered.

    Raises:
        ValueError: If the URL is not in canonical form, malformed,
            uses an unsupported scheme, or contains null bytes.

    Examples:
        ```python
        relay = Relay("wss://relay.damus.io")
        relay.url       # 'wss://relay.damus.io'
        relay.network   # NetworkType.CLEARNET
        relay.scheme    # 'wss'
        relay.to_db_params()
        # RelayDbParams(url='wss://relay.damus.io', network='clearnet', ...)
        ```

        For untrusted input, sanitize first:

        ```python
        from bigbrotr.models.relay_url import normalize_relay_url

        dirty = "ws://Relay.Example.Com:443/path?key=val#frag"
        clean = normalize_relay_url(dirty)  # 'wss://relay.example.com/path'
        relay = Relay(clean)
        ```

    Note:
        Computed fields are set via ``object.__setattr__`` in ``__post_init__``
        because the dataclass is frozen. This is the standard workaround and is
        safe because it runs during ``__init__`` before the instance is exposed.

    See Also:
        [normalize_relay_url][bigbrotr.models.relay_url.normalize_relay_url]: Pre-processor
            for untrusted relay URLs.
        [Relay.parse][bigbrotr.models.relay.Relay.parse]: Higher-level parser
            with explicit policy controls for local relay acceptance.
        [NetworkType][bigbrotr.models.constants.NetworkType]: Enum of supported network types.
        [RelayDbParams][bigbrotr.models.relay.RelayDbParams]: Database parameter container
            produced by [to_db_params()][bigbrotr.models.relay.Relay.to_db_params].
        [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]: Junction linking
            a relay to a [Metadata][bigbrotr.models.metadata.Metadata] record.
        [EventRelay][bigbrotr.models.event_relay.EventRelay]: Junction linking a relay
            to an [Event][bigbrotr.models.event.Event].
    """

    url: str
    discovered_at: int = field(default_factory=lambda: int(time()))

    network: NetworkType = field(init=False)
    scheme: str = field(init=False)
    host: str = field(init=False)
    port: int | None = field(init=False)
    path: str | None = field(init=False)
    _db_params: RelayDbParams = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
        hash=False,  # type: ignore[assignment]  # mypy expects bool literal, field() accepts it at runtime
    )

    def __post_init__(self) -> None:
        """Validate that the URL is in canonical form and populate computed fields.

        Raises:
            TypeError: If field types are incorrect.
            ValueError: If the URL is not canonical, invalid, or contains null bytes.
        """
        validate_str_no_null(self.url, "url")
        validate_timestamp(self.discovered_at, "discovered_at")

        # Defence in depth: re-sanitize to guarantee canonical form even though
        # callers should pre-sanitize.  This duplicates the RFC 3986 parse in
        # _parse() below -- a deliberate "never trust input" trade-off.
        canonical = normalize_relay_url(self.url, allow_local=True)
        if canonical != self.url:
            raise ValueError(
                f"Relay URL is not in canonical form: {self.url!r} (expected {canonical!r})"
            )

        parsed = parse_canonical_relay_url(self.url)

        object.__setattr__(self, "network", parsed.network)
        object.__setattr__(self, "scheme", parsed.scheme)
        object.__setattr__(self, "host", parsed.host)
        object.__setattr__(self, "port", parsed.port)
        object.__setattr__(self, "path", parsed.path)

        object.__setattr__(self, "_db_params", self._compute_db_params())

    @classmethod
    def parse(
        cls,
        raw: str,
        *,
        discovered_at: int | None = None,
        allow_local: bool = False,
    ) -> Relay:
        """Parse raw input into a canonical Relay using an explicit policy.

        Args:
            raw: Raw relay URL string from untrusted input.
            discovered_at: Optional discovery timestamp.
            allow_local: When ``True``, accept canonical local relay URLs
                such as ``ws://localhost`` or ``wss://127.0.0.1:7447``.

        Returns:
            Canonical [Relay][bigbrotr.models.relay.Relay].

        Raises:
            ValueError: If the raw URL is invalid or disallowed by policy.
            TypeError: If field types are invalid.
        """
        canonical = normalize_relay_url(raw, allow_local=allow_local)
        if discovered_at is not None:
            return cls(canonical, discovered_at)
        return cls(canonical)

    def _compute_db_params(self) -> RelayDbParams:
        """Compute positional parameters for the database insert procedure.

        Called once during ``__post_init__`` to populate the ``_db_params``
        cache. All subsequent access goes through
        [to_db_params()][bigbrotr.models.relay.Relay.to_db_params].

        Returns:
            [RelayDbParams][bigbrotr.models.relay.RelayDbParams] with the
            normalized URL, network name, and discovery timestamp.
        """
        return RelayDbParams(
            url=self.url,
            network=self.network,
            discovered_at=self.discovered_at,
        )

    def to_db_params(self) -> RelayDbParams:
        """Return cached positional parameters for the database insert procedure.

        The result is computed once during construction and cached for the
        lifetime of the (frozen) instance, avoiding repeated network name
        conversions.

        Returns:
            [RelayDbParams][bigbrotr.models.relay.RelayDbParams] with the
            normalized URL, network name, and discovery timestamp.
        """
        return self._db_params
