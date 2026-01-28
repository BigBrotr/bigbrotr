"""Base classes shared across NIP models."""

from __future__ import annotations

from typing import Any, ClassVar, Final, Self

from pydantic import BaseModel, ConfigDict, StrictBool, model_validator

# Default timeout for network operations (NIP-11 fetch, NIP-66 tests)
DEFAULT_TIMEOUT: Final[float] = 10.0


class BaseData(BaseModel):
    """Base class for NIP data models with parsing capabilities.

    Subclasses define field type sets as class variables:
        - _INT_FIELDS: fields that should be int (not bool)
        - _BOOL_FIELDS: fields that should be bool
        - _STR_FIELDS: fields that should be str
        - _STR_LIST_FIELDS: fields that should be list[str]
        - _FLOAT_FIELDS: fields that should be float (accepts int, converts)
        - _INT_LIST_FIELDS: fields that should be list[int]

    The generic parse() method handles all these field types automatically.
    Subclasses can override parse() for custom parsing (e.g., nested objects).

    This class is inherited by:
        - Nip11FetchDataLimitation, Nip11FetchDataRetentionEntry, etc.
        - Nip66RttData, Nip66SslData, Nip66GeoData, etc.
    """

    model_config = ConfigDict(frozen=True)

    _INT_FIELDS: ClassVar[set[str]] = set()
    _BOOL_FIELDS: ClassVar[set[str]] = set()
    _STR_FIELDS: ClassVar[set[str]] = set()
    _STR_LIST_FIELDS: ClassVar[set[str]] = set()
    _FLOAT_FIELDS: ClassVar[set[str]] = set()
    _INT_LIST_FIELDS: ClassVar[set[str]] = set()

    @classmethod
    def parse(cls, data: Any) -> dict[str, Any]:
        """Parse arbitrary data into a valid dict for this model.

        Handles type coercion and validation based on _*_FIELDS class variables.
        Invalid values are silently dropped (not raised as errors).
        """
        if not isinstance(data, dict):
            return {}
        result: dict[str, Any] = {}
        for key, value in data.items():
            if key in cls._INT_FIELDS:
                if isinstance(value, int) and not isinstance(value, bool):
                    result[key] = value
            elif key in cls._BOOL_FIELDS:
                if isinstance(value, bool):
                    result[key] = value
            elif key in cls._STR_FIELDS:
                if isinstance(value, str):
                    result[key] = value
            elif key in cls._STR_LIST_FIELDS:
                if isinstance(value, list):
                    items = [s for s in value if isinstance(s, str)]
                    if items:
                        result[key] = items
            elif key in cls._FLOAT_FIELDS:
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    result[key] = float(value)
            elif key in cls._INT_LIST_FIELDS:
                if isinstance(value, list):
                    int_items = [i for i in value if isinstance(i, int) and not isinstance(i, bool)]
                    if int_items:
                        result[key] = int_items
        return result

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
