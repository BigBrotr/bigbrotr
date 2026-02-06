"""
Declarative field parsing for NIP data models.

Centralizes the type-coercion logic shared by all NIP-11 and NIP-66 data
classes. Each model declares a ``FieldSpec`` describing which fields should
be parsed as which types; ``parse_fields()`` then applies the spec to raw
dictionaries from external sources, silently dropping invalid values.

Supported field types: ``int``, ``bool``, ``str``, ``float``,
``list[int]``, ``list[str]``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """Declarative specification of expected field types for parsing.

    Each attribute is a frozenset of field names that should be parsed
    as the corresponding Python type. Fields not listed in any set are
    ignored during parsing.

    Attributes:
        int_fields: Fields expected as ``int`` (``bool`` excluded).
        bool_fields: Fields expected as ``bool``.
        str_fields: Fields expected as ``str``.
        str_list_fields: Fields expected as ``list[str]`` (invalid elements filtered).
        float_fields: Fields expected as ``float`` (``int`` accepted and converted).
        int_list_fields: Fields expected as ``list[int]`` (invalid elements filtered).
    """

    int_fields: frozenset[str] = field(default_factory=frozenset)
    bool_fields: frozenset[str] = field(default_factory=frozenset)
    str_fields: frozenset[str] = field(default_factory=frozenset)
    str_list_fields: frozenset[str] = field(default_factory=frozenset)
    float_fields: frozenset[str] = field(default_factory=frozenset)
    int_list_fields: frozenset[str] = field(default_factory=frozenset)


def parse_fields(data: dict[str, Any], spec: FieldSpec) -> dict[str, Any]:
    """Parse a dictionary according to a FieldSpec, dropping invalid values.

    Each key-value pair is checked against the field sets in *spec*.
    Values that do not match the expected type are silently excluded
    from the result. Keys not present in any field set are ignored.

    Type-specific behavior:

    * ``int_fields`` -- must be ``int`` and not ``bool`` (Python's ``bool``
      is a subclass of ``int``).
    * ``bool_fields`` -- must be ``bool``.
    * ``str_fields`` -- must be ``str``.
    * ``str_list_fields`` -- must be ``list``; non-string elements are filtered out.
    * ``float_fields`` -- accepts ``int`` or ``float`` (not ``bool``); converts to ``float``.
    * ``int_list_fields`` -- must be ``list``; non-int elements (and bools) are filtered out.

    Args:
        data: Raw dictionary to parse.
        spec: Field type specification.

    Returns:
        A new dictionary containing only valid, type-checked fields.
    """
    result: dict[str, Any] = {}

    for key, value in data.items():
        if key in spec.int_fields:
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
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                result[key] = float(value)

        elif key in spec.int_list_fields and isinstance(value, list):
            int_items = [i for i in value if isinstance(i, int) and not isinstance(i, bool)]
            if int_items:
                result[key] = int_items

    return result


__all__ = ["FieldSpec", "parse_fields"]
