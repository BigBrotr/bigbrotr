"""
Content-addressed metadata payload with SHA-256 deduplication.

Stores arbitrary JSON-compatible data with a type classification
(``MetadataType``). A deterministic content hash is computed from the
canonical JSON representation of the value, enabling content-addressed
deduplication in PostgreSQL.

The ``Metadata`` class is agnostic about the internal structure of
``value``; higher-level models such as ``Nip11`` and ``Nip66`` define
their own conventions for what goes inside it.
"""

from __future__ import annotations

import builtins
import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, NamedTuple, TypeVar, overload


class MetadataType(StrEnum):
    """Metadata type identifiers matching the database CHECK constraint.

    Each value corresponds to a specific data source or monitoring test:

    * ``nip11_fetch`` -- NIP-11 relay information document (HTTP fetch)
    * ``nip66_rtt``   -- NIP-66 round-trip time measurements
    * ``nip66_ssl``   -- NIP-66 SSL/TLS certificate information
    * ``nip66_geo``   -- NIP-66 geolocation data
    * ``nip66_net``   -- NIP-66 network and ASN information
    * ``nip66_dns``   -- NIP-66 DNS resolution data
    * ``nip66_http``  -- NIP-66 HTTP header information
    """

    NIP11_FETCH = "nip11_fetch"
    NIP66_RTT = "nip66_rtt"
    NIP66_SSL = "nip66_ssl"
    NIP66_GEO = "nip66_geo"
    NIP66_NET = "nip66_net"
    NIP66_DNS = "nip66_dns"
    NIP66_HTTP = "nip66_http"


class MetadataDbParams(NamedTuple):
    """Positional parameters for the metadata database insert procedure.

    Attributes:
        id: SHA-256 content hash (32 bytes) used as the primary key.
        value: Canonical JSON string for PostgreSQL JSONB storage.
        type: Metadata type discriminator.
    """

    id: bytes
    value: str
    type: MetadataType


T = TypeVar("T")
_UNSET: object = object()  # Sentinel for missing default in _get()


@dataclass(frozen=True, slots=True)
class Metadata:
    """Immutable metadata payload with deterministic content hashing.

    On construction, the ``value`` dict is sanitized (null values and
    empty containers removed, keys sorted) and a canonical JSON string
    is produced. The SHA-256 hash of that string serves as a
    content-addressed identifier for deduplication.

    The hash is derived from ``value`` only -- ``type`` is not included.

    Attributes:
        type: The metadata classification (see ``MetadataType``).
        value: Sanitized JSON-compatible dictionary.
    """

    _DEFAULT_MAX_DEPTH: ClassVar[int] = 50

    type: MetadataType
    value: dict[str, Any] = field(default_factory=dict)

    # Cached computed values (set in __post_init__)
    _canonical_json: str = field(default="", init=False, repr=False, compare=False)
    _content_hash: bytes = field(default=b"", init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Sanitize the value dict and compute the canonical JSON and hash."""
        sanitized = self._sanitize(self.value) if self.value else {}
        object.__setattr__(self, "value", sanitized)

        canonical = json.dumps(
            sanitized,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        object.__setattr__(self, "_canonical_json", canonical)

        content_hash = hashlib.sha256(canonical.encode("utf-8")).digest()
        object.__setattr__(self, "_content_hash", content_hash)

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
        default: T = _UNSET,  # type: ignore[assignment]
    ) -> T | None:
        """Retrieve a nested value with type checking.

        Traverses the ``value`` dict using the given key path and returns
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
        current: Any = self.value
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
        produces the same 32-byte hash.

        Returns:
            32-byte SHA-256 digest suitable for PostgreSQL BYTEA columns.
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

    def to_db_params(self) -> MetadataDbParams:
        """Convert to positional parameters for the database insert procedure.

        Returns:
            MetadataDbParams with the content hash as ``id``, the canonical
            JSON as ``value``, and the metadata type.
        """
        return MetadataDbParams(
            id=self._content_hash,
            value=self._canonical_json,
            type=self.type,
        )

    @classmethod
    def from_db_params(cls, params: MetadataDbParams) -> Metadata:
        """Reconstruct a Metadata instance from database parameters.

        Re-parses the stored JSON and verifies that the recomputed hash
        matches the stored ``id`` to detect data corruption.

        Args:
            params: Database row values previously produced by ``to_db_params()``.

        Returns:
            A new Metadata instance.

        Raises:
            ValueError: If the recomputed hash does not match ``params.id``.
        """
        value_dict = json.loads(params.value)
        instance = cls(type=params.type, value=value_dict)

        if instance._content_hash != params.id:
            raise ValueError(
                f"Hash mismatch: computed {instance._content_hash.hex()}, "
                f"expected {params.id.hex()}"
            )

        return instance

    @classmethod
    def from_json(cls, metadata_type: MetadataType, json_str: str) -> Metadata:
        """Create a Metadata instance from a raw JSON string.

        Args:
            metadata_type: The type classification for this metadata.
            json_str: JSON string to parse into the value dict.

        Returns:
            A new Metadata instance.

        Raises:
            json.JSONDecodeError: If *json_str* is not valid JSON.
        """
        return cls(type=metadata_type, value=json.loads(json_str))

    def __bool__(self) -> bool:
        """Return True if the value dict is non-empty."""
        return bool(self.value)

    def __len__(self) -> int:
        """Return the number of top-level keys in the value dict."""
        return len(self.value)
