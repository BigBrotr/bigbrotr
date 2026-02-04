"""NIP-66 logs models."""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, StrictBool, model_validator

from models.nips.base import BaseLogs


class Nip66RttLogs(BaseModel):
    """RTT probe results with multi-step validation.

    NOTE: This class does NOT inherit from BaseLogs because RTT probes
    have three separate success/reason pairs (open, read, write) instead
    of the single success/reason pair defined in BaseLogs.

    Validation rules:
        - open_success is required (mandatory field)
        - If open_success is False, read_success and write_success must also be False
        - For each success/reason pair: if success=True, reason=None; if success=False, reason required
    """

    model_config = ConfigDict(frozen=True)

    open_success: StrictBool
    open_reason: str | None = None
    read_success: StrictBool | None = None
    read_reason: str | None = None
    write_success: StrictBool | None = None
    write_reason: str | None = None

    @model_validator(mode="after")
    def validate_semantic(self) -> Self:
        """Validate success/reason consistency and dependency constraints."""
        # Open: success/reason constraint
        if self.open_success and self.open_reason is not None:
            raise ValueError("open_reason must be None when open_success is True")
        if not self.open_success and self.open_reason is None:
            raise ValueError("open_reason is required when open_success is False")

        # If open failed, read and write must also be False
        if not self.open_success:
            if self.read_success is not None and self.read_success:
                raise ValueError("read_success must be False when open_success is False")
            if self.write_success is not None and self.write_success:
                raise ValueError("write_success must be False when open_success is False")

        # Read: success/reason constraint (if present)
        if self.read_success is not None:
            if self.read_success and self.read_reason is not None:
                raise ValueError("read_reason must be None when read_success is True")
            if not self.read_success and self.read_reason is None:
                raise ValueError("read_reason is required when read_success is False")

        # Write: success/reason constraint (if present)
        if self.write_success is not None:
            if self.write_success and self.write_reason is not None:
                raise ValueError("write_reason must be None when write_success is True")
            if not self.write_success and self.write_reason is None:
                raise ValueError("write_reason is required when write_success is False")

        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create from dict with strict validation."""
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization, excluding None values."""
        return self.model_dump(exclude_none=True)


class Nip66BaseLogs(BaseLogs):
    """Base class for standard NIP-66 operation logs.

    Inherits from BaseLogs:
        - success: StrictBool (required)
        - reason: None when success=True, str when success=False
        - from_dict() and to_dict() methods
    """


class Nip66SslLogs(Nip66BaseLogs):
    """SSL test operation logs."""


class Nip66GeoLogs(Nip66BaseLogs):
    """Geo lookup operation logs."""


class Nip66NetLogs(Nip66BaseLogs):
    """Net lookup operation logs."""


class Nip66DnsLogs(Nip66BaseLogs):
    """DNS resolve operation logs."""


class Nip66HttpLogs(Nip66BaseLogs):
    """HTTP check operation logs."""
