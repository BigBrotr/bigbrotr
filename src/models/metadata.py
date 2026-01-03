"""
Content-addressed metadata payload for BigBrotr.

Provides the Metadata class for storing NIP-11 and NIP-66 data in the unified
`metadata` table. The content hash (SHA-256) is computed by PostgreSQL during
insertion, enabling automatic deduplication of identical metadata across relays.

Features:
    - Type-safe accessor methods with defaults
    - JSON sanitization for PostgreSQL JSONB storage
    - Circular reference handling during serialization
    - Immutable frozen dataclass design

Example:
    >>> metadata = Metadata({"name": "My Relay", "supported_nips": [1, 11]})
    >>> name = metadata._get("name", expected_type=str)  # "My Relay"
    >>> nips = metadata._get("supported_nips", expected_type=list, default=[])
    >>> (json_str,) = metadata.to_db_params()  # For database insertion
"""

import json
from dataclasses import dataclass
from typing import Any, TypeVar, overload


T = TypeVar("T")
_UNSET: Any = object()  # Sentinel for missing default


@dataclass(frozen=True, slots=True)
class Metadata:
    """
    Immutable metadata payload.

    Contains the JSONB data for NIP-11 or NIP-66 metadata.
    The content-addressed hash ID is computed by PostgreSQL
    during insertion (see relay_metadata_insert_cascade procedure).

    This class provides:
    - Type-safe property accessors with defaults
    - JSON sanitization for PostgreSQL JSONB storage
    """

    data: dict[str, Any]

    @staticmethod
    def _sanitize(obj: Any) -> Any:
        """Recursively sanitize to JSON-compatible types. Non-serializable values become None."""
        if obj is None or isinstance(obj, (bool, int, float)):
            return obj
        if isinstance(obj, str):
            return obj.replace("\x00", "") if "\x00" in obj else obj
        if isinstance(obj, dict):
            return {k: Metadata._sanitize(v) for k, v in obj.items() if isinstance(k, str)}
        if isinstance(obj, list):
            return [Metadata._sanitize(item) for item in obj]
        return None

    @staticmethod
    def _to_jsonb(data: dict[str, Any]) -> str:
        """Serialize any dict to JSON string safe for PostgreSQL JSONB."""
        return json.dumps(Metadata._sanitize(data), ensure_ascii=False)

    def __new__(cls, data: dict[str, Any] | None = None) -> "Metadata":
        instance = object.__new__(cls)
        sanitized = cls._sanitize(data) if data else {}
        object.__setattr__(instance, "data", sanitized)
        return instance

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        """Empty initializer; all initialization is performed in __new__ for frozen dataclass."""

    # --- Type-safe accessor ---

    @overload
    def _get(self, *keys: str, expected_type: type[T]) -> T | None: ...
    @overload
    def _get(self, *keys: str, expected_type: type[T], default: T) -> T: ...

    def _get(self, *keys: str, expected_type: type[T], default: T = _UNSET) -> T | None:
        """
        Get value at any nesting depth with type checking.

        Args:
            *keys: Path to the value (e.g., "name" or "limitation", "max_limit")
            expected_type: Expected type of the value
            default: Default value if missing/wrong type (None if not provided)

        Returns:
            The value if found and type matches, otherwise default (or None)

        Examples:
            >>> metadata._get("name", expected_type=str)  # top-level, optional
            >>> metadata._get("supported_nips", expected_type=list, default=[])  # with default
            >>> metadata._get("limitation", "max_limit", expected_type=int)  # nested
            >>> metadata._get("fees", "admission", "amount", expected_type=int)  # deep nested
        """
        value: Any = self.data
        for key in keys:
            if not isinstance(value, dict):
                return None if default is _UNSET else default
            value = value.get(key)

        if isinstance(value, expected_type):
            return value
        if value is None and default is _UNSET:
            return None
        return None if default is _UNSET else default

    def to_db_params(self) -> tuple[str]:
        """Returns parameters for database insert: (json_string,)."""
        return (self._to_jsonb(self.data),)

    @classmethod
    def from_db_params(cls, data_jsonb: str) -> "Metadata":
        """
        Create a Metadata from database parameters.

        Args:
            data_jsonb: JSON string from PostgreSQL JSONB column

        Returns:
            Metadata instance with parsed data
        """
        data = json.loads(data_jsonb)
        return cls(data)
