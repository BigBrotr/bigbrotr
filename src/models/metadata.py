"""
Content-addressed metadata payload for BigBrotr.

Provides a generic Metadata class for storing arbitrary JSON-compatible data
with type classification. The content hash (SHA-256) is computed from the value
only (not including type) for deterministic deduplication.

Features:
    - `type` field for metadata classification (MetadataType enum)
    - `value` field for any JSON-compatible dict
    - Type-safe accessor methods with defaults
    - JSON sanitization and normalization for PostgreSQL JSONB storage
    - Deterministic content hashing (SHA-256) computed once at init (from value only)
    - Immutable frozen dataclass design with cached computed values

The Metadata class is agnostic about the structure of `value`. Higher-level
classes (Nip11, Nip66) define their own conventions for what goes in `value`.

Example:
    >>> m = Metadata(type=MetadataType.NIP11_FETCH, value={"name": "My Relay"})
    >>> name = m._get("name", expected_type=str)  # "My Relay"
    >>> params = m.to_db_params()  # MetadataDbParams for database insertion
    >>> content_hash = m.content_hash  # SHA-256 hash for deduplication (from value)
"""

from __future__ import annotations

import builtins
import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, NamedTuple, TypeVar, overload


class MetadataType(StrEnum):
    """Metadata type constants matching database CHECK constraint.

    Supported types:
        - nip11_fetch: NIP-11 relay information document (HTTP fetch)
        - nip66_rtt: NIP-66 round-trip time measurements
        - nip66_ssl: NIP-66 SSL certificate information
        - nip66_geo: NIP-66 geolocation data
        - nip66_net: NIP-66 network information
        - nip66_dns: NIP-66 DNS resolution data
        - nip66_http: NIP-66 HTTP header information
    """

    NIP11_FETCH = "nip11_fetch"
    NIP66_RTT = "nip66_rtt"
    NIP66_SSL = "nip66_ssl"
    NIP66_GEO = "nip66_geo"
    NIP66_NET = "nip66_net"
    NIP66_DNS = "nip66_dns"
    NIP66_HTTP = "nip66_http"


class MetadataDbParams(NamedTuple):
    """Database parameters for Metadata insert operations.

    Attributes:
        id: SHA-256 hash (32 bytes) computed in Python for deduplication.
        value: Canonical JSON string for JSONB storage.
        type: Metadata type (nip11_fetch, nip66_*, etc.).
    """

    id: bytes
    value: str
    type: MetadataType


T = TypeVar("T")
_UNSET: object = object()  # Sentinel for missing default in _get()


@dataclass(frozen=True, slots=True)
class Metadata:
    """
    Immutable typed metadata payload with deterministic content hashing.

    Generic container for any JSON-compatible dict with type classification.
    The content hash (SHA-256) is computed once at creation time using canonical
    JSON serialization (sorted keys, no whitespace) for deterministic deduplication.
    Note: The hash is computed from `value` only, not including `type`.

    Attributes:
        type: Metadata type (MetadataType enum).
        value: JSON-compatible dict with the actual data.

    Value is sanitized and normalized once in __post_init__:
        - Removes None values and empty containers ({}, [])
        - Sorts keys for deterministic serialization
        - Rejects strings containing NUL characters (raises ValueError)

    Computed values (canonical JSON and hash) are cached for efficiency.
    """

    _DEFAULT_MAX_DEPTH: ClassVar[int] = 50

    type: MetadataType
    value: dict[str, Any] = field(default_factory=dict)

    # Cached computed values (set in __post_init__)
    _canonical_json: str = field(default="", init=False, repr=False, compare=False)
    _content_hash: bytes = field(default=b"", init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Sanitize value and compute cached values once at creation."""
        # Sanitize value
        sanitized = self._sanitize(self.value) if self.value else {}
        object.__setattr__(self, "value", sanitized)

        # Compute and cache canonical JSON
        canonical = json.dumps(
            sanitized,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        object.__setattr__(self, "_canonical_json", canonical)

        # Compute and cache content hash
        content_hash = hashlib.sha256(canonical.encode("utf-8")).digest()
        object.__setattr__(self, "_content_hash", content_hash)

    @classmethod
    def _sanitize(cls, obj: Any, max_depth: int | None = None, _depth: int = 0) -> Any:
        """
        Recursively sanitize to JSON-compatible types with normalization.

        Normalization ensures deterministic hashing for content-addressed storage:
            - Removes None values from dicts
            - Removes empty dicts {} and empty lists []
            - Sorts dict keys for consistent serialization

        Args:
            obj: Object to sanitize
            max_depth: Maximum depth limit (None = use default, default = 50)
            _depth: Current recursion depth (internal use)

        Returns:
            Sanitized and normalized object. Empty containers and None become None.
            Non-serializable values become None.

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
        """Check if a value should be filtered out (None or empty container)."""
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
        """
        Get value at any nesting depth with type checking.

        Args:
            *keys: Path to the value (e.g., "name" or "nested", "field")
            expected_type: Expected type of the value
            default: Default value if missing/wrong type (None if not provided)

        Returns:
            The value if found and type matches, otherwise default (or None)

        Examples:
            >>> metadata._get("name", expected_type=str)
            >>> metadata._get("config", "timeout", expected_type=int)
            >>> metadata._get("enabled", expected_type=bool, default=False)
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
        """SHA-256 hash of canonical JSON for content-addressed storage.

        The hash is computed once at creation time from the canonical JSON
        representation (sorted keys, no whitespace) to ensure identical
        semantic data produces identical hashes.

        Returns:
            32-byte SHA-256 digest suitable for PostgreSQL BYTEA.
        """
        return self._content_hash

    @property
    def canonical_json(self) -> str:
        """Canonical JSON representation of value.

        Canonical format:
            - Sorted keys
            - No whitespace (compact separators)
            - UTF-8 encoding

        Returns:
            JSON string suitable for PostgreSQL JSONB storage.
        """
        return self._canonical_json

    def to_db_params(self) -> MetadataDbParams:
        """Returns parameters for database insert.

        Uses pre-computed cached values for efficiency.

        Returns:
            MetadataDbParams with content hash (id), canonical JSON (value), and type.
        """
        return MetadataDbParams(
            id=self._content_hash,
            value=self._canonical_json,
            type=self.type,
        )

    @classmethod
    def from_db_params(cls, params: MetadataDbParams) -> Metadata:
        """
        Create a Metadata from database parameters.

        Args:
            params: MetadataDbParams containing id, value, and type.

        Returns:
            Metadata instance with parsed value and type.

        Raises:
            ValueError: If the computed hash doesn't match id.
        """
        value_dict = json.loads(params.value)
        instance = cls(type=params.type, value=value_dict)

        # Validate hash integrity
        if instance._content_hash != params.id:
            raise ValueError(
                f"Hash mismatch: computed {instance._content_hash.hex()}, "
                f"expected {params.id.hex()}"
            )

        return instance

    @classmethod
    def from_json(cls, metadata_type: MetadataType, json_str: str) -> Metadata:
        """
        Create a Metadata from a JSON string.

        Args:
            metadata_type: Type of metadata.
            json_str: JSON string to parse.

        Returns:
            Metadata instance with parsed value and type.

        Raises:
            json.JSONDecodeError: If JSON is invalid.
        """
        return cls(type=metadata_type, value=json.loads(json_str))

    def __bool__(self) -> bool:
        """Return True if value is non-empty."""
        return bool(self.value)

    def __len__(self) -> int:
        """Return the number of top-level keys in value."""
        return len(self.value)
