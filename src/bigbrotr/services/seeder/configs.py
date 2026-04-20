"""Seeder service configuration models.

See Also:
    [Seeder][bigbrotr.services.seeder.Seeder]: The service class
        that consumes these configurations.
    [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
        Base class providing ``interval``, ``max_consecutive_failures``,
        and ``metrics`` fields.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from bigbrotr.core.base_service import BaseServiceConfig


def _normalize_non_blank_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name}: expected string, got {type(value).__name__}")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _require_string_mapping_keys(value: Any, field_name: str) -> Any:
    if not isinstance(value, Mapping):
        return value
    for key in value:
        if not isinstance(key, str):
            raise ValueError(f"{field_name}: expected string keys, got {type(key).__name__}")
    return value


class SeedConfig(BaseModel):
    """Configuration for seed data source and insertion mode.

    See Also:
        [SeederConfig][bigbrotr.services.seeder.SeederConfig]: Parent
            config that embeds this model.
    """

    file_path: str = Field(
        default="static/seed_relays.txt", min_length=1, description="Seed file path"
    )
    to_validate: bool = Field(
        default=True,
        description="If True, add as candidates. If False, insert directly into relays.",
    )

    @model_validator(mode="before")
    @classmethod
    def _require_string_field_keys(cls, data: Any) -> Any:
        return _require_string_mapping_keys(data, "config")

    @field_validator("file_path", mode="before")
    @classmethod
    def _normalize_file_path(cls, value: Any, info: ValidationInfo) -> str:
        field_name = info.field_name or "value"
        return _normalize_non_blank_string(value, field_name)

    @field_validator("to_validate", mode="before")
    @classmethod
    def _require_boolean_to_validate(cls, value: Any, info: ValidationInfo) -> bool:
        field_name = info.field_name or "value"
        if not isinstance(value, bool):
            raise ValueError(f"{field_name}: expected bool, got {type(value).__name__}")
        return value


class SeederConfig(BaseServiceConfig):
    """Seeder service configuration.

    See Also:
        [Seeder][bigbrotr.services.seeder.Seeder]: The service class
            that consumes this configuration.
        [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
            Base class providing ``interval``, ``max_consecutive_failures``, and ``metrics`` fields.
    """

    seed: SeedConfig = Field(default_factory=SeedConfig, description="Seed data source settings")

    @model_validator(mode="before")
    @classmethod
    def _require_string_field_keys(cls, data: Any) -> Any:
        return _require_string_mapping_keys(data, "config")
