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
    >>> params = metadata.to_db_params()  # MetadataDbParams for database insertion
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, ClassVar, NamedTuple, TypeVar, overload


class MetadataDbParams(NamedTuple):
    """Database parameters for Metadata insert operations."""

    data_json: str


T = TypeVar("T")
_UNSET: object = object()  # Sentinel for missing default in _get()


@dataclass(frozen=True, slots=True)
class Metadata:
    """
    Immutable metadata payload.

    Contains the JSONB data for NIP-11 or NIP-66 metadata.
    The content hash (SHA-256) is computed by PostgreSQL during insertion.

    Data is sanitized in __post_init__ to ensure JSON compatibility.
    """

    _DEFAULT_MAX_DEPTH: ClassVar[int] = 50

    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Sanitize data after initialization."""
        sanitized = self._sanitize(self.data) if self.data else {}
        object.__setattr__(self, "data", sanitized)

    @classmethod
    def _sanitize(
        cls, obj: Any, max_depth: int | None = _DEFAULT_MAX_DEPTH, _depth: int = 0
    ) -> Any:
        """
        Recursively sanitize to JSON-compatible types.

        Args:
            obj: Object to sanitize
            max_depth: Maximum depth limit (None = unlimited, default = 50)

        Returns:
            Sanitized object. Non-serializable values become None.
        """
        if max_depth is not None and _depth > max_depth:
            return None
        if obj is None or isinstance(obj, bool | int | float):
            return obj
        if isinstance(obj, str):
            return obj.replace("\x00", "") if "\x00" in obj else obj
        if isinstance(obj, dict):
            return {
                k: cls._sanitize(v, max_depth, _depth + 1)
                for k, v in obj.items()
                if isinstance(k, str)
            }
        if isinstance(obj, list):
            return [cls._sanitize(item, max_depth, _depth + 1) for item in obj]
        return None

    @classmethod
    def _to_jsonb(cls, data: dict[str, Any], max_depth: int | None = _DEFAULT_MAX_DEPTH) -> str:
        """Serialize any dict to JSON string safe for PostgreSQL JSONB."""
        return json.dumps(cls._sanitize(data, max_depth), ensure_ascii=False)

    # --- Type-safe accessor ---

    @overload
    def _get(self, *keys: str, expected_type: type[T]) -> T | None: ...
    @overload
    def _get(self, *keys: str, expected_type: type[T], default: T) -> T: ...

    def _get(self, *keys: str, expected_type: type[T], default: T = _UNSET) -> T | None:  # type: ignore[assignment]
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

    def to_db_params(self) -> MetadataDbParams:
        """Returns parameters for database insert."""
        return MetadataDbParams(data_json=self._to_jsonb(self.data))

    @classmethod
    def from_db_params(cls, data_jsonb: str) -> Metadata:
        """
        Create a Metadata from database parameters.

        Args:
            data_jsonb: JSON string from PostgreSQL JSONB column

        Returns:
            Metadata instance with parsed data
        """
        data = json.loads(data_jsonb)
        return cls(data)
