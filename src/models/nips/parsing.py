"""Parsing utilities for NIP data models.

This module provides centralized field parsing logic for NIP-11 and NIP-66
data models. The FieldSpec dataclass defines which fields should be parsed
as which types, eliminating the need for each model class to repeat the
same parsing logic.

Key Features:
    - Declarative field type specification via FieldSpec
    - Type coercion with silent dropping of invalid values
    - Support for int, bool, str, float, list[int], list[str]
    - Reusable across all NIP data models

Example:
    >>> from models.nips.parsing import FieldSpec, parse_fields
    >>> spec = FieldSpec(
    ...     int_fields=frozenset({"count", "limit"}),
    ...     str_fields=frozenset({"name", "description"}),
    ... )
    >>> data = {"count": 10, "name": "Test", "invalid": "value"}
    >>> result = parse_fields(data, spec)
    >>> # result = {"count": 10, "name": "Test"}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """Specification of field types for parsing NIP data.

    Defines which fields in a data dict should be parsed as which types.
    Used by parse_fields() to perform type-aware parsing with silent
    dropping of invalid values.

    All field sets are frozensets for immutability and hashability.

    Attributes:
        int_fields: Fields that should be int (not bool).
        bool_fields: Fields that should be bool.
        str_fields: Fields that should be str.
        str_list_fields: Fields that should be list[str].
        float_fields: Fields that should be float (accepts int, converts).
        int_list_fields: Fields that should be list[int].
    """

    int_fields: frozenset[str] = field(default_factory=frozenset)
    bool_fields: frozenset[str] = field(default_factory=frozenset)
    str_fields: frozenset[str] = field(default_factory=frozenset)
    str_list_fields: frozenset[str] = field(default_factory=frozenset)
    float_fields: frozenset[str] = field(default_factory=frozenset)
    int_list_fields: frozenset[str] = field(default_factory=frozenset)


def parse_fields(data: dict[str, Any], spec: FieldSpec) -> dict[str, Any]:
    """Parse dict according to FieldSpec, dropping invalid values.

    Iterates over all key-value pairs in the input data and validates
    each against the field type specifications. Invalid values are
    silently dropped (not included in the result).

    Type Handling:
        - int_fields: Must be int (bool excluded). Dropped if not.
        - bool_fields: Must be bool. Dropped if not.
        - str_fields: Must be str. Dropped if not.
        - str_list_fields: Must be list. Invalid elements filtered out.
        - float_fields: Must be int or float. Converted to float.
        - int_list_fields: Must be list. Invalid elements filtered out.

    Args:
        data: Raw dictionary to parse.
        spec: FieldSpec defining expected field types.

    Returns:
        dict[str, Any]: Dictionary containing only valid fields.
            Keys not matching any field set in spec are ignored.
    """
    result: dict[str, Any] = {}

    for key, value in data.items():
        if key in spec.int_fields:
            # int but not bool (Python bool is subclass of int)
            if isinstance(value, int) and not isinstance(value, bool):
                result[key] = value

        elif key in spec.bool_fields:
            if isinstance(value, bool):
                result[key] = value

        elif key in spec.str_fields:
            if isinstance(value, str):
                result[key] = value

        elif key in spec.str_list_fields:
            if isinstance(value, list):
                str_items = [s for s in value if isinstance(s, str)]
                if str_items:
                    result[key] = str_items

        elif key in spec.float_fields:
            # Accept int or float, convert to float
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                result[key] = float(value)

        elif key in spec.int_list_fields and isinstance(value, list):
            int_items = [i for i in value if isinstance(i, int) and not isinstance(i, bool)]
            if int_items:
                result[key] = int_items

    return result


__all__ = ["FieldSpec", "parse_fields"]
