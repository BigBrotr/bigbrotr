"""
Shared base classes for all NIP data, metadata, and log models.

Provides three Pydantic base classes that define the common interface
and behavior inherited by NIP-11 and NIP-66 model hierarchies:

    BaseData        Frozen model with declarative field parsing via ``FieldSpec``.
    BaseMetadata    Container pairing a data object with a logs object.
    BaseLogs        Operation log with success/reason semantic validation.
"""

from __future__ import annotations

from typing import Any, ClassVar, Self

from pydantic import BaseModel, ConfigDict, StrictBool, model_validator

from models.nips.parsing import FieldSpec, parse_fields


class BaseData(BaseModel):
    """Base class for NIP data models with declarative field parsing.

    Subclasses declare a ``_FIELD_SPEC`` class variable that maps field
    names to their expected types. The ``parse()`` class method uses this
    spec to coerce raw data into valid constructor arguments, silently
    dropping values that fail type checks.

    Subclasses may override ``parse()`` for custom logic (e.g., nested objects).
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
