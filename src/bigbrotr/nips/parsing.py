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

import functools
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
class ParseIssue:
    """Single parsing issue recorded while sanitizing untrusted NIP data."""

    kind: str
    path: str
    detail: str


@dataclass(frozen=True, slots=True)
class ParseReport:
    """Structured result of a permissive parse operation."""

    parsed: dict[str, Any]
    issues: tuple[ParseIssue, ...] = ()

    @property
    def has_issues(self) -> bool:
        """Whether the parse operation dropped or ignored any data."""
        return bool(self.issues)

    def summary(self, limit: int = 5) -> str:
        """Return a compact, human-readable summary of parse issues."""
        if not self.issues:
            return "none"

        visible = [f"{issue.kind}@{issue.path}" for issue in self.issues[:limit]]
        remaining = len(self.issues) - len(visible)
        if remaining > 0:
            visible.append(f"+{remaining} more")
        return ", ".join(visible)


@dataclass(frozen=True, slots=True)
class _FieldParser:
    label: str
    parser: Callable[[Any], Any]
    is_list: bool = False


def join_parse_path(base: str, segment: str) -> str:
    """Join parse path fragments using dotted notation plus list indices."""
    if not base:
        return segment
    if segment.startswith("["):
        return f"{base}{segment}"
    return f"{base}.{segment}"


def _invalid_value_issue(path: str, detail: str) -> ParseIssue:
    return ParseIssue(kind="invalid_value", path=path, detail=detail)


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


@functools.lru_cache(maxsize=8)
def _build_dispatch(spec: FieldSpec) -> dict[str, _FieldParser]:
    dispatch: dict[str, _FieldParser] = {}
    for attr_name, parser in _FIELD_PARSERS:
        label = attr_name.removesuffix("_fields").replace("_", "")
        if attr_name == "str_list_fields":
            label = "list[str]"
        elif attr_name == "int_list_fields":
            label = "list[int]"
        elif attr_name == "float_fields":
            label = "float"
        elif attr_name == "bool_fields":
            label = "bool"
        elif attr_name == "int_fields":
            label = "int"
        elif attr_name == "str_fields":
            label = "str"

        field_parser = _FieldParser(
            label=label,
            parser=parser,
            is_list=attr_name in {"str_list_fields", "int_list_fields"},
        )
        for name in getattr(spec, attr_name):
            dispatch[name] = field_parser
    return dispatch


def parse_fields_report(
    data: dict[str, Any],
    spec: FieldSpec,
    *,
    path: str = "",
    extra_known_fields: frozenset[str] = frozenset(),
) -> ParseReport:
    """Parse a dictionary according to a ``FieldSpec`` and record dropped data."""
    dispatch = _build_dispatch(spec)

    result: dict[str, Any] = {}
    issues: list[ParseIssue] = []

    for key, value in data.items():
        field_path = join_parse_path(path, key)
        handler = dispatch.get(key)
        if handler is None:
            if key not in extra_known_fields:
                issues.append(
                    ParseIssue(
                        kind="unknown_field",
                        path=field_path,
                        detail="field not declared in parsing spec",
                    )
                )
            continue

        parsed = handler.parser(value)
        if parsed is _SKIP:
            issues.append(_invalid_value_issue(field_path, f"expected {handler.label}"))
            continue

        result[key] = parsed
        if handler.is_list and isinstance(value, list) and len(parsed) != len(value):
            dropped = len(value) - len(parsed)
            issues.append(
                ParseIssue(
                    kind="filtered_items",
                    path=field_path,
                    detail=f"filtered {dropped} invalid item(s)",
                )
            )

    return ParseReport(parsed=result, issues=tuple(issues))


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
    return parse_fields_report(data, spec).parsed


__all__ = [
    "FieldSpec",
    "ParseIssue",
    "ParseReport",
    "join_parse_path",
    "parse_fields",
    "parse_fields_report",
]
