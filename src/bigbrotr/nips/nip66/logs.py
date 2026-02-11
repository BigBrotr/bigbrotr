"""
NIP-66 operation log models.

Defines log classes for each
[NIP-66](https://github.com/nostr-protocol/nips/blob/master/66.md) monitoring
test. Most tests use the standard
[BaseLogs][bigbrotr.nips.base.BaseLogs] success/reason pattern via
[Nip66BaseLogs][bigbrotr.nips.nip66.logs.Nip66BaseLogs]. The RTT test uses
a custom [Nip66RttMultiPhaseLogs][bigbrotr.nips.nip66.logs.Nip66RttMultiPhaseLogs]
class with three separate success/reason pairs for the open, read, and
write probe phases.

See Also:
    [bigbrotr.nips.base.BaseLogs][bigbrotr.nips.base.BaseLogs]: Base class
        with success/reason semantic validation.
    [bigbrotr.nips.nip66.data][bigbrotr.nips.nip66.data]: Corresponding data
        models for each test type.
"""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, StrictBool, model_validator

from bigbrotr.nips.base import BaseLogs


class Nip66RttMultiPhaseLogs(BaseModel):
    """RTT probe results with multi-phase validation.

    Unlike other log models, RTT probes track three separate phases
    (open, read, write), each with its own success/reason pair.

    The ``open_success`` field is mandatory; read and write are optional.
    If ``open_success`` is ``False``, read and write must also be ``False``
    (cascading failure). For each phase, ``success=True`` requires
    ``reason=None``; ``success=False`` requires a non-None ``reason`` string.

    Note:
        This class does **not** inherit from
        [BaseLogs][bigbrotr.nips.base.BaseLogs] because the multi-phase
        structure requires a different validation model. The cascading
        failure constraint ensures that if the connection cannot be opened,
        read and write phases are automatically marked as failed.

    See Also:
        [bigbrotr.nips.nip66.rtt.Nip66RttMetadata][bigbrotr.nips.nip66.rtt.Nip66RttMetadata]:
            Container that pairs these logs with
            [Nip66RttData][bigbrotr.nips.nip66.data.Nip66RttData].
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

    Inherits success/reason validation from
    [BaseLogs][bigbrotr.nips.base.BaseLogs]. Used as the base class for
    all non-RTT NIP-66 log models.

    See Also:
        [Nip66RttMultiPhaseLogs][bigbrotr.nips.nip66.logs.Nip66RttMultiPhaseLogs]:
            The multi-phase alternative used by RTT probes.
    """


class Nip66SslLogs(Nip66BaseLogs):
    """Log record for SSL/TLS certificate inspection.

    See Also:
        [bigbrotr.nips.nip66.ssl.Nip66SslMetadata][bigbrotr.nips.nip66.ssl.Nip66SslMetadata]:
            Container that pairs this log with
            [Nip66SslData][bigbrotr.nips.nip66.data.Nip66SslData].
    """


class Nip66GeoLogs(Nip66BaseLogs):
    """Log record for geolocation lookup.

    See Also:
        [bigbrotr.nips.nip66.geo.Nip66GeoMetadata][bigbrotr.nips.nip66.geo.Nip66GeoMetadata]:
            Container that pairs this log with
            [Nip66GeoData][bigbrotr.nips.nip66.data.Nip66GeoData].
    """


class Nip66NetLogs(Nip66BaseLogs):
    """Log record for network/ASN lookup.

    See Also:
        [bigbrotr.nips.nip66.net.Nip66NetMetadata][bigbrotr.nips.nip66.net.Nip66NetMetadata]:
            Container that pairs this log with
            [Nip66NetData][bigbrotr.nips.nip66.data.Nip66NetData].
    """


class Nip66DnsLogs(Nip66BaseLogs):
    """Log record for DNS resolution.

    See Also:
        [bigbrotr.nips.nip66.dns.Nip66DnsMetadata][bigbrotr.nips.nip66.dns.Nip66DnsMetadata]:
            Container that pairs this log with
            [Nip66DnsData][bigbrotr.nips.nip66.data.Nip66DnsData].
    """


class Nip66HttpLogs(Nip66BaseLogs):
    """Log record for HTTP header extraction.

    See Also:
        [bigbrotr.nips.nip66.http.Nip66HttpMetadata][bigbrotr.nips.nip66.http.Nip66HttpMetadata]:
            Container that pairs this log with
            [Nip66HttpData][bigbrotr.nips.nip66.data.Nip66HttpData].
    """
