"""Ranker service configuration models."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from bigbrotr.core.base_service import BaseServiceConfig


_ALGORITHM_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_DEFAULT_ALGORITHM_ID = "global-pagerank"


def _reject_bool_alias(value: Any, field_name: str, expected_type: str) -> Any:
    """Reject bool aliases before Pydantic coerces them into numeric budgets."""
    if isinstance(value, bool):
        raise ValueError(f"{field_name}: expected {expected_type}, got bool")
    return value


def _require_bool(value: Any, field_name: str) -> bool:
    """Require canonical booleans for authored ranker config boundaries."""
    if not isinstance(value, bool):
        raise ValueError(f"{field_name}: expected bool, got {type(value).__name__}")
    return value


def _require_number(value: Any, field_name: str) -> int | float:
    """Require canonical numeric values for authored ranker config boundaries."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name}: expected number, got {type(value).__name__}")
    return cast("int | float", value)


class RankerStorageConfig(BaseModel):
    """DuckDB and checkpoint storage paths for the ranker."""

    model_config = ConfigDict(extra="forbid")

    path: Path = Field(
        default=Path("/app/data/ranker.duckdb"),
        description="Path to the private DuckDB database used by the ranker",
    )
    checkpoint_path: Path = Field(
        default=Path("/app/data/ranker.checkpoint.json"),
        description="Optional legacy JSON checkpoint import path for the follow-graph cursor",
    )


class RankerProcessingConfig(BaseModel):
    """Whole-cycle processing budgets for one ranker run."""

    model_config = ConfigDict(extra="forbid")

    max_duration: float | None = Field(
        default=None,
        ge=1.0,
        le=86_400.0,
        description="Maximum seconds for one ranker cycle (None = unbounded)",
    )

    @field_validator("max_duration", mode="before")
    @classmethod
    def require_numeric_max_duration(cls, value: Any, info: ValidationInfo) -> int | float | None:
        if value is None:
            return None
        return _require_number(value, str(info.field_name))


class RankerGraphConfig(BaseModel):
    """Graph-ranking parameters for the 30382 PageRank computation."""

    model_config = ConfigDict(extra="forbid")

    damping: float = Field(
        default=0.85,
        gt=0.0,
        lt=1.0,
        description="PageRank damping factor for the 30382 pubkey ranking",
    )
    iterations: int = Field(
        default=20,
        ge=1,
        le=10000,
        description="Maximum PageRank iterations for the 30382 pubkey ranking",
    )
    ignore_self_follows: bool = Field(
        default=True,
        description="Ignore self-follow edges when computing PageRank",
    )

    @field_validator("iterations", mode="before")
    @classmethod
    def reject_boolean_iterations(cls, value: Any, info: ValidationInfo) -> Any:
        return _reject_bool_alias(value, str(info.field_name), "integer")

    @field_validator("ignore_self_follows", mode="before")
    @classmethod
    def require_boolean_ignore_self_follows(cls, value: Any, info: ValidationInfo) -> bool:
        return _require_bool(value, str(info.field_name))


class RankerSyncConfig(BaseModel):
    """Incremental PostgreSQL -> DuckDB sync settings."""

    model_config = ConfigDict(extra="forbid")

    batch_size: int = Field(
        default=1000,
        ge=1,
        le=100000,
        description="Maximum changed followers to sync per batch",
    )
    max_batches: int | None = Field(
        default=None,
        ge=1,
        description="Maximum follow-graph sync batches per cycle (None = unbounded)",
    )
    max_followers_per_cycle: int | None = Field(
        default=None,
        ge=1,
        description="Maximum changed followers to sync per cycle (None = unbounded)",
    )

    @field_validator("batch_size", "max_batches", "max_followers_per_cycle", mode="before")
    @classmethod
    def reject_boolean_numerics(cls, value: Any, info: ValidationInfo) -> Any:
        return _reject_bool_alias(value, str(info.field_name), "integer")


class RankerFactsStageConfig(BaseModel):
    """PostgreSQL fact staging settings for non-user score subjects."""

    model_config = ConfigDict(extra="forbid")

    batch_size: int = Field(
        default=1000,
        ge=1,
        le=100000,
        description="Maximum non-user fact rows to fetch per staging batch",
    )
    max_event_rows: int | None = Field(
        default=None,
        ge=1,
        description="Maximum event fact rows to stage per cycle (None = unbounded)",
    )
    max_addressable_rows: int | None = Field(
        default=None,
        ge=1,
        description="Maximum addressable fact rows to stage per cycle (None = unbounded)",
    )
    max_identifier_rows: int | None = Field(
        default=None,
        ge=1,
        description="Maximum identifier fact rows to stage per cycle (None = unbounded)",
    )

    @field_validator(
        "batch_size",
        "max_event_rows",
        "max_addressable_rows",
        "max_identifier_rows",
        mode="before",
    )
    @classmethod
    def reject_boolean_numerics(cls, value: Any, info: ValidationInfo) -> Any:
        return _reject_bool_alias(value, str(info.field_name), "integer")


class RankerExportConfig(BaseModel):
    """PostgreSQL batch settings for public score export."""

    model_config = ConfigDict(extra="forbid")

    batch_size: int = Field(
        default=1000,
        ge=1,
        le=100000,
        description="Maximum rows to read or export per batch during ranking runs",
    )
    max_batches_per_subject: int | None = Field(
        default=None,
        ge=1,
        description="Maximum export batches per score subject per cycle (None = unbounded)",
    )

    @field_validator("batch_size", "max_batches_per_subject", mode="before")
    @classmethod
    def reject_boolean_numerics(cls, value: Any, info: ValidationInfo) -> Any:
        return _reject_bool_alias(value, str(info.field_name), "integer")


class RankerCleanupConfig(BaseModel):
    """DuckDB-local cleanup settings for ranker bookkeeping."""

    model_config = ConfigDict(extra="forbid")

    rank_runs_retention: int | None = Field(
        default=100,
        ge=1,
        description="Rank run records to keep in DuckDB (None = keep all)",
    )

    @field_validator("rank_runs_retention", mode="before")
    @classmethod
    def reject_boolean_rank_runs_retention(cls, value: Any, info: ValidationInfo) -> Any:
        return _reject_bool_alias(value, str(info.field_name), "integer")


class RankerConfig(BaseServiceConfig):
    """Configuration for the Ranker service."""

    model_config = ConfigDict(extra="forbid")

    algorithm_id: str = Field(
        default=_DEFAULT_ALGORITHM_ID,
        min_length=1,
        max_length=128,
        description="Stable identifier for the ranking algorithm namespace",
    )
    storage: RankerStorageConfig = Field(
        default_factory=RankerStorageConfig,
        description="DuckDB file locations for the private ranker store",
    )
    processing: RankerProcessingConfig = Field(
        default_factory=RankerProcessingConfig,
        description="Whole-cycle processing budgets",
    )
    graph: RankerGraphConfig = Field(
        default_factory=RankerGraphConfig,
        description="Graph-ranking settings for the 30382 PageRank pipeline",
    )
    sync: RankerSyncConfig = Field(
        default_factory=RankerSyncConfig,
        description="Incremental follow-graph sync settings",
    )
    facts_stage: RankerFactsStageConfig = Field(
        default_factory=RankerFactsStageConfig,
        description="Non-user fact staging settings",
    )
    export: RankerExportConfig = Field(
        default_factory=RankerExportConfig,
        description="Batch settings for PostgreSQL score export",
    )
    cleanup: RankerCleanupConfig = Field(
        default_factory=RankerCleanupConfig,
        description="Private DuckDB cleanup settings",
    )
    interval: float = Field(
        default=3600.0,
        ge=60.0,
        description="Target seconds between ranker sync cycles",
    )

    @field_validator("algorithm_id")
    @classmethod
    def algorithm_id_valid(cls, v: str) -> str:
        if not _ALGORITHM_ID_PATTERN.fullmatch(v):
            raise ValueError(
                "algorithm_id must match [a-z0-9]+(?:[._-][a-z0-9]+)* "
                "(lowercase letters, digits, '.', '_' and '-')"
            )
        return v
