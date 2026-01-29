"""
Content-addressed metadata payload for BigBrotr.

Provides a generic Metadata class for storing arbitrary JSON-compatible data
in the unified `metadata` table. The content hash (SHA-256) is computed in
Python for deterministic deduplication.

Features:
    - Single `metadata` field for any JSON-compatible dict
    - Type-safe accessor methods with defaults
    - JSON sanitization and normalization for PostgreSQL JSONB storage
    - Deterministic content hashing (SHA-256) computed in Python
    - Immutable frozen dataclass design

The Metadata class is agnostic about the structure of `metadata`. Higher-level
classes (Nip11, Nip66) define their own conventions for what goes in `metadata`.

Example:
    >>> m = Metadata({"name": "My Relay", "version": "1.0"})
    >>> name = m._get("name", expected_type=str)  # "My Relay"
    >>> params = m.to_db_params()  # MetadataDbParams for database insertion
    >>> content_hash = m.content_hash  # SHA-256 hash for deduplication
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, ClassVar, NamedTuple, TypeVar, overload


class MetadataDbParams(NamedTuple):
    """Database parameters for Metadata insert operations.

    Attributes:
        metadata_id: SHA-256 hash (32 bytes) computed in Python for deduplication.
        metadata_json: Canonical JSON string for JSONB storage.
    """

    metadata_id: bytes
    metadata_json: str


T = TypeVar("T")
_UNSET: object = object()  # Sentinel for missing default in _get()


@dataclass(frozen=True, slots=True)
class Metadata:
    """
    Immutable metadata payload with deterministic content hashing.

    Generic container for any JSON-compatible dict. The content hash (SHA-256)
    is computed in Python using canonical JSON serialization (sorted keys,
    no whitespace) for deterministic deduplication.

    This class is structure-agnostic - it does not assume any particular
    schema for the `metadata` dict. Higher-level classes (Nip11, Nip66) define
    their own conventions.

    Metadata is sanitized and normalized in __post_init__:
        - Removes None values and empty containers ({}, [])
        - Sorts keys for deterministic serialization
        - Strips NUL characters from strings
    """

    _DEFAULT_MAX_DEPTH: ClassVar[int] = 50

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Sanitize metadata after initialization."""
        sanitized = self._sanitize(self.metadata) if self.metadata else {}
        object.__setattr__(self, "metadata", sanitized)

    @classmethod
    def _sanitize(
        cls, obj: Any, max_depth: int | None = _DEFAULT_MAX_DEPTH, _depth: int = 0
    ) -> Any:
        """
        Recursively sanitize to JSON-compatible types with normalization.

        Normalization ensures deterministic hashing for content-addressed storage:
            - Removes None values from dicts
            - Removes empty dicts {} and empty lists []
            - Sorts dict keys for consistent serialization
            - Strips NUL characters from strings

        Args:
            obj: Object to sanitize
            max_depth: Maximum depth limit (None = unlimited, default = 50)

        Returns:
            Sanitized and normalized object. Empty containers and None become None.
            Non-serializable values become None.
        """
        if max_depth is not None and _depth > max_depth:
            return None
        if obj is None or isinstance(obj, bool | int | float):
            return obj
        if isinstance(obj, str):
            return obj.replace("\x00", "") if "\x00" in obj else obj
        if isinstance(obj, dict):
            # Filter to string keys first, then sort for deterministic output
            string_keys = sorted(k for k in obj if isinstance(k, str))
            result = {}
            for k in string_keys:
                v = cls._sanitize(obj[k], max_depth, _depth + 1)
                # Skip None, empty dicts, and empty lists
                if v is None:
                    continue
                if isinstance(v, dict) and not v:
                    continue
                if isinstance(v, list) and not v:
                    continue
                result[k] = v
            return result
        if isinstance(obj, list):
            # Recursively sanitize, filter out None and empty containers
            result_list = []
            for item in obj:
                v = cls._sanitize(item, max_depth, _depth + 1)
                # Skip None, empty dicts, and empty lists within lists
                if v is None:
                    continue
                if isinstance(v, dict) and not v:
                    continue
                if isinstance(v, list) and not v:
                    continue
                result_list.append(v)
            return result_list
        return None

    @classmethod
    def _to_canonical_json(
        cls, data: dict[str, Any], max_depth: int | None = _DEFAULT_MAX_DEPTH
    ) -> str:
        """Serialize to canonical JSON for deterministic hashing.

        Canonical format:
            - Sorted keys
            - No whitespace (compact separators)
            - UTF-8 encoding

        This ensures identical semantic data produces identical JSON strings,
        which in turn produces identical SHA-256 hashes for deduplication.
        """
        sanitized = cls._sanitize(data, max_depth)
        # Use separators without spaces for canonical form
        return json.dumps(
            sanitized if sanitized else {},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    # --- Type-safe accessor ---

    @overload
    def _get(self, *keys: str, expected_type: type[T]) -> T | None: ...
    @overload
    def _get(self, *keys: str, expected_type: type[T], default: T) -> T: ...

    def _get(
        self,
        *keys: str,
        expected_type: type[T],
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
        value: Any = self.metadata
        for key in keys:
            if not isinstance(value, dict):
                return None if default is _UNSET else default
            value = value.get(key)

        if isinstance(value, expected_type):
            return value
        if value is None and default is _UNSET:
            return None
        return None if default is _UNSET else default

    @property
    def content_hash(self) -> bytes:
        """Compute SHA-256 hash of canonical JSON for content-addressed storage.

        The hash is computed from the canonical JSON representation (sorted keys,
        no whitespace) to ensure identical semantic data produces identical hashes.

        Returns:
            32-byte SHA-256 digest suitable for PostgreSQL BYTEA.
        """
        canonical = self._to_canonical_json(self.metadata)
        return hashlib.sha256(canonical.encode("utf-8")).digest()

    def to_db_params(self) -> MetadataDbParams:
        """Returns parameters for database insert.

        Returns:
            MetadataDbParams with pre-computed hash and canonical JSON.
        """
        canonical = self._to_canonical_json(self.metadata)
        content_hash = hashlib.sha256(canonical.encode("utf-8")).digest()
        return MetadataDbParams(metadata_id=content_hash, metadata_json=canonical)

    @classmethod
    def from_db_params(cls, metadata_json: str) -> Metadata:
        """
        Create a Metadata from database parameters.

        Args:
            metadata_json: JSON string from PostgreSQL JSONB column

        Returns:
            Metadata instance with parsed metadata
        """
        metadata = json.loads(metadata_json)
        return cls(metadata)
