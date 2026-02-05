"""Base classes shared across NIP models."""

from __future__ import annotations

from typing import Any, ClassVar, Final, Self

from pydantic import BaseModel, ConfigDict, StrictBool, model_validator

from models.nips.parsing import FieldSpec, parse_fields


# Default timeout for network operations (NIP-11 fetch, NIP-66 tests)
DEFAULT_TIMEOUT: Final[float] = 10.0


class BaseData(BaseModel):
    """Base class for NIP data models with parsing capabilities.

    Subclasses define field types via _FIELD_SPEC class variable:
        - int_fields: fields that should be int (not bool)
        - bool_fields: fields that should be bool
        - str_fields: fields that should be str
        - str_list_fields: fields that should be list[str]
        - float_fields: fields that should be float (accepts int, converts)
        - int_list_fields: fields that should be list[int]

    The generic parse() method handles all these field types automatically.
    Subclasses can override parse() for custom parsing (e.g., nested objects).

    This class is inherited by:
        - Nip11Data, Nip11DataLimitation, Nip11DataRetentionEntry, etc.
        - Nip66RttData, Nip66SslData, Nip66GeoData, etc.
    """

    model_config = ConfigDict(frozen=True)

    # Subclasses define this to specify field types for parsing
    _FIELD_SPEC: ClassVar[FieldSpec] = FieldSpec()

    @classmethod
    def parse(cls, data: Any) -> dict[str, Any]:
        """Parse arbitrary data into a valid dict for this model.

        Handles type coercion and validation based on _FIELD_SPEC.
        Invalid values are silently dropped (not raised as errors).
        """
        if not isinstance(data, dict):
            return {}
        return parse_fields(data, cls._FIELD_SPEC)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create from dict with strict validation."""
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization, excluding None values."""
        return self.model_dump(exclude_none=True)


class BaseMetadata(BaseModel):
    """Base class for metadata containers (data + logs pairs).

    Provides standard from_dict() and to_dict() methods for containers
    that hold a data object and a logs object.

    The to_dict() method automatically detects nested objects with to_dict()
    methods and calls them for proper serialization. This eliminates the need
    for subclasses to override to_dict().

    This class is inherited by:
        - Nip11FetchMetadata
        - Nip66RttMetadata, Nip66SslMetadata, Nip66GeoMetadata, etc.
    """

    model_config = ConfigDict(frozen=True)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Self:
        """Create from dict with strict validation."""
        return cls.model_validate(raw)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict, calling nested to_dict() methods.

        Iterates over model fields and:
        - Calls to_dict() on objects that have it (data, logs)
        - Excludes None values
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
    """Base class for operation logs with success/reason semantic validation.

    Validation rules:
        - If success=True, reason must be None
        - If success=False, reason is required (non-None string)

    This class is inherited by:
        - Nip11FetchLogs
        - Nip66BaseLogs (and its subclasses: Nip66SslLogs, Nip66GeoLogs, etc.)
    """

    model_config = ConfigDict(frozen=True)

    success: StrictBool
    reason: str | None = None

    @model_validator(mode="after")
    def validate_semantic(self) -> Self:
        """Validate success/reason consistency."""
        if self.success and self.reason is not None:
            raise ValueError("reason must be None when success is True")
        if not self.success and self.reason is None:
            raise ValueError("reason is required when success is False")
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create from dict with strict validation."""
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization, excluding None values."""
        return self.model_dump(exclude_none=True)
