"""Finder service configuration models.

See Also:
    [Finder][bigbrotr.services.finder.Finder]: The service class
        that consumes these configurations.
    [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
        Base class providing ``interval`` and ``log_level`` fields.
"""

from __future__ import annotations

from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

import jmespath
from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from bigbrotr.core.base_service import BaseServiceConfig


def _reject_bool_alias(value: Any, field_name: str, expected: str) -> Any:
    """Reject boolean aliases for numeric finder config fields."""
    if isinstance(value, bool):
        raise ValueError(f"{field_name}: expected {expected}, got bool")
    return value


def _require_bool(value: Any, field_name: str) -> bool:
    """Require canonical booleans for authored finder config boundaries."""
    if not isinstance(value, bool):
        raise ValueError(f"{field_name}: expected bool, got {type(value).__name__}")
    return value


def _require_int(value: Any, field_name: str) -> int:
    """Require canonical integers for authored finder config boundaries."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name}: expected integer, got {type(value).__name__}")
    return int(value)


def _require_number(value: Any, field_name: str) -> int | float:
    """Require canonical numeric types for authored finder config boundaries."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name}: expected number, got {type(value).__name__}")
    return cast("int | float", value)


def _normalize_non_blank_string(value: Any, field_name: str) -> str:
    """Normalize authored string config values that must not be blank."""
    if not isinstance(value, str):
        raise ValueError(f"{field_name}: expected string, got {type(value).__name__}")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _normalize_api_source_url(value: str) -> str:
    """Canonicalize authored HTTP(S) source URLs for checkpointing and dedupe."""
    normalized = value.strip()
    if not normalized:
        raise ValueError("url must not be blank")

    parsed = urlsplit(normalized)
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname
    if scheme not in {"http", "https"} or not parsed.netloc or hostname is None:
        raise ValueError("url must be an absolute http(s) URL")
    default_port = 80 if scheme == "http" else 443

    canonical_host = hostname.lower()
    if ":" in canonical_host and not canonical_host.startswith("["):
        canonical_host = f"[{canonical_host}]"

    netloc = canonical_host
    if parsed.port is not None and parsed.port != default_port:
        netloc = f"{netloc}:{parsed.port}"

    if parsed.username is not None:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo = f"{userinfo}:{parsed.password}"
        netloc = f"{userinfo}@{netloc}"

    return urlunsplit((scheme, netloc, parsed.path, parsed.query, ""))


class EventsConfig(BaseModel):
    """Event scanning configuration for discovering relay URLs from stored events.

    Scans all events per relay (cursor-paginated by ``observed_at``) and extracts
    relay URLs from ``tagvalues``. Any tagvalue that parses as a valid relay
    URL becomes a validation candidate.

    See Also:
        [scan_event_observation][bigbrotr.services.finder.queries.scan_event_observation]:
            The SQL query driven by ``batch_size``.
        [FinderConfig][bigbrotr.services.finder.FinderConfig]: Parent
            config that embeds this model.
    """

    enabled: bool = Field(default=True, description="Enable event scanning")
    scan_size: int = Field(default=500, ge=10, le=10_000, description="Rows per paginated DB query")
    batch_size: int = Field(
        default=500, ge=10, le=10_000, description="Discovered relays to buffer before flushing"
    )
    parallel_relays: int = Field(
        default=60, ge=1, le=200, description="Maximum concurrent relay event scans"
    )
    max_relay_time: float = Field(
        default=900.0,
        ge=10.0,
        le=86_400.0,
        description="Maximum seconds to scan a single relay",
    )
    max_duration: float = Field(
        default=7200.0,
        ge=60.0,
        le=86_400.0,
        description="Maximum seconds for the entire event scanning phase",
    )

    @field_validator("scan_size", "batch_size", "parallel_relays", mode="before")
    @classmethod
    def require_integer_scan_controls(cls, v: Any, info: ValidationInfo) -> int:
        """Require canonical integers for paging, buffering, and concurrency controls."""
        field_name = info.field_name or "parallel_relays"
        return _require_int(v, field_name)

    @field_validator("enabled", mode="before")
    @classmethod
    def require_boolean_enabled(cls, v: Any, info: ValidationInfo) -> bool:
        """Require canonical booleans for phase enablement."""
        field_name = info.field_name or "enabled"
        return _require_bool(v, field_name)

    @field_validator("max_relay_time", "max_duration", mode="before")
    @classmethod
    def require_numeric_phase_budgets(cls, v: Any, info: ValidationInfo) -> int | float:
        """Require canonical numeric types for event-scan time budgets."""
        field_name = info.field_name or "value"
        return _require_number(v, field_name)


class ApiSourceConfig(BaseModel):
    """Single API source configuration.

    The ``expression`` field declares how relay URL strings are extracted from
    the JSON response.  It accepts any valid
    `JMESPath <https://jmespath.org/>`_ expression.  The default ``[*]``
    assumes the response is a flat JSON array of URL strings.

    Examples of common expressions::

        [*]                   -- flat list of strings (default)
        data.relays           -- nested path to a list
        data.relays[*].url    -- list of objects, extract "url" field
        keys(@)               -- dict keys are the URLs

    See Also:
        [extract_relays_from_response][bigbrotr.services.finder.utils.extract_relays_from_response]:
            The extraction function driven by this field.
    """

    url: str = Field(description="API endpoint URL")
    enabled: bool = Field(default=True, description="Enable this source")
    timeout: float = Field(default=30.0, ge=0.1, le=120.0, description="Request timeout")
    connect_timeout: float = Field(
        default=10.0,
        ge=0.1,
        le=60.0,
        description="HTTP connection timeout (capped to total timeout)",
    )
    expression: str = Field(
        description="JMESPath expression to extract URL strings from the JSON response"
    )
    allow_insecure: bool = Field(
        default=False,
        description="Allow insecure connections without TLS certificate verification",
    )

    @field_validator("timeout", "connect_timeout", mode="before")
    @classmethod
    def require_numeric_timeout_controls(cls, v: Any, info: ValidationInfo) -> int | float:
        """Require canonical numeric types for HTTP timeout controls."""
        field_name = info.field_name or "value"
        return _require_number(v, field_name)

    @field_validator("enabled", "allow_insecure", mode="before")
    @classmethod
    def require_boolean_flags(cls, v: Any, info: ValidationInfo) -> bool:
        """Require canonical booleans for source enablement and TLS policy."""
        field_name = info.field_name or "value"
        return _require_bool(v, field_name)

    @model_validator(mode="after")
    def _validate_connect_timeout(self) -> ApiSourceConfig:
        if self.connect_timeout > self.timeout:
            raise ValueError(
                f"connect_timeout ({self.connect_timeout}) must not exceed timeout ({self.timeout})"
            )
        return self

    @field_validator("expression")
    @classmethod
    def _validate_expression(cls, v: str) -> str:
        normalized = _normalize_non_blank_string(v, "expression")
        try:
            jmespath.compile(normalized)
        except jmespath.exceptions.ParseError as e:
            msg = f"invalid JMESPath expression: {e}"
            raise ValueError(msg) from e
        return normalized

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        return _normalize_api_source_url(v)


class ApiConfig(BaseModel):
    """API fetching configuration -- discovers relay URLs from public APIs.

    See Also:
        [ApiSourceConfig][bigbrotr.services.finder.ApiSourceConfig]:
            Per-source URL, timeout, and enablement settings.
        [FinderConfig][bigbrotr.services.finder.FinderConfig]: Parent
            config that embeds this model.
    """

    enabled: bool = Field(default=True, description="Enable API fetching")
    cooldown: float = Field(
        default=86400.0,
        ge=1.0,
        le=604_800.0,
        description="Minimum seconds to wait before querying any source again",
    )
    sources: list[ApiSourceConfig] = Field(
        default_factory=lambda: [
            ApiSourceConfig(url="https://api.nostr.watch/v1/online", expression="[*]"),
            ApiSourceConfig(url="https://api.nostr.watch/v1/offline", expression="[*]"),
        ],
        description="List of API endpoint configurations",
    )
    request_delay: float = Field(
        default=1.0, ge=0.0, le=10.0, description="Delay between API requests"
    )
    max_response_size: int = Field(
        default=5_242_880,
        ge=1024,
        le=52_428_800,
        description="Maximum API response body size in bytes (default: 5 MB)",
    )

    @field_validator("cooldown", "request_delay", mode="before")
    @classmethod
    def require_numeric_pacing_controls(cls, v: Any, info: ValidationInfo) -> int | float:
        """Require canonical numeric types for API pacing controls."""
        field_name = info.field_name or "value"
        return _require_number(v, field_name)

    @field_validator("max_response_size", mode="before")
    @classmethod
    def require_integer_max_response_size(cls, v: Any, info: ValidationInfo) -> int:
        """Require canonical integers for API response-size budgets."""
        field_name = info.field_name or "max_response_size"
        return _require_int(v, field_name)

    @field_validator("enabled", mode="before")
    @classmethod
    def require_boolean_enabled(cls, v: Any, info: ValidationInfo) -> bool:
        """Require canonical booleans for phase enablement."""
        field_name = info.field_name or "enabled"
        return _require_bool(v, field_name)

    @model_validator(mode="after")
    def _validate_unique_sources(self) -> ApiConfig:
        seen: set[str] = set()
        duplicates: list[str] = []
        for source in self.sources:
            if source.url in seen and source.url not in duplicates:
                duplicates.append(source.url)
            seen.add(source.url)
        if duplicates:
            raise ValueError(
                "duplicate finder API source URLs are not allowed: " + ", ".join(duplicates)
            )
        return self


class FinderConfig(BaseServiceConfig):
    """Finder service configuration.

    See Also:
        [Finder][bigbrotr.services.finder.Finder]: The service class
            that consumes this configuration.
        [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
            Base class providing ``interval``, ``max_consecutive_failures``, and ``metrics`` fields.
    """

    api: ApiConfig = Field(default_factory=ApiConfig, description="API fetching settings")
    events: EventsConfig = Field(
        default_factory=EventsConfig, description="Event scanning settings"
    )
