"""
Metadata class for BigBrotr.

Represents metadata payload for relay information documents.
The content-addressed ID (hash) is computed in PostgreSQL during insertion.
"""

import json
from dataclasses import dataclass
from typing import Any, Optional, Type, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class Metadata:
    """
    Immutable metadata payload.

    Contains the JSONB data for NIP-11 or NIP-66 metadata.
    The content-addressed hash ID is computed by PostgreSQL
    during insertion (see insert_relay_metadata procedure).

    This class provides:
    - Type-safe property accessors with defaults
    - JSON sanitization for PostgreSQL JSONB storage
    """

    data: dict[str, Any]

    def __new__(cls, data: Optional[dict[str, Any]] = None) -> "Metadata":
        instance = object.__new__(cls)
        object.__setattr__(instance, "data", data if data is not None else {})
        return instance

    def __init__(self, data: Optional[dict[str, Any]] = None) -> None:
        pass

    # --- Type-safe helpers ---

    def _get(self, key: str, expected_type: Type[T], default: T) -> T:
        """Get value with type checking. Returns default if wrong type."""
        value = self.data.get(key)
        if isinstance(value, expected_type):
            return value
        return default

    def _get_optional(self, key: str, expected_type: Type[T]) -> Optional[T]:
        """Get optional value with type checking. Returns None if wrong type."""
        value = self.data.get(key)
        if value is None or isinstance(value, expected_type):
            return value
        return None

    def _get_nested(self, outer: str, key: str, expected_type: Type[T], default: T) -> T:
        """Get nested value with type checking."""
        outer_dict = self.data.get(outer, {})
        if not isinstance(outer_dict, dict):
            return default
        value = outer_dict.get(key)
        if isinstance(value, expected_type):
            return value
        return default

    def _get_nested_optional(self, outer: str, key: str, expected_type: Type[T]) -> Optional[T]:
        """Get nested optional value with type checking."""
        outer_dict = self.data.get(outer, {})
        if not isinstance(outer_dict, dict):
            return None
        value = outer_dict.get(key)
        if value is None or isinstance(value, expected_type):
            return value
        return None

    # --- JSON serialization ---

    @staticmethod
    def _sanitize_for_json(obj: Any, _seen: Optional[set] = None) -> Any:
        """
        Recursively sanitize object for JSON serialization.

        Handles circular references to prevent infinite recursion.

        Args:
            obj: Object to sanitize
            _seen: Set of object IDs already visited (for cycle detection)

        Returns:
            JSON-serializable version of the object
        """
        if obj is None or isinstance(obj, (bool, int, float, str)):
            return obj

        # Track visited objects to detect circular references
        if _seen is None:
            _seen = set()

        obj_id = id(obj)
        if obj_id in _seen:
            return "<circular reference>"
        _seen.add(obj_id)

        if isinstance(obj, dict):
            result = {}
            for k, v in obj.items():
                if not isinstance(k, str):
                    continue
                try:
                    sanitized = Metadata._sanitize_for_json(v, _seen)
                    if sanitized is not None or v is None:
                        result[k] = sanitized
                except (TypeError, ValueError):
                    continue
            return result

        if isinstance(obj, (list, tuple)):
            result = []
            for item in obj:
                try:
                    sanitized = Metadata._sanitize_for_json(item, _seen)
                    result.append(sanitized)
                except (TypeError, ValueError):
                    continue
            return result

        try:
            return str(obj)
        except Exception:
            return None

    @property
    def data_jsonb(self) -> str:
        """Data as JSON string for PostgreSQL JSONB storage."""
        sanitized = self._sanitize_for_json(self.data)
        return json.dumps(sanitized, ensure_ascii=False)
