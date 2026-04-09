"""Ranker service configuration models."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bigbrotr.core.base_service import BaseServiceConfig


_ALGORITHM_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_DEFAULT_ALGORITHM_ID = "global-pagerank-v1"


class RankerStorageConfig(BaseModel):
    """DuckDB and checkpoint storage paths for the ranker."""

    model_config = ConfigDict(extra="forbid")

    path: Path = Field(
        default=Path("/app/data/ranker.duckdb"),
        description="Path to the private DuckDB database used by the ranker",
    )
    checkpoint_path: Path = Field(
        default=Path("/app/data/ranker.checkpoint.json"),
        description="Path to the incremental sync checkpoint JSON file",
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


class RankerFactsStageConfig(BaseModel):
    """PostgreSQL fact staging settings for non-user rank subjects."""

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


class RankerExportConfig(BaseModel):
    """PostgreSQL export settings for rank snapshots and staged fact batches."""

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
        description="Maximum export batches per rank subject per cycle (None = unbounded)",
    )


class RankerCleanupConfig(BaseModel):
    """DuckDB-local cleanup settings for ranker bookkeeping."""

    model_config = ConfigDict(extra="forbid")

    rank_runs_retention: int | None = Field(
        default=100,
        ge=1,
        description="Rank run records to keep in DuckDB (None = keep all)",
    )


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
        description="Batch settings for PostgreSQL rank export",
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
