"""
Shared base classes for all NIP data, metadata, and log models.

Provides three Pydantic base classes that define the common interface
and behavior inherited by NIP-11 and NIP-66 model hierarchies:

    [BaseData][bigbrotr.nips.base.BaseData]
        Frozen model with declarative field parsing via
        [FieldSpec][bigbrotr.nips.parsing.FieldSpec].
    [BaseMetadata][bigbrotr.nips.base.BaseMetadata]
        Container pairing a data object with a logs object.
    [BaseLogs][bigbrotr.nips.base.BaseLogs]
        Operation log with success/reason semantic validation.

See Also:
    [bigbrotr.nips.parsing][bigbrotr.nips.parsing]: The declarative field
        parsing engine used by [BaseData][bigbrotr.nips.base.BaseData].
    [bigbrotr.nips.nip11][bigbrotr.nips.nip11]: NIP-11 models that extend
        these base classes.
    [bigbrotr.nips.nip66][bigbrotr.nips.nip66]: NIP-66 models that extend
        these base classes.
"""

from __future__ import annotations

from typing import Any, ClassVar, Self

from pydantic import BaseModel, ConfigDict, StrictBool, model_validator

from .parsing import FieldSpec, parse_fields


class BaseData(BaseModel):
    """Base class for NIP data models with declarative field parsing.

    Subclasses declare a ``_FIELD_SPEC`` class variable (a
    [FieldSpec][bigbrotr.nips.parsing.FieldSpec]) that maps field names to
    their expected types. The ``parse()`` class method uses this spec to
    coerce raw data into valid constructor arguments, silently dropping
    values that fail type checks.

    Subclasses may override ``parse()`` for custom logic (e.g., nested objects).

    Note:
        All ``BaseData`` subclasses use ``frozen=True`` to ensure immutability
        after construction. This matches the project-wide convention for
        dataclass and Pydantic models.

    See Also:
        [FieldSpec][bigbrotr.nips.parsing.FieldSpec]: Declarative type
            specification consumed by ``parse()``.
        [parse_fields][bigbrotr.nips.parsing.parse_fields]: The underlying
            parsing engine.
    """

    model_config = ConfigDict(frozen=True)

    _FIELD_SPEC: ClassVar[FieldSpec] = FieldSpec()

    @classmethod
    def parse(cls, data: Any) -> dict[str, Any]:
        """Parse arbitrary data into validated constructor arguments.

        Invalid or unrecognized values are silently dropped rather than
        raising errors, making this safe for untrusted relay responses.

        Args:
            data: Raw dictionary from an external source.

        Returns:
            A cleaned dictionary containing only valid fields.
        """
        if not isinstance(data, dict):
            return {}
        return parse_fields(data, cls._FIELD_SPEC)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create an instance from a dictionary with strict validation."""
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary, excluding fields with ``None`` values."""
        return self.model_dump(exclude_none=True)


class BaseMetadata(BaseModel):
    """Base class for metadata containers that pair data with operation logs.

    Provides standard ``from_dict()`` and ``to_dict()`` methods. The
    ``to_dict()`` implementation automatically delegates to nested
    objects that define their own ``to_dict()`` method, so subclasses
    do not need to override it.

    Note:
        Subclasses are expected to declare exactly two fields: ``data``
        (a [BaseData][bigbrotr.nips.base.BaseData] subclass) and ``logs``
        (a [BaseLogs][bigbrotr.nips.base.BaseLogs] subclass). The
        ``to_dict()`` method iterates all model fields and delegates
        serialization to nested objects automatically.

    See Also:
        [bigbrotr.nips.nip11.info.Nip11InfoMetadata][bigbrotr.nips.nip11.info.Nip11InfoMetadata]:
            NIP-11 metadata container with HTTP info retrieval capabilities.
        [bigbrotr.nips.nip66.rtt.Nip66RttMetadata][bigbrotr.nips.nip66.rtt.Nip66RttMetadata]:
            NIP-66 RTT metadata container with relay probe capabilities.
    """

    model_config = ConfigDict(frozen=True)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Self:
        """Create an instance from a dictionary with strict validation."""
        return cls.model_validate(raw)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary, delegating to nested ``to_dict()`` methods.

        Iterates over model fields and calls ``to_dict()`` on any nested
        object that supports it (e.g., data and logs sub-models).
        ``None`` values are excluded.

        Returns:
            A dictionary suitable for JSON serialization or database storage.
        """
        result: dict[str, Any] = {}
        for key in type(self).model_fields:
            value = getattr(self, key)
            if value is None:
                continue
            if hasattr(value, "to_dict"):
                result[key] = value.to_dict()
            else:
                result[key] = value
        return result


class BaseLogs(BaseModel):
    """Base class for operation logs with success/reason validation.

    Enforces semantic consistency between the ``success`` flag and the
    ``reason`` message:

    * When ``success=True``, ``reason`` must be ``None``.
    * When ``success=False``, ``reason`` is required (non-None string).

    See Also:
        [bigbrotr.nips.nip11.logs.Nip11InfoLogs][bigbrotr.nips.nip11.logs.Nip11InfoLogs]:
            NIP-11 info log subclass.
        [bigbrotr.nips.nip66.logs.Nip66BaseLogs][bigbrotr.nips.nip66.logs.Nip66BaseLogs]:
            NIP-66 standard log subclass.
        [bigbrotr.nips.nip66.logs.Nip66RttMultiPhaseLogs][bigbrotr.nips.nip66.logs.Nip66RttMultiPhaseLogs]:
            Multi-phase RTT log (does not inherit from ``BaseLogs``).
    """

    model_config = ConfigDict(frozen=True)

    success: StrictBool
    reason: str | None = None

    @model_validator(mode="after")
    def validate_semantic(self) -> Self:
        """Enforce success/reason consistency."""
        if self.success and self.reason is not None:
            raise ValueError("reason must be None when success is True")
        if not self.success and self.reason is None:
            raise ValueError("reason is required when success is False")
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create an instance from a dictionary with strict validation."""
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary, excluding fields with ``None`` values."""
        return self.model_dump(exclude_none=True)
