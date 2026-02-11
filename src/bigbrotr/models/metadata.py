"""
Content-addressed metadata with SHA-256 deduplication.

Stores arbitrary JSON-compatible data with a type classification
([MetadataType][bigbrotr.models.metadata.MetadataType]). A deterministic
content hash is computed from the canonical JSON representation of the
data, enabling content-addressed deduplication in PostgreSQL.

The [Metadata][bigbrotr.models.metadata.Metadata] class is agnostic about
the internal structure of ``data``; higher-level models in
[bigbrotr.nips.nip11][] and [bigbrotr.nips.nip66][] define their own
conventions for what goes inside it.

See Also:
    [bigbrotr.models.relay_metadata][]: Junction model linking a
        [Relay][bigbrotr.models.relay.Relay] to a
        [Metadata][bigbrotr.models.metadata.Metadata] record.
    [bigbrotr.nips.nip11][]: Produces ``nip11_info``-typed metadata from
        relay information documents.
    [bigbrotr.nips.nip66][]: Produces ``nip66_*``-typed metadata from
        health check results (RTT, SSL, DNS, Geo, Net, HTTP).
"""

from __future__ import annotations

import builtins  # noqa: TC003
import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, NamedTuple, TypeVar, overload


class MetadataType(StrEnum):
    """Metadata type identifiers stored in the ``metadata.metadata_type`` column.

    Each value corresponds to a specific data source or monitoring test
    performed by the [Monitor][bigbrotr.services.monitor.Monitor] service.

    Attributes:
        NIP11_INFO: NIP-11 relay information document fetched via HTTP(S).
        NIP66_RTT: NIP-66 round-trip time measurements (WebSocket latency).
        NIP66_SSL: NIP-66 SSL/TLS certificate information (expiry, issuer, chain).
        NIP66_GEO: NIP-66 geolocation data (country, city, coordinates).
        NIP66_NET: NIP-66 network and ASN information (provider, AS number).
        NIP66_DNS: NIP-66 DNS resolution data (A/AAAA records, response times).
        NIP66_HTTP: NIP-66 HTTP header information (server, content-type, CORS).

    See Also:
        [Metadata][bigbrotr.models.metadata.Metadata]: The content-addressed container
            that carries a [MetadataType][bigbrotr.models.metadata.MetadataType] alongside
            its data.
        [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]: Junction model
            linking a relay to a metadata record.
    """

    NIP11_INFO = "nip11_info"
    NIP66_RTT = "nip66_rtt"
    NIP66_SSL = "nip66_ssl"
    NIP66_GEO = "nip66_geo"
    NIP66_NET = "nip66_net"
    NIP66_DNS = "nip66_dns"
    NIP66_HTTP = "nip66_http"


class MetadataDbParams(NamedTuple):
    """Positional parameters for the metadata database insert procedure.

    Produced by [Metadata.to_db_params()][bigbrotr.models.metadata.Metadata.to_db_params]
    and consumed by the ``metadata_insert`` stored procedure in PostgreSQL.

    Attributes:
        id: SHA-256 content hash (32 bytes), part of composite PK ``(id, metadata_type)``.
        metadata_type: [MetadataType][bigbrotr.models.metadata.MetadataType] discriminator,
            part of composite PK ``(id, metadata_type)``.
        data: Canonical JSON string for PostgreSQL JSONB storage.

    See Also:
        [Metadata][bigbrotr.models.metadata.Metadata]: The model that produces these
            parameters.
        [Metadata.from_db_params()][bigbrotr.models.metadata.Metadata.from_db_params]:
            Reconstructs a [Metadata][bigbrotr.models.metadata.Metadata] instance from
            these parameters with integrity verification.
    """

    id: bytes
    metadata_type: MetadataType
    data: str


T = TypeVar("T")
_UNSET: Any = object()  # Sentinel for missing default in _get()


@dataclass(frozen=True, slots=True)
class Metadata:
    """Immutable metadata with deterministic content hashing.

    On construction, the ``data`` dict is sanitized (null values and
    empty containers removed, keys sorted) and a canonical JSON string
    is produced. The SHA-256 hash of that string serves as a
    content-addressed identifier for deduplication.

    The hash is derived from ``data`` only -- ``type`` is not included in
    the hash computation but is part of the composite primary key
    ``(id, metadata_type)`` in the database.

    Attributes:
        type: The metadata classification
            (see [MetadataType][bigbrotr.models.metadata.MetadataType]).
        data: Sanitized JSON-compatible dictionary.

    Examples:
        ```python
        meta = Metadata(type=MetadataType.NIP11_INFO, data={"name": "My Relay"})
        meta.content_hash    # 32-byte SHA-256 digest
        meta.canonical_json  # '{"name":"My Relay"}'
        meta.to_db_params()  # MetadataDbParams(...)
        ```

        Identical data always produces the same hash (content-addressed):

        ```python
        m1 = Metadata(type=MetadataType.NIP11_INFO, data={"b": 2, "a": 1})
        m2 = Metadata(type=MetadataType.NIP11_INFO, data={"a": 1, "b": 2})
        m1.content_hash == m2.content_hash  # True
        ```

    Note:
        The content hash is derived from ``data`` alone. The ``type`` is stored
        alongside the hash on the ``metadata`` table with composite primary key
        ``(id, metadata_type)``, ensuring each document is tied to exactly one type.
        The ``relay_metadata`` junction table references metadata via a
        compound foreign key on ``(metadata_id, metadata_type)``.

        Computed fields (``_canonical_json``, ``_content_hash``, ``_db_params``)
        are set via ``object.__setattr__`` in ``__post_init__`` because the
        dataclass is frozen.

    Warning:
        String data containing null bytes (``\\x00``) will raise ``ValueError``
        during sanitization. PostgreSQL TEXT and JSONB columns do not support null
        bytes.

    See Also:
        [MetadataType][bigbrotr.models.metadata.MetadataType]: Enum of supported
            metadata classifications.
        [MetadataDbParams][bigbrotr.models.metadata.MetadataDbParams]: Database
            parameter container produced by
            [to_db_params()][bigbrotr.models.metadata.Metadata.to_db_params].
        [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]: Junction
            linking a [Relay][bigbrotr.models.relay.Relay] to this metadata record.
    """

    _DEFAULT_MAX_DEPTH: ClassVar[int] = 50

    type: MetadataType
    data: dict[str, Any] = field(default_factory=dict)

    # Cached computed values (set in __post_init__)
    _canonical_json: str = field(default="", init=False, repr=False, compare=False)
    _content_hash: bytes = field(default=b"", init=False, repr=False, compare=False)
    _db_params: MetadataDbParams | None = field(
        default=None, init=False, repr=False, compare=False, hash=False
    )

    def __post_init__(self) -> None:
        """Sanitize the data dict and compute the canonical JSON and hash."""
        sanitized = self._sanitize(self.data) if self.data else {}
        object.__setattr__(self, "data", sanitized)

        canonical = json.dumps(
            sanitized,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        object.__setattr__(self, "_canonical_json", canonical)

        content_hash = hashlib.sha256(canonical.encode("utf-8")).digest()
        object.__setattr__(self, "_content_hash", content_hash)

        object.__setattr__(self, "_db_params", self._compute_db_params())

    @classmethod
    def _sanitize(cls, obj: Any, max_depth: int | None = None, _depth: int = 0) -> Any:
        """Recursively normalize an object for deterministic JSON serialization.

        * Removes ``None`` values and empty containers (``{}``, ``[]``).
        * Sorts dictionary keys for consistent ordering.
        * Rejects strings containing null bytes (PostgreSQL incompatible).
        * Non-serializable types are replaced with ``None``.

        Args:
            obj: The value to sanitize.
            max_depth: Maximum recursion depth (defaults to 50).
            _depth: Current recursion depth (internal use).

        Returns:
            The sanitized object, or ``None`` for unserializable values.

        Raises:
            ValueError: If any string contains null bytes.
        """
        if max_depth is None:
            max_depth = cls._DEFAULT_MAX_DEPTH

        if _depth > max_depth:
            return None

        if obj is None or isinstance(obj, bool | int | float):
            return obj

        if isinstance(obj, str):
            if "\x00" in obj:
                raise ValueError("Metadata value contains null bytes")
            return obj

        if isinstance(obj, dict):
            result: dict[str, Any] = {}
            for key in sorted(k for k in obj if isinstance(k, str)):
                v = cls._sanitize(obj[key], max_depth, _depth + 1)
                if cls._is_empty(v):
                    continue
                result[key] = v
            return result

        if isinstance(obj, list):
            result_list: list[Any] = []
            for item in obj:
                v = cls._sanitize(item, max_depth, _depth + 1)
                if cls._is_empty(v):
                    continue
                result_list.append(v)
            return result_list

        return None

    @staticmethod
    def _is_empty(v: Any) -> bool:
        """Return True if the value is None or an empty container."""
        if v is None:
            return True
        if isinstance(v, dict) and not v:
            return True
        return bool(isinstance(v, list) and not v)

    # --- Type-safe accessor ---

    @overload
    def _get(self, *keys: str, expected_type: builtins.type[T]) -> T | None: ...
    @overload
    def _get(self, *keys: str, expected_type: builtins.type[T], default: T) -> T: ...

    def _get(
        self,
        *keys: str,
        expected_type: builtins.type[T],
        default: T = _UNSET,
    ) -> T | None:
        """Retrieve a nested value with type checking.

        Traverses the ``data`` dict using the given key path and returns
        the leaf value if it matches ``expected_type``.

        Args:
            *keys: Key path into the nested dict (e.g., ``"config", "timeout"``).
            expected_type: Required type for the returned value.
            default: Fallback if the path is missing or the type is wrong.
                Defaults to ``None`` when not specified.

        Returns:
            The value at the key path if it matches ``expected_type``,
            otherwise *default*.
        """
        current: Any = self.data
        for key in keys:
            if not isinstance(current, dict):
                return default if default is not _UNSET else None
            current = current.get(key)

        if isinstance(current, expected_type):
            return current

        return default if default is not _UNSET else None

    @property
    def content_hash(self) -> bytes:
        """SHA-256 digest of the canonical JSON representation.

        Computed once at construction time. Identical semantic data always
        produces the same 32-byte hash, enabling content-addressed
        deduplication in the ``metadata`` table.

        Returns:
            32-byte SHA-256 digest suitable for PostgreSQL BYTEA columns.

        See Also:
            [canonical_json][bigbrotr.models.metadata.Metadata.canonical_json]:
                The JSON string from which this hash is derived.
        """
        return self._content_hash

    @property
    def canonical_json(self) -> str:
        """Canonical JSON string used for hashing and JSONB storage.

        Format: sorted keys, compact separators, UTF-8 encoding.

        Returns:
            Deterministic JSON string of the sanitized value.
        """
        return self._canonical_json

    def _compute_db_params(self) -> MetadataDbParams:
        """Compute positional parameters for the database insert procedure.

        Called once during ``__post_init__`` to populate the ``_db_params``
        cache. All subsequent access goes through
        [to_db_params()][bigbrotr.models.metadata.Metadata.to_db_params].

        Returns:
            [MetadataDbParams][bigbrotr.models.metadata.MetadataDbParams] with
            the content hash as ``id``, the canonical JSON as ``data``,
            and the metadata type.
        """
        return MetadataDbParams(
            id=self._content_hash,
            metadata_type=self.type,
            data=self._canonical_json,
        )

    def to_db_params(self) -> MetadataDbParams:
        """Return cached positional parameters for the database insert procedure.

        The result is computed once during construction and cached for the
        lifetime of the (frozen) instance.

        Returns:
            [MetadataDbParams][bigbrotr.models.metadata.MetadataDbParams] with
            the content hash as ``id``, the canonical JSON as ``data``,
            and the metadata type.
        """
        assert self._db_params is not None  # noqa: S101  # Always set in __post_init__
        return self._db_params

    @classmethod
    def from_db_params(cls, params: MetadataDbParams) -> Metadata:
        """Reconstruct a ``Metadata`` instance from database parameters.

        Re-parses the stored JSON and verifies that the recomputed hash
        matches the stored ``id`` to detect data corruption.

        Args:
            params: Database row values previously produced by
                [to_db_params()][bigbrotr.models.metadata.Metadata.to_db_params].

        Returns:
            A new [Metadata][bigbrotr.models.metadata.Metadata] instance.

        Raises:
            ValueError: If the recomputed hash does not match ``params.id``,
                indicating data corruption in the database.

        Note:
            Unlike [Relay.from_db_params()][bigbrotr.models.relay.Relay.from_db_params],
            this method performs an explicit integrity check by comparing the
            recomputed SHA-256 hash against the stored ``id``. This catches
            silent data corruption that could otherwise propagate through the
            pipeline.
        """
        value_dict = json.loads(params.data)
        instance = cls(type=params.metadata_type, data=value_dict)

        if instance._content_hash != params.id:
            raise ValueError(
                f"Hash mismatch: computed {instance._content_hash.hex()}, "
                f"expected {params.id.hex()}"
            )

        return instance

    @classmethod
    def from_json(cls, metadata_type: MetadataType, json_str: str) -> Metadata:
        """Create a [Metadata][bigbrotr.models.metadata.Metadata] instance from a raw JSON string.

        Args:
            metadata_type: The [MetadataType][bigbrotr.models.metadata.MetadataType]
                classification for this metadata.
            json_str: JSON string to parse into the value dict.

        Returns:
            A new [Metadata][bigbrotr.models.metadata.Metadata] instance with the
            parsed and sanitized value.

        Raises:
            json.JSONDecodeError: If *json_str* is not valid JSON.
        """
        return cls(type=metadata_type, data=json.loads(json_str))

    def __bool__(self) -> bool:
        """Return True if the data dict is non-empty."""
        return bool(self.data)

    def __len__(self) -> int:
        """Return the number of top-level keys in the data dict."""
        return len(self.data)
