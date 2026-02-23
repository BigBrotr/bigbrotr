"""
Declarative field parsing for NIP data models.

Centralizes the type-coercion logic shared by all NIP-11 and NIP-66 data
classes. Each model declares a [FieldSpec][bigbrotr.nips.parsing.FieldSpec]
describing which fields should be parsed as which types;
[parse_fields][bigbrotr.nips.parsing.parse_fields] then applies the spec
to raw dictionaries from external sources, silently dropping invalid values.

Supported field types: ``int``, ``bool``, ``str``, ``float``,
``list[int]``, ``list[str]``.

Note:
    This module is intentionally defensive: no exceptions are raised for
    invalid data. Values that fail type checks are silently excluded from
    the result dictionary. This design is critical for handling untrusted
    relay responses that may contain arbitrary or malformed JSON.

See Also:
    [bigbrotr.nips.base.BaseData][bigbrotr.nips.base.BaseData]: Base class
        that uses ``FieldSpec`` and ``parse_fields`` for declarative parsing.
    [bigbrotr.nips.nip11.data][bigbrotr.nips.nip11.data]: NIP-11 data models
        that declare their own ``_FIELD_SPEC``.
    [bigbrotr.nips.nip66.data][bigbrotr.nips.nip66.data]: NIP-66 data models
        that declare their own ``_FIELD_SPEC``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from collections.abc import Callable


_SKIP: Any = object()


def _parse_int(value: Any) -> Any:
    return value if isinstance(value, int) and not isinstance(value, bool) else _SKIP


def _parse_bool(value: Any) -> Any:
    return value if isinstance(value, bool) else _SKIP


def _parse_str(value: Any) -> Any:
    return value if isinstance(value, str) else _SKIP


def _parse_float(value: Any) -> Any:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return _SKIP


def _parse_str_list(value: Any) -> Any:
    if isinstance(value, list):
        items = [s for s in value if isinstance(s, str)]
        if items:
            return items
    return _SKIP


def _parse_int_list(value: Any) -> Any:
    if isinstance(value, list):
        items = [i for i in value if isinstance(i, int) and not isinstance(i, bool)]
        if items:
            return items
    return _SKIP


_FIELD_PARSERS: tuple[tuple[str, Callable[[Any], Any]], ...] = (
    ("int_fields", _parse_int),
    ("bool_fields", _parse_bool),
    ("str_fields", _parse_str),
    ("str_list_fields", _parse_str_list),
    ("float_fields", _parse_float),
    ("int_list_fields", _parse_int_list),
)


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

    Note:
        Python's ``bool`` is a subclass of ``int``, so ``int_fields`` parsing
        explicitly excludes ``bool`` values to prevent ``True``/``False``
        from being accepted as integers.

    See Also:
        [parse_fields][bigbrotr.nips.parsing.parse_fields]: The function that
            applies this spec to raw data dictionaries.
    """

    int_fields: frozenset[str] = field(default_factory=frozenset)
    bool_fields: frozenset[str] = field(default_factory=frozenset)
    str_fields: frozenset[str] = field(default_factory=frozenset)
    str_list_fields: frozenset[str] = field(default_factory=frozenset)
    float_fields: frozenset[str] = field(default_factory=frozenset)
    int_list_fields: frozenset[str] = field(default_factory=frozenset)


def parse_fields(data: dict[str, Any], spec: FieldSpec) -> dict[str, Any]:
    """Parse a dictionary according to a ``FieldSpec``, dropping invalid values.

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
        spec: [FieldSpec][bigbrotr.nips.parsing.FieldSpec] type specification.

    Returns:
        A new dictionary containing only valid, type-checked fields.

    See Also:
        [bigbrotr.nips.base.BaseData.parse][bigbrotr.nips.base.BaseData.parse]:
            Class method that delegates to this function.
    """
    dispatch: dict[str, Callable[[Any], Any]] = {}
    for attr_name, parser in _FIELD_PARSERS:
        for name in getattr(spec, attr_name):
            dispatch[name] = parser

    result: dict[str, Any] = {}
    for key, value in data.items():
        handler = dispatch.get(key)
        if handler is not None:
            parsed = handler(value)
            if parsed is not _SKIP:
                result[key] = parsed

    return result


__all__ = ["FieldSpec", "parse_fields"]
