"""
NIP-66 operation log models.

Defines log classes for each NIP-66 monitoring test. Most tests use the
standard ``BaseLogs`` success/reason pattern via ``Nip66BaseLogs``. The
RTT test uses a custom ``Nip66RttLogs`` class with three separate
success/reason pairs for the open, read, and write probe phases.
"""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, StrictBool, model_validator

from models.nips.base import BaseLogs


class Nip66RttLogs(BaseModel):
    """RTT probe results with multi-phase validation.

    Unlike other log models, RTT probes track three separate phases
    (open, read, write), each with its own success/reason pair.

    Validation rules:

    * ``open_success`` is mandatory; read and write are optional.
    * If ``open_success`` is False, read and write must also be False
      (cascading failure).
    * For each phase: ``success=True`` requires ``reason=None``;
      ``success=False`` requires a non-None ``reason`` string.
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
        """Enforce success/reason consistency and phase dependency constraints."""
        # Open phase
        if self.open_success and self.open_reason is not None:
            raise ValueError("open_reason must be None when open_success is True")
        if not self.open_success and self.open_reason is None:
            raise ValueError("open_reason is required when open_success is False")

        # Cascading failure: open failure implies read/write failure
        if not self.open_success:
            if self.read_success is not None and self.read_success:
                raise ValueError("read_success must be False when open_success is False")
            if self.write_success is not None and self.write_success:
                raise ValueError("write_success must be False when open_success is False")

        # Read phase (if present)
        if self.read_success is not None:
            if self.read_success and self.read_reason is not None:
                raise ValueError("read_reason must be None when read_success is True")
            if not self.read_success and self.read_reason is None:
                raise ValueError("read_reason is required when read_success is False")

        # Write phase (if present)
        if self.write_success is not None:
            if self.write_success and self.write_reason is not None:
                raise ValueError("write_reason must be None when write_success is True")
            if not self.write_success and self.write_reason is None:
                raise ValueError("write_reason is required when write_success is False")

        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create an instance from a dictionary with strict validation."""
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary, excluding fields with ``None`` values."""
        return self.model_dump(exclude_none=True)


class Nip66BaseLogs(BaseLogs):
    """Standard NIP-66 operation log with single success/reason pair.

    Inherits success/reason validation from ``BaseLogs``. Used as the
    base class for all non-RTT NIP-66 log models.
    """


class Nip66SslLogs(Nip66BaseLogs):
    """Log record for SSL/TLS certificate inspection."""


class Nip66GeoLogs(Nip66BaseLogs):
    """Log record for geolocation lookup."""


class Nip66NetLogs(Nip66BaseLogs):
    """Log record for network/ASN lookup."""


class Nip66DnsLogs(Nip66BaseLogs):
    """Log record for DNS resolution."""


class Nip66HttpLogs(Nip66BaseLogs):
    """Log record for HTTP header extraction."""
