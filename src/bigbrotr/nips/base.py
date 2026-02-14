"""
Shared base classes for all NIP data, metadata, log, and top-level models.

Provides Pydantic base classes that define the common interface and behavior
inherited by NIP-11 and NIP-66 model hierarchies:

    [BaseData][bigbrotr.nips.base.BaseData]
        Frozen model with declarative field parsing via
        [FieldSpec][bigbrotr.nips.parsing.FieldSpec].
    [BaseMetadata][bigbrotr.nips.base.BaseMetadata]
        Container pairing a data object with a logs object.
    [BaseLogs][bigbrotr.nips.base.BaseLogs]
        Operation log with success/reason semantic validation.
    [BaseNip][bigbrotr.nips.base.BaseNip]
        Abstract top-level NIP model with relay, generated_at, and
        enforced ``create()`` / ``to_relay_metadata_tuple()`` contract.
    [BaseNipSelection][bigbrotr.nips.base.BaseNipSelection]
        Base for selection models controlling which metadata types
        to retrieve.
    [BaseNipOptions][bigbrotr.nips.base.BaseNipOptions]
        Base for options models controlling how metadata is retrieved.

See Also:
    [bigbrotr.nips.parsing][bigbrotr.nips.parsing]: The declarative field
        parsing engine used by [BaseData][bigbrotr.nips.base.BaseData].
    [bigbrotr.nips.nip11][bigbrotr.nips.nip11]: NIP-11 models that extend
        these base classes.
    [bigbrotr.nips.nip66][bigbrotr.nips.nip66]: NIP-66 models that extend
        these base classes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from time import time
from typing import Any, ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from bigbrotr.models.relay import Relay  # noqa: TC001

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


# =============================================================================
# Top-level NIP Base Classes
# =============================================================================


class BaseNipSelection(BaseModel):
    """Which metadata types to retrieve during a NIP operation.

    Subclasses define boolean fields for each metadata type supported
    by the NIP. All fields should default to ``True`` (all enabled).

    See Also:
        [BaseNipOptions][bigbrotr.nips.base.BaseNipOptions]:
            Controls *how* metadata is retrieved.
        [bigbrotr.nips.nip11.nip11.Nip11Selection][bigbrotr.nips.nip11.nip11.Nip11Selection]:
            NIP-11 selection (``info`` field).
        [bigbrotr.nips.nip66.nip66.Nip66Selection][bigbrotr.nips.nip66.nip66.Nip66Selection]:
            NIP-66 selection (``rtt``, ``ssl``, ``geo``, ``net``, ``dns``, ``http``).
    """


class BaseNipOptions(BaseModel):
    """How to execute NIP metadata retrieval.

    Provides the common ``allow_insecure`` option inherited by all
    NIP option models. Subclasses add NIP-specific options
    (e.g., ``max_size`` for NIP-11).

    Attributes:
        allow_insecure: Fall back to unverified SSL for clearnet relays
            with invalid certificates (default: ``False``).

    See Also:
        [BaseNipSelection][bigbrotr.nips.base.BaseNipSelection]:
            Controls *which* metadata is retrieved.
        [bigbrotr.nips.nip11.nip11.Nip11Options][bigbrotr.nips.nip11.nip11.Nip11Options]:
            NIP-11 options (adds ``max_size``).
        [bigbrotr.nips.nip66.nip66.Nip66Options][bigbrotr.nips.nip66.nip66.Nip66Options]:
            NIP-66 options (inherits only ``allow_insecure``).
    """

    allow_insecure: bool = False


class BaseNip(BaseModel, ABC):
    """Abstract base class for top-level NIP models.

    Provides the common ``relay`` and ``generated_at`` fields shared by
    all NIP implementations, and enforces the factory/serialization
    contract via abstract methods.

    Subclasses must implement:

    * ``to_relay_metadata_tuple()`` — converts results to database-ready
      [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata] records.
    * ``create()`` — async factory that performs I/O and returns a populated
      instance. Must **never raise exceptions** — errors are captured in
      the ``logs.success`` / ``logs.reason`` fields of each metadata container.

    Note:
        ``BaseNip`` cannot be instantiated directly due to the ABC constraint.
        Only concrete subclasses with all abstract methods implemented can be
        created.

    See Also:
        [bigbrotr.nips.nip11.nip11.Nip11][bigbrotr.nips.nip11.nip11.Nip11]:
            NIP-11 implementation.
        [bigbrotr.nips.nip66.nip66.Nip66][bigbrotr.nips.nip66.nip66.Nip66]:
            NIP-66 implementation.
        [BaseNipSelection][bigbrotr.nips.base.BaseNipSelection]:
            Selection model base controlling which metadata types to retrieve.
        [BaseNipOptions][bigbrotr.nips.base.BaseNipOptions]:
            Options model base controlling how metadata is retrieved.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    relay: Relay
    generated_at: StrictInt = Field(default_factory=lambda: int(time()), ge=0)

    @abstractmethod
    def to_relay_metadata_tuple(self) -> tuple[Any, ...]:
        """Convert to a database-ready tuple of RelayMetadata records."""
        ...

    @classmethod
    @abstractmethod
    async def create(cls, relay: Relay, **kwargs: Any) -> Self:
        """Async factory method. Never raises — check logs.success."""
        ...
